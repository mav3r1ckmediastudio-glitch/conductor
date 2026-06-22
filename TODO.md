# Conductor — Development To-Do List
*Last updated: 20 June 2026 (v2 — fibre-assignment stability session)*

---

## 🔧 TOOLS — Core Design
- [x] Draw Build Area
- [x] Place Cabinet / POP
- [x] Edit Cabinet / POP
- [x] Place Chamber
- [x] Digitise Duct
- [x] Place Joint (with optional splitter)
- [x] Digitise Fibre Cable
- [x] Digitise Drop Cable
- [x] Delete Asset (select_delete.py)
- [x] Move Asset (with auto-renumber chambers)
- [x] Import Premises (OS AddressBase CSV)
- [x] Edit Chamber / Duct / Joint / Fibre Cable / Drop Cable / Bundle / Cabinet-POP — unified Edit Asset tool (edit_assets.py)
- [x] Digitise Road Crossing / Digitise Stream Crossing — thin Digitise Duct wrappers, surface_type locked to ROAD/WATERCOURSE — digitise_road_crossing.py / digitise_stream_crossing.py
- [x] Duct sleeve (scaffold bar) tracking — sleeve_type/sleeve_length_m fields + BoM line item
- [ ] Renumber Chambers tool (standalone, post cabinet move)

---

## 🔧 TOOLS — Fibre & Network
- [x] Fibre Assignments (per-tube/fibre role assignment UI) — fibre_assign.py
- [x] Fibre Trace (premises → joint → cable → joint → cabinet) — fibre_trace.py
- [x] Fibre Count Calculator (Calix cabinet calculator logic) — fibre_count.py
- [x] Validate Fibre Routes — validate_routes.py
- [ ] Validate Relationships (FK checker across all layers) — confirm whether validate_routes.py already covers this, or if it's route-geometry-only and a separate FK checker is still needed

---

## 🔧 TOOLS — Build & Reporting
- [x] BOM Export (Bill of Materials — chambers, duct lengths, cable, splitters, Excel export) — bom.py
- [x] Single Line Diagram generator — sld.py
- [x] Splice Plan Export (HTML) — splice_plan.py
- [x] Route / Splice Export — route_splice_export.py
- [x] Cabinet Cost Calculator (cabinet_cost.py) — equipment cost from cabinet's own DUX/Calix/GPON/battery counts (real Gigaloch unit prices) + civils/cable BoM rollup per area, project grand total

---

## 🔧 TOOLS — PIA
- [x] Place Pole — place_pole.py
- [x] Place CBT — place_cbt.py
- [x] Place PIA UG Chamber (incl. surface_type, v1.0.1) — place_pia_chamber.py
- [x] Digitise PIA UG Duct / Subduct Route (v1.0.1 schema fixes) — digitise_pia_ug_duct.py
- [x] Digitise PIA UG Drop — digitise_pia_ug_drop.py
- [x] Digitise PIA Aerial Span — digitise_aerial_span.py
- [x] Digitise PIA Aerial Drop — digitise_aerial_drop.py
- [x] Digitise Bundle — digitise_bundle.py
- [ ] PIA Order Reference management (pia_ref/openreach_ref fields exist on schema, but no dedicated management UI)

---

## 🔧 TOOLS — Utility
- [x] Postcode Zoom — postcode_zoom.py

---

