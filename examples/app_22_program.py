"""Read a program record, build a weekday blue-light entry, then read back.

WARNING: This replaces persistent routine-3 settings with an enabled 18:30
Monday-Friday entry: blue at 50% brightness. It builds clock mode 1 explicitly;
the old light settings and raw flags are not retained. A complete initial read
is one record, not an inventory of every program slot. The example does not
wait for 18:30, prove execution or restore the previous configuration.
"""

import asyncio
from awox import (AwoXMeshSession, ESPHomeProxy, Credentials, ScheduleWritePart,
                  routine_color_settings)

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
            current = await lamp.read_program(timeout=15)
            print("Current program:", current)
            if current is None or not current.complete:
                print("No valid program response; nothing was written.")
                return
            print("Stored program light settings:", current.start.light_settings)

            await asyncio.sleep(2)

            # One scheduled state: blue at 50%, weekdays at 18:30.
            # Sunday=bit0, Monday=bit1, ... Saturday=bit6.
            light = routine_color_settings(50, 0, 0, 255, power_on=True)
            settings = ScheduleWritePart.clock(
                3, 18, 30, light, enabled=True,
                weekdays_mask=0b0111110, repeat=True,
            )
            # Use enabled=False instead to store a disabled program.
            response = await lamp.set_program(settings, timeout=15)
            print("Set program response:", response)
            # Inspect the returned values; this script does not compare them or test execution.
            readback = await lamp.read_program(timeout=15)
            print("Program after writing:", readback)
            print("Stored program light settings:",
                  readback.start.light_settings if readback is not None and readback.complete else None)


if __name__ == "__main__":
    asyncio.run(main())
