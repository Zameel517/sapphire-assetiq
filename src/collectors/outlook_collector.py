r"""
outlook_collector.py
=====================
Collects: Outlook Email.

Classic Outlook (Microsoft 365 / 2021 / 2019 / 2016 / 2013 / 2010) keeps every
mail profile in the registry, so the mailbox address can be read without
Outlook running:

  HKCU\Software\Microsoft\Office\<16.0|15.0|14.0>\Outlook\Profiles\<profile>\
      9375CFF0413111d3B88A00104B2A6676\<0000000N>   one key per account:
          "Account Name", "Email", "IMAP Server", "POP3 Server"
      <service section>                                 Exchange / Microsoft 365:
          001f6641   PR_PROFILE_USER_SMTP_EMAIL_ADDRESS

Most of that text is stored as REG_BINARY UTF-16, which is why reading it as a
plain string finds nothing. Every value in the profile is decoded, candidate
addresses are ranked by the property they came from, and the default profile
is tried first.

The new Outlook app (olk.exe) has no registry profile: its accounts are read
from %LOCALAPPDATA%\Microsoft\Olk\UserSettings.json. Whichever Outlook the user
is set to use (Outlook\Preferences\UseNewOutlook) is tried first, then the other.

Reads HKEY_CURRENT_USER, so it must run as the signed-in user (an AD logon
script, not a computer startup script running as SYSTEM).

The mail system behind the account (Exchange, IMAP host, Microsoft 365) is
still worked out, because it decides which account is the real mailbox, but
it is no longer reported: the Email Server column was dropped on 2026-09-17.
"""

import json
import os
import platform
import re

from models.system_info import SystemInfoRecord

IS_WINDOWS = platform.system() == "Windows"

OFFICE_VERSIONS = ("16.0", "15.0", "14.0")
OUTLOOK_EXE_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-']+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")

# How far each profile property is trusted to hold THE user's own mailbox address.
EMAIL_PROPERTY_RANK = {
    "001f6641": 100, "001e6641": 100,        # PR_PROFILE_USER_SMTP_EMAIL_ADDRESS (Exchange / M365)
    "email": 90, "smtp email address": 90,   # IMAP / POP accounts
    "account name": 80,                      # normally the address itself
    "001f39fe": 70, "001e39fe": 70,          # PR_SMTP_ADDRESS
}
OTHER_PROPERTY_RANK = 10                     # any other address (shared mailboxes, contacts, ...)
MAILBOX_SERVER_PROPERTIES = {"imap server": "IMAP", "pop3 server": "POP3"}
MICROSOFT_365_MARKERS = ("outlook.office365.com", ".prod.outlook.com", "onmicrosoft.com")
PROFILE_DEPTH = 3

NEW_OUTLOOK_SETTINGS = r"Microsoft\Olk\UserSettings.json"
NEW_OUTLOOK_PREFERENCE = (r"Software\Microsoft\Office\16.0\Outlook\Preferences", "UseNewOutlook")
SHADOW_DOMAIN = "@shadow.outlook.com"        # new Outlook's internal account id, never a mailbox


def collect(record: SystemInfoRecord):
    if not IS_WINDOWS:
        record.set("outlook_email", None, source="none", status="missing")
        return

    try:
        import winreg
    except ImportError:
        record.set("outlook_email", "Not Available", source="none", status="missing")
        return

    hkcu = WinRegReader(winreg, winreg.HKEY_CURRENT_USER)
    hklm = WinRegReader(winreg, winreg.HKEY_LOCAL_MACHINE)
    classic = find_outlook_account(hkcu, hklm)
    new = find_new_outlook_account(os.environ.get("LOCALAPPDATA"))
    prefers_new = decode_text(hkcu.value(*NEW_OUTLOOK_PREFERENCE)) == "1"
    account = choose_account(classic, new, prefers_new)

    if account["email"]:
        record.set("outlook_email", account["email"], source="Registry:Outlook profile",
                   raw=account["where"], note=f"Read from {account['where']}")
    else:
        record.set("outlook_email", "Not Available", source="none", status="missing",
                   note=account["note"])

    # The mail server is still worked out above because it decides which account
    # is the real mailbox, but the column was dropped: it carried product labels
    # ("Microsoft 365", "IMAP host"), which confused the inventory more than helped.