## 🏗️ ARCHITECTURE & QUALITY
- [x] Schema-contract static test (tests/test_schema_contract.py, v1.0.1) — guards tool attribute dicts against LAYER_SCHEMA drift
- [x] Undo / Redo manager (Ctrl+Z / Ctrl+Shift+Z, 5 levels, covers place/delete/move/edit) — conductor_utils.py UndoStack, conductor_dockwidget.py QShortcut
- [x] Staged tool unlock — tools unlock progressively as premises/build area/cabinet are created. State derived from gpkg ground truth on every open (crash-resilient).
- [x] Cookie-cutter clip — premises outside build area polygon automatically deleted when build area is drawn.
- [x] Splitter integrity warning — edit-time and validation-time check for joints with >1 downstream connection but no splitter declared.
- [x] 1:4 × 1:8 splitter chain enforcement — route validator checks every ROUTED premises has exactly a 1:8 (distribution) and 1:4 (spine) splitter in correct order.
- [x] CBT tail 500m warning — non-blocking warning if tail exceeds 500m.
- [x] Sticky, freeze-aware fibre port allocation — Auto-Assign Fibres persists splitter ports (`splitter_port` on bundles/drop_ducts, `feeder_port` on joints) so re-running no longer reshuffles existing customers when premises/cables change. INSTALLED/LIVE assignments are frozen; new consumers fill the lowest free ports. Shared `sticky_allocate()` serves both terminal (Stage 2) and feeder (Stage 1) allocation. Verified on CH33 (234 records; first run reproduces the prior assignment exactly).
- [x] Splitter topology drift report (validate-only) — `tools/splitter_topology.py` derives splitter presence + role (feeder/terminal) from network structure and flags drift vs declared `has_splitter`/`split_ratio` (stale ticks, missing ticks, oversubscription, feeder-ratio mismatch) as issue rows in the validation dock. Declared fields stay the source of truth; supersedes the cruder downstream-paths stub in `run_validation_headless`.
- [x] **Network/FK integrity validator** (Phase 1) — `tools/validate_integrity.py` checks every cross-layer reference resolves to a real feature (typed `from_node`/`to_node`, `from_chamber`, `bundle_id`, `splitter_id`/`cable_id` splitter pseudo-ids, pole refs). Understands the model's legitimate overloads: `from_chamber`→chamber|CBT-joint, `bundle_id`→bundle|ddct|joint, `-SP`→splitter set, and poles stored as `PIA_POLE` chambers. Runs headless (`run_integrity_check_headless()`), wired into the validation dock as a "Network Integrity" row that runs on every refresh; broken links open a detail popup with zoom-to-feature. Negative-tested + regression test `tests/test_integrity_validator.py` (2/2). Verified clean on CH33 (1,978 refs, 0 orphans).
- [ ] Splitter drift parity — the Validate Routes *dialog* still runs the old downstream-paths stub; point it at `splitter_drift_issues()` to match the validation dock.
- [ ] Through-splice carry-fibre ordering at a shared CBT attach joint is still sort-positional — the last non-sticky spot in fibre_assign Stage 1.
- [ ] Splitter topology derive-and-write — optionally promote the validate-only drift report to write `has_splitter`/`split_ratio`/`cascade_level`/`cascade_type` back to joints, keeping all downstream tools (BoM, SLD, splice plan, styling) consistent. Needs `cascade_level`/`cascade_type` handling.
- [ ] Optical schematic view (QGraphicsView fibre topology diagram)
- [ ] Fibre slack tracking per chamber/joint
- [ ] Refactor tools into manager classes (LayerManager, IDManager, SnappingManager)
- [ ] Plugin Reloader compatibility (dev workflow)
- [ ] Broader unit tests for ID generation and topology rules

### Bug fixes (v1.0.2 session — 18 June 2026)
- [x] PyQt/SIP GC bug — map tools created as local variables were garbage-collected immediately after _run_map_tool() returned, leaving a dead tool with no cursor. Fixed: self._active_map_tool = tool holds strong reference.
- [x] Edit Joint dialog auto-sizing — three competing resize attempts fired before Qt laid out the scroll area. Fixed: single deferred resize via showEvent + QTimer.singleShot(0).
- [x] Ctrl+Z not firing — keyPressEvent on dockwidget intercepted by QGIS. Fixed: QShortcut with Qt.ApplicationShortcut context.
- [x] LAYER_ID_FIELDS → ID_FIELDS in select_delete.py undo push.
- [x] from_chamber resolution in splitter integrity check — CBT aerial drops store joint_id directly in from_chamber; UG drops store chamber_id. Both cases now handled correctly.
- [x] Build area accidentally deletable via delete tool — excluded from SEARCHABLE_LAYERS (covers both delete and move tools).

### Bug fixes (v1.2.0 session)
- [x] validate_routes.py — `trace_premises()` didn't resolve PIA_AERIAL_DROP drop ducts (from_pole set, from_chamber empty); now finds the CBT joint mounted on that pole. Fixes "no drop_duct" PARTIAL errors for premises connected via aerial drops from CBTs.
- [x] place_pop.py `EditPOPMapTool.canvasReleaseEvent` — `point.buffer(radius)` called on a `QgsPointXY` (no such method); now wraps in `QgsGeometry.fromPointXY(...)` first.
- [x] place_pop.py `EditPOPMapTool.canvasReleaseEvent` — click point wasn't transformed from canvas CRS (commonly EPSG:3857) to the layer's EPSG:27700 before filtering, so "Edit Cabinet/POP" could never find a cabinet. Now transforms first, same pattern as edit_assets.py's `_find_feature`.

### Bug fixes (v2 session — 20 June 2026)
- [x] Auto-Assign Fibres reshuffled existing customer ports when premises were added or removed (sort-positional allocation). Fixed via sticky port allocation (see Architecture).
- [x] Conductor toolbar toggle and the main dock's X button left the Validation and Routes docks orphaned on screen. Fixed: `_toggle_dockwidget` and `ConductorDockWidget.closeEvent` now hide/show all three docks together.

