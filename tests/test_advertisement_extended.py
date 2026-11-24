"""Advertisement decode and ESPHome event paths; isolated offline tests."""
import math
import asyncio
import sys
import types
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from awox.advertisements import AdvertisementRecord
from awox.esphome_proxy import ESPHomeProxy

RAW_1 = bytes.fromhex(
    '60 01 96 20 19 22 11 38 03 00 02 61 D3 00 FF 4D 01 FF FF 04 3E 60 00 00 00 00 00 00 00'
)
RAW_2 = bytes.fromhex(
    '60 01 96 20 B8 44 33 38 03 00 02 DD 9C 02 FF FF FF 11 FE 04 3E 60 00 00 00 00 00 00 00'
)


def ad_field(ad_type, payload):
    return bytes((len(payload) + 1, ad_type)) + payload


def info(address='02:00:38:11:22:19', raw=None, manufacturer=RAW_1,
         time=123.4):
    return SimpleNamespace(
        address=address, rssi=-66, device=object(), name='TestBLE1',
        manufacturer_data={0x0160: manufacturer[2:], 0x004c: b'hello'},
        service_data={'0000feaa-0000-1000-8000-00805f9b34fb': b'\x00\x01'},
        service_uuids=['0000180f-0000-1000-8000-00805f9b34fb'],
        raw=raw, time=time, source='esphome', connectable=True,
    )


class AdvertisementDecoderTests(unittest.TestCase):
    def test_apk_confirmed_light_and_hardware_fields_for_both_real_devices(self):
        first = AdvertisementRecord.from_manufacturer_data(0x0160, RAW_1[2:])
        second = AdvertisementRecord.from_manufacturer_data(0x0160, RAW_2[2:])
        self.assertEqual((first.model_lookup_code, first.firmware), (b'\x20\x96', '3.0.2'))
        self.assertEqual(first.mesh_address, -11423)
        self.assertEqual(first.mesh_address_unsigned, 0xD361)
        self.assertEqual(second.mesh_address_unsigned, 0x9CDD)
        self.assertEqual((first.hardware_version, second.hardware_version), ('4.62', '4.62'))
        self.assertEqual((first.provisioning_byte, second.provisioning_byte), (0x60, 0x60))
        self.assertFalse(first.light_state.is_on)
        self.assertFalse(first.light_state.color_mode)
        self.assertEqual(first.light_state.white_temperature_mired, 333)
        self.assertIsNone(first.light_state.hue_raw)
        self.assertFalse(second.light_state.is_on)
        self.assertTrue(second.light_state.color_mode)
        self.assertEqual(second.light_state.hue_raw, 17)
        self.assertEqual(second.light_state.saturation_raw, 254)
        self.assertAlmostEqual(second.light_state.hue_degrees, 17 * 360 / 254)
        self.assertEqual(second.light_state.saturation_percent, 100)
        self.assertIsNone(second.light_state.white_temperature_mired)
        self.assertEqual(second.light_state.brightness_raw, 255)
        self.assertEqual(second.light_state.brightness_percent, 100)

    def test_light_flags_and_mode_applicability(self):
        raw = bytearray(RAW_2)
        raw[13] = 0x17  # on + color + cycle + candle
        raw[14] = 2
        record = AdvertisementRecord.from_manufacturer_data(0x0160, raw[2:])
        state = record.light_state
        self.assertTrue(all((state.is_on, state.color_mode, state.color_cycle, state.candle_mode)))
        self.assertEqual(state.brightness_percent, 0)
        raw[13] = 0x01  # on + white mode
        raw[15:17] = b'\xff\xff'
        record = AdvertisementRecord.from_manufacturer_data(0x0160, raw[2:])
        self.assertIsNone(record.light_state.white_temperature_mired)
        self.assertIsNone(record.light_state.hue_degrees)

    def test_short_wrong_vendor_and_old_firmware_not_misdecoded(self):
        short = AdvertisementRecord.from_manufacturer_data(0x0160, RAW_1[2:20])
        self.assertIsNone(short.light_state)
        self.assertIsNone(short.hardware_version)
        old = bytearray(RAW_1)
        old[8:11] = b'\x02\x00\x1a'  # 2.0.26
        old_record = AdvertisementRecord.from_manufacturer_data(0x0160, old[2:])
        # Below 2.0.27 the APK selects n7.i + n7.l: a percent byte,
        # not the newer two-byte mired field. These are synthetic old bytes.
        self.assertIsNone(old_record.light_state.white_temperature_mired)
        self.assertEqual(old_record.light_state.temperature_percent_raw, 0x4D)
        self.assertEqual(old_record.hardware_version, '255.4')
        newer = bytearray(old)
        newer[10] = 27
        self.assertIsNotNone(AdvertisementRecord.from_manufacturer_data(0x0160, newer[2:]).light_state)
        foreign = AdvertisementRecord.from_manufacturer_data(0x004C, RAW_1[2:])
        self.assertIsNone(foreign.light_state)

    def test_lossless_raw_and_structured_metadata_from_proxy(self):
        packet = ad_field(0xff, RAW_1) + ad_field(9, b'Real') + ad_field(0x01, b'\x06')
        record = AdvertisementRecord.from_service_info(info(raw=packet, time=12.5))
        self.assertEqual(record.raw_advertisement, packet)
        self.assertEqual(record.raw_fields[9], b'Real')
        self.assertEqual(record.raw_fields[0x01], b'\x06')
        self.assertEqual(record.fields[0xff], RAW_1)
        self.assertEqual(record.manufacturer_data[0x0160], RAW_1[2:])
        self.assertEqual(record.manufacturer_data[0x004c], b'hello')
        self.assertEqual(record.service_data['0000feaa-0000-1000-8000-00805f9b34fb'], b'\x00\x01')
        self.assertEqual(record.service_uuids, ('0000180f-0000-1000-8000-00805f9b34fb',))
        self.assertEqual(record.source, 'esphome')
        self.assertTrue(record.connectable)
        self.assertEqual(record.received_monotonic, 12.5)
        self.assertEqual(record.local_name, 'TestBLE1')  # merged cache value, not raw AD09
        for mapping in (record.fields, record.raw_fields, record.manufacturer_data, record.service_data):
            with self.assertRaises(TypeError):
                mapping['x'] = b'y'

    def test_preserve_raw_with_no_manufacturer_from_proxy(self):
        packet = ad_field(0xff, RAW_2)
        # RAW_2 embeds B8 44 33 38, i.e. the BLE sender ends 38:33:44:B8.
        observation = info(address='02:00:38:33:44:B8', raw=packet, manufacturer=RAW_2)
        observation.manufacturer_data = {}
        result = AdvertisementRecord.from_service_info(observation)
        self.assertIsNotNone(result)
        self.assertEqual(result.mesh_address_unsigned, 0x9CDD)
        self.assertEqual(result.raw_advertisement, packet)
        unrelated = info(manufacturer=RAW_1)
        unrelated.manufacturer_data = {0x004c: b'a'}
        unrelated.raw = b'\x00'
        self.assertIsNone(AdvertisementRecord.from_service_info(unrelated))


