"""Send one explicit removal command to a device, then disconnect.

WARNING: This can remove persistent mesh access and change credentials/ID.
Save required groups/settings first. The device is NOT automatically enrolled
again. No App/cloud record is deleted and no complete factory reset is promised.
GATT completion alone does not prove removal. Never automatically resend it.
"""

import asyncio
from awox import AwoXMeshSession, Credentials, ESPHomeProxy
from awox.transport import ConnectionLost

# Edit your local copy; running it deliberately requests removal of this device.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # Mesh name for current authentication
MESH_PASSWORD = ""          # Mesh password for current authentication
DEVICE_MAC = ""             # Direct Bluetooth connection to the device being removed
MESH_ID = 0                 # Its verified current individual ID


async def main():
    if not PROXY_HOST or not MESH_NAME or not DEVICE_MAC or not MESH_ID:
        raise ValueError("Set PROXY_HOST, MESH_NAME, DEVICE_MAC and MESH_ID.")
    if (type(MESH_ID) is not int or not 1 <= MESH_ID < 0xFFFF
            or 0x8000 <= MESH_ID <= 0x80FF):
        raise ValueError("MESH_ID must be a verified individual address, not zero or a reserved ID.")
    credentials = Credentials(MESH_NAME, MESH_PASSWORD)
    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        async with AwoXMeshSession(lambda: proxy.create_transport(DEVICE_MAC),
                                  credentials, {MESH_ID: DEVICE_MAC}) as mesh:
            try:
                await mesh.remove_from_mesh(MESH_ID)  # Exactly one query01.
            except ConnectionLost:
                print("Connection lost during removal; outcome unknown. Do not automatically retry.")
                return
            print("Removal write completed. Actual removal must be verified separately.")
            # Do not keep using the old registration. After removal the device
            # can require factory credentials and report a different address.


if __name__ == '__main__':
    asyncio.run(main())
