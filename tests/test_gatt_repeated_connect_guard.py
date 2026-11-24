"""Repeated connect must not create or invalidate a second physical link."""
import asyncio
import unittest

from awox.transport import ConnectionLost, GattChannel, GattOperation, OperationKind


class CountingBackend:
    def __init__(self):
        self.links = 0
        self.events = []
        self.callbacks = []
        self.fail_next_connect = False
        self.connect_gate = None
        self.connect_entered = asyncio.Event()
        self.write_gate = None
        self.write_entered = asyncio.Event()

    async def connect(self, callback):
        self.events.append('connect')
        self.connect_entered.set()
        if self.connect_gate is not None:
            await self.connect_gate.wait()
        if self.fail_next_connect:
            raise OSError('backend would fail a second connection')
        self.links += 1
        self.callbacks.append(callback)

    async def disconnect(self):
        self.events.append('disconnect')
        self.links = max(0, self.links - 1)

    async def write(self, characteristic, data, response):
        self.events.append(('write', bytes(data)))
        self.write_entered.set()
        if self.write_gate is not None:
            await self.write_gate.wait()


class RepeatedConnectGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_connect_leaves_original_link_and_callback_intact(self):
        backend = CountingBackend()
        channel = GattChannel(backend)
        disconnected = []
        await channel.connect(disconnected.append)
        generation = channel.generation
        try:
            with self.assertRaisesRegex(ConnectionLost, 'already connected'):
                await channel.connect(lambda _: None)
            self.assertTrue(channel.active)
            self.assertEqual(channel.generation, generation)
            self.assertEqual(backend.events, ['connect'])
            self.assertEqual(backend.links, 1)
            backend.links = 0  # Physical link loss, then its original callback.
            backend.callbacks[0](8)
            self.assertFalse(channel.active)
            self.assertEqual(disconnected, [8])
        finally:
            await channel.close()

    async def test_duplicate_never_calls_backend_that_would_fail(self):
        backend = CountingBackend()
        channel = GattChannel(backend)
        await channel.connect(lambda _: None)
        backend.fail_next_connect = True
        try:
            with self.assertRaises(ConnectionLost):
                await channel.connect(lambda _: None)
            self.assertTrue(channel.active)
            self.assertEqual(backend.links, 1)
            self.assertEqual(backend.events, ['connect'])
        finally:
            await channel.close()

    async def test_concurrent_duplicate_does_not_replace_pending_attempt(self):
        backend = CountingBackend()
        backend.connect_gate = asyncio.Event()
        channel = GattChannel(backend)
        pending = asyncio.create_task(channel.connect(lambda _: None))
        try:
            await asyncio.wait_for(backend.connect_entered.wait(), 1)
            generation = channel.generation
            with self.assertRaisesRegex(ConnectionLost, 'already pending'):
                await channel.connect(lambda _: None)
            self.assertEqual(channel.generation, generation)
            self.assertEqual(backend.events, ['connect'])
            backend.connect_gate.set()
            await pending
            self.assertTrue(channel.active)
            self.assertEqual(backend.links, 1)
        finally:
            backend.connect_gate.set()
            await asyncio.gather(pending, return_exceptions=True)
            await channel.close()

    async def test_rejected_duplicate_does_not_cancel_inflight_write(self):
        backend = CountingBackend()
        backend.write_gate = asyncio.Event()
        channel = GattChannel(backend)
        await channel.connect(lambda _: None)
        pending = asyncio.create_task(channel.execute(GattOperation(OperationKind.WRITE, '1912', b'once')))
        try:
            await asyncio.wait_for(backend.write_entered.wait(), 1)
            with self.assertRaises(ConnectionLost):
                await channel.connect(lambda _: None)
            self.assertFalse(pending.done())
            self.assertTrue(channel.active)
            backend.write_gate.set()
            await pending
            self.assertEqual(backend.events, ['connect', ('write', b'once')])
        finally:
            backend.write_gate.set()
            await asyncio.gather(pending, return_exceptions=True)
            await channel.close()

    async def test_close_then_connect_opens_exactly_one_replacement(self):
        backend = CountingBackend()
        channel = GattChannel(backend)
        await channel.connect(lambda _: None)
        await channel.close()
        await channel.connect(lambda _: None)
        try:
            self.assertEqual(backend.links, 1)
            self.assertEqual(backend.events, ['connect', 'disconnect', 'connect'])
            self.assertTrue(channel.active)
        finally:
            await channel.close()

    async def test_physical_loss_allows_reconnect_and_old_callback_stays_stale(self):
        backend = CountingBackend()
        channel = GattChannel(backend)
        await channel.connect(lambda _: None)
        old_callback = backend.callbacks[0]
        backend.links = 0
        old_callback(8)
        await channel.connect(lambda _: None)
        try:
            old_callback(8)
            self.assertTrue(channel.active)
            self.assertEqual(backend.links, 1)
        finally:
            await channel.close()
