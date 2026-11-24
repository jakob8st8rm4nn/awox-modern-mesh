"""Short (8-byte identity) AwoX advertisements from real ESPHome observations."""
import unittest
from types import SimpleNamespace

from awox.advertisements import AdvertisementRecord
from awox.esphome_proxy import ESPHomeProxy

SHORT = bytes.fromhex('60 01 96 20 19 22 11 38')
LONG = bytes.fromhex(
    '60 01 96 20 19 22 11 38 03 00 02 61 D3 00 FF 4D 01 FF FF 04 3E 60 00 00 00 00 00 00 00'
)


def ad(ff):
    return bytes((len(ff) + 1, 0xFF)) + ff


def info(manufacturer=SHORT, *, raw=None, timestamp=10.0):
    return SimpleNamespace(
        address='02:00:38:11:22:19', device=object(), rssi=-73, name='TestBLE1',
        manufacturer_data={0x0160: manufacturer[2:]}, raw=raw,
        service_data={}, service_uuids=(), time=timestamp, source='test',
        connectable=True,
    )


class ShortAdvertisementTests(unittest.TestCase):
    def test_actual_eight_byte_short_format(self):
        record = AdvertisementRecord.from_manufacturer_data(0x0160, SHORT[2:])
        self.assertTrue(record.awox_vendor)
        self.assertEqual(record.manufacturer, SHORT)
        self.assertEqual(record.model_code, bytes.fromhex('20 96'))
        self.assertEqual(record.model_lookup_code, bytes.fromhex('20 96'))
        self.assertEqual(record.normalized_manufacturer, SHORT)
        self.assertIsNone(record.mesh_address)
        self.assertIsNone(record.mesh_address_unsigned)
        self.assertEqual(record.firmware, '')
        self.assertIsNone(record.hardware_version)
        self.assertIsNone(record.provisioning_byte)
        self.assertIsNone(record.light_state)

    def test_incomplete_four_byte_identity_is_not_treated_as_full_short_packet(self):
        incomplete = AdvertisementRecord.from_manufacturer_data(0x0160, SHORT[2:4])
        self.assertIsNone(incomplete.model_code)
        self.assertIsNone(AdvertisementRecord.from_service_info(info(SHORT[:4])))

    def test_short_raw_advertisement_with_name_uuid_and_company_id(self):
        raw = bytes.fromhex('02 01 05 03 02 00 18 09 09') + b'TestBLE1' + ad(SHORT)
        record = AdvertisementRecord.from_bytes(raw)
        self.assertEqual(record.model_lookup_code, bytes.fromhex('20 96'))
        self.assertEqual(record.local_name, 'TestBLE1')
        self.assertEqual(record.raw_fields[0xff], SHORT)
        self.assertIsNone(record.mesh_address_unsigned)

    def test_live_proxy_accepts_short_and_repeated_identical_events(self):
        proxy = ESPHomeProxy('test.local')
        received = []
        proxy.on_advertisement(received.append)
        proxy._handle_advertisement_event(info())
        proxy._handle_advertisement_event(info())
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0].advertisement.model_code, b'\x20\x96')
        self.assertIsNone(received[1].advertisement.light_state)
        self.assertIsNone(proxy.get_advertisement('02:00:38:11:22:19').mesh_address_unsigned)

    def test_raw_short_event_overrides_merged_manufacturer_cache(self):
        proxy = ESPHomeProxy('test.local')
        events = []
        proxy.on_advertisement(events.append)
        proxy._handle_advertisement_event(info(LONG, timestamp=1.0))
        raw_short = ad(SHORT)
        proxy._handle_advertisement_event(info(LONG, raw=raw_short, timestamp=2.0))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].advertisement.mesh_address_unsigned, 0xD361)
        self.assertIsNone(events[1].advertisement.mesh_address_unsigned)
        self.assertEqual(events[1].advertisement.manufacturer, SHORT)
        self.assertEqual(proxy.get_advertisement('02:00:38:11:22:19').manufacturer, SHORT)
        self.assertEqual(events[1].advertisement.manufacturer_data[0x0160], LONG[2:])

    def test_short_then_long_and_short_unrelated_vendor(self):
        proxy = ESPHomeProxy('test.local')
        proxy._handle_advertisement_event(info(SHORT, timestamp=1.0))
        proxy._handle_advertisement_event(info(LONG, timestamp=2.0))
        record = proxy.get_advertisement('02:00:38:11:22:19')
        self.assertEqual(record.mesh_address_unsigned, 0xD361)
        self.assertEqual(record.firmware, '3.0.2')
        self.assertEqual(record.light_state.brightness_percent, 100.0)
        unrelated = info(SHORT)
        unrelated.manufacturer_data = {0x004c: SHORT[2:]}
        self.assertIsNone(AdvertisementRecord.from_service_info(unrelated))

    def test_long_plus_short_ad_structures_preserves_longest_policy(self):
        raw = ad(SHORT) + ad(LONG)
        record = AdvertisementRecord.from_service_info(info(LONG, raw=raw))
        self.assertEqual(record.mesh_address_unsigned, 0xD361)
        self.assertEqual(record.raw_fields[0xFF], LONG)


if __name__ == '__main__':
    unittest.main()
