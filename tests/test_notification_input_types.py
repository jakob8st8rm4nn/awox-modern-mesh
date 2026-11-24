"""Malformed notification events are dropped without affecting later valid data."""
import asyncio
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from awox.esphome_transport import ESPHomeNoCCCDTransport
from awox.frames import NOTIFY_UUID
from awox.transport import GattChannel, GattOperation, OperationKind
from test_esphome_no_cccd_transport import FakeBackend, factory


def malformed_values():
    released = memoryview(b'abc')
    released.release()
    return (20, -1, True, 20.0, None, 'data', [1, 2], {}, object(), released)


class NotificationBackend:
    async def connect(self, callback):
        pass

    async def disconnect(self):
        pass

    async def start_notify(self, characteristic, callback):
        self.callback = callback

    async def stop_notify(self, characteristic):
        pass


class ChannelNotificationTypeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = NotificationBackend()
        self.channel = GattChannel(self.backend)
        self.received = []
        await self.channel.connect(lambda _: None)
        await self.channel.execute(GattOperation(OperationKind.ENABLE_NOTIFY, NOTIFY_UUID),
                                   self.received.append)

    async def asyncTearDown(self):
        await self.channel.close()

    async def test_malformed_events_are_dropped_and_reception_continues(self):
        for value in malformed_values():
            self.backend.callback(value)
        self.assertEqual(self.received, [])
        self.assertTrue(self.channel.active)
        self.backend.callback(b'valid')
        self.assertEqual(self.received, [b'valid'])

    async def test_buffer_types_and_empty_payload_remain_valid(self):
        for value in (b'', b'abc', bytearray(b'abc'), memoryview(b'abc')):
            self.backend.callback(value)
        self.assertEqual(self.received, [b'', b'abc', b'abc', b'abc'])
        self.assertTrue(all(type(value) is bytes for value in self.received))

    async def test_old_registration_cannot_deliver_after_stop(self):
        callback = self.backend.callback
        await self.channel.execute(GattOperation(OperationKind.DISABLE_NOTIFY, NOTIFY_UUID))
        callback(20)
        callback(b'stale')
        self.assertEqual(self.received, [])


class ESPHomeNotificationTypeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def establish(client_factory, device, **kwargs):
            client = client_factory(device, disconnected_callback=kwargs['disconnected_callback'])
            await client.connect()
            return client
        patcher = patch.dict(sys.modules, {
            'bleak_retry_connector': SimpleNamespace(establish_connection=establish)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.transport = ESPHomeNoCCCDTransport(
            SimpleNamespace(address='11:22:33:44:55:66', name='test'),
            client_factory=factory, backend_type=FakeBackend)
        self.channel = GattChannel(self.transport)
        await self.channel.connect(lambda _: None)
        await self.transport.discover_services()
        self.received = []
        self.loop_errors = []
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _, context: self.loop_errors.append(context))
        self.addCleanup(loop.set_exception_handler, previous)

    async def asyncTearDown(self):
        await self.channel.close()
        self.assertEqual(self.loop_errors, [])

    async def test_direct_adapter_discards_malformed_events(self):
        await self.transport.start_notify(NOTIFY_UUID, self.received.append)
        callback = self.transport._client._backend.callback
        for value in malformed_values():
            callback(0x12, value)
        await asyncio.sleep(0)
        self.assertEqual(self.received, [])
        callback(0x12, b'valid')
        await asyncio.sleep(0)
        self.assertEqual(self.received, [b'valid'])
        self.assertTrue(self.channel.active)

    async def test_end_to_end_buffers_are_copied_before_dispatch(self):
        await self.channel.execute(GattOperation(OperationKind.ENABLE_NOTIFY, NOTIFY_UUID),
                                   self.received.append)
        callback = self.transport._client._backend.callback
        mutable = bytearray(b'abc')
        callback(0x12, mutable)
        mutable[:] = b'xyz'
        callback(0x12, memoryview(b'view'))
        callback(0x12, b'')
        callback(0x12, 20)
        await asyncio.sleep(0)
        self.assertEqual(self.received, [b'abc', b'view', b''])
        self.assertTrue(all(type(value) is bytes for value in self.received))

    async def test_stopped_adapter_does_not_dispatch_queued_or_stale_events(self):
        await self.transport.start_notify(NOTIFY_UUID, self.received.append)
        callback = self.transport._client._backend.callback
        callback(0x12, b'queued')
        await self.transport.stop_notify(NOTIFY_UUID)
        callback(0x12, 20)
        callback(0x12, b'stale')
        await asyncio.sleep(0)
        self.assertEqual(self.received, [])