---

## 📐 DATA MODEL
- [x] v0.4 data model (ducts + fibre_cables as separate layers, shotgun/PIA/drop_duct_type, DUCT-NNN IDs) — done v0.3.0
- [x] surface_type added to chambers schema (v1.0.1) — migration applied to SCOT-222.gpkg
- [ ] fibre_assignments layer population tool — confirm whether fibre_assign.py already populates this layer, or if a separate population step is still needed
- [ ] QField compatibility review (field survey workflow)

---

## 🛠️ MIGRATION — v1.0.1 (run once per existing GeoPackage)

v1.0.1 adds one new column to the `chambers` table: `surface_type` (TEXT),
used by "Place PIA UG Chamber". New projects get it automatically. For
**existing** GeoPackages, run this once (e.g. via the QGIS Python console
with the layer closed, or `ogrinfo`/`spatialite_gui`):

```sql
ALTER TABLE chambers ADD COLUMN surface_type TEXT;
```

Until this is run, "Place PIA UG Chamber" still works — it now logs a
warning to the Conductor log panel (Plugins ▸ Conductor) instead of
silently discarding the Surface Type value, so the gap is visible rather
than invisible.

No other v1.0.1 changes require a schema migration: the PIA UG Duct and
drop-duct fixes only changed *which existing columns* (`from_node`/
`to_node`/`from_node_type`/`to_node_type`/`duct_type`, `from_pole`) are
populated — those columns already exist in the v0.4 schema.

**Status: applied to SCOT-222.gpkg.**

Note: any PIA UG ducts already digitised before v1.0.1 will have
duct_type='PIA_UG' and empty from_node/to_node. Re-saving them via Edit
Asset will currently reset duct_type to 'SHOTGUN' (the v1.0.1 fix stops
this for *new* features, but pre-existing 'PIA_UG' rows should be bulk
-updated, e.g. `UPDATE ducts SET duct_type='PIA_SUBDUCT' WHERE duct_type='PIA_UG';`,
and from_node/from_node_type/to_node/to_node_type re-populated manually
from the duct geometry endpoints if needed).

---

## 🛠️ MIGRATION — v1.0.2 (run once per existing GeoPackage)

v1.0.2 adds two new columns to the `ducts` table: `sleeve_type` (TEXT) and
`sleeve_length_m` (REAL), used by Digitise Duct's new Sleeve field (and by
Digitise Road/Stream Crossing, which are Digitise Duct wrappers). New
projects get these automatically. For **existing** GeoPackages, run once:

```sql
ALTER TABLE ducts ADD COLUMN sleeve_type TEXT;
ALTER TABLE ducts ADD COLUMN sleeve_length_m REAL;
```

**Status: applied to SCOT-222.gpkg.**

---

## 🛠️ MIGRATION — v2 (auto-applied on project open)

v2 adds sticky-port columns: `splitter_port` (INTEGER) on `bundles` and
`drop_ducts`, and `feeder_port` (INTEGER) on `joints`. These let Auto-Assign
Fibres remember which port each premises / child splitter sits on, so
re-running never reshuffles existing customers.

New projects get the columns from the template. For **existing** GeoPackages,
`ensure_port_schema()` (project_manager.py) adds any missing columns
automatically when the project is opened — no manual SQL required. Equivalent
statements if ever needed:

```sql
ALTER TABLE bundles    ADD COLUMN splitter_port INTEGER;
ALTER TABLE drop_ducts ADD COLUMN splitter_port INTEGER;
ALTER TABLE joints     ADD COLUMN feeder_port   INTEGER;
```

Until the columns exist the new code degrades gracefully (assignment still
works, just non-sticky) and logs a hint.

**Status: applied to CH33.gpkg; auto-applies on open for all other projects.**

---

## 💡 IDEAS / FUTURE
- [ ] PostGIS backend option (multi-user concurrent access)
- [ ] QField integration for field survey capture
- [ ] Auto-generate fibre assignments from cable + joint data
- [ ] Network coverage heatmap (homes passed vs premises layer)
- [ ] Take-up tracker (demand_tier + registered vs connected)
- [ ] Export to KMZ for sharing with non-GIS stakeholders
## Design Decisions

### Splitter fibre consumption (fibre_assign.py)
Splitters consume fibres as follows:
- **F1** = splitter input (the single incoming fibre)
- **F2 onwards** = splitter port outputs (one per port)
- A **1:4** consumes 5 fibres total (F1 input + F2–F5 ports)
- A **1:8** consumes 9 fibres total (F1 input + F2–F9 ports)
- Onward through-splices start at the next fibre after the last port

This matches physical splitter behaviour where input and outputs are distinct fibre positions.

