# Editor support and type information (VS Code / Pylance)

The repository uses a `python/` source layout. Open the folder containing
`pyproject.toml` in VS Code so `.vscode/settings.json` and `pyrightconfig.json`
can locate the package without installing it first.

To use the library in another project, activate that project's Python
environment, then run the following from this repository's root:

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
