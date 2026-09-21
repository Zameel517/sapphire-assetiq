"""The 28-field contract (config/schema.py) and the drawn icon (gui/icon.py)."""

from config.schema import HEADERS, IDENTITY_CANDIDATES, SCHEMA
from gui.icon import ico_bytes, png_bytes


def test_schema_has_28_unique_fields():
    assert len(SCHEMA) == 28
    assert len(set(HEADERS)) == 28


def test_email_server_was_dropped():
    assert "Email Server" not in HEADERS


def test_identity_is_tried_in_a_fixed_order():
    assert IDENTITY_CANDIDATES == ["asset_tag", "computer_name", "serial_no", "mac_address"]


def test_icon_renders_a_valid_png():
    data = png_bytes(32)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_icon_file_holds_every_requested_size():
    data = ico_bytes((16, 32, 48))
    assert data[:4] == b"\x00\x00\x01\x00"
    assert int.from_bytes(data[4:6], "little") == 3
