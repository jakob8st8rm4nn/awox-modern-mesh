"""Regression tests for APK-reference behavior and discoverable Python API."""
import asyncio
import inspect
import time
import unittest
from typing import get_type_hints
from unittest.mock import patch

from awox import (
    AwoXMeshSession, ESPHomeProxy, DiscoveredDevice, AdvertisementRecord,
    Lamp, MeshTarget, ScheduleWritePart, routine_white_settings,
)
from awox.frames import COMMAND_UUID
from awox.pir import PirSettings, SceneConfig
from awox.frames import ExtendedNotification
from awox.transport import DiscoveredDevice as TransportDevice
from test_session_operations import FakeTransport, ID, MAC, CREDS


class BehaviorRegressions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = FakeTransport()
        self.mesh = AwoXMeshSession(lambda: self.transport, CREDS, {ID: MAC})
        await self.mesh.connect()
        self.transport.writes.clear()

    async def asyncTearDown(self):
        await self.mesh.disconnect()

    def count_commands(self):
        return sum(c == COMMAND_UUID for c, _, _ in self.transport.writes)

    async def test_invalid_groups_reply_then_valid_reply_is_accepted(self):
        # 0x08 + ID LE16 + unknown + count. Invalid advertises 120 groups.
        self.transport.reply = (0x08, bytes.fromhex('34120078'))
        loop = asyncio.get_running_loop()
        loop.call_later(.005, self.transport.emit, 0x08, bytes.fromhex('341200010080'))
        result = await self.mesh.read_mesh_groups(ID, timeout=.08)
        self.assertEqual(result.group_addresses, (0x8000,))
        self.assertEqual(self.count_commands(), 1)
        self.assertEqual(self.mesh.notifications_rejected, 1)

    async def test_only_invalid_groups_reply_times_out_without_error(self):
        self.transport.reply = (0x08, bytes.fromhex('34120078'))
        answer = await self.mesh.read_mesh_groups(ID, timeout=.012)
        self.assertIsNone(answer)
        self.assertEqual(self.count_commands(), 1)
        self.assertEqual(self.mesh.notifications_rejected, 1)

    async def test_parallel_same_group_reads_are_serialized(self):
        results = await asyncio.gather(
            self.mesh.read_mesh_groups(ID, timeout=.012),
            self.mesh.read_mesh_groups(ID, timeout=.012),
        )
        self.assertEqual(results, [None, None])
        self.assertEqual(self.count_commands(), 2)

    async def test_parallel_same_power_cut_requests_are_serialized(self):
        results = await asyncio.gather(
            self.mesh.read_power_cut_mode(ID, timeout=.012),
            self.mesh.read_power_cut_mode(ID, timeout=.012),
        )
        self.assertEqual(results, [None, None])
        self.assertEqual(self.count_commands(), 2)

    async def test_parallel_confirmed_set_requests_are_serialized(self):
        results = await asyncio.gather(
            self.mesh.set_power_cut_mode(ID, 'on', timeout=.012),
            self.mesh.set_power_cut_mode(ID, 'on', timeout=.012),
        )
        self.assertEqual(results, [None, None])
        self.assertEqual(self.count_commands(), 2)

    async def test_parallel_unaddressed_pir_reads_are_serialized(self):
        results = await asyncio.gather(
            self.mesh.read_pir_settings(ID, timeout=.012),
            self.mesh.read_pir_settings(ID, timeout=.012),
        )
        self.assertEqual(results, [None, None])
        self.assertEqual(self.count_commands(), 2)

    async def test_pir_valid_reads_reuse_one_decoder_and_preserve_raw_luminosity(self):
        expected = PirSettings(SceneConfig(0, 20), SceneConfig(0, 50),
                               5, 30, True, False, 2)
        self.transport.reply = (0x12, expected.encode())
        original_decode = PirSettings.decode
        with patch.object(PirSettings, 'decode', side_effect=original_decode) as decode:
            result = await self.mesh.read_pir_settings(ID, timeout=.08)
        self.assertEqual(result, expected)
        self.assertEqual(decode.call_count, 1)  # Not one filter decode plus one return decode.

        for value in (0, 255):
            self.transport.reply = (0x13, bytes((value,)))
            with self.subTest(luminosity=value):
                self.assertEqual(await self.mesh.read_pir_luminosity_raw(ID, timeout=.08), value)
        self.assertEqual(self.count_commands(), 3)

    async def test_pir_malformed_notifications_are_discarded_before_valid_reply(self):
        self.transport.reply = None
        expected = PirSettings(SceneConfig(0, 20), SceneConfig(0, 50),
                               5, 30, True, False, 2)
        for opcode, call, valid, result in (
            (0x12, self.mesh.read_pir_settings(ID, timeout=.08), expected.encode(), expected),
            (0x13, self.mesh.read_pir_luminosity_raw(ID, timeout=.08), b'\x00', 0),
        ):
            task = asyncio.create_task(call)
            for _ in range(100):
                if any(r._opcode == opcode and r._deadline is not None for r in self.mesh._receipts):
                    break
                await asyncio.sleep(0)
            else:
                self.fail('PIR receipt was not armed')
            # Raw decoded notifications can be shorter than expected. Such a
            # packet must not consume the reply window or terminate the read.
            self.mesh._receive(ExtendedNotification(opcode, 'raw', b'', b''))
            self.assertFalse(task.done())
            self.mesh._receive(ExtendedNotification(opcode, 'raw', valid, valid))
            self.assertEqual(await task, result)
        self.assertEqual(self.mesh.notifications_rejected, 2)
        self.assertEqual(self.count_commands(), 2)

    async def test_parallel_unaddressed_pir_reads_serialize_even_across_targets(self):
        results = await asyncio.gather(
            self.mesh.read_pir_settings(ID, timeout=.012),
            self.mesh.read_pir_settings(ID + 1, timeout=.012),
            self.mesh.read_pir_luminosity_raw(ID, timeout=.012),
            self.mesh.read_pir_luminosity_raw(ID + 1, timeout=.012),
        )
        self.assertEqual(results, [None, None, None, None])
        self.assertEqual(self.count_commands(), 4)

    async def test_parallel_status_reads_are_serialized(self):
        results = await asyncio.gather(
            self.mesh.read_status(ID, timeout=.012),
            self.mesh.read_status(ID, timeout=.012),
        )
        self.assertEqual(results, [None, None])
        self.assertEqual(self.count_commands(), 2)

    async def test_schedule_total_timeout_includes_slow_write(self):
        class SlowTransport(FakeTransport):
            async def write(self, characteristic, data, response):
                await super().write(characteristic, data, response)
                if characteristic == COMMAND_UUID:
                    await asyncio.sleep(.055)

        await self.mesh.disconnect()
        self.transport = SlowTransport()
        self.mesh = AwoXMeshSession(lambda: self.transport, CREDS, {ID: MAC})
        await self.mesh.connect()
        self.transport.writes.clear()
        timer = ScheduleWritePart.timer(
            20, routine_white_settings(20, 50, power_on=False), enabled=True,
        )
        start = time.monotonic()
        result = await self.mesh.set_timer(ID, timer, timeout=.020)
        elapsed = time.monotonic() - start
        self.assertIsNone(result.start_response)
        self.assertFalse(result.complete)
        self.assertEqual(self.count_commands(), 1)
        self.assertGreater(elapsed, .050)
        self.assertLess(elapsed, .078)  # No extra full reply window after slow write.

    async def test_schedule_reply_during_slow_write_before_deadline_counts(self):
        class SlowTransport(FakeTransport):
            async def write(self, characteristic, data, response):
                await super().write(characteristic, data, response)
                if characteristic == COMMAND_UUID:
                    await asyncio.sleep(.055)

        await self.mesh.disconnect()
        self.transport = SlowTransport()
        self.transport.reply = (0x33, bytes.fromhex('3412003302'))
        self.mesh = AwoXMeshSession(lambda: self.transport, CREDS, {ID: MAC})
        await self.mesh.connect()
        timer = ScheduleWritePart.timer(
            20, routine_white_settings(20, 50, power_on=False), enabled=True,
        )
        result = await self.mesh.set_timer(ID, timer, timeout=.02)
        self.assertIsNotNone(result.start_response)
        self.assertTrue(result.complete)

    async def test_schedule_reply_during_slow_write_after_deadline_is_not_counted(self):
        class LateTransport(FakeTransport):
            async def write(self, characteristic, data, response):
                if characteristic == COMMAND_UUID:
                    await asyncio.sleep(.035)
                await super().write(characteristic, data, response)

        await self.mesh.disconnect()
        self.transport = LateTransport()
        self.transport.reply = (0x33, bytes.fromhex('3412003302'))
        self.mesh = AwoXMeshSession(lambda: self.transport, CREDS, {ID: MAC})
        await self.mesh.connect()
        timer = ScheduleWritePart.timer(
            20, routine_white_settings(20, 50, power_on=False), enabled=True,
        )
        result = await self.mesh.set_timer(ID, timer, timeout=.02)
        self.assertIsNone(result.start_response)
        self.assertFalse(result.complete)


