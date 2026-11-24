"""Proxy close deadlines never discard pending or failed cleanup ownership."""
import asyncio
import sys
import unittest
from unittest.mock import patch

from awox.esphome_proxy import ESPHomeProxy
from test_proxy_cleanup_disconnect_validation import FakeProxyDeps


class ProxyBoundedCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def blocked_stop(self, stage, *, cancel_waiter=False):
        deps = FakeProxyDeps()
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def blocked(manager):
            nonlocal calls
            calls += 1
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
        cls = deps.modules['bleak_esphome'].APIConnectionManager if stage == 'api' else deps.modules['habluetooth'].BluetoothManager
        method = 'stop' if stage == 'api' else 'async_stop'
        original_wait = asyncio.wait
        async def short_wait(tasks, *, timeout=None, return_when=asyncio.ALL_COMPLETED):
            return await original_wait(tasks, timeout=.02 if timeout == 15 else timeout,
                                       return_when=return_when)
        with patch.dict(sys.modules, deps.modules), patch.object(cls, method, blocked), patch.object(asyncio, 'wait', short_wait):
            proxy = await ESPHomeProxy('test.invalid').__aenter__()
            closing = asyncio.create_task(proxy.__aexit__())
            try:
                await entered.wait()
                if cancel_waiter:
                    closing.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await closing
                else:
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(asyncio.shield(closing), .3)
                cleanup = proxy._cleanup_task
                self.assertIsNotNone(cleanup)
                self.assertFalse(cleanup.done())
                with self.assertRaises(RuntimeError):
                    await proxy.__aenter__()
                with self.assertRaisesRegex(RuntimeError, 'another ESPHomeProxy'):
                    await ESPHomeProxy('other.invalid').__aenter__()
                with self.assertRaises(asyncio.TimeoutError):
                    await proxy.__aexit__()
                self.assertIs(proxy._cleanup_task, cleanup)
                self.assertEqual(calls, 1)
                release.set()
                await asyncio.wait_for(cleanup, .3)
                self.assertIsNone(proxy._bluetooth)
                await proxy.__aexit__()
                self.assertEqual(calls, 1)
                async with ESPHomeProxy('other.invalid'):
                    pass
            finally:
                release.set()
                await asyncio.gather(closing, return_exceptions=True)
                await proxy.__aexit__()

    async def test_api_stop_deadline_retains_cleanup_and_blocks_reopen(self):
        await self.blocked_stop('api')

    async def test_bluetooth_stop_deadline_retains_cleanup_and_blocks_reopen(self):
        await self.blocked_stop('bluetooth')

    async def test_cancelled_waiter_keeps_shared_cleanup_alive(self):
        await self.blocked_stop('api', cancel_waiter=True)

    async def test_bluetooth_failure_retry_does_not_repeat_successful_api_stop(self):
        deps = FakeProxyDeps()
        cls = deps.modules['habluetooth'].BluetoothManager
        count = 0
        async def stop(manager):
            nonlocal count
            count += 1
            if count == 1:
                raise OSError('bluetooth stop failed')
        with patch.dict(sys.modules, deps.modules), patch.object(cls, 'async_stop', stop):
            proxy = await ESPHomeProxy('test.invalid').__aenter__()
            try:
                with self.assertRaisesRegex(OSError, 'bluetooth stop failed'):
                    await proxy.__aexit__()
                self.assertEqual(deps.events.count('api.stop'), 1)
                with self.assertRaises(RuntimeError):
                    await ESPHomeProxy('other.invalid').__aenter__()
                await proxy.__aexit__()
                self.assertEqual(deps.events.count('api.stop'), 1)
                self.assertEqual(count, 2)
                self.assertIsNone(proxy._bluetooth)
            finally:
                await proxy.__aexit__()
