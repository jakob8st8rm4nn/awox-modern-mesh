"""Single explicit time writes on the new session; no retries or ACK gate."""
import unittest
from awox import AwoXMeshSession, Credentials
from awox.frames import open_frame, COMMAND_UUID
from test_session_operations import FakeTransport, CREDS

class ExplicitTimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_time_write(self):
        transport = FakeTransport()
        async with AwoXMeshSession(lambda: transport, CREDS) as mesh:
            transport.writes.clear()
            await mesh.set_time(1793793600123,3600)
            writes=[d for c,d,_ in transport.writes if c==COMMAND_UUID]
            self.assertEqual(len(writes),1)
            self.assertEqual(open_frame(transport.key,writes[0]).data[0],48)
