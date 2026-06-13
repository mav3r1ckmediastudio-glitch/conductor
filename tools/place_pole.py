# -*- coding: utf-8 -*-
"""
Conductor — Place Pole Tool (PIA)
Places an Openreach pole as a chamber record with chamber_type = PIA_POLE.
Poles are civil-only assets — no optical role. The CBT placed on a pole
carries the optical event.
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QDoubleSpinBox,
    QPushButton, QFrame, QMessageBox, QScrollArea,
)
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
)
from qgis.gui import QgsMapToolEmitPoint
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE, MONO_STYLE

def _next_pole_id(layer, area_id):
    """Find the next available pole sequence number for this build area."""
    existing = set()
    prefix = f"{area_id}-POL-"
    for feat in layer.getFeatures():
        cid = feat["chamber_id"] or ""
        if cid.startswith(prefix):
            try:
                existing.add(int(cid.replace(prefix, "")))
            except ValueError:
                pass
    n = 1
    while n in existing:
        n += 1
    return f"{prefix}{n:03d}", n


# ═══════════════════════════════════════════════════════════════════════════
# PLACE POLE FORM
# ═══════════════════════════════════════════════════════════════════════════

class PlacePoleDialog(QDialog):

    def __init__(self, pole_id, area_id, pop_id, point, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Place Pole")
        self.setMinimumWidth(500)
        self.setMaximumHeight(680)
        self.setModal(True)

        self._pole_id = pole_id
        self._area_id = area_id
        self._pop_id  = pop_id
        self._point   = point
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
        hdr = QLabel(f"  Place Pole  —  {self._pole_id}")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        coords = QLabel(f"  E {self._point.x():.1f}  N {self._point.y():.1f}  (EPSG:27700)")
        coords.setFixedHeight(24)
        coords.setStyleSheet(f"background:{TEAL}; color:{WHITE}; font-size:11px; padding-left:8px;")
        root.addWidget(coords)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{LIGHT}; border:none;")

        fw = QFrame(); fw.setStyleSheet(f"background:{LIGHT};")
        fl = QVBoxLayout(fw); fl.setContentsMargins(20, 14, 20, 8); fl.setSpacing(8)

        # ── IDENTITY ──────────────────────────────────────────────────────
        fl.addWidget(self._section("IDENTITY"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)

        id_disp = QLineEdit(self._pole_id)
        id_disp.setReadOnly(True)
        id_disp.setStyleSheet(MONO_STYLE)
        f1.addRow(self._lbl("Pole ID"), id_disp)

        self.openreach_ref = QLineEdit()
        self.openreach_ref.setPlaceholderText("Openreach pole reference (stamped on pole)")
        self.openreach_ref.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Openreach Ref"), self.openreach_ref)

        self.status = QComboBox()
        self.status.addItems(["PROPOSED", "SURVEY", "INSTALLED"])
        self.status.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Status"), self.status)

        fl.addLayout(f1)
        fl.addWidget(self._divider())

        # ── PHYSICAL ──────────────────────────────────────────────────────
        fl.addWidget(self._section("PHYSICAL"))
        f2 = QFormLayout(); f2.setSpacing(8); f2.setLabelAlignment(Qt.AlignRight)

        self.pole_type = QComboBox()
        self.pole_type.addItems([
            "— not set —",
            "SOFTWOOD_7M", "SOFTWOOD_9M", "SOFTWOOD_11M",
            "CONCRETE_7M", "CONCRETE_9M",
            "STEEL",
            "OTHER",
        ])
        self.pole_type.setStyleSheet(INPUT_STYLE)
        f2.addRow(self._lbl("Pole Type"), self.pole_type)

        self.attachment_height_m = QDoubleSpinBox()
        self.attachment_height_m.setMinimum(0.0)
        self.attachment_height_m.setMaximum(15.0)
        self.attachment_height_m.setSingleStep(0.5)
        self.attachment_height_m.setDecimals(1)
        self.attachment_height_m.setSpecialValueText("— not set")
        self.attachment_height_m.setStyleSheet(INPUT_STYLE)
        self.attachment_height_m.setToolTip(
            "Height in metres at which the fibre cable is attached. "
            "Openreach minimum clearance rules apply."
        )
        f2.addRow(self._lbl("Attachment Height (m)"), self.attachment_height_m)

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
        save = QPushButton("Place Pole"); save.setStyleSheet(BTN_PRIMARY)
        save.clicked.connect(self.accept); br.addWidget(save)
        root.addLayout(br)

    def get_attributes(self):
        pole_type = self.pole_type.currentText()
        height    = self.attachment_height_m.value()
        return {
            "chamber_id":          self._pole_id,
            "chamber_type":        "PIA_POLE",
            "area_id":             self._area_id,
            "pop_id":              self._pop_id,
            "openreach_ref":       self.openreach_ref.text().strip() or None,
            "pole_type":           pole_type if not pole_type.startswith("—") else None,
            "attachment_height_m": height if height > 0.0 else None,
            "status":              self.status.currentText(),
            "notes":               self.notes.text().strip() or None,
        }


# ═══════════════════════════════════════════════════════════════════════════
# MAP TOOL
# ═══════════════════════════════════════════════════════════════════════════

class PlacePoleMapTool(QgsMapToolEmitPoint):
    """Single click places a PIA_POLE in the chambers layer."""

    placed = pyqtSignal(str)  # emits pole_id

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        # ── PREREQUISITES ─────────────────────────────────────────────────
        pop_layer = self._project.get_layer("exchange_pops")
        if not pop_layer or pop_layer.featureCount() == 0:
            QMessageBox.warning(
                None, "Conductor — Cannot Place Pole",
                "No Cabinet found.\n\nPlease place a Cabinet / POP first."
            )
            return

        pop_id = None
        for feat in pop_layer.getFeatures():
            if feat["area_id"] == self._project.area_id:
                pop_id = feat["pop_id"]
                break

        chamber_layer = self._project.get_layer("chambers")
        if not chamber_layer:
            QMessageBox.critical(None, "Conductor", "chambers layer not found.")
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

        # ── AUTO NUMBERING ────────────────────────────────────────────────
        pole_id, _ = _next_pole_id(chamber_layer, self._project.area_id)

        # ── OPEN FORM ─────────────────────────────────────────────────────
        dlg = PlacePoleDialog(
            pole_id=pole_id,
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

        for fname, val in attrs.items():
            idx = chamber_layer.fields().indexOf(fname)
            if idx >= 0 and val is not None:
                feat.setAttribute(idx, val)

        chamber_layer.startEditing()
        if chamber_layer.addFeature(feat):
            chamber_layer.commitChanges()
            chamber_layer.triggerRepaint()

            tree_layer = QgsProject.instance().layerTreeRoot().findLayer(
                chamber_layer.id()
            )
            if tree_layer:
                tree_layer.setItemVisibilityChecked(True)

            self._canvas.flashFeatureIds(
                chamber_layer,
                [f.id() for f in chamber_layer.getFeatures()
                 if f["chamber_id"] == pole_id]
            )

            self.placed.emit(pole_id)
        else:
            chamber_layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to write pole feature.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._canvas.unsetMapTool(self)
