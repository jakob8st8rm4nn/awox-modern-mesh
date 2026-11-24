"""Backend contract checks: malformed returns must not become active state or data."""
import asyncio
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock, patch

from awox.esphome_transport import ESPHomeNoCCCDTransport
from awox.frames import NOTIFY_UUID
from awox.transport import GattChannel, GattOperation, OperationKind
from test_esphome_no_cccd_transport import FakeBackend, factory


class ReadBackend:
    async def connect(self, callback):
        pass

    async def disconnect(self):
        self.disconnected = True

    async def read(self, characteristic):
        return self.result


class ReadResultContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_channel_rejects_non_bytes_and_closes_invalid_backend(self):
        for value in (9, True, None, 'data', [1, 2]):
            with self.subTest(value=value):
                backend = ReadBackend()
                backend.result = value
                channel = GattChannel(backend)
                await channel.connect(lambda _: None)
                with self.assertRaisesRegex(TypeError, 'read result must be bytes-like'):
                    await channel.execute(GattOperation(OperationKind.READ, 'test'))
                self.assertFalse(channel.active)
                self.assertTrue(backend.disconnected)

    async def test_channel_preserves_bytes_like_payloads(self):
        for value in (b'', b'\x00\xff', bytearray(b'\x00\xff'), memoryview(b'\x00\xff')):
            with self.subTest(value=value):
                backend = ReadBackend()
                backend.result = value
                channel = GattChannel(backend)
                await channel.connect(lambda _: None)
                try:
                    result = await channel.execute(GattOperation(OperationKind.READ, 'test'))
                    self.assertIs(type(result), bytes)
                    self.assertEqual(result, bytes(value))
                    self.assertTrue(channel.active)
                finally:
                    await channel.close()


class SubscriptionResultContractTests(unittest.IsolatedAsyncioTestCase):
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
        self.backend = self.transport._client._backend

    async def asyncTearDown(self):
        await self.channel.close()

    async def test_invalid_subscription_results_are_not_published(self):
        original = self.backend.bluetooth_gatt_start_notify
        for value in (None, 7, (), (lambda: None,), (None, None),
                      (lambda: None, 1), (1, lambda: None), (1, 2, 3)):
            with self.subTest(value=value):
                async def subscribe(*args, **kwargs):
                    return value
                self.backend.bluetooth_gatt_start_notify = subscribe
                with self.assertRaisesRegex(RuntimeError, 'two cleanup callables'):
                    await self.transport.start_notify(NOTIFY_UUID, lambda _: None)
                self.assertIsNone(self.transport._active_notify)
                self.assertEqual(self.backend._notify_cancels, {})
        self.backend.bluetooth_gatt_start_notify = original
        await self.transport.start_notify(NOTIFY_UUID, lambda _: None)
        await self.transport.stop_notify(NOTIFY_UUID)
        self.assertEqual(self.backend._notify_cancels, {})

    async def test_invalid_subscription_closes_channel(self):
        self.backend.bluetooth_gatt_start_notify = AsyncMock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, 'two cleanup callables'):
            await self.channel.execute(
                GattOperation(OperationKind.ENABLE_NOTIFY, NOTIFY_UUID), lambda _: None)
        self.assertFalse(self.channel.active)
        self.assertIsNone(self.transport._active_notify)
        self.assertEqual(self.backend._notify_cancels, {})

    async def test_valid_list_cleanup_is_normalized_and_stops(self):
        original = self.backend.bluetooth_gatt_start_notify
        async def subscribe(*args, **kwargs):
            return list(await original(*args, **kwargs))
        self.backend.bluetooth_gatt_start_notify = subscribe
        await self.transport.start_notify(NOTIFY_UUID, lambda _: None)
        self.assertIs(type(self.backend._notify_cancels[0x12]), tuple)
        await self.transport.stop_notify(NOTIFY_UUID)
        self.assertEqual(self.backend.events[-2:], [('remove_callback', 0x12), ('stop', 0x12)])

    async def test_late_invalid_subscription_result_after_cancellation_is_ignored(self):
        entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def subscribe(*args, **kwargs):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            finished.set()
            return (None, None)
        self.backend.bluetooth_gatt_start_notify = subscribe
        errors = []
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _, context: errors.append(context))
        task = asyncio.create_task(self.transport.start_notify(NOTIFY_UUID, lambda _: None))
        try:
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            release.set()
            await finished.wait()
            for _ in range(5):
                await asyncio.sleep(0)
            self.assertIsNone(self.transport._active_notify)
            self.assertEqual(self.backend._notify_cancels, {})
            self.assertEqual(errors, [])
        finally:
            release.set()
            loop.set_exception_handler(previous)

    async def test_bleak_adapter_validates_before_bytes_conversion(self):
        client = self.transport._client
        for value in (9, True, None, 'data', [1, 2]):
            with self.subTest(value=value):
                client.read_gatt_char = AsyncMock(return_value=value)
                with self.assertRaisesRegex(TypeError, 'read result must be bytes-like'):
                    await self.transport.read(NOTIFY_UUID)
        for value in (b'', b'\x00\xff', bytearray(b'\x00\xff'), memoryview(b'\x00\xff')):
            client.read_gatt_char = AsyncMock(return_value=value)
            result = await self.transport.read(NOTIFY_UUID)
            self.assertIs(type(result), bytes)
            self.assertEqual(result, bytes(value))
