"""APK-derived family/layout regressions; no Bluetooth or hardware access.

The independent model-code fixture comes from MainApplication/Descriptor.i().
Offsets: n7.f.d, n7.h/i/j, n7.k/l and g9.j.e -> da.b/c/d.
"""
import csv
from pathlib import Path
from types import SimpleNamespace
import unittest
from awox.advertisements import AdvertisementRecord, ScanObservation
from vector_adapter import ExtendedNotification
from awox.status import parse_lamp_status, StatusStore
from awox.status import parse_status_variant
from awox.frames import decode_notification
from awox.crypto import aes_att_encryption
from awox.session import Credentials
CONTROL_CODES = {'EPIR-Zm': '2058', 'ERCU-Zm': '2028', 'ERCU-WS-Zm': '202D', 'ERCU-3groups-Zm': '202C'}
FIXTURE = Path(__file__).parent / 'fixtures/apk-modellcodes-1.14.11.csv'
with FIXTURE.open(encoding='utf-8-sig', newline='') as stream:
    MODELS = [(row['Modellname'], bytes.fromhex(row['Modellcode hex (i())'])) for row in csv.DictReader(stream, delimiter=';')]

def manufacturer(code=b' \x96', *, firmware=(3, 0, 2), flags=3):
    return b'`\x01' + code[::-1] + bytes.fromhex('7F665538') + bytes(firmware) + b't\x99' + bytes((flags, 60, 96, 1, 83, 254, 4, 62, 96)) + bytes(7)

def note(code=b' \x96', *, flags=3, endpoint=1, opcode=130):
    payload = b't\x99' + bytes((endpoint,)) + b'\x00\x00' + code[::-1] + bytes.fromhex('7F665538') + bytes((1, flags, 120)) + b'M\x01' + bytes((83, 254, 96))
    return ExtendedNotification(opcode, 'mesh_status_raw', payload, payload)

class FamilyAdvertisementTests(unittest.TestCase):

    def test_all_48_registered_models_and_scanner_mask(self):
        self.assertEqual(len(MODELS), 48)
        for name, code in MODELS:
            for extra_bit in (0, 16):
                variant = bytes((code[0] | extra_bit, code[1]))
                with self.subTest(name=name, extra_bit=extra_bit):
                    raw = manufacturer(variant)
                    record = AdvertisementRecord.from_manufacturer_data(352, raw[2:])
                    self.assertEqual(record.model_lookup_code, code)
                    self.assertEqual(record.mesh_address_unsigned, 39284)
                    self.assertEqual(record.firmware, '3.0.2')
                    if name in CONTROL_CODES:
                        self.assertIsNone(record.light_state)
                        self.assertEqual(record.hardware_version, '3.60')
                        self.assertEqual(record.provisioning_byte, 96)
                    else:
                        self.assertTrue(record.light_state.is_on)
                        self.assertEqual(record.hardware_version, '4.62')
                        self.assertEqual(record.provisioning_byte, 96)

    def test_actual_remote_advertisement_all_ingress_paths(self):
        raw = bytes.fromhex('60012C207F6655380300027499043C60' + '00' * 13)
        packet = bytes((30, 255)) + raw
        observation = SimpleNamespace(address='02:00:38:55:66:7F', manufacturer_data={352: raw[2:]}, raw=packet)
        records = [AdvertisementRecord.from_bytes(packet), AdvertisementRecord.from_manufacturer_data(352, raw[2:]), AdvertisementRecord.from_service_info(observation)]
        for record in records:
            with self.subTest(record=record):
                self.assertEqual(record.model_lookup_code, b' ,')
                self.assertEqual(record.firmware, '3.0.2')
                self.assertEqual(record.hardware_version, '4.60')
                self.assertEqual(record.provisioning_byte, 96)
                self.assertEqual(record.mesh_address_unsigned, 39284)
                self.assertIsNone(record.light_state)
                self.assertEqual(record.manufacturer, raw)

    def test_control_hardware_does_not_depend_on_lamp_firmware_boundary(self):
        for code in CONTROL_CODES.values():
            for firmware in ((1, 0, 0), (2, 0, 26), (2, 0, 27), (3, 0, 2)):
                raw = manufacturer(bytes.fromhex(code), firmware=firmware, flags=4)
                record = AdvertisementRecord.from_manufacturer_data(352, raw[2:])
                with self.subTest(code=code, firmware=firmware):
                    self.assertIsNone(record.light_state)
                    self.assertEqual(record.hardware_version, '4.60')
                    self.assertEqual(record.provisioning_byte, 96)

    def test_control_hardware_follows_signed_apk_format_and_preserves_raw(self):
        raw = bytearray(manufacturer(b' ,'))
        raw[13:15] = b'\x80\xff'
        record = AdvertisementRecord.from_manufacturer_data(352, raw[2:])
        self.assertEqual(record.hardware_version, '-128.-1')
        self.assertEqual(record.manufacturer, raw)

    def test_old_lamp_percent_and_new_mired_offsets(self):
        raw = bytearray(manufacturer(firmware=(2, 0, 26), flags=1))
        raw[13:22] = bytes((1, 128, 75, 83, 254, 4, 62, 160, 221))
        old = AdvertisementRecord.from_manufacturer_data(352, raw[2:])
        self.assertEqual(old.light_state.temperature_percent_raw, 75)
        self.assertIsNone(old.light_state.white_temperature_mired)
        self.assertEqual(old.hardware_version, '4.62')
        self.assertEqual(old.provisioning_byte, 160)
        raw[8:11] = bytes((2, 0, 27))
        raw[15:22] = bytes((77, 1, 83, 254, 5, 63, 96))
        new = AdvertisementRecord.from_manufacturer_data(352, raw[2:])
        self.assertIsNone(new.light_state.temperature_percent_raw)
        self.assertEqual(new.light_state.white_temperature_mired, 333)
        self.assertEqual(new.hardware_version, '5.63')
        self.assertEqual(new.provisioning_byte, 96)

    def test_old_color_values_and_no_invented_temperature(self):
        raw = bytearray(manufacturer(firmware=(2, 0, 26)))
        raw[13:18] = bytes((23, 128, 75, 91, 200))
        state = AdvertisementRecord.from_manufacturer_data(352, raw[2:]).light_state
        self.assertTrue(state.candle_mode and state.color_cycle and state.color_mode)
        self.assertEqual((state.hue_raw, state.saturation_raw), (91, 200))
        self.assertIsNone(state.white_temperature_mired)
        self.assertIsNone(state.temperature_percent_raw)

    def test_full_mac_lamp_n7_h_through_proxy_and_explicit_raw_parser(self):
        address = '01:02:03:04:05:06'
        raw = b'`\x01\x96 ' + bytes.fromhex('060504030201') + bytes((3, 0, 2)) + b't\x99' + bytes((1, 128, 77, 1, 83, 254, 4, 62, 96)) + bytes(5)
        self.assertEqual(len(raw), 29)
        packet = bytes((30, 255)) + raw
        info = SimpleNamespace(address=address, manufacturer_data={352: raw[2:]}, raw=packet)
        for record in (AdvertisementRecord.from_service_info(info), ScanObservation(address, -60, packet).decode(), AdvertisementRecord.from_bytes(packet, address=address), AdvertisementRecord.from_manufacturer_data(352, raw[2:], address=address)):
            self.assertEqual(record.firmware, '3.0.2')
            self.assertEqual(record.mesh_address_unsigned, 39284)
            self.assertEqual(record.hardware_version, '4.62')
            self.assertEqual(record.provisioning_byte, 96)
            self.assertEqual(record.light_state.white_temperature_mired, 333)

    def test_short_truncated_and_unknown_models_keep_raw_without_light_state(self):
        for name, code in MODELS:
            raw = manufacturer(code)
            for length in range(29):
                with self.subTest(name=name, length=length):
                    record = AdvertisementRecord.from_manufacturer_data(352, raw[2:length])
                    self.assertIsNone(record.light_state)
                    self.assertIsNone(record.hardware_version)
                    self.assertIsNone(record.provisioning_byte)
        raw = manufacturer(b'w\x99')
        record = AdvertisementRecord.from_manufacturer_data(352, raw[2:])
        self.assertIsNone(record.light_state)
        self.assertIsNone(record.hardware_version)
        self.assertIsNone(record.provisioning_byte)
        self.assertEqual(record.manufacturer, raw)

