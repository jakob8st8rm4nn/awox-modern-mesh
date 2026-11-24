"""Read timer routine 2, build an enabled 20-minute OFF timer, read back.

WARNING: This replaces persistent timer settings and may start a countdown.
The requested action is OFF; its four stored light bytes are supplied explicitly.
Writes only after a valid initial read, but builds a new record rather than
preserving the old one. Readback does not prove that the timer will execute.
The example does not wait 20 minutes or restore the previous configuration.
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
            current = await lamp.read_timer(timeout=15)
            print("Current timer:", current)
            if current is None or not current.complete:
                print("No valid timer response; nothing was written.")
                return
            print("Stored timer light settings:", current.start.light_settings)

            await asyncio.sleep(2)

            # One timer action: switch OFF after the requested 20 minutes.
            # White fields complete the payload; power_on=False requests OFF.
            light = routine_white_settings(50, 50, power_on=False)
            settings = ScheduleWritePart.timer(20, light, enabled=True)
            # Use enabled=False instead to store a disabled timer.
            response = await lamp.set_timer(settings, timeout=15)
            print("Set timer response:", response)
            # Readback checks stored fields, not whether the timer fired.
            readback = await lamp.read_timer(timeout=15)
            print("Timer after writing:", readback)
            print("Stored timer light settings:",
                  readback.start.light_settings if readback is not None and readback.complete else None)


if __name__ == "__main__":
    asyncio.run(main())
