"""
wmi_utils.py
============
Thin, defensive wrapper around the `wmi` package.

Design rule from the project chat: "one field failing must never crash
the scan." Every query here catches exceptions and returns None instead
of raising, so collectors can decide how to handle a missing value.
"""

import gc
import platform
import subprocess
import threading
from contextlib import contextmanager

IS_WINDOWS = platform.system() == "Windows"

# A WMI connection is a COM object, and COM objects belong to the thread that
# created them. The window scans on a fresh background thread every time, so a
# connection cached during one scan and reused by the next failed -- and in
# testing crashed the process with an access violation. Connections are kept
# per thread, and COM is initialised on each thread before it is used.
_local = threading.local()

if IS_WINDOWS:
    try:
        # The wmi package opens a COM object as soon as it is imported and keeps
        # it until the program exits, on the importing thread. This module is
        # loaded at start-up on the main thread, whose COM stays on for the whole
        # run, so that object is never left behind on a finished scan thread.
        import wmi  # noqa: F401
    except Exception:
        pass


def _ensure_com():
    # Importing pythoncom already switched COM on for the main thread, for the
    # whole run. Only other threads have to do it themselves.
    if getattr(_local, "com_initialised", False) or threading.current_thread() is threading.main_thread():
        return
    try:
        import pythoncom
        pythoncom.CoInitialize()
        _local.com_initialised = True
    except Exception:
        pass


def _live_com_objects() -> int | None:
    """How many COM objects the program holds right now (None if unknown)."""
    try:
        import pythoncom
        return pythoncom._GetInterfaceCount()
    except Exception:
        return None


def get_wmi_namespace(namespace: str = "root\\cimv2"):
    """This thread's connection to a WMI namespace, created on first use."""
    if not IS_WINDOWS:
        return None
    connections = _local.__dict__.setdefault("connections", {})
    if namespace not in connections:
        _ensure_com()
        import wmi  # only imported on Windows
        connections[namespace] = wmi.WMI(namespace=namespace)
    return connections[namespace]


def get_wmi():
    """This thread's connection to root\\cimv2."""
    return get_wmi_namespace("root\\cimv2")


def get_wmi_security_center():
    """This thread's connection to root\\SecurityCenter2 (antivirus)."""
    return get_wmi_namespace("root\\SecurityCenter2")


@contextmanager
def com_session():
    """Prepare COM on the current thread for one scan, then release that thread's
    WMI connections, so the next scan -- on any thread -- starts clean.

    A scan thread switches COM off again only once every COM object the scan made
    is gone: an object still alive at that point causes an access violation when
    it is finally released. The main thread's COM is never switched off --
    doing so ended every test run with an access violation at exit.
    """
    _ensure_com()
    live_before = _live_com_objects()
    try:
        yield
    finally:
        _local.__dict__.pop("connections", None)
        gc.collect()                                  # release this scan's COM wrappers
        if getattr(_local, "com_initialised", False):
            live_after = _live_com_objects()
            if live_before is not None and live_after is not None and live_after <= live_before:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                    _local.com_initialised = False
                except Exception:
                    pass


def safe_query(query_fn, default=None):
    """Run a zero-arg callable; swallow errors and return `default`."""
    try:
        return query_fn()
    except Exception:
        return default


# Starting PowerShell and loading a module (Get-PhysicalDisk, Get-VpnConnection)
# took 5-16 s on a normal laptop in real scan logs, and old till PCs are slower
# still. 15 s was too tight: a timeout silently became Disk Type "Unknown" or
# VPN "No". A longer limit only costs time on a machine that is genuinely slow;
# a fast machine returns as soon as PowerShell finishes.
POWERSHELL_TIMEOUT_S = 60


def run_powershell(command: str, timeout: int = POWERSHELL_TIMEOUT_S) -> str | None:
    """Run a PowerShell command and return stdout, or None on failure."""
    if not IS_WINDOWS:
        return None
    try:
        # The EXE is a windowed program with no console, so Windows would open a
        # visible console window for every PowerShell call. Keep it hidden.
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0                      # SW_HIDE
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startupinfo,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None
