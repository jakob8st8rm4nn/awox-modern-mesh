"""Synthetic offline AdvertisingPacket vectors derived from n7.a and scanner DEX."""
import unittest
from awox.advertisements import (
    AdvertisementRecord, ScanBuffer, ScanObservation, ScanTiming,
    advertising_field, android_scan_permissions_granted, manufacturer_firmware,
    manufacturer_mesh_address, normalize_manufacturer_data, parse_advertising_record,
)


def field(ad_type, payload):
    return bytes((len(payload) + 1, ad_type)) + payload


class DiscoveryTests(unittest.TestCase):
    def test_ad_fields_and_terminator(self):
        record = field(1, b'\x06') + field(9, b'mesh') + b'\0' + field(9, b'ignored')
        self.assertEqual(parse_advertising_record(record), {1: b'\x06', 9: b'mesh'})
        self.assertEqual(advertising_field(record, 9), b'mesh')
        self.assertIsNone(advertising_field(record, 1))

    def test_other_duplicate_types_use_last_value(self):
        record = field(9, b'long-name') + field(9, b'x')
        self.assertEqual(parse_advertising_record(record)[9], b'x')

    def test_manufacturer_keeps_longest_and_replaces_ties(self):
        record = field(255, b'abcdef') + field(255, b'xy') + field(255, b'ghijkl')
        self.assertEqual(parse_advertising_record(record)[255], b'ghijkl')

    def test_signed_length_stops_with_prior_fields(self):
        record = field(9, b'mesh') + b'\x80' + field(9, b'new')
        self.assertEqual(parse_advertising_record(record), {9: b'mesh'})

    def test_truncated_field_uses_original_bytewise_resync(self):
        # First length overruns; the next byte is a valid standalone AD header.
        self.assertEqual(parse_advertising_record(b'\x7f\x02\x09x'), {9: b'x'})
        self.assertEqual(parse_advertising_record(b'\x03\x09x'), {})
        self.assertEqual(parse_advertising_record(b''), {})
        self.assertEqual(parse_advertising_record(b'\x01\x09'), {9: b''})

    def test_exact_manufacturer_layout_normalization(self):
        raw = b'\x60\x01' + bytes(range(2, 29))
        expected = bytes.fromhex('600104050607c1a4020308090a0d0e0f101112131415161718191a1b1c')
        self.assertEqual(normalize_manufacturer_data(raw), expected)
        self.assertEqual(advertising_field(field(255, raw), 255), expected)
        self.assertEqual(normalize_manufacturer_data(raw + b'extra'), expected)

    def test_vendor_filter_applies_only_to_long_layout(self):
        self.assertIsNone(normalize_manufacturer_data(b'\x4c\0' + bytes(27)))
        self.assertEqual(normalize_manufacturer_data(b'\x4c\0short'), b'\x4c\0short')
        self.assertTrue(AdvertisementRecord.from_bytes(field(255, b'\x4c\0short')).apple_vendor)

    def test_mesh_address_uses_raw_not_normalized_offsets(self):
        raw = bytearray(b'\x60\x01' + bytes(range(2, 29)))
        raw[11:13] = b'\x34\x92'
        self.assertEqual(manufacturer_mesh_address(field(255, raw)), -28108)
        self.assertEqual(manufacturer_mesh_address(field(255, bytes(12))), 0)
        self.assertEqual(manufacturer_mesh_address(b''), 0)

    def test_model_and_firmware_from_normalized_data(self):
        raw = bytearray(b'\x60\x01' + bytes(range(2, 29)))
        raw[2:4] = b'\x23\x15'
        raw[8:11] = b'\x02\x05\x00'
        info = AdvertisementRecord.from_bytes(field(255, raw) + field(9, b'my mesh'))
        self.assertTrue(info.awox_vendor)
        self.assertEqual(info.model_code, b'\x15\x23')
        self.assertEqual(info.model_lookup_code, b'\x05\x23')
        self.assertEqual(info.firmware, '2.5.0')
        self.assertEqual(info.local_name, 'my mesh')

    def test_short_unknown_firmware_and_name_decoding(self):
        self.assertEqual(manufacturer_firmware(b'\x60\x01'), '')
        self.assertEqual(manufacturer_firmware(bytes(13)), '')
        info = AdvertisementRecord.from_bytes(field(9, b'\xff'))
        self.assertEqual(info.local_name, '\ufffd')
        self.assertIsNone(info.model_code)
        self.assertIsNone(info.manufacturer)
        with self.assertRaises(TypeError):
            info.fields[9] = b'changed'

    def test_android31_permission_branches(self):
        self.assertTrue(android_scan_permissions_granted(31, scan=True, connect=True))
        self.assertFalse(android_scan_permissions_granted(31, scan=True, fine_location=True))
        self.assertFalse(android_scan_permissions_granted(31, connect=True))
        self.assertTrue(android_scan_permissions_granted(30, fine_location=True))
        self.assertFalse(android_scan_permissions_granted(30, scan=True, connect=True))

    def test_latest_per_address_batch_and_inactive_clear(self):
        buffer = ScanBuffer()
        buffer.add(ScanObservation('A', -80, b'old'))
        latest = ScanObservation('A', -40, b'new')
        buffer.add(latest)
        buffer.add(ScanObservation('B', -60, None))
        self.assertEqual({x.address: x for x in buffer.drain()},
                         {'A': latest, 'B': ScanObservation('B', -60, None)})
        self.assertEqual(buffer.drain(), ())
        buffer.add(latest)
        self.assertEqual(buffer.drain(scanning=False), ())
        self.assertEqual(buffer.drain(), ())

    def test_observations_copy_mutable_payloads_and_allow_no_record(self):
        raw = bytearray(field(9, b'mesh'))
        observation = ScanObservation('A', -45, raw)
        raw[-1] = 0
        self.assertEqual(observation.decode().local_name, 'mesh')
        self.assertIsNone(ScanObservation('B', 0, None).decode())

    def test_scan_timing_from_original_constants(self):
        timing = ScanTiming()
        self.assertEqual((timing.scan_mode, timing.number_of_matches), (2, 1))
        self.assertEqual((timing.batch_seconds, timing.window_seconds, timing.restart_delay_seconds),
                         (0.8, 6.5, 0.5))

    def test_bleak_manufacturer_adapter_has_no_invented_scan_record(self):
        raw = b'\x60\x01' + bytes(range(2, 29))
        android = AdvertisementRecord.from_bytes(field(255, raw))
        adapted = AdvertisementRecord.from_manufacturer_data(0x0160, raw[2:], local_name='provided name')
        self.assertEqual(adapted.manufacturer, raw)
        self.assertEqual(adapted.normalized_manufacturer, android.normalized_manufacturer)
        self.assertEqual(adapted.model_code, android.model_code)
        self.assertEqual(adapted.mesh_address, android.mesh_address)
        self.assertEqual(adapted.firmware, android.firmware)
        self.assertEqual(adapted.local_name, 'provided name')
        self.assertEqual(dict(adapted.fields), {255: raw})
        for invalid in (-1, 0x10000):
            with self.assertRaises(ValueError):
                AdvertisementRecord.from_manufacturer_data(invalid, b'')


if __name__ == '__main__':
    unittest.main()
