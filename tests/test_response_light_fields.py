"""Offline APK-backed 0x35/0x3C/0x43 response light-field decoding."""
import unittest

from vector_adapter import parse_power_cut_get_mode, ExtendedNotification
from awox.light_settings import decode_light_settings
from awox.schedule import parse_schedule_read
from awox.presence import parse_presence_read
from awox.status import parse_lamp_status


def schedule(routine, light=b'\x03\x64\x11\xfe', *, b4=0, b5=20):
    return (bytes((0x35, 0xDD, 0x9C, routine, b4, b5, 0, 0))
            + light + b'\x00' + bytes(7))


class LightSettingsTests(unittest.TestCase):
    def test_all_sequence_codes_keep_preset_and_fallback(self):
        expected = {1: 1, 2: 4, 3: 2, 4: 6, 5: 3, 6: 5}
        for raw in range(256):
            with self.subTest(raw=raw):
                state = decode_light_settings(bytes((5, 80, raw, 0)))
                self.assertEqual(state.sequence_preset, expected.get(raw, 12))
                self.assertEqual(state.sequence_wire_code, raw)

    def test_color_apk_vector(self):
        value = decode_light_settings(bytes.fromhex('03 64 11 fe'))
        self.assertTrue(value.power_on)
        self.assertEqual(value.lighting_mode_code, 1)
        self.assertEqual(value.lighting_mode, 'color')
        self.assertFalse(value.candle_enabled)
        self.assertEqual(value.brightness_percent, 100)
        self.assertEqual((value.hue_native, value.saturation_native), (17, 254))
        self.assertIsNone(value.temperature_mired)
        self.assertEqual(value.unknown_flag_bits, 0)
        self.assertEqual(value.raw_bytes, bytes.fromhex('03 64 11 fe'))

    def test_white_apk_vector(self):
        value = decode_light_settings(bytes.fromhex('01 32 8a 01'))
        self.assertEqual(value.lighting_mode, 'white')
        self.assertEqual(value.brightness_percent, 50)
        self.assertEqual(value.temperature_mired, 394)
        self.assertIsNone(value.hue_native)
        self.assertIsNone(value.saturation_native)

    def test_real_timer_placeholder_not_guessed(self):
        value = decode_light_settings(bytes.fromhex('00 ff ff ff'))
        self.assertFalse(value.power_on)
        self.assertEqual(value.lighting_mode, 'white')
        self.assertIsNone(value.brightness_percent)
        self.assertIsNone(value.temperature_mired)

    def test_unknown_bits_and_apk_sequence_mode_are_preserved(self):
        value = decode_light_settings(bytes.fromhex('e9 50 b9 00'))
        self.assertTrue(value.power_on)
        self.assertEqual(value.unknown_flag_bits, 0xe8)
        self.assertEqual(value.lighting_mode_code, 0)
        self.assertEqual(value.lighting_mode, 'white')
        self.assertEqual(value.brightness_percent, 80)
        other = decode_light_settings(bytes.fromhex('05 ff ff ff'))
        self.assertEqual(other.lighting_mode_code, 2)
        self.assertEqual(other.lighting_mode, 'sequence')
        self.assertEqual(other.sequence_wire_code, 0xff)
        self.assertEqual(other.sequence_preset, 12)  # APK fallback, not an inferred firmware preset
        self.assertIsNone(other.temperature_mired)
        self.assertIsNone(other.hue_native)
        self.assertIsNone(other.brightness_percent)

    def test_candle_flag_and_unknown_bytes(self):
        value = decode_light_settings(bytes.fromhex('11 28 99 00'))
        self.assertTrue(value.candle_enabled)
        self.assertEqual(value.brightness_percent, 40)
        self.assertEqual(value.temperature_mired, 153)

    def test_rejects_invalid_length_and_types(self):
        for raw in (b'', b'\x01', bytes(5)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                decode_light_settings(raw)
        for raw in (None, '036411fe', [3, 100, 17, 254]):
            with self.subTest(raw=raw), self.assertRaises(TypeError):
                decode_light_settings(raw)

    def test_schedule_reads_decoded_and_raw(self):
        raw = schedule(3)
        part = parse_schedule_read(raw)
        self.assertEqual(part.light_settings.lighting_mode, 'color')
        self.assertEqual(part.light_settings.hue_native, 17)
        self.assertEqual(part.light_fields, bytes.fromhex('03 64 11 fe'))
        self.assertEqual(part.raw_response, raw)
        err = parse_schedule_read(bytes.fromhex('35 dd 9c ff 94 03'))
        self.assertIsNone(err.light_settings)

    def test_apk_timer_forced_duration_and_clock_extra_flag(self):
        raw = schedule(2, b4=0x21, b5=0x40)
        part = parse_schedule_read(raw)
        self.assertEqual(part.time_mode, 0)  # Unlike other routines, forced by APK
        self.assertEqual(part.minutes, 0x240)
        self.assertIsNone(part.clock_extra_flag)
        clock = parse_schedule_read(schedule(3, b4=(33 << 2) | 1, b5=(14 | 0x40)))
        self.assertEqual((clock.time_mode, clock.hour, clock.minute), (1, 14, 33))
        self.assertTrue(clock.clock_extra_flag)
        self.assertFalse(parse_schedule_read(schedule(3, b4=1, b5=14)).clock_extra_flag)

    def test_presence_reads_decoded_and_raw(self):
        raw = (bytes.fromhex('3c 34 12 81 80 03 64 11 fe')
               + bytes(6) + bytes((1, 0)))
        presence = parse_presence_read(raw)
        self.assertEqual(presence.light_settings.lighting_mode, 'color')
        self.assertEqual(presence.light_settings.brightness_percent, 100)
        self.assertEqual(presence.light_fields, bytes.fromhex('03 64 11 fe'))
        self.assertEqual(presence.raw_response, raw)
        err = parse_presence_read(bytes.fromhex('3c 34 12 ff 94 01'))
        self.assertIsNone(err.light_settings)

    def test_power_cut_only_active_known_scene_decodes(self):
        white_raw = bytes.fromhex('43 34 12 01 32 8a 01 02') + b'EXTRA'
        white = parse_power_cut_get_mode(white_raw)
        self.assertEqual(white.mesh_id, 0x1234)
        self.assertEqual(white.raw_response, white_raw)
        self.assertEqual(white.scene_settings.brightness_percent, 50)
        self.assertEqual(white.scene_settings.temperature_mired, 394)
        color = parse_power_cut_get_mode(bytes.fromhex('43 34 12 03 32 54 fe 02'))
        self.assertEqual((color.scene_settings.hue_native,
                          color.scene_settings.saturation_native), (84, 254))
        self.assertEqual(color.scene_kind, 'color')
        self.assertIsNone(parse_power_cut_get_mode(bytes.fromhex('43 34 12 01 32 8a 01 01')).scene_settings)
        self.assertIsNone(parse_power_cut_get_mode(bytes.fromhex('43 34 12 05 32 8a 01 02')).scene_settings)
        self.assertIsNone(parse_power_cut_get_mode(bytes.fromhex('43 34 12 ab 32 8a 01 ff')).scene_settings)

    def test_status_flag_properties_keep_raw_frame(self):
        # Valid synthetic 19-byte EGLO-ZM-RGB-TW status payload.
        p = (bytes.fromhex('dd 9c 01 00 00 96 20 b8 44 33 38')
             + bytes((1, 0x17, 138)) + bytes.fromhex('ff ff 50 be 60'))
        assert len(p) == 19
        state = parse_lamp_status(ExtendedNotification(0x80, 'mesh_status_raw', p, p))
        self.assertTrue(state.is_color_mode)
        self.assertTrue(state.candle_active)
        self.assertTrue(state.color_cycle_active)
        self.assertEqual(state.raw_response, b'\x80' + p)


if __name__ == '__main__':
    unittest.main()
