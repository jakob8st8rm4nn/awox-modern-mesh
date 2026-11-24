"""Two independently extracted APK descriptor byte tables; no Bluetooth I/O."""
import csv
from pathlib import Path
import unittest

from awox import lookup_model, lookup_models_by_code, registered_model_code
from awox.advertisements import AdvertisementRecord


ROOT = Path(__file__).resolve().parents[1]


def codes_from_apk(version):
    with (ROOT / 'tests' / 'fixtures' / f'apk-modellcodes-{version}.csv').open(encoding='utf-8', newline='') as handle:
        return {row['Modellname']: (bytes.fromhex(row['Modellcode hex (i())']), row['Protokoll'])
                for row in csv.DictReader(handle, delimiter=';')}


class ModelCodeTests(unittest.TestCase):
    def test_all_codes_agree_in_both_apks(self):
        older = codes_from_apk('1.14.10')
        newer = codes_from_apk('1.14.11')
        self.assertEqual(older, newer)
        self.assertEqual(len(newer), 48)
        self.assertEqual(len({code for code, protocol in newer.values()}), 48)
        for name, (code, family) in newer.items():
            self.assertEqual(family, 'modern')
            self.assertEqual(registered_model_code(name), code)
            models = lookup_models_by_code(code)
            self.assertIn(lookup_model(name), models)

    def test_concrete_leaf_classes_not_old_descriptor_base_classes(self):
        # Different EGLO-MAT descriptors inherit a common superclass, but
        # override their numeric model identifiers in their own i() method.
        self.assertEqual(registered_model_code('EGLO-MAT-Dimmable'), bytes.fromhex('8098'))
        self.assertEqual(registered_model_code('EGLO-MAT-RGB-TW'), bytes.fromhex('8096'))
        self.assertEqual(registered_model_code('EGLO-MAT-TW'), bytes.fromhex('8097'))
        self.assertEqual(registered_model_code('EGLO-ZM-RGB-TW'), bytes.fromhex('2096'))
        self.assertEqual(registered_model_code('EPIR-Zm'), bytes.fromhex('2058'))
        self.assertIsNone(registered_model_code('EPIRm'))

    def test_legacy_only_descriptor_codes_are_not_returned(self):
        self.assertEqual(lookup_models_by_code(bytes.fromhex('00A8')), ())
        self.assertEqual(len(lookup_models_by_code(bytes.fromhex('2096'))), 1)

    def test_works_with_existing_advertisement_scan_mask(self):
        # Synthetic AwoX 29-byte manufacturer layout. Raw model first byte
        # is 30, while the app scanner masks 0x10 -> 20 before the lookup.
        raw = bytearray(b'\x60\x01' + bytes(27))
        raw[2:4] = bytes.fromhex('9630')
        observation = AdvertisementRecord.from_manufacturer_data(0x0160, raw[2:])
        self.assertEqual(observation.model_code, bytes.fromhex('3096'))
        self.assertEqual(observation.model_lookup_code, bytes.fromhex('2096'))
        self.assertEqual([m.name for m in lookup_models_by_code(observation.model_lookup_code)],
                         ['EGLO-ZM-RGB-TW'])
        self.assertEqual(lookup_models_by_code(observation.model_code), ())

    def test_unknown_or_incomplete_input_does_not_guess_model(self):
        for value in (None, 0x2096, '2096', b'', b'\x20', b'\x20\x96\x00', b'\xff\xff', b'\x96\x20'):
            self.assertEqual(lookup_models_by_code(value), ())
        self.assertIsNone(registered_model_code('EGLO-ZM-RGB-TW-other'))
        self.assertIsNone(registered_model_code(None))

    def test_memoryview_lookup_uses_byte_length_not_element_count(self):
        raw = b'\x20\x96'
        expected = lookup_models_by_code(raw)
        self.assertEqual(len(expected), 1)
        self.assertEqual(lookup_models_by_code(memoryview(raw).cast('H')), expected)
        self.assertEqual(lookup_models_by_code(memoryview(raw).cast('B', shape=(1, 2))), expected)
        self.assertEqual(lookup_models_by_code(memoryview(raw * 2).cast('H')), ())

    def test_mutable_input_does_not_change_internal_lookup(self):
        data = bytearray(b'\x20\x96')
        expected = lookup_models_by_code(data)
        data[0] = 0
        self.assertEqual(len(expected), 1)
        self.assertEqual(expected[0].name, 'EGLO-ZM-RGB-TW')
        self.assertEqual(lookup_models_by_code(b'\x20\x96'), expected)
        with self.assertRaises(AttributeError):
            expected.append('other')


if __name__ == '__main__':
    unittest.main()
