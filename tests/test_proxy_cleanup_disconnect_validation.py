"""Offline N1-N4 regressions: no network, BLE stack or device access."""
import asyncio
import sys
import types
import unittest
from unittest.mock import patch
from awox.esphome_proxy import ESPHomeProxy
from awox.frames import COMMAND_UUID, NOTIFY_UUID, PAIR_UUID, SERVICE_UUID
from awox.session import Credentials
from awox.transport import ConnectionLost
CREDS = Credentials('example', 'password')
DEVICES = {40157: 'AA:BB:CC:DD:EE:FF'}

class FakeProxyDeps:

    def __init__(self, *, setup_error=None, start_error=None, stop_error=None, stop_is_async=False):
        self.manager = object()
        self.events = []
        self.setup_error = setup_error
        self.start_error = start_error
        self.stop_error = stop_error
        self.stop_is_async = stop_is_async
        outer = self

        class BluetoothManager:

            def __init__(self):
                outer.events.append('bluetooth.create')

            async def async_setup(self):
                outer.events.append('bluetooth.setup')
                if outer.setup_error:
                    raise outer.setup_error

            def async_stop(self):
                outer.events.append('bluetooth.stop')
                if outer.stop_is_async:

                    async def finish():
                        outer.events.append('bluetooth.stop.awaited')
                    return finish()
                return None

        class APIConnectionManager:

            def __init__(self, config):
                outer.events.append('api.create')
                self.config = config

            async def start(self):
                outer.events.append('api.start')
                if outer.start_error:
                    raise outer.start_error

            async def stop(self):
                outer.events.append('api.stop')
                if outer.stop_error:
                    raise outer.stop_error

        class HaBleakClientWrapper:

            async def connect(self, **kwargs):
                self._backend = ESPHomeClient()

            async def disconnect(self):
                pass

        class ESPHomeClient:
            pass

        def get_manager():
            if outer.manager is None:
                raise RuntimeError('no bluetooth manager')
            return outer.manager

        def set_manager(value):
            outer.events.append('global.set')
            outer.manager = value
        habluetooth = types.ModuleType('habluetooth')
        habluetooth.BluetoothManager = BluetoothManager
        habluetooth.HaBleakClientWrapper = HaBleakClientWrapper
        habluetooth.get_manager = get_manager
        habluetooth.set_manager = set_manager
        bleak = types.ModuleType('bleak_esphome')
        bleak.APIConnectionManager = APIConnectionManager
        backend = types.ModuleType('bleak_esphome.backend')
        client = types.ModuleType('bleak_esphome.backend.client')
        client.ESPHomeClient = ESPHomeClient
        self.modules = {'habluetooth': habluetooth, 'bleak_esphome': bleak, 'bleak_esphome.backend': backend, 'bleak_esphome.backend.client': client}

