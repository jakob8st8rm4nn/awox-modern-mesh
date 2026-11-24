"""Watch one brightness fade from 10% to 90% over three seconds.

The script switches the lamp on, sets 10% without a fade, then requests a
3000-ms transition to 90%. The following four seconds allow observation of
the requested fade. The script leaves the requested brightness at 90%.
Color and temperature commands also support the transition parameter.
"""

import asyncio
from awox import AwoXMeshSession, ESPHomeProxy, Credentials

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
            await lamp.set_power(True)  # Make the following change visible.
            print("Lamp ON command sent for observation.")

            # Establish a visible starting point without a fade.
            await lamp.set_brightness(10, transition=0)
            print("Starting brightness: 10% (no fade).")
            await asyncio.sleep(2)

            # transition is in milliseconds, in 100-ms steps; default is 200.
            await lamp.set_brightness(90, transition=3000)
            print("Requested fade: 10% -> 90% over three seconds.")
            await asyncio.sleep(4)  # Observe the fade; this is not an ACK.


if __name__ == "__main__":
    asyncio.run(main())
