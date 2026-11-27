"""Connect.Z 96 20 sender suffix and dynamic hue FF regressions (offline)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from awox.advertisements import AdvertisementRecord
from awox.esphome_proxy import ESPHomeProxy
from vector_adapter import ExtendedNotification
from awox.status import parse_lamp_status

# Observed Connect.Z AwoX long/short profile (anonymized reference fixture).
# Embedded MAC tail is 02 EE DD CC, while the BLE address ends CC:DD:EE:02.
LONG = bytes.fromhex(
    '60 01 96 20 02 EE DD CC 03 00 02 DD 9C 02 FF FF FF 11 FE 04 3E 60 00 00 00 00 00 00 00'
)
SHORT = LONG[:8]
MATCHING_MAC = 'AA:BB:CC:DD:EE:02'
WRONG_MAC = 'AA:BB:CC:DD:EE:03'


def service_info(mac=MATCHING_MAC, manufacturer=LONG, *, raw=None):
    return SimpleNamespace(
        address=mac, device=object(), rssi=-55, name='EGLO',
        manufacturer_data={0x0160: manufacturer[2:]}, raw=raw,
        service_data={}, service_uuids=(), time=1.0,
        source='esphome', connectable=True,
    )


def ad_frame(manufacturer):
    return bytes((len(manufacturer) + 1, 0xFF)) + manufacturer


class AdvertisementMacHueTests(unittest.TestCase):
    def test_long_matches_sender_and_keeps_proxy_mac(self):
        observation = ESPHomeProxy._from_service_info(service_info())
        self.assertIsNotNone(observation)
        self.assertEqual(observation.address, MATCHING_MAC)
        self.assertEqual(observation.advertisement.manufacturer[4:8], bytes.fromhex('02 EE DD CC'))

    def test_short_matches_sender(self):
        observation = ESPHomeProxy._from_service_info(service_info(manufacturer=SHORT))
        self.assertIsNotNone(observation)
        self.assertIsNone(observation.advertisement.light_state)

    def test_wrong_suffix_rejected_in_short_and_long(self):
        for manufacturer in (LONG, SHORT):
            with self.subTest(length=len(manufacturer)):
                self.assertIsNone(AdvertisementRecord.from_service_info(
                    service_info(WRONG_MAC, manufacturer)))
                self.assertIsNone(ESPHomeProxy._from_service_info(
                    service_info(WRONG_MAC, manufacturer)))

    def test_no_sender_or_malformed_sender_rejected_for_known_profile(self):
        for address in (None, 'AA:BB:CC:DD:EE', 'AA:BB:CC:DD:EE:GG'):
            with self.subTest(address=address):
                self.assertIsNone(AdvertisementRecord.from_service_info(
                    service_info(address)))

    def test_raw_only_record_checks_sender(self):
        for address in (MATCHING_MAC, WRONG_MAC):
            info = service_info(address)
            info.manufacturer_data = {}
            info.raw = ad_frame(LONG)
            result = AdvertisementRecord.from_service_info(info)
            self.assertEqual(result is not None, address == MATCHING_MAC)

    def test_short_raw_packet_wins_over_merged_long_packet_for_validation(self):
        info = service_info(MATCHING_MAC, LONG, raw=ad_frame(SHORT))
        self.assertIsNotNone(AdvertisementRecord.from_service_info(info))
        mutated_short = bytearray(SHORT)
        mutated_short[4] ^= 0x01
        info.raw = ad_frame(mutated_short)
        self.assertIsNone(AdvertisementRecord.from_service_info(info))

    def test_other_unverified_manufacturer_layout_not_assumed_same_offsets(self):
        unknown = bytearray(LONG)
        unknown[2:4] = b'\x01\x02'  # Not the confirmed 96 20 profile
        self.assertIsNotNone(AdvertisementRecord.from_service_info(
            service_info(WRONG_MAC, bytes(unknown))))

    def test_effect_ff_retains_raw_but_not_fake_hue_angle(self):
        manufacturer = bytearray(LONG)
        manufacturer[13] = 0x07  # power, color, cycle
        manufacturer[17] = 0xFF
        state = AdvertisementRecord.from_manufacturer_data(0x0160, manufacturer[2:]).light_state
        self.assertIsNotNone(state)
        self.assertTrue(state.color_cycle)
        self.assertEqual(state.hue_raw, 255)
        self.assertIsNone(state.hue_degrees)
        self.assertEqual(state.saturation_raw, 0xFE)
        # The ESPHome incoming decoding uses the same semantic conversion.
        received = AdvertisementRecord.from_service_info(service_info(manufacturer=bytes(manufacturer)))
        self.assertIsNone(received.light_state.hue_degrees)
        self.assertEqual(received.light_state.hue_raw, 255)

    def test_status_hue_ff_is_only_raw_no_derived_angle(self):
        # LampStatus preserves the raw hue byte even when conversion is unavailable.
        # Retain original bytes for diagnostics; do not invent a fixed angle.
        payload = (bytes.fromhex('DD 9C 01 00 00 96 20 01 EE DD CC')
                   + bytes((1, 7, 138)) + b'\xff\xff' + bytes((255, 254, 0x60)))
        assert len(payload) == 19
        packet = ExtendedNotification(0x80, 'mesh_status_raw', payload, payload)
        status = parse_lamp_status(packet, received_at=1.0)
        self.assertIsNotNone(status)
        self.assertTrue(status.color_cycle_active)
        self.assertEqual(status.hs_raw[0], 255)
        self.assertIsNone(status.hs)
        self.assertFalse(hasattr(status, 'hue_degrees'))

    def test_defined_hue_boundary_still_interpreted(self):
        manufacturer = bytearray(LONG)
        manufacturer[13] = 0x03
        for hue in (0, 1, 253, 254):
            with self.subTest(hue=hue):
                manufacturer[17] = hue
                state = AdvertisementRecord.from_manufacturer_data(
                    0x0160, manufacturer[2:]).light_state
                self.assertEqual(state.hue_raw, hue)
                self.assertAlmostEqual(state.hue_degrees, hue * 360.0 / 254)

    def test_invalid_advertisement_skipped_by_event_cache_and_callbacks(self):
        proxy = ESPHomeProxy('proxy.local')
        received = []
        proxy.on_advertisement(received.append)
        proxy._handle_advertisement_event(service_info())
        self.assertEqual(len(received), 1)
        self.assertIsNotNone(proxy.get_advertisement(MATCHING_MAC))
        proxy._handle_advertisement_event(service_info(WRONG_MAC))
        self.assertEqual(len(received), 1)
        self.assertIsNone(proxy.get_advertisement(WRONG_MAC))


if __name__ == '__main__':
    unittest.main()
