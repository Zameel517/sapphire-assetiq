"""
paths.py
========
Where the program's files live, whatever folder it was started from.

The program writes NO data files on the machine -- the Google Sheet is the
record. The only thing it leaves behind is a small log per run, in the
signed-in user's own AppData, so a scan that fails on a remote machine can
still be explained afterwards.

Read-only inputs (config.json, service_account.json) are resolved against the
APPLICATION folder, never the current folder, because an AD logon script
usually starts the EXE in C:\\Windows\\System32:

  built EXE     -> the folder containing SapphireAssetIQ.exe
  from source   -> the src folder containing main.py
"""

import os
import sys

APP_DATA_FOLDER = "Sapphire AssetIQ"


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundle_dir() -> str | None:
    """Where files built INTO a one-file EXE are unpacked (config.json,
    service_account.json), or None when not running as a built EXE."""
    return getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None


def log_dir() -> str:
    """The one folder this program creates: %LOCALAPPDATA%\\Sapphire AssetIQ\\logs.

    Nothing is written next to the EXE, so running it straight from a read-only
    network share is fine and no output folder ever appears on a user's machine."""
    home = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(home, APP_DATA_FOLDER, "logs")
    os.makedirs(path, exist_ok=True)
    return path


def resolve(path: str, base: str | None = None) -> str:
    """Absolute paths are kept; relative ones are placed under `base`
    (default: the application folder)."""
    if not path:
        return path
    path = os.path.expandvars(os.path.expanduser(path))
    return path if os.path.isabs(path) else os.path.join(base or app_dir(), path)
