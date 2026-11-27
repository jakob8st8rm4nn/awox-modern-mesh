"""Provision one factory lamp into an existing mesh network.

Supply the existing mesh credentials and 16-byte network key. This changes
persistent device settings and can assign a new ID. No group configuration,
light commands, retries or automatic restoration are performed.

The result reports completion and the new ID if the device supplies one.
A missing ID does not undo a confirmed setup; establish the actual identity
separately before later addressed commands. The old ID may no longer apply.
The factory login in this example assumes the current name is 'unpaired'.
"""

import asyncio
from awox import (AwoXMeshSession, AdvertisementRecord, Credentials,
                  DiscoveredDevice, ESPHomeProxy, ProvisioningSettings,
                  factory_credentials, lookup_models_by_code, lookup_model_properties)

# Edit your local copy; never commit real credentials or device identifiers.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # Existing mesh to join
MESH_PASSWORD = ""          # Existing mesh password
NETWORK_KEY_HEX = ""        # Existing 16-byte network key as 32 hex characters
LAMP_MAC = ""               # Factory lamp's Bluetooth address; connected directly


async def main():
    if not PROXY_HOST or not MESH_NAME or not LAMP_MAC or not NETWORK_KEY_HEX:
        raise ValueError("Set PROXY_HOST, MESH_NAME, LAMP_MAC and NETWORK_KEY_HEX.")
    settings = ProvisioningSettings(Credentials(MESH_NAME, MESH_PASSWORD),
                                    bytes.fromhex(NETWORK_KEY_HEX))

    # A mutable collection is updated by the later advertisement callback.
    # This also lets Pylance see that a matching record may arrive asynchronously.
    matching_records: dict[str, AdvertisementRecord] = {}

    def remember_device(device: DiscoveredDevice) -> None:
        if device.address.upper() != LAMP_MAC.upper():
            return
        candidate = device.advertisement
        if (candidate.firmware and candidate.mesh_address is not None
                and candidate.model_lookup_code
                and any('white_brightness' in (lookup_model_properties(model.name) or ())
                        for model in lookup_models_by_code(candidate.model_lookup_code))):
            # Short advertisements must not replace complete setup metadata.
            matching_records[LAMP_MAC.upper()] = candidate

    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        unsubscribe = proxy.on_advertisement(remember_device)
        try:
            print("Watching for a complete factory-lamp advertisement for 15 seconds...")
            await asyncio.sleep(15)
        finally:
            unsubscribe()
        record = matching_records.get(LAMP_MAC.upper())
        if record is None:
            print("No complete lamp advertisement; nothing was written.")
            return
        # The chosen advertisement must include a full current identity.
        if record.mesh_address is None or record.model_lookup_code is None:
            print("Incomplete lamp identity; nothing was written.")
            return
        current = factory_credentials(LAMP_MAC, record.model_lookup_code, record.firmware)
        # Log in directly to this factory lamp with its current credentials.
        async with AwoXMeshSession(
            lambda: proxy.create_transport(LAMP_MAC), current,
        ) as setup:
            # APK-style wizard pause remains in the example, not in the Library.
            await asyncio.sleep(1)
            result = await setup.provision(
                record.mesh_address & 0xFFFF, settings, groups=None, timeout=20,
                provisioning_byte=record.provisioning_byte,
            )
        if record.provisioning_byte == 0xA0:
            print("0xA0 provisioning branch: network parameters and key were skipped. Verify device operation separately.")
            return
        if not result.completed:
            print("No provisioning completion received; outcome unknown. Do not automatically retry.")
            return
        print("Provisioning completion observed; new ID:",
              f"0x{result.mesh_id:04X}" if result.mesh_id is not None else "not reported")


if __name__ == '__main__':
    asyncio.run(main())
