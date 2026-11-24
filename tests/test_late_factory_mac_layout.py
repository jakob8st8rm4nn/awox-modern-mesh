"""Late factories cannot start login; MAC spellings cannot change the wire layout."""
import asyncio
from types import SimpleNamespace
import unittest
from awox.advertisements import AdvertisementRecord, ScanObservation
from awox.session import Credentials
from awox.transport import ConnectionLost
def manufacturer(code=b'\x20\x96', *, firmware=(3,0,2), flags=3):
    return (b'\x60\x01' + code[::-1] + bytes.fromhex('7F665538')
            + bytes(firmware) + b'\x74\x99'
            + bytes((flags,60,96,1,83,254,4,62,0x60)) + bytes(7))

class AdvertisementMacLayoutTests(unittest.TestCase):

    def full_packet(self):
        mac = bytes.fromhex('AABBCCDDEE02')
        raw = b'`\x01\x96 ' + mac[::-1] + bytes((3, 0, 2)) + b'4\x12' + bytes((1, 128, 77, 1, 83, 254, 4, 62, 96)) + bytes(5)
        return (raw, bytes((30, 255)) + raw)

    def test_all_supported_spellings_select_identical_full_mac_layout(self):
        raw, packet = self.full_packet()
        for address in ('AA:BB:CC:DD:EE:02', 'aa:bb:cc:dd:ee:02', 'AA-BB-CC-DD-EE-02', 'AABB.CCDD.EE02', ' AABBCCDDEE02 '):
            info = SimpleNamespace(address=address, manufacturer_data={352: raw[2:]}, raw=packet)
            for record in (AdvertisementRecord.from_service_info(info), AdvertisementRecord.from_bytes(packet, address=address), AdvertisementRecord.from_manufacturer_data(352, raw[2:], address=address), ScanObservation(address, -50, packet).decode()):
                with self.subTest(address=address):
                    self.assertIsNotNone(record)
                    self.assertEqual(record.firmware, '3.0.2')
                    self.assertEqual(record.mesh_address_unsigned, 4660)
                    self.assertEqual(record.hardware_version, '4.62')
                    self.assertEqual(record.provisioning_byte, 96)
                    self.assertEqual(record.light_state.white_temperature_mired, 333)

    def test_invalid_or_mismatched_sender_does_not_pass_proxy_consistency_check(self):
        raw, packet = self.full_packet()
        for address in (None, '', 'invalid', 'GG:BB:CC:DD:EE:02', 'AA:BB:CC:DD:EE', 'AA:BB:CC:DD:EE:03'):
            info = SimpleNamespace(address=address, manufacturer_data={352: raw[2:]}, raw=packet)
            self.assertIsNone(AdvertisementRecord.from_service_info(info))

    def test_existing_a4c1_layout_stays_unchanged_across_spellings(self):
        raw = manufacturer()
        for address in ('02:00:38:55:66:7F', '02-00-38-55-66-7F', '0200.3855.667F'):
            info = SimpleNamespace(address=address, manufacturer_data={352: raw[2:]})
            record = AdvertisementRecord.from_service_info(info)
            self.assertEqual(record.firmware, '3.0.2')
            self.assertEqual(record.mesh_address_unsigned, 39284)
