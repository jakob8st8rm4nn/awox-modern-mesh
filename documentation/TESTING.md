# Offline testing

From the repository root:

```console
python -m pip install -e .
python -m pip install pytest
python -m pytest -q
```

No ESPHome installation, network account, proxy or physical device is needed.
pytest resolves `python` and `tests` using pyproject.toml.

The suite combines APK-related and synthetic crypto fixtures, stored
reference-byte comparisons, transport/proxy regression tests, authenticated
session tests using a fake GATT transport, and execution of all 29 examples
with mocked external endpoints. The Bluetooth examples use the session code against simulated external
connections. The cloud example uses a simulated endpoint.

The frozen test vectors cover addresses, group lists, scene slots, immediate
light values, transitions, color conversions, dual-zone and query fields.
These comparisons establish equality with stored reference values, not
independent proof of the APK implementation. APK-derived exact-byte fixtures and model tables supply separate evidence.

Async cases cover replies during writes, expiry without waiting, optional waits,
disconnection, local cancellation, cleanup ownership, stale callbacks, login
rejection, schedule continuation and absence of hidden retransmission.

Offline example execution is not a hardware confirmation. No automated tests
operate real cloud endpoints or Bluetooth devices. Hardware investigations and
private logs are not included in the published package.

## Optional ESPHome dependency compatibility

The ordinary offline test job does **not** install the optional ESPHome
packages; hardware and network access are unnecessary for it. A separate CI
job installs the **real** optional dependencies and runs
`tests/test_esphome_installed_dependencies.py` to check import and interface
availability. To reproduce locally:

```console
python -m pip install -e '.[esphome]' pytest
python -m pytest -q tests/test_esphome_installed_dependencies.py
python -m pip show bleak-esphome habluetooth bleak
```

CI saves the exact resolved dependency versions in its
`esphome-resolved-versions-py313` artifact; consult the successful workflow
run for the versions tested by CI. For a local run, record the versions shown
by `pip show`. The checks cover imports and selected interfaces. The private
No-CCCD subscription still needs a real proxy and device to verify delivery.
