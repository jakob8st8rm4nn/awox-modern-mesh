"""Bound caller waits without allowing a pending old disconnect to close a new link."""
import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from awox.esphome_transport import ESPHomeNoCCCDTransport
from awox.transport import (ConnectionLost, GattChannel, GattOperation,
                            GattOperationTimeout, GattQueue, OperationKind)


class UncooperativeDisconnect:
    def __init__(self):
        self.release = asyncio.Event()
        self.disconnect_started = asyncio.Event()
        self.write_started = asyncio.Event()
        self.disconnects = 0
        self.connects = 0
        self.writes = []
        self.stall_write = True
        self.late_error = None

    async def connect(self, callback):
        self.connects += 1

    async def write(self, characteristic, data, response):
        self.writes.append(bytes(data))
        self.write_started.set()
        if self.stall_write:
            self.stall_write = False
            await asyncio.Event().wait()

    async def disconnect(self):
        self.disconnects += 1
        self.disconnect_started.set()
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                pass  # deliberately broken backend: finishes only when released
        if self.late_error:
            raise self.late_error


class BoundedCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = UncooperativeDisconnect()
        self.channel = GattChannel(self.backend, operation_timeout=.01)
        self.tasks = []
        await self.channel.connect(lambda status: None)

    async def asyncTearDown(self):
        self.backend.release.set()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        closing = getattr(self.channel, '_closing_task', None)
        if closing is not None:
            await asyncio.gather(closing, return_exceptions=True)
        try:
            await self.channel.close()
        except OSError:
            pass

    def start(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task

    async def assert_returns_without_releasing_backend(self, task, error):
        await asyncio.wait_for(self.backend.disconnect_started.wait(), .5)
        done, _ = await asyncio.wait({task}, timeout=.2)
        self.assertIn(task, done, 'caller must not wait for an uncooperative disconnect')
        with self.assertRaises(error):
            task.result()
        self.assertFalse(self.channel.active)

    async def test_operation_watchdog_returns_even_when_disconnect_ignores_cancel(self):
        operation = self.start(self.channel.execute(GattOperation(OperationKind.WRITE, '1912', b'once')))
        await self.assert_returns_without_releasing_backend(operation, GattOperationTimeout)
        self.assertEqual(self.backend.writes, [b'once'])
        self.assertEqual(self.backend.disconnects, 1)

    async def test_explicit_close_times_out_and_repeated_close_shares_pending_cleanup(self):
        first = self.start(self.channel.close())
        await self.assert_returns_without_releasing_backend(first, asyncio.TimeoutError)
        second = self.start(self.channel.close())
        await self.assert_returns_without_releasing_backend(second, asyncio.TimeoutError)
        self.assertEqual(self.backend.disconnects, 1)

    async def test_connect_is_refused_until_old_disconnect_really_finishes(self):
        closing = self.start(self.channel.close())
        await self.assert_returns_without_releasing_backend(closing, asyncio.TimeoutError)
        with self.assertRaises(ConnectionLost):
            await self.channel.connect(lambda status: None)
        self.assertEqual(self.backend.connects, 1)
        self.backend.release.set()
        await asyncio.wait_for(asyncio.shield(self.channel._closing_task), .5)
        await self.channel.connect(lambda status: None)
        self.backend.stall_write = False
        await self.channel.execute(GattOperation(OperationKind.WRITE, '1912', b'new'))
        self.assertTrue(self.channel.active)
        self.assertEqual(self.backend.connects, 2)
        self.assertEqual(self.backend.writes, [b'new'])

    async def test_caller_cancellation_remains_cancellation_after_bounded_cleanup(self):
        operation = self.start(self.channel.execute(GattOperation(OperationKind.WRITE, '1912', b'once')))
        await asyncio.wait_for(self.backend.write_started.wait(), .5)
        operation.cancel()
        await self.assert_returns_without_releasing_backend(operation, asyncio.CancelledError)

    async def test_late_cleanup_exception_is_observed_without_loop_error(self):
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        unhandled = []
        loop.set_exception_handler(lambda loop, context: unhandled.append(context))
        self.backend.late_error = OSError('late cleanup failure')
        try:
            closing = self.start(self.channel.close())
            await self.assert_returns_without_releasing_backend(closing, asyncio.TimeoutError)
            self.backend.release.set()
            await asyncio.wait({self.channel._closing_task}, timeout=.5)
            await asyncio.sleep(0)
            self.assertEqual(unhandled, [])
            self.assertIsInstance(self.channel._closing_task.exception(), OSError)
        finally:
            loop.set_exception_handler(previous)

    async def test_explicit_close_cancellation_returns_without_waiting_for_backend(self):
        closing = self.start(self.channel.close())
        await asyncio.wait_for(self.backend.disconnect_started.wait(), .5)
        closing.cancel()
        done, _ = await asyncio.wait({closing}, timeout=.2)
        self.assertIn(closing, done)
        with self.assertRaises(asyncio.CancelledError):
            closing.result()
        with self.assertRaises(ConnectionLost):
            await self.channel.connect(lambda status: None)
        self.assertFalse(self.channel.active)

    async def test_cancelled_backend_task_is_not_reported_as_caller_cancellation(self):
        backend = SimpleNamespace(disconnect=AsyncMock(side_effect=asyncio.CancelledError))
        channel = GattChannel(backend, operation_timeout=.01)
        with self.assertRaises(ConnectionLost):
            await channel.close()
        self.assertFalse(channel.active)

    async def test_cancelling_one_close_waiter_does_not_cancel_shared_disconnect(self):
        self.channel.operation_timeout = .5
        first = self.start(self.channel.close())
        await asyncio.wait_for(self.backend.disconnect_started.wait(), .5)
        second = self.start(self.channel.close())
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertFalse(second.done())
        self.backend.release.set()
        await asyncio.wait_for(second, .5)
        self.assertEqual(self.backend.disconnects, 1)

    async def test_other_device_can_use_shared_queue_after_watchdog_cleanup_timeout(self):
        queue = GattQueue()
        self.channel.queue = queue
        other_backend = UncooperativeDisconnect()
        other_backend.stall_write = False
        other_backend.release.set()
        other = GattChannel(other_backend, queue=queue, operation_timeout=.01)
        await other.connect(lambda status: None)
        try:
            operation = self.start(self.channel.execute(GattOperation(OperationKind.WRITE, '1912', b'old')))
            await self.assert_returns_without_releasing_backend(operation, GattOperationTimeout)
            await asyncio.wait_for(other.execute(GattOperation(OperationKind.WRITE, '1912', b'other')), .5)
            self.assertEqual(other_backend.writes, [b'other'])
        finally:
            await other.close()


class FailedCleanupReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def check_failed_cleanup(self, failure):
        backend = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(side_effect=failure))
        channel = GattChannel(backend, operation_timeout=.01)
        await channel.connect(lambda _: None)
        expected = ConnectionLost if isinstance(failure, asyncio.CancelledError) else OSError
        with self.assertRaises(expected):
            await channel.close()
        with self.assertRaises(ConnectionLost):
            await channel.connect(lambda _: None)
        self.assertEqual(backend.connect.await_count, 1)
        self.assertFalse(channel.active)

        # Only an explicitly requested, successful cleanup permits reuse.
        backend.disconnect.side_effect = None
        await channel.close()
        await channel.connect(lambda _: None)
        self.assertTrue(channel.active)
        self.assertEqual(backend.connect.await_count, 2)
        await channel.close()

    async def test_disconnect_error_blocks_reconnect_until_explicit_cleanup_succeeds(self):
        await self.check_failed_cleanup(OSError('disconnect not confirmed'))

    async def test_cancelled_disconnect_blocks_reconnect_until_explicit_cleanup_succeeds(self):
        await self.check_failed_cleanup(asyncio.CancelledError())

    async def test_watchdog_cancelled_disconnect_stays_blocked_after_task_finishes(self):
        started = asyncio.Event()
        async def disconnect():
            started.set()
            await asyncio.Event().wait()
        backend = SimpleNamespace(connect=AsyncMock(), disconnect=disconnect)
        channel = GattChannel(backend, operation_timeout=.01)
        await channel.connect(lambda _: None)
        with self.assertRaises(asyncio.TimeoutError):
            await channel.close()
        self.assertTrue(started.is_set())
        await asyncio.gather(channel._closing_task, return_exceptions=True)
        self.assertTrue(channel._closing_task.cancelled())
        with self.assertRaises(ConnectionLost):
            await channel.connect(lambda _: None)
        self.assertEqual(backend.connect.await_count, 1)
        backend.disconnect = AsyncMock()
        await channel.close()
        await channel.connect(lambda _: None)
        await channel.close()

    async def test_late_disconnect_error_does_not_unlock_reconnect(self):
        backend = UncooperativeDisconnect()
        backend.late_error = OSError('late disconnect failure')
        channel = GattChannel(backend, operation_timeout=.01)
        await channel.connect(lambda _: None)
        try:
            with self.assertRaises(asyncio.TimeoutError):
                await channel.close()
            backend.release.set()
            await asyncio.gather(channel._closing_task, return_exceptions=True)
            with self.assertRaises(ConnectionLost):
                await channel.connect(lambda _: None)
            self.assertEqual(backend.connects, 1)
        finally:
            backend.release.set()
            backend.late_error = None
            await channel.close()

    async def test_cancelled_close_waiter_does_not_poison_successful_cleanup(self):
        backend = UncooperativeDisconnect()
        channel = GattChannel(backend, operation_timeout=.5)
        await channel.connect(lambda _: None)
        close = asyncio.create_task(channel.close())
        await backend.disconnect_started.wait()
        close.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await close
        backend.release.set()
        await channel._closing_task
        await channel.connect(lambda _: None)
        self.assertTrue(channel.active)
        await channel.close()

    async def check_adapter_cleanup(self, failure, *, replacement=False):
        class Backend: pass
        old = SimpleNamespace(_backend=Backend(), is_connected=True,
                              disconnect=AsyncMock(side_effect=failure))
        new = SimpleNamespace(_backend=Backend(), is_connected=True, disconnect=AsyncMock())
        establish = AsyncMock(side_effect=(old, new))
        transport = ESPHomeNoCCCDTransport(
            SimpleNamespace(address='02:00:00:00:00:01'), client_factory=object,
            backend_type=Backend)
        channel = GattChannel(transport, operation_timeout=.01)
        with patch('awox.esphome_transport._ESPHomeBleakTransportBase._open_client', side_effect=establish):
            await channel.connect(lambda _: None)
            if replacement:
                # The adapter also preserves a client when cleanup before a
                # replacement connect fails, without creating a second client.
                with self.assertRaises(OSError):
                    await transport.connect(lambda _: None)
                self.assertEqual(establish.await_count, 1)
            else:
                expected = ConnectionLost if isinstance(failure, asyncio.CancelledError) else OSError
                with self.assertRaises(expected):
                    await channel.close()
                with self.assertRaises(ConnectionLost):
                    await channel.connect(lambda _: None)
            self.assertIs(transport._client, old)
            old.disconnect.side_effect = None
            await channel.close()
            self.assertEqual(old.disconnect.await_count, 2)
            self.assertIsNone(transport._client)
            await channel.connect(lambda _: None)
            self.assertIs(transport._client, new)
            await channel.close()

    async def test_esphome_failed_disconnect_retains_client_for_explicit_cleanup(self):
        await self.check_adapter_cleanup(OSError('disconnect failed'))

    async def test_esphome_cancelled_disconnect_retains_client_for_explicit_cleanup(self):
        await self.check_adapter_cleanup(asyncio.CancelledError())

    async def test_esphome_failed_replacement_cleanup_retains_old_client(self):
        await self.check_adapter_cleanup(OSError('replacement cleanup failed'), replacement=True)

    async def test_esphome_pending_disconnect_blocks_replacement_until_cleanup_succeeds(self):
        class Backend: pass
        started, release = asyncio.Event(), asyncio.Event()
        async def fail_late():
            started.set()
            await release.wait()
            raise OSError('old cleanup failed late')
        old = SimpleNamespace(_backend=Backend(), is_connected=True, disconnect=fail_late)
        new = SimpleNamespace(_backend=Backend(), is_connected=True, disconnect=AsyncMock())
        establish = AsyncMock(side_effect=(old, new))
        transport = ESPHomeNoCCCDTransport(
            SimpleNamespace(address='02:00:00:00:00:01'), client_factory=object,
            backend_type=Backend)
        with patch('awox.esphome_transport._ESPHomeBleakTransportBase._open_client', side_effect=establish):
            await transport.connect(lambda _: None)
            closing = asyncio.create_task(transport.disconnect())
            try:
                await started.wait()
                with self.assertRaisesRegex(ConnectionLost, 'cleanup is still pending'):
                    await transport.connect(lambda _: None)
                self.assertEqual(establish.await_count, 1)
                release.set()
                with self.assertRaises(OSError):
                    await closing
                # The failed old client remains owned; an explicit later
                # connect must close it before establishing its replacement.
                old.disconnect = AsyncMock()
                await transport.connect(lambda _: None)
                old.disconnect.assert_awaited_once()
                self.assertIs(transport._client, new)
            finally:
                release.set()
                await asyncio.gather(closing, return_exceptions=True)
                await transport.disconnect()
