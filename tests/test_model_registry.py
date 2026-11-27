"""Offline checks against the two captured Android MainApplication registers."""
import csv
from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

from awox import AwoXModel, lookup_model, scanned_model_name


ROOT = Path(__file__).resolve().parents[1]


def apk_models(version):
    path = ROOT / 'tests' / 'fixtures' / f'apk-modellregister-{version}.csv'
    with path.open(encoding='utf-8-sig', newline='') as source:
        rows = list(csv.DictReader(source, delimiter=';'))
    return {row['Modellname']: row['Protokoll'] for row in rows}


class ModelRegistryTests(unittest.TestCase):
    def test_model_register_exactly_matches_both_original_apks(self):
        older = apk_models('1.14.10')
        newer = apk_models('1.14.11')
        self.assertEqual(newer, older)
        self.assertEqual(len(newer), 48)
        self.assertEqual(list(newer.values()).count('modern'), 48)
        for name, protocol in newer.items():
            self.assertEqual(lookup_model(name), AwoXModel(name, 'modern'))

    def test_explicit_known_models_not_marketing_guess(self):
        self.assertEqual(lookup_model('EGLO-ZM-RGB-TW').protocol, 'modern')
        self.assertEqual(lookup_model('EPIR-Zm').protocol, 'modern')
        self.assertIsNone(lookup_model('EPIRm'))
        self.assertIsNone(lookup_model('ESMP-Bm10-UK'))

    def test_unknown_models_remain_unknown_without_fallback_guesses(self):
        for value in ('EGLO-ZM-RGB-TW-X', 'EGLO-ZM-RGB-TW ',
                      'eglo-zm-rgb-tw', '', 'brand-new-modern', None, b'EGLO-ZM-RGB-TW'):
            self.assertIsNone(lookup_model(value))

    def test_color_temperature_range_kelvin(self):
        expected = {
            "EBF-RGB-Zm": (2700, 6500),
            "EBF-RGB-Zm-CLP": (2700, 6500),
            "EGLO-ZM-RGB-TW": (2700, 6500),
            "ESMLzm-TW-GU10": (2700, 6500),
            "EZMB-RGB-TW-CLB": (2700, 6500),
            "EZMB-RGB-TW-I2C": (2700, 6500),
            "ESMLFzm-w6-TW": (2200, 6500),
            "EGLO-ZM-TW": (2200, 6500),
            "EDUAL-RGBTW-TW": (2200, 6500),
            "EGLO-ZM-Dimmable": None,
            "EGLO-ZM-RGB-W": None,
            "EGLO-ZMB-RGB-W": None,
            "EMAT-RGB-W-I2C": None,
            "EZMB-RGB-W-I2C": None,
            "EPIR-Zm": None,
            "ERCU-Zm": None,
        }
        for name, temperature_range in expected.items():
            with self.subTest(name=name):
                self.assertEqual(lookup_model(name).color_temperature_range_kelvin, temperature_range)

    def test_model_is_immutable(self):
        model = lookup_model('EGLO-ZM-RGB-TW')
        with self.assertRaises(FrozenInstanceError):
            model.protocol = 'invalid'
        self.assertEqual(lookup_model('EGLO-ZM-RGB-TW').protocol, 'modern')

    def test_scanner_aliases_apply_only_to_exact_firmware(self):
        self.assertEqual(scanned_model_name('EBF-RGB-Zm-CLP', '2.5.0'), 'EBF-RGB-Zm')
        self.assertEqual(scanned_model_name('EGLO-ZM-TW-CLP', '2.5.0'), 'EGLO-ZM-TW')
        for version in ('2.5', '2.5.1', '2.6.0', ''):
            self.assertEqual(scanned_model_name('EBF-RGB-Zm-CLP', version), 'EBF-RGB-Zm-CLP')
        self.assertEqual(scanned_model_name('EGLO-ZM-RGB-TW', '2.5.0'), 'EGLO-ZM-RGB-TW')
        self.assertEqual(scanned_model_name('EBF-RGB-ZMB-CLB', '2.5.0'), 'EBF-RGB-ZMB-CLB')

    def test_name_rewrite_does_not_infer_advertising_model_code(self):
        # Bytes in AdvertisementRecord.model_lookup_code require w9.a.c,
        # which cannot be reconstructed from the name-only CSV register.
        from awox.advertisements import AdvertisementRecord
        observation = AdvertisementRecord.from_manufacturer_data(0x0160, bytes(27))
        self.assertIsNotNone(observation.model_lookup_code)
        self.assertIsNone(lookup_model(observation.local_name))


if __name__ == '__main__':
    unittest.main()