class FamilyStatusTests(unittest.TestCase):

    def test_all_registered_models_both_status_opcodes(self):
        for name, code in MODELS:
            for opcode in (128, 130):
                n = note(code, opcode=opcode)
                with self.subTest(name=name, opcode=opcode):
                    state = parse_lamp_status(n)
                    frame = parse_status_variant(n)
                    self.assertEqual(frame.provisioning_state_code, 96)
                    self.assertEqual(frame.raw_response, bytes((opcode,)) + n.payload)
                    if name in CONTROL_CODES:
                        self.assertIsNone(state)
                        self.assertIsNone(frame.is_on)
                    else:
                        self.assertTrue(state.is_on)
                        self.assertTrue(frame.is_on)

    def test_controls_never_publish_lamp_status_for_any_flags(self):
        store = StatusStore({39284: '02:00:38:55:66:7F'})
        key = bytes(range(16))
        for code in CONTROL_CODES.values():
            for flags in range(256):
                n = note(bytes.fromhex(code), flags=flags)
                with self.subTest(code=code, flags=flags):
                    self.assertEqual(store.observe(n), (None, False))
                    frame = parse_status_variant(n)
                    self.assertIsNone(frame.is_on)
                    self.assertEqual(frame.mode, flags)
                    wire = b'\x82' + aes_att_encryption(key, n.payload[:16]) + n.payload[16:]
                    envelope = decode_notification(key, wire)
                    decoded = parse_status_variant(envelope)
                    self.assertIsNone(decoded.is_on)
                    self.assertEqual(envelope.payload, n.payload)
        self.assertEqual(store.states, {})

    def test_unknown_model_has_no_convenience_lamp_state(self):
        n = note(b'w\x99')
        self.assertIsNone(parse_lamp_status(n))
        self.assertEqual(parse_status_variant(n).raw_response, b'\x82' + n.payload)

    def test_full_mac_status_bytes_are_not_misused_as_product_code(self):
        n = note(b' ,')
        p = bytearray(n.payload)
        p[3:5] = b'4\x12'
        n = ExtendedNotification(130, 'mesh_status_raw', bytes(p), bytes(p))
        self.assertEqual(parse_status_variant(n).layout, 'da.b')
        self.assertTrue(parse_status_variant(n).is_on)
        self.assertIsNone(parse_lamp_status(n))

    def test_compact_control_status_keeps_raw_layout_and_provisioning(self):
        n = note(b' X')
        p = n.payload[:14] + bytes((50, 91, 200, 160))
        n = ExtendedNotification(128, 'mesh_status_raw', p, p)
        frame = parse_status_variant(n)
        self.assertEqual(frame.layout, 'da.c')
        self.assertIsNone(frame.is_on)
        self.assertEqual(frame.provisioning_state_code, 160)
        self.assertEqual(frame.raw_response, b'\x80' + p)
if __name__ == '__main__':
    unittest.main()