class PublicTypeContracts(unittest.TestCase):
    def test_typed_advertisement_callback_fields_are_runtime_resolvable(self):
        self.assertIs(DiscoveredDevice, TransportDevice)
        self.assertIs(get_type_hints(DiscoveredDevice)['advertisement'], AdvertisementRecord)
        self.assertEqual(get_type_hints(AdvertisementRecord)['firmware'], str)
        self.assertEqual(get_type_hints(AdvertisementRecord)['mesh_address'], int | None)
        self.assertEqual(get_type_hints(ESPHomeProxy.on_advertisement)['return'].__origin__, __import__('collections.abc').abc.Callable)

    def test_user_facing_method_return_types_are_discoverable(self):
        self.assertIs(get_type_hints(AwoXMeshSession.lamp)['return'], Lamp)
        self.assertIs(get_type_hints(AwoXMeshSession.group)['return'], MeshTarget)
        self.assertIs(get_type_hints(AwoXMeshSession.broadcast)['return'], MeshTarget)
        self.assertIs(get_type_hints(MeshTarget.set_power)['return'], type(None))
        self.assertEqual(get_type_hints(ESPHomeProxy.create_transport)['return'].__name__, 'ESPHomeNoCCCDTransport')
        self.assertEqual(str(get_type_hints(ESPHomeProxy.scan_mesh_devices)['return']), 'tuple[awox.transport.DiscoveredDevice, ...]')
        self.assertTrue(inspect.iscoroutinefunction(AwoXMeshSession.provision))
