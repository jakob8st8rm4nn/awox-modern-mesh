"""Offline APK i9.e 0x35 nightlight/dawn read and missing-response contracts."""
import asyncio
import unittest
from unittest.mock import AsyncMock
from types import SimpleNamespace
from awox import AwoXMeshSession, Credentials
from vector_adapter import ExtendedCommandBuilder, ExtendedNotification, decode_notification
from awox.schedule import ScheduleRead, parse_schedule_read
from awox.crypto import aes_att_encryption
from awox.transport import ConnectionLost, OperationKind
A, B = (54113, 40157)
DEVICES = {A: '11:22:33:44:55:66', B: 'AA:BB:CC:DD:EE:99'}
KEY = bytes(range(16))

def reply(addr=A, routine=5, *, enabled=True, error=None):
    if error is not None:
        return bytes((53,)) + addr.to_bytes(2, 'little') + bytes((255, error, routine)) + bytes(11)
    return bytes((53,)) + addr.to_bytes(2, 'little') + bytes((routine | (128 if enabled else 0), 1 | 30 << 2, 6, 128 | 2 | 8, 10, 1, 50, 153, 0, 16)) + bytes(4)

class ReadCompletenessTests(unittest.TestCase):

    def test_completion_requires_matching_target_ids(self):
        for target in (A, B):
            for name, routine in (('timer', 2), ('program', 3)):
                for response_target in (A, B):
                    with self.subTest(target=target, name=name, response=response_target):
                        start = parse_schedule_read(reply(addr=response_target, routine=routine))
                        self.assertEqual(ScheduleRead(target, name, start, None).complete, response_target == target)
            for name, first, last in (('nightlight', 5, 6), ('dawn_simulator', 7, 8)):
                for start_target in (A, B):
                    for end_target in (A, B):
                        with self.subTest(target=target, name=name, start=start_target, end=end_target):
                            start = parse_schedule_read(reply(addr=start_target, routine=first))
                            end = parse_schedule_read(reply(addr=end_target, routine=last))
                            self.assertEqual(ScheduleRead(target, name, start, end).complete, start_target == end_target == target)

    def test_pairs_require_the_exact_start_and_end_routines(self):
        for name, expected in (('nightlight', (5, 6)), ('dawn_simulator', (7, 8))):
            for first in (2, 3, 5, 6, 7, 8):
                for last in (2, 3, 5, 6, 7, 8):
                    with self.subTest(name=name, first=first, last=last):
                        value = ScheduleRead(A, name, parse_schedule_read(reply(routine=first)), parse_schedule_read(reply(routine=last)))
                        self.assertEqual(value.complete, (first, last) == expected)

    def test_single_routines_still_require_their_one_record(self):
        for name, expected in (('timer', 2), ('program', 3)):
            for routine in (2, 3, 5, 6, 7, 8):
                with self.subTest(name=name, routine=routine):
                    part = parse_schedule_read(reply(routine=routine))
                    self.assertEqual(ScheduleRead(A, name, part, None).complete, routine == expected)
                    self.assertFalse(ScheduleRead(A, name, part, part).complete)

    def test_correct_pairs_need_both_valid_responses(self):
        for name, first, last in (('nightlight', 5, 6), ('dawn_simulator', 7, 8)):
            start = parse_schedule_read(reply(routine=first))
            end = parse_schedule_read(reply(routine=last))
            with self.subTest(name=name):
                self.assertTrue(ScheduleRead(A, name, start, end).complete)
                self.assertFalse(ScheduleRead(A, name, start, None).complete)
                self.assertFalse(ScheduleRead(A, name, parse_schedule_read(reply(routine=first, error=148)), end).complete)
                self.assertFalse(ScheduleRead(A, name, start, parse_schedule_read(reply(routine=last, error=148))).complete)

    def test_unknown_property_cannot_be_complete(self):
        self.assertFalse(ScheduleRead(A, 'unknown', parse_schedule_read(reply(routine=5)), parse_schedule_read(reply(routine=6))).complete)

class CodecTests(unittest.TestCase):

    def test_apk_query_vector_all_four_routines(self):
        for routine in (2, 3, 5, 6, 7, 8):
            cmd = ExtendedCommandBuilder(A).schedule_get(routine)
            self.assertEqual(cmd.plaintext[3:], bytes((53,)) + A.to_bytes(2, 'little') + bytes((routine,)))
            self.assertEqual(cmd.plaintext[2], 4)

    def test_query_rejects_invalid_routine_without_sending(self):
        for routine in (0, 1, 4, 9, 255, -1, '5', True, None):
            with self.subTest(routine=routine), self.assertRaises(ValueError):
                ExtendedCommandBuilder(A).schedule_get(routine)

    def test_real_encrypted_1911_decoder_dispatch(self):
        raw = reply()
        packet = raw[:1] + aes_att_encryption(KEY, raw[1:17])
        notification = decode_notification(KEY, packet)
        self.assertEqual(notification.kind, 'schedule_read')
        self.assertEqual(notification.value, raw)
        self.assertEqual(parse_schedule_read(notification.value).routine_id, 5)

    def test_normal_answer_fields_and_preserves_raw(self):
        raw = reply()
        part = parse_schedule_read(raw)
        self.assertEqual((part.mesh_id, part.routine_id, part.enabled, part.error_code), (A, 5, True, None))
        self.assertEqual((part.time_mode, part.hour, part.minute, part.minutes), (1, 6, 30, None))
        self.assertEqual((part.repeat, part.weekdays_mask, part.fade_minutes), (True, 10, 10))
        self.assertEqual((part.light_fields, part.current_part, part.total_part), (bytes((1, 50, 153, 0)), 0, 1))
        self.assertEqual(part.raw_response, raw)

    def test_duration_format_and_disabled_flag(self):
        raw = bytearray(reply(enabled=False))
        raw[4] = 32
        raw[5] = 35
        part = parse_schedule_read(raw)
        self.assertFalse(part.enabled)
        self.assertEqual(part.time_mode, 0)
        self.assertEqual(part.minutes, 547)
        self.assertIsNone(part.hour)

    def test_device_error_is_explicit_not_disabled(self):
        part = parse_schedule_read(reply(error=148))
        self.assertEqual(part.error_code, 148)
        self.assertFalse(part.valid)
        self.assertIsNone(part.enabled)
        self.assertIsNone(part.time_mode)
        self.assertEqual(part.routine_id, 5)

    def test_rejects_malformed_or_unrelated_reply(self):
        for raw in (b'', b'5', b'5\x00\x00\x85\x00\x00', b'4' + reply()[1:], reply(routine=4), b'5\x00\x00\xff\x01\x04'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_schedule_read(raw)
if __name__ == '__main__':
    unittest.main()
