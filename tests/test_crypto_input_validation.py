"""Validate real byte counts for binary buffers at all four AES entry points."""
from array import array
import unittest

from awox.crypto import (aes128_encrypt_block, aes128_decrypt_block,
                         aes_att_encryption, aes_att_decryption)

TRANSFORMS = (aes128_encrypt_block, aes128_decrypt_block, aes_att_encryption, aes_att_decryption)
ZERO_CIPHER = bytes.fromhex('66e94bd4ef8a2c3b884cfa59ca342b2e')


class CryptoInputValidationTests(unittest.TestCase):
    def test_sixteen_multibyte_elements_are_not_a_sixteen_byte_block(self):
        view = memoryview(array('I', range(16)))
        self.assertEqual(len(view), 16)
        self.assertNotEqual(view.nbytes, 16)
        for transform in TRANSFORMS:
            for key, data in ((view, bytes(16)), (bytes(16), view)):
                with self.subTest(transform=transform.__name__, key_size=len(bytes(key)), data_size=len(bytes(data))):
                    with self.assertRaises(ValueError): transform(key, data)

    def test_buffers_with_sixteen_actual_bytes_match_known_aes_vector(self):
        buffers = (bytes(16), bytearray(16), memoryview(bytes(16)),
                   memoryview(bytearray(16)).cast('I'),
                   memoryview(bytearray(16)).cast('B', shape=(4, 4)))
        for key in buffers:
            for data in buffers:
                with self.subTest(key_format=type(key), data_format=type(data)):
                    self.assertEqual(aes128_encrypt_block(key, data), ZERO_CIPHER)
                    self.assertEqual(aes_att_encryption(key, data), ZERO_CIPHER[::-1])
            self.assertEqual(aes128_decrypt_block(key, ZERO_CIPHER), bytes(16))
            self.assertEqual(aes_att_decryption(key, ZERO_CIPHER[::-1]), bytes(16))

    def test_non_buffer_inputs_are_rejected(self):
        for invalid in (16, True, None, '0' * 16, [0] * 16, (0,) * 16):
            for transform in TRANSFORMS:
                with self.subTest(transform=transform.__name__, input_type=type(invalid)):
                    with self.assertRaises(TypeError): transform(invalid, bytes(16))
                    with self.assertRaises(TypeError): transform(bytes(16), invalid)

    def test_mutable_input_buffers_are_not_modified(self):
        for transform in TRANSFORMS:
            key, data = bytearray(range(16)), bytearray(range(16, 32))
            before = bytes(key), bytes(data)
            result = transform(key, data)
            self.assertIsInstance(result, bytes)
            self.assertEqual((bytes(key), bytes(data)), before)
