# -*- coding: utf-8 -*-
"""
Conductor — Place Chamber Tool
Auto-numbers chambers by compass direction from the parent cabinet.
Requires a Build Area polygon and a Cabinet within it.
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox,
    QPushButton, QFrame, QMessageBox, QScrollArea,
)
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeatureRequest, QgsRectangle,
)
from qgis.gui import QgsMapToolEmitPoint
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE, MONO_STYLE
from ..conductor_utils import compass_quadrant

def _push_undo(project, layer_name, action, id_field, id_value, attrs, geom, description):
    """Push an undo entry to the dockwidget's undo stack if available."""
    try:
        from qgis.utils import iface
        from qgis.core import QgsGeometry
        plugins = __import__('qgis.utils', fromlist=['plugins']).plugins
        dw = plugins.get('conductor')
        if dw and hasattr(dw, 'dockwidget') and dw.dockwidget:
            dw.dockwidget.push_undo({
                'description': description,
                'layer_name':  layer_name,
                'action':      action,
                'feature_id':  None,
                'attrs':       attrs,
                'geometry':    QgsGeometry(geom) if geom else None,
                'id_field':    id_field,
                'id_value':    str(id_value),
            })
    except Exception:
        pass  # undo is best-effort, never block the main action


# ── NUMBERING HELPERS ─────────────────────────────────────────────────────────

# Number ranges per compass direction
DIRECTION_BASE = {"N": 1, "S": 1001, "W": 2001, "E": 3001}
DIRECTION_MAX  = {"N": 999, "S": 1999, "W": 2999, "E": 3999}


def _compass_direction(chamber_pt, cabinet_pt):
    return compass_quadrant(cabinet_pt, chamber_pt)


def _next_chamber_id(layer, area_id, direction, spur_suffix=""):
    """
    Find the next available chamber sequence number for this direction.
    Returns (chamber_id, seq_number).
    """
    base    = DIRECTION_BASE[direction]
    maximum = DIRECTION_MAX[direction]
    existing = set()
    prefix = f"{area_id}-CMBR-"

    for feat in layer.getFeatures():
        cid = feat["chamber_id"] or ""
        if not cid.startswith(prefix):
            continue
        seq = feat["chamber_seq"]
        if seq and base <= seq <= maximum:
            existing.add(seq)

    n = base
    while n in existing and n <= maximum:
        n += 1

    if n > maximum:
        raise ValueError(f"No available chamber numbers for direction {direction}")

    suffix = f"({spur_suffix})" if spur_suffix else ""
    chamber_id = f"{prefix}{n:04d}{suffix}"
    return chamber_id, n


def _get_cabinet_for_area(pop_layer, area_id):
    """
    Return the cabinet feature for this build area.
    If multiple exist, return the first (edge case — one cabinet per build area is the rule).
    """
    for feat in pop_layer.getFeatures():
        if feat["area_id"] == area_id:
            return feat
    return None


def _check_prerequisites(project):
    """
    Check that a Build Area and Cabinet exist before allowing chamber placement.
    Returns (ok: bool, message: str, cabinet_feat or None, cabinet_pt or None).
    """
    ba_layer  = project.get_layer("build_areas")
    pop_layer = project.get_layer("exchange_pops")

    if not ba_layer or ba_layer.featureCount() == 0:
        return False, (
            "No Build Area found.\n\n"
            "Please draw a Build Area polygon first using\n"
            "Design → Build Areas before placing chambers."
        ), None, None

    if not pop_layer or pop_layer.featureCount() == 0:
        return False, (
            "No Cabinet found in this Build Area.\n\n"
            "Please place a Cabinet / POP first using\n"
            "Design → Place Cabinet / POP."
        ), None, None

    cab_feat = _get_cabinet_for_area(pop_layer, project.area_id)
    if cab_feat is None:
        return False, (
            f"No cabinet found for Build Area {project.area_id}.\n\n"
            "Place a Cabinet / POP first."
        ), None, None

    cab_geom = cab_feat.geometry()
    cab_pt   = cab_geom.asPoint()
    return True, "", cab_feat, cab_pt


# ═══════════════════════════════════════════════════════════════════════════
# CHAMBER FORM
# ═══════════════════════════════════════════════════════════════════════════

