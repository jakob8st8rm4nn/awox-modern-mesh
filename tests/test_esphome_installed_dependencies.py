"""Smoke-check real optional ESPHome packages without a proxy or BLE device.

Offline test runs skip these checks if [esphome] is not installed. A separate
CI job installs [esphome] and runs this test against actual installed packages.
This is not an end-to-end hardware or APK compatibility test.
"""

import asyncio
import importlib.util
import inspect
import unittest
from importlib.metadata import version
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


@unittest.skipUnless(
    all(importlib.util.find_spec(name) is not None for name in
        ("bleak_esphome", "habluetooth", "bleak", "aioesphomeapi")),
    "Optional ESPHome packages are not installed; use pip install '.[esphome]'",
)
class InstalledESPHomeInterfaces(unittest.TestCase):
    def test_required_proxy_and_client_entrypoints(self):
        from bleak_esphome import APIConnectionManager
        from bleak_esphome.backend.client import ESPHomeClient
        from habluetooth import BluetoothManager, HaBleakClientWrapper
        import habluetooth

        self.assertTrue(callable(APIConnectionManager))
        self.assertTrue(callable(ESPHomeClient))
        self.assertTrue(callable(HaBleakClientWrapper))
        for name in ("start", "stop"):
            with self.subTest(api_connection_manager=name):
                self.assertTrue(callable(getattr(APIConnectionManager, name, None)))
        for name in ("async_setup", "async_discovered_service_info",
                     "async_register_advertisement_callback", "_discover_service_info"):
            with self.subTest(bluetooth_manager=name):
                self.assertTrue(callable(getattr(BluetoothManager, name, None)),
                                f"habluetooth.BluetoothManager.{name} missing")
        self.assertTrue(callable(getattr(habluetooth, "get_manager", None)))
        self.assertTrue(callable(getattr(habluetooth, "set_manager", None)))
        # Our adapter calls these methods on the actual ESPHome-aware client.
        for name in ("stop_notify", "write_gatt_char", "read_gatt_char"):
            with self.subTest(esphome_client=name):
                self.assertTrue(callable(getattr(ESPHomeClient, name, None)))
        self.assertIn("config", inspect.signature(APIConnectionManager).parameters)

    def test_proxy_loss_releases_notifications_and_scanner(self):
        asyncio.run(self._check_proxy_loss_cleanup())

    async def _check_proxy_loss_cleanup(self):
        from aioesphomeapi.core import APIConnectionError
        from bleak.backends.device import BLEDevice
        from bleak_esphome.backend.client import ESPHomeClient
        from habluetooth import HaBleakClientWrapper

        from awox.esphome_transport import ESPHomeNoCCCDTransport

        device = BLEDevice("A4:C1:38:00:00:01", "Test lamp",
                           {"source": "test-proxy", "address_type": 0})
        api = SimpleNamespace(
            is_connected=False,
            bluetooth_device_disconnect=AsyncMock(side_effect=APIConnectionError("Proxy lost")),
        )
        remote_device = SimpleNamespace(cache={}, async_untrack_client=Mock())
        scanner = SimpleNamespace(_clients=set())
        backend = ESPHomeClient(
            device,
            client_data=SimpleNamespace(
                client=api, bluetooth_device=remote_device, scanner=scanner,
                device_info=SimpleNamespace(bluetooth_proxy_feature_flags_compat=lambda _: 0),
                api_version=None, title="Offline test", disconnect_callbacks=set(),
            ),
        )
        # Seed the wrapper's connected state without registering a global manager.
        wrapper = HaBleakClientWrapper.__new__(HaBleakClientWrapper)
        wrapper._backend = backend
        wrapper._connected_scanner = scanner
        wrapper._connected_device = device
        scanner._clients.add(wrapper)

        backend._is_connected = True
        backend._disconnect_callbacks.add(backend._async_esp_disconnected)
        notify_stop, notify_abort = AsyncMock(), Mock()
        backend._notify_cancels[1] = (notify_stop, notify_abort)
        transport = ESPHomeNoCCCDTransport(device, backend_type=ESPHomeClient)
        transport._client = wrapper

        backend._async_esp_disconnected()
        self.assertFalse(wrapper.is_connected)
        notify_abort.assert_called_once_with()
        notify_stop.assert_not_awaited()
        self.assertEqual(backend._notify_cancels, {})
        self.assertNotIn(backend._async_esp_disconnected, backend._disconnect_callbacks)

        await transport.disconnect()
        api.bluetooth_device_disconnect.assert_awaited_once()
        self.assertIsNone(wrapper._connected_scanner)
        self.assertIsNone(wrapper._connected_device)
        self.assertNotIn(wrapper, scanner._clients)
        self.assertEqual(transport._cleanup_clients, [])

    def test_optional_versions_are_recorded_by_ci(self):
        # A CI build log and dependency artifact state precisely what ran.
        for project in ("bleak-esphome", "habluetooth", "bleak", "aioesphomeapi"):
            with self.subTest(project=project):
                self.assertTrue(version(project))


if __name__ == "__main__":
    unittest.main()
