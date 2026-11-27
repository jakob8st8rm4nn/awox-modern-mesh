"""Discover nearby AwoX devices through one ESPHome Bluetooth proxy.

Set the proxy connection values below. No mesh credentials or lamp connection
are needed. The 15-second scan returns one cached observation per device,
not every radio packet. Short advertisements can lack an ID or light state.
"""
import asyncio
from awox import ESPHomeProxy

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)


async def main():
    if not PROXY_HOST:
        raise ValueError("Set PROXY_HOST in this example.")
    # Connect only to the proxy API; there is no mesh session in this example.
    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        # Observe nearby devices for 15 seconds; no lamp connection is opened.
        devices = await proxy.scan_mesh_devices(duration=15)
        if not devices:
            print("No compatible AwoX advertisements detected by the proxy.")
        for device in devices:
            print("MAC:", device.address)
            print("RSSI:", device.rssi)
            print("Name:", device.advertisement.local_name)
            # Short advertisements may not contain a mesh address.
            print("Mesh address:", device.advertisement.mesh_address)
            print("Model code:", device.advertisement.model_code)
            print(device)


if __name__ == "__main__":
    asyncio.run(main())
