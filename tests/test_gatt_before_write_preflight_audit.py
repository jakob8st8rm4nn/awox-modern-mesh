"""Regression tests: malformed pre-write hooks must not tear down BLE."""
import unittest

from awox.transport import GattChannel, GattOperation, OperationKind


class _RecordingTransport:
    def __init__(self):
        self.disconnect_calls = 0
        self.writes = []
        self.marker_state = None

    async def connect(self, disconnected):
        self.on_disconnect = disconnected

    async def disconnect(self):
        self.disconnect_calls += 1

    async def write(self, characteristic, data, response):
        self.writes.append((characteristic, data, response, self.marker_state))

    async def read(self, characteristic):
        return b'ack'


class BeforeWritePreflightTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = _RecordingTransport()
        self.channel = GattChannel(self.transport)
        await self.channel.connect(lambda status: None)

    async def test_non_callable_write_hook_does_not_close_healthy_connection(self):
        with self.assertRaisesRegex(TypeError, 'before_write callback'):
            await self.channel.execute(
                GattOperation(OperationKind.WRITE, '1912', b'command'),
                before_write=42,
            )
        self.assertTrue(self.channel.active)
        self.assertEqual(self.transport.disconnect_calls, 0)
        self.assertEqual(self.transport.writes, [])
        await self.channel.execute(GattOperation(OperationKind.WRITE, '1912', b'valid'))
        self.assertEqual(len(self.transport.writes), 1)

    async def test_non_callable_hook_is_rejected_before_read_or_transport_work(self):
        with self.assertRaisesRegex(TypeError, 'before_write callback'):
            await self.channel.execute(
                GattOperation(OperationKind.READ, '1912'), before_write=object(),
            )
        self.assertTrue(self.channel.active)
        self.assertEqual(self.transport.disconnect_calls, 0)

    async def test_valid_hook_still_runs_immediately_before_write(self):
        marker_calls = []

        def marker():
            self.transport.marker_state = 'armed'
            marker_calls.append('armed')

        await self.channel.execute(
            GattOperation(OperationKind.WRITE, '1912', b'command'),
            before_write=marker,
        )
        self.assertEqual(marker_calls, ['armed'])
        self.assertEqual(self.transport.writes, [('1912', b'command', True, 'armed')])


if __name__ == '__main__':
    unittest.main()
