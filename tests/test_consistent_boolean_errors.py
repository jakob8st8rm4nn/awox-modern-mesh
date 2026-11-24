"""Same invalid enabled type means TypeError for send-only light controls."""

import unittest
from awox.targets import MeshTarget


class InvalidLightBooleanInputs(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_enabled_type_rejected_before_any_send(self):
        class FakeMesh:
            def __init__(self):
                self.sent = []

            async def _write_control_destination(self, *args):
                self.sent.append(args)

        mesh = FakeMesh()
        lamp = MeshTarget(mesh, 0x1234)
        for name in ("set_power", "set_candle_mode", "set_color_cycle"):
            for bad in (1, 0, None, "yes"):
                with self.subTest(method=name, value=bad):
                    with self.assertRaises(TypeError):
                        await getattr(lamp, name)(bad)
        self.assertEqual(mesh.sent, [])


class CallbackDiagnostics(unittest.TestCase):
    def test_callback_exception_is_logged_and_isolated(self):
        from awox.session import AwoXMeshSession

        mesh = object.__new__(AwoXMeshSession)
        mesh.callback_errors = 0

        def fails(_value):
            raise RuntimeError("deliberate callback failure")

        with self.assertLogs("awox.session", level="ERROR") as captured:
            mesh._callback(fails, "not logged")
        self.assertEqual(mesh.callback_errors, 1)
        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(record.getMessage(), "AwoX callback failed")
        self.assertIsNotNone(record.exc_info)
        self.assertIsInstance(record.exc_info[1], RuntimeError)
