"""APK 1.14.10/1.14.11 0x33 schedule writes; OFFLINE fake-GATT only."""
import asyncio
from dataclasses import replace
import unittest
from unittest.mock import AsyncMock
from awox import ScheduleWritePart, ScheduleWriteResult, ScheduleSetResponse, parse_schedule_set
from vector_adapter import ExtendedCommandBuilder, ExtendedNotification, decode_notification
from awox.crypto import aes_att_encryption
from awox.session import Credentials
from awox.transport import ConnectionLost, OperationKind
from awox.schedule import parse_schedule_read
A, B = (54113, 40157)
KEY = bytes(range(16))
KNOWN = {A: '11:22:33:44:55:66', B: 'AA:BB:CC:DD:EE:99'}
# These are actual hardware 0x35 readback payloads from EGLO-ZM-RGB-TW,
# with no keys, credentials, or encrypted BLE blocks.
NIGHT_START = bytes.fromhex('35 61 d3 05 01 16 ff 05 03 32 a2 fe 00 00 00 00 00 00 00 00')
NIGHT_END = bytes.fromhex('35 61 d3 06 01 02 ff 00 00 ff ff ff 00 00 00 00 00 00 00 00')
DAWN_START = bytes.fromhex('35 61 d3 07 01 08 be 1e 01 46 72 01 00 00 00 00 00 00 00 00')
DAWN_END = bytes.fromhex('35 61 d3 08 79 09 be 00 00 ff ff ff 00 00 00 00 00 00 00 00')

def from_capture(raw):
    return ScheduleWritePart.from_read(parse_schedule_read(raw))

def reply(addr=A, code=0, routine=5, action=51):
    return bytes((51,)) + addr.to_bytes(2, 'little') + bytes((code, action, routine)) + bytes(12)

class WriteCompletenessTests(unittest.TestCase):

    def test_completion_requires_matching_target_ids(self):
        for target in (A, B):
            for name, routine in (('timer', 2), ('program', 3)):
                for response_target in (A, B):
                    with self.subTest(target=target, name=name, response=response_target):
                        start = parse_schedule_set(reply(addr=response_target, routine=routine, code=0))
                        self.assertEqual(ScheduleWriteResult(target, name, start, None, False).complete, response_target == target)
            for name, first, last in (('nightlight', 5, 6), ('dawn_simulator', 7, 8)):
                for start_target in (A, B):
                    for end_target in (A, B):
                        with self.subTest(target=target, name=name, start=start_target, end=end_target):
                            start = parse_schedule_set(reply(addr=start_target, routine=first, code=153))
                            end = parse_schedule_set(reply(addr=end_target, routine=last, code=0))
                            self.assertEqual(ScheduleWriteResult(target, name, start, end, True).complete, start_target == end_target == target)

    def test_pairs_require_the_exact_start_and_end_routines(self):
        for name, expected in (('nightlight', (5, 6)), ('dawn_simulator', (7, 8))):
            for first in (2, 3, 5, 6, 7, 8):
                for last in (2, 3, 5, 6, 7, 8):
                    with self.subTest(name=name, first=first, last=last):
                        start = parse_schedule_set(reply(code=153, routine=first))
                        end = parse_schedule_set(reply(code=0, routine=last))
                        self.assertEqual(ScheduleWriteResult(A, name, start, end, True).complete, (first, last) == expected)

    def test_single_routines_still_require_one_positive_response(self):
        for name, expected in (('timer', 2), ('program', 3)):
            for routine in (2, 3, 5, 6, 7, 8):
                for code in (0, 153, 148):
                    with self.subTest(name=name, routine=routine, code=code):
                        response = parse_schedule_set(reply(code=code, routine=routine))
                        self.assertEqual(ScheduleWriteResult(A, name, response, None, False).complete, routine == expected and code == 0)
                        self.assertFalse(ScheduleWriteResult(A, name, response, None, True).complete)
                        self.assertFalse(ScheduleWriteResult(A, name, response, response, False).complete)

    def test_correct_pairs_need_continuation_final_success_and_sent_end(self):
        for name, first, last in (('nightlight', 5, 6), ('dawn_simulator', 7, 8)):
            for start_code in (0, 153, 148):
                for end_code in (0, 153, 148):
                    for sent in (False, True):
                        with self.subTest(name=name, start=start_code, end=end_code, sent=sent):
                            start = parse_schedule_set(reply(code=start_code, routine=first))
                            end = parse_schedule_set(reply(code=end_code, routine=last))
                            self.assertEqual(ScheduleWriteResult(A, name, start, end, sent).complete, sent and start_code == 153 and (end_code == 0))
            with self.subTest(name=name, missing=True):
                start = parse_schedule_set(reply(code=153, routine=first))
                end = parse_schedule_set(reply(code=0, routine=last))
                self.assertFalse(ScheduleWriteResult(A, name, None, end, True).complete)
                self.assertFalse(ScheduleWriteResult(A, name, start, None, True).complete)

    def test_unknown_property_cannot_be_complete(self):
        start = parse_schedule_set(reply(code=153, routine=5))
        end = parse_schedule_set(reply(code=0, routine=6))
        self.assertFalse(ScheduleWriteResult(A, 'unknown', start, end, True).complete)

