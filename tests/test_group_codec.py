"""Offline group membership codec checks against both original APKs.

1.14.11: i9.c.c / i9.n.c / g9.c.b; 1.14.10: j9.c.c / j9.n.c / h9.c.b.
Receive bytes: DeviceSettingsActivity.onRead / g9.j.e.
No hardware, provisioning, group mutation, or cloud activity.
"""
import unittest

from awox.crypto import aes_att_encryption
from vector_adapter import (
    ExtendedCommandBuilder, crc8, decode_notification,
    parse_mesh_groups_get, query_frame,
)
from awox.frames import build_query


KEY = bytes(range(16))


class GroupCodecTests(unittest.TestCase):
    def test_membership_query_has_08_and_three_zero_bytes(self):
        command = ExtendedCommandBuilder(0xD361).get_mesh_groups()
        self.assertEqual(command.plaintext, query_frame(bytes.fromhex('0861d3000000')))
        self.assertEqual(command.plaintext[0], 2)
        self.assertEqual(command.plaintext[1], crc8(command.plaintext[2:]))
        self.assertEqual(command.encrypt(KEY),
                         build_query(KEY, 0x08, bytes.fromhex('61d3000000')))

    def test_membership_list_mixed_endianness_and_count(self):
        command = ExtendedCommandBuilder(0xD361).set_mesh_groups([0x8000, 0x80FE, 0x8100])
        self.assertEqual(command.plaintext[3:], bytes.fromhex('0c61d303800080fe8100'))
        self.assertEqual(command.plaintext, query_frame(bytes.fromhex('0c61d303800080fe8100')))
        self.assertEqual(command.plaintext[0], 2)
        self.assertEqual(command.plaintext[1], crc8(command.plaintext[2:]))

    def test_group_count_and_limit_follow_encoded_entries(self):
        class FilteredGroups(list):
            def __iter__(self):
                yield self[0]

        class ExpandedGroups(tuple):
            def __iter__(self):
                return iter([0x8000] * 126)

        builder = ExtendedCommandBuilder(0x1234)
        command = builder.set_mesh_groups(FilteredGroups([0x8000, 0x8001]))
        self.assertEqual(command.plaintext[3:], bytes.fromhex('0c3412018000'))
        with self.assertRaisesRegex(ValueError, 'one-byte APK frame limit'):
            builder.set_mesh_groups(ExpandedGroups((0x8000,)))

    def test_empty_list_replaces_with_zero_groups(self):
        command = ExtendedCommandBuilder(0x1234).set_mesh_groups([])
        self.assertEqual(command.plaintext[3:], bytes.fromhex('0c341200'))

    def test_order_and_duplicates_preserved_without_guessing_firmware_policy(self):
        command = ExtendedCommandBuilder(0x1234).set_mesh_groups([0x80FF, 0x8000, 0x80FF])
        self.assertEqual(command.plaintext[3:], bytes.fromhex('0c34120380ff800080ff'))

    def test_length_boundary_is_explicit_not_silent_overflow(self):
        command = ExtendedCommandBuilder(0x1234).set_mesh_groups([0x8000] * 125)
        self.assertEqual(command.plaintext[2], 254)
        self.assertEqual(len(command.plaintext), 257)
        with self.assertRaises(ValueError):
            ExtendedCommandBuilder(0x1234).set_mesh_groups([0x8000] * 126)

    def test_wrong_group_argument_types_rejected(self):
        b = ExtendedCommandBuilder(0x1234)
        for bad in (None, '8000', (x for x in [0x8000])):
            with self.subTest(bad=repr(bad)), self.assertRaises(TypeError):
                b.set_mesh_groups(bad)
        for invalid in ([True], [-1], [65536], [0x8000, '0x8001'], [1.2]):
            with self.subTest(bad=invalid), self.assertRaises(ValueError):
                b.set_mesh_groups(invalid)

    def test_get_reply_address_count_and_little_endian_groups(self):
        raw = bytes.fromhex('0861d300038000fe800081') + b'unchanged'
        parsed = parse_mesh_groups_get(raw)
        self.assertEqual(parsed.mesh_id, 0xD361)
        self.assertEqual(parsed.group_addresses, (0x0080, 0x80FE, 0x8100))
        self.assertEqual(parsed.raw_response, raw)

    def test_empty_reply_and_truncated_or_wrong_opcode(self):
        parsed = parse_mesh_groups_get(bytes.fromhex('0861d30000'))
        self.assertEqual(parsed.group_addresses, ())
        for bad in (b'', b'\x08\x61\xd3', bytes.fromhex('0861d3000180'),
                    bytes.fromhex('0c61d30000')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_mesh_groups_get(bad)
        with self.assertRaises(TypeError):
            parse_mesh_groups_get('0861d30000')

    def test_encrypted_08_notification_still_preserves_raw_packet(self):
        payload = bytes.fromhex('61d3000280000180') + bytes(8)
        note = decode_notification(KEY, b'\x08' + aes_att_encryption(KEY, payload))
        self.assertEqual(note.kind, 'get_mesh_groups')
        self.assertEqual(note.value, b'\x08' + payload)
        parsed = parse_mesh_groups_get(note.value)
        self.assertEqual(parsed.mesh_id, 0xD361)
        self.assertEqual(parsed.group_addresses, (0x0080, 0x8001))
        self.assertFalse(note.authenticated)

    def test_0c_result_remains_separate_from_get_reply(self):
        payload = bytes.fromhex('61d300') + bytes(13)
        note = decode_notification(KEY, b'\x0c' + aes_att_encryption(KEY, payload))
        self.assertEqual(note.kind, 'mesh_groups_result')
        self.assertEqual(note.value, (0xD361, 0))
        self.assertFalse(note.authenticated)
