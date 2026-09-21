"""
console.py
==========
Decides whether to keep the console window open when the program finishes.

Double-clicking the EXE opens a window that closes the instant the program
ends, so nobody could read the result: pause there. Never pause when something
else started it -- an AD logon script, a scheduled task or a terminal --
because an unseen "Press Enter" prompt would leave the process waiting forever.
"""

import os
import sys


def should_pause(force: bool = False, never: bool = False) -> bool:
    if never:
        return False
    if force:
        return True
    return launched_by_double_click()


def launched_by_double_click() -> bool:
    if os.name != "nt":
        return False
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
        return launcher_name() == "explorer.exe"
    except Exception:
        return False


def launcher_name() -> str:
    """Name of the process that started this program. Copies of our own
    executable are skipped: PyInstaller's one-file bootloader, and the venv
    python.exe launcher when running from source."""
    table = _process_table()
    own = os.path.basename(sys.executable).lower()
    parent = table.get(os.getpid(), (0, ""))[0]
    for _ in range(4):
        parent_of_parent, name = table.get(parent, (0, ""))
        if name.lower() != own:
            return name.lower()
        parent = parent_of_parent
    return ""


def _process_table() -> dict:
    """pid -> (parent pid, exe name), from a Toolhelp snapshot (no extra packages)."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)     # TH32CS_SNAPPROCESS
    if snapshot is None or snapshot == ctypes.c_void_p(-1).value:
        return {}
    table = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return table
