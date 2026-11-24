"""Read presence settings, build one weekday half-hour window, read back.

WARNING: This replaces the persistent presence record with an enabled repeating
Monday-Friday 09:00-09:30 selection and fixed white light at 50% brightness.
All other slots start clear; random mode is explicitly off. It builds new
settings, not an edit that retains previous slots or unknown flags.
Readback does not prove physical execution; no automatic restore is performed.
"""

import asyncio
from awox import (AwoXMeshSession, ESPHomeProxy, Credentials, PresenceWritePart,
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
            current = await lamp.read_presence_simulator(timeout=15)
            print("Current presence simulation:", current)
            if current is None or not current.valid:
                print("No valid presence response; nothing was written.")
                return
            print("Stored presence light settings:", current.light_settings)

            await asyncio.sleep(2)

            # One selected slot: weekdays, 09:00-09:30, fixed white.
            # Change random_enabled to True for the alternative random mode;
            # it is still the same single configuration write.
            light = routine_white_settings(50, 50, power_on=True)
            settings = PresenceWritePart.create(
                light, enabled=True, weekdays_mask=0b0111110,
                repeat=True, random_enabled=False,
            ).with_half_hour_slot(18, True)
            # Use enabled=False instead to store a disabled simulation.
            response = await lamp.set_presence_simulator(settings, timeout=15)
            print("Set presence simulation response:", response)
            # Readback shows stored values, not proof of simulator execution.
            readback = await lamp.read_presence_simulator(timeout=15)
            print("Presence after writing:", readback)
            print("Stored presence light settings:",
                  readback.light_settings if readback is not None and readback.valid else None)


if __name__ == "__main__":
    asyncio.run(main())
