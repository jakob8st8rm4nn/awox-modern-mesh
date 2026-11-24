"""Offline regression tests for APK e0 POSIX timezone rule formatting."""
from __future__ import annotations

import unittest

from awox import build_time_with_timezone
from awox.timezone_rule import (
    AndroidTransitionRule, apk_posix_offset, apk_transition_time,
    format_apk_transition, format_apk_fixed_timezone, format_apk_dst_timezone,
)


def vienna_start(**kwargs):
    values = dict(month=3, day_of_month_indicator=-1, day_of_week=7,
                  local_time_seconds=7200, time_definition='WALL',
                  standard_offset_seconds=3600, offset_before_seconds=3600,
                  offset_after_seconds=7200)
    values.update(kwargs)
    return AndroidTransitionRule(**values)


def vienna_end(**kwargs):
    values = dict(month=10, day_of_month_indicator=-1, day_of_week=7,
                  local_time_seconds=10800, time_definition='WALL',
                  standard_offset_seconds=3600, offset_before_seconds=7200,
                  offset_after_seconds=3600)
    values.update(kwargs)
    return AndroidTransitionRule(**values)


class APKTimezoneFormattingTests(unittest.TestCase):
    def test_inverse_gmt_offset_sign(self):
        for sec, expected in [(0, '0'), (3600, '-1'), (-18000, '5'),
                              (19800, '-5:30'), (-19800, '5:30'),
                              (3601, '-1:00:01'), (-1, '0:00:01')]:
            with self.subTest(sec=sec):
                self.assertEqual(apk_posix_offset(sec), expected)

    def test_offset_types_and_overflow(self):
        for val in (True, 5.3, '3600'):
            with self.subTest(value=val), self.assertRaises(TypeError):
                apk_posix_offset(val)
        for val in (-(1 << 31), (1 << 31)):
            with self.subTest(value=val), self.assertRaises(ValueError):
                apk_posix_offset(val)

    def test_transition_time_java_formatter(self):
        for seconds, expected in ((0,'0'), (7200,'2'), (10800,'3'), (86400,'24'),
                                  (3690,'1:01:30'), (-3600,'-1'),
                                  (-3661,'-1:01:01'), (-1800,'0:30')):
            with self.subTest(seconds=seconds):
                self.assertEqual(apk_transition_time(seconds), expected)

    def test_last_sunday_m_rule_and_wall_clock(self):
        self.assertEqual(format_apk_transition(vienna_start()), 'M3.5.0')
        self.assertEqual(format_apk_transition(vienna_end()), 'M10.5.0/3')

    def test_first_through_fourth_week(self):
        for day, week in ((1,1),(8,2),(15,3),(22,4),(25,5),(-7,5)):
            with self.subTest(day=day):
                self.assertEqual(format_apk_transition(vienna_start(
                    day_of_month_indicator=day, day_of_week=1)), f'M3.{week}.1')

    def test_unrepresentable_weekday_dates_return_none(self):
        for day in (2,7,9,14,23,24,-8,-28):
            with self.subTest(day=day):
                self.assertIsNone(format_apk_transition(vienna_start(day_of_month_indicator=day)))

    def test_julian_days_nonleap_year(self):
        self.assertEqual(format_apk_transition(vienna_start(
            month=1, day_of_month_indicator=1, day_of_week=None)), 'J1')
        self.assertEqual(format_apk_transition(vienna_start(
            month=3, day_of_month_indicator=1, day_of_week=None)), 'J60')
        self.assertEqual(format_apk_transition(vienna_start(
            month=4, day_of_month_indicator=-1, day_of_week=None)), 'J120')

    def test_february_negative_nonweekday_is_explicitly_unrepresentable(self):
        self.assertIsNone(format_apk_transition(vienna_start(
            month=2, day_of_month_indicator=-1, day_of_week=None)))

    def test_utc_transition_time_definition(self):
        self.assertEqual(format_apk_transition(vienna_start(
            time_definition='UTC')), 'M3.5.0/3')

    def test_standard_transition_time_definition(self):
        self.assertEqual(format_apk_transition(vienna_end(
            local_time_seconds=7200, time_definition='STANDARD')), 'M10.5.0/3')

    def test_wall_transition_time_definition(self):
        self.assertEqual(format_apk_transition(vienna_start(
            time_definition='WALL')), 'M3.5.0')

    def test_midnight_end_of_day(self):
        self.assertEqual(format_apk_transition(vienna_start(
            local_time_seconds=0, midnight_end_of_day=True)), 'M3.5.0/24')

    def test_invalid_rule_is_not_silently_converted(self):
        for field, value, error in (
            ('month',0,ValueError),('day_of_month_indicator',0,ValueError),
            ('day_of_week',8,ValueError),('local_time_seconds',86400,ValueError),
            ('time_definition','APP',ValueError),('offset_before_seconds',70000,ValueError),
            ('midnight_end_of_day',1,TypeError),('month',True,TypeError),
        ):
            with self.subTest(field=field), self.assertRaises(error):
                vienna_start(**{field:value})
        with self.assertRaises(ValueError):
            vienna_start(local_time_seconds=3600, midnight_end_of_day=True)
        with self.assertRaises(TypeError):
            format_apk_transition('M3.5.0')

    def test_fixed_offset(self):
        self.assertEqual(format_apk_fixed_timezone(0), 'UTC0')
        self.assertEqual(format_apk_fixed_timezone(3600), 'UTC-1')
        self.assertEqual(format_apk_fixed_timezone(-18000), 'UTC5')
        self.assertEqual(format_apk_fixed_timezone(19800), 'UTC-5:30')

    def test_unfinished_fixed_zone_transition_is_not_misreported(self):
        self.assertIsNone(format_apk_fixed_timezone(3600, has_future_transition=True))
        with self.assertRaises(TypeError):
            format_apk_fixed_timezone(3600, has_future_transition=1)

    def test_full_europe_vienna_rule(self):
        self.assertEqual(format_apk_dst_timezone('CET', 3600, 'CEST',
                         vienna_start(), vienna_end()),
                         'CET-1CEST,M3.5.0,M10.5.0/3')

    def test_new_york_rule_standard_winter_five_hours(self):
        start = vienna_start(month=3, day_of_month_indicator=8,
                             offset_before_seconds=-18000, offset_after_seconds=-14400,
                             standard_offset_seconds=-18000)
        end = vienna_end(month=11, day_of_month_indicator=1,
                         local_time_seconds=7200, offset_before_seconds=-14400,
                         offset_after_seconds=-18000, standard_offset_seconds=-18000)
        self.assertEqual(format_apk_dst_timezone('EST', -18000, 'EDT', start, end),
                         'EST5EDT,M3.2.0,M11.1.0')

    def test_nonstandard_daylight_offset_is_explicit(self):
        start = vienna_start(offset_after_seconds=5400)
        end = vienna_end(offset_before_seconds=5400)
        self.assertEqual(format_apk_dst_timezone('CET', 3600, 'DST', start, end),
                         'CET-1DST-1:30,M3.5.0,M10.5.0/3')

    def test_names_fallback_to_original_std_dst(self):
        self.assertEqual(format_apk_dst_timezone('CET 1', 3600, None,
                         vienna_start(), vienna_end()),
                         'STD-1DST,M3.5.0,M10.5.0/3')

    def test_apk_rule_length_limit_does_not_truncate(self):
        self.assertIsNone(format_apk_dst_timezone('VeryLongStandardAbbreviation',
                          3600, 'LongDaylightName', vienna_start(), vienna_end()))

    def test_invalid_dst_direction_returns_none(self):
        self.assertIsNone(format_apk_dst_timezone('CET', 3600, 'CEST',
                         vienna_end(), vienna_start()))
        self.assertIsNone(format_apk_dst_timezone('CET', 3600, 'CEST',
                         vienna_start(day_of_month_indicator=6), vienna_end()))

    def test_ascii_padding_still_owned_by_previous_encoder(self):
        rule = format_apk_dst_timezone('CET', 3600, 'CEST', vienna_start(), vienna_end())
        cmd = build_time_with_timezone(946684800000, rule)
        self.assertEqual(cmd.plaintext[3], 0x29)
        self.assertEqual(cmd.plaintext[8:8+len(rule)], rule.encode('ascii'))
        self.assertEqual(cmd.plaintext[8+len(rule):], bytes(32-len(rule)))

    def test_no_automatic_timezone_or_wallclock(self):
        # There are no arguments for current timestamp, IANA name or system TZ.
        # Pure source-based settings only; the existing 0x29 encoder needs time.
        rule = format_apk_fixed_timezone(3600)
        self.assertEqual(rule, 'UTC-1')
        with self.assertRaises(TypeError):
            build_time_with_timezone(posix_rule=rule)


if __name__ == '__main__':
    unittest.main()
