"""Old in-flight failures cannot close a replacement connection; fake I/O only."""
import asyncio
import gc
import unittest

from awox.transport import (ConnectionLost, GattChannel, GattOperation,
                            GattOperationTimeout, OperationKind)


class ReconnectingTransport:
    def __init__(self, cancelled_read_error=None):
        self.cancelled_read_error = cancelled_read_error
        self.read_started = asyncio.Event()
        self.callback = None
        self.disconnects = 0
        self.writes = []

    async def connect(self, disconnected):
        # No yield: a replacement connection can finish before the old
        # operation's cancellation/completion is processed by its waiter.
        self.callback = disconnected

    async def disconnect(self):
        self.disconnects += 1

    async def read(self, characteristic):
        self.read_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if self.cancelled_read_error is not None:
                raise self.cancelled_read_error('old backend operation completed after reconnect')
            raise

    async def write(self, characteristic, data, response):
        self.writes.append((characteristic, bytes(data), response))


class TransportGenerationRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def assert_cancelled_backend_is_observed(self, *, caller_cancel=False,
                                                 delayed=False, backend_error=OSError):
        release = asyncio.Event()
        backend = ReconnectingTransport(backend_error)
        original_read = backend.read
        if delayed:
            async def read(characteristic):
                try:
                    return await original_read(characteristic)
                except OSError:
                    await release.wait()
                    raise
            backend.read = read
        channel = GattChannel(backend, operation_timeout=.01)
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        unhandled = []
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
        await channel.connect(lambda _: None)
        operation = asyncio.create_task(channel.execute(
            GattOperation(OperationKind.READ, 'pair')))
        try:
            await backend.read_started.wait()
            backend_task = channel._operation
            if caller_cancel:
                operation.cancel()
            with self.assertRaises(asyncio.CancelledError if caller_cancel else GattOperationTimeout):
                await operation
            self.assertFalse(channel.active)
            self.assertEqual(backend.disconnects, 1)
            if delayed:
                self.assertFalse(backend_task.done())
                # The old worker must retire before this channel can reconnect.
                with self.assertRaisesRegex(ConnectionLost, 'GATT operation is still pending'):
                    await channel.connect(lambda _: None)
            release.set()
            await asyncio.wait({backend_task}, timeout=.5)
            await asyncio.sleep(0)
            del backend_task
            del operation
            gc.collect()
            await asyncio.sleep(0)
            self.assertEqual(unhandled, [])
            if delayed:
                await channel.connect(lambda _: None)
                self.assertTrue(channel.active)
                await channel.execute(GattOperation(OperationKind.WRITE, 'command', b'new'))
                self.assertEqual(backend.writes, [('command', b'new', True)])
        finally:
            release.set()
            await channel.close()
            loop.set_exception_handler(previous_handler)

    async def test_watchdog_observes_error_raised_during_backend_cancellation(self):
        await self.assert_cancelled_backend_is_observed()

    async def test_caller_cancellation_observes_backend_error(self):
        await self.assert_cancelled_backend_is_observed(caller_cancel=True)

    async def test_late_backend_error_is_observed_before_allowing_reconnect(self):
        await self.assert_cancelled_backend_is_observed(delayed=True)

    async def test_clean_backend_cancellation_has_no_unhandled_exception(self):
        await self.assert_cancelled_backend_is_observed(backend_error=None)

    async def assert_replacement_survives(self, backend_error, expected_error):
        backend = ReconnectingTransport(backend_error)
        channel = GattChannel(backend)
        await channel.connect(lambda status: None)
        old_read = asyncio.create_task(channel.execute(
            GattOperation(OperationKind.READ, 'pair')))
        try:
            await asyncio.wait_for(backend.read_started.wait(), 1)
            backend_task = channel._operation
            backend.callback(8)
            with self.assertRaisesRegex(ConnectionLost, 'GATT operation is still pending'):
                await channel.connect(lambda status: None)
            await asyncio.wait({backend_task}, timeout=.5)
            self.assertTrue(backend_task.done())
            await channel.connect(lambda status: None)
            replacement_generation = channel.generation
            self.assertTrue(channel.active)

            with self.assertRaises(expected_error):
                await old_read

            self.assertTrue(channel.active)
            self.assertEqual(channel.generation, replacement_generation)
            self.assertEqual(backend.disconnects, 0)
            await channel.execute(GattOperation(OperationKind.WRITE, 'command', b'new'))
            self.assertEqual(backend.writes, [('command', b'new', True)])
        finally:
            if not old_read.done():
                old_read.cancel()
                try:
                    await old_read
                except (asyncio.CancelledError, Exception):
                    pass
            await channel.close()

    async def test_cancelled_old_read_cannot_close_replacement_connection(self):
        await self.assert_replacement_survives(None, ConnectionLost)

    async def test_old_backend_failure_cannot_close_replacement_connection(self):
        await self.assert_replacement_survives(OSError, OSError)

    async def test_old_backend_timeout_cannot_close_replacement_connection(self):
        await self.assert_replacement_survives(asyncio.TimeoutError, GattOperationTimeout)
