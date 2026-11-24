"""Offline tests for the *new* AwoX/EGLO modern lighting commands."""
from __future__ import annotations
import unittest
from awox.frames import COMMAND_UUID, PAIR_UUID, SERVICE_UUID
from awox.lighting import brightness_native_from_percent, brightness_payload_native, build_brightness_native, build_brightness_percent, build_temperature_kelvin, build_temperature_mired, mired_from_kelvin, temperature_payload_mired
from awox.frames import open_frame
from awox.session import Credentials
from awox.transport import ConnectionLost
# Synthetic only; these are NOT real mesh credentials or session keys.
KEY = bytes(range(16))
RANDOM = bytes(range(8))
PAIRING_REPLY = b'\r' + bytes(range(8)) + bytes(7)
DEVICE_ID = 40157

class LightingCodecTests(unittest.TestCase):

    def test_all_percentages_keep_original_raw_values(self):
        for percent in range(101):
            with self.subTest(percent=percent):
                self.assertEqual(brightness_native_from_percent(percent), 2 + (percent * 252 + 50) // 100)

    def test_all_native_brightness_values_remain_supported(self):
        for level in range(1, 256):
            with self.subTest(level=level):
                self.assertEqual(brightness_payload_native(level)[1], level)

    def test_captured_brightness_payloads(self):
        self.assertEqual(brightness_payload_native(1), bytes.fromhex('04 01 02 00 00 00 00'))
        self.assertEqual(brightness_payload_native(255), bytes.fromhex('04 ff 02 00 00 00 00'))
        self.assertEqual(brightness_payload_native(254), bytes.fromhex('04 fe 02 00 00 00 00'))
        self.assertEqual(brightness_payload_native(194), bytes.fromhex('04 c2 02 00 00 00 00'))
        self.assertEqual(brightness_payload_native(47), bytes.fromhex('04 2f 02 00 00 00 00'))

    def test_captured_temperature_payloads(self):
        self.assertEqual(temperature_payload_mired(153), bytes.fromhex('0a 99 00 02 00'))
        self.assertEqual(temperature_payload_mired(454), bytes.fromhex('0a c6 01 02 00'))
        self.assertEqual(temperature_payload_mired(421), bytes.fromhex('0a a5 01 02 00'))

    def test_brightness_frame_contains_wire_opcode_08_00_and_exact_payload(self):
        packet = build_brightness_native(KEY, DEVICE_ID, 194)
        opened = open_frame(KEY, packet)
        self.assertEqual(len(packet), 17)
        self.assertEqual(opened.flag, 0)
        self.assertEqual(opened.data, bytes.fromhex('9c dd 01 08 00 04 c2 02 00 00 00 00'))

    def test_white_frame_contains_wire_opcode_00_03_and_mired(self):
        packet = build_temperature_mired(KEY, DEVICE_ID, 421)
        opened = open_frame(KEY, packet)
        self.assertEqual(len(packet), 17)
        self.assertEqual(opened.flag, 0)
        self.assertEqual(opened.data, bytes.fromhex('9c dd 01 00 03 0a a5 01 02 00'))

    def test_group_destination_observed_offline_but_not_sent(self):
        packet = build_brightness_native(KEY, 32768, 254)
        opened = open_frame(KEY, packet)
        self.assertEqual(opened.flag, 1)
        self.assertEqual(opened.data, bytes.fromhex('80 00 01 08 00 04 fe 02 00 00 00 00'))

    def test_native_allowed_boundaries_are_preserved_in_frame(self):
        for level in (1, 2, 254, 255):
            with self.subTest(level=level):
                frame = open_frame(KEY, build_brightness_native(KEY, DEVICE_ID, level))
                self.assertEqual(frame.data, bytes.fromhex('9c dd 01 08 00 04') + bytes((level,)) + bytes.fromhex('02 00 00 00 00'))

    def test_percent_conversion_endpoints_and_middle(self):
        self.assertEqual(brightness_native_from_percent(0), 2)
        self.assertEqual(brightness_native_from_percent(50), 128)
        self.assertEqual(brightness_native_from_percent(100), 254)
        self.assertEqual(open_frame(KEY, build_brightness_percent(KEY, DEVICE_ID, 50)).data, bytes.fromhex('9c dd 01 08 00 04 80 02 00 00 00 00'))

    def test_kelvin_conversion_and_frame(self):
        self.assertEqual(mired_from_kelvin(3000), 333)
        self.assertEqual(open_frame(KEY, build_temperature_kelvin(KEY, DEVICE_ID, 3000)).data, bytes.fromhex('9c dd 01 00 03 0a 4d 01 02 00'))

    def test_reject_invalid_native_percent_and_mired(self):
        for bad in (-1, 0, 256, 2.0, True, None):
            with self.subTest(brightness=bad), self.assertRaises(ValueError):
                brightness_payload_native(bad)
        for bad in (-1, 101, 50.0, True, None):
            with self.subTest(percent=bad), self.assertRaises(ValueError):
                brightness_native_from_percent(bad)
        for bad in (152, 455, 153.0, False, None):
            with self.subTest(mired=bad), self.assertRaises(ValueError):
                temperature_payload_mired(bad)
        for bad in (1, 2000, 10000, 3000.1, False):
            with self.subTest(kelvin=bad), self.assertRaises(ValueError):
                mired_from_kelvin(bad)

    def test_dual_zone_native_encoders_share_exact_legacy_bytes(self):
        from awox import lighting
        from awox._numeric import percentage_to_value

        vectors = (
            (lighting.dual_zone_brightness, (0x1234, 0, 0), '00220a12340152ff1000020002'),
            (lighting.dual_zone_brightness, (0x1234, 255, 100), '004f0a12340152ff10fffe0002'),
            (lighting.dual_zone_color, (0x1234, 1, 255, 0, 0), '00110b12340152ff200100fe0002'),
            (lighting.dual_zone_temperature, (0x1234, 2, 0), '00480b12340152ff210299000002'),
            (lighting.dual_zone_temperature, (0x1234, 2, 100), '005a0b12340152ff2102c6010002'),
        )
        for encoder, args, expected_hex in vectors:
            with self.subTest(encoder=encoder.__name__, args=args):
                self.assertEqual(encoder(*args).plaintext, bytes.fromhex(expected_hex))

        for zone in (0, 255):
            for percent in range(101):
                with self.subTest(zone=zone, percent=percent):
                    self.assertEqual(
                        lighting.dual_zone_brightness(0x1234, zone, percent).plaintext,
                        lighting.dual_zone_brightness_native(
                            0x1234, zone, percentage_to_value(percent, 2, 254)
                        ).plaintext,
                    )
                    self.assertEqual(
                        lighting.dual_zone_temperature(0x1234, zone, percent).plaintext,
                        lighting.dual_zone_temperature_mired(
                            0x1234, zone, percentage_to_value(percent, 153, 454)
                        ).plaintext,
                    )
            for red, green, blue in ((0, 0, 0), (255, 255, 255), (255, 0, 0),
                                     (0, 255, 0), (0, 0, 255), (137, 129, 63)):
                hue, saturation = lighting.rgb_to_native(red, green, blue)
                self.assertEqual(
                    lighting.dual_zone_color(0x1234, zone, red, green, blue).plaintext,
                    lighting.dual_zone_color_native(0x1234, zone, hue, saturation).plaintext,
                )

    def test_dual_zone_errors_preserve_validation_order_and_messages(self):
        from awox import lighting

        cases = (
            (lighting.dual_zone_brightness, (-1, 256, -1), 'zone must be a byte'),
            (lighting.dual_zone_brightness, (-1, 0, -1), 'percent must be 0..100'),
            (lighting.dual_zone_brightness, (-1, 0, 10), 'destination must be a 16-bit integer'),
            (lighting.dual_zone_brightness_native, (-1, 0, 0), 'native dual-zone brightness must be 1..255'),
            (lighting.dual_zone_brightness_native, (-1, 0, 256), 'native dual-zone brightness must be 1..255'),
            (lighting.dual_zone_color, (-1, 256, -1, -1, -1), 'zone must be a byte'),
            (lighting.dual_zone_color, (-1, 0, -1, -1, -1), 'RGB channels must be integers from 0 to 255'),
            (lighting.dual_zone_color, (-1, 0, 0, 0, 0), 'destination must be a 16-bit integer'),
            (lighting.dual_zone_temperature, (-1, 256, -1), 'zone must be a byte'),
            (lighting.dual_zone_temperature, (-1, 0, -1), 'percent must be 0..100'),
            (lighting.dual_zone_temperature_mired, (-1, 0, 152), 'dual-zone temperature must be 153..454 mired'),
        )
        for encoder, args, message in cases:
            with self.subTest(encoder=encoder.__name__, args=args):
                with self.assertRaises(ValueError) as error:
                    encoder(*args)
                self.assertEqual(str(error.exception), message)

if __name__ == '__main__':
    unittest.main()
