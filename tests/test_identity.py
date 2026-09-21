"""Is this machine already in the inventory? (config/identity.py)"""

import pytest

from config.identity import matching_rows, normalise


class Machine:
    """Just enough of a SystemInfoRecord for identity matching."""

    def __init__(self, **values):
        self.values = values

    def get(self, key):
        return self.values.get(key)


ME = Machine(asset_tag="Not Available", computer_name="PC-00123",
             serial_no="5CG0000000", mac_address="7C:2A:31:00:00:01")


def test_matches_on_computer_name():
    assert matching_rows(ME, [{"Computer Name": "PC-00123"}]) == ([2], "Computer Name")


@pytest.mark.parametrize("typed", [
    "PC-00123  ",          # stray spaces
    "'PC-00123",           # leading apostrophe from a text-formatted cell
    "pc-00123",            # different case
    "PC-00123 ",      # non-breaking space from a paste
])
def test_messy_cells_still_match(typed):
    assert matching_rows(ME, [{"Computer Name": typed}]) == ([2], "Computer Name")


def test_falls_back_to_serial_when_the_name_is_blank():
    assert matching_rows(ME, [{"Computer Name": "", "Serial No": "5CG0000000"}]) == ([2], "Serial No")


def test_an_unrelated_machine_matches_nothing():
    assert matching_rows(ME, [{"Computer Name": "PC-99999", "Serial No": "XYZ"}]) == ([], None)


def test_every_duplicate_is_reported():
    rows = [{"Computer Name": "PC-00123"}, {"Computer Name": "PC-00123"}]
    assert matching_rows(ME, rows) == ([2, 3], "Computer Name")


def test_a_shared_dock_mac_never_beats_the_computer_name():
    """Laptops on one docking station report the same MAC; the name must win."""
    rows = [{"Computer Name": "OTHER-PC", "MAC Address": "7C:2A:31:00:00:01"},
            {"Computer Name": "PC-00123"}]
    assert matching_rows(ME, rows) == ([3], "Computer Name")


def test_a_numeric_serial_read_back_as_a_float_still_matches():
    assert normalise("12345.0") == normalise("12345") == "12345"


def test_placeholders_identify_nothing():
    unknown = Machine(asset_tag="Not Available", computer_name="Unknown")
    assert matching_rows(unknown, [{"Asset Tag": "Not Available", "Computer Name": "Unknown"}]) == ([], None)
