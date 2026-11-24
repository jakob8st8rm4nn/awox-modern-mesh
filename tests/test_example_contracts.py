"""Verify coverage, safe example flows and supported public API names."""
import ast
from pathlib import Path
import unittest
import awox

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples'


class ExampleContracts(unittest.TestCase):
    def test_all_examples_have_descriptions_and_supported_api_names(self):
        examples = sorted(EXAMPLES.glob('app_*.py'))
        self.assertEqual(len(examples), 29)
        obsolete = (
            '.turn_on(', '.turn_off(', '.transport_for(',
            'ProvisioningSession(', '.send_quiet_mode(',
            '.write_pir_settings(', '.set_dual_zone_color(',
        )
        for index, path in enumerate(examples, 1):
            with self.subTest(example=path.name):
                self.assertEqual(int(path.name[4:6]), index)
                source = path.read_text(encoding='utf-8')
                self.assertTrue(ast.get_docstring(ast.parse(source)))
                self.assertFalse(any(name in source for name in obsolete))

    def test_examples_include_safeguards_and_demonstrations(self):
        features = {
            7: ('set_power(True)', 'set_power(False)', 'asyncio.sleep(2)'),
            13: ('ZONE = 0', 'set_dual_zone_rgb(', 'enabled=True', 'enabled=False'),
            15: ('GROUP_DESTINATION = 0x8000', 'read_mesh_groups(', 'set_mesh_groups(',
                 'group.set_power(True)', 'group.set_power(False)'),
            18: ('POWER_CUT_MODE = "previous"', 'read_power_cut_mode(',
                 'set_power_cut_mode(', 'power_cut_white_scene(50, 50)'),
            20: ('POSIX_TIMEZONE_RULE = "CET-1CEST,M3.5.0,M10.5.0/3"',
                 'set_time_with_timezone(', 'set_time(', 'asyncio.sleep(0.25)'),
            21: ('ScheduleWritePart.timer(20,', 'read_timer(', 'set_timer('),
            22: ('weekdays_mask=0b0111110', 'read_program(', 'set_program('),
            23: ('read_nightlight(', 'set_nightlight(', '0x7F'),
            24: ('read_dawn_simulator(', 'set_dawn_simulator(', 'fade_minutes=30'),
            25: ('with_half_hour_slot(18, True)', 'read_presence_simulator(',
                 'set_presence_simulator('),
            26: ('BUTTON_GROUPS = (0x8000, 0x8001, 0x8002)',
                 'factory_credentials(', 'setup.provision(',
                 'provisioning_byte=record.provisioning_byte'),
            27: ('factory_credentials(', 'setup.provision(',
                 'provisioning_byte=record.provisioning_byte'),
            28: ('remove_from_mesh(', 'except ConnectionLost:'),
            29: ('read_mesh_groups(', 'send_and_track_reply(', 'receipt.wait()',
                 'parse_mesh_groups_set_result(', 'timeout=5.0'),
        }
        for number, checks in features.items():
            path = next(EXAMPLES.glob(f'app_{number:02d}_*.py'))
            source = path.read_text(encoding='utf-8')
            for feature in checks:
                with self.subTest(example=path.name, feature=feature):
                    self.assertIn(feature, source)

    def test_packaged_type_marker(self):
        self.assertTrue((Path(awox.__file__).parent / 'py.typed').is_file())


if __name__ == '__main__':
    unittest.main()
