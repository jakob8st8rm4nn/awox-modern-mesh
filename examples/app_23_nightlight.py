"""Read nightlight, build a daily 21:00-23:00 white-light window, read back.

WARNING: This replaces both persistent records with an enabled daily schedule:
white at 20% brightness from 21:00, OFF at 23:00. The initial read must contain
both records. New light fields and clock mode 1 replace the old settings.
The second write requires the protocol's 0x99 continuation; partial changes
can remain stored. This does not wait for the schedule or prove execution.
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
            current = await lamp.read_nightlight(timeout=15)
            print("Current nightlight:", current)
            if current is None or not current.complete or current.end is None:
                print("No complete nightlight response; nothing was written.")
                return
            print("Stored nightlight start light settings:", current.start.light_settings)
            print("Stored nightlight end light settings:", current.end.light_settings)

            await asyncio.sleep(2)

            # One daily window: dim white at 21:00, OFF at 23:00.
            on = routine_white_settings(20, 75, power_on=True)
            off = routine_white_settings(20, 75, power_on=False)
            start = ScheduleWritePart.clock(
                5, 21, 0, on, enabled=True, weekdays_mask=0x7F, repeat=True,
            )
            end = ScheduleWritePart.clock(
                6, 23, 0, off, enabled=True, weekdays_mask=0x7F, repeat=True,
            )
            # To disable, use enabled=False on BOTH records.
            # The Library handles the two-record protocol exchange.
            response = await lamp.set_nightlight(start, end, timeout=15)
            print("Set nightlight response:", response)
            # Read both records again to see what the lamp stored.
            readback = await lamp.read_nightlight(timeout=15)
            print("Nightlight after writing:", readback)
            if readback is not None and readback.complete and readback.end is not None:
                print("Stored nightlight start light settings:", readback.start.light_settings)
                print("Stored nightlight end light settings:", readback.end.light_settings)


if __name__ == "__main__":
    asyncio.run(main())
