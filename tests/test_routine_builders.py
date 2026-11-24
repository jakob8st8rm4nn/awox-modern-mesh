"""Pure routine builders: APK i9.r.c/i9.p.c vectors, boundaries and preservation.

These are offline byte contracts, not assertions that device firmware executes
a routine, retains it after power loss, or implements every raw mode.
"""
import itertools
import unittest
from dataclasses import FrozenInstanceError, replace

from awox import (ScheduleWritePart, PresenceWritePart,
                  routine_white_settings, routine_color_settings)
from awox.lighting import rgb_to_native
from vector_adapter import ExtendedCommandBuilder
from awox.light_settings import decode_light_settings
from awox.schedule import parse_schedule_read
from awox.presence import parse_presence_read


class ScheduleCopyTests(unittest.TestCase):
    def test_from_read_rejects_conflicting_device_or_routine(self):
        raw = bytes.fromhex("35 34 12 85 00 00 00 00 00 00 00 00 00")
        part = parse_schedule_read(raw)
        self.assertEqual(ScheduleWritePart.from_read(part).settings, raw[3:13])
        for mismatch in (replace(part, mesh_id=0x2222), replace(part, routine_id=6)):
            with self.subTest(mismatch=mismatch), self.assertRaises(ValueError):
                ScheduleWritePart.from_read(mismatch)


class LightBuilderTests(unittest.TestCase):
    def test_white_apk_temperature_and_flag_vectors(self):
        # APK MathUtils.percentageToValue(p,153,454), Java half-up rounding.
        for percent, mired in ((0, 153), (1, 156), (25, 228), (50, 304),
                               (75, 379), (99, 451), (100, 454)):
            for power, candle in itertools.product((False, True), repeat=2):
                with self.subTest(percent=percent, power=power, candle=candle):
                    expected = bytes((int(power) | int(candle) << 4, 50)) + mired.to_bytes(2, 'little')
                    raw = routine_white_settings(50, percent, power_on=power, candle_enabled=candle)
                    self.assertEqual(raw, expected)
                    self.assertEqual(decode_light_settings(raw).temperature_mired, mired)

    def test_rgb_apk_rounded_vectors_are_not_immediate_truncation(self):
        vectors = (((255, 0, 0), (0, 254)), ((0, 255, 0), (85, 254)),
                   ((0, 0, 255), (169, 254)), ((255, 255, 0), (42, 254)),
                   ((0, 255, 255), (127, 254)), ((255, 0, 255), (212, 254)),
                   ((255, 128, 128), (0, 127)), ((128, 128, 128), (0, 0)),
                   ((0, 0, 0), (0, 0)), ((255, 255, 255), (0, 0)))
        for rgb, native in vectors:
            for power, candle in itertools.product((False, True), repeat=2):
                with self.subTest(rgb=rgb, power=power, candle=candle):
                    flags = 2 | int(power) | int(candle) << 4
                    self.assertEqual(routine_color_settings(70, *rgb, power_on=power,
                                     candle_enabled=candle), bytes((flags, 70, *native)))
        # Immediate/power-cut commands must retain their existing truncation.
        self.assertEqual(rgb_to_native(0, 255, 0), (84, 254))
        self.assertEqual(rgb_to_native(255, 0, 255), (211, 254))
        self.assertEqual(rgb_to_native(255, 128, 128), (0, 126))

    def test_brightness_all_percentages_and_apk_ff_sentinel(self):
        for brightness in (*range(101), None):
            with self.subTest(brightness=brightness):
                expected = 255 if brightness is None else brightness
                self.assertEqual(routine_white_settings(brightness, 0, power_on=False),
                                 bytes((0, expected, 153, 0)))
                self.assertEqual(routine_color_settings(brightness, 0, 255, 0, power_on=True),
                                 bytes((3, expected, 85, 254)))

    def test_routine_builder_input_guards(self):
        for bad in (-1, 101, True, 1.5, '50', b'50'):
            with self.subTest(brightness=bad):
                for build in (lambda: routine_white_settings(bad, 0, power_on=True),
                              lambda: routine_color_settings(bad, 255, 0, 0, power_on=True)):
                    with self.assertRaises(ValueError):
                        build()
        for bad in (-1, 101, None, True, 0.5, '50'):
            with self.subTest(temperature=bad), self.assertRaises(ValueError):
                routine_white_settings(50, bad, power_on=True)
        for bad in (-1, 256, None, True, 0.5, '50'):
            for position in range(3):
                rgb = [1, 2, 3]
                rgb[position] = bad
                with self.subTest(rgb=rgb), self.assertRaises(ValueError):
                    routine_color_settings(50, *rgb, power_on=True)
        for bad in (0, 1, None, 'yes'):
            for build in (lambda: routine_white_settings(50, 0, power_on=bad),
                          lambda: routine_white_settings(50, 0, power_on=True, candle_enabled=bad),
                          lambda: routine_color_settings(50, 1, 2, 3, power_on=bad),
                          lambda: routine_color_settings(50, 1, 2, 3, power_on=True, candle_enabled=bad)):
                with self.subTest(flag=bad), self.assertRaises(TypeError):
                    build()