def find_outlook_account(hkcu, hklm) -> dict:
    """-> {email, where, server, note}. `hkcu`/`hklm` are registry readers."""
    profiles = []
    for version in OFFICE_VERSIONS:
        base = rf"Software\Microsoft\Office\{version}\Outlook\Profiles"
        names = hkcu.subkeys(base)
        if not names:
            continue
        default = decode_text(hkcu.value(rf"Software\Microsoft\Office\{version}\Outlook", "DefaultProfile"))
        names.sort(key=lambda n: 0 if default and n.lower() == default.lower() else 1)
        profiles += [(version, name, rf"{base}\{name}") for name in names]

    if not profiles:
        installed = outlook_installed(hklm)
        return {"email": None, "where": None,
                "server": "Unknown/Not Configured" if installed else "Outlook Not Found",
                "note": ("Classic Outlook is installed but has no mail profile for this user"
                         if installed else "Classic Outlook is not installed")}

    best = None                  # (rank, -order, address, where, key)
    servers_by_key, order = {}, 0
    exchange = microsoft_365 = False
    for version, name, path in profiles:
        for key, value_name, data in walk(hkcu, path, PROFILE_DEPTH):
            text = decode_text(data)
            if not text:
                continue
            prop = value_name.lower()
            if prop in MAILBOX_SERVER_PROPERTIES and text.strip():
                servers_by_key.setdefault(key, f"{MAILBOX_SERVER_PROPERTIES[prop]} ({text.strip()})")
            if prop in ("001f6641", "001e6641"):
                exchange = True
            if any(marker in text.lower() for marker in MICROSOFT_365_MARKERS):
                microsoft_365 = True
            for address in EMAIL_RE.findall(text):
                order += 1
                candidate = (EMAIL_PROPERTY_RANK.get(prop, OTHER_PROPERTY_RANK), -order, address,
                             f"Office {version} Outlook profile '{name}' ({value_name})", key)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
        if best and best[0] >= EMAIL_PROPERTY_RANK["account name"]:
            break                # a real mailbox address in the default profile: done

    if best and best[4] in servers_by_key:
        server = servers_by_key[best[4]]
    elif microsoft_365:
        server = "Microsoft 365 (Exchange Online)"
    elif exchange:
        server = "Microsoft Exchange"
    elif servers_by_key:
        server = next(iter(servers_by_key.values()))
    else:
        server = "Configured (profile detected)"

    return {"email": best[2] if best else None,
            "where": best[3] if best else None,
            "server": server,
            "note": "" if best else (f"{len(profiles)} Outlook profile(s) found, but none holds "
                                     f"a readable email address")}


def find_new_outlook_account(local_app_data: str | None):
    """Accounts set up in the new Outlook app, or None if it has never run."""
    if not local_app_data:
        return None
    try:
        with open(os.path.join(local_app_data, NEW_OUTLOOK_SETTINGS), encoding="utf-8-sig") as fh:
            settings = json.load(fh)
    except (OSError, ValueError):
        return None
    return parse_new_outlook_settings(settings)


