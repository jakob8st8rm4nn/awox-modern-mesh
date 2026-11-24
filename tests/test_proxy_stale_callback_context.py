"""Late ESPHome advertisement callbacks must not escape their proxy generation.

All tests use in-memory proxy backends; no BLE connection or credentials.
"""
import asyncio
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from awox.esphome_proxy import ESPHomeProxy

ADDRESS = 'AA:BB:CC:DD:EE:FF'
MANUFACTURER = bytes(range(2, 29))


def observation(timestamp, rssi):
    return SimpleNamespace(
        address=ADDRESS, rssi=rssi, name='EGLO', device=object(),
        manufacturer_data={0x0160: MANUFACTURER}, raw=None, time=timestamp,
    )


class SavedCallbacks:
    def __init__(self):
        self.callback = None

    def async_register_advertisement_callback(self, callback, address):
        self.callback = callback
        return lambda: None  # Already-queued callbacks may outlive unregister.


class ProxyStaleCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_address_listener_cannot_pollute_new_context(self):
        proxy = ESPHomeProxy('proxy.local')
        deliveries = []
        proxy.on_advertisement(lambda entry: deliveries.append(entry.rssi))
        first = SavedCallbacks()
        proxy._bluetooth = first
        proxy._manager = object()
        proxy._subscribe_address(ADDRESS)
        old_callback = first.callback
        self.assertIsNotNone(old_callback)

        # Simulate context replacement; the prior callback has already been
        # enqueued externally, so unregister cannot retract it.
        proxy._stop_advertisement_callbacks()
        proxy._latest_observations.clear()
        proxy._manager = object()
        second = SavedCallbacks()
        proxy._bluetooth = second
        proxy._subscribe_address(ADDRESS)
        second.callback(observation(20.0, -40))
        old_callback(observation(30.0, -90))

        self.assertEqual(deliveries, [-40])
        self.assertEqual(proxy.get_advertisement(ADDRESS).received_monotonic, 20.0)
        self.assertEqual(proxy._latest_observations[ADDRESS].rssi, -40)

    async def test_queued_address_callback_is_ignored_while_shutdown_waits(self):
        proxy = ESPHomeProxy('proxy.local')
        deliveries = []
        proxy.on_advertisement(lambda entry: deliveries.append(entry.rssi))
        backend = SavedCallbacks()
        backend.async_stop = lambda: None
        proxy._bluetooth = backend
        old_manager = object()
        proxy._manager = old_manager
        proxy._subscribe_address(ADDRESS)
        queued_callback = backend.callback

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_stop():
            started.set()
            await release.wait()

        proxy._manager = SimpleNamespace(stop=slow_stop)
        fake_habluetooth = types.ModuleType('habluetooth')
        fake_habluetooth.get_manager = lambda: backend
        fake_habluetooth.set_manager = lambda _: None
        with patch.dict(sys.modules, {'habluetooth': fake_habluetooth}):
            shutting_down = asyncio.create_task(proxy.__aexit__())
            await asyncio.wait_for(started.wait(), 1)
            # Unregistration has begun, but the old backend already enqueued
            # this callback; it must not reach the app or re-seed the cache.
            queued_callback(observation(40.0, -87))
            self.assertEqual(deliveries, [])
            self.assertIsNone(proxy.get_advertisement(ADDRESS))
            release.set()
            await asyncio.wait_for(shutting_down, 1)

    async def test_old_discovery_hook_cannot_pollute_reopened_proxy(self):
        saved = {'manager': None}
        habluetooth = types.ModuleType('habluetooth')
        bleak = types.ModuleType('bleak_esphome')
        bleak_backend = types.ModuleType('bleak_esphome.backend')
        bleak_client = types.ModuleType('bleak_esphome.backend.client')

        class FakeBluetoothManager:
            def async_discovered_service_info(self, _):
                return []

            def async_register_advertisement_callback(self, callback, address):
                return lambda: None

            async def async_setup(self):
                pass

            def async_stop(self):
                pass

        class FakeAPIManager:
            def __init__(self, _config):
                pass

            async def start(self):
                pass

            async def stop(self):
                pass

        habluetooth.BluetoothManager = FakeBluetoothManager
        habluetooth.HaBleakClientWrapper = object
        habluetooth.get_manager = lambda: saved['manager']
        habluetooth.set_manager = lambda manager: saved.__setitem__('manager', manager)
        bleak.APIConnectionManager = FakeAPIManager
        bleak_client.ESPHomeClient = type('FakeESPHomeClient', (), {})

        with patch.dict(sys.modules, {
            'habluetooth': habluetooth,
            'bleak_esphome': bleak,
            'bleak_esphome.backend': bleak_backend,
            'bleak_esphome.backend.client': bleak_client,
        }):
            proxy = ESPHomeProxy('proxy.local')
            received = []
            proxy.on_advertisement(lambda entry: received.append(entry.rssi))
            async with proxy:
                old_discovery = proxy._bluetooth._discover_service_info
                old_discovery(observation(10.0, -50))
                self.assertEqual(received, [-50])
            async with proxy:
                proxy._bluetooth._discover_service_info(observation(20.0, -35))
                old_info = observation(30.0, -95)
                old_info.address = '11:22:33:44:55:66'  # not registered in new proxy
                old_discovery(old_info)
                self.assertEqual(received, [-50, -35])
                self.assertIsNone(proxy.get_advertisement(old_info.address))
                self.assertEqual(proxy.get_advertisement(ADDRESS).received_monotonic, 20.0)


if __name__ == '__main__':
    unittest.main()
