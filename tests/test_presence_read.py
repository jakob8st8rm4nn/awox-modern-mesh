"""APK 1.14.10/11 read-only Modern 0x3C presence: bytes, routing, safety."""
import asyncio
import unittest
from awox import AwoXMeshSession, Credentials, PresenceRead
from awox.crypto import aes_att_encryption
from vector_adapter import ExtendedCommandBuilder, ExtendedNotification, decode_notification
from awox.presence import parse_presence_read
from awox.transport import ConnectionLost
A, B = (54113, 40157)
KNOWN = {A: '11:22:33:44:55:66', B: 'AA:BB:CC:DD:EE:99'}
KEY = bytes(range(16))

def presence(addr=A, *, enabled=False, routine=1, err=None, bits=None):
    if err is not None:
        return b'<' + addr.to_bytes(2, 'little') + bytes((255, err, routine)) + bytes(11)
    if bits is None:
        bits = bytes((1, 128, 0, 1, 3, 128))
    assert len(bits) == 6
    return b'<' + addr.to_bytes(2, 'little') + bytes((routine | (128 if enabled else 0), 190)) + bytes.fromhex('03 64 11 fe') + bits + bytes((1, 33))

class CodecTests(unittest.TestCase):

    def test_apk_query_exact_bytes(self):
        frame = ExtendedCommandBuilder(A).presence_get().plaintext
        self.assertEqual(frame[2:], bytes.fromhex('04 3c 61 d3 01'))

    def test_query_not_schedule_query(self):
        self.assertNotEqual(ExtendedCommandBuilder(A).presence_get().plaintext, ExtendedCommandBuilder(A).schedule_get(3).plaintext)

    def test_routine_and_all_fields(self):
        raw = presence(enabled=True)
        obj = parse_presence_read(raw)
        self.assertIsInstance(obj, PresenceRead)
        self.assertEqual((obj.mesh_id, obj.routine_id, obj.enabled), (A, 1, True))
        self.assertEqual((obj.repeat, obj.weekdays_mask), (True, 62))
        self.assertEqual(obj.light_fields, bytes.fromhex('03 64 11 fe'))
        self.assertEqual((obj.current_part, obj.total_part), (1, 2))
        self.assertTrue(obj.random_enabled)
        self.assertEqual(len(obj.half_hour_slots), 48)
        self.assertEqual(obj.half_hour_slots[0], True)
        self.assertEqual(obj.half_hour_slots[7], False)
        self.assertEqual(obj.half_hour_slots[15], True)
        self.assertEqual(obj.half_hour_slots[24], True)
        self.assertEqual(obj.half_hour_slots[47], True)
        self.assertEqual(obj.raw_response, raw)
        self.assertTrue(obj.valid)

    def test_disabled_still_valid(self):
        obj = parse_presence_read(presence())
        self.assertFalse(obj.enabled)
        self.assertIsNone(obj.error_code)

    def test_absent_all_slots_is_not_error(self):
        obj = parse_presence_read(presence(bits=bytes(6)))
        self.assertEqual(sum(obj.half_hour_slots), 0)
        self.assertTrue(obj.valid)

    def test_error_preserves_original_status_and_unknown_enabled(self):
        raw = presence(err=148)
        obj = parse_presence_read(raw)
        self.assertEqual((obj.mesh_id, obj.routine_id, obj.error_code), (A, 1, 148))
        self.assertIsNone(obj.enabled)
        self.assertIsNone(obj.half_hour_slots)
        self.assertFalse(obj.valid)
        self.assertEqual(obj.raw_response, raw)

    def test_nonroutine_error_rejected(self):
        with self.assertRaises(ValueError):
            parse_presence_read(presence(err=9, routine=2))

    def test_wrong_normal_routine_rejected(self):
        with self.assertRaises(ValueError):
            parse_presence_read(presence(routine=3))

    def test_truncated_reply_rejected(self):
        for n in (0, 1, 2, 3, 4, 5, 6, 10, 16):
            with self.subTest(n=n), self.assertRaises(ValueError):
                parse_presence_read(presence()[:n])

    def test_wrong_opcode_rejected(self):
        with self.assertRaises(ValueError):
            parse_presence_read(b'5' + presence()[1:])

    def test_bad_type_rejected(self):
        for value in ('3c', None, [60]):
            with self.subTest(value=value), self.assertRaises(TypeError):
                parse_presence_read(value)

    def test_trailing_bytes_preserved(self):
        raw = presence() + bytes.fromhex('ab cd ef')
        self.assertEqual(parse_presence_read(raw).raw_response, raw)

    def test_full_encrypted_notification_classifies_presence(self):
        raw = presence()
        encrypted = bytes((60,)) + aes_att_encryption(KEY, raw[1:17])
        decoded = decode_notification(KEY, encrypted)
        self.assertEqual(decoded.kind, 'presence_read')
        self.assertEqual(decoded.value, raw)
if __name__ == '__main__':
    unittest.main()
