"""Concurrent proxy closure/replacement during discovery; in-memory fake backend."""
import asyncio
import unittest
from types import SimpleNamespace

from awox.esphome_proxy import ESPHomeProxy


class ProxyLifecycleScanTests(unittest.IsolatedAsyncioTestCase):
    async def test_scan_does_not_call_disposed_manager_or_return_new_context_devices(self):
        proxy = ESPHomeProxy('proxy.local')
        first = object()
        entered = asyncio.Event()
        calls = []

        class Backend:
            def async_discovered_service_info(self, connectable):
                calls.append(connectable)
                entered.set()
                return []

        proxy._manager = first
        proxy._bluetooth = Backend()
        scanning = asyncio.create_task(proxy.scan_mesh_devices(0.9))
        await asyncio.wait_for(entered.wait(), 1)
        # The proxy context closes and a replacement opens while an old
        # scan has yielded. Its results belong to the previous lifecycle.
        proxy._manager = object()
        proxy._bluetooth = Backend()
        with self.assertRaisesRegex(RuntimeError, 'changed|closed'):
            await asyncio.wait_for(scanning, 1)
        self.assertEqual(calls, [False])

    async def test_transport_lookup_stops_on_proxy_closure(self):
        proxy = ESPHomeProxy('proxy.local', discovery_timeout=1)
        proxy._manager = object()
        queried = asyncio.Event()

        class Backend:
            def async_ble_device_from_address(self, mac, connectable):
                queried.set()
                return None

        proxy._bluetooth = Backend()
        proxy._client_type = object
        proxy._backend_type = object
        searching = asyncio.create_task(proxy.create_transport('AA:BB:CC:DD:EE:FF'))
        await asyncio.wait_for(queried.wait(), 1)
        proxy._manager = None
        proxy._bluetooth = None
        with self.assertRaisesRegex(RuntimeError, 'changed|closed'):
            await asyncio.wait_for(searching, 1)

    async def test_transport_lookup_does_not_use_replacement_proxy_backend(self):
        proxy = ESPHomeProxy('proxy.local', discovery_timeout=1)
        first = object()
        proxy._manager = first
        queried = asyncio.Event()

        class Backend:
            def async_ble_device_from_address(self, mac, connectable):
                queried.set()
                return None

        proxy._bluetooth = Backend()
        proxy._client_type = object
        proxy._backend_type = object
        searching = asyncio.create_task(proxy.create_transport('AA:BB:CC:DD:EE:FF'))
        await asyncio.wait_for(queried.wait(), 1)
        proxy._manager = object()
        proxy._bluetooth = SimpleNamespace(async_ble_device_from_address=lambda *_:
                                           SimpleNamespace(address='AA:BB:CC:DD:EE:FF'))
        with self.assertRaisesRegex(RuntimeError, 'changed|closed'):
            await asyncio.wait_for(searching, 1)
