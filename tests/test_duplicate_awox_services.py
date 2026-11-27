"""Keep actual service instances intact when recognizing the login service."""
from types import SimpleNamespace
import unittest
from awox.frames import SERVICE_UUID, PAIR_UUID, COMMAND_UUID, NOTIFY_UUID
from awox.authentication import Credentials
from awox.connection import MeshConnection as MeshSession
from awox.esphome_transport import _ESPHomeBleakTransportBase
from awox.transport import MissingCharacteristic

def service(*uuids):
    return SimpleNamespace(uuid=SERVICE_UUID.upper(), characteristics=[SimpleNamespace(uuid=uuid.upper()) for uuid in uuids])

class Client:

    def __init__(self, services):
        self.services = services
        self.is_connected = True
        self.calls = []

    async def write_gatt_char(self, characteristic, data, *, response):
        self.calls.append(('write', characteristic.uuid.lower()))

    async def read_gatt_char(self, characteristic):
        self.calls.append(('read', characteristic.uuid.lower()))
        return b'\r' + bytes(range(8))

    async def disconnect(self):
        self.is_connected = False

class Transport(_ESPHomeBleakTransportBase):

    def __init__(self, services):
        super().__init__(SimpleNamespace(address='11:22:33:44:55:66'))
        self.test_client = Client(services)

    async def connect(self, callback):
        self._client = self.test_client

class DuplicateServiceTests(unittest.IsolatedAsyncioTestCase):

    async def test_missing_or_separate_notify_stops_before_login(self):
        login = service(PAIR_UUID, COMMAND_UUID)
        notify = service(NOTIFY_UUID)
        for services in ([login], [login, notify], [notify, login]):
            with self.subTest(services=services):
                transport = Transport(services)
                mesh = MeshSession(transport, Credentials('mesh', 'pass'))
                with self.assertRaisesRegex(MissingCharacteristic, 'pair/command/notify'):
                    await mesh.connect()
                self.assertEqual(transport.test_client.calls, [])
                self.assertFalse(mesh.login_accepted)
                await mesh.disconnect()

    async def test_pair_and_command_in_separate_instances_cannot_login(self):
        pair, command = (service(PAIR_UUID), service(COMMAND_UUID))
        for services in ([pair, command], [command, pair]):
            with self.subTest(services=services):
                transport = Transport(services)
                mesh = MeshSession(transport, Credentials('mesh', 'pass'))
                with self.assertRaises(MissingCharacteristic):
                    await mesh.connect()
                self.assertEqual(transport.test_client.calls, [])
                self.assertFalse(mesh.login_accepted)
                await mesh.disconnect()


class ServiceSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_complete_instance_is_selected_in_both_orders(self):
        complete = service(PAIR_UUID, COMMAND_UUID, NOTIFY_UUID)
        other = service('00000000-0000-0000-0000-000000000001')
        for services in ([complete, other], [other, complete], [complete]):
            with self.subTest(order=services):
                transport = Transport(services)
                await transport.connect(lambda status: None)
                found = await transport.discover_services()
                self.assertEqual(found[SERVICE_UUID], {PAIR_UUID, COMMAND_UUID, NOTIFY_UUID})
                self.assertIs(transport._resolve(COMMAND_UUID), complete.characteristics[1])
                await transport.disconnect()

    async def test_incomplete_instance_does_not_hide_complete_instance(self):
        complete = service(PAIR_UUID, COMMAND_UUID, NOTIFY_UUID)
        incomplete = service(PAIR_UUID, COMMAND_UUID)
        for services in ([complete, incomplete], [incomplete, complete]):
            with self.subTest(order=services):
                transport = Transport(services)
                await transport.connect(lambda status: None)
                found = await transport.discover_services()
                self.assertEqual(found[SERVICE_UUID], {PAIR_UUID, COMMAND_UUID, NOTIFY_UUID})
                with self.assertRaises(MissingCharacteristic):
                    transport._resolve(PAIR_UUID)
                await transport.disconnect()
