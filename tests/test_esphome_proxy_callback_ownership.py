"""Advertisement subscription ownership and snapshot consistency; offline."""
import unittest
from awox.esphome_proxy import ESPHomeProxy
from test_advertisement_extended import info

class ProxyCallbackOwnershipTests(unittest.TestCase):

    def test_unsubscribe_twice_does_not_remove_another_registration(self):
        proxy = ESPHomeProxy('offline.example')
        events = []
        first = proxy.on_advertisement(events.append)
        second = proxy.on_advertisement(events.append)
        first()
        first()
        proxy._handle_advertisement_event(info(time=1.0))
        self.assertEqual(len(events), 1)
        second()
        proxy._handle_advertisement_event(info(time=2.0))
        self.assertEqual(len(events), 1)

    def test_old_unsubscribe_cannot_remove_a_later_registration(self):
        proxy = ESPHomeProxy('offline.example')
        events = []
        callback = events.append
        old_unsubscribe = proxy.on_advertisement(callback)
        old_unsubscribe()
        new_unsubscribe = proxy.on_advertisement(callback)
        old_unsubscribe()
        proxy._handle_advertisement_event(info(time=1.0))
        self.assertEqual(len(events), 1)
        new_unsubscribe()

    def test_equal_callable_objects_keep_separate_registration_ownership(self):
        proxy = ESPHomeProxy('offline.example')
        events = []

        class Callback:

            def __init__(self, name):
                self.name = name

            def __eq__(self, other):
                return isinstance(other, Callback)

            def __call__(self, observation):
                events.append(self.name)
        a, b = (Callback('a'), Callback('b'))
        remove_a = proxy.on_advertisement(a)
        remove_b = proxy.on_advertisement(b)
        remove_b()
        proxy._handle_advertisement_event(info(time=1.0))
        self.assertEqual(events, ['a'])
        remove_a()

    def test_snapshots_callbacks_and_latest_lookup_share_one_accepted_record(self):
        proxy = ESPHomeProxy('offline.example')
        events = []
        proxy.on_advertisement(events.append)
        first_info = info(time=10.0)
        proxy._handle_advertisement_event(first_info)
        snapshot = proxy.advertisements
        first = snapshot[first_info.address.upper()]
        self.assertIs(first, events[0].advertisement)
        proxy._handle_advertisement_event(info(time=20.0))
        latest = proxy.get_advertisement(first_info.address.lower())
        self.assertIs(latest, events[-1].advertisement)
        self.assertIs(latest, proxy.advertisements[first_info.address.upper()])
        self.assertEqual(snapshot[first_info.address.upper()].received_monotonic, 10.0)
        with self.assertRaises(TypeError):
            snapshot['x'] = latest
        proxy._handle_advertisement_event(info(time=15.0))
        self.assertEqual(len(events), 2)
        self.assertIs(proxy.get_advertisement(first_info.address), latest)
