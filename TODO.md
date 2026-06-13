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

## 💡 IDEAS / FUTURE
- [ ] PostGIS backend option (multi-user concurrent access)
- [ ] QField integration for field survey capture
- [ ] Auto-generate fibre assignments from cable + joint data
- [ ] Network coverage heatmap (homes passed vs premises layer)
- [ ] Take-up tracker (demand_tier + registered vs connected)
- [ ] Export to KMZ for sharing with non-GIS stakeholders
