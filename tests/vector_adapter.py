"""Test-only adapter for stored protocol vectors; not packaged in awox."""
from awox.frames import *
from awox.frames import _frame_bytes
from awox.authentication import network_update_packets
from awox.lighting import *
from awox.lighting import _candle_payload, _color_cycle_payload, _scene_payload
from awox.groups import *
from awox.power_cut import *
from awox.pir import *
from awox.presence import presence_get, presence_set
from awox.schedule import schedule_get, schedule_set
from awox.provisioning import remove_from_mesh

class ExtendedCommandBuilder:
    def __init__(self, destination):
        if type(destination) is not int or not 0 <= destination <= 65535:
            raise ValueError('destination must fit 16 bits')
        self.destination = destination

    def status_query(self):
        return addressed_query(self.destination, 0x0A)

    def get_mesh_groups(self, *args, **kwargs):
        return get_mesh_groups(self.destination, *args, **kwargs)

    def set_mesh_groups(self, *args, **kwargs):
        return set_mesh_groups(self.destination, *args, **kwargs)

    def power_cut_get_mode(self, *args, **kwargs):
        return power_cut_get_mode(self.destination, *args, **kwargs)

    def power_cut_set_mode(self, *args, **kwargs):
        return power_cut_set_mode(self.destination, *args, **kwargs)

    def pir_settings_get(self, *args, **kwargs):
        return pir_settings_get(self.destination, *args, **kwargs)

    def pir_luminosity_get(self, *args, **kwargs):
        return pir_luminosity_get(self.destination, *args, **kwargs)

    def quiet_mode(self, *args, **kwargs):
        return quiet_mode(self.destination, *args, **kwargs)

    def dual_zone_power(self, *args, **kwargs):
        return dual_zone_power(self.destination, *args, **kwargs)

    def dual_zone_brightness(self, *args, **kwargs):
        return dual_zone_brightness(self.destination, *args, **kwargs)

    def dual_zone_color(self, *args, **kwargs):
        return dual_zone_color(self.destination, *args, **kwargs)

    def dual_zone_temperature(self, *args, **kwargs):
        return dual_zone_temperature(self.destination, *args, **kwargs)

    def native_scene(self, *args, **kwargs):
        return native_scene(self.destination, *args, **kwargs)

    def set(self, *args, **kwargs):
        return set(self.destination, *args, **kwargs)

    def color_hsv(self, *args, **kwargs):
        return color_hsv(self.destination, *args, **kwargs)

    def presence_get(self, *args, **kwargs):
        return presence_get(self.destination, *args, **kwargs)

    def presence_set(self, *args, **kwargs):
        return presence_set(self.destination, *args, **kwargs)

    def schedule_get(self, *args, **kwargs):
        return schedule_get(self.destination, *args, **kwargs)

    def schedule_set(self, *args, **kwargs):
        return schedule_set(self.destination, *args, **kwargs)

    def remove_from_mesh(self, *args, **kwargs):
        return remove_from_mesh(self.destination, *args, **kwargs)

    pir_settings_set = staticmethod(pir_settings_set)

from awox.session import decode_apk_notification as decode_notification
