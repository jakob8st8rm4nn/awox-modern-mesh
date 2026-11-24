"""Offline regression: preserve partial PIR scenes for unknown mode 3."""

import unittest

from awox.crypto import aes_att_encryption
from vector_adapter import decode_notification
from awox.pir import PirSettings, decode_scene, encode_scene


class UnknownPirSceneTests(unittest.TestCase):
    def test_unknown_scene_keeps_mode_without_inventing_fields(self):
        scene = decode_scene(3, b"\xff\xff\xff")
        self.assertEqual(scene.mode, 3)
        self.assertEqual(scene.brightness, -1)
        with self.assertRaises(ValueError):
            encode_scene(scene)

    def test_pir_decode_keeps_both_scenes_if_one_is_unknown(self):
        # Low two bits = nightlight mode, next two bits = motion mode.
        # Keep sensitivity, timeout, flags and the *other* valid scene.
        for first_byte in (0xAB, 0xAE):
            with self.subTest(first_byte=hex(first_byte)):
                raw = (bytes((first_byte, 42)) + b"\xff\xee\xdd"
                       + b"\x40\x20\x10" + b"\x17")
                settings = PirSettings.decode(raw)
                self.assertEqual(settings.sensitivity, 0xA)
                self.assertEqual(settings.timeout, 42)
                self.assertTrue(settings.motion_enabled)
                self.assertTrue(settings.nightlight_enabled)
                self.assertEqual(settings.luminosity_threshold, 5)
                unknown = settings.nightlight if first_byte == 0xAB else settings.motion
                known = settings.motion if first_byte == 0xAB else settings.nightlight
                self.assertEqual((unknown.mode, unknown.brightness), (3, -1))
                self.assertEqual(known.mode, 2)
                self.assertGreaterEqual(known.brightness, 0)

    def test_pir_notification_with_unknown_mode_is_decoded(self):
        # Nightlight mode 3, motion mode 0, sensitivity 2.
        raw = bytes.fromhex('23 1a ff ee dd 40 20 10 17')
        payload = raw + bytes(7)
        key = bytes(range(16))
        packet = b"\x12" + aes_att_encryption(key, payload)
        result = decode_notification(key, packet)
        self.assertEqual(result.kind, 'pir_settings')
        self.assertEqual((result.value.nightlight.mode,
                          result.value.nightlight.brightness), (3, -1))
        self.assertEqual(result.value.motion.mode, 0)
        self.assertEqual(result.value.timeout, 0x1A)
        self.assertEqual(result.payload, payload)
        self.assertFalse(result.authenticated)

    def test_pir_requires_complete_fields(self):
        with self.assertRaises(ValueError):
            PirSettings.decode(bytes(8))


if __name__ == '__main__':
    unittest.main()
