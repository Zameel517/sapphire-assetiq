"""
settings.py
============
Loads config.json: the copy built into the one-file EXE, or one placed next to
the EXE, which wins over it (see scan_runner.plan_run).

The customer chose the single-file build, so config.json and the Google service-account
key travel inside the EXE. Keep the EXE on a share users can only read and
execute, and rotate the key if a copy ever leaves the domain.
"""

import json
import os

DEFAULT_CONFIG = {
    "company": None,
    "location": None,
    # VLAN prefix -> site name, e.g. {"10.20.30.": "Head Office"}.
    # One shared map goes to the whole fleet; each machine looks up the VLAN its
    # own IP sits on, so no site name is ever hardcoded per machine. Only VLANs
    # the company has confirmed belong here. See collectors/organization_collector.py.
    "vlan_location_map": {},
    "google_spreadsheet_id": None,
    "google_credentials_path": "service_account.json",
    "google_worksheet_name": "Inventory",
}


def load_config(config_path: str = "config.json") -> dict:
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        config.update({k: v for k, v in user_config.items() if v is not None})
    return config
