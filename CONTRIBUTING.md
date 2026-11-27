# Contributing

Keep changes focused on the **Bluetooth protocol used by AwoX HomeControl**. The library intentionally does not implement a Home Assistant integration, retry policies, automatic reconnection, or application-specific command delays.

Before submitting a change:

1. Include a minimal explanation or protocol byte evidence where possible; distinguish confirmed APK behavior from hypotheses.
2. For behavior changes, add focused offline regression tests using synthetic frames or transports. Keep private credentials out of tests.
3. Run `python -m pytest -q` from the repository root.
4. Keep the example scripts consistent and free of hardcoded secrets or personal device addresses.
5. Verify that any new setting example clearly documents persistent device effects.

Keep documentation focused on protocol fields, API behavior and readable examples. Local hardware investigations, measurement logs and issue-analysis reports are not repository documentation.
