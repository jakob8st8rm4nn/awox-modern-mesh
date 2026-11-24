"""API stop calls serialize per manager, including concurrent exit during startup."""
import asyncio
import sys
import unittest
from unittest.mock import patch

from awox.esphome_proxy import ESPHomeProxy
from test_proxy_cleanup_disconnect_validation import FakeProxyDeps


class ProxyConcurrentStopTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self, *, cancel_start=False, fail_first=False):
        deps = FakeProxyDeps()
        cls = deps.modules['bleak_esphome'].APIConnectionManager
        started, release_start = asyncio.Event(), asyncio.Event()
        stop_entered, release_stop = asyncio.Event(), asyncio.Event()
        active = maximum = count = 0

        async def start(manager):
            started.set()
            try:
                await release_start.wait()
            except asyncio.CancelledError:
                await release_start.wait()

        async def stop(manager):
            nonlocal active, maximum, count
            count += 1
            current = count
            active += 1
            maximum = max(maximum, active)
            try:
                if current == 1:
                    stop_entered.set()
                    await release_stop.wait()
                    if fail_first:
                        raise OSError('first stop failed')
            finally:
                active -= 1

        with patch.dict(sys.modules, deps.modules), patch.object(cls, 'start', start), patch.object(cls, 'stop', stop):
            proxy = ESPHomeProxy('test.invalid')
            opening = asyncio.create_task(proxy.__aenter__())
            closing = None
            try:
                await started.wait()
                closing = asyncio.create_task(proxy.__aexit__())
                await stop_entered.wait()
                if cancel_start:
                    opening.cancel()
                release_start.set()
                for _ in range(10):
                    await asyncio.sleep(0)
                self.assertEqual(count, 1)
                self.assertEqual(maximum, 1)
                release_stop.set()
                results = await asyncio.gather(opening, closing, return_exceptions=True)
                self.assertIsInstance(results[0], asyncio.CancelledError if cancel_start else RuntimeError)
                if fail_first:
                    self.assertIsInstance(results[1], OSError)
                else:
                    self.assertIsNone(results[1])
                for _ in range(10):
                    await asyncio.sleep(0)
                self.assertEqual(count, 2)
                self.assertEqual(maximum, 1)
                self.assertIsNone(proxy._manager)
                if fail_first:
                    # A later standalone stop does not acknowledge the failed
                    # context cleanup; an explicit close retries its open step.
                    self.assertIsNotNone(proxy._bluetooth)
                    await proxy.__aexit__()
                    self.assertEqual(maximum, 1)
                self.assertIsNone(proxy._bluetooth)
            finally:
                release_start.set()
                release_stop.set()
                await asyncio.gather(*[t for t in (opening, closing) if t is not None], return_exceptions=True)
                await proxy.__aexit__()

    async def test_explicit_exit_during_successful_start_does_not_overlap_stops(self):
        await self.scenario()

    async def test_cancelled_start_during_external_exit_does_not_overlap_stops(self):
        await self.scenario(cancel_start=True)

    async def test_failed_first_stop_releases_lock_for_late_cleanup(self):
        await self.scenario(fail_first=True)

    async def test_late_stop_survives_cancellation_and_can_be_retried(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                deps = FakeProxyDeps()
                cls = deps.modules["bleak_esphome"].APIConnectionManager
                started, release_start = asyncio.Event(), asyncio.Event()
                stopping, release_stop = asyncio.Event(), asyncio.Event()
                stops = []

                async def start(manager):
                    started.set()
                    await release_start.wait()

                async def stop(manager):
                    stops.append(manager)
                    if len(stops) == 2:
                        stopping.set()
                        await release_stop.wait()
                        if fail:
                            raise OSError("late stop failed")

                with patch.dict(sys.modules, deps.modules), patch.object(cls, "start", start), patch.object(cls, "stop", stop):
                    proxy = ESPHomeProxy("test.invalid")
                    opening = asyncio.create_task(proxy.__aenter__())
                    try:
                        await asyncio.wait_for(started.wait(), 1)
                        await proxy.__aexit__()
                        release_start.set()
                        await asyncio.wait_for(stopping.wait(), 1)
                        opening.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await opening
                        release_stop.set()
                        if fail:
                            with self.assertRaisesRegex(OSError, "late stop failed"):
                                await proxy.__aexit__()
                        await proxy.__aexit__()
                        self.assertEqual(len(stops), 3 if fail else 2)
                        self.assertTrue(all(manager is stops[0] for manager in stops))
                    finally:
                        release_start.set()
                        release_stop.set()
                        await asyncio.gather(opening, return_exceptions=True)
                        await proxy.__aexit__()

    async def test_explicit_exit_retries_failed_late_stop_after_new_context(self):
        deps = FakeProxyDeps()
        cls = deps.modules["bleak_esphome"].APIConnectionManager
        started, release_start = asyncio.Event(), asyncio.Event()
        managers, stops = [], []
        active = set()

        async def start(manager):
            managers.append(manager)
            if len(managers) == 1:
                started.set()
                await release_start.wait()
            active.add(manager)

        async def stop(manager):
            stops.append(manager)
            if manager is managers[0] and stops.count(manager) == 2:
                raise OSError("late stop failed")
            active.discard(manager)

        with patch.dict(sys.modules, deps.modules), patch.object(cls, "start", start), patch.object(cls, "stop", stop):
            proxy = ESPHomeProxy("test.invalid")
            opening = asyncio.create_task(proxy.__aenter__())
            try:
                await asyncio.wait_for(started.wait(), 1)
                await proxy.__aexit__()
                with self.assertLogs("awox.esphome_proxy", level="ERROR"):
                    release_start.set()
                    with self.assertRaisesRegex(RuntimeError, "context closed during API setup"):
                        await asyncio.wait_for(opening, 1)
                old_manager = managers[0]
                self.assertEqual(active, {old_manager})

                async with proxy:
                    self.assertEqual(active, set(managers))
                self.assertEqual(active, {old_manager})
                self.assertEqual(stops, [old_manager, old_manager, managers[1]])

                await proxy.__aexit__()
                self.assertFalse(active)
                self.assertEqual(stops, [old_manager, old_manager, managers[1], old_manager])
            finally:
                release_start.set()
                await asyncio.gather(opening, return_exceptions=True)
                await proxy.__aexit__()

    async def test_old_cleanup_does_not_hold_new_managers_stop_lock(self):
        deps = FakeProxyDeps()
        cls = deps.modules['bleak_esphome'].APIConnectionManager
        managers = []
        original_init = cls.__init__
        started, release_start = asyncio.Event(), asyncio.Event()
        old_late_stop, release_late_stop = asyncio.Event(), asyncio.Event()
        stops = []
        def initialize(manager, config):
            original_init(manager, config)
            managers.append(manager)
        async def start(manager):
            if manager is managers[0]:
                started.set()
                await release_start.wait()
        async def stop(manager):
            stops.append(manager)
            if manager is managers[0] and stops.count(manager) == 2:
                old_late_stop.set()
                await release_late_stop.wait()
        with patch.dict(sys.modules, deps.modules), patch.object(cls, '__init__', initialize), patch.object(cls, 'start', start), patch.object(cls, 'stop', stop):
            proxy = ESPHomeProxy('test.invalid')
            old_opening = asyncio.create_task(proxy.__aenter__())
            try:
                await started.wait()
                await proxy.__aexit__()
                await proxy.__aenter__()
                new_manager = proxy._manager
                release_start.set()
                await asyncio.wait_for(old_late_stop.wait(), 1)
                self.assertIs(proxy._manager, new_manager)
                await asyncio.wait_for(proxy.__aexit__(), 0.2)
                self.assertIn(new_manager, stops)
                release_late_stop.set()
                with self.assertRaises(RuntimeError):
                    await old_opening
            finally:
                release_start.set()
                release_late_stop.set()
                await asyncio.gather(old_opening, return_exceptions=True)
                await proxy.__aexit__()
