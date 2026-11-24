"""Observe delivered AwoX advertisement events and inspect the final cache.

Requires only proxy settings; no mesh login or BLE lamp connection is opened.
Prints valid events delivered by the backend, including repeats when available.
This is not a capture of every transmitted radio packet. The final cache may
contain older or short observations without light data; no lamp is controlled.
"""
import asyncio
import time
from awox import ESPHomeProxy, DiscoveredDevice

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
OBSERVE_SECONDS = 15       # Seconds to monitor incoming advertisements


async def main():
    if not PROXY_HOST:
        raise ValueError("Set PROXY_HOST in this example.")

    received = {}
    observing = True

    # Called for each AwoX event delivered by the proxy, including repeats.
    def on_advertisement(device: DiscoveredDevice) -> None:
        if not observing:
            return

        mac = device.address
        received[mac] = received.get(mac, 0) + 1
        record = device.advertisement
        mesh_id = (f"0x{record.mesh_address_unsigned:04X}"
                   if record.mesh_address_unsigned is not None else "unknown")
        model = record.model_code.hex(" ") if record.model_code is not None else "unknown"
        print(f"Advertisement #{received[mac]}: {mac}, RSSI={device.rssi}, "
              f"mesh={mesh_id}, model={model}, firmware={record.firmware}, "
              f"hardware={record.hardware_version}, provisioning={record.provisioning_byte}")
        print(f"  Light: {record.light_state if record.light_state is not None else 'not present'}")
        print(f"  Manufacturer: {record.manufacturer.hex(' ') if record.manufacturer else 'unknown'}")

    print("Connecting to ESPHome proxy (receive-only)...", flush=True)
    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY, on_advertisement=on_advertisement) as proxy:
        print("ESPHome proxy connected; advertisement callbacks active.", flush=True)
        print(f"Listening for {OBSERVE_SECONDS} seconds (no mesh connection)...")
        await asyncio.sleep(OBSERVE_SECONDS)
        # Stop printing before closing the proxy; take a final cache snapshot.
        observing = False

        # Take one typed snapshot. get_advertisement(mac) could return None,
        # even when mac appeared in an earlier snapshot.
        snapshot = proxy.advertisements
        cached = {mac: snapshot[mac] for mac in sorted(snapshot)}

    print("Advertisements received:", received)
    print("Cached AwoX devices:", len(cached))

    for mac, record in cached.items():
        if record.received_monotonic is None:
            age = "unknown"
        else:
            age = f"{max(0.0, time.monotonic() - record.received_monotonic):.1f}s"

        print(f"{mac}: last-seen age={age}, "
              f"raw AD bytes={len(record.raw_advertisement) if record.raw_advertisement is not None else 'not supplied'}, "
              f"service UUIDs={record.service_uuids}")

    print("A cached advertisement is not a confirmed/current GATT lamp status.")


if __name__ == "__main__":
    asyncio.run(main())
