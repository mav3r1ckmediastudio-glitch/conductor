# -*- coding: utf-8 -*-
"""
Conductor — Digitise Duct Tool
Draw a duct line between two nodes (chambers, poles, or cabinet).
Auto-assigns DUCT-NNN ID based on compass leg from cabinet.
Auto-calculates length from digitised geometry.
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QFrame, QMessageBox, QScrollArea, QCheckBox,
)
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeatureRequest, QgsDistanceArea, QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE, MONO_STYLE, CALC_STYLE
from ..conductor_utils import compass_quadrant, line_length_m, snap_to_node

# ── NUMBERING HELPERS ─────────────────────────────────────────────────────────

LEG_BASE = {"N": 1, "S": 100, "E": 200, "W": 300}
LEG_MAX  = {"N": 99, "S": 199, "E": 299, "W": 399}


def _compass_leg(midpoint, cabinet_pt):
    return compass_quadrant(cabinet_pt, midpoint)


def _next_duct_id(layer, area_id, leg, spur_suffix=""):
    """Find next available duct sequence number for this leg."""
    base    = LEG_BASE[leg]
    maximum = LEG_MAX[leg]
    existing = set()
    prefix = f"{area_id}-DUCT-"

    for feat in layer.getFeatures():
        did = feat["duct_id"] or ""
        if not did.startswith(prefix):
            continue
        seq = feat["duct_seq"]
        if seq and base <= seq <= maximum:
            existing.add(seq)

    n = base
    while n in existing and n <= maximum:
        n += 1

    if n > maximum:
        raise ValueError(f"No available duct numbers for leg {leg}")

    suffix = f"({spur_suffix})" if spur_suffix else ""
    return f"{prefix}{n:03d}{suffix}", n


def _calc_length(points):
    return line_length_m(points)


def _get_cabinet(project):
    """Return the cabinet feature for this build area."""
    pop_layer = project.get_layer("exchange_pops")
    if not pop_layer:
        return None, None
    for feat in pop_layer.getFeatures():
        if feat["area_id"] == project.area_id:
            return feat, feat.geometry().asPoint()
    return None, None


def _snap_to_node(canvas, project, canvas_pos, snap_radius_px=14):
    return snap_to_node(canvas, project, canvas_pos,
        [("chambers", "chamber_id", "CHAMBER"),
         ("poles", "pole_id", "POLE"),
         ("exchange_pops", "pop_id", "POP")],
        snap_radius_px=snap_radius_px)


# ═══════════════════════════════════════════════════════════════════════════
# DUCT FORM
# ═══════════════════════════════════════════════════════════════════════════

class DigitiseDuctDialog(QDialog):

    def __init__(self, duct_id, duct_seq, compass_leg, area_id, pop_id,
                 from_node, from_node_type, to_node, to_node_type,
                 length_m, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Digitise Duct")
        self.setMinimumWidth(500)
        self.setMaximumHeight(720)
        self.setModal(True)

        self._duct_id       = duct_id
        self._duct_seq      = duct_seq
        self._compass_leg   = compass_leg
        self._area_id       = area_id
        self._pop_id        = pop_id
        self._from_node     = from_node
        self._from_node_type= from_node_type
        self._to_node       = to_node
        self._to_node_type  = to_node_type
        self._length_m      = length_m
        self._build_ui()

    def _lbl(self, t):
        l = QLabel(t); l.setStyleSheet(LABEL_STYLE); return l

    def _section(self, t):
        l = QLabel(t); l.setStyleSheet(SECTION_STYLE); return l

    def _divider(self):
        f = QFrame(); f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"color:{MID}; margin:4px 0px;"); return f

    def _ro(self, text, style=MONO_STYLE):
        e = QLineEdit(str(text)); e.setReadOnly(True); e.setStyleSheet(style)
        return e

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr = QLabel(f"  Digitise Duct  —  {self._duct_id}")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        leg_names = {"N":"North leg","S":"South leg","E":"East leg","W":"West leg"}
        sub = QLabel(
            f"  {leg_names.get(self._compass_leg,'')}  ·  "
            f"Length: {self._length_m} m  ·  "
            f"{self._from_node_type}: {self._from_node}  →  "
            f"{self._to_node_type}: {self._to_node}"
        )
        sub.setFixedHeight(24)
        sub.setStyleSheet(f"background:{TEAL}; color:{WHITE}; font-size:11px; padding-left:8px;")
        root.addWidget(sub)

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
        self._id_display = QLineEdit(self._duct_id)
        self._id_display.setReadOnly(True)
        self._id_display.setStyleSheet(MONO_STYLE)
        id_row.addWidget(self._id_display)
        f1.addRow(self._lbl("Duct ID"), id_row)

        self.spur_suffix = QLineEdit()
        self.spur_suffix.setPlaceholderText("e.g. a, b, c1  (leave blank for main leg)")
        self.spur_suffix.setMaxLength(6)
        self.spur_suffix.setStyleSheet(INPUT_STYLE)
        self.spur_suffix.textChanged.connect(self._update_id_preview)
        f1.addRow(self._lbl("Spur Suffix"), self.spur_suffix)

        f1.addRow(self._lbl("Length (m)"), self._ro(f"{self._length_m} m", CALC_STYLE))
        f1.addRow(self._lbl("Compass Leg"), self._ro(
            {"N":"North (001–099)","S":"South (100–199)",
             "E":"East (200–299)","W":"West (300–399)"}[self._compass_leg]
        ))

        self.status = QComboBox()
        self.status.addItems(["PROPOSED", "SURVEY", "PERMITTED", "INSTALLED"])
        self.status.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Status"), self.status)

        fl.addLayout(f1)
        fl.addWidget(self._divider())

        # ── DUCT TYPE ──────────────────────────────────────────────────────
        fl.addWidget(self._section("DUCT TYPE"))
        f2 = QFormLayout(); f2.setSpacing(8); f2.setLabelAlignment(Qt.AlignRight)

        self.duct_type = QComboBox()
        self.duct_type.addItems(["SHOTGUN", "PIA_AERIAL", "PIA_SUBDUCT", "OWN_DUCT"])
        self.duct_type.setStyleSheet(INPUT_STYLE)
        self.duct_type.currentTextChanged.connect(self._on_duct_type_changed)
        f2.addRow(self._lbl("Duct Type *"), self.duct_type)

        self.shotgun_spare = QComboBox()
        self.shotgun_spare.addItems(["Yes — second barrel available", "No — second barrel used/damaged"])
        self.shotgun_spare.setStyleSheet(INPUT_STYLE)
        f2.addRow(self._lbl("Shotgun Spare"), self.shotgun_spare)

        self.pia_ref = QLineEdit()
        self.pia_ref.setPlaceholderText("Openreach PIA order/asset reference")
        self.pia_ref.setStyleSheet(INPUT_STYLE)
        self.pia_ref.setEnabled(False)
        f2.addRow(self._lbl("PIA Reference"), self.pia_ref)

        self.owner = QLineEdit("Gigaloch")
        self.owner.setStyleSheet(INPUT_STYLE)
        f2.addRow(self._lbl("Owner"), self.owner)

        fl.addLayout(f2)
        fl.addWidget(self._divider())

        # ── PHYSICAL ──────────────────────────────────────────────────────
        fl.addWidget(self._section("PHYSICAL"))
        f3 = QFormLayout(); f3.setSpacing(8); f3.setLabelAlignment(Qt.AlignRight)

        self.surface_type = QComboBox()
        self.surface_type.addItems(["FIELD", "VERGE", "ROAD", "PRIVATE", "MIXED", "AERIAL"])
        self.surface_type.setStyleSheet(INPUT_STYLE)
        f3.addRow(self._lbl("Surface Type *"), self.surface_type)

        self.depth_m = QDoubleSpinBox()
        self.depth_m.setMinimum(0); self.depth_m.setMaximum(3.0)
        self.depth_m.setSingleStep(0.1); self.depth_m.setValue(0.0)
        self.depth_m.setSpecialValueText("— not yet set")
        self.depth_m.setStyleSheet(INPUT_STYLE)
        f3.addRow(self._lbl("Depth (m)"), self.depth_m)

        fl.addLayout(f3)
        fl.addWidget(self._divider())

        # ── PERMITS & WAYLEAVE ────────────────────────────────────────────
        fl.addWidget(self._section("PERMITS & WAYLEAVE"))
        f4 = QFormLayout(); f4.setSpacing(8); f4.setLabelAlignment(Qt.AlignRight)

        self.permit_ref = QLineEdit()
        self.permit_ref.setPlaceholderText("S50 / S171 reference (if applicable)")
        self.permit_ref.setStyleSheet(INPUT_STYLE)
        f4.addRow(self._lbl("Permit Ref"), self.permit_ref)

        self.wayleave_req = QCheckBox("Private wayleave required for this duct")
        self.wayleave_req.setStyleSheet(f"font-size:12px; color:{NAVY};")
        f4.addRow(self._lbl(""), self.wayleave_req)

        fl.addLayout(f4)
        fl.addWidget(self._divider())

        # ── NOTES ─────────────────────────────────────────────────────────
        fl.addWidget(self._section("NOTES"))
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Free text notes (optional)")
        self.notes.setStyleSheet(INPUT_STYLE)
        fl.addWidget(self.notes)

        scroll.setWidget(fw)
        root.addWidget(scroll)

        br = QHBoxLayout(); br.setContentsMargins(20, 12, 20, 16); br.addStretch()
        cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
        cancel.clicked.connect(self.reject); br.addWidget(cancel)
        save = QPushButton("Save Duct"); save.setStyleSheet(BTN_PRIMARY)
        save.clicked.connect(self._on_save); br.addWidget(save)
        root.addLayout(br)

    def _on_duct_type_changed(self, duct_type):
        is_shotgun = duct_type == "SHOTGUN"
        is_pia     = duct_type in ("PIA_AERIAL", "PIA_SUBDUCT")
        is_aerial  = duct_type == "PIA_AERIAL"

        self.shotgun_spare.setEnabled(is_shotgun)
        self.pia_ref.setEnabled(is_pia)
        self.depth_m.setEnabled(not is_aerial)

        if is_aerial:
            idx = self.surface_type.findText("AERIAL")
            if idx >= 0:
                self.surface_type.setCurrentIndex(idx)
            self.owner.setText("Openreach")
        elif is_pia:
            self.owner.setText("Openreach")
        else:
            self.owner.setText("Gigaloch")

    def _update_id_preview(self, suffix):
        suffix = suffix.strip()
        base = f"{self._area_id}-DUCT-{self._duct_seq:03d}"
        self._id_display.setText(f"{base}({suffix})" if suffix else base)

    def _on_save(self):
        if self.duct_type.currentText() in ("PIA_AERIAL", "PIA_SUBDUCT") \
                and not self.pia_ref.text().strip():
            r = QMessageBox.question(
                self, "PIA Reference Missing",
                "No PIA reference entered for a PIA duct.\n\n"
                "Save without it? You can add it later.",
                QMessageBox.Yes | QMessageBox.No
            )
            if r != QMessageBox.Yes:
                return
        self.accept()

    def get_attributes(self):
        return {
            "duct_id":        self._id_display.text().strip(),
            "duct_seq":       self._duct_seq,
            "spur_suffix":    self.spur_suffix.text().strip(),
            "compass_leg":    self._compass_leg,
            "from_node":      self._from_node,
            "from_node_type": self._from_node_type,
            "to_node":        self._to_node,
            "to_node_type":   self._to_node_type,
            "pop_id":         self._pop_id,
            "area_id":        self._area_id,
            "duct_type":      self.duct_type.currentText(),
            "shotgun_spare":  self.shotgun_spare.currentIndex() == 0,
            "pia_ref":        self.pia_ref.text().strip(),
            "owner":          self.owner.text().strip(),
            "length_m":       self._length_m,
            "surface_type":   self.surface_type.currentText(),
            "depth_m":        self.depth_m.value() if self.depth_m.value() > 0 else None,
            "permit_ref":     self.permit_ref.text().strip(),
            "wayleave_req":   self.wayleave_req.isChecked(),
            "status":         self.status.currentText(),
            "notes":          self.notes.text().strip(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# MAP TOOL
# ═══════════════════════════════════════════════════════════════════════════

class DigitiseDuctMapTool(QgsMapTool):
    """
    Click points to digitise a duct line.
    Snaps to existing chambers, poles, and cabinets.
    Right-click to finish.
    """

    placed = pyqtSignal(str)  # emits duct_id

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self._points  = []       # EPSG:27700 points
        self._node_ids   = []    # snapped node IDs
        self._node_types = []    # snapped node types

        # Rubber band — navy blue line
        self._rubber = QgsRubberBand(self._canvas, QgsWkbTypes.LineGeometry)
        self._rubber.setColor(QColor(26, 58, 92, 200))
        self._rubber.setWidth(2)

        # Snap indicator — small orange circle
        self._snap_rubber = QgsRubberBand(self._canvas, QgsWkbTypes.PointGeometry)
        self._snap_rubber.setColor(QColor(200, 90, 0, 220))
        self._snap_rubber.setIconSize(10)

        self.setCursor(QCursor(Qt.CrossCursor))

    def _to_27700(self, canvas_pt):
        canvas_crs = self._canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
        if canvas_crs == target_crs:
            return canvas_pt
        xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
        return xform.transform(canvas_pt)

    def _to_canvas(self, pt_27700):
        canvas_crs = self._canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
        if canvas_crs == target_crs:
            return pt_27700
        xform = QgsCoordinateTransform(target_crs, canvas_crs, QgsProject.instance())
        return xform.transform(pt_27700)

    def canvasMoveEvent(self, event):
        """Show snap indicator when hovering near a node."""
        snapped_pt, _, _ = _snap_to_node(self._canvas, self._project, event.pos())
        self._snap_rubber.reset(QgsWkbTypes.PointGeometry)
        if snapped_pt:
            canvas_pt = self._to_canvas(snapped_pt)
            self._snap_rubber.addPoint(canvas_pt, True)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Try to snap to a node first
            snapped_pt, node_id, node_type = _snap_to_node(
                self._canvas, self._project, event.pos()
            )

            if snapped_pt:
                pt_27700  = snapped_pt
                nid       = node_id
                ntype     = node_type
            else:
                canvas_pt = self.toMapCoordinates(event.pos())
                pt_27700  = self._to_27700(canvas_pt)
                nid       = None
                ntype     = None

            self._points.append(pt_27700)
            self._node_ids.append(nid)
            self._node_types.append(ntype)

            # Add to rubber band (in canvas CRS)
            canvas_pt = self._to_canvas(pt_27700)
            self._rubber.addPoint(canvas_pt, True)

        elif event.button() == Qt.RightButton:
            if len(self._points) < 2:
                QMessageBox.warning(None, "Conductor",
                    "A duct needs at least 2 points.\n"
                    "Keep left-clicking to add vertices, then right-click to finish.")
                return
            self._finish()

    def canvasDoubleClickEvent(self, event):
        pass  # swallowed — right-click finishes

    def _finish(self):
        self._rubber.reset()
        self._snap_rubber.reset()

        # Validate prerequisites
        cab_feat, cab_pt = _get_cabinet(self._project)
        if not cab_pt:
            QMessageBox.warning(None, "Conductor",
                "No cabinet found for this Build Area.\n"
                "Place a Cabinet / POP first.")
            self._reset()
            return

        duct_layer = self._project.get_layer("ducts")
        if not duct_layer:
            QMessageBox.critical(None, "Conductor", "Ducts layer not found.")
            self._reset()
            return

        # Calculate midpoint for compass leg
        mid_x = sum(p.x() for p in self._points) / len(self._points)
        mid_y = sum(p.y() for p in self._points) / len(self._points)
        midpoint = QgsPointXY(mid_x, mid_y)
        compass_leg = _compass_leg(midpoint, cab_pt)

        # Auto ID
        try:
            duct_id, seq = _next_duct_id(
                duct_layer, self._project.area_id, compass_leg
            )
        except ValueError as e:
            QMessageBox.critical(None, "Conductor", str(e))
            self._reset()
            return

        # Calculate length
        length_m = _calc_length(self._points)

        # Determine from/to nodes
        from_node  = self._node_ids[0]   or "unknown"
        from_type  = self._node_types[0] or "UNKNOWN"
        to_node    = self._node_ids[-1]  or "unknown"
        to_type    = self._node_types[-1]or "UNKNOWN"

        pop_id = cab_feat["pop_id"]

        dlg = DigitiseDuctDialog(
            duct_id=duct_id, duct_seq=seq, compass_leg=compass_leg,
            area_id=self._project.area_id, pop_id=pop_id,
            from_node=from_node, from_node_type=from_type,
            to_node=to_node, to_node_type=to_type,
            length_m=length_m,
        )

        if dlg.exec_() != QDialog.Accepted:
            self._reset()
            return

        attrs = dlg.get_attributes()

        # Write feature
        feat = QgsFeature(duct_layer.fields())
        feat.setGeometry(QgsGeometry.fromPolylineXY(self._points))

        for fname, val in attrs.items():
            idx = duct_layer.fields().indexOf(fname)
            if idx >= 0 and val is not None:
                feat.setAttribute(idx, val)

        duct_layer.startEditing()
        if duct_layer.addFeature(feat):
            duct_layer.commitChanges()
            duct_layer.triggerRepaint()

            # Make layer visible
            tree_layer = QgsProject.instance().layerTreeRoot().findLayer(duct_layer.id())
            if tree_layer:
                tree_layer.setItemVisibilityChecked(True)

            self.placed.emit(attrs["duct_id"])
            # Stay active — ready to draw the next duct segment immediately
        else:
            duct_layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to write duct feature.")

        self._reset()

    def _reset(self):
        self._points     = []
        self._node_ids   = []
        self._node_types = []
        self._rubber.reset()
        self._snap_rubber.reset()

    def deactivate(self):
        """Clean up canvas graphics when tool deactivates."""
        try:
            self._rubber.reset()
            self._canvas.scene().removeItem(self._rubber)
        except Exception:
            pass
        try:
            self._snap_rubber.reset()
            self._canvas.scene().removeItem(self._snap_rubber)
        except Exception:
            pass
        self._canvas.refresh()
        super().deactivate()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reset()
            self._canvas.unsetMapTool(self)
        elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
            # Ctrl+Z removes last point
            if self._points:
                self._points.pop()
                self._node_ids.pop()
                self._node_types.pop()
                self._rubber.removeLastPoint()