class ScheduleBuilderTests(unittest.TestCase):
    def test_timer_exact_apk_vector_and_packet(self):
        light = routine_white_settings(50, 50, power_on=True, candle_enabled=True)
        part = ScheduleWritePart.timer(780, light, enabled=True, fade_minutes=5)
        self.assertEqual(part.settings, bytes.fromhex('82 30 0c 00 05 11 32 30 01 00'))
        self.assertEqual(ExtendedCommandBuilder(0x1234).schedule_set(part).plaintext[3:],
                         bytes.fromhex('33 34 12 82 30 0c 00 05 11 32 30 01 00'))
        read = parse_schedule_read(b'\x35\x34\x12' + part.settings)
        self.assertEqual((read.minutes, read.time_mode, read.fade_minutes), (780, 0, 5))
        self.assertEqual(ScheduleWritePart.from_read(read), part)

    def test_every_timer_duration_encodes_without_affecting_other_fields(self):
        for minutes in range(1, 1440):
            part = ScheduleWritePart.timer(minutes, b'\x00\x64\xff\xff', enabled=False)
            self.assertEqual(part.settings, bytes((2, (minutes >> 8) << 4, minutes & 255,
                                                  0, 0, 0, 100, 255, 255, 0)))

    def test_clock_exact_vector_all_routine_ids_and_wire(self):
        for rid in (3, 5, 6, 7, 8):
            with self.subTest(routine=rid):
                part = ScheduleWritePart.clock(rid, 23, 59, b'\x03\x46\x55\xfe',
                        enabled=True, weekdays_mask=0x3E, repeat=True, fade_minutes=63)
                expected = bytes((rid | 128, 237, 23, 190, 63, 3, 70, 85, 254, 0))
                self.assertEqual(part.settings, expected)
                self.assertEqual(ExtendedCommandBuilder(0x1234).schedule_set(part).plaintext[3:],
                                 b'\x33\x34\x12' + expected)
                read = parse_schedule_read(b'\x35\x34\x12' + expected)
                self.assertEqual((read.hour, read.minute, read.time_mode, read.weekdays_mask,
                                  read.repeat, read.current_part, read.total_part),
                                 (23, 59, 1, 62, True, 0, 0))
                self.assertEqual(ScheduleWritePart.from_read(read), part)

    def test_all_clock_minutes_and_day_masks(self):
        for hour, minute in itertools.product(range(24), range(60)):
            part = ScheduleWritePart.clock(3, hour, minute, bytes(4), enabled=False)
            self.assertEqual(part.settings, bytes((3, minute * 4 + 1, hour)) + bytes(7))
        for mask, repeat in itertools.product(range(128), (False, True)):
            part = ScheduleWritePart.clock(5, 0, 0, bytes(4), enabled=True,
                                           weekdays_mask=mask, repeat=repeat)
            self.assertEqual(part.settings[3], mask | (128 if repeat else 0))

    def test_light_and_fade_edits_preserve_unknown_bits_and_part_counters(self):
        for high, fade in itertools.product((0, 64, 128, 192), range(64)):
            source = ScheduleWritePart(bytes((0x87, 0xFE, 0xF7, 0xFF, high | 12,
                                               0xE9, 80, 0xB9, 0, 0xA3)))
            new = source.with_fade_minutes(fade)
            self.assertEqual(new.settings[4], high | fade)
            self.assertEqual(new.settings[:4] + new.settings[5:],
                             source.settings[:4] + source.settings[5:])
            self.assertEqual(source.settings[4], high | 12)
        changed = source.with_light_fields(b'\x04\xff\xff\xff')
        self.assertEqual(changed.settings, source.settings[:5] + b'\x04\xff\xff\xff' + b'\xa3')

    def test_schedule_constructor_and_edit_guards(self):
        for rid in (0, 1, 2, 4, 9, 255, True, 3.0, None, '3'):
            with self.subTest(routine=rid), self.assertRaises(ValueError):
                ScheduleWritePart.clock(rid, 0, 0, bytes(4), enabled=True)
        for hour, minute in ((-1, 0), (24, 0), (True, 0), (0, -1), (0, 60), (0, True)):
            with self.subTest(hour=hour, minute=minute), self.assertRaises(ValueError):
                ScheduleWritePart.clock(3, hour, minute, bytes(4), enabled=True)
        for minutes in (-1, 0, 1440, True, 1.5, None):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                ScheduleWritePart.timer(minutes, bytes(4), enabled=True)
        for fade in (-1, 64, True, 1.5, None):
            for build in (lambda: ScheduleWritePart.timer(1, bytes(4), enabled=False, fade_minutes=fade),
                          lambda: ScheduleWritePart.clock(3, 0, 0, bytes(4), enabled=False, fade_minutes=fade)):
                with self.subTest(fade=fade), self.assertRaises(ValueError):
                    build()


