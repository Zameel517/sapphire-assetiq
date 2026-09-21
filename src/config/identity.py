"""
identity.py
===========
Deciding whether a scanned machine is already in the inventory.

Shared by the Google Sheet writer and the Excel writer so both agree on what
"the same machine" means, and so a machine that runs the program twice always
lands on its own row instead of collecting duplicates.

Fields are tried in the order they appear in schema.py (Asset Tag, Computer
Name, Serial No, MAC Address) and the FIRST field that matches any row wins.
The order matters: several laptops sharing one docking station can report the
same MAC address, so the stable, machine-specific fields are tried first.
"""

from config.schema import IDENTITY_CANDIDATES, SCHEMA

# Values that exist in the sheet but identify nothing.
NOT_REAL = {"not available", "unknown", "n/a", "none", ""}


def normalise(value) -> str:
    """Compare-ready form of an identity value.

    Sheets hands back what a person may have typed or pasted: stray spaces, a
    leading apostrophe from a text-formatted cell, a non-breaking space, or a
    serial that looks numeric and comes back as 12345.0. All of those mean the
    same machine, so they must compare equal."""
    text = "" if value is None else str(value)
    text = text.replace(" ", " ").strip()
    text = text.lstrip("'").strip()
    text = " ".join(text.split()).casefold()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def identity_values(record) -> dict:
    """This machine's usable identity values, header -> value, in match order."""
    values = {}
    for key in IDENTITY_CANDIDATES:
        spec = next(s for s in SCHEMA if s.key == key)
        value = record.get(key)
        if normalise(value) not in NOT_REAL:
            values[spec.header] = value
    return values


def matching_rows(record, existing_rows: list) -> tuple:
    """Rows that are this machine: (list of 1-indexed rows, which field matched).

    Row numbering matches the sheet, so 2 is the first data row. More than one
    row coming back means the inventory already holds duplicates of this
    machine -- the caller updates the first and reports the rest."""
    for header, value in identity_values(record).items():
        wanted = normalise(value)
        hits = [i for i, row in enumerate(existing_rows, start=2)
                if normalise(row.get(header, "")) == wanted]
        if hits:
            return hits, header
    return [], None


def describe(record) -> str:
    """The identity values a failed match was looking for, for the log."""
    values = identity_values(record)
    return ", ".join(f"{h}={v!r}" for h, v in values.items()) or "no usable identity value"
