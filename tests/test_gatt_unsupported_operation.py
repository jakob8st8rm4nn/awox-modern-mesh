"""Only the portable unsupported MTU request is a harmless backend exception."""
import unittest

from awox.transport import GattChannel, GattOperation, OperationKind


class UnsupportedTransport:
    def __init__(self):
        self.closed = 0
        self.calls = []

    async def disconnect(self):
        self.closed += 1

    async def fail(self, *args):
        self.calls.append(args)
        raise NotImplementedError('backend operation failed')

    read = write = start_notify = stop_notify = request_mtu = fail


class UnsupportedOperationTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_mtu_backend_errors_invalidate_and_close(self):
        for kind in (OperationKind.WRITE, OperationKind.READ,
                     OperationKind.ENABLE_NOTIFY, OperationKind.DISABLE_NOTIFY):
            with self.subTest(kind=kind):
                transport = UnsupportedTransport()
                channel = GattChannel(transport)
                channel.active = True
                with self.assertRaises(NotImplementedError):
                    await channel.execute(GattOperation(kind, '1911'), lambda packet: None)
                self.assertFalse(channel.active)
                self.assertEqual(transport.closed, 1)
                self.assertEqual(len(transport.calls), 1)

    async def test_unsupported_portable_mtu_keeps_connection(self):
        transport = UnsupportedTransport()
        channel = GattChannel(transport)
        channel.active = True
        with self.assertRaises(NotImplementedError):
            await channel.execute(GattOperation(OperationKind.MTU))
        self.assertTrue(channel.active)
        self.assertEqual(transport.closed, 0)

    async def test_local_write_hook_error_keeps_connection_without_io(self):
        transport = UnsupportedTransport()
        channel = GattChannel(transport)
        channel.active = True

        def fail_before_write():
            raise NotImplementedError('local preparation failed')

        with self.assertRaises(NotImplementedError):
            await channel.execute(GattOperation(OperationKind.WRITE, '1912'),
                                  before_write=fail_before_write)
        self.assertTrue(channel.active)
        self.assertEqual(transport.closed, 0)
        self.assertEqual(transport.calls, [])
