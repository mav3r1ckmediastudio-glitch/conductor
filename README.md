# Conductor

**FTTP Network Design Plugin for QGIS** — built for [Gigaloch](https://gigaloch.co.uk), Scotland's vertically integrated rural fibre ISP.

Conductor stores an entire FTTP network design — from cabinet to customer — in a single portable GeoPackage file, and provides map-based tools for every stage of the design process: drawing ducts and chambers, placing joints and splitters, importing premises, validating fibre routes, assigning fibre numbers, and generating engineer-ready splice plans.

## Status

**v2.0.0** — Active development (experimental). The civil, fibre, PIA/aerial design, validation, and reporting tools are complete and verified against the CH3 / TARVIN test project (TARVIN VILLAGE 002, `CH33.gpkg`, area `ENG-CH3`). A two-gate CI contract suite (schema + network integrity) runs on every push. See [`TODO.md`](TODO.md) for the full feature list and roadmap.

### Scope — what Conductor does today

Conductor is a **design and fibre-planning** tool: build-area planning, passive infrastructure (ducts, chambers, poles, PIA and aerial), a cascade-aware fibre-assignment engine, optical-budget and route validation, network/FK integrity checking, and engineer-ready outputs (Bill of Materials, splice plan, single-line diagram).

### Planned — not yet implemented

The following **lifecycle** capabilities are deliberately out of scope for now and will be revisited only once there is a robust, release-ready V1 of the core design engine. The relevant layers exist in the schema and appear in the layer tree marked **(planned)**, but no tools populate them yet:

- **Survey** — field survey capture
- **Wayleave** — wayleave tracking and consent management
- **Build progress** — build task tracking
- **Customer connection** — customer records and connection status
- Field round-trip (QField / mobile) and a persisted as-built / digital-twin layer

Conductor today is a strong design & fibre-planning tool; it is not yet a survey/wayleave/build/customer lifecycle tool, and the documentation no longer claims otherwise.

## Requirements

- QGIS 3.22+
- Python 3.12
- GeoPackage storage, EPSG:27700 (British National Grid)

## Installation

1. Download or clone this repository
2. Copy the `conductor` folder into your QGIS plugins directory:
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
3. Restart QGIS (or use **Plugin Reloader**) and enable Conductor via **Plugins → Manage and Install Plugins**

## What's included

| Area | Tools |
|---|---|
| **Civil** | Draw Build Area, Place Cabinet/POP, Place Chamber, Digitise Duct, Edit/Delete/Move Asset |
| **Fibre** | Place Joint, Digitise Cable, Digitise Bundle, Assign Fibre Roles, Fibre Trace, Fibre Count Calculator |
| **PIA & Aerial** | Place Pole, Place CBT, Digitise PIA Aerial Route, Digitise PIA Subduct Route |
| **Premises** | Import Premises (OS AddressBase CSV), Postcode Zoom |
| **Analysis & Reporting** | Validate Fibre Routes, Splice Plan Export, Route Splice Export, Bill of Materials, Single Line Diagram |

## Documentation

The full user manual is in [`docs/conductor_manual.html`](docs/conductor_manual.html) — open it in a browser for a complete reference covering installation, key concepts, every tool, ID naming conventions, topology rules, and the roadmap.

## Architecture

All shared utilities (colour constants, IEC 60794 fibre colour tables, layer lookup, geometry/numbering helpers, snapping, write-safety context managers) live in `conductor/conductor_utils.py`. Tool files import from here — see the manual's Topology Rules and ID Naming sections for conventions.

## Designed for Gigaloch's build standard

All naming conventions, splitter cascades, and cable types reflect Gigaloch's real-world network design practices. The 1:4 + 1:8 splitter cascade gives an effective 1:32 split per GPON port on the Calix E7-2 cabinet.

## Licence

Proprietary — Mav3r1ck Media Studio / Gigaloch. Not for redistribution.
