# Conductor — Development To-Do List
*Last updated: June 2026 (v1.2.0 session)*

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
- [ ] Undo / Redo manager (Ctrl+Z for all placement tools)
- [ ] Optical schematic view (QGraphicsView fibre topology diagram)
- [ ] Fibre slack tracking per chamber/joint
- [ ] Refactor tools into manager classes (LayerManager, IDManager, SnappingManager)
- [ ] Plugin Reloader compatibility (dev workflow)
- [ ] Broader unit tests for ID generation and topology rules

### Bug fixes (v1.2.0 session)
- [x] validate_routes.py — `trace_premises()` didn't resolve PIA_AERIAL_DROP drop ducts (from_pole set, from_chamber empty); now finds the CBT joint mounted on that pole. Fixes "no drop_duct" PARTIAL errors for premises connected via aerial drops from CBTs.
- [x] place_pop.py `EditPOPMapTool.canvasReleaseEvent` — `point.buffer(radius)` called on a `QgsPointXY` (no such method); now wraps in `QgsGeometry.fromPointXY(...)` first.
- [x] place_pop.py `EditPOPMapTool.canvasReleaseEvent` — click point wasn't transformed from canvas CRS (commonly EPSG:3857) to the layer's EPSG:27700 before filtering, so "Edit Cabinet/POP" could never find a cabinet. Now transforms first, same pattern as edit_assets.py's `_find_feature`.

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

## 💡 IDEAS / FUTURE
- [ ] PostGIS backend option (multi-user concurrent access)
- [ ] QField integration for field survey capture
- [ ] Auto-generate fibre assignments from cable + joint data
- [ ] Network coverage heatmap (homes passed vs premises layer)
- [ ] Take-up tracker (demand_tier + registered vs connected)
- [ ] Export to KMZ for sharing with non-GIS stakeholders