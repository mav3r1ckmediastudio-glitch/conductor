# Conductor — Development To-Do List
*Last updated: June 2026*

---

## 🔧 TOOLS — Core Design (in progress)
- [x] Draw Build Area
- [x] Place Cabinet / POP
- [x] Edit Cabinet / POP
- [x] Place Chamber
- [x] Digitise Duct
- [x] Place Joint (with optional splitter)
- [x] Digitise Fibre Cable
- [x] Digitise Drop Cable
- [x] Delete Asset
- [x] Move Asset (with auto-renumber chambers)
- [x] Import Premises (OS AddressBase CSV)
- [ ] Renumber Chambers tool (standalone, post cabinet move)
- [ ] Edit Chamber
- [ ] Edit Duct
- [ ] Edit Joint
- [ ] Edit Fibre Cable
- [ ] Edit Drop Cable

---

## 🔧 TOOLS — Fibre & Network
- [ ] Fibre Assignments (per-tube/fibre role assignment UI)
- [ ] Fibre Trace (premises → joint → cable → joint → cabinet)
- [ ] Fibre Count Calculator (Calix cabinet calculator logic)
- [ ] Validate Relationships (FK checker across all layers)

---

## 🔧 TOOLS — Build & Reporting
- [ ] Add Build Task
- [ ] Generate Job Pack (PPTX — Gigaloch template)
- [ ] BDUK Export (homes passed / connected report)
- [ ] BOM Export (Bill of Materials — chambers, duct lengths, cable, splitters)
- [ ] Cabinet Cost Calculator

---

## 🔧 TOOLS — PIA (Phase 2)
- [ ] Place Pole
- [ ] Digitise PIA Aerial Route
- [ ] Digitise PIA Subduct Route
- [ ] PIA Order Reference management

---

## 🏗️ ARCHITECTURE & QUALITY
- [ ] Undo / Redo manager (Ctrl+Z for all placement tools)
- [ ] Optical schematic view (QGraphicsView fibre topology diagram)
- [ ] Fibre slack tracking per chamber/joint
- [ ] Refactor tools into manager classes (LayerManager, IDManager, SnappingManager)
- [ ] Plugin Reloader compatibility (dev workflow)
- [ ] Unit tests for ID generation and topology rules

---

## 📐 DATA MODEL
- [ ] Update plugin schema to v0.5 (joints replacing splitters) ✓ done in v0.7.0
- [ ] fibre_assignments layer population tool
- [ ] QField compatibility review (field survey workflow)

---

## 🐛 KNOWN ISSUES / POLISH
- [ ] Chamber type dropdown still shows old values on existing projects (pre v0.6.1)
- [ ] Build Area filter in Import Premises — verify fix working in v0.6.4
- [ ] Conductor panel title shows area_id not project name on re-open
- [ ] No confirmation when closing QGIS with unsaved Conductor edits

---

## 🛠️ MIGRATION — v1.0.1 (run once per existing GeoPackage, e.g. SCOT-222.gpkg)

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

Note: any PIA UG ducts already digitised before v1.0.1 will have
duct_type='PIA_UG' and empty from_node/to_node. Re-saving them via Edit
Asset will currently reset duct_type to 'SHOTGUN' (the v1.0.1 fix stops
this for *new* features, but pre-existing 'PIA_UG' rows should be bulk
-updated, e.g. `UPDATE ducts SET duct_type='PIA_SUBDUCT' WHERE duct_type='PIA_UG';`,
and from_node/from_node_type/to_node/to_node_type re-populated manually
from the duct geometry endpoints if needed).

---

## 💡 IDEAS / FUTURE
- [ ] PostGIS backend option (multi-user concurrent access)
- [ ] QField integration for field survey capture
- [ ] Auto-generate fibre assignments from cable + joint data
- [ ] Network coverage heatmap (homes passed vs premises layer)
- [ ] Take-up tracker (demand_tier + registered vs connected)
- [ ] Export to KMZ for sharing with non-GIS stakeholders
