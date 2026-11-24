"""Offline-only checks for APK Modern time commands 0x30 and 0x29."""
from __future__ import annotations

import unittest
from awox import build_time, build_time_with_timezone
from vector_adapter import ExtendedCommand, crc8, decode_notification, encrypt_frame
from awox.frames import build_query, open_frame
from awox.crypto import aes_att_encryption

MILLIS_2000 = 946684800000
KEY = bytes(range(16))


class TimeCodecTests(unittest.TestCase):
    def test_0x30_epoch_and_zero_offset(self):
        cmd = build_time(MILLIS_2000, 0)
        self.assertIsInstance(cmd, ExtendedCommand)
        self.assertEqual(cmd.plaintext[3:], bytes.fromhex('30 00 00 00 00 00 00 00 00 00'))
        self.assertEqual(cmd.plaintext[2], 10)

    def test_0x30_one_second_and_positive_offset(self):
        cmd = build_time(MILLIS_2000 + 1000, 3600)
        self.assertEqual(cmd.plaintext[3:], bytes.fromhex('30 01 00 00 00 10 0e 00 00 00'))

    def test_0x30_negative_offset_twos_complement(self):
        cmd = build_time(MILLIS_2000, -3600)
        self.assertEqual(cmd.plaintext[3:], bytes.fromhex('30 00 00 00 00 f0 f1 ff ff 00'))

    def test_0x30_epoch_millisecond_truncation(self):
        self.assertEqual(build_time(MILLIS_2000 + 1999, 0).plaintext,
                         build_time(MILLIS_2000 + 1000, 0).plaintext)

    def test_0x30_millis_before_2000_not_representable(self):
        with self.assertRaises(ValueError):
            build_time(MILLIS_2000 - 1, 0)

    def test_0x30_max_time_roundtrip(self):
        cmd = build_time((946684800 + 0xffffffff) * 1000, 0)
        self.assertEqual(cmd.plaintext[4:8], b'\xff' * 4)

    def test_0x30_overflow_rejected(self):
        with self.assertRaises(ValueError):
            build_time((946684800 + 0x100000000) * 1000, 0)

    def test_0x30_offset_limits(self):
        for offset in (-2147483648, 2147483647):
            self.assertEqual(int.from_bytes(build_time(MILLIS_2000, offset).plaintext[8:12],
                                            'little', signed=True), offset)
        for offset in (-2147483649, 2147483648):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                build_time(MILLIS_2000, offset)

    def test_0x30_invalid_types(self):
        for ms, offset in ((True, 0), (MILLIS_2000 + .5, 0), ('946684800000', 0),
                           (MILLIS_2000, False), (MILLIS_2000, 3.5)):
            with self.subTest(ms=ms, offset=offset), self.assertRaises(TypeError):
                build_time(ms, offset)

    def test_0x29_epoch_and_fixed_rule(self):
        cmd = build_time_with_timezone(MILLIS_2000, 'UTC-1')
        self.assertEqual(len(cmd.plaintext), 40)
        self.assertEqual(cmd.plaintext[2], 37)
        self.assertEqual(cmd.plaintext[3:8], bytes.fromhex('29 00 00 00 00'))
        self.assertEqual(cmd.plaintext[8:13], b'UTC-1')
        self.assertEqual(cmd.plaintext[13:], bytes(27))

    def test_0x29_one_second(self):
        cmd = build_time_with_timezone(MILLIS_2000 + 1000, 'UTC0')
        self.assertEqual(cmd.plaintext[4:8], b'\x01\x00\x00\x00')

    def test_0x29_exact_30_characters(self):
        cmd = build_time_with_timezone(MILLIS_2000, 'A' * 30)
        self.assertEqual(cmd.plaintext[-32:], b'A' * 30 + b'\0\0')

    def test_0x29_reject_length_and_null(self):
        for value in ('', 'A' * 31, 'UTC\0-1', ' UTC0', 'UTC0 ', 'UTC\n0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_time_with_timezone(MILLIS_2000, value)

    def test_0x29_reject_non_ascii(self):
        with self.assertRaises(ValueError):
            build_time_with_timezone(MILLIS_2000, 'Wien/München')

    def test_0x29_invalid_type(self):
        for value in (None, 1, b'UTC0'):
            with self.subTest(value=value), self.assertRaises(TypeError):
                build_time_with_timezone(MILLIS_2000, value)

    def test_0x29_invalid_timestamp(self):
        with self.assertRaises(ValueError):
            build_time_with_timezone(-1, 'UTC0')

    def test_both_queries_have_correct_crc_and_lengths(self):
        for cmd in (build_time(MILLIS_2000, 3600),
                    build_time_with_timezone(MILLIS_2000, 'UTC0')):
            self.assertEqual(cmd.plaintext[0], 2)
            self.assertEqual(cmd.plaintext[1], crc8(cmd.plaintext[2:]))
            self.assertEqual(cmd.plaintext[2], len(cmd.plaintext) - 3)

    def test_extended_crypto_matches_existing_build_query(self):
        for cmd in (build_time(MILLIS_2000, -3600),
                    build_time_with_timezone(MILLIS_2000, 'UTC0')):
            self.assertEqual(cmd.encrypt(KEY), build_query(KEY, cmd.plaintext[3], cmd.plaintext[4:]))

    def test_roundtrip_extended_query_frame_offline(self):
        for cmd in (build_time(MILLIS_2000 + 1000, 3600),
                    build_time_with_timezone(MILLIS_2000 + 1000, 'UTC0')):
            data = open_frame(KEY, cmd.encrypt(KEY))
            self.assertEqual(data.body[1:], cmd.plaintext[3:])

    def test_no_mesh_address_in_original_time_payloads(self):
        for cmd in (build_time(MILLIS_2000, 0),
                    build_time_with_timezone(MILLIS_2000, 'UTC0')):
            self.assertEqual(cmd.plaintext[3], 0x30 if len(cmd.plaintext) == 13 else 0x29)
            self.assertNotIn(b'\x61\xd3', cmd.plaintext[3:])

    def test_0x29_response_is_only_status_not_time_readback(self):
        payload = bytes.fromhex('61 d3 00') + bytes(13)
        packet = b'\x29' + aes_att_encryption(KEY, payload)
        note = decode_notification(KEY, packet)
        self.assertEqual(note.kind, 'time_with_timezone_result')
        self.assertEqual(note.value, 0)
        self.assertFalse(note.authenticated)

    def test_build_functions_never_touch_clock(self):
        # API accepts explicit input only and no defaults (no hidden now()).
        with self.assertRaises(TypeError):
            build_time()  # type: ignore
        with self.assertRaises(TypeError):
            build_time_with_timezone(MILLIS_2000)  # type: ignore


if __name__ == '__main__':
    unittest.main()
