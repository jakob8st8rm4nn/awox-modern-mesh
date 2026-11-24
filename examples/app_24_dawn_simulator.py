"""Read dawn settings, build a daily 06:30-07:00 white-light window, read back.

WARNING: This replaces both persistent records with an enabled daily schedule.
It requests white at 80% brightness, with a 30-minute fade field on the start
record and the same final light target at 07:00. The initial read must contain
both records. New fields replace old settings. The second write requires 0x99;
partial changes can remain stored. This does not wait 30 minutes, verify a
physical sunrise animation or restore the previous configuration.
"""

import asyncio
from awox import (AwoXMeshSession, ESPHomeProxy, Credentials, ScheduleWritePart,
                  routine_white_settings)

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # AwoX mesh name
MESH_PASSWORD = ""          # AwoX mesh password
LAMP_MAC = ""               # Target lamp Bluetooth MAC address
MESH_ID = 0                 # Target lamp mesh ID (for example 0x1234)
GATEWAY_MAC = LAMP_MAC      # BLE gateway in the same mesh; may differ from target


async def main():
    if not PROXY_HOST or not MESH_NAME or not LAMP_MAC or not MESH_ID:
        raise ValueError("Set PROXY_HOST, MESH_NAME, LAMP_MAC and MESH_ID in this example.")
    credentials = Credentials(MESH_NAME, MESH_PASSWORD)
    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        async with AwoXMeshSession(
            lambda: proxy.create_transport(GATEWAY_MAC),
            credentials,
            {MESH_ID: LAMP_MAC},
        ) as mesh:
            lamp = mesh.lamp(MESH_ID)
            current = await lamp.read_dawn_simulator(timeout=15)
            print("Current dawn simulator:", current)
            if current is None or not current.complete or current.end is None:
                print("No complete dawn response; nothing was written.")
                return
            print("Stored dawn start light settings:", current.start.light_settings)
            print("Stored dawn end light settings:", current.end.light_settings)

            await asyncio.sleep(2)

            # One daily dawn window with a fixed white target, not a
            # sequence of immediate brightness/color commands.
            light = routine_white_settings(80, 75, power_on=True)
            start = ScheduleWritePart.clock(
                7, 6, 30, light, enabled=True, weekdays_mask=0x7F,
                repeat=True, fade_minutes=30,
            )
            end = ScheduleWritePart.clock(
                8, 7, 0, light, enabled=True, weekdays_mask=0x7F, repeat=True,
            )
            # To disable, use enabled=False on BOTH records.
            # The Library handles the two-record protocol exchange.
            response = await lamp.set_dawn_simulator(start, end, timeout=15)
            print("Set dawn simulator response:", response)
            # Readback is not a test of the actual sunrise animation.
            readback = await lamp.read_dawn_simulator(timeout=15)
            print("Dawn simulator after writing:", readback)
            if readback is not None and readback.complete and readback.end is not None:
                print("Stored dawn simulator start light settings:", readback.start.light_settings)
                print("Stored dawn simulator end light settings:", readback.end.light_settings)


if __name__ == "__main__":
    asyncio.run(main())
