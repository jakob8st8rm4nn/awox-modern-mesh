"""Regressions for APK-defined modern lamp state flags (offline)."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from vector_adapter import ExtendedNotification
from awox.status import StatusStore, parse_lamp_status, parse_status_variant

MESH_ID = 0x9CDD
LAMP_MAC = "02:00:38:33:44:B8"
MAC_TAIL = bytes.fromhex("b8443338")


def status_packet(mode: int, *, temperature: int | None = None,
                  hue: int = 80, saturation: int = 190, opcode: int = 0x80):
    # Same 19-byte payload layout as the existing EGLO_ZM_RGB_TW status tests.
    if temperature is None:
        temperature = 333 if (mode & 0x03) == 1 else 0xFFFF
    payload = (MESH_ID.to_bytes(2, "little") + b"\x01\x00\x00"
               + b"\x96\x20" + MAC_TAIL
               + bytes((1, mode, 138)) + temperature.to_bytes(2, "little")
               + bytes((hue, saturation, 0x60)))
    assert len(payload) == 19
    return ExtendedNotification(opcode, "mesh_status_raw", payload, payload)


class StatusBitsTest(unittest.TestCase):
    def test_all_four_power_color_combinations(self):
        for mode, on, color in ((0x00, False, False), (0x01, True, False),
                                (0x02, False, True), (0x03, True, True)):
            with self.subTest(mode=hex(mode)):
                result = parse_lamp_status(status_packet(mode), received_at=7.5)
                self.assertIsNotNone(result)
                self.assertEqual(result.mode, mode)
                self.assertIs(result.is_on, on)
                self.assertEqual(result.received_monotonic, 7.5)
                if color:
                    self.assertEqual(result.hs_raw, (80, 190))
                    self.assertIsNone(result.white_temperature_mired)
                else:
                    self.assertIsNone(result.hs_raw)

    def test_da_d_field11_is_preserved_without_filtering_lamp_state(self):
        packet = status_packet(0x01)
        for value in (0, 1, 0xFF):
            with self.subTest(value=value):
                payload = packet.payload[:11] + bytes((value,)) + packet.payload[12:]
                observation = ExtendedNotification(0x80, "mesh_status_raw", payload, payload)
                raw = parse_status_variant(observation)
                lamp = parse_lamp_status(observation)
                self.assertEqual(raw.field11_raw, value)
                self.assertTrue(lamp.is_on)
                self.assertEqual(lamp.white_temperature_mired, 333)
                self.assertEqual(lamp.raw_response, raw.raw_response)

    def test_da_d_checks_explicit_registered_model(self):
        for models, accepted in ((None, True), ({MESH_ID: "EGLO-ZM-RGB-TW"}, True),
                                 ({MESH_ID: "ERCU-Zm"}, False),
                                 ({MESH_ID: "EPIR-Zm"}, False)):
            with self.subTest(models=models):
                store = StatusStore({MESH_ID: LAMP_MAC}, device_models=models)
                status, changed = store.observe(status_packet(0x01))
                self.assertEqual(status is not None, accepted)
                self.assertEqual(changed, accepted)

    def test_unknown_model_name_requires_a_recognized_lamp_code(self):
        packet = status_packet(0x01)
        for layout, suffix in (("da.d", packet.payload[14:]), ("da.c", bytes((60, 80, 190, 0x60)))):
            for code, accepted in ((bytes.fromhex("9620"), True),
                                   (bytes.fromhex("2820"), False),
                                   (bytes.fromhex("0000"), False)):
                with self.subTest(layout=layout, code=code):
                    payload = packet.payload[:5] + code + packet.payload[7:14] + suffix
                    notification = replace(packet, value=payload, payload=payload)
                    store = StatusStore({MESH_ID: LAMP_MAC}, device_models={MESH_ID: "Unknown model"})
                    status, changed = store.observe(notification)
                    self.assertEqual(status is not None, accepted)
                    self.assertEqual(changed, accepted)

    def test_lamp_status_exposes_converted_units_without_losing_raw_values(self):
        white = parse_lamp_status(status_packet(0x01, temperature=333))
        self.assertEqual(white.brightness_raw, 138)
        self.assertEqual(white.brightness_percent, 54)
        self.assertEqual(white.white_temperature_mired, 333)
        self.assertEqual(white.color_temperature_mired, 333)
        self.assertEqual(white.color_temperature_kelvin, 3003)
        self.assertIsNone(white.hs)
        self.assertIsNone(white.rgb)
        for level, expected in ((0, 0), (1, 0), (2, 0), (128, 50), (254, 100), (255, 100)):
            with self.subTest(level=level):
                self.assertEqual(replace(white, brightness_raw=level).brightness_percent, expected)
        self.assertIsNone(parse_lamp_status(status_packet(0x01, temperature=0xFFFF)).color_temperature_kelvin)

        color = parse_lamp_status(status_packet(0x03, hue=254, saturation=255))
        self.assertEqual(color.hs_raw, (254, 255))
        self.assertEqual(color.hs, (0.0, 100.0))
        self.assertEqual(color.rgb, (255, 0, 0))
        self.assertIsNone(color.color_temperature_mired)
        self.assertIsNone(color.color_temperature_kelvin)
        self.assertEqual(replace(color, hs_raw=(254, 127)).rgb, (255, 128, 128))
        self.assertIsNone(replace(color, hs_raw=(255, 255)).hs)
        self.assertIsNone(replace(color, hs_raw=(255, 255)).rgb)

    def test_off_white_can_retain_temperature(self):
        result = parse_lamp_status(status_packet(0x00, temperature=333))
        self.assertIsNotNone(result)
        self.assertFalse(result.is_on)
        self.assertEqual(result.white_temperature_mired, 333)

    def test_documented_cycle_and_candle_bits(self):
        # Bits 2/4 must not affect power or the colour/white selection.
        for flags in (0x04, 0x10, 0x14):
            for base in (0x00, 0x01, 0x02, 0x03):
                mode = base | flags
                with self.subTest(mode=hex(mode)):
                    result = parse_lamp_status(status_packet(mode))
                    self.assertIsNotNone(result)
                    self.assertEqual(result.mode, mode)
                    self.assertIs(result.is_on, bool(base & 1))
                    if base & 2:
                        self.assertEqual(result.hs_raw, (80, 190))
                        self.assertIsNone(result.white_temperature_mired)
                    else:
                        self.assertIsNone(result.hs_raw)

    def test_unknown_mode_bits_are_preserved_and_known_bits_used(self):
        for mode in (0x08, 0x20, 0x80, 0xFF):
            with self.subTest(mode=hex(mode)):
                result = parse_lamp_status(status_packet(mode))
                self.assertIsNotNone(result)
                self.assertEqual(result.mode, mode)
                self.assertEqual(result.mode & ~0x17, mode & ~0x17)
                self.assertIs(result.is_on, bool(mode & 0x01))
                self.assertIs(result.is_color_mode, bool(mode & 0x02))
                self.assertIs(result.color_cycle_active, bool(mode & 0x04))
                self.assertIs(result.candle_active, bool(mode & 0x10))
                if mode & 0x02:
                    self.assertEqual(result.hs_raw, (80, 190))
                else:
                    self.assertIsNone(result.hs_raw)

    def test_unusual_white_temperature_keeps_status_and_raw_bytes(self):
        for opcode in (0x80, 0x82):
            for temperature in (0, 152, 455, 0xFFFF):
                with self.subTest(opcode=hex(opcode), temperature=temperature):
                    result = parse_lamp_status(status_packet(
                        0x01, temperature=temperature, opcode=opcode))
                    self.assertIsNotNone(result)
                    self.assertTrue(result.is_on)
                    self.assertEqual(result.mode, 0x01)
                    self.assertEqual(result.brightness_raw, 138)
                    self.assertIsNone(result.white_temperature_mired)
                    self.assertEqual(result.raw_response[15:17],
                                     temperature.to_bytes(2, 'little'))
        for temperature in (153, 454):
            with self.subTest(temperature=temperature):
                result = parse_lamp_status(status_packet(0x01, temperature=temperature))
                self.assertEqual(result.white_temperature_mired, temperature)
        self.assertIsNone(parse_lamp_status(status_packet(0x00)).white_temperature_mired)

    def test_store_keeps_unusual_values_and_new_unknown_flags_as_changes(self):
        events = []
        store = StatusStore({MESH_ID: LAMP_MAC}, on_change=events.append)
        first, changed = store.observe(status_packet(0x01, temperature=455))
        self.assertTrue(changed)
        self.assertIsNotNone(first)
        self.assertEqual(first.raw_response[15:17], b'\xc7\x01')
        repeated, changed = store.observe(status_packet(0x01, temperature=455, opcode=0x82))
        self.assertFalse(changed)
        self.assertIsNotNone(repeated)
        different, changed = store.observe(status_packet(0x21, temperature=455))
        self.assertTrue(changed)
        self.assertEqual(different.mode, 0x21)
        self.assertEqual([event.mode for event in events], [0x01, 0x21])

    def test_store_tracks_color_on_to_color_off_and_repeated_off(self):
        events = []
        store = StatusStore({MESH_ID: LAMP_MAC}, on_change=events.append)
        with patch("awox.status.time.monotonic", side_effect=[10., 11., 12.]):
            first, changed = store.observe(status_packet(0x03))
            self.assertTrue(changed)
            self.assertTrue(first.is_on)
            off, changed = store.observe(status_packet(0x02))
            self.assertTrue(changed)
            self.assertFalse(off.is_on)
            repeated, changed = store.observe(status_packet(0x02, opcode=0x82))
            self.assertFalse(changed)
            self.assertFalse(repeated.is_on)
            self.assertEqual(repeated.received_monotonic, 12.)
        self.assertEqual([state.mode for state in events], [0x03, 0x02])
        self.assertEqual(store.get(MESH_ID).mode, 0x02)
        self.assertFalse(store.states[MESH_ID].is_on)
