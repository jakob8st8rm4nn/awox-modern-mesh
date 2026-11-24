"""Offline transition encoding and public API forwarding, no hardware."""
import unittest
from awox import AwoXMeshSession, Credentials
from vector_adapter import ExtendedCommandBuilder
from awox.lighting import color_payload_native, build_color_native, build_color_rgb
from awox.lighting import brightness_payload_native, temperature_payload_mired, build_brightness_native, build_brightness_percent, build_temperature_kelvin, build_temperature_mired
from awox.frames import open_frame
from awox.lighting import transition_bytes, DEFAULT_TRANSITION
KEY = bytes(range(16))
ADDR = 4660

class TransitionCodecTests(unittest.TestCase):

    def test_default_200ms_is_apk_byte_exact(self):
        self.assertEqual(DEFAULT_TRANSITION, 200)
        self.assertEqual(transition_bytes(), b'\x02\x00')
        self.assertEqual(brightness_payload_native(128), bytes.fromhex('04 80 02 00 00 00 00'))
        self.assertEqual(color_payload_native(0, 254), bytes.fromhex('06 00 fe 02 00'))
        self.assertEqual(temperature_payload_mired(333), bytes.fromhex('0a 4d 01 02 00'))
        for baseline, explicit in ((build_brightness_native(KEY, ADDR, 128), build_brightness_native(KEY, ADDR, 128, transition=200)), (build_brightness_percent(KEY, ADDR, 50), build_brightness_percent(KEY, ADDR, 50, transition=200)), (build_temperature_mired(KEY, ADDR, 333), build_temperature_mired(KEY, ADDR, 333, transition=200)), (build_temperature_kelvin(KEY, ADDR, 3000), build_temperature_kelvin(KEY, ADDR, 3000, transition=200)), (build_color_rgb(KEY, ADDR, 0, 255, 0), build_color_rgb(KEY, ADDR, 0, 255, 0, transition=200)), (build_color_native(KEY, ADDR, 84, 254), build_color_native(KEY, ADDR, 84, 254, transition=200))):
            self.assertEqual(baseline, explicit)

    def test_ms_values_are_little_endian_100ms_units(self):
        for ms, encoded in ((0, '00 00'), (100, '01 00'), (200, '02 00'), (500, '05 00'), (1000, '0a 00'), (2000, '14 00'), (5000, '32 00'), (25600, '00 01'), (6553500, 'ff ff')):
            with self.subTest(ms=ms):
                self.assertEqual(transition_bytes(ms), bytes.fromhex(encoded))
                b = bytes.fromhex(encoded)
                self.assertEqual(brightness_payload_native(128, transition=ms)[2:4], b)
                self.assertEqual(temperature_payload_mired(333, transition=ms)[3:5], b)
                self.assertEqual(color_payload_native(84, 254, transition=ms)[3:5], b)

    def test_wire_packets_for_all_six_paths(self):
        for ms in (0, 100, 200, 500, 1000, 5000):
            t = transition_bytes(ms)
            for packet, prefix, suffix in ((build_brightness_native(KEY, ADDR, 128, transition=ms), bytes.fromhex('12 34 01 08 00 04 80'), bytes(3)), (build_brightness_percent(KEY, ADDR, 50, transition=ms), bytes.fromhex('12 34 01 08 00 04 80'), bytes(3)), (build_temperature_mired(KEY, ADDR, 333, transition=ms), bytes.fromhex('12 34 01 00 03 0a 4d 01'), b''), (build_temperature_kelvin(KEY, ADDR, 3000, transition=ms), bytes.fromhex('12 34 01 00 03 0a 4d 01'), b''), (build_color_native(KEY, ADDR, 84, 254, transition=ms), bytes.fromhex('12 34 01 00 03 06 54 fe'), b''), (build_color_rgb(KEY, ADDR, 0, 255, 0, transition=ms), bytes.fromhex('12 34 01 00 03 06 54 fe'), b'')):
                with self.subTest(ms=ms, prefix=prefix.hex()):
                    self.assertEqual(open_frame(KEY, packet).data, prefix + t + suffix)

    def test_extended_encoder_uses_same_value(self):
        codec = ExtendedCommandBuilder(ADDR)
        self.assertEqual(codec.set('white_brightness', 50).plaintext, codec.set('white_brightness', 50, transition=200).plaintext)
        for t in (0, 500, 1000):
            b = transition_bytes(t)
            self.assertEqual(codec.set('white_brightness', 50, transition=t).plaintext[-5:-3], b)
            self.assertEqual(codec.set('white_temperature', 50, transition=t).plaintext[-2:], b)
            self.assertEqual(codec.color_hsv(120, 1, transition=t).plaintext[-2:], b)
        with self.assertRaises(ValueError):
            codec.set('power_state', 1, transition=500)

    def test_invalid_transition_is_rejected_without_rounding(self):
        for bad in (-100, 1, 50, 150, 201, 6553501, 6553600, True, 2.0, None, '200'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                transition_bytes(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                brightness_payload_native(128, transition=bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                color_payload_native(84, 254, transition=bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                temperature_payload_mired(333, transition=bad)
if __name__ == '__main__':
    unittest.main()
