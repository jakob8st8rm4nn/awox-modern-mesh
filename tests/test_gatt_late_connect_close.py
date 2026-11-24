"""Late generic connects and repeated closes share one channel cleanup owner."""
import asyncio
import unittest

from awox.transport import ConnectionLost, GattChannel


class Backend:
    def __init__(self):
        self.connected = False
        self.connects = 0
        self.disconnects = 0
        self.callbacks = []
        self.connect_entered = asyncio.Event()
        self.connect_release = asyncio.Event()
        self.connect_release.set()
        self.disconnect_entered = asyncio.Event()
        self.disconnect_release = asyncio.Event()
        self.disconnect_release.set()
        self.fail_connect = False
        self.fail_disconnect = False
        self.strict_disconnect = False

    async def wait(self, event):
        while not event.is_set():
            try:
                await event.wait()
            except asyncio.CancelledError:
                pass  # Deliberately non-cooperative backend under test.

    async def connect(self, callback):
        self.connects += 1
        self.callbacks.append(callback)
        self.connect_entered.set()
        await self.wait(self.connect_release)
        self.connected = True
        if self.fail_connect:
            raise OSError('late connection failure')

    async def disconnect(self):
        self.disconnects += 1
        self.disconnect_entered.set()
        await self.wait(self.disconnect_release)
        if self.fail_disconnect:
            raise OSError('disconnect failed')
        if self.strict_disconnect and not self.connected:
            raise RuntimeError('already disconnected')
        self.connected = False


class LateConnectAndIdempotentCloseTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_close_is_idempotent_for_strict_backend(self):
        backend = Backend()
        backend.strict_disconnect = True
        channel = GattChannel(backend)
        await channel.connect(lambda _: None)
        await channel.close()
        channel.invalidate()  # Local invalidation does not create a new link.
        await channel.close()
        self.assertEqual(backend.disconnects, 1)
        self.assertFalse(channel.active)
        await channel.connect(lambda _: None)
        self.assertTrue(channel.active)
        await channel.close()
        self.assertEqual(backend.disconnects, 2)

    async def test_late_success_is_disconnected_before_replacement(self):
        backend = Backend()
        backend.connect_release.clear()
        channel = GattChannel(backend)
        old = asyncio.create_task(channel.connect(lambda _: None))
        await backend.connect_entered.wait()
        await channel.close()
        with self.assertRaisesRegex(ConnectionLost, 'already pending'):
            await channel.connect(lambda _: None)
        self.assertEqual(backend.connects, 1)
        backend.strict_disconnect = True
        backend.connect_release.set()
        with self.assertRaises(ConnectionLost):
            await old
        self.assertFalse(backend.connected)
        self.assertFalse(channel.active)
        self.assertEqual(backend.disconnects, 2)
        await channel.close()
        self.assertEqual(backend.disconnects, 2)
        await channel.connect(lambda _: None)
        backend.callbacks[0](8)
        self.assertTrue(channel.active)
        self.assertTrue(backend.connected)
        await channel.close()

    async def test_late_error_with_partial_connection_is_cleaned(self):
        backend = Backend()
        backend.fail_connect = True
        backend.connect_release.clear()
        channel = GattChannel(backend)
        old = asyncio.create_task(channel.connect(lambda _: None))
        await backend.connect_entered.wait()
        await channel.close()
        backend.connect_release.set()
        with self.assertRaisesRegex(OSError, 'late connection failure'):
            await old
        self.assertFalse(backend.connected)
        self.assertEqual(backend.disconnects, 2)

    async def test_failed_late_cleanup_blocks_reconnect_until_explicit_retry(self):
        backend = Backend()
        backend.connect_release.clear()
        channel = GattChannel(backend)
        old = asyncio.create_task(channel.connect(lambda _: None))
        await backend.connect_entered.wait()
        await channel.close()
        backend.fail_disconnect = True
        backend.connect_release.set()
        with self.assertRaises(ConnectionLost):
            await old
        self.assertTrue(backend.connected)
        with self.assertRaisesRegex(ConnectionLost, 'did not complete successfully'):
            await channel.connect(lambda _: None)
        backend.fail_disconnect = False
        await channel.close()
        self.assertFalse(backend.connected)
        await channel.connect(lambda _: None)
        await channel.close()

    async def test_disconnect_finishing_after_late_connect_is_shared(self):
        backend = Backend()
        backend.connect_release.clear()
        backend.disconnect_release.clear()
        channel = GattChannel(backend)
        old = asyncio.create_task(channel.connect(lambda _: None))
        await backend.connect_entered.wait()
        closing = asyncio.create_task(channel.close())
        await backend.disconnect_entered.wait()
        backend.connect_release.set()
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertTrue(backend.connected)
        self.assertFalse(old.done())
        self.assertEqual(backend.disconnects, 1)
        backend.disconnect_release.set()
        await closing
        with self.assertRaises(ConnectionLost):
            await old
        self.assertFalse(backend.connected)
        await channel.close()
        self.assertEqual(backend.disconnects, 1)

    async def test_cancelled_close_waiter_does_not_discard_late_cleanup(self):
        backend = Backend()
        backend.connect_release.clear()
        backend.disconnect_release.clear()
        channel = GattChannel(backend)
        old = asyncio.create_task(channel.connect(lambda _: None))
        await backend.connect_entered.wait()
        closing = asyncio.create_task(channel.close())
        await backend.disconnect_entered.wait()
        closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closing
        backend.connect_release.set()
        backend.disconnect_release.set()
        with self.assertRaises(ConnectionLost):
            await old
        self.assertFalse(backend.connected)
        await channel.close()
        self.assertEqual(backend.disconnects, 1)

    async def test_timed_out_pending_disconnect_remains_guarded(self):
        backend = Backend()
        backend.connect_release.clear()
        backend.disconnect_release.clear()
        channel = GattChannel(backend, operation_timeout=0.01)
        old = asyncio.create_task(channel.connect(lambda _: None))
        await backend.connect_entered.wait()
        try:
            with self.assertRaises(TimeoutError):
                await channel.close()
            backend.connect_release.set()
            with self.assertRaises(ConnectionLost):
                await old
            with self.assertRaises(ConnectionLost):
                await channel.connect(lambda _: None)
        finally:
            backend.connect_release.set()
            backend.disconnect_release.set()
            await asyncio.gather(old, return_exceptions=True)
            await channel._closing_task
        self.assertFalse(backend.connected)
        await channel.connect(lambda _: None)
        await channel.close()
