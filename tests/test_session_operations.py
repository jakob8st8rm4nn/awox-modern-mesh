"""Offline tests of the real new connection/session path with a fake GATT peer."""
import asyncio
import unittest

from awox import AwoXMeshSession, Credentials, ConnectionLost
from awox.authentication import derive_session_key
from awox.crypto import aes_att_encryption
from awox.frames import SERVICE_UUID, PAIR_UUID, COMMAND_UUID, NOTIFY_UUID, open_frame
from awox import groups, provisioning, schedule, lighting

CREDS = Credentials('test-mesh', 'test-password')
MAC = 'A4:C1:38:11:22:33'
ID = 0x1234


class FakeTransport:
    def __init__(self):
        self.writes = []
        self.callback = None
        self.loss = None
        self.key = None
        self.pair_response = b'\x0d' + bytes(range(8))
        self.reply = None
        self.connected = False
        self.disconnects = 0
        self.block_command = None

    async def connect(self, disconnected):
        self.loss = disconnected
        self.connected = True

    async def discover_services(self):
        return {SERVICE_UUID: frozenset({PAIR_UUID, COMMAND_UUID, NOTIFY_UUID})}

    async def read(self, characteristic):
        return self.pair_response

    async def write(self, characteristic, data, response):
        self.writes.append((characteristic, bytes(data), response))
        if characteristic == PAIR_UUID and data[0] == 0x0C:
            if self.pair_response[0] == 0x0D:
                self.key = derive_session_key(CREDS.name, CREDS.password, data[1:9], self.pair_response)
        if characteristic == COMMAND_UUID:
            if self.reply is not None:
                self.emit(*self.reply)
            if self.block_command is not None:
                await self.block_command.wait()

    def emit(self, opcode, payload):
        payload = payload.ljust(19, b'\0')
        self.callback(bytes((opcode,)) + aes_att_encryption(self.key, payload[:16]) + payload[16:])

    async def start_notify(self, characteristic, callback):
        self.callback = callback

    async def stop_notify(self, characteristic):
        self.callback = None

    async def request_mtu(self, mtu):
        return mtu

    async def disconnect(self):
        self.disconnects += 1
        self.connected = False