class EventManager:
    """Minimal stand-in for the base habluetooth manager, NOT HA's wrapper."""
    def __init__(self):
        self.address_callbacks = {}
        self.stopped = []
        self.cached = []

    def async_register_advertisement_callback(self, callback, address):
        self.address_callbacks[address] = callback
        def unsubscribe():
            self.stopped.append(address)
            self.address_callbacks.pop(address, None)
        return unsubscribe

    def async_discovered_service_info(self, connectable):
        self.connectable = connectable
        return list(self.cached)

    def fire_repeat(self, adv):
        self.address_callbacks[adv.address.upper()](adv)


class AdvertisementEventTests(unittest.TestCase):
    def new_proxy(self):
        proxy = ESPHomeProxy('esp.example')
        proxy._bluetooth = EventManager()
        return proxy

    def test_events_cache_repeats_unsubscribe_and_cleanup(self):
        proxy = self.new_proxy()
        received = []
        cancel = proxy.on_advertisement(received.append)
        proxy._start_advertisement_callbacks()
        # The plain habluetooth BluetoothManager does not provide
        # Home Assistant's async_register_callback. The standalone manager
        # uses _discover_service_info instead (tested end-to-end below).
        self.assertFalse(hasattr(proxy._bluetooth, 'async_register_callback'))
        a = info()
        proxy._handle_changed_advertisement(a)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].address, a.address)
        self.assertEqual(proxy.get_advertisement(a.address.lower()).received_monotonic, 123.4)
        self.assertEqual(tuple(proxy.advertisements), (a.address,))
        self.assertEqual(proxy._bluetooth.connectable, False)
        proxy._bluetooth.fire_repeat(a)
        proxy._bluetooth.fire_repeat(a)
        self.assertEqual(len(received), 3)  # identical advertisements are events
        # Discovery hook does not duplicate a per-address callback.
        proxy._handle_changed_advertisement(a)
        self.assertEqual(len(received), 3)
        with self.assertRaises(TypeError):
            proxy.advertisements['foo'] = received[0].advertisement
        cancel()
        proxy._bluetooth.fire_repeat(a)
        self.assertEqual(len(received), 3)
        proxy._stop_advertisement_callbacks()
        self.assertEqual(set(proxy._bluetooth.stopped), {a.address})

    def test_seed_cache_without_synthetic_callback_then_per_address_update(self):
        proxy = self.new_proxy()
        first = info(time=10.0)
        proxy._bluetooth.cached = [first]
        received = []
        proxy.on_advertisement(received.append)
        proxy._start_advertisement_callbacks()
        self.assertEqual(received, [])
        self.assertEqual(proxy.get_advertisement(first.address).received_monotonic, 10.0)
        newer = info(time=11.0)
        proxy._bluetooth.fire_repeat(newer)
        self.assertEqual(len(received), 1)
        self.assertEqual(proxy.get_advertisement(first.address).received_monotonic, 11.0)
        proxy._save_observation(proxy._from_service_info(info(time=3.0)))
        self.assertEqual(proxy.get_advertisement(first.address).received_monotonic, 11.0)
        proxy._stop_advertisement_callbacks()

    def test_plain_bluetooth_manager_discovery_hook_in_full_proxy_context(self):
        """Regression: a callback must fire without HA async_register_callback."""
        registered = {'manager': None}
        fake_habluetooth = types.ModuleType('habluetooth')
        fake_bleak_esphome = types.ModuleType('bleak_esphome')
        fake_backend = types.ModuleType('bleak_esphome.backend')
        fake_backend_client = types.ModuleType('bleak_esphome.backend.client')

        class FakeBluetoothManager(EventManager):
            def __init__(self):
                super().__init__()
                self._subclass_discover_info = self._discover_service_info
                self.stopped_manager = False
                self.known = {}

            async def async_setup(self):
                pass

            def async_stop(self):
                self.stopped_manager = True

            def feed(self, advertisement):
                callbacks = self.address_callbacks.get(advertisement.address.upper())
                if callbacks is not None:
                    callbacks(advertisement)
                previous = self.known.get(advertisement.address)
                if previous is None or previous.manufacturer_data != advertisement.manufacturer_data:
                    self.known[advertisement.address] = advertisement
                    self._subclass_discover_info(advertisement)

        class FakeAPIConnectionManager:
            def __init__(self, config):
                self.config = config
            async def start(self):
                pass
            async def stop(self):
                pass

        class FakeESPHomeClient:
            pass

        class FakeHaBleakClientWrapper:
            pass

        def get_manager():
            if registered['manager'] is None:
                raise RuntimeError('No manager')
            return registered['manager']

        def set_manager(manager):
            registered['manager'] = manager

        fake_habluetooth.BluetoothManager = FakeBluetoothManager
        fake_habluetooth.HaBleakClientWrapper = FakeHaBleakClientWrapper
        fake_habluetooth.get_manager = get_manager
        fake_habluetooth.set_manager = set_manager
        fake_bleak_esphome.APIConnectionManager = FakeAPIConnectionManager
        fake_backend_client.ESPHomeClient = FakeESPHomeClient

        async def exercise():
            received = []
            proxy = ESPHomeProxy('esp.example', on_advertisement=received.append)
            async with proxy:
                manager = registered['manager']
                self.assertFalse(hasattr(manager, 'async_register_callback'))
                advertisement = info(time=2.0)
                manager.feed(advertisement)       # New device: discovery hook
                manager.feed(advertisement)       # Unchanged: per-address callback
                self.assertEqual(len(received), 2)
                self.assertEqual(len(proxy.advertisements), 1)
                self.assertEqual(proxy.get_advertisement(advertisement.address).received_monotonic, 2.0)
                self.assertEqual(len(manager.address_callbacks), 1)
            self.assertEqual(registered['manager'], None)
            self.assertTrue(manager.stopped_manager)
            self.assertEqual(manager.address_callbacks, {})

        with patch.dict(sys.modules, {
            'habluetooth': fake_habluetooth,
            'bleak_esphome': fake_bleak_esphome,
            'bleak_esphome.backend': fake_backend,
            'bleak_esphome.backend.client': fake_backend_client,
        }):
            asyncio.run(exercise())

    def test_callback_exceptions_do_not_stop_other_subscribers(self):
        proxy = self.new_proxy()
        events = []
        def fail(_):
            raise ValueError('my application error')
        proxy.on_advertisement(fail)
        proxy.on_advertisement(events.append)
        with self.assertLogs('awox.esphome_proxy', level='ERROR'):
            proxy._handle_advertisement_event(info())
        self.assertEqual(len(events), 1)

    def test_invalid_callback_and_empty_cache(self):
        proxy = ESPHomeProxy('proxy.example')
        self.assertIsNone(proxy.get_advertisement('aa'))
        self.assertFalse(proxy.advertisements)
        with self.assertRaises(TypeError):
            proxy.on_advertisement(42)
        with self.assertRaises(TypeError):
            ESPHomeProxy('proxy.example', on_advertisement=42)


if __name__ == '__main__':
    unittest.main()
