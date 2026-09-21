# Changelog

All notable changes to Sapphire AssetIQ. Version 1.0.0 is the first production release; the
sections below record how it was built, because the interesting decisions happened on the way.

## [1.0.0] — 2026-09-17

First production release, approved for fleet-wide deployment.

### Added
- 28-field inventory record per machine, written as one row into a central Google Sheet.
- Upsert by identity (Asset Tag → Computer Name → Serial No → MAC Address) so a machine scanned
  again updates its own row, with a second check immediately before inserting to rule out a
  duplicate when two runs overlap.
- Location resolved at run time from the VLAN of the machine's own IP; an unlisted VLAN reports
  `Unknown` for review rather than guessing a neighbouring site.
- Asset Tag taken from firmware when it is real, otherwise from the computer name — no naming
  pattern assumed, because the fleet's asset codes are not all one shape.
- Single-file EXE for Active Directory deployment: runs in the background with no window, no
  console and nothing staged on the machine.
- Optional window (`--window`) and console mode (`--cli`) for testing and hand-running.
- Google Sheet formatting applied on every write: frozen header, per-column alignment and number
  formats, fitted widths, banded rows, filter row, and yellow/red highlighting for values a human
  needs to look at. Idempotent — 500 machines never stack duplicate banding.

### Changed
- **Sheets only.** The local Excel and JSON writers were removed at the customer's request: no
  output folder is created on endpoints, and the sheet is the single record. One small log per run
  remains under `%LOCALAPPDATA%`.
- Email Server was dropped from the schema (29 → 28 fields). It carried product labels rather than
  a fact about the machine and confused the sheet more than it helped.
- The window is off by default, because Active Directory runs this and nothing should appear on a
  user's screen.

### Fixed
- **"Scan again" returned empty fields.** WMI connections are COM objects bound to the thread that
  created them, and the window scans on a fresh thread every time; the cached connections failed
  there. Connections are now per-thread, and a scan thread only shuts COM down once every object it
  created has been released — doing it earlier caused an access violation at exit in every test run.
- Laptops with a large external monitor were classified as desktops; display size now prefers the
  built-in panel, and external monitors are reported separately.
- Lenovo machines all collided on one row, because their firmware asset tag reads
  "No Asset Information" — placeholder tags are now rejected as identities.

## Development phases

The work before 1.0.0, in order. Nothing here was released; it is recorded because each phase
changed the design.

**Phase 1 — Match the real data, not an idea of it.** The schema was rebuilt against an actual
audit export rather than a hypothetical spec, which corrected several field formats and revealed
that the firmware Asset Tag is empty fleet-wide.

**Phase 2 — Collectors and the central sheet.** One collector per domain, each failure-isolated, and
the first Sheets upsert. Identity matching was added the first time two different machines landed on
one row.

**Phase 3 — A real interface.** A Tkinter window replaced the console: live progress, per-field
status, data-quality score. The sheet link was deliberately removed from it — sheet access is
granted separately by IT.

**Phase 4 — Deployment shape.** A single-file EXE, because the alternative was staging a folder on
every machine before Active Directory could run it. Config and credentials are built in, with files
beside the EXE overriding them.

**Phase 5 — Reliability under real use.** Repeat scans, overlapping runs, read-only shares and
machines that fail mid-scan. Most of the fixes in this release came from this phase.

**Phase 6 — Getting out of the way.** Hidden PowerShell calls, no console windows, background by
default, and guidance for the SmartScreen prompt that unsigned executables trigger.

**Phase 7 — Product identity.** Renamed to Sapphire AssetIQ, with the brand's real logo imported
from vector artwork and filled in code at any size. (This public repository ships a neutral mark in
place of the official logo.)