class PlaceChamberDialog(QDialog):

    def __init__(self, chamber_id, chamber_seq, direction,
                 area_id, pop_id, point, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Place Chamber")
        self.setMinimumWidth(480)
        self.setMaximumHeight(700)
        self.setModal(True)

        self._chamber_id  = chamber_id
        self._chamber_seq = chamber_seq
        self._direction   = direction
        self._area_id     = area_id
        self._pop_id      = pop_id
        self._point       = point
        self._build_ui()

    def _lbl(self, t):
        l = QLabel(t); l.setStyleSheet(LABEL_STYLE); return l

    def _section(self, t):
        l = QLabel(t); l.setStyleSheet(SECTION_STYLE); return l

    def _divider(self):
        f = QFrame(); f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"color:{MID}; margin:4px 0px;"); return f

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # Header
        hdr = QLabel(f"  Place Chamber  —  {self._chamber_id}")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        coords = QLabel(
            f"  E {self._point.x():.1f}  N {self._point.y():.1f}  "
            f"  Direction from cabinet: {self._direction}"
        )
        coords.setFixedHeight(24)
        coords.setStyleSheet(f"background:{TEAL}; color:{WHITE}; font-size:11px; padding-left:8px;")
        root.addWidget(coords)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{LIGHT}; border:none;")

        fw = QFrame(); fw.setStyleSheet(f"background:{LIGHT};")
        fl = QVBoxLayout(fw); fl.setContentsMargins(20, 14, 20, 8); fl.setSpacing(8)

        # ── IDENTITY ──────────────────────────────────────────────────────
        fl.addWidget(self._section("IDENTITY"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)

        # Chamber ID display with spur suffix option
        id_row = QHBoxLayout()
        self._id_display = QLineEdit(self._chamber_id)
        self._id_display.setReadOnly(True)
        self._id_display.setStyleSheet(MONO_STYLE)
        id_row.addWidget(self._id_display)
        f1.addRow(self._lbl("Chamber ID"), id_row)

        # Spur suffix
        spur_row = QHBoxLayout()
        self.spur_suffix = QLineEdit()
        self.spur_suffix.setPlaceholderText("e.g. a, b, c1  (leave blank for main route)")
        self.spur_suffix.setMaxLength(6)
        self.spur_suffix.setStyleSheet(INPUT_STYLE)
        self.spur_suffix.textChanged.connect(self._update_id_preview)
        spur_row.addWidget(self.spur_suffix)
        f1.addRow(self._lbl("Spur Suffix"), spur_row)

        # Direction display
        dir_display = QLineEdit(
            {"N": "North  (0001–0999)",
             "S": "South  (1001–1999)",
             "W": "West   (2001–2999)",
             "E": "East   (3001–3999)"}[self._direction]
        )
        dir_display.setReadOnly(True)
        dir_display.setStyleSheet(MONO_STYLE)
        f1.addRow(self._lbl("Direction"), dir_display)

        self.chamber_type = QComboBox()
        self.chamber_type.addItems(["ACCESS_CHAMBER", "JOINT", "BURIED_JOINT"])
        self.chamber_type.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Chamber Function"), self.chamber_type)

        self.chamber_size = QComboBox()
        self.chamber_size.addItems(["SMALL", "LARGE"])
        self.chamber_size.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Chamber Size"), self.chamber_size)

        self.ring_count = QSpinBox()
        self.ring_count.setMinimum(0); self.ring_count.setMaximum(10)
        self.ring_count.setValue(4)
        self.ring_count.setSpecialValueText("— not yet set")
        self.ring_count.setStyleSheet(INPUT_STYLE)
        self.ring_count.setToolTip("Number of STAKKAbox rings (typically 4–5). Leave at 0 for buried joints.")
        f1.addRow(self._lbl("Ring Count"), self.ring_count)

        self.status = QComboBox()
        self.status.addItems(["PROPOSED", "SURVEY", "INSTALLED"])
        self.status.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Status"), self.status)

        fl.addLayout(f1)
        fl.addWidget(self._divider())

        # ── PHYSICAL ──────────────────────────────────────────────────────
        fl.addWidget(self._section("PHYSICAL"))
        f2 = QFormLayout(); f2.setSpacing(8); f2.setLabelAlignment(Qt.AlignRight)

        self.owner = QLineEdit("Gigaloch")
        self.owner.setStyleSheet(INPUT_STYLE)
        f2.addRow(self._lbl("Owner"), self.owner)

        self.pia_ref = QLineEdit()
        self.pia_ref.setPlaceholderText("Openreach PIA reference (if applicable)")
        self.pia_ref.setStyleSheet(INPUT_STYLE)
        f2.addRow(self._lbl("PIA Reference"), self.pia_ref)

        self.lid_type = QComboBox()
        self.lid_type.addItems(["— not yet set —", "STEEL_CONCRETE", "IRON", "COMPOSITE", "RECESSED"])
        self.lid_type.setStyleSheet(INPUT_STYLE)
        f2.addRow(self._lbl("Lid Type"), self.lid_type)

        self.depth_m = QSpinBox()
        self.depth_m.setMinimum(0); self.depth_m.setMaximum(5)
        self.depth_m.setSpecialValueText("— not yet set")
        self.depth_m.setStyleSheet(INPUT_STYLE)
        f2.addRow(self._lbl("Depth (m)"), self.depth_m)

        fl.addLayout(f2)
        fl.addWidget(self._divider())

        # ── NOTES ─────────────────────────────────────────────────────────
        fl.addWidget(self._section("NOTES"))
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Free text notes (optional)")
        self.notes.setStyleSheet(INPUT_STYLE)
        fl.addWidget(self.notes)

        scroll.setWidget(fw)
        root.addWidget(scroll)

        # Buttons
        br = QHBoxLayout(); br.setContentsMargins(20, 12, 20, 16); br.addStretch()
        cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
        cancel.clicked.connect(self.reject); br.addWidget(cancel)
        save = QPushButton("Place Chamber"); save.setStyleSheet(BTN_PRIMARY)
        save.clicked.connect(self.accept); br.addWidget(save)
        root.addLayout(br)

    def _update_id_preview(self, suffix):
        """Update the chamber ID display when spur suffix changes."""
        suffix = suffix.strip()
        base = f"{self._area_id}-CMBR-{self._chamber_seq:04d}"
        self._id_display.setText(f"{base}({suffix})" if suffix else base)

    def get_attributes(self):
        return {
            "chamber_id":   self._id_display.text().strip(),
            "chamber_seq":  self._chamber_seq,
            "spur_suffix":  self.spur_suffix.text().strip(),
            "compass_dir":  self._direction,
            "pop_id":       self._pop_id,
            "area_id":      self._area_id,
            "chamber_type": self.chamber_type.currentText(),
            "chamber_size": self.chamber_size.currentText(),
            "ring_count":   self.ring_count.value() if self.ring_count.value() > 0 else None,
            "owner":        self.owner.text().strip(),
            "pia_ref":      self.pia_ref.text().strip(),
            "lid_type":     self.lid_type.currentText() if not self.lid_type.currentText().startswith("—") else "",
            "depth_m":      self.depth_m.value() if self.depth_m.value() > 0 else None,
            "status":       self.status.currentText(),
            "notes":        self.notes.text().strip(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# MAP TOOL
# ═══════════════════════════════════════════════════════════════════════════

class PlaceChamberMapTool(QgsMapToolEmitPoint):

    placed = pyqtSignal(str)  # emits chamber_id

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        # ── PREREQUISITES ─────────────────────────────────────────────────
        ok, msg, cab_feat, cab_pt = _check_prerequisites(self._project)
        if not ok:
            QMessageBox.warning(None, "Conductor — Cannot Place Chamber", msg)
            return

        # ── TRANSFORM CLICK TO EPSG:27700 ─────────────────────────────────
        canvas_crs = self._canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
        canvas_pt  = self.toMapCoordinates(event.pos())

        if canvas_crs != target_crs:
            xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
            point = xform.transform(canvas_pt)
        else:
            point = canvas_pt

        # ── AUTO COMPASS DIRECTION ────────────────────────────────────────
        direction = _compass_direction(point, cab_pt)

        # ── AUTO NUMBERING ────────────────────────────────────────────────
        chamber_layer = self._project.get_layer("chambers")
        if not chamber_layer:
            QMessageBox.critical(None, "Conductor", "chambers layer not found.")
            return

        try:
            chamber_id, seq = _next_chamber_id(
                chamber_layer, self._project.area_id, direction
            )
        except ValueError as e:
            QMessageBox.critical(None, "Conductor", str(e))
            return

        pop_id = cab_feat["pop_id"]

        # ── OPEN FORM ─────────────────────────────────────────────────────
        dlg = PlaceChamberDialog(
            chamber_id=chamber_id,
            chamber_seq=seq,
            direction=direction,
            area_id=self._project.area_id,
            pop_id=pop_id,
            point=point,
        )

        if dlg.exec_() != QDialog.Accepted:
            return

        attrs = dlg.get_attributes()

        # ── WRITE FEATURE ─────────────────────────────────────────────────
        feat = QgsFeature(chamber_layer.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(point))

        for fname, fvalue in attrs.items():
            idx = chamber_layer.fields().indexOf(fname)
            if idx >= 0 and fvalue is not None:
                feat.setAttribute(idx, fvalue)

        chamber_layer.startEditing()
        if chamber_layer.addFeature(feat):
            chamber_layer.commitChanges()
            chamber_layer.triggerRepaint()

            # Make layer visible
            tree_layer = QgsProject.instance().layerTreeRoot().findLayer(
                chamber_layer.id()
            )
            if tree_layer:
                tree_layer.setItemVisibilityChecked(True)

            # Flash
            self._canvas.flashFeatureIds(
                chamber_layer,
                [f.id() for f in chamber_layer.getFeatures()
                 if f["chamber_id"] == attrs["chamber_id"]]
            )

            self.placed.emit(attrs["chamber_id"])
            _push_undo(
                self._project, "chambers", "ADD",
                "chamber_id", attrs["chamber_id"],
                {f: feat[f] for f in feat.fields().names()},
                feat.geometry(),
                "Place Chamber " + str(attrs["chamber_id"])
            )
        else:
            chamber_layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to write chamber feature.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._canvas.unsetMapTool(self)
