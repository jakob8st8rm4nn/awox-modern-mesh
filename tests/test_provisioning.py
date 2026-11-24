"""APK lifecycle wire and failure-boundary tests; no BLE/network/hardware."""
import asyncio
import hashlib
import unittest
from awox import AwoXMeshSession, Credentials, ProvisioningSettings, factory_credentials
from awox.crypto import aes_att_decryption, aes_att_encryption
from vector_adapter import ExtendedCommandBuilder, decode_notification
from awox.frames import COMMAND_UUID, NOTIFY_UUID, PAIR_UUID, SERVICE_UUID
from awox.model_codes import registered_model_code
from awox.model_registry import _MODELS
from awox.authentication import derive_session_key, login_request
from awox.provisioning import build_network_key, build_provision_network
from awox.transport import ConnectionLost, MissingCharacteristic
ID = 4660
MAC = '11:22:33:44:55:66'
CREDS = Credentials('old', 'password')
RANDOM = bytes(range(8))
ANSWER = b'\r' + bytes(range(8, 16))
KEY = derive_session_key(CREDS.name, CREDS.password, RANDOM, ANSWER)
SETTINGS = ProvisioningSettings(Credentials('ABCDEF', 'new'), bytes(range(16)))

def session(transport):
    return ProvisioningSession(transport, CREDS, random_bytes=lambda n: RANDOM)

class CodecTests(unittest.TestCase):

    def test_binary_credentials_are_exact_not_utf8_reencoded(self):
        binary = bytes(range(240, 256))
        creds = Credentials(b'mesh', binary)
        secret = bytes((a ^ b for a, b in zip(b'mesh'.ljust(16, b'\x00'), binary)))
        expected = b'\x0c' + RANDOM + aes_att_encryption(RANDOM + bytes(8), secret)[:8]
        self.assertEqual(login_request(creds.name, creds.password, RANDOM), expected)
        self.assertEqual(derive_session_key(creds.name, creds.password, RANDOM, ANSWER), aes_att_encryption(secret, RANDOM + ANSWER[1:9]))
        self.assertNotIn('240', repr(creds))
        self.assertEqual(login_request('old', 'password', RANDOM), login_request(b'old', b'password', RANDOM))

    def test_invalid_credential_types_and_length(self):
        for bad in (None, 123, bytearray(16), b'x' * 17, 'Ã¤' * 9):
            with self.subTest(value=type(bad).__name__), self.assertRaises(ValueError):
                Credentials('mesh', bad)

    def test_factory_credentials_all_registered_models_at_thresholds(self):
        expected_secure = hashlib.sha256(bytes.fromhex('11223344556656e850edcfdd8b990000')).digest()[:16]
        for name in _MODELS:
            code = registered_model_code(name)
            threshold = {32: 3, 96: 2, 97: 2, 99: 2, 128: 1, 129: 1}[code[0]]
            for major in (threshold - 1, threshold, threshold + 1):
                with self.subTest(model=name, firmware=major):
                    creds = factory_credentials(MAC, code, f'{major}.0.0')
                    self.assertEqual(creds.name, 'unpaired')
                    self.assertEqual(creds.password, expected_secure if major >= threshold else b'1234')

    def test_factory_metadata_is_required_and_custom_name_preserved(self):
        for mac, code, fw in (('', b' \x96', '3.0.0'), (MAC, b'\xff\xff', '3.0.0'), (MAC, b' \x96', ''), (MAC, b' \x96', '3.0'), (MAC, b' \x96', '256.0.0')):
            with self.subTest(firmware=fw), self.assertRaises(ValueError):
                factory_credentials(mac, code, fw)
        self.assertEqual(factory_credentials(MAC, b' \x96', '3.0.0', name='R-example').name, 'R-example')

    def test_exact_network_layout_and_name_mapping(self):
        frame = SETTINGS.network_frame()
        self.assertEqual(frame.plaintext[3:], bytes.fromhex('03144142464544434241c1a40000000000'))
        explicit = build_provision_network(26, b'\x124', bytes(range(8)), group_address=32784, reserved=4660)
        self.assertEqual(explicit.plaintext[3:], b'\x03\x1a\x124' + bytes(range(8)) + b'\x10\x804\x12\x00')
        self.assertEqual(len(frame.plaintext[3:]), 17)

    def test_exact_network_key_and_remove_layout(self):
        self.assertEqual(build_network_key(bytes(range(16))).plaintext[3:], b'\x04' + bytes(range(16)) + b'\x00')
        self.assertEqual(ExtendedCommandBuilder(43981).remove_from_mesh().plaintext[3:], b'\x01\xcd\xab')
        for bad in (0, True, 32768, 65535):
            with self.assertRaises(ValueError):
                ExtendedCommandBuilder(bad).remove_from_mesh()

    def test_invalid_settings_fail_without_transport(self):
        for kwargs in ({'channel': True}, {'channel': -1}, {'channel': 256}, {'group_address': -1}, {'group_address': 65536}, {'network_key': bytes(15)}, {'network_key': bytearray(16)}):
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                ProvisioningSettings(**{'credentials': CREDS, 'network_key': bytes(16)} | kwargs)
        for short, long in ((b'1', bytes(8)), (bytes(2), bytes(7))):
            with self.assertRaises(ValueError):
                build_provision_network(20, short, long)

    def test_83_is_explicit_and_retains_payload(self):
        payload = bytes(range(19))
        packet = b'\x83' + aes_att_encryption(KEY, payload[:16]) + payload[16:]
        notification = decode_notification(KEY, packet)
        self.assertEqual((notification.kind, notification.value, notification.payload), ('provisioning_done', True, payload))
if __name__ == '__main__':
    unittest.main()
