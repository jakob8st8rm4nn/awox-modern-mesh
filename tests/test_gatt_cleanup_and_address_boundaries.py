"""Offline regressions for fixed targets, time validation and client cleanup."""
import asyncio
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import unittest
from awox.targets import MeshTarget
from awox.clock import build_time_with_timezone
from awox.timezone_rule import format_apk_fixed_timezone, format_apk_dst_timezone
from awox.esphome_transport import _ESPHomeBleakTransportBase
from awox.transport import GattChannel, ConnectionLost
from test_timezone_rule import vienna_start, vienna_end

class NoEncode(str):

    def encode(self, *args, **kwargs):
        raise AssertionError('oversized string encoded')

class InputAndAddressBoundaries(unittest.TestCase):

    def test_target_address_is_read_only(self):
        for address, replacement in ((32769, 65535), (65535, 32769)):
            target = MeshTarget(None, address)
            with self.assertRaises(AttributeError):
                target.destination = replacement
            self.assertEqual(target.destination, address)

    def test_rule_length_before_encoding(self):
        with self.assertRaises(ValueError):
            build_time_with_timezone(946684800000, NoEncode('A' * 4096))
        for rule in ('UTC0', 'A' * 30):
            self.assertIn(rule.encode(), build_time_with_timezone(946684800000, rule).plaintext)

    def test_zone_offset_bounds(self):
        for offset in (-64801, 64801, -70000, 70000):
            with self.assertRaises(ValueError):
                format_apk_fixed_timezone(offset)
            with self.assertRaises(ValueError):
                format_apk_dst_timezone('STD', offset, 'DST', vienna_start(), vienna_end())
        for offset in (-64800, 64800):
            self.assertIsInstance(format_apk_fixed_timezone(offset), str)
            format_apk_dst_timezone('STD', offset, 'DST', vienna_start(), vienna_end())

    def test_long_names_and_fallback(self):
        self.assertIsNone(format_apk_dst_timezone('A' * 4096, 3600, 'DST', vienna_start(), vienna_end()))
        expected = format_apk_dst_timezone('STD', 3600, 'DST', vienna_start(), vienna_end())
        self.assertEqual(format_apk_dst_timezone('A' * 4096 + '!', 3600, 'DST', vienna_start(), vienna_end()), expected)

    def test_gatt_timeout_overflow_is_value_error(self):
        with self.assertRaises(ValueError):
            GattChannel(None, operation_timeout=10 ** 1000)

class Client:

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0
        self.is_connected = True
        self.started = asyncio.Event()
        self.release = None
        self.active = 0
        self.maximum_active = 0

    async def disconnect(self):
        self.calls += 1
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            self.started.set()
            if self.release is not None:
                await self.release.wait()
            if self.fail:
                raise OSError('simulated cleanup failure')
            self.is_connected = False
        finally:
            self.active -= 1

def transport():
    return _ESPHomeBleakTransportBase(SimpleNamespace(address='A4:C1:00:00:00:01', name='test'), client_factory=object)

def connector(establish):
    module = ModuleType('bleak_retry_connector')
    module.establish_connection = establish
    return patch('awox.esphome_transport._ESPHomeBleakTransportBase._open_client', side_effect=establish)

class CleanupTests(unittest.IsolatedAsyncioTestCase):

    async def test_late_failed_cleanup_is_retried(self):
        client = Client(fail=True)
        started, release = (asyncio.Event(), asyncio.Event())

        async def establish(*args, **kwargs):
            started.set()
            await release.wait()
            return client
        t = transport()
        with connector(establish):
            task = asyncio.create_task(t.connect(lambda _: None))
            await started.wait()
            await t.disconnect()
            release.set()
            with self.assertRaises(ConnectionLost):
                await task
            self.assertIn(client, t._cleanup_clients)
            client.fail = False
            await t.disconnect()
        self.assertEqual(client.calls, 2)
        self.assertFalse(client.is_connected)
        self.assertEqual(t._cleanup_clients, [])

    async def test_overlapping_disconnects_retain_failed_client(self):
        t = transport()
        client = Client(fail=True)
        client.release = asyncio.Event()
        t._client = client
        first = asyncio.create_task(t.disconnect())
        await client.started.wait()
        second = asyncio.create_task(t.disconnect())
        await asyncio.sleep(0)
        client.release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        self.assertTrue(all((isinstance(result, OSError) for result in results)))
        client.fail = False
        await t.disconnect()
        self.assertFalse(client.is_connected)
        self.assertEqual(client.maximum_active, 1)
        self.assertEqual(t._cleanup_clients, [])

    async def test_concurrent_success_closes_client_once(self):
        t = transport()
        client = Client()
        client.release = asyncio.Event()
        t._client = client
        first = asyncio.create_task(t.disconnect())
        await client.started.wait()
        second = asyncio.create_task(t.disconnect())
        await asyncio.sleep(0)
        client.release.set()
        await asyncio.gather(first, second)
        self.assertEqual(client.calls, 1)
        self.assertEqual(t._cleanup_clients, [])

    async def test_old_failure_does_not_fail_successful_current_close(self):
        t = transport()
        old, current = (Client(fail=True), Client())
        t._cleanup_clients.append(old)
        t._client = current
        await t.disconnect()
        self.assertFalse(current.is_connected)
        self.assertIsNone(t._client)
        self.assertIn(old, t._cleanup_clients)
        old.fail = False
        await t.disconnect()
        self.assertFalse(old.is_connected)

    async def test_connect_waits_for_old_cleanup(self):
        t = transport()
        old, new = (Client(fail=True), Client())
        t._cleanup_clients.append(old)
        calls = []

        async def establish(*args, **kwargs):
            calls.append(1)
            return new
        with connector(establish):
            with self.assertRaises(OSError):
                await t.connect(lambda _: None)
            self.assertEqual(calls, [])
            old.fail = False
            await t.connect(lambda _: None)
            self.assertIs(t._client, new)
            await t.disconnect()
        self.assertEqual(calls, [1])

    async def test_cancelled_cleanup_remains_owned(self):
        t = transport()
        client = Client()
        client.release = asyncio.Event()
        t._client = client
        task = asyncio.create_task(t.disconnect())
        await client.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIn(client, t._cleanup_clients)
        client.release.set()
        await t.disconnect()
        self.assertFalse(client.is_connected)
        self.assertEqual(t._cleanup_clients, [])

    async def test_old_connect_cannot_replace_new_client(self):
        t = transport()
        old, new = (Client(fail=True), Client())
        started, release = (asyncio.Event(), asyncio.Event())
        calls = 0

        async def establish(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await release.wait()
                return old
            return new
        with connector(establish):
            first = asyncio.create_task(t.connect(lambda _: None))
            await started.wait()
            await t.connect(lambda _: None)
            release.set()
            with self.assertRaises(ConnectionLost):
                await first
            self.assertIs(t._client, new)
            self.assertIn(old, t._cleanup_clients)
            await t.disconnect()
            self.assertFalse(new.is_connected)
            old.fail = False
            await t.disconnect()
            self.assertFalse(old.is_connected)

    async def test_overlapping_cleanup_snapshots_do_not_reclose_clients(self):
        t = transport()
        first, second = (Client(), Client())
        first.release = asyncio.Event()
        t._cleanup_clients.extend((first, second))
        a = asyncio.create_task(t.disconnect())
        await first.started.wait()
        b = asyncio.create_task(t.disconnect())
        await asyncio.sleep(0)
        first.release.set()
        await asyncio.gather(a, b)
        self.assertEqual((first.calls, second.calls), (1, 1))
        self.assertEqual(t._cleanup_clients, [])
