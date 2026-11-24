# AwoX Modern Mesh

A Python library for discovering, controlling and provisioning AwoX Modern Mesh
devices over an ESPHome Bluetooth proxy. It provides typed commands, low-level
frame builders and decoders for device replies and advertisements.

The implementation is based on protocol analysis of AwoX HomeControl Android
1.14.10 and 1.14.11. Device features vary by model. The project is independent of
AwoX, EGLO and ESPHome. Legacy Telink and firmware updates are outside its scope.

## Installation

Clone this repository and run one of these commands from its root.

| Use | Command |
| --- | --- |
| Connect through an ESPHome Bluetooth proxy | `python -m pip install ".[esphome]"` |
| Work with protocol codecs offline | `python -m pip install .` |

The base package supports Python 3.10 and later. The ESPHome dependency check
runs on Python 3.13, which is the tested setup for the proxy examples.
The distribution is named `awox-mesh-reconstruction`. Import it as `awox`.

## First connection

Start with [Getting started](documentation/GETTING_STARTED.md) to obtain the
proxy settings, mesh credentials and device identity. Then try
[Example 06](examples/app_06_read_status.py) to connect and query a lamp without
changing its settings.

After opening a session, a typical interaction looks like this:

```python
lamp = mesh.lamp(mesh_id)
await lamp.set_power(True)
await lamp.set_brightness(50)
status = await lamp.read_status()
```

The first two calls send one command each. The third actively requests a
device report. A successful Bluetooth write confirms the GATT operation.
A status report describes the observed device state. To receive acknowledgements
for commands that provide them, use the methods described in the Python API.

## Documentation

- [Getting started](documentation/GETTING_STARTED.md) — settings, discovery and first connection
- [Examples](examples/README.md) — 29 standalone scripts by task
- [Python API](documentation/PYTHON_API.md) — sessions, commands, replies and timeouts
- [Command reference](documentation/COMMAND_REFERENCE.md) — arguments and results
- [Documentation index](documentation/README.md) — provisioning, device models, architecture and testing

The library sends commands and exposes replies. Applications decide when to
send another command, how to verify an outcome and whether to retry.

## Development

Run the offline suite with `python -m pytest -q` after installing the package
and pytest. See [Offline testing](documentation/TESTING.md) and
[Contributing](CONTRIBUTING.md) for details. See [Security](SECURITY.md) for
handling credentials and sharing example output.

The implementation is released under the [MIT license](LICENSE). See
[NOTICE.md](NOTICE.md) for project and reference-data information.
