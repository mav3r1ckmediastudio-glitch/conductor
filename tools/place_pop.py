# -*- coding: utf-8 -*-
"""
Conductor — Place / Edit Cabinet Tool  v0.4.1
Handles both placing a new cabinet and editing an existing one.
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox,
    QPushButton, QFrame, QMessageBox, QCheckBox, QGroupBox,
)
from qgis.core import (
    QgsFeature, QgsGeometry,
    QgsFeatureRequest,
)
from qgis.gui import QgsMapTool, QgsMapToolEmitPoint
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE, SUBLABEL_STYLE, SECTION_STYLE, MONO_STYLE, CALC_STYLE

RED    = "#C0392B"

# ── HELPERS ───────────────────────────────────────────────────────────────────

def _next_pop_id(layer, area_id):
    existing = set()
    prefix = f"{area_id}-CAB-"
    for feat in layer.getFeatures():
        pid = feat["pop_id"] or ""
        if pid.startswith(prefix):
            try:
                existing.add(int(pid.replace(prefix, "").split("(")[0]))
            except ValueError:
                pass
    n = 1
    while n in existing:
        n += 1
    return f"{prefix}{n:03d}"


def _completion_score(attrs):
    """
    Return (score 0-100, list of missing important fields).
    Used to show how complete a cabinet record is.
    """
    checks = [
        ("pop_name",      "Site name",        True),
        ("pop_type",      "POP type",         False),
        ("operator",      "Operator",         False),
        ("address",       "Address",          False),
        ("postcode",      "Postcode",         False),
        ("power_supply",  "Power supply",     False),
        ("calix_shelves", "Calix shelves",    False),
        ("gpon_cards",    "GPON cards",       False),
        ("gpon_optics",   "GPON optics",      False),
        ("status",        "Status",           False),
    ]
    total   = len(checks)
    missing = []
    score   = 0
    for field, label, required in checks:
        val = attrs.get(field)
        if val is not None and val != "" and val != 0:
            score += 1
        else:
            missing.append((label, required))
    return int(score / total * 100), missing


# ═══════════════════════════════════════════════════════════════════════════
# CABINET FORM
# ═══════════════════════════════════════════════════════════════════════════

class CabinetDialog(QDialog):
    """
    Unified form for placing a new cabinet or editing an existing one.
    Pass existing_feat=None for new placement, or a QgsFeature to edit.
    """

    def __init__(self, point, pop_id, area_id, existing_feat=None, parent=None):
        super().__init__(parent)
        self._point        = point
        self._pop_id       = pop_id
        self._area_id      = area_id
        self._existing     = existing_feat
        self._is_edit      = existing_feat is not None

        title = "Edit Cabinet / POP" if self._is_edit else "Place Cabinet / POP"
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self.setMaximumHeight(750)
        self.setModal(True)
        self._build_ui()

        if self._is_edit:
            self._populate_from_feature(existing_feat)

    # ── WIDGET FACTORIES ──────────────────────────────────────────────────

    def _lbl(self, text):
        l = QLabel(text); l.setStyleSheet(LABEL_STYLE); return l

    def _sublbl(self, text):
        l = QLabel(text); l.setStyleSheet(SUBLABEL_STYLE); return l

    def _section(self, text):
        l = QLabel(text); l.setStyleSheet(SECTION_STYLE); return l

    def _divider(self):
        f = QFrame(); f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"color:{MID}; margin:4px 0px;"); return f

    def _spinbox(self, default=0, lo=0, hi=999):
        s = QSpinBox(); s.setMinimum(lo); s.setMaximum(hi)
        s.setValue(default); s.setStyleSheet(INPUT_STYLE)
        s.setSpecialValueText("—")   # show dash when value is 0
        return s

    def _readonly(self, text="", style=MONO_STYLE):
        e = QLineEdit(str(text)); e.setReadOnly(True); e.setStyleSheet(style)
        return e

    # ── BUILD UI ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # Header
        action = "EDIT" if self._is_edit else "NEW"
        hdr = QLabel(f"  {action}  Cabinet / POP  —  {self._pop_id}")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        # Coordinates / feature ID strip
        if self._point:
            loc = f"  E {self._point.x():.1f}  N {self._point.y():.1f}  (EPSG:27700)"
        else:
            loc = f"  Editing existing feature"
        coords = QLabel(loc)
        coords.setFixedHeight(24)
        coords.setStyleSheet(f"background:{TEAL}; color:{WHITE}; font-size:11px; padding-left:8px;")
        root.addWidget(coords)

        # Completion bar (edit mode only)
        if self._is_edit:
            self._completion_bar = QLabel("  Completion: calculating…")
            self._completion_bar.setFixedHeight(22)
            self._completion_bar.setStyleSheet(
                f"background:{ORANGE}; color:{WHITE}; font-size:11px; padding-left:8px;")
            root.addWidget(self._completion_bar)

        # Scrollable form area
        from qgis.PyQt.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{LIGHT}; border:none;")

        fw = QFrame(); fw.setStyleSheet(f"background:{LIGHT};")
        fl = QVBoxLayout(fw); fl.setContentsMargins(20, 14, 20, 8); fl.setSpacing(8)

        # ── IDENTITY ──────────────────────────────────────────────────────
        fl.addWidget(self._section("IDENTITY"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)

        id_row = QHBoxLayout()
        self._id_display = QLineEdit(self._pop_id)
        self._id_display.setReadOnly(True)
        self._id_display.setStyleSheet(MONO_STYLE)
        id_row.addWidget(self._id_display)
        if not self._is_edit:
            ovr = QPushButton("Override")
            ovr.setStyleSheet(BTN_SECONDARY); ovr.setFixedWidth(80)
            ovr.clicked.connect(self._toggle_id_override)
            id_row.addWidget(ovr)
        f1.addRow(self._lbl("POP ID"), id_row)

        self.pop_name = QLineEdit()
        self.pop_name.setPlaceholderText("e.g. Tyndrum Cabinet 1")
        self.pop_name.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Site Name *"), self.pop_name)

        self.pop_type = QComboBox()
        self.pop_type.addItems(["CABINET", "EXCHANGE", "DATACENTRE", "ROOFTOP"])
        self.pop_type.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("POP Type"), self.pop_type)

        self.operator = QLineEdit("Gigaloch")
        self.operator.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Operator"), self.operator)

        self.status = QComboBox()
        self.status.addItems(["PROPOSED", "SURVEY", "ACTIVE", "DECOMMISSIONED"])
        self.status.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Status"), self.status)

        fl.addLayout(f1)
        fl.addWidget(self._divider())

        # ── LOCATION ──────────────────────────────────────────────────────
        fl.addWidget(self._section("LOCATION"))
        f2 = QFormLayout(); f2.setSpacing(8); f2.setLabelAlignment(Qt.AlignRight)

        self.address = QLineEdit()
        self.address.setPlaceholderText("Street address (optional — fill in later)")
        self.address.setStyleSheet(INPUT_STYLE)
        f2.addRow(self._lbl("Address"), self.address)

        self.postcode = QLineEdit()
        self.postcode.setPlaceholderText("e.g. FK20 8RU  — tab to auto-fill address")
        self.postcode.setMaxLength(8)
        self.postcode.setStyleSheet(INPUT_STYLE)
        self.postcode.editingFinished.connect(self._on_postcode_lookup)
        f2.addRow(self._lbl("Postcode"), self.postcode)

        self.power_supply = QComboBox()
        self.power_supply.addItems(["— not yet set —", "MAINS", "GENERATOR", "UPS", "SOLAR"])
        self.power_supply.setStyleSheet(INPUT_STYLE)
        f2.addRow(self._lbl("Power Supply"), self.power_supply)

        fl.addLayout(f2)
        fl.addWidget(self._divider())

        # ── CALIX EQUIPMENT ───────────────────────────────────────────────
        fl.addWidget(self._section("CALIX EQUIPMENT"))

        note = QLabel(
            "Standard build: 1× DU-X shelf, up to 2× E7-2 shelves, up to 4× GPON cards (2 per shelf), "
            "up to 8× optics per card.\n"
            "Leave at 0 if not yet ordered — you can return to update this later."
        )
        note.setStyleSheet(f"color:{MID}; font-size:10px;")
        note.setWordWrap(True)
        fl.addWidget(note)

        # Equipment grid:  [item] [installed spinbox] [planned spinbox] [capacity label]
        grid = QGridLayout(); grid.setSpacing(8)

        def gh(text, col):
            l = QLabel(text); l.setStyleSheet(SECTION_STYLE); l.setAlignment(Qt.AlignCenter)
            grid.addWidget(l, 0, col)

        gh("",           0)
        gh("Installed",  1)
        gh("Planned",    2)
        gh("Max",        3)

        def grid_row(row, label, sublabel, inst_default, inst_max, planned_max, max_text):
            lbl = QLabel(label); lbl.setStyleSheet(LABEL_STYLE)
            sub = QLabel(sublabel); sub.setStyleSheet(SUBLABEL_STYLE)
            lc  = QVBoxLayout(); lc.setSpacing(0); lc.addWidget(lbl); lc.addWidget(sub)
            lw  = QFrame(); lw.setLayout(lc)
            grid.addWidget(lw, row, 0)

            inst = self._spinbox(inst_default, 0, inst_max)
            grid.addWidget(inst, row, 1)

            plan = self._spinbox(0, 0, planned_max)
            grid.addWidget(plan, row, 2)

            mx = QLabel(max_text); mx.setStyleSheet(SUBLABEL_STYLE); mx.setAlignment(Qt.AlignCenter)
            grid.addWidget(mx, row, 3)
            return inst, plan

        self.dux_inst,    self.dux_plan    = grid_row(1, "DU-X Rectifier", "1 per cabinet standard", 1, 2, 2, "max 2")
        self.calix_inst,  self.calix_plan  = grid_row(2, "Calix E7-2 Shelves", "up to 2", 0, 2, 2, "max 2")
        self.cards_inst,  self.cards_plan  = grid_row(3, "GPON Cards", "2 per shelf, up to 4", 0, 4, 4, "max 4")
        self.optics_inst, self.optics_plan = grid_row(4, "GPON Optics", "8 per card, up to 32", 0, 32, 32, "max 32")
        self.battery_inst,self.battery_plan= grid_row(5, "Battery Sets", "1 per cabinet standard", 1, 4, 4, "—")
        self.patches_inst,self.patches_plan= grid_row(6, "Patch Panels", "", 0, 16, 16, "—")

        fl.addLayout(grid)

        # Live calculated outputs
        calc_row = QHBoxLayout(); calc_row.setSpacing(12)
        calc_row.addWidget(self._sublbl("Max customers (installed optics):"))

        self._max_inst = self._readonly("0", CALC_STYLE)
        self._max_inst.setFixedWidth(80)
        calc_row.addWidget(self._max_inst)

        calc_row.addWidget(self._sublbl("Max customers (planned optics):"))
        self._max_plan = self._readonly("0", CALC_STYLE)
        self._max_plan.setFixedWidth(80)
        calc_row.addWidget(self._max_plan)
        calc_row.addStretch()
        fl.addLayout(calc_row)

        # Connect live calculation
        self.optics_inst.valueChanged.connect(self._recalc)
        self.optics_plan.valueChanged.connect(self._recalc)
        self.cards_inst.valueChanged.connect(self._suggest_optics)
        self.calix_inst.valueChanged.connect(self._suggest_cards)

        # Aggregation router
        self.has_aggreg = QCheckBox("Aggregation router present")
        self.has_aggreg.setStyleSheet(f"font-size:12px; color:{NAVY};")
        fl.addWidget(self.has_aggreg)

        fl.addWidget(self._divider())

        # ── NOTES ─────────────────────────────────────────────────────────
        fl.addWidget(self._section("NOTES"))
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Free text notes — equipment orders, site access, survey findings…")
        self.notes.setStyleSheet(INPUT_STYLE)
        fl.addWidget(self.notes)

        scroll.setWidget(fw)
        root.addWidget(scroll)

        # Buttons
        br = QHBoxLayout(); br.setContentsMargins(20, 12, 20, 16)

        if self._is_edit:
            self._comp_label = QLabel("")
            self._comp_label.setStyleSheet(f"color:{TEAL}; font-size:11px;")
            br.addWidget(self._comp_label)

        br.addStretch()
        cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
        cancel.clicked.connect(self.reject); br.addWidget(cancel)

        save_lbl = "Save Changes" if self._is_edit else "Place Cabinet"
        save = QPushButton(save_lbl); save.setStyleSheet(BTN_PRIMARY)
        save.clicked.connect(self._on_save); br.addWidget(save)
        root.addLayout(br)

    # ── LOGIC ─────────────────────────────────────────────────────────────

    def _on_postcode_lookup(self):
        """Auto-fill address from postcode using postcodes.io."""
        pc = self.postcode.text().strip()
        if not pc or len(pc) < 5:
            return
        try:
            from .postcode_zoom import lookup_postcode
            result = lookup_postcode(pc)
            if result:
                self.postcode.setText(result["postcode"])
                # Only fill address if currently empty
                if not self.address.text().strip():
                    loc = result.get("admin_district","")
                    if loc:
                        self.address.setPlaceholderText(f"e.g. near {loc}")
        except Exception:
            pass  # silently fail — postcode lookup is optional

    def _toggle_id_override(self):
        ro = self._id_display.isReadOnly()
        self._id_display.setReadOnly(not ro)
        self._id_display.setStyleSheet(MONO_STYLE if not ro else INPUT_STYLE)

    def _recalc(self):
        inst = self.optics_inst.value() * 32
        plan = self.optics_plan.value() * 32
        self._max_inst.setText(str(inst))
        self._max_plan.setText(str(plan if plan > inst else inst))
        if self._is_edit and hasattr(self, '_comp_label'):
            self._update_completion_display()

    def _suggest_cards(self):
        """When shelves change, nudge cards max to shelves × 2."""
        shelves = self.calix_inst.value()
        max_cards = shelves * 2
        if self.cards_inst.value() > max_cards:
            self.cards_inst.setValue(max_cards)

    def _suggest_optics(self):
        """When cards change, nudge optics max to cards × 8."""
        cards = self.cards_inst.value()
        max_optics = cards * 8
        if self.optics_inst.value() > max_optics:
            self.optics_inst.setValue(max_optics)

    def _update_completion_display(self):
        attrs = self.get_attributes()
        score, missing = _completion_score(attrs)
        colour = TEAL if score >= 70 else ORANGE if score >= 40 else RED
        if hasattr(self, '_completion_bar'):
            self._completion_bar.setText(f"  Completion: {score}%")
            self._completion_bar.setStyleSheet(
                f"background:{colour}; color:{WHITE}; font-size:11px; padding-left:8px;")
        if hasattr(self, '_comp_label'):
            self._comp_label.setText(f"Record: {score}% complete")
            self._comp_label.setStyleSheet(f"color:{colour}; font-size:11px;")

    def _populate_from_feature(self, feat):
        """Fill form fields from an existing feature."""
        def fv(name, default=""):
            v = feat[name]
            return default if v is None or str(v) == "NULL" else v

        self._id_display.setText(fv("pop_id", self._pop_id))
        self.pop_name.setText(fv("pop_name"))

        idx = self.pop_type.findText(fv("pop_type", "CABINET"))
        if idx >= 0: self.pop_type.setCurrentIndex(idx)

        self.operator.setText(fv("operator", "Gigaloch"))

        idx = self.status.findText(fv("status", "PROPOSED"))
        if idx >= 0: self.status.setCurrentIndex(idx)

        self.address.setText(fv("address"))
        self.postcode.setText(fv("postcode"))

        ps = fv("power_supply", "")
        idx = self.power_supply.findText(ps)
        if idx >= 0: self.power_supply.setCurrentIndex(idx)

        def si(spin, field):
            try: spin.setValue(int(fv(field, 0)))
            except (ValueError, TypeError): pass

        si(self.dux_inst,    "dux_shelves")
        si(self.calix_inst,  "calix_shelves")
        si(self.cards_inst,  "gpon_cards")
        si(self.optics_inst, "gpon_optics")
        si(self.battery_inst,"battery_sets")
        si(self.patches_inst,"patch_panels")

        self.has_aggreg.setChecked(bool(fv("has_aggreg_router", False)))
        self.notes.setText(fv("notes"))
        self._recalc()
        self._update_completion_display()

    def _on_save(self):
        if not self.pop_name.text().strip():
            QMessageBox.warning(self, "Required Field",
                "Site Name is the only required field.\n"
                "All other fields can be filled in later.")
            return

        # Warn (but don't block) if status is ACTIVE but equipment is empty
        if (self.status.currentText() == "ACTIVE"
                and self.optics_inst.value() == 0):
            r = QMessageBox.question(
                self, "Incomplete Equipment",
                "Status is set to ACTIVE but no GPON optics are recorded.\n\n"
                "Save anyway? You can update the equipment details later.",
                QMessageBox.Yes | QMessageBox.No
            )
            if r != QMessageBox.Yes:
                return

        self.accept()

    # ── RESULT ────────────────────────────────────────────────────────────

    def get_attributes(self):
        ps = self.power_supply.currentText()
        if ps.startswith("—"):
            ps = ""
        return {
            "pop_id":            self._id_display.text().strip(),
            "pop_name":          self.pop_name.text().strip(),
            "area_id":           self._area_id,
            "pop_type":          self.pop_type.currentText(),
            "operator":          self.operator.text().strip(),
            "address":           self.address.text().strip(),
            "postcode":          self.postcode.text().strip().upper(),
            "power_supply":      ps,
            "dux_shelves":       self.dux_inst.value(),
            "calix_shelves":     self.calix_inst.value(),
            "gpon_cards":        self.cards_inst.value(),
            "gpon_optics":       self.optics_inst.value(),
            "battery_sets":      self.battery_inst.value(),
            "patch_panels":      self.patches_inst.value(),
            "has_aggreg_router": self.has_aggreg.isChecked(),
            "max_customers":     self.optics_inst.value() * 32,
            "status":            self.status.currentText(),
            "notes":             self.notes.text().strip(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# MAP TOOLS
# ═══════════════════════════════════════════════════════════════════════════

class PlacePOPMapTool(QgsMapToolEmitPoint):
    """Click to place a new cabinet."""

    placed = pyqtSignal(str)

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        # Get the clicked point in the canvas CRS, then transform to EPSG:27700
        from qgis.core import (
            QgsProject, QgsCoordinateTransform,
            QgsCoordinateReferenceSystem,
        )
        canvas_point = self.toMapCoordinates(event.pos())
        canvas_crs = self._canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:27700")

        if canvas_crs != target_crs:
            transform = QgsCoordinateTransform(
                canvas_crs, target_crs,
                QgsProject.instance()
            )
            point = transform.transform(canvas_point)
        else:
            point = canvas_point

        layer = self._project.get_layer("exchange_pops")
        if not layer:
            QMessageBox.critical(None, "Conductor",
                "exchange_pops layer not found. Open a Conductor project first.")
            return

        # Make sure the layer is visible
        tree_layer = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if tree_layer:
            tree_layer.setItemVisibilityChecked(True)

        pop_id = _next_pop_id(layer, self._project.area_id)
        dlg = CabinetDialog(point=point, pop_id=pop_id, area_id=self._project.area_id)

        if dlg.exec_() != QDialog.Accepted:
            return

        attrs = dlg.get_attributes()
        feat  = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(point))
        for fname, val in attrs.items():
            idx = layer.fields().indexOf(fname)
            if idx >= 0:
                feat.setAttribute(idx, val)

        layer.startEditing()
        if layer.addFeature(feat):
            layer.commitChanges()
            layer.triggerRepaint()

            # Zoom to new cabinet — transform back to canvas CRS for extent
            from qgis.core import (
                QgsCoordinateTransform, QgsCoordinateReferenceSystem,
                QgsRectangle,
            )
            canvas_crs = self._canvas.mapSettings().destinationCrs()
            layer_crs  = QgsCoordinateReferenceSystem("EPSG:27700")
            if canvas_crs != layer_crs:
                xform = QgsCoordinateTransform(
                    layer_crs, canvas_crs, QgsProject.instance()
                )
                canvas_pt = xform.transform(point)
            else:
                canvas_pt = point

            rect = QgsRectangle(
                canvas_pt.x() - 200, canvas_pt.y() - 200,
                canvas_pt.x() + 200, canvas_pt.y() + 200,
            )
            self._canvas.setExtent(rect)
            self._canvas.refresh()

            # Flash the feature on the map
            self._canvas.flashFeatureIds(
                layer,
                [f.id() for f in layer.getFeatures()
                 if f["pop_id"] == attrs["pop_id"]],
            )

            self.placed.emit(attrs["pop_id"])
        else:
            layer.rollBack()
            QMessageBox.critical(None, "Error",
                "Failed to write feature to exchange_pops layer.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._canvas.unsetMapTool(self)


class EditPOPMapTool(QgsMapTool):
    """Click an existing cabinet point to edit it."""

    edited = pyqtSignal(str)

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        layer = self._project.get_layer("exchange_pops")
        if not layer:
            return

        # Find feature within ~10 pixels of click
        point  = self.toMapCoordinates(event.pos())
        radius = self._canvas.mapUnitsPerPixel() * 10
        request = QgsFeatureRequest().setFilterRect(
            point.buffer(radius).boundingBox()
        )

        feat = None
        for f in layer.getFeatures(request):
            feat = f
            break

        if feat is None:
            QMessageBox.information(None, "Conductor",
                "No cabinet found at that location.\n"
                "Click closer to a cabinet point, or press Esc to cancel.")
            return

        pop_id  = feat["pop_id"] or "unknown"
        area_id = feat["area_id"] or self._project.area_id

        dlg = CabinetDialog(
            point=None, pop_id=pop_id,
            area_id=area_id, existing_feat=feat
        )

        if dlg.exec_() != QDialog.Accepted:
            return

        attrs = dlg.get_attributes()
        layer.startEditing()
        for fname, val in attrs.items():
            idx = layer.fields().indexOf(fname)
            if idx >= 0:
                layer.changeAttributeValue(feat.id(), idx, val)

        if layer.commitChanges():
            layer.triggerRepaint()
            # Flash the edited feature so it's easy to find
            self._canvas.flashFeatureIds(layer, [feat.id()])
            self.edited.emit(pop_id)
        else:
            layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to save changes.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._canvas.unsetMapTool(self)