class SessionOperations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = FakeTransport()
        self.session = AwoXMeshSession(lambda: self.transport, CREDS, {ID: MAC})
        await self.session.connect()
        self.transport.writes.clear()

    async def asyncTearDown(self):
        await self.session.disconnect()

    def commands(self):
        return [open_frame(self.transport.key, d).data for c, d, _ in self.transport.writes
                if c == COMMAND_UUID]

    async def test_truncated_ble_notifications_do_not_interrupt_reception(self):
        received = self.session.notifications_received
        for size in (0, 1, 16):
            with self.subTest(size=size):
                packet = bytes(size)
                with self.assertRaises(ValueError):
                    self.session._current().decode_received(packet)
                self.transport.callback(packet)
                self.assertEqual(self.session.notifications_received, received)

        self.transport.emit(0x37, bytes(19))
        self.assertEqual(self.session.notifications_received, received + 1)

    async def test_lamp_request_status_sends_one_query_without_pending_reply(self):
        self.assertIsNone(await self.session.lamp(ID).request_status())
        self.assertEqual(self.commands(), [bytes.fromhex('0a 34 12')])
        self.assertFalse(self.session._receipts)

    async def test_write_time_with_timezone_sends_same_frame_without_reply(self):
        instant = 1_700_000_000_000
        rule = 'UTC0'
        # With no simulated device reply, the send-only variant still returns.
        self.assertIsNone(await asyncio.wait_for(
            self.session.write_time_with_timezone(instant, rule), timeout=0.5,
        ))
        self.assertEqual(len(self.commands()), 1)
        self.assertEqual(self.commands()[0][0], 0x29)
        self.assertFalse(self.session._receipts)

        self.transport.reply = (0x29, bytes(19))
        result = await self.session.set_time_with_timezone(instant, rule)
        self.assertTrue(result.success)
        self.assertEqual(len(self.commands()), 2)
        self.assertEqual(self.commands()[0], self.commands()[1])

    def test_status_query_builds_device_group_and_broadcast_frames(self):
        from awox import status_query

        for destination, expected in (
            (ID, '0a 34 12'), (0x8001, '0a 01 80'), (0xFFFF, '0a ff ff'),
        ):
            frame = status_query(destination)
            decoded = open_frame(self.transport.key, frame.encrypt(self.transport.key))
            self.assertEqual(decoded.flag, 2)
            self.assertEqual(decoded.data, bytes.fromhex(expected))
        self.assertEqual(self.commands(), [])
        for invalid in (0, -1, 0x10000, True):
            with self.subTest(destination=invalid), self.assertRaises(ValueError):
                status_query(invalid)

    async def test_light_group_broadcast_each_write_once_without_poll(self):
        await self.session.lamp(ID).set_power(True)
        await self.session.group(0x8000).set_rgb(0, 0, 255)
        await self.session.broadcast().set_power(False)
        self.assertEqual(len(self.commands()), 3)
        self.assertEqual(self.commands()[0], bytes.fromhex('123401060001'))
        self.assertEqual(self.commands()[1], bytes.fromhex('800001000306a9fe0200'))
        self.assertEqual(self.commands()[2], bytes.fromhex('ffff01060000'))
        self.assertTrue(all(response for _, _, response in self.transport.writes))

    async def test_reply_during_write_retained_until_later_wait(self):
        self.transport.reply = (0x0C, b'\x34\x12\0')
        receipt = await self.session.send_and_track_reply(groups.set_mesh_groups(ID, [0x8000]),
                                                   0x0C, target=ID, timeout=.1)
        await asyncio.sleep(.005)
        answer = await receipt.wait()
        self.assertEqual(answer.payload[:3], b'\x34\x12\0')
        self.assertEqual(len(self.commands()), 1)
        self.assertEqual(len(self.session._receipts), 0)

    async def test_no_reply_is_not_retried_and_does_not_block_next_write(self):
        receipt = await self.session.send_and_track_reply(groups.set_mesh_groups(ID, []),
                                                   0x0C, target=ID, timeout=.02)
        await self.session.lamp(ID).set_power(False)
        self.assertEqual(len(self.commands()), 2)
        self.assertIsNone(await receipt.wait())
        self.assertEqual(len(self.commands()), 2)

    async def test_expired_reply_is_not_resurrected_by_later_wait(self):
        self.transport.reply = (0x0C, b'\x34\x12\0')
        receipt = await self.session.send_and_track_reply(groups.set_mesh_groups(ID, []),
                                                   0x0C, target=ID, timeout=.01)
        await asyncio.sleep(.025)
        self.assertIsNone(await receipt.wait(timeout=1))
        self.assertEqual(len(self.session._receipts), 0)

    async def test_wrong_address_does_not_complete_window(self):
        self.transport.reply = (0x0C, b'\x35\x12\0')
        r = await self.session.send_and_track_reply(groups.set_mesh_groups(ID, []), 0x0C,
                                              target=ID, timeout=.01)
        self.assertIsNone(await r.wait())

    async def test_factory_exception_is_restricted_and_optional(self):
        self.transport.reply = (0x0C, b'\xff\xff\0')
        r = await self.session.send_and_track_reply(groups.set_mesh_groups(0, [0x8000]), 0x0C,
                                              target=0, factory=True, timeout=.02)
        self.assertEqual((await r.wait()).payload[:2], b'\xff\xff')
        with self.assertRaises(ValueError):
            await self.session.send_and_track_reply(groups.set_mesh_groups(ID, []), 0x0C,
                                              target=ID, factory=True)

    async def test_provision_bounds_group_iteration_before_writing(self):
        class OversizedGroups(list):
            consumed = 0

            def __iter__(self):
                for _ in range(200):
                    self.consumed += 1
                    yield 0x8000

        addresses = OversizedGroups()
        settings = provisioning.ProvisioningSettings(CREDS, bytes(16))
        with self.assertRaisesRegex(ValueError, 'one-byte APK frame limit'):
            await self.session.provision(ID, settings, groups=addresses)
        self.assertEqual(addresses.consumed, 126)
        self.assertEqual(self.transport.writes, [])

    async def test_no_groups_ack_gate_or_implicit_provisioning_followup(self):
        settings = provisioning.ProvisioningSettings(CREDS, bytes(range(16)))
        await self.session.write_mesh_groups(0, [0x8000, 0x8001, 0x8002])
        await self.session.set_mesh_credentials(CREDS.name, CREDS.password)
        self.transport.pair_response = b'\x07'
        self.assertEqual(await self.session.read_pair_response(), b'\x07')
        # Pair07 does not automatically send 03/04.
        self.assertEqual(len(self.commands()), 1)
        await self.session.set_network_parameters(settings)
        await self.session.set_network_key(settings.network_key)
        self.assertEqual([p[0] for p in self.commands()], [0x0C, 0x03, 0x04])

    async def test_schedule_continuation_is_owned_by_caller(self):
        from awox import ScheduleWritePart, routine_white_settings
        part = ScheduleWritePart.clock(5, 20, 0, routine_white_settings(20, 50, power_on=True), enabled=True)
        self.transport.reply = (0x33, bytes.fromhex('3412990005'))
        r = await self.session.send_and_track_reply(schedule.schedule_set(ID, part), 0x33,
                                              target=ID, routine=5, timeout=.1)
        self.assertEqual((await r.wait()).payload[2], 0x99)
        self.assertEqual(len(self.commands()), 1)

    async def test_04_and_83_are_distinct_observations(self):
        r = await self.session.send_and_track_reply(provisioning.build_network_key(bytes(16)),
                                              0x83, timeout=.02)
        self.transport.emit(0x04, bytes(19))
        self.assertFalse(r._future.done())
        self.transport.emit(0x83, bytes(19))
        self.assertEqual((await r.wait()).opcode, 0x83)

    async def test_disconnect_invalidates_pending_receipt(self):
        r = await self.session.send_and_track_reply(groups.get_mesh_groups(ID), 0x08, target=ID)
        await self.session.disconnect()
        with self.assertRaises(ConnectionLost):
            await r.wait()

    async def test_callback_failure_does_not_interrupt_receipt(self):
        self.session._on_notification = lambda n: (_ for _ in ()).throw(ValueError('test'))
        self.transport.reply = (0x0C, b'\x34\x12\0')
        r = await self.session.send_and_track_reply(groups.set_mesh_groups(ID, []), 0x0C, target=ID)
        self.assertIsNotNone(await r.wait())
        self.assertEqual(self.session.callback_errors, 1)

    async def test_connect_is_single_attempt_and_no_provisioning(self):
        self.assertTrue(self.session.connected)
        self.assertEqual(self.commands(), [])
        await self.session.connect()
        self.assertEqual(self.commands(), [])

    async def test_concurrent_lights_remain_ordered_no_added_waits(self):
        await asyncio.gather(*(self.session.lamp(ID).set_brightness(p) for p in range(50)))
        self.assertEqual(len(self.commands()), 50)

    async def test_82_status_early_during_query_ignores_passive_age_filter(self):
        self.session._status_max_age = .000001
        # Supported layout: addr, endpoint/format, model LE, MAC tail, marker, light.
        payload = bytes.fromhex('3412010000') + bytes.fromhex('9620') + bytes.fromhex('33221138') + bytes.fromhex('01018000000060')
        self.transport.reply = (0x82, payload)
        status = await self.session.read_status(ID, timeout=.03)
        self.assertIsNotNone(status)


    async def test_duplicate_pending_window_is_rejected_before_second_write(self):
        r = await self.session.send_and_track_reply(groups.get_mesh_groups(ID), 0x08, target=ID, timeout=.01)
        with self.assertRaises(RuntimeError):
            await self.session.send_and_track_reply(groups.get_mesh_groups(ID), 0x08, target=ID, timeout=.01)
        self.assertEqual(len(self.commands()), 1)
        await r.wait()

    async def test_enabled_schedule_read_masks_flag_before_routine_match(self):
        self.transport.reply = (0x35, bytes.fromhex('341285810000ff0001144d0111'))
        result = await self.session.read_schedule_part(ID, 5, timeout=.02)
        self.assertIsNotNone(result)
        self.assertEqual(result.routine_id, 5)
        self.assertTrue(result.enabled)

    async def test_captured_receipt_is_invalid_after_disconnect(self):
        self.transport.reply = (0x0C, b'\x34\x12\0')
        r = await self.session.send_and_track_reply(groups.set_mesh_groups(ID, []), 0x0C, target=ID)
        await self.session.disconnect()
        with self.assertRaises(ConnectionLost):
            await r.wait()

    async def test_wrong_mac_status_cannot_satisfy_active_read(self):
        self.transport.reply = (0x80, bytes.fromhex('34120100009620010203040101804d0150be60'))
        self.assertIsNone(await self.session.read_status(ID, timeout=.01))

    async def test_no_wait_receipt_expires_without_leaking_session_state(self):
        await self.session.send_and_track_reply(groups.get_mesh_groups(ID), 0x08, target=ID, timeout=.005)
        await asyncio.sleep(.02)
        self.assertEqual(len(self.session._receipts), 0)
        self.assertEqual(len(self.commands()), 1)

    async def test_invalid_receipt_parameters_never_write(self):
        frame = groups.get_mesh_groups(ID)
        for kwargs in ({'opcode':True}, {'opcode':256}, {'opcode':8, 'target':False},
                       {'opcode':8, 'routine':256}, {'opcode':8, 'timeout':float('inf')},
                       {'opcode':8, 'timeout':0}, {'opcode':8, 'factory':True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                await self.session.send_and_track_reply(frame, **kwargs)
        self.assertEqual(self.commands(), [])

    async def test_shorter_wait_never_resends(self):
        r = await self.session.send_and_track_reply(groups.get_mesh_groups(ID), 0x08, target=ID, timeout=1)
        self.assertIsNone(await r.wait(timeout=.005))
        self.assertEqual(len(self.commands()), 1)
        self.assertEqual(len(self.session._receipts), 0)

    async def test_negative_groups_response_does_not_block_next_setup_write(self):
        self.transport.reply = (0x0C, b'\x34\x12\x94')
        r = await self.session.send_and_track_reply(groups.set_mesh_groups(ID, []), 0x0C, target=ID)
        self.assertEqual((await r.wait()).payload[2], 0x94)
        await self.session.set_network_key(bytes(16))
        self.assertEqual(len(self.commands()), 2)


    async def test_failed_write_invalidates_other_pending_receipts(self):
        r = await self.session.send_and_track_reply(groups.get_mesh_groups(ID), 0x08, target=ID)
        original_write = self.transport.write
        async def fail(characteristic, data, response):
            if characteristic == COMMAND_UUID:
                raise OSError('simulated failed write')
            return await original_write(characteristic, data, response)
        self.transport.write = fail
        with self.assertRaises(OSError):
            await self.session.lamp(ID).set_power(False)
        self.assertFalse(self.session.connected)
        with self.assertRaises(ConnectionLost):
            await r.wait()


    async def test_schedule_error_reply_keeps_its_code_instead_of_timing_out(self):
        self.transport.reply = (0x35, bytes.fromhex('3412ff8205'))
        result = await self.session.read_schedule_part(ID, 5, timeout=.02)
        self.assertIsNotNone(result)
        self.assertEqual(result.error_code, 0x82)

    async def test_presence_error_reply_keeps_its_code_instead_of_timing_out(self):
        self.transport.reply = (0x3C, bytes.fromhex('3412ff8201'))
        result = await self.session.read_presence_simulator(ID, timeout=.02)
        self.assertIsNotNone(result)
        self.assertEqual(result.error_code, 0x82)


class SetupFailures(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_login_never_retries(self):
        t = FakeTransport()
        t.pair_response = b'\x0e'
        mesh = AwoXMeshSession(lambda: t, CREDS)
        with self.assertRaises(ValueError):
            await mesh.connect()
        self.assertFalse(mesh.connected)
        self.assertEqual(len(t.writes), 1)
        await mesh.disconnect()

    async def test_late_factory_result_closed_and_never_logged_in(self):
        release = asyncio.Event()
        t = FakeTransport()
        async def factory():
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return t
        mesh = AwoXMeshSession(factory, CREDS)
        with self.assertRaises(asyncio.TimeoutError):
            await mesh.connect(timeout=.01)
        with self.assertRaises(ConnectionLost):
            await mesh.connect(timeout=.01)
        release.set()
        await asyncio.sleep(.02)
        self.assertEqual(t.writes, [])
        self.assertEqual(t.disconnects, 1)
        await mesh.disconnect()


if __name__ == '__main__':
    unittest.main()


class ESPHomeSingleAttempt(unittest.IsolatedAsyncioTestCase):
    async def test_failed_connect_is_not_retried_and_client_is_cleaned_up(self):
        from types import SimpleNamespace
        from awox.esphome_transport import ESPHomeNoCCCDTransport
        calls = []
        class Client:
            async def connect(self):
                calls.append('connect')
                raise OSError('simulated first connection failure')
            async def disconnect(self):
                calls.append('disconnect')
        client = Client()
        def factory(*args, **kwargs):
            calls.append('factory')
            return client
        transport = ESPHomeNoCCCDTransport(
            SimpleNamespace(address='02:00:00:00:00:01'), client_factory=factory, backend_type=object,
        )
        with self.assertRaises(OSError):
            await transport.connect(lambda status: None)
        self.assertEqual(calls, ['factory', 'connect'])
        await transport.disconnect()
        self.assertEqual(calls, ['factory', 'connect', 'disconnect'])
