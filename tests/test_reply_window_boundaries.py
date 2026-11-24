"""Offline regressions for local response windows, not on-air transaction IDs."""

import asyncio
import time
import unittest
from unittest.mock import patch

from awox import AwoXMeshSession, ConnectionLost, ScheduleWritePart, routine_white_settings
from awox import schedule
from awox.status import parse_status_variant
from awox.crypto import aes_att_encryption
from awox.frames import COMMAND_UUID, ExtendedNotification, addressed_query, open_frame
from test_session_operations import CREDS, FakeTransport, ID, MAC


class ReplyWindowBoundaries(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = FakeTransport()
        self.mesh = AwoXMeshSession(lambda: self.transport, CREDS, {ID: MAC})
        await self.mesh.connect()
        self.transport.writes.clear()

    async def asyncTearDown(self):
        await self.mesh.disconnect()

    async def test_queued_operations_cannot_write_to_replacement_connection(self):
        timer = ScheduleWritePart(b"\x02" + bytes(9))
        cases = (
            (self.mesh._reply_lock(0x0C, ID), lambda: self.mesh.set_mesh_groups(ID, [0x8001])),
            (self.mesh._schedule_lock(ID), lambda: self.mesh.set_timer(ID, timer)),
            (self.mesh._reply_lock(0x80, ID), lambda: self.mesh.read_status(ID)),
            (self.mesh._time29_lock, lambda: self.mesh.set_time_with_timezone(1_700_000_000_000, "UTC0")),
        )
        for lock, operation in cases:
            replacement = FakeTransport()
            async with lock:
                waiting = asyncio.create_task(operation())
                try:
                    await asyncio.sleep(0)
                    await self.mesh.disconnect()
                    self.mesh._transport_factory = lambda: replacement
                    await self.mesh.connect()
                except BaseException:
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
                    raise
            with self.assertRaisesRegex(ConnectionLost, "replaced connection"):
                await asyncio.wait_for(waiting, 1)
            self.assertFalse(any(uuid == COMMAND_UUID for uuid, _, _ in replacement.writes))

    async def test_non_callable_reply_filter_is_rejected_before_write(self):
        with self.assertRaisesRegex(TypeError, "_accept must be callable or None"):
            await self.mesh.send_and_track_reply(
                addressed_query(ID, 0x08), 0x08, target=ID, _accept=False
            )
        self.assertFalse(self.transport.writes)
        self.assertFalse(self.mesh._receipts)

    async def test_expired_reply_is_rejected_before_delayed_timer_runs(self):
        receipt = await self.mesh.send_and_track_reply(
            addressed_query(ID, 0x08), 0x08, target=ID, timeout=1
        )
        # Simulate event-loop processing latency: the receive handler runs
        # after the absolute deadline but before the timeout callback.
        receipt._deadline = asyncio.get_running_loop().time() - .025
        self.mesh._receive(ExtendedNotification(0x08, 'raw', b'\x34\x12\x00', b'\x34\x12\x00'))
        self.assertIsNone(await receipt.wait())
        self.assertNotIn(receipt, self.mesh._receipts)

    async def test_late_receive_after_blocked_event_loop_is_not_accepted(self):
        receipt = await self.mesh.send_and_track_reply(
            addressed_query(ID, 0x08), 0x08, target=ID, timeout=.01,
        )
        # Mimic a synchronous backend that blocks the timer callback.
        time.sleep(.03)
        self.transport.emit(0x08, b'\x34\x12\x00')
        self.assertIsNone(await receipt.wait())
        self.assertNotIn(receipt, self.mesh._receipts)

    async def test_disconnect_invalidates_reply_before_waiter_resumes(self):
        receipt = await self.mesh.send_and_track_reply(
            addressed_query(ID, 0x08), 0x08, target=ID, timeout=1,
        )
        waiter = asyncio.create_task(receipt.wait())
        await asyncio.sleep(0)  # Let the waiter begin waiting for the reply.
        self.transport.emit(0x08, b'\x34\x12\x00')
        # Disconnect invalidates receipts before its first await.
        await self.mesh.disconnect()
        with self.assertRaises(ConnectionLost):
            await waiter

    async def test_short_wait_uses_receive_time_when_timer_is_delayed(self):
        loop = asyncio.get_running_loop()
        for arrival, accepted in ((0.5, True), (2.0, False)):
            with self.subTest(arrival=arrival):
                receipt = await self.mesh.send_and_track_reply(
                    addressed_query(ID, 0x08), 0x08, target=ID, timeout=10,
                )
                start = loop.time()
                waiter = asyncio.create_task(receipt.wait(timeout=1))
                await asyncio.sleep(0)  # Install the shorter wait timer.
                # Deliver before the event loop can service the due timer.
                with patch.object(loop, 'time', return_value=start + arrival):
                    self.transport.emit(0x08, b'\x34\x12\x00')
                self.assertEqual((await waiter) is not None, accepted)
                self.assertNotIn(receipt, self.mesh._receipts)

    async def test_captured_reply_expires_before_late_first_wait(self):
        receipt = await self.mesh.send_and_track_reply(
            addressed_query(ID, 0x08), 0x08, target=ID, timeout=.04,
        )
        notification = ExtendedNotification(0x08, 'raw', b'\x34\x12\x00', b'\x34\x12\x00')
        self.mesh._receive(notification)
        await asyncio.sleep(.055)
        self.assertIsNone(await receipt.wait())

    async def test_schedule_read_rejects_reply_after_total_deadline(self):
        loop = asyncio.get_running_loop()
        real_time = loop.time
        offset = 0.0
        write_started = asyncio.Event()
        release_write = asyncio.Event()
        write = self.transport.write
        from awox.frames import COMMAND_UUID

        async def slow_write(characteristic, data, response):
            await write(characteristic, data, response)
            if characteristic == COMMAND_UUID:
                write_started.set()
                await release_write.wait()

        self.transport.write = slow_write
        with patch.object(loop, "time", side_effect=lambda: real_time() + offset):
            task = asyncio.create_task(self.mesh.read_nightlight(ID, timeout=1))
            try:
                await asyncio.wait_for(write_started.wait(), timeout=0.5)
                offset = 0.25
                release_write.set()
                # Wait until the GATT write has finished and the receipt is armed.
                async def wait_until_written():
                    while not any(r._deadline is not None for r in self.mesh._receipts):
                        await asyncio.sleep(0)

                await asyncio.wait_for(wait_until_written(), timeout=0.5)
                receipt = next(iter(self.mesh._receipts))
                offset = 1.125
                self.assertLess(loop.time(), receipt._deadline)
                # Deliver synchronously, before the due asyncio timer can run.
                self.transport.emit(0x35, bytes.fromhex('341285810000ff0001144d0111'))
                self.assertIsNone(await task)
            finally:
                release_write.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_schedule_timer_expires_in_gatt_queue_without_write(self):
        loop = asyncio.get_running_loop()
        real_time = loop.time
        offset = 0.0
        write_started = asyncio.Event()
        release_write = asyncio.Event()
        timer_queued = asyncio.Event()
        write = self.transport.write
        send = self.mesh._connection.send_frame

        async def hold_first_write(characteristic, data, response):
            await write(characteristic, data, response)
            if characteristic == COMMAND_UUID and not write_started.is_set():
                write_started.set()
                await release_write.wait()

        async def observe_timer_queue(frame, **kwargs):
            if frame.plaintext[0] == 2 and frame.plaintext[3] == 0x33:
                timer_queued.set()
            return await send(frame, **kwargs)

        self.transport.write = hold_first_write
        self.mesh._connection.send_frame = observe_timer_queue
        lamp = self.mesh.lamp(ID)
        timer = ScheduleWritePart.timer(
            20, routine_white_settings(20, 50, power_on=True), enabled=True,
        )
        tasks = [asyncio.create_task(lamp.set_power(True))]
        try:
            await asyncio.wait_for(write_started.wait(), 1)
            with patch.object(loop, 'time', side_effect=lambda: real_time() + offset):
                tasks.append(asyncio.create_task(lamp.set_timer(timer, timeout=1)))
                await asyncio.wait_for(timer_queued.wait(), 1)
                offset = 2.0
                release_write.set()
                result = await tasks[1]
                await tasks[0]
            self.assertIsNone(result.start_response)
            self.assertEqual(sum(c == COMMAND_UUID for c, _, _ in self.transport.writes), 1)
            self.assertTrue(self.mesh.connected)
        finally:
            release_write.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_second_schedule_part_does_not_cross_connections(self):
        light = routine_white_settings(20, 50, power_on=True)
        start = ScheduleWritePart.clock(5, 21, 0, light, enabled=True)
        end = ScheduleWritePart.clock(6, 23, 0, light, enabled=True)
        self.transport.reply = (0x33, bytes.fromhex("3412990005"))
        replacement = FakeTransport()
        queued = asyncio.Event()
        build = schedule.schedule_set

        def observe_second_part(destination, part):
            if part.routine_id == 6:
                queued.set()
            return build(destination, part)

        with patch.object(schedule, "schedule_set", side_effect=observe_second_part):
            async with self.mesh._reply_lock(0x33, ID, 6):
                waiting = asyncio.create_task(self.mesh.set_nightlight(ID, start, end))
                try:
                    await asyncio.wait_for(queued.wait(), 1)
                    await self.mesh.disconnect()
                    self.mesh._transport_factory = lambda: replacement
                    await self.mesh.connect()
                except BaseException:
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
                    raise
            with self.assertRaises(ConnectionLost):
                await asyncio.wait_for(waiting, 1)
        self.assertEqual(sum(uuid == COMMAND_UUID for uuid, _, _ in self.transport.writes), 1)
        self.assertFalse(any(uuid == COMMAND_UUID for uuid, _, _ in replacement.writes))

    async def test_schedule_end_flag_stays_false_when_end_expires_before_write(self):
        loop = asyncio.get_running_loop()
        real_time = loop.time
        offset = 0.0
        build = schedule.schedule_set

        def expire_end(destination, part):
            nonlocal offset
            if part.routine_id == 6:
                offset = 2.0
            return build(destination, part)

        self.transport.reply = (0x33, bytes.fromhex('3412990005'))
        light = routine_white_settings(20, 50, power_on=True)
        start = ScheduleWritePart.clock(5, 21, 0, light, enabled=True)
        end = ScheduleWritePart.clock(6, 23, 0, light, enabled=True)
        with (
            patch.object(loop, 'time', side_effect=lambda: real_time() + offset),
            patch.object(schedule, 'schedule_set', side_effect=expire_end),
        ):
            result = await self.mesh.lamp(ID).set_nightlight(start, end, timeout=1)

        self.assertTrue(result.start_response.requires_followup)
        self.assertFalse(result.end_sent)
        self.assertIsNone(result.end_response)
        commands = [
            open_frame(self.transport.key, packet).data
            for char, packet, _ in self.transport.writes if char == COMMAND_UUID
        ]
        self.assertEqual([(cmd[0], cmd[3] & 0x7F) for cmd in commands], [(0x33, 5)])

    async def test_target_wildcard_overlaps_specific_target(self):
        first = await self.mesh.send_and_track_reply(
            addressed_query(ID, 0x08), 0x08, timeout=.2
        )
        with self.assertRaisesRegex(RuntimeError, 'overlapping'):
            await self.mesh.send_and_track_reply(
                addressed_query(ID, 0x08), 0x08, target=ID, timeout=.2,
            )
        first._expire()

    async def test_status_receipts_match_registered_identity_with_or_without_target(self):
        valid = bytes.fromhex('341201000096203322113801018000000060').ljust(19, b'\0')
        wrong_mac = valid[:7] + b'\x00' + valid[8:]
        for selector, opcode in ((0x80, 0x80), (0x80, 0x82), (0x82, 0x82)):
            for target in (None, ID):
                with self.subTest(selector=selector, opcode=opcode, target=target):
                    receipt = await self.mesh.send_and_track_reply(
                        addressed_query(ID, 0x0A), selector, target=target, timeout=1,
                    )
                    self.transport.emit(opcode, wrong_mac)
                    self.transport.emit(opcode, valid)
                    response = await receipt.wait()
                    self.assertIsNotNone(response)
                    self.assertEqual(response.payload, valid)

    async def test_raw_receipts_support_full_mac_and_compact_status(self):
        full = bytes.fromhex('341202010033221138c1a40101800000000060')
        compact = bytes.fromhex('341203000096203322113801018000000060')
        for payload, mac_offset in ((full, 10), (compact, 7)):
            wrong_mac = payload[:mac_offset] + b'\x00' + payload[mac_offset + 1:]
            for selector, opcode in ((0x80, 0x80), (0x80, 0x82), (0x82, 0x82)):
                for target in (None, ID):
                    with self.subTest(size=len(payload), selector=selector, opcode=opcode, target=target):
                        receipt = await self.mesh.send_and_track_reply(
                            addressed_query(ID, 0x0A), selector, target=target, timeout=1,
                        )
                        for data in (wrong_mac, payload):
                            wire = bytes((opcode,)) + aes_att_encryption(self.transport.key, data[:16]) + data[16:]
                            self.transport.callback(wire)
                        response = await receipt.wait()
                        self.assertIsNotNone(response)
                        self.assertEqual(response.payload, payload)

    async def test_raw_status_identity_is_shared_by_receipts_and_cache(self):
        transport = FakeTransport()
        devices = {ID: MAC, ID + 1: 'aa:bb:38:44:55:66'}
        compact = bytes.fromhex('35120100009620665544380101800000006000')
        full = bytes.fromhex('351202010066554438bbaa0101800000000060')
        ordinary = bytes.fromhex('34120100009620332211380101800000006000')

        async with AwoXMeshSession(lambda: transport, CREDS, devices) as mesh:
            first = await mesh.send_and_track_reply(
                addressed_query(ID, 0x0A), 0x82, target=ID, timeout=1,
            )
            second = await mesh.send_and_track_reply(
                addressed_query(ID + 1, 0x0A), 0x82, target=ID + 1, timeout=1,
            )
            with patch('awox.session.parse_status_variant', wraps=parse_status_variant) as decode:
                transport.emit(0x82, compact)
                self.assertEqual(mesh.mesh_states, {})
                transport.emit(0x82, full)
                transport.emit(0x82, ordinary)
                self.assertEqual(decode.call_count, 3)

            self.assertEqual((await first.wait()).payload, ordinary)
            self.assertEqual((await second.wait()).payload, full)
            self.assertEqual(set(mesh.mesh_states), {(ID, 1), (ID + 1, 2)})

    async def test_active_lamp_status_uses_same_mac_tail_as_passive_observation(self):
        lamp = bytes.fromhex('34120100009620332211380101800000006000')
        wrong_mac = lamp[:7] + b'\x00' + lamp[8:]
        transport = FakeTransport()
        notifications = []
        async with AwoXMeshSession(
            lambda: transport, CREDS, {ID: '02:00:38:11:22:33'},
            on_status=notifications.append,
        ) as mesh:
            emit = transport.emit

            def emit_both(opcode, payload):
                emit(opcode, wrong_mac)
                emit(opcode, payload)

            transport.reply = (0x82, lamp)
            with patch.object(transport, 'emit', emit_both):
                result = await mesh.read_status(ID, timeout=.2)
            self.assertIsNotNone(result)
            self.assertEqual(result.raw_response, b'\x82' + lamp)
            self.assertEqual(mesh.get_status(ID).raw_response, result.raw_response)
            self.assertEqual(len(notifications), 1)
            self.assertEqual(mesh.mesh_states, {})

    async def test_lamp_read_waits_past_raw_status_for_lamp_layout(self):
        full = bytes.fromhex('341202010033221138c1a40101800000000060')
        lamp = bytes.fromhex('341201000096203322113801018000000060').ljust(19, b'\0')
        emit = self.transport.emit

        def emit_both(opcode, payload):
            emit(opcode, full)
            emit(opcode, payload)

        self.transport.reply = (0x82, lamp)
        with patch.object(self.transport, 'emit', emit_both):
            status = await self.mesh.read_status(ID)
        self.assertIsNotNone(status)
        self.assertEqual(status.raw_response, b'\x82' + lamp)

    async def test_status_80_and_82_selector_overlap(self):
        first = await self.mesh.send_and_track_reply(
            addressed_query(ID, 0x0A), 0x80, target=ID, timeout=.2,
        )
        with self.assertRaisesRegex(RuntimeError, 'overlapping'):
            await self.mesh.send_and_track_reply(
                addressed_query(ID, 0x0A), 0x82, target=ID, timeout=.2,
            )
        first._expire()

    async def test_factory_group_ack_overlaps_ffff_selector(self):
        first = await self.mesh.send_and_track_reply(
            addressed_query(0, 0x08), 0x0C, target=0, factory=True, timeout=.2,
        )
        with self.assertRaisesRegex(RuntimeError, 'overlapping'):
            await self.mesh.send_and_track_reply(
                addressed_query(0, 0x08), 0x0C, target=0xFFFF, timeout=.2,
            )
        first._expire()

    async def test_distinct_targets_can_coexist(self):
        first = await self.mesh.send_and_track_reply(
            addressed_query(ID, 0x08), 0x08, target=ID, timeout=.2,
        )
        second = await self.mesh.send_and_track_reply(
            addressed_query(0x3456, 0x08), 0x08, target=0x3456, timeout=.2,
        )
        self.mesh._receive(ExtendedNotification(0x08, 'raw', b'\x34\x12\x00', b'\x34\x12\x00'))
        self.assertIsNotNone(await first.wait())
        self.assertIsNone(await second.wait(timeout=.01))

    async def test_wildcard_routine_overlaps_specific_routine(self):
        first = await self.mesh.send_and_track_reply(
            addressed_query(ID, 0x35), 0x35, target=ID, timeout=.2,
        )
        with self.assertRaisesRegex(RuntimeError, 'overlapping'):
            await self.mesh.send_and_track_reply(
                addressed_query(ID, 0x35), 0x35, target=ID, routine=7, timeout=.2,
            )
        first._expire()

    async def test_live_encrypted_notifications_have_raw_kinds(self):
        from awox.session import decode_apk_notification
        import awox.session as session_module
        self.assertFalse(hasattr(session_module, 'decode_notification'))
        self.assertTrue(callable(decode_apk_notification))
        observations = []
        self.mesh._on_notification = observations.append
        for opcode in (0x29, 0x40, 0x37):
            self.transport.emit(opcode, bytes(19))
        self.assertEqual([n.opcode for n in observations], [0x29, 0x40, 0x37])
        self.assertTrue(all(n.kind == 'raw' and n.value == n.payload
                            for n in observations))

    def test_remote_example_keeps_wizard_pause_after_group_write(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / 'examples' /
                  'app_26_remote_provisioning.py').read_text()
        group = source.index('await setup.write_mesh_groups(current_id, BUTTON_GROUPS)')
        pause = source.index('await asyncio.sleep(1)')
        provision = source.index('result = await setup.provision(')
        self.assertLess(group, pause)
        self.assertLess(pause, provision)

    async def test_notification_callback_receives_raw_envelope(self):
        received = []
        self.mesh._on_notification = received.append
        self.mesh._receive(ExtendedNotification(0x40, 'raw', b'\x00' * 16, b'\x00' * 16))
        self.assertEqual(received[0].opcode, 0x40)
        self.assertEqual(received[0].kind, 'raw')
        self.assertEqual(received[0].value, received[0].payload)


class OpcodeValidation(unittest.TestCase):
    def test_bool_and_out_of_range_are_rejected(self):
        for opcode in (True, False, -1, 256, 1.0):
            with self.subTest(opcode=opcode), self.assertRaises(ValueError):
                addressed_query(ID, opcode)

    def test_valid_opcode_bytes_are_unchanged(self):
        self.assertEqual(addressed_query(ID, 1).plaintext[3], 1)


if __name__ == '__main__':
    unittest.main()
