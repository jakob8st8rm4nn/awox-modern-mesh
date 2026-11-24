"""Command decoder accepts exactly one padded frame, without extra tail data."""
import unittest

from awox.crypto import aes_att_encryption
from vector_adapter import ExtendedCommandBuilder
from awox.frames import crc8, open_frame, seal_frame


class CommandFrameExactLengthTests(unittest.TestCase):
    KEY = bytes(range(16))

    def test_all_length_values_and_flags_roundtrip(self):
        for length in range(256):
            body = bytes((length,)) + bytes(range(length))
            for flag in (0, 1, 2):
                with self.subTest(length=length, flag=flag):
                    packet = seal_frame(self.KEY, flag, body)
                    decoded = open_frame(self.KEY, packet)
                    self.assertEqual(decoded.body, body)
                    self.assertEqual(decoded.flag, flag)
                    self.assertEqual(len(packet), 1 + max(16, length + 2))

    def test_appended_data_is_rejected_for_every_length(self):
        for length in range(256):
            packet = seal_frame(self.KEY, 2, bytes((length,)) + bytes(range(length)))
            for tail in (b"\x00", bytes.fromhex('deadbeef')):
                with self.subTest(length=length, tail=tail):
                    with self.assertRaisesRegex(ValueError, 'packet size'):
                        open_frame(self.KEY, packet + tail)

    def test_missing_tail_data_is_rejected(self):
        for length in range(15, 256):
            packet = seal_frame(self.KEY, 2, bytes((length,)) + bytes(range(length)))
            with self.subTest(length=length):
                with self.assertRaisesRegex(ValueError, 'packet size'):
                    open_frame(self.KEY, packet[:-1])

    def test_exact_length_still_requires_valid_crc(self):
        body = b"\x01\x0a"
        clear = bytes((crc8(body) ^ 1,)) + body
        packet = b"\x02" + aes_att_encryption(self.KEY, clear.ljust(16, b"\x00"))
        with self.assertRaisesRegex(ValueError, 'CRC8 mismatch'):
            open_frame(self.KEY, packet)

    def test_extended_command_encoder_remains_compatible(self):
        for command in (ExtendedCommandBuilder(0x1234).status_query(),
                        ExtendedCommandBuilder(0x1234).set_mesh_groups((0x8000, 0x8001, 0x8002))):
            decoded = open_frame(self.KEY, command.encrypt(self.KEY))
            self.assertEqual(decoded.flag, command.plaintext[0])
            self.assertEqual(decoded.body, command.plaintext[2:])
