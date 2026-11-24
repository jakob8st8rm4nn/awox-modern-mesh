"""Read two lamps through one BLE gateway, one after the other.

Fill in both mesh-ID/MAC pairs for distinct lamps in the same mesh. Both reads
use the same connection through GATEWAY_MAC; each can time out independently.
An active session does not establish that both lamps are reachable. No light
or persistent settings are changed.
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
SECOND_LAMP_MAC = ""        # Second lamp MAC address
SECOND_MESH_ID = 0          # Second lamp mesh address (e.g. 0x5678)


async def main():
    if not PROXY_HOST or not MESH_NAME or not LAMP_MAC or not MESH_ID or not SECOND_LAMP_MAC or not SECOND_MESH_ID:
        raise ValueError("Set PROXY_HOST, MESH_NAME, LAMP_MAC, MESH_ID, SECOND_LAMP_MAC and SECOND_MESH_ID in this example.")
    if MESH_ID == SECOND_MESH_ID:
        raise ValueError("The two lamps must have different mesh IDs.")
    credentials = Credentials(MESH_NAME, MESH_PASSWORD)
    # Both mesh IDs use the same Bluetooth link through GATEWAY_MAC.
    devices: dict[int, str] = {MESH_ID: LAMP_MAC, SECOND_MESH_ID: SECOND_LAMP_MAC}
    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        async with AwoXMeshSession(
            lambda: proxy.create_transport(GATEWAY_MAC),
            credentials,
            devices=devices,
        ) as mesh:
            print("Mesh connected:", mesh.connected)
            for mesh_id in devices:
                # Query each mesh address separately; a remote lamp may time out.
                status = await mesh.lamp(mesh_id).read_status(timeout=15)
                print(f"Lamp 0x{mesh_id:04X} status:", status)
            print("Cached mesh states:", mesh.states)


if __name__ == "__main__":
    asyncio.run(main())
