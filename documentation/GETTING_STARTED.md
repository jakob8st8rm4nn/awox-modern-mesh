# Getting started

## Install

Use Python 3.13 for the tested ESPHome setup. From the repository root, run
`python -m pip install ".[esphome]"`. To use the offline codecs alone, run
`python -m pip install .` on Python 3.10 or later.

## Identify the devices

Prepare the ESPHome proxy host and its API encryption key if enabled. You also
need the mesh name and password, plus the Bluetooth MAC and mesh ID of each
lamp you want to address. [Example 01](../examples/app_01_cloud_account_read.py)
can read available HomeControl account records separately from the library.
Keep its output private because some fields identify accounts and devices.

[Example 02](../examples/app_02_bluetooth_discovery.py) discovers devices and
[Example 03](../examples/app_03_advertisement_monitor.py) observes their
advertisements. An advertisement may be short or omit the mesh ID.
`mesh_address_unsigned` gives the 16-bit address when present. For a live
device report, use a status query after connecting.

## Connect and read a lamp

Run [Example 06](../examples/app_06_read_status.py) with your settings. An
`AwoXMeshSession` takes a transport factory for the Bluetooth gateway you
choose and a mapping of target mesh IDs to Bluetooth MACs. The mapping lets
the session associate status replies with known devices.

The gateway can be the lamp itself or a reachable device in the same mesh.
Use a direct connection when reading group membership for a backup or as a
basis for a write. For more than one target on a single gateway, see
[Example 14](../examples/app_14_multiple_lamps.py).

The async context logs in, enables reception and releases the connection on
exit. If setup fails, the error reaches the caller. For setting values and
handling responses, see the [Python API](PYTHON_API.md).

## Choose an example

Start with [the example index](../examples/README.md). Examples 07–12
demonstrate basic light commands. Examples 15 and 17–29 can change persistent
settings, scene slots, or mesh membership. Review the script's setup values
and side effects before running it.
