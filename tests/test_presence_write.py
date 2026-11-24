"""APK 1.14.10/11 presence 0x3B write: bytes, ACK routing, errors, no retries."""
import asyncio
import unittest
from awox import AwoXMeshSession, Credentials, PresenceWritePart, PresenceSetResponse, parse_presence_read, parse_presence_set
from awox.crypto import aes_att_encryption
from vector_adapter import ExtendedCommandBuilder, ExtendedNotification, decode_notification
from awox.transport import ConnectionLost, OperationKind
A, B = (54113, 40157)
KNOWN = {A: '11:22:33:44:55:66', B: 'AA:BB:CC:DD:EE:99'}
ORIGINAL = bytes.fromhex('3c 61 d3 01 ff e9 50 b9 00 00 00 0f 0f c0 3f 84 00 00 00 00')
PART = PresenceWritePart.from_read(parse_presence_read(ORIGINAL))
MODIFIED = PART.with_half_hour_slot(20, True)

def ack(addr=A, status=0, routine=1, action=59):
    return b';' + addr.to_bytes(2, 'little') + bytes((status, action, routine)) + bytes(14)

class CodecTests(unittest.TestCase):

    def test_exact_apk_payload_from_original_hardware(self):
        self.assertEqual(PART.settings.hex(' '), '01 ff e9 50 b9 00 00 00 0f 0f c0 3f 84 00')
        self.assertEqual(ExtendedCommandBuilder(A).presence_set(PART).plaintext[2:], bytes.fromhex('11 3b 61 d3 01 ff e9 50 b9 00 00 00 0f 0f c0 3f 84 00'))
        self.assertEqual(ExtendedCommandBuilder(A).presence_set(MODIFIED).plaintext[2:], bytes.fromhex('11 3b 61 d3 01 ff e9 50 b9 00 00 00 1f 0f c0 3f 84 00'))

    def test_only_one_slot_changes_and_raw_bits_preserved(self):
        self.assertFalse(PART.enabled)
        self.assertEqual(sum((a != b for a, b in zip(PART.settings, MODIFIED.settings))), 1)
        self.assertEqual(PART.settings[6:12], bytes.fromhex('00 00 0f 0f c0 3f'))
        self.assertEqual(MODIFIED.settings[6:12], bytes.fromhex('00 00 1f 0f c0 3f'))
        self.assertEqual(MODIFIED.with_half_hour_slot(20, False), PART)
        self.assertEqual(MODIFIED.with_half_hour_slot(20, True), MODIFIED)
        self.assertEqual(MODIFIED.settings[12:], PART.settings[12:])
        self.assertEqual(PART.with_enabled(True).settings[0], 129)

    def test_all_48_slots_are_addressable(self):
        for i in range(48):
            with self.subTest(i=i):
                new = PresenceWritePart(bytes.fromhex('01') + bytes(13)).with_half_hour_slot(i, True)
                self.assertEqual(new.settings[6 + i // 8], 1 << i % 8)
                self.assertEqual(sum((x.bit_count() for x in new.settings[6:12])), 1)

    def test_reject_bad_parts_and_slot_types(self):
        for val in (b'', b'1' * 13, b'1' * 15, '123', None):
            with self.subTest(val=val), self.assertRaises(ValueError):
                PresenceWritePart(val)
        with self.assertRaises(ValueError):
            PresenceWritePart(b'\x02' + bytes(13))
        for index in (-1, 48, True, 1.5, '3'):
            with self.subTest(index=index), self.assertRaises(ValueError):
                PART.with_half_hour_slot(index, True)
        for flag in (1, None, 'yes'):
            with self.subTest(flag=flag), self.assertRaises(TypeError):
                PART.with_half_hour_slot(1, flag)
        with self.assertRaises(TypeError):
            ExtendedCommandBuilder(A).presence_set(b'\x01' + bytes(13))

    def test_from_read_rejects_error_and_unknown(self):
        with self.assertRaises(ValueError):
            PresenceWritePart.from_read(None)
        with self.assertRaises(ValueError):
            PresenceWritePart.from_read(parse_presence_read(b'<a\xd3\xff\x94\x01'))

    def test_ack_status_opcode_and_target_fields(self):
        result = parse_presence_set(ack())
        self.assertIsInstance(result, PresenceSetResponse)
        self.assertTrue(result.success)
        self.assertEqual((result.mesh_id, result.status_code, result.action, result.routine_id), (A, 0, 59, 1))
        self.assertFalse(parse_presence_set(ack(status=148)).success)
        self.assertFalse(parse_presence_set(ack(status=153)).success)
        for raw in (ack()[:5], ack(routine=2), b'3' + ack()[1:]):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_presence_set(raw)
        with self.assertRaises(TypeError):
            parse_presence_set('3b')

    def test_ack_action_is_received_raw_field_not_a_part_counter(self):
        # APK 0x3B ACK: byte 4 is named action, observed as 0x3B.
        raw = bytes.fromhex('3b 61 d3 00 3b 01') + bytes(14)
        result = parse_presence_set(raw)
        self.assertEqual(result.action, 59)
        self.assertEqual(result.raw_response, raw)
        self.assertNotIn('current_part', result.__dataclass_fields__)
        self.assertEqual(parse_presence_set(ack(action=86)).action, 86)

    def test_encrypted_reply_classified_only_as_presence_set(self):
        key = bytes(range(16))
        packet = ack()
        notification = decode_notification(key, b';' + aes_att_encryption(key, packet[1:17]))
        self.assertEqual(notification.kind, 'presence_set')
        self.assertEqual(notification.value, packet[:17])
