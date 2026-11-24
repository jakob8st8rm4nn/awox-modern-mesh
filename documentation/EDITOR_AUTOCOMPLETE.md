# Editor support and type information (VS Code / Pylance)

The repository uses a `python/` source layout. Open the folder containing
`pyproject.toml` in VS Code so `.vscode/settings.json` and `pyrightconfig.json`
can locate the package without installing it first.

For normal use from another project, install the package into that project's
Python environment:

```console
python -m pip install -e ".[esphome]"
```

Select the interpreter in **Python: Select Interpreter**. If imports or method
suggestions are stale, use **Python: Restart Language Server**. The installed
package includes `awox/py.typed` (PEP 561), allowing Pylance and other type
checkers to read public type annotations.

```python
from awox import AwoXMeshSession, ESPHomeProxy, AdvertisementRecord

# mesh.lamp(device_id) returns Lamp, with set_power(), set_rgb(), etc.
# proxy.create_transport(mac) provides an ESPHome transport.
# AdvertisementRecord exposes firmware, mesh_address and other parsed fields.
```

`set_power()` belongs to `Lamp`/`MeshTarget`; `create_transport()` belongs to
`ESPHomeProxy`; and `provision()` belongs to `AwoXMeshSession`. Colorization is
editor/theme-specific and does not determine whether a method is callable.

Some fields are optional. For example `AdvertisementRecord.local_name` is
`str | None`. Check that it is nonempty before passing it to a function that
requires a string. Likewise, `get_advertisement()` can return `None`.

For scan callbacks, annotate the incoming `DiscoveredDevice`, or use the
`AdvertisementRecord` type for stored advertisements. A container like
`dict[str, AdvertisementRecord]` makes callbacks that collect scan results
easier for static analyzers to reason about.

If Pylance reports **unreachable code**, inspect the actual control flow and
value narrowing; a callback scheduled by an external library may not be
recognized by static analysis. Use explicit checks after the asynchronous
observation window. A faded import may simply be unused.

The 29 examples demonstrate typed session/target calls, checked optional
fields and safe result handling. Python runtime behavior and editor markings
are separate concerns.
