"""Smoke-check real optional ESPHome packages without a proxy or BLE device.

Offline test runs skip these checks if [esphome] is not installed. A separate
CI job installs [esphome] and runs this test against actual installed packages.
This is not an end-to-end hardware or APK compatibility test.
"""

import importlib.util
import inspect
import unittest
from importlib.metadata import version


@unittest.skipUnless(
    all(importlib.util.find_spec(name) is not None for name in
        ("bleak_esphome", "habluetooth", "bleak")),
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

    def test_optional_versions_are_recorded_by_ci(self):
        # A CI build log and dependency artifact state precisely what ran.
        for project in ("bleak-esphome", "habluetooth", "bleak"):
            with self.subTest(project=project):
                self.assertTrue(version(project))


if __name__ == "__main__":
    unittest.main()
