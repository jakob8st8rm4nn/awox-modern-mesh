"""An abandoned worker blocks its own channel, not other queue participants."""
import asyncio
import unittest

from awox.transport import (GattChannel, GattQueue, GattOperation, OperationKind,
                            GattOperationTimeout, ConnectionLost)


class Backend:
    def __init__(self, *, slow=False):
        self.slow = slow
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.connects = 0
        self.callback = None
        self.writes = []
        self.error = None

    async def connect(self, callback):
        self.connects += 1
        self.callback = callback

    async def disconnect(self):
        pass

    async def perform(self):
        self.started.set()
        if self.slow:
            while not self.release.is_set():
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    pass
        if self.error:
            raise self.error
        return b'result'

    async def read(self, characteristic):
        return await self.perform()

    async def write(self, characteristic, data, response):
        await self.perform()
        self.writes.append(data)


class ChannelWorkerGuardTests(unittest.IsolatedAsyncioTestCase):
    async def scenario(self, kind, *, cancel=False, physical_loss=False, late_error=False):
        queue = GattQueue()
        backend = Backend(slow=True)
        other_backend = Backend()
        channel = GattChannel(backend, queue=queue, operation_timeout=.01)
        other = GattChannel(other_backend, queue=queue, operation_timeout=.1)
        await channel.connect(lambda _: None)
        await other.connect(lambda _: None)
        request = asyncio.create_task(channel.execute(GattOperation(kind, 'test', b'first')))
        await backend.started.wait()
        worker = channel._operation
        try:
            if cancel:
                request.cancel()
            if physical_loss:
                backend.callback(8)
            with self.assertRaises(asyncio.CancelledError if cancel else GattOperationTimeout):
                await request
            self.assertFalse(worker.done())
            self.assertIs(channel._operation, worker)
            for _ in range(2):
                with self.assertRaisesRegex(ConnectionLost, 'GATT operation is still pending'):
                    await channel.connect(lambda _: None)
            self.assertEqual(backend.connects, 1)
            await asyncio.wait_for(other.execute(
                GattOperation(OperationKind.WRITE, 'test', b'other')), .3)
            self.assertEqual(other_backend.writes, [b'other'])
            self.assertFalse(worker.done())
            if late_error:
                backend.error = OSError('old worker failed late')
            backend.release.set()
            await asyncio.wait({worker}, timeout=.3)
            self.assertTrue(worker.done())
            await asyncio.sleep(0)
            self.assertIsNone(channel._operation)
            backend.slow = False
            backend.error = None
            await channel.connect(lambda _: None)
            generation = channel.generation
            await channel.execute(GattOperation(OperationKind.WRITE, 'test', b'new'))
            await asyncio.sleep(0)
            self.assertTrue(channel.active)
            self.assertEqual(channel.generation, generation)
            self.assertEqual(backend.writes[-1], b'new')
        finally:
            backend.release.set()
            await asyncio.gather(request, worker, return_exceptions=True)
            await channel.close()
            await other.close()

    async def test_timed_out_write_blocks_only_its_own_channel(self):
        await self.scenario(OperationKind.WRITE)

    async def test_timed_out_read_blocks_only_its_own_channel(self):
        await self.scenario(OperationKind.READ)

    async def test_caller_cancellation_keeps_worker_guard(self):
        await self.scenario(OperationKind.WRITE, cancel=True)

    async def test_physical_disconnect_keeps_worker_guard(self):
        await self.scenario(OperationKind.READ, physical_loss=True)

    async def test_late_worker_error_does_not_poison_replacement(self):
        await self.scenario(OperationKind.WRITE, late_error=True)
