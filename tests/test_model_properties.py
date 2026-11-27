"""APK-derived descriptor properties; no hardware or network access."""
import csv
import json
from pathlib import Path
import unittest

from awox import lookup_model, lookup_model_properties, lookup_models_by_code
from awox import lookup_dual_zone_properties, lookup_fixed_white_picker_percent

ROOT = Path(__file__).resolve().parents[1]


def apk_properties(version):
    path = ROOT / 'tests' / 'fixtures' / f'apk-descriptor-properties-{version}.csv'
    with path.open(encoding='utf-8', newline='') as handle:
        return {row['Modellname']: (tuple(json.loads(row['Properties (JSON; Originalreihenfolge)'])),
                                   json.loads(row['Descriptor-Flags (normalisiert JSON)']))
                for row in csv.DictReader(handle, delimiter=';')}


class ModelPropertiesTests(unittest.TestCase):

    def test_apk_zone_properties(self):
        white = ("dual_zone_power_state", "dual_zone_brightness", "dual_zone_temperature")
        for model in ("EDUAL-RGBTW-TW", "EDUAL2G-RGBTW-TW", "EDUAL-RGB2TW-2BT"):
            with self.subTest(model=model):
                self.assertEqual(lookup_dual_zone_properties(model, 0), white + ("dual_zone_color",))
                self.assertEqual(lookup_dual_zone_properties(model, 1), white)
                self.assertIsNone(lookup_dual_zone_properties(model, 2))
                self.assertIsNone(lookup_dual_zone_properties(model, True))
        self.assertIsNone(lookup_dual_zone_properties("EGLO-ZM-RGB-TW", 0))

    def test_apk_fixed_white_picker_percent(self):
        self.assertEqual(lookup_fixed_white_picker_percent("EGLO-ZMB-RGB-W"), 80)
        self.assertIsNone(lookup_fixed_white_picker_percent("EGLO-ZM-RGB-W"))
        self.assertIsNone(lookup_fixed_white_picker_percent("unknown"))

    def test_all_48_modern_properties_agree_in_both_original_apks(self):
        older = apk_properties('1.14.10')
        newer = apk_properties('1.14.11')
        self.assertEqual(older, newer)
        self.assertEqual(len(newer), 48)
        for name, (properties, _) in newer.items():
            if lookup_model(name) is not None:
                self.assertEqual(lookup_model_properties(name), properties)
            else:
                self.assertIsNone(lookup_model_properties(name))

    def test_rgb_tunable_and_dimmable_property_boundaries(self):
        rgb = lookup_model_properties('EGLO-ZM-RGB-TW')
        tw = lookup_model_properties('EGLO-ZM-TW')
        dim = lookup_model_properties('EGLO-ZM-Dimmable')
        self.assertIn('color', rgb)
        self.assertIn('white_temperature', rgb)
        self.assertNotIn('color', tw)
        self.assertIn('white_temperature', tw)
        self.assertNotIn('color', dim)
        self.assertNotIn('white_temperature', dim)
        self.assertIn('white_brightness', dim)

    def test_sensor_remote_and_dualzone_have_separate_profiles(self):
        pir = lookup_model_properties('EPIR-Zm')
        remote = lookup_model_properties('ERCU-3groups-Zm')
        dual = lookup_model_properties('EDUAL-RGBTW-TW')
        self.assertIn('pir_settings', pir)
        self.assertIn('pir_current_luminosity', pir)
        self.assertNotIn('color', pir)
        self.assertIn('rcu_3_buttons', remote)
        self.assertNotIn('color', remote)
        self.assertIn('dual_zone_temperature', dual)
        self.assertIn('dual_zone_color', dual)

    def test_power_cut_properties_are_registered_for_44_models(self):
        models = apk_properties('1.14.11')
        names = {name for name, (properties, _) in models.items()
                 if 'power_cut_get_mode' in properties and 'power_cut_set_mode' in properties}
        self.assertEqual(len(names), 44)
        self.assertIn('EGLO-ZM-RGB-TW', names)
        self.assertIn('EGLO-ZM-TW', names)
        self.assertIn('EGLO-ZM-Dimmable', names)
        self.assertNotIn('EPIR-Zm', names)
        self.assertNotIn('ERCU-3groups-Zm', names)
        for name, (properties, _) in models.items():
            self.assertEqual('power_cut_get_mode' in properties,
                             'power_cut_set_mode' in properties, name)

    def test_property_list_does_not_equal_implemented_api(self):
        names = lookup_model_properties('EGLO-ZM-RGB-TW')
        self.assertIn('mesh_ota', names)
        self.assertIn('scenes', names)
        self.assertIn('program', names)
        self.assertNotIn('pir_settings', names)

    def test_absent_name_and_bad_types_remain_unknown(self):
        for name in (None, 0, '', 'eglo-zm-rgb-tw', 'EGLO-ZM-RGB-TW-not-registered'):
            self.assertIsNone(lookup_model_properties(name))

    def test_reference_is_immutable_and_preserves_duplicates(self):
        values = lookup_model_properties('EGLO-ZM-RGB-TW')
        self.assertIn('time', values)
        with self.assertRaises(AttributeError):
            values.append('new property')
        mutable = list(values)
        mutable.clear()
        self.assertEqual(lookup_model_properties('EGLO-ZM-RGB-TW'), values)
        matches = lookup_models_by_code(bytes.fromhex('2096'))
        self.assertEqual(lookup_model_properties(matches[0].name),
                         lookup_model_properties('EGLO-ZM-RGB-TW'))


if __name__ == '__main__':
    unittest.main()
