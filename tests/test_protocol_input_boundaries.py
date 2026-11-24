import asyncio
from array import array
from dataclasses import replace
import unittest
from unittest.mock import patch
from awox.presence import PresenceWritePart, parse_presence_read, parse_presence_set
from awox.power_cut import parse_power_cut_get_mode
from awox.schedule import ScheduleWritePart
from awox.pir import SceneConfig, PirSettings, encode_scene
from awox.frames import addressed_query, build_query, build_control, open_frame
from awox.provisioning import build_network_key
from awox.authentication import Credentials

class NoCopy(bytearray):

    def __bytes__(self):
        raise AssertionError('invalid buffer copied')

class DivergentBuffer(bytearray):
    def __init__(self, original, snapshot):
        super().__init__(original)
        self.snapshot = snapshot

    def __bytes__(self):
        return self.snapshot


class ProtocolInputBoundaryTests(unittest.TestCase):

    def test_routine_settings_check_the_copied_length(self):
        for part, routine, size in ((PresenceWritePart, 1, 14), (ScheduleWritePart, 2, 10)):
            original = bytes((routine,)) + bytes(size - 1)
            self.assertEqual(part(bytearray(original)).settings, original)
            for snapshot in (original[:1], original + b"\x00"):
                with self.subTest(part=part.__name__, size=len(snapshot)), self.assertRaises(ValueError):
                    part(DivergentBuffer(original, snapshot))

    def test_power_cut_checks_and_parses_one_snapshot(self):
        original = bytes.fromhex("43 34 12 01 32 99 00 02")
        for snapshot in (b"\x43", b"\x99" + original[1:]):
            with self.subTest(snapshot=snapshot), self.assertRaises(ValueError):
                parse_power_cut_get_mode(DivergentBuffer(original, snapshot))

        snapshot = bytes.fromhex("43 78 56 03 20 30 40 01")
        self.assertEqual(
            parse_power_cut_get_mode(DivergentBuffer(original, snapshot)),
            parse_power_cut_get_mode(snapshot),
        )


    def test_presence_rejects_invalid_buffers_before_copy(self):
        for parser in (parse_presence_read, parse_presence_set):
            for data in (NoCopy(), NoCopy(b'\x00' * 4096)):
                with self.subTest(parser=parser.__name__, size=len(data)):
                    with self.assertRaises(ValueError):
                        parser(data)

    def test_presence_keeps_valid_trailers(self):
        read = b'<#\x01\x01' + bytes(13) + b'trailer'
        ack = b';#\x01\x00\x00\x01trailer'
        self.assertEqual(parse_presence_read(bytearray(read)).raw_response, read)
        self.assertEqual(parse_presence_set(bytearray(ack)).raw_response, ack)

    def test_scene_huge_hsv_rejected_without_overflow(self):
        scene = SceneConfig(1, 50)
        for field in ('hue', 'saturation'):
            for value in (10 ** 1000, -10 ** 1000, float('inf'), float('nan')):
                with self.subTest(field=field, value_type=type(value).__name__):
                    with self.assertRaises(ValueError):
                        encode_scene(replace(scene, **{field: value}))

    def test_pir_requires_scenes(self):
        settings = PirSettings(SceneConfig(0, 50), SceneConfig(0, 50), 1, 1, True, False, 0)
        for field in ('nightlight', 'motion'):
            with self.assertRaises(TypeError):
                replace(settings, **{field: None}).encode()

    def test_oversized_frame_rejected_before_decryption(self):
        with patch('awox.frames.aes_att_decryption', side_effect=AssertionError('AES called')):
            with self.assertRaisesRegex(ValueError, 'packet size'):
                open_frame(bytes(16), bytes(259))

    def test_frame_builders_reject_non_buffer_payloads(self):
        key = bytes(16)
        builders = (
            lambda payload: build_query(key, 10, payload),
            lambda payload: build_control(key, 1, (6, 0), payload),
        )
        for build in builders:
            for payload in ({1: 90, 0: 91}, [1, 0]):
                with self.subTest(payload=payload), self.assertRaises(TypeError):
                    build(payload)

    def test_payload_sizes_use_bytes_and_preserve_valid_frames(self):
        key = bytes(16)
        valid = memoryview(array('I', range(60)))
        self.assertEqual(build_query(key, 10, valid), build_query(key, 10, bytes(valid)))
        self.assertEqual(build_control(key, 1, (6, 0), valid), build_control(key, 1, (6, 0), bytes(valid)))
        large = memoryview(array('I', range(64)))
        for call in (lambda: build_query(key, 10, large), lambda: build_control(key, 1, (6, 0), large)):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(len(open_frame(key, build_query(key, 10, bytes(254))).data), 255)
        self.assertEqual(len(open_frame(key, build_control(key, 1, (6, 0), bytes(250))).data), 255)

    def test_addressed_query_rejects_oversized_suffix_before_copy(self):
        with self.assertRaises(ValueError):
            addressed_query(1, 8, NoCopy(bytes(253)))
        self.assertEqual(len(addressed_query(1, 8, bytes(252)).plaintext), 258)

    def test_command_repr_omits_key_but_keeps_explicit_bytes(self):
        key = b'EXAMPLE_KEY_1234'
        command = build_network_key(key)
        self.assertNotIn(key.decode(), repr(command))
        self.assertIn(key, command.plaintext)
