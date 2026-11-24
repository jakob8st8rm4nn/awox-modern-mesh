import asyncio
from awox.frames import SERVICE_UUID, PAIR_UUID, COMMAND_UUID, NOTIFY_UUID
ANSWER=b"\x0d"+bytes(range(8))+bytes(7)
class FakeTransport:

    def __init__(self, response=ANSWER, services=None):
        self.response = response
        self.services = services if services is not None else {SERVICE_UUID: frozenset((PAIR_UUID, COMMAND_UUID, NOTIFY_UUID))}
        self.calls = []
        self.callback = None
        self.connected = False
        self.raise_on_query = None
        self.query_started = asyncio.Event()
        self.query_release = None
        self.read_started = asyncio.Event()
        self.read_release = None

    async def connect(self, callback):
        self.calls.append(('connect',))
        self.callback = callback
        self.connected = True

    async def discover_services(self):
        self.calls.append(('discover',))
        return self.services

    async def disconnect(self):
        self.calls.append(('disconnect',))
        self.connected = False
        if self.callback:
            self.callback(0)

    async def write(self, characteristic, data, response=True):
        self.calls.append(('write', characteristic, bytes(data), response))
        if characteristic == COMMAND_UUID:
            self.query_started.set()
            if self.query_release is not None:
                await self.query_release.wait()
            if self.raise_on_query:
                raise self.raise_on_query

    async def read(self, characteristic):
        self.calls.append(('read', characteristic))
        self.read_started.set()
        if self.read_release is not None:
            await self.read_release.wait()
        return self.response

    async def start_notify(self, characteristic, callback):
        self.calls.append(('notify', characteristic))
        raise AssertionError('modern profile must not attempt CCCD notification write')

    async def stop_notify(self, characteristic):
        self.calls.append(('stop_notify', characteristic))

    async def request_mtu(self, mtu):
        self.calls.append(('mtu', mtu))