class ProxyCleanupTests(unittest.IsolatedAsyncioTestCase):

    async def test_second_owner_is_rejected_until_cleanup_finishes(self):
        deps = FakeProxyDeps()
        started, release = (asyncio.Event(), asyncio.Event())

        async def stop(_manager):
            started.set()
            await release.wait()
        with patch.dict(sys.modules, deps.modules):
            first = await ESPHomeProxy('first.example').__aenter__()
            with patch.object(deps.modules['bleak_esphome'].APIConnectionManager, 'stop', stop):
                task = asyncio.create_task(first.__aexit__(None, None, None))
                try:
                    await started.wait()
                    with self.assertRaisesRegex(RuntimeError, 'another ESPHomeProxy'):
                        await ESPHomeProxy('second.example').__aenter__()
                finally:
                    release.set()
                    await task
            async with ESPHomeProxy('second.example'):
                pass

    async def test_second_owner_is_rejected_without_changing_first_owner(self):
        deps = FakeProxyDeps()
        original = deps.manager
        with patch.dict(sys.modules, deps.modules):
            async with ESPHomeProxy('first.example') as first:
                manager = deps.manager
                before = list(deps.events)
                second = ESPHomeProxy('second.example')
                with self.assertRaisesRegex(RuntimeError, 'another ESPHomeProxy'):
                    await second.__aenter__()
                self.assertIs(deps.manager, manager)
                self.assertEqual(deps.events, before)
                # Explicit cleanup of a rejected owner cannot release the first.
                await second.__aexit__(None, None, None)
                with self.assertRaisesRegex(RuntimeError, 'another ESPHomeProxy'):
                    await ESPHomeProxy('third.example').__aenter__()
                self.assertIs(first._bluetooth, manager)
            self.assertIs(deps.manager, original)
            async with second:
                self.assertIsNot(deps.manager, original)
            self.assertIs(deps.manager, original)

    async def test_setup_failure_releases_owner_for_next_context(self):
        deps = FakeProxyDeps(setup_error=RuntimeError('setup failure'))
        with patch.dict(sys.modules, deps.modules):
            with self.assertRaisesRegex(RuntimeError, 'setup failure'):
                await ESPHomeProxy('first.example').__aenter__()
            deps.setup_error = None
            async with ESPHomeProxy('second.example'):
                pass

    async def test_second_owner_is_rejected_while_first_is_starting(self):
        deps = FakeProxyDeps()
        started, release = (asyncio.Event(), asyncio.Event())

        async def setup(_manager):
            started.set()
            await release.wait()
        with patch.dict(sys.modules, deps.modules), patch.object(deps.modules['habluetooth'].BluetoothManager, 'async_setup', setup):
            first = ESPHomeProxy('first.example')
            task = asyncio.create_task(first.__aenter__())
            try:
                await started.wait()
                with self.assertRaisesRegex(RuntimeError, 'another ESPHomeProxy'):
                    await ESPHomeProxy('second.example').__aenter__()
            finally:
                release.set()
                await task
                await first.__aexit__(None, None, None)

    async def test_close_waits_for_bluetooth_setup_before_stopping_manager(self):
        deps = FakeProxyDeps()
        bluetooth_type = deps.modules['habluetooth'].BluetoothManager
        started, release = asyncio.Event(), asyncio.Event()

        async def setup(_manager):
            started.set()
            await release.wait()
            deps.events.append('bluetooth.tracking_started')

        with patch.dict(sys.modules, deps.modules), patch.object(bluetooth_type, 'async_setup', setup):
            proxy = ESPHomeProxy('first.example')
            opening = asyncio.create_task(proxy.__aenter__())
            await started.wait()
            closing = asyncio.create_task(proxy.__aexit__())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            try:
                self.assertNotIn('bluetooth.stop', deps.events)
                self.assertFalse(closing.done())
                with self.assertRaisesRegex(RuntimeError, 'another ESPHomeProxy'):
                    await ESPHomeProxy('second.example').__aenter__()
            finally:
                release.set()
                with self.assertRaisesRegex(RuntimeError, 'closed during Bluetooth setup'):
                    await opening
                await closing
            self.assertLess(deps.events.index('bluetooth.tracking_started'), deps.events.index('bluetooth.stop'))
            self.assertNotIn('api.start', deps.events)
            async with ESPHomeProxy('second.example'):
                pass

    async def test_close_cleans_up_setup_failure_and_cancellation(self):
        for outcome in ('setup_error', 'cancel_open', 'cancel_close'):
            with self.subTest(outcome=outcome):
                deps = FakeProxyDeps()
                previous = deps.manager
                bluetooth_type = deps.modules['habluetooth'].BluetoothManager
                started, release = asyncio.Event(), asyncio.Event()

                async def setup(_manager):
                    started.set()
                    try:
                        await release.wait()
                        if outcome == 'setup_error':
                            raise ValueError('setup failed')
                    finally:
                        deps.events.append('bluetooth.setup_finished')

                with patch.dict(sys.modules, deps.modules):
                    with patch.object(bluetooth_type, 'async_setup', setup):
                        proxy = ESPHomeProxy('first.example')
                        opening = asyncio.create_task(proxy.__aenter__())
                        await started.wait()
                        closing = asyncio.create_task(proxy.__aexit__())
                        await asyncio.sleep(0)
                        if outcome == 'cancel_open':
                            opening.cancel()
                            expected = asyncio.CancelledError
                        elif outcome == 'cancel_close':
                            closing.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await closing
                            closing = asyncio.create_task(proxy.__aexit__())
                            expected = RuntimeError
                        else:
                            expected = ValueError
                        release.set()
                        with self.assertRaises(expected):
                            await opening
                        await closing

                    self.assertEqual(deps.events.count('bluetooth.stop'), 1)
                    self.assertLess(
                        deps.events.index('bluetooth.setup_finished'),
                        deps.events.index('bluetooth.stop'),
                    )
                    self.assertNotIn('api.start', deps.events)
                    self.assertIs(deps.manager, previous)
                    async with ESPHomeProxy('second.example'):
                        pass

    async def test_cancelled_setup_releases_owner(self):
        deps = FakeProxyDeps()
        started = asyncio.Event()

        async def setup(_manager):
            started.set()
            await asyncio.Event().wait()
        with patch.dict(sys.modules, deps.modules):
            with patch.object(deps.modules['habluetooth'].BluetoothManager, 'async_setup', setup):
                task = asyncio.create_task(ESPHomeProxy('first.example').__aenter__())
                await started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            async with ESPHomeProxy('second.example'):
                pass

    async def test_context_releases_both_managers_and_restores_previous_global(self):
        deps = FakeProxyDeps(stop_is_async=True)
        previous = deps.manager
        with patch.dict(sys.modules, deps.modules):
            proxy = ESPHomeProxy('proxy.example')
            async with proxy:
                self.assertIsNot(deps.manager, previous)
                self.assertIsNotNone(proxy._manager)
                with self.assertRaises(RuntimeError):
                    await proxy.__aenter__()
            self.assertIs(deps.manager, previous)
            self.assertIsNone(proxy._bluetooth)
            self.assertIsNone(proxy._manager)
            self.assertLess(deps.events.index('api.stop'), deps.events.index('bluetooth.stop'))
            self.assertIn('bluetooth.stop.awaited', deps.events)
            async with ESPHomeProxy('proxy.example'):
                pass
            self.assertIs(deps.manager, previous)
            self.assertEqual(deps.events.count('bluetooth.stop'), 2)

    async def test_setup_failure_releases_bluetooth_and_previous_global(self):
        deps = FakeProxyDeps(setup_error=RuntimeError('setup failure'))
        previous = deps.manager
        with patch.dict(sys.modules, deps.modules):
            with self.assertRaisesRegex(RuntimeError, 'setup failure'):
                async with ESPHomeProxy('proxy.example'):
                    pass
        self.assertIs(deps.manager, previous)
        self.assertIn('bluetooth.stop', deps.events)
        self.assertNotIn('api.stop', deps.events)

    async def test_api_start_failure_releases_api_and_bluetooth(self):
        deps = FakeProxyDeps(start_error=RuntimeError('api failure'))
        previous = deps.manager
        with patch.dict(sys.modules, deps.modules):
            with self.assertRaisesRegex(RuntimeError, 'api failure'):
                async with ESPHomeProxy('proxy.example'):
                    pass
        self.assertIs(deps.manager, previous)
        self.assertIn('api.stop', deps.events)
        self.assertIn('bluetooth.stop', deps.events)

    async def test_stop_failure_retains_owner_until_explicit_cleanup_retry(self):
        deps = FakeProxyDeps(stop_error=RuntimeError('stop failure'))
        previous = deps.manager
        with patch.dict(sys.modules, deps.modules):
            proxy = await ESPHomeProxy('proxy.example').__aenter__()
            try:
                with self.assertRaisesRegex(RuntimeError, 'stop failure'):
                    await proxy.__aexit__()
                self.assertIsNot(deps.manager, previous)
                self.assertIn('bluetooth.stop', deps.events)
                with self.assertRaisesRegex(RuntimeError, 'another ESPHomeProxy'):
                    await ESPHomeProxy('second.example').__aenter__()
            finally:
                deps.stop_error = None
                await proxy.__aexit__()
            self.assertIs(deps.manager, previous)
            self.assertEqual(deps.events.count('bluetooth.stop'), 1)

    async def test_does_not_overwrite_global_manager_replaced_by_other_owner(self):
        deps = FakeProxyDeps()
        other = object()
        with patch.dict(sys.modules, deps.modules):
            async with ESPHomeProxy('proxy.example'):
                deps.manager = other
            self.assertIs(deps.manager, other)
            self.assertIn('bluetooth.stop', deps.events)

    async def test_no_global_manager_before_context_is_restored(self):
        deps = FakeProxyDeps()
        deps.manager = None
        with patch.dict(sys.modules, deps.modules):
            async with ESPHomeProxy('proxy.example'):
                self.assertIsNotNone(deps.manager)
        self.assertIsNone(deps.manager)
if __name__ == '__main__':
    unittest.main()
