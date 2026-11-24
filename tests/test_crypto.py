"""AES known answers and synthetic independent-engine packet vectors, all offline."""
import json
import unittest
from pathlib import Path
from awox.crypto import (
    aes128_encrypt_block, aes128_decrypt_block, aes_att_encryption,
    aes_att_decryption,
)
from awox.frames import transform_extended_packet


class CryptoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / 'fixtures' / 'crypto_vectors.json'
        cls.vectors = [{k: bytes.fromhex(v) for k, v in row.items()}
                       for row in json.loads(path.read_text(encoding='utf-8'))['vectors']]

    def test_aes128_known_answers(self):
        cases = [
            ('000102030405060708090a0b0c0d0e0f', '00112233445566778899aabbccddeeff',
             '69c4e0d86a7b0430d8cdb78070b4c55a'),
            ('00' * 16, '00' * 16, '66e94bd4ef8a2c3b884cfa59ca342b2e'),
        ]
        for key, plain, cipher in cases:
            key, plain, cipher = map(bytes.fromhex, (key, plain, cipher))
            self.assertEqual(aes128_encrypt_block(key, plain), cipher)
            self.assertEqual(aes128_decrypt_block(key, cipher), plain)

    def test_att_reverses_key_input_and_output(self):
        key = bytes.fromhex('0f0e0d0c0b0a09080706050403020100')
        plain = bytes.fromhex('ffeeddccbbaa99887766554433221100')
        cipher = bytes.fromhex('5ac5b47080b7cdd830047b6ad8e0c469')
        self.assertEqual(aes_att_encryption(key, plain), cipher)
        self.assertEqual(aes_att_decryption(key, cipher), plain)

    def test_att_independent_engine_vectors(self):
        for v in self.vectors:
            self.assertEqual(aes_att_encryption(v['key'], v['packet'][:16]), v['att_output'])
            self.assertEqual(aes_att_decryption(v['key'], v['att_output']), v['packet'][:16])

    def test_extended_packet_default_cipher(self):
        v = self.vectors[0]
        packet = b'\x42' + v['packet'][:16] + b'tail'
        self.assertEqual(transform_extended_packet(packet, v['key']),
                         b'\x42' + v['att_output'] + b'tail')

    def test_lengths_rejected_before_native_style_overread(self):
        for transform in (aes128_encrypt_block, aes128_decrypt_block,
                          aes_att_encryption, aes_att_decryption):
            for length in (0, 15, 17, 32):
                with self.assertRaises(ValueError):
                    transform(bytes(length), bytes(16))
                with self.assertRaises(ValueError):
                    transform(bytes(16), bytes(length))


if __name__ == '__main__':
    unittest.main()
