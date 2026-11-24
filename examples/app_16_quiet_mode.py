"""Send one explicitly configured Quiet Mode command (0x40).

Choose QUIET_TARGET before running. Actions 1/2 follow the APK's group/HOME
contexts; the unit of parameter 30 and its physical effect remain unverified.
This example sends one write, without the App's ten-second renewal timer.
A received result cannot be linked to a particular request or target, so it
does not establish that the requested device changed state.
"""

import asyncio
from awox import AwoXMeshSession, ESPHomeProxy, Credentials

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # AwoX mesh name
MESH_PASSWORD = ""          # AwoX mesh password
GATEWAY_MAC = ""           # Bluetooth MAC of a device in this mesh

QUIET_TARGET = 0            # Set a real address (for example an existing group).
QUIET_ACTION = 1            # APK action 1 (non-HOME group) or 2 (HOME context).
QUIET_ENABLED = True        # Change to False to send a disable instead.
QUIET_PARAMETER = 30        # APK caller's raw byte value; unit is unknown.


async def main():
    if not PROXY_HOST or not MESH_NAME or not GATEWAY_MAC:
        raise ValueError("Set PROXY_HOST, MESH_NAME and GATEWAY_MAC in this example.")
    # Check the explicit target before opening a Bluetooth connection.
    if not 1 <= QUIET_TARGET <= 0xFFFF:
        raise ValueError("Set QUIET_TARGET to the intended nonzero address.")
    credentials = Credentials(MESH_NAME, MESH_PASSWORD)

    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        async with AwoXMeshSession(
            lambda: proxy.create_transport(GATEWAY_MAC),
            credentials,
        ) as mesh:
            # Send the selected action once.
            await mesh.set_quiet_mode(
                QUIET_TARGET,
                action=QUIET_ACTION,
                enabled=QUIET_ENABLED,
                parameter=QUIET_PARAMETER,
            )
            print(f"Quiet Mode 0x40 write sent to 0x{QUIET_TARGET:04X}.")
            await asyncio.sleep(2)
            print("Last uncorrelated 0x40 result:", mesh.last_quiet_result_code)
            print("No causally attributed acknowledgement or device state is known.")


if __name__ == "__main__":
    asyncio.run(main())