class PresenceBuilderTests(unittest.TestCase):
    def test_presence_exact_apk_vector_and_packet(self):
        part = PresenceWritePart.create(routine_color_settings(70, 0, 255, 0, power_on=True),
                  enabled=True, weekdays_mask=0x3E, repeat=True, random_enabled=True)
        for slot in (0, 7, 8, 18, 47):
            part = part.with_half_hour_slot(slot, True)
        expected = bytes.fromhex('81 be 03 46 55 fe 81 01 04 00 00 80 01 00')
        self.assertEqual(part.settings, expected)
        self.assertEqual(ExtendedCommandBuilder(0x1234).presence_set(part).plaintext[3:],
                         b'\x3b\x34\x12' + expected)
        read = parse_presence_read(b'\x3c\x34\x12' + expected)
        self.assertEqual(PresenceWritePart.from_read(read), part)
        self.assertEqual([i for i, enabled in enumerate(read.half_hour_slots) if enabled], [0, 7, 8, 18, 47])

    def test_presence_defaults_are_explicitly_empty_and_can_select_every_slot(self):
        part = PresenceWritePart.create(bytes(4), enabled=False)
        self.assertEqual(part.settings, b'\x01' + bytes(13))
        for index in range(48):
            part = part.with_half_hour_slot(index, True)
        self.assertEqual(part.settings[6:12], b'\xff' * 6)
        self.assertEqual(part.settings[:6] + part.settings[12:], b'\x01' + bytes(7))
        for index in range(48):
            part = part.with_half_hour_slot(index, False)
        self.assertEqual(part.settings, b'\x01' + bytes(13))

    def test_all_presence_weekdays_and_random_bit_preservation(self):
        source = PresenceWritePart(bytes.fromhex('81 ff e9 50 b9 00 00 00 0f 0f c0 3f 84 a3'))
        for mask, repeat in itertools.product(range(128), (False, True)):
            changed = source.with_weekdays(mask, repeat)
            self.assertEqual(changed.settings[1], mask | (128 if repeat else 0))
            self.assertEqual(changed.settings[:1] + changed.settings[2:],
                             source.settings[:1] + source.settings[2:])
        for raw in range(256):
            stored = PresenceWritePart(source.settings[:12] + bytes((raw, 0xA3)))
            for enabled in (False, True):
                changed = stored.with_random_enabled(enabled)
                self.assertEqual(changed.settings[12], (raw & 254) | int(enabled))
                self.assertEqual(changed.settings[:12] + changed.settings[13:],
                                 stored.settings[:12] + stored.settings[13:])
        changed = source.with_light_fields(b'\x04\xff\xff\xff')
        self.assertEqual(changed.settings, source.settings[:2] + b'\x04\xff\xff\xff' + source.settings[6:])

    def test_presence_day_and_random_guards(self):
        for mask in (-1, 128, True, 1.5, None, '1'):
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                PresenceWritePart.create(bytes(4), enabled=False, weekdays_mask=mask)
        for flag in (0, 1, None, 'yes'):
            for build in (lambda: PresenceWritePart.create(bytes(4), enabled=False, repeat=flag),
                          lambda: PresenceWritePart.create(bytes(4), enabled=False, random_enabled=flag)):
                with self.subTest(flag=flag), self.assertRaises(TypeError):
                    build()


