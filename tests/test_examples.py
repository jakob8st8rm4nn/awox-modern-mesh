"""Run every example with the real new session and a simulated GATT peer."""
import asyncio
import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
from datetime import timedelta
import unittest
from unittest.mock import patch
from email.message import Message
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl

from awox import Credentials, registered_model_code
from awox.authentication import derive_session_key
from awox.frames import COMMAND_UUID, PAIR_UUID, open_frame
from awox.pir import PirSettings, SceneConfig
from test_session_operations import FakeTransport, ID, MAC


class ExampleTransport(FakeTransport):
    def __init__(self, credentials):
        super().__init__()
        self.credentials = credentials
        self.address = ID

    async def write(self, characteristic, data, response):
        self.writes.append((characteristic, bytes(data), response))
        if characteristic == PAIR_UUID:
            if data[0] == 0x0C:
                self.key = derive_session_key(self.credentials.name, self.credentials.password,
                                              data[1:9], self.pair_response)
            elif data[0] == 0x05:
                self.pair_response = b'\x07'
            return
        if characteristic != COMMAND_UUID:
            return
        frame = open_frame(self.key, data)
        raw = frame.data
        if frame.flag != 2:
            return
        opcode = raw[0]
        target = raw[1:3]
        if opcode == 0x0A:
            self.emit(0x80, target + bytes.fromhex('0100009620') + bytes.fromhex('33221138')
                      + bytes.fromhex('0101804d0150be60'))
        elif opcode == 0x08:
            self.emit(0x08, target + bytes.fromhex('000200800180'))
        elif opcode == 0x0C:
            self.emit(0x0C, target + b'\0')
        elif opcode == 0x43:
            self.emit(0x43, target + bytes.fromhex('000000000001'))
        elif opcode == 0x42:
            self.emit(0x42, target + b'\0')
        elif opcode == 0x35:
            routine = raw[3]
            self.emit(0x35, target + bytes((routine, 0x81, 0, 0, 0xFF, 0, 1, 20, 0x4D, 1, 0x11)))
        elif opcode == 0x33:
            routine = raw[3] & 0x7F
            self.emit(0x33, target + bytes((0x99 if routine in (5, 7) else 0, 0x33, routine)))
        elif opcode == 0x3C:
            self.emit(0x3C, target + bytes.fromhex('0181000000000000ff01144d01'))
        elif opcode == 0x3B:
            self.emit(0x3B, target + bytes((0, 0x3B, 1)))
        elif opcode == 0x12:
            settings = PirSettings(SceneConfig(0, 20), SceneConfig(0, 50), 5, 30, True, False, 2)
            self.emit(0x12, settings.encode())
        elif opcode == 0x13:
            self.emit(0x13, b'\x40')
        elif opcode == 0x29:
            self.emit(0x29, bytes(19))
        elif opcode == 0x04:
            self.emit(0x04, bytes(19))
            self.emit(0x0B, b'\x45\x23')
            self.emit(0x83, bytes(19))


