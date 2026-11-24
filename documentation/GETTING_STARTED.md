# Getting started

Install from the repository with `python -m pip install ".[esphome]"`.
For pure offline protocol work, `python -m pip install .` is sufficient.

Obtain the ESPHome proxy host/API encryption key, mesh name/password and current
device identities. Example 01 reads available cloud records separately; the
package does not log into the cloud. Never publish real settings or tokens.

Use example 02 for discovery and example 03 for passive advertisements. An
advertisement may be short, stale or missing fields; a cached scan result is
not an active device status. `mesh_address_unsigned` gives an explicit unsigned
wire address from the signed scanner field.

Select one gateway MAC explicitly. Create an `AwoXMeshSession` using a callable
which returns or awaits `proxy.create_transport(gateway_mac)`. Known lamp IDs and
MACs are supplied as a dictionary for status identity checks. Group and
broadcast control does not register a fake lamp.

Open the session as an async context. A successful open includes one login
attempt and receive activation. A failed login is reported; the application
decides whether and when to try again. Close releases the owned connection.

Examples 07–12 demonstrate one light feature at a time. Follow with example 14
for multiple devices on one gateway. Example 15 replaces the selected lamp's
group list, checks that the requested membership is reported, then controls
the group. Group commands do not confirm every member.

Examples which change persistent settings say so in their opening comments.
Review the selected values before running them. Examples 26–28 change mesh
configuration and may change device identities. They are not restoration tools.