class CodecTest(unittest.TestCase):

    def test_original_readbacks_produce_exact_0x33_write_fields(self):
        for source in (NIGHT_START, NIGHT_END, DAWN_START, DAWN_END):
            with self.subTest(source=source[:4]):
                packet = ExtendedCommandBuilder(A).schedule_set(from_capture(source)).plaintext
                self.assertEqual(packet[3:], b'3' + source[1:13])
                self.assertEqual(packet[2], 13)

    def test_enable_changes_only_one_bit(self):
        p = from_capture(NIGHT_START)
        self.assertFalse(p.enabled)
        enabled = p.with_enabled(True)
        self.assertTrue(enabled.enabled)
        self.assertEqual(enabled.settings[0], p.settings[0] | 128)
        self.assertEqual(enabled.settings[1:], p.settings[1:])
        self.assertEqual(enabled.with_enabled(False), p)

    def test_clock_changes_only_apk_hour_minute_fields(self):
        p = from_capture(DAWN_END)
        changed = p.with_clock_time(13, 45)
        self.assertEqual(changed.settings[1], p.settings[1] & 3 | 45 << 2)
        self.assertEqual(changed.settings[2], p.settings[2] & 224 | 13)
        self.assertEqual(changed.settings[:1] + changed.settings[3:], p.settings[:1] + p.settings[3:])

    def test_duration_mode_cannot_be_edited_as_clock(self):
        p = from_capture(NIGHT_START)
        x = bytearray(p.settings)
        x[1] &= 252
        with self.assertRaises(ValueError):
            ScheduleWritePart(bytes(x)).with_clock_time(12, 0)

    def test_weekday_and_repeat_only_update_byte_three(self):
        p = from_capture(DAWN_START)
        changed = p.with_weekdays(127, False)
        self.assertEqual(changed.settings[3], 127)
        self.assertEqual(changed.settings[:3] + changed.settings[4:], p.settings[:3] + p.settings[4:])
        self.assertEqual(changed.with_weekdays(0, True).settings[3], 128)

    def test_input_validation(self):
        for val in (b'', b'\x05' * 9, b'\x05' * 11, 'x' * 10, None):
            with self.subTest(val=val), self.assertRaises(ValueError):
                ScheduleWritePart(val)
        for rid in (0, 4, 9, 127):
            with self.subTest(rid=rid), self.assertRaises(ValueError):
                ScheduleWritePart(bytes((rid,)) + bytes(9))
        p = from_capture(NIGHT_START)
        for val in (1, 0, None, 'yes'):
            with self.subTest(enabled=val), self.assertRaises(TypeError):
                p.with_enabled(val)
        for time in ((24, 0), (-1, 2), (12, 60), (True, 5)):
            with self.subTest(time=time), self.assertRaises(ValueError):
                p.with_clock_time(*time)
        for mask, repeat in ((128, True), (-1, True), (True, False), (3, 1)):
            with self.subTest(mask=mask, repeat=repeat), self.assertRaises((TypeError, ValueError)):
                p.with_weekdays(mask, repeat)
        with self.assertRaises(TypeError):
            ExtendedCommandBuilder(A).schedule_set(b'\x00' * 10)

    def test_parse_success_0x99_and_unknown_code(self):
        a = parse_schedule_set(reply(code=153))
        self.assertEqual((a.mesh_id, a.routine_id, a.status_code, a.action), (A, 5, 153, 51))
        self.assertFalse(a.success)
        self.assertTrue(a.requires_followup)
        b = parse_schedule_set(reply(code=0, routine=6))
        self.assertTrue(b.success)
        self.assertFalse(b.requires_followup)
        c = parse_schedule_set(reply(code=148))
        self.assertFalse(c.success)
        self.assertFalse(c.requires_followup)
        self.assertEqual(c.status_code, 148)

    def test_ack_action_is_the_received_byte_not_a_part_counter(self):
        # Real timer ACK: 33 DD 9C 00 33 02 followed by unused trailer.
        raw = bytes.fromhex('33 dd 9c 00 33 02') + bytes(14)
        result = parse_schedule_set(raw)
        self.assertEqual(result.mesh_id, 40157)
        self.assertEqual(result.action, 51)
        self.assertEqual(result.raw_response, raw)
        self.assertNotIn('current_part', result.__dataclass_fields__)
        self.assertEqual(parse_schedule_set(reply(action=106)).action, 106)

    def test_parse_rejects_unrelated_responses(self):
        for raw in (b'', b'3', b'5' + reply()[1:], reply(routine=4), b'3a\xd3\x99\x00'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_schedule_set(raw)

    def test_decryption_routes_0x33_without_claiming_success(self):
        raw = reply(code=153)
        packet = raw[:1] + aes_att_encryption(KEY, raw[1:17]) + raw[17:]
        notice = decode_notification(KEY, packet)
        self.assertEqual(notice.kind, 'schedule_set')
        self.assertEqual(notice.value, raw)
        self.assertTrue(parse_schedule_set(notice.value).requires_followup)

    def test_no_unwanted_frame_adjustments(self):
        p = from_capture(DAWN_START)
        q = ExtendedCommandBuilder(A).schedule_set(p)
        self.assertEqual(len(q.plaintext), 16)
        self.assertEqual(q.plaintext[3], 51)
        self.assertEqual(q.plaintext[4:6], b'a\xd3')
        self.assertEqual(q.plaintext[6:], p.settings)
if __name__ == '__main__':
    unittest.main()
