"""CCCD-free ESPHome transport tests, no actual BLE or network I/O."""
import asyncio
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from awox.esphome_transport import ESPHomeNoCCCDTransport
from awox.frames import NOTIFY_UUID, SERVICE_UUID
from awox.transport import GattChannel, GattOperation, OperationKind


class APIConnectionError(Exception):
    pass


class ConnectionNotEstablishedAPIError(APIConnectionError):
    pass


def mock_api_errors():
    api = ModuleType("aioesphomeapi.core")
    api.APIConnectionError = APIConnectionError
    api.ConnectionNotEstablishedAPIError = ConnectionNotEstablishedAPIError
    return patch.dict(sys.modules, {"aioesphomeapi.core": api})


class FakeBackend:
    def __init__(self):
        self._client = self
        self._address_as_int = 0x112233445566
        self._notify_cancels = {}
        self.events = []
        self.callback = None

    async def bluetooth_gatt_start_notify(self, address, handle, callback, timeout):
        self.events.append(('subscribe', address, handle))
        self.callback = callback
        async def stop():
            self.events.append(('stop', handle))
        def remove_callback():
            self.events.append(('remove_callback', handle))
        return stop, remove_callback


class FakeClient:
    def __init__(self, device, *, disconnected_callback):
        self.disconnected_callback = disconnected_callback
        self.is_connected = False
        self._backend = FakeBackend()
        notify = SimpleNamespace(uuid=NOTIFY_UUID, handle=0x12,
                                 properties=['notify', 'write', 'read'],
                                 descriptors=[SimpleNamespace(uuid='00002901-0000-1000-8000-00805f9b34fb')])
        self.notify_char = notify
        self.services = [SimpleNamespace(uuid=SERVICE_UUID, characteristics=[notify])]
        self.events = []

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    async def stop_notify(self, characteristic):
        self.events.append(('stop_notify', characteristic.handle))
        stop, remove_callback = self._backend._notify_cancels.pop(characteristic.handle)
        remove_callback()
        await stop()


def factory(*args, **kwargs):
    kwargs.pop('pair', None)
    kwargs.pop('_is_retry_client', None)
    return FakeClient(*args, **kwargs)


class TransportTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def fake_establish(factory, device, **kwargs):
            client = factory(device, disconnected_callback=kwargs['disconnected_callback'])
            await client.connect()
            return client
        self._connector_patch = patch.dict(sys.modules, {
            'bleak_retry_connector': SimpleNamespace(establish_connection=fake_establish)
        })
        self._connector_patch.start()
        self.addCleanup(self._connector_patch.stop)
        self.t = ESPHomeNoCCCDTransport(SimpleNamespace(address='11:22:33:44:55:66', name='EGLO'), client_factory=factory,
                                        backend_type=FakeBackend)
        self.ch = GattChannel(self.t)
        await self.ch.connect(lambda status: None)
        await self.t.discover_services()

    async def asyncTearDown(self):
        if self.ch.active:
            await self.ch.close()

    async def test_disconnect_after_confirmed_proxy_loss_releases_client(self):
        await self.check_confirmed_proxy_loss(ConnectionNotEstablishedAPIError, None)

    async def test_generic_api_error_releases_client_if_proxy_api_is_down(self):
        await self.check_confirmed_proxy_loss(APIConnectionError, False)

    async def check_confirmed_proxy_loss(self, error_type, api_connected):
        async def failed_disconnect():
            raise RuntimeError("BLE wrapper") from error_type()

        client = self.t._client
        client.is_connected = False
        client._backend.is_connected = False
        if api_connected is not None:
            client._backend._client = SimpleNamespace(is_connected=api_connected)
        client._connected_scanner = None
        with mock_api_errors():
            with patch.object(client, "disconnect", failed_disconnect):
                await self.ch.close()
        self.assertEqual(self.t._cleanup_clients, [])
        await self.ch.connect(lambda status: None)
        self.assertIsNot(self.t._client, client)

    async def test_proxy_error_during_disconnect_keeps_uncertain_client(self):
        client = self.t._client
        client._backend.is_connected = True
        async def failed_disconnect():
            client.is_connected = False
            client._backend.is_connected = False
            raise RuntimeError("BLE wrapper") from ConnectionNotEstablishedAPIError()

        with mock_api_errors():
            with patch.object(client, "disconnect", failed_disconnect):
                with self.assertRaisesRegex(RuntimeError, "BLE wrapper"):
                    await self.ch.close()
        self.assertIn(client, self.t._cleanup_clients)
        await self.t.disconnect()

    async def test_generic_api_error_keeps_client_if_proxy_api_is_still_up(self):
        async def failed_disconnect():
            raise RuntimeError("BLE wrapper") from APIConnectionError()

        client = self.t._client
        client.is_connected = False
        client._backend.is_connected = False
        client._backend._client = SimpleNamespace(is_connected=True)
        with mock_api_errors(), patch.object(client, "disconnect", failed_disconnect):
            with self.assertRaisesRegex(RuntimeError, "BLE wrapper"):
                await self.ch.close()
        self.assertIn(client, self.t._cleanup_clients)
        await self.t.disconnect()

    async def test_subscribe_notify_and_stop(self):
        packets = []
        await self.ch.execute(GattOperation(OperationKind.ENABLE_NOTIFY, NOTIFY_UUID),
                              packets.append)
        callback = self.t._client._backend.callback
        callback(0x12, b'\x80' + b'\x00' * 19)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(packets, [b'\x80' + b'\x00' * 19])
        self.assertIn(0x12, self.t._client._backend._notify_cancels)
        await self.ch.execute(GattOperation(OperationKind.DISABLE_NOTIFY, NOTIFY_UUID))
        self.assertEqual(self.t._client.events, [('stop_notify', 0x12)])
        self.assertEqual(self.t._client._backend.events[-2:],
                         [('remove_callback', 0x12), ('stop', 0x12)])
        callback(0x12, b'stale')
        await asyncio.sleep(0)
        self.assertEqual(len(packets), 1)

    async def test_reject_other_backend_without_registration(self):
        self.t._client._backend = object()
        with self.assertRaises(RuntimeError):
            await self.ch.execute(GattOperation(OperationKind.ENABLE_NOTIFY, NOTIFY_UUID),
                                  lambda x: None)

    async def test_cccd_refusal(self):
        self.t._client.notify_char.descriptors.append(
            SimpleNamespace(uuid='00002902-0000-1000-8000-00805f9b34fb'))
        with self.assertRaises(ValueError):
            await self.ch.execute(GattOperation(OperationKind.ENABLE_NOTIFY, NOTIFY_UUID),
                                  lambda x: None)

    async def test_old_callback_does_not_deliver_after_reconnect(self):
        events = []
        await self.ch.execute(GattOperation(OperationKind.ENABLE_NOTIFY, NOTIFY_UUID), events.append)
        callback = self.t._client._backend.callback
        await self.ch.close()
        await self.ch.connect(lambda status: None)
        await self.t.discover_services()
        callback(0x12, b'old')
        await asyncio.sleep(0)
        self.assertEqual(events, [])

    async def test_failed_stop_restores_owned_registration_for_explicit_retry(self):
        backend = self.t._client._backend
        client = self.t._client
        received = []
        await self.t.start_notify(NOTIFY_UUID, received.append)
        original_cleanup = backend._notify_cancels[0x12]
        callback = backend.callback
        original_stop = client.stop_notify
        stops = 0

        async def fail_after_pop(characteristic):
            nonlocal stops
            stops += 1
            backend._notify_cancels.pop(characteristic.handle)
            raise OSError('backend stop failed after removing registration')

        client.stop_notify = fail_after_pop
        with self.assertRaisesRegex(OSError, 'backend stop failed'):
            await self.t.stop_notify(NOTIFY_UUID)
        self.assertEqual(stops, 1)
        self.assertIs(backend._notify_cancels[0x12], original_cleanup)
        self.assertEqual(self.t._active_notify, 0x12)
        callback(0x12, b'old')
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(received, [])  # Epoch invalidated despite stop failure.

        client.stop_notify = original_stop
        await self.t.stop_notify(NOTIFY_UUID)
        self.assertEqual(backend._notify_cancels, {})
        self.assertIsNone(self.t._active_notify)
        self.assertEqual(backend.events[-2:], [('remove_callback', 0x12), ('stop', 0x12)])

    async def test_failed_stop_does_not_overwrite_competing_registration(self):
        backend = self.t._client._backend
        client = self.t._client
        await self.t.start_notify(NOTIFY_UUID, lambda _: None)
        original_stop = client.stop_notify
        calls = []

        async def foreign_stop():
            calls.append("stop")

        def foreign_remove():
            calls.append("remove")

        competitor = (foreign_stop, foreign_remove)

        async def fail_with_replacement(characteristic):
            backend._notify_cancels[characteristic.handle] = competitor
            raise OSError('another backend owner replaced the handle')

        client.stop_notify = fail_with_replacement
        with self.assertRaisesRegex(OSError, 'another backend owner'):
            await self.t.stop_notify(NOTIFY_UUID)
        self.assertIs(backend._notify_cancels[0x12], competitor)
        client.stop_notify = original_stop
        await self.t.stop_notify(NOTIFY_UUID)
        self.assertIs(backend._notify_cancels[0x12], competitor)
        self.assertEqual(calls, [])
        self.assertIsNone(self.t._active_notify)

    async def test_cannot_subscribe_twice(self):
        await self.ch.execute(GattOperation(OperationKind.ENABLE_NOTIFY, NOTIFY_UUID), lambda x: None)
        with self.assertRaises(RuntimeError):
            await self.t.start_notify(NOTIFY_UUID, lambda x: None)

    async def test_collision_removes_only_new_callback_and_preserves_competitor(self):
        backend = self.t._client._backend
        competitor = object()
        events, packets = [], []
        callbacks = []

        async def subscribe(address, handle, callback, timeout):
            callbacks.append(callback)
            backend._notify_cancels[handle] = competitor
            async def stop():
                events.append('stop')
            def remove_callback():
                events.append('remove_callback')
            return stop, remove_callback

        backend.bluetooth_gatt_start_notify = subscribe
        with self.assertRaisesRegex(RuntimeError, 'registry changed concurrently'):
            await self.t.start_notify(NOTIFY_UUID, packets.append)
        self.assertEqual(events, ['remove_callback'])
        self.assertIs(backend._notify_cancels[0x12], competitor)
        self.assertIsNone(self.t._active_notify)
        callbacks[0](0x12, b'late')
        await asyncio.sleep(0)
        self.assertEqual(packets, [])

    async def test_existing_registration_is_rejected_before_subscribe(self):
        backend = self.t._client._backend
        competitor = object()
        backend._notify_cancels[0x12] = competitor
        with self.assertRaisesRegex(RuntimeError, 'already registered in backend'):
            await self.t.start_notify(NOTIFY_UUID, lambda _: None)
        self.assertEqual(backend.events, [])
        self.assertIs(backend._notify_cancels[0x12], competitor)

    async def test_collision_allows_new_subscription_after_competitor_is_removed(self):
        backend = self.t._client._backend
        original = backend.bluetooth_gatt_start_notify

        async def subscribe(address, handle, callback, timeout):
            result = await original(address, handle, callback, timeout)
            backend._notify_cancels[handle] = object()
            return result

        backend.bluetooth_gatt_start_notify = subscribe
        with self.assertRaisesRegex(RuntimeError, 'registry changed concurrently'):
            await self.t.start_notify(NOTIFY_UUID, lambda _: None)
        backend._notify_cancels.clear()
        backend.bluetooth_gatt_start_notify = original
        await self.t.start_notify(NOTIFY_UUID, lambda _: None)
        await self.t.stop_notify(NOTIFY_UUID)
        self.assertNotIn(0x12, backend._notify_cancels)
