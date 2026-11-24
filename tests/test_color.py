"""Offline tests for HCI-observed modern AwoX colour mode.

All test vectors use synthetic session keys and simulated BLE transports.
"""
import argparse
import unittest
from awox.lighting import build_color_native, build_color_rgb, color_payload_native, rgb_to_native
from awox.frames import open_frame
from awox.session import Credentials
from awox.frames import PAIR_UUID, COMMAND_UUID, SERVICE_UUID
from awox.transport import ConnectionLost
SYNTHETIC_KEY = bytes(range(16))
DEVICE_ID = 40157
PAIR_RESPONSE = b'\r' + bytes(range(8)) + bytes(7)

class ColorCodecTests(unittest.TestCase):

    def test_real_capture_payload_examples(self):
        self.assertEqual(color_payload_native(96, 254), bytes.fromhex('06 60 fe 02 00'))
        self.assertEqual(color_payload_native(22, 29), bytes.fromhex('06 16 1d 02 00'))
        self.assertEqual(color_payload_native(173, 218), bytes.fromhex('06 ad da 02 00'))

    def test_unicast_frame_uses_exact_wire_opcode_and_payload(self):
        frame = build_color_native(SYNTHETIC_KEY, DEVICE_ID, 96, 254)
        self.assertEqual(len(frame), 17)
        decoded = open_frame(SYNTHETIC_KEY, frame)
        self.assertEqual(decoded.flag, 0)
        self.assertEqual(decoded.data, bytes.fromhex('9c dd 01 00 03 06 60 fe 02 00'))

    def test_does_not_modify_old_white_or_brightness(self):
        from awox.lighting import brightness_payload_native, temperature_payload_mired
        self.assertEqual(brightness_payload_native(128), bytes.fromhex('04 80 02 00 00 00 00'))
        self.assertEqual(temperature_payload_mired(333), bytes.fromhex('0a 4d 01 02 00'))

    def test_android_skia_primary_and_secondary_vectors(self):
        vectors = {(255, 0, 0): (0, 254), (0, 255, 0): (84, 254), (0, 0, 255): (169, 254), (255, 255, 0): (42, 254), (0, 255, 255): (127, 254), (255, 0, 255): (211, 254)}
        for rgb, native in vectors.items():
            with self.subTest(rgb=rgb):
                self.assertEqual(rgb_to_native(*rgb), native)

    def test_intermediate_hues_and_saturation_truncate(self):
        vectors = {(255, 128, 0): (21, 254), (255, 128, 64): (14, 190), (0, 128, 255): (148, 254), (128, 0, 255): (190, 254), (255, 127, 127): (0, 127), (12, 34, 56): (148, 199)}
        for rgb, native in vectors.items():
            with self.subTest(rgb=rgb):
                self.assertEqual(rgb_to_native(*rgb), native)

    def test_achromatic_black_white_gray_do_not_encode_brightness(self):
        for intensity in (0, 1, 128, 255):
            self.assertEqual(rgb_to_native(intensity, intensity, intensity), (0, 0))
        self.assertEqual(build_color_rgb(SYNTHETIC_KEY, DEVICE_ID, 0, 0, 0), build_color_rgb(SYNTHETIC_KEY, DEVICE_ID, 255, 255, 255))

    def test_all_rgb_paths_produce_exact_native_plaintext(self):
        from vector_adapter import ExtendedCommandBuilder
        for rgb, expected in (((0, 255, 0), '06 54 fe 02 00'), ((255, 128, 64), '06 0e be 02 00'), ((255, 255, 255), '06 00 00 02 00')):
            with self.subTest(rgb=rgb):
                native = rgb_to_native(*rgb)
                direct = color_payload_native(*native)
                packet = build_color_rgb(SYNTHETIC_KEY, DEVICE_ID, *rgb)
                self.assertEqual(direct, bytes.fromhex(expected))
                self.assertEqual(open_frame(SYNTHETIC_KEY, packet).data[-5:], direct)
        self.assertEqual(ExtendedCommandBuilder(DEVICE_ID).color_hsv(120, 1).plaintext[-5:], bytes.fromhex('06 54 fe 02 00'))

    def test_rgb_does_not_encode_brightness(self):
        self.assertEqual(rgb_to_native(255, 0, 0), rgb_to_native(128, 0, 0))
        decoded = open_frame(SYNTHETIC_KEY, build_color_rgb(SYNTHETIC_KEY, DEVICE_ID, 255, 0, 0))
        self.assertEqual(decoded.data, bytes.fromhex('9c dd 01 00 03 06 00 fe 02 00'))

    def test_native_saturation_supports_0xff(self):
        self.assertEqual(color_payload_native(0, 255), bytes.fromhex('06 00 ff 02 00'))
        self.assertEqual(color_payload_native(254, 255, transition=5000), bytes.fromhex('06 fe ff 32 00'))
        decoded = open_frame(SYNTHETIC_KEY, build_color_native(SYNTHETIC_KEY, DEVICE_ID, 254, 255))
        self.assertEqual(decoded.data, bytes.fromhex('9c dd 01 00 03 06 fe ff 02 00'))

    def test_rgb_still_uses_apk_saturation_254(self):
        self.assertEqual(rgb_to_native(255, 0, 0), (0, 254))
        self.assertEqual(color_payload_native(*rgb_to_native(255, 0, 0)), bytes.fromhex('06 00 fe 02 00'))

    def test_reject_native_invalid_fields(self):
        for hue, sat in [(-1, 0), (255, 0), (0, -1), (0, 256), (True, 20), (20, False), (1.0, 0), (0, None)]:
            with self.subTest(hue=hue, sat=sat), self.assertRaises(ValueError):
                color_payload_native(hue, sat)

    def test_reject_invalid_rgb(self):
        for rgb in [(-1, 0, 0), (256, 0, 0), (True, 0, 0), (0, 3.5, 0), (2, None, 3)]:
            with self.subTest(rgb=rgb), self.assertRaises(ValueError):
                rgb_to_native(*rgb)

    def test_frame_crc_is_validated_by_existing_open(self):
        packet = bytearray(build_color_native(SYNTHETIC_KEY, DEVICE_ID, 60, 254))
        packet[6] ^= 128
        with self.assertRaises(ValueError):
            open_frame(SYNTHETIC_KEY, bytes(packet))
if __name__ == '__main__':
    unittest.main()
