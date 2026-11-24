"""Proxy advertisement discovery: no OS scanner or mesh login required."""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from awox.esphome_proxy import ESPHomeProxy


class ProxyDiscoveryTests(IsolatedAsyncioTestCase):
    @staticmethod
    def info(address, rssi, *, company=0x0160, raw=None):
        return SimpleNamespace(
            address=address, rssi=rssi, name='EGLO', device=object(),
            manufacturer_data={company: bytes(range(2, 29))}, raw=raw,
        )

    async def test_reads_only_proxy_cache_including_nonconnectable(self):
        a = self.info('AA:BB:CC:DD:EE:FF', -55)
        other = self.info('11:22:33:44:55:66', -20, company=0x004C)

        class RemoteCache:
            def __init__(self):
                self.calls = []
            def async_discovered_service_info(self, connectable):
                self.calls.append(connectable)
                return [a, other]

        cache = RemoteCache()
        proxy = ESPHomeProxy('proxy.local')
        proxy._manager = object()
        proxy._bluetooth = cache
        found = await proxy.scan_mesh_devices(0.001)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].address, a.address)
        self.assertEqual(found[0].rssi, -55)
        self.assertIs(found[0].device, a.device)
        self.assertEqual(found[0].advertisement.local_name, 'EGLO')
        self.assertTrue(found[0].advertisement.awox_vendor)
        self.assertTrue(cache.calls)
        self.assertEqual(set(cache.calls), {False})

    async def test_retains_advertisements_observed_earlier_in_scan_window(self):
        a = self.info('AA:BB:CC:DD:EE:FF', -55)
        class ChangingCache:
            def __init__(self): self.count = 0
            def async_discovered_service_info(self, connectable):
                self.count += 1
                return [a] if self.count == 1 else []
        proxy = ESPHomeProxy('proxy.local')
        proxy._manager = object()
        proxy._bluetooth = ChangingCache()
        self.assertEqual(len(await proxy.scan_mesh_devices(0.01)), 1)
        self.assertGreaterEqual(proxy._bluetooth.count, 2)

    async def test_raw_advertisement_fallback_and_inactive_context(self):
        proxy = ESPHomeProxy('proxy.local')
        with self.assertRaisesRegex(RuntimeError, 'context'):
            await proxy.scan_mesh_devices(0.001)
        original = b'\x60\x01' + bytes(range(2, 29))
        raw = bytes([len(original) + 1, 255]) + original
        info = SimpleNamespace(address='AA:BB:CC:DD:EE:FF', device=object(),
                               rssi=-60, name='EGLO', manufacturer_data={}, raw=raw)
        proxy._manager = object()
        proxy._bluetooth = SimpleNamespace(async_discovered_service_info=lambda _: [info])
        found = await proxy.scan_mesh_devices(0.001)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].advertisement.awox_vendor)

    async def test_invalid_duration(self):
        proxy = ESPHomeProxy('proxy.local')
        for invalid in (0, -1, float('nan'), float('inf'), -float('inf'), None, True, '5'):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    await proxy.scan_mesh_devices(invalid)
