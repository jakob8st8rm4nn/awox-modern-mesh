"""Strict operation kinds and local-vs-I/O cancellation; offline only."""
import asyncio
from enum import IntEnum
import unittest
from awox.session import Credentials
from awox.transport import GattChannel, GattOperation, OperationKind, ConnectionLost
from transport_fixture import FakeTransport

class Backend(FakeTransport):

    async def start_notify(self, characteristic, callback):
        self.calls.append(('notify', characteristic))

class GattKindAndLocalCancellationTests(unittest.IsolatedAsyncioTestCase):

    async def test_invalid_kinds_never_touch_backend(self):

        class OtherKind(IntEnum):
            WRITE = 0
        backend = Backend()
        channel = GattChannel(backend)
        await channel.connect(lambda *args: None)
        for kind in (False, True, 0, 1, 2, 3, 4, 0.0, 1.0, 99, 'WRITE', None, OtherKind.WRITE):
            with self.subTest(kind=kind, type=type(kind)):
                with self.assertRaises(ValueError):
                    await channel.execute(GattOperation(kind, 'sample', b'data'))
                self.assertEqual(backend.calls, [('connect',)])
                self.assertTrue(channel.active)
        await channel.close()

    async def test_valid_operation_kinds_still_work(self):
        backend = Backend()
        channel = GattChannel(backend)
        await channel.connect(lambda *args: None)
        for kind in OperationKind:
            await channel.execute(GattOperation(kind, 'sample', b'data'), lambda data: None)
        self.assertEqual([call[0] for call in backend.calls], ['connect', 'write', 'read', 'notify', 'stop_notify', 'mtu'])
        await channel.close()

    async def test_local_hook_cancellation_preserves_channel(self):
        backend = Backend()
        channel = GattChannel(backend)
        await channel.connect(lambda *args: None)
        original = asyncio.CancelledError('local preparation cancelled')

        def hook():
            raise original
        with self.assertRaises(asyncio.CancelledError) as caught:
            await channel.execute(GattOperation(OperationKind.WRITE, 'sample', b'data'), before_write=hook)
        self.assertIs(caught.exception, original)
        self.assertTrue(channel.active)
        self.assertEqual(backend.calls, [('connect',)])
        await channel.execute(GattOperation(OperationKind.WRITE, 'sample', b'next'))
        self.assertEqual(backend.calls[-1][0], 'write')
        await channel.close()

    async def test_simultaneous_caller_cancel_is_not_hidden_by_local_cancel(self):
        backend = Backend()
        channel = GattChannel(backend)
        await channel.connect(lambda *args: None)

        async def send():
            caller = asyncio.current_task()

            def hook():
                caller.cancel()
                raise asyncio.CancelledError('local cancellation too')
            await channel.execute(GattOperation(OperationKind.WRITE, 'sample', b'data'), before_write=hook)
        with self.assertRaises(asyncio.CancelledError):
            await send()
        self.assertFalse(channel.active)
        self.assertEqual(backend.calls, [('connect',), ('disconnect',)])

    async def test_backend_cancellation_still_invalidates_channel(self):

        class CancelledBackend(Backend):

            async def write(self, *args):
                raise asyncio.CancelledError('backend cancellation')
        backend = CancelledBackend()
        channel = GattChannel(backend)
        await channel.connect(lambda *args: None)
        with self.assertRaises(ConnectionLost):
            await channel.execute(GattOperation(OperationKind.WRITE, 'sample', b'data'))
        self.assertFalse(channel.active)
        self.assertIn(('disconnect',), backend.calls)