def parse_new_outlook_settings(settings: dict) -> dict:
    """UserSettings.json -> {email, where, server, note}. The main account
    (GlobalSettingsAccout, Microsoft's own spelling) is preferred; internal
    shadow.outlook.com identities are ignored."""
    try:
        accounts = json.loads((settings.get("AccountLocalBackup") or {}).get("Json") or "[]")
    except (TypeError, ValueError):
        accounts = []
    accounts = [a for a in accounts if isinstance(a, dict)
                and EMAIL_RE.fullmatch(str(a.get("emailAddress", "")))
                and not str(a.get("emailAddress")).lower().endswith(SHADOW_DOMAIN)]
    if not accounts:
        return {"email": None, "where": None, "server": None,
                "note": "New Outlook has no mail account set up"}

    main = settings.get("GlobalSettingsAccout") or settings.get("GlobalSettingsAccount") or {}
    main_email = str(main.get("Email", "")).lower()
    accounts.sort(key=lambda a: 0 if a["emailAddress"].lower() == main_email else 1)
    chosen = accounts[0]
    kind = chosen.get("accountType") or "Mail"
    return {"email": chosen["emailAddress"],
            "where": f"new Outlook, {kind} account (UserSettings.json)",
            "server": f"{kind} (new Outlook)",
            "note": f"{len(accounts)} account(s) set up in new Outlook"}


def choose_account(classic: dict, new: dict | None, prefers_new: bool) -> dict:
    """The Outlook the user is set to use goes first; the other is the fallback."""
    for account in ([new, classic] if prefers_new else [classic, new]):
        if account and account["email"]:
            return account
    return classic                   # no address anywhere: keep classic's status label


def outlook_installed(hklm) -> bool:
    return hklm.exists(OUTLOOK_EXE_APP_PATH)


def walk(reader, path: str, depth: int):
    """Yield (key path, value name, data) for a key and its subkeys."""
    for name, data in reader.values(path):
        yield path, name, data
    if depth <= 0:
        return
    for sub in reader.subkeys(path) or []:
        yield from walk(reader, rf"{path}\{sub}", depth - 1)


def decode_text(data) -> str:
    """Registry data -> readable text. Outlook stores most strings as UTF-16
    inside REG_BINARY values; ANSI (001e...) properties are single-byte."""
    if data is None or isinstance(data, int):
        return ""
    if isinstance(data, str):
        return data.replace("\x00", "").strip()
    if isinstance(data, (list, tuple)):
        return " ".join(decode_text(item) for item in data).strip()
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
        if len(raw) >= 2 and len(raw) % 2 == 0:
            text = raw.decode("utf-16-le", errors="ignore").replace("\x00", "")
            if text and sum(32 <= ord(c) < 127 for c in text) >= 0.9 * len(text):
                return text.strip()
        return " ".join(re.findall(r"[\x20-\x7e]{4,}", raw.decode("latin-1")))
    return ""


class WinRegReader:
    """Minimal read-only registry access; every miss returns empty, never raises.
    Tries the 64-bit and 32-bit views, since 32-bit Office registers in the latter."""

    def __init__(self, winreg, hive):
        self._w, self._hive = winreg, hive
        self._views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)

    def _open(self, path):
        for view in self._views:
            try:
                return self._w.OpenKey(self._hive, path, 0, self._w.KEY_READ | view)
            except OSError:
                continue
        return None

    def exists(self, path) -> bool:
        key = self._open(path)
        if key is None:
            return False
        self._w.CloseKey(key)
        return True

    def subkeys(self, path):
        key = self._open(path)
        if key is None:
            return None
        try:
            return [self._w.EnumKey(key, i) for i in range(self._w.QueryInfoKey(key)[0])]
        finally:
            self._w.CloseKey(key)

    def values(self, path):
        key = self._open(path)
        if key is None:
            return []
        out = []
        try:
            for i in range(self._w.QueryInfoKey(key)[1]):
                try:
                    name, data, _type = self._w.EnumValue(key, i)
                    out.append((name, data))
                except OSError:
                    continue
        finally:
            self._w.CloseKey(key)
        return out

    def value(self, path, name):
        key = self._open(path)
        if key is None:
            return None
        try:
            return self._w.QueryValueEx(key, name)[0]
        except OSError:
            return None
        finally:
            self._w.CloseKey(key)