class SharedBuilderTests(unittest.TestCase):
    def test_all_new_constructors_require_explicit_boolean_enable(self):
        for flag in (0, 1, None, 'yes'):
            for build in (lambda: ScheduleWritePart.timer(1, bytes(4), enabled=flag),
                          lambda: ScheduleWritePart.clock(3, 0, 0, bytes(4), enabled=flag),
                          lambda: PresenceWritePart.create(bytes(4), enabled=flag)):
                with self.subTest(flag=flag), self.assertRaises(TypeError):
                    build()
        for build in (lambda: ScheduleWritePart.timer(1, bytes(4)),
                      lambda: ScheduleWritePart.clock(3, 0, 0, bytes(4)),
                      lambda: PresenceWritePart.create(bytes(4))):
            with self.assertRaises(TypeError):
                build()

    def test_light_fields_reject_invalid_types_or_lengths_in_every_entry_point(self):
        for fields in (None, 'abcd', [0, 1, 2, 3], memoryview(bytes(4)), b'', bytes(3), bytes(5)):
            for build in (lambda: ScheduleWritePart.timer(1, fields, enabled=True),
                          lambda: ScheduleWritePart.clock(3, 0, 0, fields, enabled=True),
                          lambda: PresenceWritePart.create(fields, enabled=True)):
                with self.subTest(fields=repr(fields)), self.assertRaises(ValueError):
                    build()

    def test_builders_copy_mutable_input_and_return_immutable_values(self):
        fields = bytearray((1, 50, 153, 0))
        timer = ScheduleWritePart.timer(1, fields, enabled=True)
        clock = ScheduleWritePart.clock(3, 0, 0, fields, enabled=False)
        presence = PresenceWritePart.create(fields, enabled=True)
        fields[:] = bytes(4)
        self.assertEqual(timer.settings[5:9], b'\x01\x32\x99\x00')
        self.assertEqual(clock.settings[5:9], b'\x01\x32\x99\x00')
        self.assertEqual(presence.settings[2:6], b'\x01\x32\x99\x00')
        for part in (timer, clock, presence):
            with self.assertRaises(FrozenInstanceError):
                part.settings = bytes(10)


if __name__ == '__main__':
    unittest.main()
