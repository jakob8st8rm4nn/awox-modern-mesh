"""Regression tests for session observation reset and the optional GATT write hook.

Real session and connection paths, in-memory GATT fake; no BLE hardware.
"""
import asyncio
import unittest

from awox import AwoXMeshSession, ConnectionLost
from awox.frames import COMMAND_UUID, NOTIFY_UUID
from awox import groups
from test_session_operations import CREDS, FakeTransport, ID, MAC


# Known lamp model and the registered MAC's four reversed trailing bytes.
_VALID_STATUS = bytes.fromhex('34120100009620332211380101804d0150be60')
_WRONG_MAC_STATUS = bytes.fromhex('34120100009620010203040101804d0150be60')


class FailedConnectObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_activation_clears_early_result_codes(self):
        class FailingActivation(FakeTransport):
            async def write(self, characteristic, data, response):
                await super().write(characteristic, data, response)
                if characteristic == NOTIFY_UUID:
                    self.emit(0x40, bytes(5) + b"\x98")
                    self.emit(0x52, b"\xfe")
                    raise OSError("notification activation failed")

        transport = FailingActivation()
        notifications = []
        session = AwoXMeshSession(
            lambda: transport, CREDS, on_notification=notifications.append
        )

        with self.assertRaisesRegex(OSError, "notification activation failed"):
            await session.connect()

        self.assertEqual([event.opcode for event in notifications], [0x40, 0x52])
        self.assertFalse(session.connected)
        self.assertIsNone(session.last_quiet_result_code)
        self.assertIsNone(session.last_dual_zone_result_code)


class SessionResetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = FakeTransport()
        self.session = AwoXMeshSession(lambda: self.transport, CREDS, {ID: MAC})
        await self.session.connect()
        self.transport.writes.clear()

    async def asyncTearDown(self):
        await self.session.disconnect()

    async def test_disconnect_clears_all_observations_and_reconnect_retains_mac_check(self):
        statuses = self.session._statuses
        expected_macs = dict(statuses._expected)
        self.transport.emit(0x80, _VALID_STATUS)
        first = self.session.get_status(ID)
        self.assertIsNotNone(first)
        self.assertEqual(self.session.states[ID], first)
        self.assertIn((ID, 1), self.session.mesh_states)

        # Independent session observations must also be invalidated.
        self.transport.emit(0x40, b'\x00' * 5 + b'\x98')
        self.transport.emit(0x52, b'\xfe')
        self.assertEqual(self.session.last_quiet_result_code, -104)
        self.assertEqual(self.session.last_dual_zone_result_code, -2)
        pending = await self.session.send_and_track_reply(
            groups.get_mesh_groups(ID), 0x08, target=ID, timeout=1
        )
        self.assertFalse(pending._future.done())

        await self.session.disconnect()
        self.assertIs(self.session._statuses, statuses)
        self.assertEqual(statuses._expected, expected_macs)
        self.assertEqual(self.session._devices, {ID: MAC})
        self.assertEqual(statuses.states, {})
        self.assertIsNone(statuses.get(ID))
        self.assertEqual(self.session._mesh_statuses, {})
        self.assertEqual(self.session.states, {})
        self.assertEqual(self.session.mesh_states, {})
        self.assertIsNone(self.session.get_status(ID))
        self.assertIsNone(self.session.last_quiet_result_code)
        self.assertIsNone(self.session.last_dual_zone_result_code)
        self.assertTrue(pending._invalidated)
        with self.assertRaises(ConnectionLost):
            await pending.wait()

        await self.session.connect()
        self.assertIs(self.session._statuses, statuses)
        self.assertEqual(self.session.states, {})
        self.assertEqual(self.session.mesh_states, {})
        self.transport.emit(0x82, _WRONG_MAC_STATUS)
        self.assertEqual(self.session.states, {})
        self.assertEqual(self.session.mesh_states, {})
        self.transport.emit(0x82, _VALID_STATUS)
        second = self.session.get_status(ID)
        self.assertIsNotNone(second)
        self.assertEqual(second.source_opcode, 0x82)
        self.assertGreater(second.received_monotonic, first.received_monotonic)
        self.assertIn((ID, 1), self.session.mesh_states)

    async def test_failed_disconnect_blocks_reconnect_until_explicit_cleanup_retry(self):
        self.transport.emit(0x80, _VALID_STATUS)
        statuses = self.session._statuses
        original_disconnect = self.transport.disconnect
        attempts = 0

        async def flaky_disconnect():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError('simulated cleanup failure')
            await original_disconnect()

        self.transport.disconnect = flaky_disconnect
        with self.assertRaisesRegex(OSError, 'simulated cleanup failure'):
            await self.session.disconnect()
        self.assertIs(self.session._statuses, statuses)
        self.assertEqual(statuses.states, {})
        self.assertFalse(self.session.connected)
        with self.assertRaisesRegex(ConnectionLost, 'previous connection cleanup failed'):
            await self.session.connect()
        self.assertEqual(attempts, 1)
        await self.session.disconnect()  # Explicit recovery, not an automatic retry.
        self.assertEqual(attempts, 2)
        await self.session.connect()
        self.assertIs(self.session._statuses, statuses)
        self.transport.emit(0x80, _VALID_STATUS)
        self.assertIsNotNone(self.session.get_status(ID))


class CommandWriteHookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = FakeTransport()
        self.session = AwoXMeshSession(lambda: self.transport, CREDS, {ID: MAC})
        await self.session.connect()
        self.transport.writes.clear()

    async def asyncTearDown(self):
        await self.session.disconnect()

    def command_writes(self):
        return [(char, data, response) for char, data, response
                in self.transport.writes if char == COMMAND_UUID]

    async def test_no_hook_and_hook_each_make_exactly_one_write(self):
        packet1, packet2 = b'without hook', b'with hook'
        events = []
        original_write = self.transport.write

        async def record_write(characteristic, data, response):
            if characteristic == COMMAND_UUID:
                events.append(('write', bytes(data)))
            return await original_write(characteristic, data, response)

        self.transport.write = record_write
        await self.session._connection._write_command_packet(packet1)

        def hook():
            events.append(('hook', None))

        await self.session._connection._write_command_packet(packet2, before_write=hook)
        self.assertEqual(events, [('write', packet1), ('hook', None), ('write', packet2)])
        self.assertEqual(self.command_writes(), [(COMMAND_UUID, packet1, True),
                                                (COMMAND_UUID, packet2, True)])
        self.assertTrue(self.session.connected)

    async def test_hook_error_and_local_cancellation_never_touch_gatt(self):
        failure = ValueError('hook rejected write')

        def bad_hook():
            raise failure

        with self.assertRaises(ValueError) as seen:
            await self.session._connection._write_command_packet(b'bad', before_write=bad_hook)
        self.assertIs(seen.exception, failure)
        self.assertEqual(self.command_writes(), [])
        self.assertTrue(self.session.connected)

        cancelled = asyncio.CancelledError('local hook cancelled')

        def cancel_hook():
            raise cancelled

        with self.assertRaises(asyncio.CancelledError) as seen:
            await self.session._connection._write_command_packet(b'cancelled', before_write=cancel_hook)
        self.assertIs(seen.exception, cancelled)
        self.assertEqual(self.command_writes(), [])
        self.assertTrue(self.session.connected)
        await self.session._connection._write_command_packet(b'good')
        self.assertEqual(len(self.command_writes()), 1)

    async def test_backend_write_failure_invalidates_channel_without_replay(self):
        original_write = self.transport.write
        attempts = 0

        async def fail_once(characteristic, data, response):
            nonlocal attempts
            if characteristic == COMMAND_UUID:
                attempts += 1
                raise OSError('simulated GATT write failure')
            await original_write(characteristic, data, response)

        self.transport.write = fail_once
        with self.assertRaisesRegex(OSError, 'simulated GATT write failure'):
            await self.session._connection._write_command_packet(b'one')
        self.assertEqual(attempts, 1)
        self.assertFalse(self.session.connected)

    async def test_caller_cancellation_does_not_replay_in_flight_write(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        original_write = self.transport.write

        async def blocked_write(characteristic, data, response):
            await original_write(characteristic, data, response)
            if characteristic == COMMAND_UUID:
                entered.set()
                await release.wait()

        self.transport.write = blocked_write
        task = asyncio.create_task(self.session._connection._write_command_packet(b'one'))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(len(self.command_writes()), 1)
            self.assertFalse(self.session.connected)
        finally:
            release.set()
