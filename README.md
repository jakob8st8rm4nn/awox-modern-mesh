# AwoX Modern Mesh protocol library

Independent Python implementation of **AwoX Modern Mesh**, based on protocol
analysis of AwoX HomeControl Android 1.14.10/1.14.11 and documented protocol
reference data. The library logs in through an explicitly selected ESPHome
Bluetooth proxy and encrypts commands with the session key. It also provides
standalone frame encoders, decoders and offline tests.

This is an independent interoperability project, not affiliated with AwoX,
EGLO or ESPHome. Legacy Telink and OTA firmware updates are outside its scope.

## Features

- Explicit BLE connection and mesh login using one `AwoXMeshSession`.
- Power, brightness, RGB/native color, color temperature, transitions and effects.
- Scenes, group/broadcast commands and stored mesh-group membership.
- Dual-Zone control, PIR, Quiet Mode and power-cut behavior.
- Timers, programs, nightlight, dawn and presence simulation.
- Time and timezone operations, status observations and BLE advertisements.
- Direct-device provisioning and mesh removal.
- Typed public Python API, 29 standalone examples and offline protocol tests.

A completed GATT write **does not** establish that a device physically applied a
command. Commands are not automatically retried, replayed, read back or rolled
back. Some explicit convenience methods wait for a documented device response.

## Installation

Requires Python 3.10 or later. From the repository root:

```console
python -m pip install -e ".[esphome]"
```

For offline codecs and tests without ESPHome dependencies:

```console
python -m pip install -e .
```

The installed package is named `awox`; the distribution name is
`awox-mesh-reconstruction`. It includes `awox/py.typed` for editor type support.

## First connection

```python
import asyncio
from awox import AwoXMeshSession, Credentials, ESPHomeProxy

# Fill these values in your local copy only.
PROXY_HOST = ""
PROXY_KEY = ""
MESH_NAME = ""
MESH_PASSWORD = ""
GATEWAY_MAC = ""
LAMP_MAC = ""
MESH_ID = 0


async def main():
    if not all((PROXY_HOST, MESH_NAME, GATEWAY_MAC, LAMP_MAC, MESH_ID)):
        raise ValueError("Configure the proxy and lamp settings first")
    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        async with AwoXMeshSession(
            lambda: proxy.create_transport(GATEWAY_MAC),
            Credentials(MESH_NAME, MESH_PASSWORD),
            devices={MESH_ID: LAMP_MAC},
        ) as mesh:
            lamp = mesh.lamp(MESH_ID)
            await lamp.set_power(True)
            await lamp.set_brightness(50)


if __name__ == "__main__":
    asyncio.run(main())
```

These are local connection settings. The repository does not include personal
credentials. The complete [status example](examples/app_06_read_status.py)
shows a separate device-read workflow.

For an active device read, use `await lamp.read_status()`. To retrieve a
previously observed status without a BLE request, use `mesh.get_status(MESH_ID)`.
Inside the connected session, for a command whose response you want to
observe explicitly:

```python
from awox.groups import set_mesh_groups

receipt = await mesh.send_and_track_reply(
    set_mesh_groups(MESH_ID, [0x8000]),
    0x0C,
    target=MESH_ID,
    timeout=5.0,
)
reply = await receipt.wait()
```

`reply` is `None` if no matching notification is observed within the response
window. This code **writes the group list**; it is not a harmless query. Use
`await lamp.set_mesh_groups([0x8000])` for a decoded result, or
`await lamp.write_mesh_groups([0x8000])` for send-only behavior.

## Examples

The [29 standalone examples](examples/README.md) demonstrate discovery,
lighting, groups, effects, persistent settings and provisioning. Editable
connection values are grouped at the top of each file and left blank.

Run an offline example immediately:

```console
python examples/app_04_model_registry.py
```

For a live example, configure the required values in
`examples/app_06_read_status.py` and run that file. Examples that alter stored
settings, mesh credentials or pairing identities explain their side effects.
**Review these operations before running them on a device.**

## Documentation

- [Documentation index](documentation/README.md)
- [Getting started](documentation/GETTING_STARTED.md)
- [Command reference](documentation/COMMAND_REFERENCE.md)
- [Python API and response handling](documentation/PYTHON_API.md)
- [Examples](examples/README.md)
- [Provisioning and removal](documentation/PROVISIONING.md)
- [Architecture](documentation/ARCHITECTURE.md)
- [Editor completion and typing](documentation/EDITOR_AUTOCOMPLETE.md)
- [Offline testing](documentation/TESTING.md)

## Tests

```console
python -m pip install pytest
python -m pytest -q
```

The tests use synthetic transports and stored protocol fixtures, not real
Bluetooth hardware. Passing offline tests is not proof of operation for every
physical device model. See [Testing](documentation/TESTING.md).

## Scope and license

The license for this implementation is MIT; see [LICENSE](LICENSE) and
[NOTICE.md](NOTICE.md) for third-party rights and the limits of the reference
data. Contributions are described in [CONTRIBUTING.md](CONTRIBUTING.md).
