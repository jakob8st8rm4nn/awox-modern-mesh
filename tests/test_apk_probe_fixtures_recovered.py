"""Useful protocol-byte invariants recovered from the retired APK audit probes.

These verify production ``awox`` encoders directly, not copies of probe
functions or scripts in the removed ``tools`` directory. No hardware access.
"""
import unittest

from vector_adapter import ExtendedCommand, ExtendedCommandBuilder, crc8
from awox.lighting import rgb_to_native
from awox.frames import build_control, open_frame


class NativeSceneHistoricalFrames(unittest.TestCase):
    def test_last_scene_index_matches_original_apk_fixture(self):
        actual = ExtendedCommandBuilder(0xD361).native_scene(255, save=False).plaintext
        self.assertEqual(actual, bytes.fromhex('00 0e 09 d3 61 01 05 00 05 00 00 ff'))

    def test_zero_scene_index_matches_original_apk_fixture(self):
        actual = ExtendedCommandBuilder(0xD361).native_scene(0, save=True).plaintext
        self.assertEqual(actual, bytes.fromhex('00 24 09 d3 61 01 05 00 04 00 00 00'))

    def test_group_destination_changes_flag_not_scene_semantics(self):
        group = ExtendedCommandBuilder(0x8001).native_scene(1, save=True).plaintext
        self.assertEqual(group, bytes.fromhex('01 49 09 80 01 01 05 00 04 00 00 01'))
        self.assertEqual(group[0], 1)
        self.assertEqual(group[8:], b'\x04\x00\x00\x01')

    def test_address_is_big_endian_in_extended_control_frame(self):
        frame = ExtendedCommandBuilder(0xD361).native_scene(7, save=True).plaintext
        self.assertEqual(frame[3:5], b'\xd3\x61')
        self.assertEqual(frame[6:8], b'\x05\x00')
        self.assertEqual(frame[8:], bytes.fromhex('04 00 00 07'))

    def test_crc_matches_both_scene_variants_from_apk(self):
        for save in (True, False):
            with self.subTest(save=save):
                frame = ExtendedCommandBuilder(0xD361).native_scene(7, save=save).plaintext
                self.assertEqual(frame[2], len(frame) - 3)
                self.assertEqual(frame[1], crc8(frame[2:]))
                self.assertEqual(ExtendedCommand(frame).plaintext, frame)

    def test_selector_only_changes_crc_and_selector(self):
        a = ExtendedCommandBuilder(0xD361).native_scene(7, save=True).plaintext
        b = ExtendedCommandBuilder(0xD361).native_scene(7, save=False).plaintext
        self.assertEqual(a[8:9], b'\x04')
        self.assertEqual(b[8:9], b'\x05')
        self.assertEqual(a[2:8], b[2:8])
        self.assertEqual(a[9:], b[9:])


class GroupColorHistoricalFrame(unittest.TestCase):
    KEY = bytes.fromhex('00112233445566778899aabbccddeeff')

    def test_exact_group_color_control_payload(self):
        # The original one-shot group-colour probe used group 0x8001,
        # RGB blue (native hue=169, sat=254). This is a codec test only.
        self.assertEqual(rgb_to_native(0, 0, 255), (169, 254))
        frame = build_control(self.KEY, 0x8001, (0x00, 0x03),
                              bytes.fromhex('06 a9 fe 02 00'))
        decoded = open_frame(self.KEY, frame)
        self.assertEqual(decoded.flag, 1)
        self.assertEqual(decoded.data, bytes.fromhex('80 01 01 00 03 06 a9 fe 02 00'))
        self.assertEqual(len(frame), 17)

    def test_group_color_is_not_membership_command(self):
        group = build_control(self.KEY, 0x8001, (0x00, 0x03),
                              bytes.fromhex('06 a9 fe 02 00'))
        self.assertNotIn(b'\x0c', open_frame(self.KEY, group).data[:5])
