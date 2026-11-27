"""Regression tests for the agreed public API without physical BLE hardware.

Use the existing fake encrypted GATT transport. Keep the code paths real:
control frames go through MeshConnection rather than mocking AwoXMeshSession.send.
"""
import asyncio
import inspect
import unittest

from awox import (
    AwoXMeshSession, Credentials, ESPHomeProxy, MeshTarget, Lamp,
    PresenceWritePart, ProvisioningSettings, ScheduleWritePart,
    routine_white_settings, ConnectionLost,
)
from awox import lighting
from awox.frames import COMMAND_UUID, open_frame
from test_session_operations import FakeTransport, ID, MAC, CREDS


class PublicCommands(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = FakeTransport()
        self.mesh = AwoXMeshSession(lambda: self.transport, CREDS, {ID: MAC})
        await self.mesh.connect()
        self.transport.writes.clear()
        self.lamp = self.mesh.lamp(ID)

    async def asyncTearDown(self):
        await self.mesh.disconnect()

    def packets(self):
        return [open_frame(self.transport.key, data).data
                for characteristic, data, _ in self.transport.writes
                if characteristic == COMMAND_UUID]

    async def test_power_has_one_public_method_for_lamp_group_broadcast(self):
        self.assertIsInstance(self.lamp, Lamp)
        self.assertIsInstance(self.mesh.group(0x8000), MeshTarget)
        for target in (self.lamp, self.mesh.group(0x8000), self.mesh.broadcast()):
            self.assertFalse(hasattr(target, 'turn_on'))
            self.assertFalse(hasattr(target, 'turn_off'))
            await target.set_power(True)
            await target.set_power(False)
        self.assertEqual(len(self.packets()), 6)
        self.assertEqual(self.packets()[0], bytes.fromhex('123401060001'))
        self.assertEqual(self.packets()[1], bytes.fromhex('123401060000'))
        self.assertEqual(self.packets()[2][:2], bytes.fromhex('8000'))
        with self.assertRaises(TypeError):
            await self.lamp.set_power(1)
        self.assertEqual(len(self.packets()), 6)

    async def test_groups_write_only_and_confirmed_set(self):
        await self.lamp.write_mesh_groups((0x8000,))
        self.assertEqual(self.packets()[0][0], 0x0C)
        self.transport.reply = (0x0C, b'\x34\x12\x00')
        answer = await self.lamp.set_mesh_groups((0x8001,), timeout=.1)
        self.assertTrue(answer.success)
        self.assertEqual(answer.mesh_id, ID)
        self.assertEqual(answer.status_code, 0)
        self.assertEqual(len(self.packets()), 2)
        self.transport.reply = None
        self.assertIsNone(await self.lamp.set_mesh_groups((), timeout=.01))
        self.assertEqual(len(self.packets()), 3)

    async def test_power_cut_return_is_same_struct_as_old_api(self):
        await self.lamp.write_power_cut_mode('on')
        self.transport.reply = (0x42, b'\x34\x12\x94')
        response = await self.lamp.set_power_cut_mode('previous', timeout=.1)
        self.assertEqual((response.mesh_id, response.status_code, response.status),
                         (ID, 0x94, 'timeout'))
        self.assertEqual([p[0] for p in self.packets()], [0x42, 0x42])

    async def test_presence_one_write_and_optional_confirmed_set(self):
        settings = PresenceWritePart.create(
            routine_white_settings(20, 50, power_on=True), enabled=True)
        await self.lamp.write_presence_simulator(settings)
        self.transport.reply = (0x3B, b'\x34\x12\x00\x3b\x01')
        result = await self.lamp.set_presence_simulator(settings, timeout=.1)
        self.assertEqual(result.status_code, 0)
        self.assertTrue(result.success)
        self.assertEqual([p[0] for p in self.packets()], [0x3B, 0x3B])

    async def test_time_with_timezone_decoded_ack_and_time30_independence(self):
        self.transport.reply = (0x29, bytes((0, 0, 0x94)))
        result = await self.mesh.set_time_with_timezone(
            946684800000, 'CET-1', timeout=.1)
        self.assertEqual(result.status_code, 0x94)
        self.assertFalse(result.success)
        self.transport.reply = None
        await self.mesh.set_time(946684800000, 3600)
        self.assertEqual([p[0] for p in self.packets()], [0x29, 0x30])

    async def test_dual_zone_native_and_rgb_match_existing_codec_bytes(self):
        zone = 1
        await self.lamp.set_dual_zone_power(zone, True)
        await self.lamp.set_dual_zone_brightness_percent(zone, 50)
        level = lighting.percentage_to_value(50, 2, 254)
        await self.lamp.set_dual_zone_brightness_raw(zone, level)
        await self.lamp.set_dual_zone_rgb(zone, 255, 0, 0)
        hue, saturation = lighting.rgb_to_native(255, 0, 0)
        await self.lamp.set_dual_zone_hs_raw(zone, hue, saturation)
        await self.lamp.set_dual_zone_color_temperature_mired(zone, 333)
        await self.lamp.set_dual_zone_color_temperature_kelvin(zone, 3003)
        self.assertEqual(self.packets()[1], self.packets()[2])
        self.assertEqual(self.packets()[3], self.packets()[4])
        self.assertEqual(self.packets()[5], self.packets()[6])
        self.assertFalse(hasattr(self.mesh, 'set_dual_zone_temperature'))
        with self.assertRaises(TypeError):
            await self.lamp.set_dual_zone_power(zone, 2)
        with self.assertRaises(ValueError):
            await self.lamp.set_dual_zone_color_temperature_mired(zone, 999)
        self.assertEqual(len(self.packets()), 7)

    async def test_hs_commands_match_raw_and_rgb_wire_bytes(self):
        await self.lamp.set_hs(240, 50, transition=700)
        await self.lamp.set_hs_raw(169, 127, transition=700)
        await self.lamp.set_hs(0, 100)
        await self.lamp.set_rgb(255, 0, 0)
        await self.lamp.set_dual_zone_hs(0, 240, 50)
        await self.mesh.set_dual_zone_hs_raw(ID, 0, 169, 127)
        await self.lamp.set_dual_zone_hs(0, 0, 100)
        await self.lamp.set_dual_zone_rgb(0, 255, 0, 0)
        writes = [data for char, data, response in self.transport.writes if char == COMMAND_UUID]
        self.assertEqual(len(writes), 8)
        self.assertEqual(writes[::2], writes[1::2])
        await self.lamp.set_hs(360, 100)
        await self.lamp.set_hs_raw(254, 254)
        await self.lamp.set_dual_zone_hs(0, 360, 100)
        await self.lamp.set_dual_zone_hs_raw(0, 254, 254)
        packets = self.packets()
        self.assertEqual(packets[8], packets[9])
        self.assertEqual(packets[10], packets[11])
        with self.assertRaises(ValueError):
            await self.lamp.set_hs(361, 100)
        with self.assertRaises(ValueError):
            await self.lamp.set_dual_zone_hs(0, 0, 101)
        self.assertEqual(len(self.packets()), 12)

    async def test_schedule_single_and_pair_preserve_old_result_contract(self):
        class EchoSchedule(FakeTransport):
            async def write(self, characteristic, data, response):
                await super().write(characteristic, data, response)
                if characteristic == COMMAND_UUID:
                    packet = open_frame(self.key, data).data
                    if packet[0] == 0x33:
                        part_id = packet[3] & 0x7F
                        status = 0x99 if part_id in (5, 7) else 0
                        self.emit(0x33, bytes((ID & 255, ID >> 8, status, 0, part_id)))
        await self.mesh.disconnect()
        self.transport = EchoSchedule()
        self.mesh = AwoXMeshSession(lambda: self.transport, CREDS, {ID: MAC})
        await self.mesh.connect()
        self.transport.writes.clear()
        self.lamp = self.mesh.lamp(ID)
        first = ScheduleWritePart.clock(
            5, 21, 0, routine_white_settings(20, 50, power_on=True), enabled=True)
        second = ScheduleWritePart.clock(
            6, 23, 0, routine_white_settings(20, 50, power_on=False), enabled=True)
        result = await self.lamp.set_nightlight(first, second, timeout=.2)
        self.assertTrue(result.complete)
        self.assertTrue(result.end_sent)
        self.assertEqual([p[0] for p in self.packets()], [0x33, 0x33])
        self.assertEqual([p[12] for p in self.packets()], [0x10, 0x11])
        timer = ScheduleWritePart.timer(
            20, routine_white_settings(20, 50, power_on=False), enabled=True)
        timer_result = await self.lamp.set_timer(timer, timeout=.2)
        self.assertTrue(timer_result.complete)
        self.assertEqual(len(self.packets()), 3)

    async def test_schedule_no_0x99_does_not_send_end(self):
        from awox import schedule
        start = ScheduleWritePart.clock(
            7, 20, 0, routine_white_settings(20, 50, power_on=True), enabled=True)
        end = ScheduleWritePart.clock(
            8, 21, 0, routine_white_settings(20, 50, power_on=False), enabled=True)
        self.transport.reply = (0x33, bytes((ID & 255, ID >> 8, 0, 0, 7)))
        answer = await self.lamp.set_dawn_simulator(start, end, timeout=.1)
        self.assertFalse(answer.end_sent)
        self.assertFalse(answer.complete)
        self.assertEqual(len(self.packets()), 1)

    async def test_paired_read_follows_only_valid_first_part(self):
        class ReadSchedule(FakeTransport):
            async def write(self, characteristic, data, response):
                await super().write(characteristic, data, response)
                if characteristic == COMMAND_UUID:
                    packet = open_frame(self.key, data).data
                    if packet[0] == 0x35:
                        routine = packet[3]
                        payload = bytearray(bytes.fromhex('341285810000ff0001144d0111'))
                        payload[2] = 0x80 | routine
                        self.emit(0x35, bytes(payload))

        await self.mesh.disconnect()
        self.transport = ReadSchedule()
        self.mesh = AwoXMeshSession(lambda: self.transport, CREDS, {ID: MAC})
        await self.mesh.connect()
        self.transport.writes.clear()
        self.lamp = self.mesh.lamp(ID)
        answer = await self.lamp.read_nightlight(timeout=.2)
        self.assertIsNotNone(answer)
        self.assertTrue(answer.complete)
        self.assertEqual(answer.start.routine_id, 5)
        self.assertEqual(answer.end.routine_id, 6)
        self.assertEqual([p[0] for p in self.packets()], [0x35, 0x35])

    async def test_bad_first_read_never_requests_second(self):
        self.transport.reply = (0x35, bytes.fromhex('3412ff8205'))
        result = await self.lamp.read_nightlight(timeout=.1)
        self.assertIsNotNone(result)
        self.assertIsNone(result.end)
        self.assertEqual(result.start.error_code, 0x82)
        self.assertEqual(len(self.packets()), 1)

    async def test_confirmed_set_timeout_does_not_fake_success(self):
        self.assertIsNone(await self.lamp.set_power_cut_mode('on', timeout=.01))
        self.assertIsNone(await self.mesh.set_time_with_timezone(
            946684800000, 'CET-1', timeout=.01))
        self.assertEqual([p[0] for p in self.packets()], [0x42, 0x29])

    async def test_api_names_have_no_hidden_aliases(self):
        self.assertFalse(hasattr(self.mesh, 'send_for_reply'))
        self.assertFalse(hasattr(self.lamp, 'write_groups'))
        self.assertFalse(hasattr(self.mesh, 'set_dual_zone_color'))
        self.assertFalse(hasattr(self.mesh, 'set_dual_zone_temperature'))
        self.assertTrue(callable(self.mesh.send_and_track_reply))
        self.assertTrue(callable(self.mesh.provision))
        self.assertTrue(inspect.iscoroutinefunction(ESPHomeProxy.create_transport))
        self.assertFalse(hasattr(ESPHomeProxy, 'transport_for'))


class ProvisionWorkflow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = FakeTransport()
        self.mesh = AwoXMeshSession(lambda: self.transport, CREDS)
        await self.mesh.connect()
        self.transport.writes.clear()
        self.transport.pair_response = b'\x07'  # Pair07 after factory login.
        self.settings = ProvisioningSettings(Credentials('new-mesh', 'new-pass'), bytes(range(16)))

    async def asyncTearDown(self):
        await self.mesh.disconnect()

    def packets(self):
        return [open_frame(self.transport.key, data).data
                for characteristic, data, _ in self.transport.writes
                if characteristic == COMMAND_UUID]

    async def test_provision_cannot_continue_on_replacement_connection(self):
        class PausedProvisioning(AwoXMeshSession):
            async def set_network_parameters(self, settings):
                paused.set()
                await resume.wait()
                await super().set_network_parameters(settings)

        first, replacement = FakeTransport(), FakeTransport()
        peers = iter((first, replacement))
        paused, resume = asyncio.Event(), asyncio.Event()
        async with PausedProvisioning(lambda: next(peers), CREDS) as mesh:
            first.pair_response = b'\x07'
            job = asyncio.create_task(mesh.provision(0, self.settings, timeout=1))
            try:
                await asyncio.wait_for(paused.wait(), 1)
                await mesh.disconnect()
                await mesh.connect()
                replacement.writes.clear()
                resume.set()
                with self.assertRaisesRegex(ConnectionLost, 'replaced connection'):
                    await asyncio.wait_for(job, 1)
                self.assertTrue(mesh.connected)
                self.assertTrue(replacement.connected)
                self.assertEqual(replacement.writes, [])
            finally:
                if not job.done():
                    job.cancel()
                    await asyncio.gather(job, return_exceptions=True)

    async def test_cancelled_provision_keeps_delegated_write_bound(self):
        paused, resume = asyncio.Event(), asyncio.Event()
        children = []

        class DelegatedProvisioning(AwoXMeshSession):
            async def set_network_parameters(self, settings):
                send_parameters = super().set_network_parameters

                async def late_write():
                    paused.set()
                    await resume.wait()
                    await send_parameters(settings)

                child = asyncio.create_task(late_write())
                children.append(child)
                await asyncio.shield(child)

        first, replacement = FakeTransport(), FakeTransport()
        peers = iter((first, replacement))
        async with DelegatedProvisioning(lambda: next(peers), CREDS) as mesh:
            first.pair_response = b'\x07'
            job = asyncio.create_task(mesh.provision(0, self.settings))
            try:
                await asyncio.wait_for(paused.wait(), 1)
                job.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await job
                await mesh.connect()
                replacement.writes.clear()
                resume.set()
                with self.assertRaisesRegex(ConnectionLost, 'replaced connection'):
                    await asyncio.wait_for(children[0], 1)
                self.assertTrue(mesh.connected)
                self.assertEqual(replacement.writes, [])
            finally:
                for pending in (job, *children):
                    if not pending.done():
                        pending.cancel()
                await asyncio.gather(job, *children, return_exceptions=True)

    async def test_delayed_provision_cleanup_leaves_replacement_connected(self):
        paused, resume = asyncio.Event(), asyncio.Event()
        job = None

        class DelayedCleanup(AwoXMeshSession):
            async def disconnect(self):
                if asyncio.current_task() is job:
                    paused.set()
                    await resume.wait()
                await super().disconnect()

        first, replacement = FakeTransport(), FakeTransport()
        peers = iter((first, replacement))
        async with DelayedCleanup(lambda: next(peers), CREDS) as mesh:
            first.pair_response = b'\x07'
            first.reply = (0x83, bytes(19))
            job = asyncio.create_task(mesh.provision(0, self.settings, timeout=1))
            try:
                await asyncio.wait_for(paused.wait(), 1)
                await mesh.disconnect()
                await mesh.connect()
                resume.set()
                result = await asyncio.wait_for(job, 1)
                self.assertTrue(result.completed)
                self.assertTrue(mesh.connected and replacement.connected)
            finally:
                if not job.done():
                    job.cancel()
                    await asyncio.gather(job, return_exceptions=True)

    async def test_provision_disconnect_respects_ack_and_replacement(self):
        for replies in ((), (0x0B, 0x83), (0x83, 0x0B), (0x83,)):
            with self.subTest(replies=replies):
                first, replacement = FakeTransport(), FakeTransport()
                peers = iter((first, replacement))
                reconnects = []
                notifications = []

                def reconnect():
                    reconnects.append(asyncio.create_task(mesh.connect()))

                async with AwoXMeshSession(
                    lambda: next(peers), CREDS, on_disconnect=reconnect,
                    on_notification=notifications.append,
                ) as mesh:
                    old_address = bytes.fromhex("bc9a")
                    first.emit(0x0B, old_address)
                    self.assertEqual(notifications[-1].opcode, 0x0B)
                    self.assertEqual(notifications[-1].payload[:2], old_address)
                    first.pair_response = b'\x07'
                    job = asyncio.create_task(mesh.provision(0, self.settings, timeout=1))

                    async def wait_until_written():
                        while not any(r._opcode == 0x83 and r._deadline is not None for r in mesh._receipts):
                            await asyncio.sleep(0)

                    try:
                        await asyncio.wait_for(wait_until_written(), 1)
                        for opcode in replies:
                            first.emit(opcode, bytes.fromhex('7856') if opcode == 0x0B else bytes(19))
                        first.loss()
                        if replies:
                            result = await asyncio.wait_for(job, 1)
                            self.assertTrue(result.completed)
                            self.assertEqual(result.mesh_id, 0x5678 if 0x0B in replies else None)
                        else:
                            with self.assertRaises(ConnectionLost):
                                await asyncio.wait_for(job, 1)
                        await asyncio.wait_for(reconnects[0], 1)
                        self.assertTrue(replacement.connected)
                    finally:
                        if not job.done():
                            job.cancel()
                        await asyncio.gather(job, *reconnects, return_exceptions=True)

    async def test_a0_skips_network_and_key(self):
        result = await self.mesh.provision(0, self.settings, provisioning_byte=0xA0)
        self.assertFalse(result.completed)
        self.assertEqual(self.packets(), [])

    async def test_remote_groups_positive_ack_then_network_and_key(self):
        original = self.transport.write
        async def write(char, data, response):
            await original(char, data, response)
            if char == COMMAND_UUID:
                cmd = open_frame(self.transport.key, data).data
                if cmd[0] == 0x0C:
                    self.transport.emit(0x0C, b'\xff\xff\x00')
                elif cmd[0] == 0x04:
                    self.transport.emit(0x0B, bytes((0x78, 0x56)))
                    self.transport.emit(0x83, bytes(19))
        self.transport.write = write
        result = await self.mesh.provision(0, self.settings, groups=(0x8000, 0x8001), timeout=.2)
        self.assertTrue(result.completed)
        self.assertEqual(result.mesh_id, 0x5678)
        self.assertEqual([p[0] for p in self.packets()], [0x0C, 0x03, 0x04])

    async def test_negative_group_notification_does_not_gate_provision(self):
        # The callback may observe a negative 0x0C result, but the APK-style
        # high-level path does not make successful setup depend on that ACK.
        self.transport.reply = (0x0C, b'\xff\xff\x94')
        result = await self.mesh.provision(0, self.settings, groups=(0x8000,), timeout=.01)
        self.assertFalse(result.completed)  # No 0x83 was supplied.
        self.assertEqual([p[0] for p in self.packets()], [0x0C, 0x03, 0x04])

    async def test_missing_group_ack_with_completion_still_succeeds(self):
        original_write = self.transport.write

        async def write(char, data, response):
            await original_write(char, data, response)
            if char == COMMAND_UUID:
                cmd = open_frame(self.transport.key, data).data
                if cmd[0] == 0x04:
                    self.transport.emit(0x83, bytes(19))

        self.transport.write = write
        result = await self.mesh.provision(0, self.settings, groups=(0x8000,), timeout=.1)
        self.assertTrue(result.completed)
        self.assertEqual([p[0] for p in self.packets()], [0x0C, 0x03, 0x04])

    async def test_missing_group_ack_does_not_gate_provision(self):
        result = await self.mesh.provision(0, self.settings, groups=(0x8000,), timeout=.01)
        self.assertFalse(result.completed)
        self.assertEqual([p[0] for p in self.packets()], [0x0C, 0x03, 0x04])


if __name__ == '__main__':
    unittest.main()
