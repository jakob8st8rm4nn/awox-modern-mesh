"""Offline reproducibility tests for ESPHome API startup cancellation/timeout.

No ESPHome packages, Bluetooth access, network or user credentials required.
"""
import asyncio
import sys
import unittest
from unittest.mock import patch

from awox.esphome_proxy import ESPHomeProxy
from test_proxy_cleanup_disconnect_validation import FakeProxyDeps


class ProxyStartCancelTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def _scenario(self, cancel_explicitly: bool) -> None:
        deps = FakeProxyDeps()
        entered = asyncio.Event()
        release = asyncio.Event()
        stop_counts = []
        start_cancel_seen = asyncio.Event()

        async def delayed_start(_manager):
            entered.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                start_cancel_seen.set()
                # Intentionally non-cooperative backend startup.
                await release.wait()

        original_wait_for = asyncio.wait_for
        original_wait = asyncio.wait

        async def short_wait(tasks, *, timeout=None, return_when=asyncio.ALL_COMPLETED):
            return await original_wait(tasks, timeout=0.02 if timeout == 30 else timeout,
                                       return_when=return_when)

        async def short_wait_for(awaitable, timeout, *args, **kwargs):
            # Shorten the production 30-second proxy startup timeout only.
            return await original_wait_for(
                awaitable, 0.02 if timeout == 30 else timeout, *args, **kwargs
            )

        api_cls = deps.modules['bleak_esphome'].APIConnectionManager
        original_stop = api_cls.stop

        async def counted_stop(manager):
            stop_counts.append(manager)
            await original_stop(manager)

        with (patch.dict(sys.modules, deps.modules),
              patch.object(api_cls, 'start', delayed_start),
              patch.object(api_cls, 'stop', counted_stop),
              patch.object(asyncio, 'wait_for', short_wait_for),
              patch.object(asyncio, 'wait', short_wait)):
            proxy = ESPHomeProxy('fake.local')
            operation = asyncio.create_task(proxy.__aenter__())
            try:
                await original_wait_for(entered.wait(), 1)
                if cancel_explicitly:
                    operation.cancel()
                await original_wait_for(start_cancel_seen.wait(), 1)
                # The library should finish caller cancellation / timeout
                # even if the external backend keeps running indefinitely.
                await asyncio.sleep(0.05)
                completed_before_release = operation.done()
                release.set()
                if cancel_explicitly:
                    with self.assertRaises(asyncio.CancelledError):
                        await original_wait_for(operation, 1)
                else:
                    with self.assertRaises(asyncio.TimeoutError):
                        await original_wait_for(operation, 1)
                self.assertTrue(completed_before_release)
                self.assertIsNone(proxy._manager)
                self.assertIsNone(proxy._bluetooth)
                # Late successful start must also have cleanup scheduled.
                await asyncio.sleep(0.02)
                self.assertGreaterEqual(len(stop_counts), 2)
            finally:
                release.set()
                if not operation.done():
                    operation.cancel()
                try:
                    await original_wait_for(operation, 1)
                except (Exception, asyncio.CancelledError):
                    pass
                if proxy._bluetooth is not None:
                    await proxy.__aexit__()

    async def test_noncooperative_proxy_start_cannot_overrun_timeout(self):
        await self._scenario(False)

    async def test_explicit_cancellation_cleans_up_late_start(self):
        await self._scenario(True)


    async def test_late_stop_waits_for_original_cleanup(self):
        deps = FakeProxyDeps()
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        release_start = asyncio.Event()
        first_stop_started = asyncio.Event()
        release_first_stop = asyncio.Event()
        stop_count = 0

        async def start(_manager):
            entered.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled.set()
                await release_start.wait()

        async def stop(_manager):
            nonlocal stop_count
            stop_count += 1
            if stop_count == 1:
                first_stop_started.set()
                await release_first_stop.wait()

        old_wait = asyncio.wait
        async def quick_wait(tasks, *, timeout=None, return_when=asyncio.ALL_COMPLETED):
            return await old_wait(tasks, timeout=0.02 if timeout == 30 else timeout,
                                  return_when=return_when)

        manager_type = deps.modules['bleak_esphome'].APIConnectionManager
        with (patch.dict(sys.modules, deps.modules),
              patch.object(manager_type, 'start', start),
              patch.object(manager_type, 'stop', stop),
              patch.object(asyncio, 'wait', quick_wait)):
            proxy = ESPHomeProxy('test.invalid')
            operation = asyncio.create_task(proxy.__aenter__())
            try:
                await asyncio.wait_for(entered.wait(), 1)
                await asyncio.wait_for(cancelled.wait(), 1)
                await asyncio.wait_for(first_stop_started.wait(), 1)
                release_start.set()  # Late backend success, while stop #1 is blocked.
                await asyncio.sleep(0.04)
                self.assertEqual(stop_count, 1, 'two stops raced on the same manager')
                release_first_stop.set()
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(operation, 1)
                await asyncio.sleep(0.04)
                self.assertEqual(stop_count, 2)
                self.assertIsNone(proxy._bluetooth)
            finally:
                release_start.set()
                release_first_stop.set()
                if not operation.done():
                    operation.cancel()
                try:
                    await asyncio.wait_for(operation, 1)
                except (Exception, asyncio.CancelledError):
                    pass
                if proxy._bluetooth is not None:
                    await proxy.__aexit__()

    async def test_old_late_start_cleanup_preserves_new_proxy_context(self):
        deps = FakeProxyDeps()
        entered = asyncio.Event()
        release = asyncio.Event()
        managers = []
        stops = []
        cls = deps.modules['bleak_esphome'].APIConnectionManager
        original_init = cls.__init__

        def create(manager, config):
            original_init(manager, config)
            managers.append(manager)

        async def start(manager):
            if manager is managers[0]:
                entered.set()
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    await release.wait()

        async def stop(manager):
            stops.append(manager)

        old_wait = asyncio.wait
        async def quick_wait(tasks, *, timeout=None, return_when=asyncio.ALL_COMPLETED):
            return await old_wait(tasks, timeout=0.02 if timeout == 30 else timeout,
                                  return_when=return_when)

        with (patch.dict(sys.modules, deps.modules),
              patch.object(cls, '__init__', create),
              patch.object(cls, 'start', start),
              patch.object(cls, 'stop', stop),
              patch.object(asyncio, 'wait', quick_wait)):
            first = ESPHomeProxy('first.invalid')
            old = asyncio.create_task(first.__aenter__())
            second = ESPHomeProxy('second.invalid')
            try:
                await asyncio.wait_for(entered.wait(), 1)
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(old, 1)
                self.assertIsNone(first._manager)
                async with second:
                    self.assertIs(second._manager, managers[1])
                    self.assertIsNotNone(second._bluetooth)
                    release.set()
                    await asyncio.sleep(0.05)
                    self.assertIs(second._manager, managers[1])
                    self.assertNotIn(managers[1], stops)
                    self.assertGreaterEqual(stops.count(managers[0]), 2)
            finally:
                release.set()
                if not old.done():
                    old.cancel()
                try:
                    await old
                except (Exception, asyncio.CancelledError):
                    pass
                if second._bluetooth is not None:
                    await second.__aexit__()
                if first._bluetooth is not None:
                    await first.__aexit__()


if __name__ == '__main__':
    unittest.main()
