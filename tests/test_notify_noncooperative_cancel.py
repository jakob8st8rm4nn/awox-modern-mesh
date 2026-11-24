"""Regression: a cancelled ESPHome 1911 registration must not be revived.

Uses in-memory async backends. No BLE access or credentials are involved.
"""
import asyncio
import unittest
from types import SimpleNamespace

from awox.esphome_transport import ESPHomeNoCCCDTransport
from awox.frames import NOTIFY_UUID, SERVICE_UUID


class SlowBackend:
    def __init__(self):
        self._client = self
        self._address_as_int = 1
        self._notify_cancels = {}
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancel_seen = asyncio.Event()
        self.callbacks = []
        self.immediate_replacement = False
        self.removes = 0
        self.stops = 0

    async def bluetooth_gatt_start_notify(self, address, handle, callback, timeout):
        self.callbacks.append(callback)
        self.started.set()
        if len(self.callbacks) == 1 or not self.immediate_replacement:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                # A real backend may ignore cancellation until GATT completes.
                self.cancel_seen.set()
                await self.release.wait()

        async def stop():
            self.stops += 1

        def remove():
            self.removes += 1

        return stop, remove


class FakeClient:
    def __init__(self):
        self._backend = SlowBackend()
        self.is_connected = True
        self.characteristic = SimpleNamespace(
            uuid=NOTIFY_UUID, handle=18, properties=['notify'], descriptors=[])
        self.services = [SimpleNamespace(
            uuid=SERVICE_UUID, characteristics=[self.characteristic])]


class NonCooperativeNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = FakeClient()
        self.transport = ESPHomeNoCCCDTransport(
            SimpleNamespace(address='test'), backend_type=SlowBackend)
        self.transport._client = self.client
        self.transport._characteristics[NOTIFY_UUID] = self.client.characteristic

    async def _wait_for_cleanup(self, *, expect_stop):
        backend = self.client._backend
        for _ in range(40):
            if backend.removes and (not expect_stop or backend.stops):
                break
            await asyncio.sleep(0)
        self.assertEqual(backend.removes, 1)
        self.assertEqual(backend.stops, int(expect_stop))

    async def test_cancelled_subscription_must_not_become_active(self):
        delivered = []
        task = asyncio.create_task(self.transport.start_notify(
            NOTIFY_UUID, delivered.append))
        backend = self.client._backend
        try:
            await asyncio.wait_for(backend.started.wait(), 1)
            task.cancel()
            await asyncio.sleep(0)
            backend.release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
            await self._wait_for_cleanup(expect_stop=True)
            self.assertIsNone(self.transport._active_notify)
            backend.callbacks[0](18, b'late')
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual(delivered, [])
        finally:
            backend.release.set()

    async def test_late_old_completion_cannot_stop_new_subscription(self):
        backend = self.client._backend
        backend.immediate_replacement = True
        old = asyncio.create_task(self.transport.start_notify(NOTIFY_UUID, lambda _: None))
        try:
            await asyncio.wait_for(backend.started.wait(), 1)
            old.cancel()
            await asyncio.sleep(0)
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(old, 1)
            # The first backend request remains unfinished. A subsequent
            # registration can succeed without waiting for its stale result.
            received = []
            await self.transport.start_notify(NOTIFY_UUID, received.append)
            self.assertEqual(self.transport._active_notify, 18)
            backend.release.set()
            await self._wait_for_cleanup(expect_stop=False)
            self.assertIn(18, backend._notify_cancels)
            self.assertEqual(self.transport._active_notify, 18)
            backend.callbacks[0](18, b'old')
            backend.callbacks[1](18, b'new')
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual(received, [b'new'])
        finally:
            backend.release.set()

    async def test_timeout_is_enforced_even_if_backend_suppresses_cancellation(self):
        # start_notify uses the supplied subscribe timeout + 2 s of margin.
        self.transport._subscribe_timeout = 0.02
        backend = self.client._backend
        task = asyncio.create_task(self.transport.start_notify(NOTIFY_UUID, lambda _: None))
        try:
            await asyncio.wait_for(backend.started.wait(), 1)
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(task, 2.7)
            self.assertTrue(backend.cancel_seen.is_set())
            self.assertIsNone(self.transport._active_notify)
        finally:
            backend.release.set()
            if not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
        await self._wait_for_cleanup(expect_stop=True)
        self.assertIsNone(self.transport._active_notify)


if __name__ == '__main__':
    unittest.main()
