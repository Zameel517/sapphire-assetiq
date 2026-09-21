"""Company, Location and Asset Tag, resolved at run time (collectors/organization_collector.py)."""

import pytest

from collectors import organization_collector as org
from models.system_info import SystemInfoRecord

SITES = {"vlan_location_map": {"10.20.30.": "Head Office"}}


def machine(ip="10.20.30.15", name="PC-00123", firmware="Not Available", status="missing", domain=None):
    record = SystemInfoRecord()
    record.set("ip_address", ip, source="test")
    record.set("subnet", "255.255.255.0", source="test")
    record.set("computer_name", name, source="test")
    record.set("asset_tag", firmware, source="test", status=status)
    if domain:
        record.set("domain_name", domain, source="test")
    return record


@pytest.mark.parametrize("ip, site", [
    ("10.20.30.15", "Head Office"),
    ("10.20.30.250", "Head Office"),
    ("10.20.31.15", "Unknown"),
    ("192.168.1.20", "Unknown"),
])
def test_location_comes_from_the_vlan(ip, site):
    record = machine(ip=ip)
    org._collect_location(record, SITES, {})
    assert record.get("location") == site


def test_an_unlisted_vlan_is_flagged_not_guessed():
    record = machine(ip="10.20.31.15")
    org._collect_location(record, SITES, {})
    assert record.fields["location"].status == "review"


@pytest.mark.parametrize("name, tag", [
    ("PC-00123", "PC-00123"),
    ("comp001234", "COMP001234"),
    ("FRF-55", "FRF-55"),
])
def test_asset_tag_falls_back_to_the_computer_name(name, tag):
    record = machine(name=name)
    org._collect_asset_tag(record, {})
    assert record.get("asset_tag") == tag


def test_a_real_firmware_tag_wins():
    record = machine(firmware="TAG-777", status="ok")
    org._collect_asset_tag(record, {})
    assert record.get("asset_tag") == "TAG-777"


@pytest.mark.parametrize("domain, company", [
    ("CONTOSO.local", "CONTOSO"),
    ("CONTOSO.store", "CONTOSO"),
    ("Workgroup", None),
])
def test_company_derives_from_the_domain(domain, company):
    assert org._company_from_domain(machine(domain=domain)) == company
