"""Read AwoX Home Control account and device records through the cloud API.

Set the account credentials below, then run:
    python app_01_cloud_account_read.py

Uses only the Python standard library; no proxy, mesh login or lamp connection
is needed. Logging in creates a cloud session, but no device/settings writes
are sent. Prints the retrieved JSON with common authentication fields masked;
names, account IDs and device addresses remain visible. No files are created.
"""

import json
import re
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# Cloud account settings (do not commit your real credentials).
EMAIL = ""                  # AwoX Home Control account email, not the mesh name
PASSWORD = ""               # Account password, not the mesh password or proxy key

# Public application identifiers used by the Home Control cloud API.
APP_ID = "55O69FLtoxPt67LLwaHGpHmVWndhZGn9Wty8PLrJ"  # Public Parse application ID
CLIENT_KEY = "PyR3yV65rytEicteNlQHSVNpAGvCByOrsLiEqJtI"  # Public Parse client key
SERVERS = (  # Home Control Parse API endpoints
    "https://l4hparse-hc-prod.awox.cloud/parse/",
    "https://l4hparse-prod.awox.cloud/parse/",
)

# Mask common authentication fields recursively; this is not full anonymization.
SECRET_FIELD = re.compile(  # Fields masked in the displayed JSON
    r"password|passwd|token|secret|authorization|api[_-]?key|"
    r"private[_-]?key|client[_-]?key|network[_-]?key|mesh[_-]?key|"
    r"^key$|^ltk$|client[_-]?id|installation[_-]?id|auth[_-]?data",
    re.IGNORECASE,
)


def request_json(url, installation_id, payload, session_token=None):
    """Send one Parse request; callers choose read operations via _method=GET."""
    headers = {
        "X-Parse-Application-Id": APP_ID,
        "X-Parse-Client-Key": CLIENT_KEY,
        "X-Parse-Installation-Id": installation_id,
        "Content-Type": "application/json",
    }
    if session_token:
        headers["X-Parse-Session-Token"] = session_token
    request = Request(url, json.dumps(payload).encode("utf-8"), headers, method="POST")
    try:
        with urlopen(request, timeout=20) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            raise RuntimeError("Invalid cloud response: expected a JSON object")
        return data
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError("Cloud service returned invalid JSON") from None
    except HTTPError as exc:
        raise RuntimeError(f"Cloud HTTP error {exc.code} at {url.split('/parse/')[0]}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Cloud service is unreachable") from exc


def read_class(server, installation_id, session_token, name, owner=None):
    """Read paged records; optionally restrict them to the account's owner ID."""
    results = []
    # Up to 100 pages of 100 records; stop rather than silently truncate.
    for page in range(100):
        query = {"_method": "GET", "limit": 100, "skip": page * 100}
        if owner is not None:
            query["where"] = {
                "owner": {"__type": "Pointer", "className": "_User", "objectId": owner}
            }
        data = request_json(server + "classes/" + name, installation_id, query, session_token)
        rows = data.get("results")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise RuntimeError(f"Invalid {name} response")
        results.extend(rows)
        if len(rows) < 100:
            return results
    raise RuntimeError(f"Too many {name} records; request stopped")


def mask_secrets(value):
    if isinstance(value, dict):
        return {
            key: "<REDACTED>" if SECRET_FIELD.search(key) else mask_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_secrets(item) for item in value]
    return value


def format_mesh_id(value):
    if value is None or value == "":
        return "?"
    try:
        return f"0x{int(value) & 0xFFFF:04X}"
    except (ValueError, TypeError):
        return str(value)


def main():
    if not EMAIL.strip() or not PASSWORD:
        print("Set EMAIL and PASSWORD in this script before running it.")
        return

    # Try the known account endpoints; retain the successful server for reads.
    installation_id = str(uuid.uuid4())
    for server in SERVERS:
        try:
            account = request_json(
                server + "login",
                installation_id,
                {"username": EMAIL.strip().lower(), "password": PASSWORD, "_method": "GET"},
            )
            if account.get("sessionToken") and account.get("objectId"):
                break
        except RuntimeError:
            pass
    else:
        print("Login failed. Check account credentials, internet access, and cloud availability.")
        return

    owner = account["objectId"]
    token = account["sessionToken"]
    # Device queries include owned records and any shared records visible to
    # this authenticated account. No ACL or membership is changed.
    credentials = read_class(server, installation_id, token, "Credential", owner)
    owned_devices = read_class(server, installation_id, token, "Device", owner)
    visible_devices = read_class(server, installation_id, token, "Device")

    # Combine owned and visible devices, removing duplicate object IDs.
    devices = {
        str(device.get("objectId") or id(device)): device
        for device in owned_devices + visible_devices
    }
    data = mask_secrets({
        "account": account,
        "credentials": credentials,
        "devices": list(devices.values()),
    })

    print("\n=== AwoX Account ===")
    print("Account ID:", owner)
    print("Devices:", len(devices), "| Credential records:", len(credentials))
    for device in devices.values():
        print(
            "-", device.get("displayName") or device.get("name") or device.get("modelName") or "Unnamed",
            "| Model:", device.get("modelName") or device.get("model") or "?",
            "| MAC:", device.get("macAddress") or device.get("mac") or "?",
            "| Mesh ID:", format_mesh_id(device.get("address", device.get("meshAddress"))),
        )

    print("\n=== Retrieved Data (Sensitive Fields Redacted) ===")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("Note: Device names, MAC addresses, and account IDs may still be private.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print("Error:", exc)