class ExampleRuns(unittest.IsolatedAsyncioTestCase):
    async def test_example_20_rejects_invalid_wire_format_before_opening_proxy(self):
        file = Path(__file__).parents[1] / "examples" / "app_20_sync_time_with_timezone.py"
        spec = importlib.util.spec_from_file_location("example_20", file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with (
            patch.multiple(module, PROXY_HOST="offline", MESH_NAME="test-mesh",
                           GATEWAY_MAC=MAC, POSIX_TIMEZONE_RULE="invalid rule"),
            patch.object(module, "ESPHomeProxy") as proxy,
            self.assertRaises(ValueError),
        ):
            await module.main()
        proxy.assert_not_called()

    async def test_example_20_uses_time_and_offset_sampled_after_login(self):
        file = Path(__file__).parents[1] / "examples" / "app_20_sync_time_with_timezone.py"
        spec = importlib.util.spec_from_file_location("example_20", file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        initial_time = 1_700_000_000
        now, offset = initial_time, 3600
        sent = []

        def local_time():
            sample = SimpleNamespace(timestamp=lambda: now, utcoffset=lambda: timedelta(seconds=offset))
            return SimpleNamespace(astimezone=lambda: sample)

        class Proxy:
            def __init__(self, *_args):
                pass

            async def __aenter__(self):
                nonlocal now
                now += 10
                return self

            async def __aexit__(self, *_args):
                pass

        class Mesh(Proxy):
            async def __aenter__(self):
                nonlocal now, offset
                now += 5
                offset = 7200
                return self

            async def set_time_with_timezone(self, timestamp_ms, _rule, *, timeout):
                sent.append((0x29, timestamp_ms))

            async def set_time(self, timestamp_ms, utc_offset):
                sent.append((0x30, timestamp_ms, utc_offset))

        with (
            patch.multiple(module, PROXY_HOST="offline", MESH_NAME="test-mesh",
                           GATEWAY_MAC=MAC, POSIX_TIMEZONE_RULE="CET-1CEST,M3.5.0,M10.5.0/3",
                           ESPHomeProxy=Proxy, AwoXMeshSession=Mesh,
                           datetime=SimpleNamespace(now=local_time)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            await module.main()
        fresh_ms = (initial_time + 15) * 1000
        self.assertEqual(sent, [(0x29, fresh_ms), (0x30, fresh_ms, 7200)])

    def test_cloud_example_stops_at_redirect(self):
        path = Path(__file__).parents[1] / 'examples/app_01_cloud_account_read.py'
        spec = importlib.util.spec_from_file_location('cloud_example', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        seen_urls = []

        class OfflineHTTPS(HTTPSHandler):
            def https_open(self, request):
                seen_urls.append(request.full_url)
                headers = Message()
                headers['Location'] = 'https://redirect.invalid/parse/login'
                response = addinfourl(io.BytesIO(), headers, request.full_url, 302)
                response.msg = 'Found'
                return response

        url = 'https://cloud.invalid/parse/login'
        with patch.object(module, 'build_opener',
                          side_effect=lambda handler: build_opener(handler, OfflineHTTPS())):
            with self.assertRaisesRegex(RuntimeError, 'Cloud HTTP redirect refused'):
                module.request_json(url, 'offline-installation', {}, 'dummy-token')
        self.assertEqual(seen_urls, [url])

    async def test_all_29_examples_execute_offline(self):
        root = Path(__file__).parents[1] / 'examples'
        files = sorted(root.glob('app_*.py'))
        self.assertEqual(len(files), 29)
        original_sleep = asyncio.sleep
        async def quick_sleep(_delay):
            await original_sleep(0)

        for file in files:
            with self.subTest(example=file.name):
                spec = importlib.util.spec_from_file_location('example_under_test', file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                number = int(file.name[4:6])
                for name, value in {
                    'PROXY_HOST':'offline-proxy','PROXY_KEY':'','MESH_NAME':'test-mesh',
                    'MESH_PASSWORD':'test-password','LAMP_MAC':MAC,'REMOTE_MAC':MAC,
                    'DEVICE_MAC':MAC,'GATEWAY_MAC':MAC,'MESH_ID':ID,'QUIET_TARGET':ID,
                    'SECOND_LAMP_MAC':'A4:C1:38:44:55:66','SECOND_MESH_ID':0x2345,
                    'NETWORK_KEY_HEX':bytes(range(16)).hex(),'EMAIL':'offline@example.invalid',
                    'PASSWORD':'offline-only','OBSERVE_SECONDS':1,'PRINT_INTERVAL_SECONDS':1,
                }.items():
                    if hasattr(module, name): setattr(module, name, value)

                if number == 1:
                    def request(url, *args, **kwargs):
                        return {'sessionToken':'offline', 'objectId':'offline'} if url.endswith('login') else {'results':[]}
                    with patch.object(module, 'request_json', request), contextlib.redirect_stdout(io.StringIO()):
                        module.main()
                    continue
                current_creds = Credentials('test-mesh', 'test-password')
                model = registered_model_code('ERCU-3groups-Zm' if number == 26 else 'EGLO-ZM-RGB-TW')
                record = SimpleNamespace(firmware='1.0.0', mesh_address=ID, mesh_address_unsigned=ID,
                    model_lookup_code=model, local_name='factory-name', provisioning_byte=0,
                    model_code=model, raw=b'', light_state=None, hardware_version=None,
                    received_monotonic=None, raw_advertisement=b'', service_uuids=(), manufacturer=b'')
                if number in (26, 27):
                    from awox import factory_credentials
                    current_creds = factory_credentials(MAC, model, '1.0.0',
                                                        name='factory-name' if number == 26 else 'unpaired')
                transport = ExampleTransport(current_creds)
                class Proxy:
                    def __init__(self, *args, **kwargs):
                        self.devices = [SimpleNamespace(address=MAC, rssi=-50, advertisement=record)]
                        self.advertisements = {MAC:record}
                        if kwargs.get('on_advertisement'):
                            kwargs['on_advertisement'](self.devices[0])
                    async def __aenter__(self): return self
                    async def __aexit__(self, *args): pass
                    def on_advertisement(self, callback):
                        callback(self.devices[0])
                        return lambda: None
                    def get_advertisement(self, address): return self.advertisements.get(address)
                    async def scan_mesh_devices(self, **kwargs): return self.devices
                    async def create_transport(self, address): return transport
                with patch.object(module, 'ESPHomeProxy', Proxy) if hasattr(module,'ESPHomeProxy') else contextlib.nullcontext(), \
                     patch('asyncio.sleep', quick_sleep), patch('builtins.input', return_value=''), \
                     contextlib.redirect_stdout(io.StringIO()):
                    result = module.main()
                    if asyncio.iscoroutine(result):
                        await result
                if number in (26, 27):
                    queries = [open_frame(transport.key,d).data for c,d,_ in transport.writes if c == COMMAND_UUID]
                    self.assertEqual([q[0] for q in queries], [0x0C,0x03,0x04] if number==26 else [0x03,0x04])
                if number == 29:
                    queries = [open_frame(transport.key, d).data[0]
                               for c, d, _ in transport.writes if c == COMMAND_UUID]
                    # One read, one write with tracked reply, one readback.
                    self.assertEqual(queries, [0x08, 0x0C, 0x08])
                if number in (23,24):
                    queries=[open_frame(transport.key,d).data for c,d,_ in transport.writes if c == COMMAND_UUID]
                    self.assertEqual(sum(q[0]==0x33 for q in queries),2)


if __name__ == '__main__':
    unittest.main()
