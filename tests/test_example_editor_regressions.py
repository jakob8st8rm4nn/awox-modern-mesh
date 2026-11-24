"""Protect examples from optional-type and callback-flow editor regressions."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class EditorExampleRegressions(unittest.TestCase):
    def test_provisioning_callbacks_do_not_make_following_code_unreachable(self):
        for number in (26, 27):
            with self.subTest(example=number):
                file = next(EXAMPLES.glob(f"app_{number:02d}_*.py"))
                source = file.read_text(encoding="utf-8")
                tree = ast.parse(source)
                self.assertNotIn("nonlocal record", source)
                self.assertIn("matching_records: dict[str, AdvertisementRecord] = {}", source)
                self.assertIn("record = matching_records.get(", source)
                self.assertIn("record.provisioning_byte", source)
                self.assertIn("setup.provision(", source)
                self.assertTrue(ast.get_docstring(tree))

    def test_remote_name_is_validated_before_factory_credentials(self):
        source = next(EXAMPLES.glob("app_26_*.py")).read_text(encoding="utf-8")
        self.assertIn("remote_name = record.local_name", source)
        self.assertIn("if remote_name is None or not remote_name.strip():", source)
        self.assertIn("name=remote_name", source)
        self.assertNotIn("name=record.local_name", source)
        self.assertLess(source.index("if remote_name is None"),
                        source.index("current = factory_credentials("))

    def test_visual_examples_switch_on_explicitly(self):
        for number in range(8, 13):
            with self.subTest(example=number):
                source = next(EXAMPLES.glob(f"app_{number:02d}_*.py")).read_text(encoding="utf-8")
                self.assertEqual(source.count("await lamp.set_power(True)"), 1)

    def test_pir_example_does_not_write_if_initial_read_times_out(self):
        source = next(EXAMPLES.glob("app_19_*.py")).read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertIn("if settings is None:", source)
        self.assertIn("nothing was written.", source)
        self.assertLess(source.index("if settings is None:"),
                        source.index("await mesh.set_pir_settings("))
        self.assertTrue(tree)

    def test_advertisement_cache_does_not_add_optional_get_results(self):
        file = next(EXAMPLES.glob("app_03_*.py"))
        source = file.read_text(encoding="utf-8")
        self.assertIn("snapshot = proxy.advertisements", source)
        self.assertIn("cached = {mac: snapshot[mac] for mac in sorted(snapshot)}", source)
        self.assertNotIn("proxy.get_advertisement(mac)", source)

    def test_time_offset_checked_before_accessing_total_seconds(self):
        file = next(EXAMPLES.glob("app_20_*.py"))
        source = file.read_text(encoding="utf-8")
        self.assertIn("if utc_offset is None:", source)
        self.assertIn("utc_offset.total_seconds()", source)

    def test_multiple_lamp_devices_have_explicit_mapping_type(self):
        file = next(EXAMPLES.glob("app_14_*.py"))
        source = file.read_text(encoding="utf-8")
        self.assertIn("devices: dict[int, str]", source)
        self.assertIn("devices=devices,", source)


if __name__ == "__main__":
    unittest.main()
