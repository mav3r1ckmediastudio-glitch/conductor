# -*- coding: utf-8 -*-
"""
Conductor — Place Joint Tool
Places a joint closure inside an existing chamber.
Joints are the nodes of the fibre topology.
Optionally contains a passive optical splitter.
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox,
    QPushButton, QFrame, QMessageBox, QScrollArea, QCheckBox,
)
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeatureRequest, QgsRectangle,
)
from qgis.gui import QgsMapToolEmitPoint
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE, MONO_STYLE

def _next_joint_id(layer, area_id):
    existing = set()
    prefix = f"{area_id}-JNT-"
    for feat in layer.getFeatures():
        jid = feat["joint_id"] or ""
        if jid.startswith(prefix):
            try:
                existing.add(int(jid.replace(prefix, "")))
            except ValueError:
                pass
    n = 1
    while n in existing:
        n += 1
    return f"{prefix}{n:03d}"


def _find_chamber_at(canvas, project, canvas_pos, radius_px=14):
    """Find the nearest chamber to the click point."""
    canvas_crs = canvas.mapSettings().destinationCrs()
    target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
    canvas_pt  = canvas.getCoordinateTransform().toMapCoordinates(canvas_pos)

    if canvas_crs != target_crs:
        xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
        pt_27700 = xform.transform(canvas_pt)
    else:
        pt_27700 = canvas_pt

    radius = canvas.mapUnitsPerPixel() * radius_px
    layer  = project.get_layer("chambers")
    if not layer:
        return None, None

    rect = QgsRectangle(
        pt_27700.x() - radius, pt_27700.y() - radius,
        pt_27700.x() + radius, pt_27700.y() + radius,
    )
    best_dist = radius
    best_feat = None

    for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
        fp   = feat.geometry().asPoint()
        dist = math.sqrt((fp.x()-pt_27700.x())**2 + (fp.y()-pt_27700.y())**2)
        if dist < best_dist:
            best_dist = dist
            best_feat = feat

    return best_feat, pt_27700


# ═══════════════════════════════════════════════════════════════════════════
# JOINT FORM
# ═══════════════════════════════════════════════════════════════════════════

class PlaceJointDialog(QDialog):

    def __init__(self, joint_id, chamber_id, chamber_name, area_id, pop_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Place Joint")
        self.setMinimumWidth(500)
        self.setMaximumHeight(720)
        self.setModal(True)

        self._joint_id   = joint_id
        self._chamber_id = chamber_id
        self._area_id    = area_id
        self._pop_id     = pop_id
        self._build_ui(chamber_name)

    def _lbl(self, t):
        l = QLabel(t); l.setStyleSheet(LABEL_STYLE); return l

    def _section(self, t):
        l = QLabel(t); l.setStyleSheet(SECTION_STYLE); return l

    def _divider(self):
        f = QFrame(); f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"color:{MID}; margin:4px 0px;"); return f

    def _build_ui(self, chamber_name):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr = QLabel(f"  Place Joint  —  {self._joint_id}")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        sub = QLabel(f"  Inside chamber: {chamber_name}")
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

        id_disp = QLineEdit(self._joint_id)
        id_disp.setReadOnly(True)
        id_disp.setStyleSheet(MONO_STYLE)
        f1.addRow(self._lbl("Joint ID"), id_disp)

        chamber_disp = QLineEdit(chamber_name)
        chamber_disp.setReadOnly(True)
        chamber_disp.setStyleSheet(MONO_STYLE)
        f1.addRow(self._lbl("Parent Chamber"), chamber_disp)

        self.joint_type = QComboBox()
        self.joint_type.addItems(["SPLICE", "BLOWING_POINT", "END_OF_LINE"])
        self.joint_type.setStyleSheet(INPUT_STYLE)
        self.joint_type.currentTextChanged.connect(self._on_joint_type_changed)
        f1.addRow(self._lbl("Joint Type *"), self.joint_type)

        self.closure_type = QLineEdit()
        self.closure_type.setPlaceholderText("e.g. Commscope ADP-FS4 (optional)")
        self.closure_type.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Closure Model"), self.closure_type)

        self.fibre_in = QSpinBox()
        self.fibre_in.setMinimum(0); self.fibre_in.setMaximum(288)
        self.fibre_in.setSpecialValueText("— not set"); self.fibre_in.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Fibres In"), self.fibre_in)

        self.fibre_out = QSpinBox()
        self.fibre_out.setMinimum(0); self.fibre_out.setMaximum(288)
        self.fibre_out.setSpecialValueText("— not set"); self.fibre_out.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Fibres Out"), self.fibre_out)

        self.status = QComboBox()
        self.status.addItems(["PROPOSED", "SURVEY", "INSTALLED", "LIVE"])
        self.status.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Status"), self.status)

        fl.addLayout(f1)
        fl.addWidget(self._divider())

        # ── SPLITTER (optional) ───────────────────────────────────────────
        fl.addWidget(self._section("SPLITTER  (leave unchecked if this is a through-splice or blowing point)"))

        self.has_splitter = QCheckBox("This joint contains a passive optical splitter")
        self.has_splitter.setStyleSheet(f"font-size:12px; color:{NAVY}; font-weight:bold;")
        self.has_splitter.toggled.connect(self._on_splitter_toggled)
        fl.addWidget(self.has_splitter)

        self._splitter_frame = QFrame()
        self._splitter_frame.setEnabled(False)
        sf = QFormLayout(self._splitter_frame)
        sf.setSpacing(8); sf.setLabelAlignment(Qt.AlignRight)

        self.split_ratio = QComboBox()
        self.split_ratio.addItems(["— select —", "1:2", "1:4", "1:8", "1:16", "1:32"])
        self.split_ratio.setStyleSheet(INPUT_STYLE)
        sf.addRow(self._lbl("Split Ratio *"), self.split_ratio)

        self.cascade_level = QComboBox()
        self.cascade_level.addItems(["— select —", "1 — Primary", "2 — Secondary"])
        self.cascade_level.setStyleSheet(INPUT_STYLE)
        sf.addRow(self._lbl("Cascade Level *"), self.cascade_level)

        self.cascade_type = QComboBox()
        self.cascade_type.addItems(["— select —", "URBAN_1_2_1_16", "RURAL_1_4_1_8", "DIRECT_1_32"])
        self.cascade_type.setStyleSheet(INPUT_STYLE)
        sf.addRow(self._lbl("Cascade Type"), self.cascade_type)

        fl.addWidget(self._splitter_frame)
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
        save = QPushButton("Place Joint"); save.setStyleSheet(BTN_PRIMARY)
        save.clicked.connect(self._on_save); br.addWidget(save)
        root.addLayout(br)

    def _on_joint_type_changed(self, jtype):
        # Blowing point and end of line can't have splitters
        can_splice = jtype == "SPLICE"
        self.has_splitter.setEnabled(can_splice)
        if not can_splice:
            self.has_splitter.setChecked(False)

    def _on_splitter_toggled(self, checked):
        self._splitter_frame.setEnabled(checked)

    def _on_save(self):
        if self.has_splitter.isChecked():
            if self.split_ratio.currentText().startswith("—"):
                QMessageBox.warning(self, "Required", "Please select a Split Ratio.")
                return
            if self.cascade_level.currentText().startswith("—"):
                QMessageBox.warning(self, "Required", "Please select a Cascade Level.")
                return
        self.accept()

    def get_attributes(self):
        ratio   = self.split_ratio.currentText()
        level   = self.cascade_level.currentText()
        ctype   = self.cascade_type.currentText()
        return {
            "joint_id":      self._joint_id,
            "chamber_id":    self._chamber_id,
            "area_id":       self._area_id,
            "pop_id":        self._pop_id,
            "joint_type":    self.joint_type.currentText(),
            "has_splitter":  self.has_splitter.isChecked(),
            "split_ratio":   ratio   if not ratio.startswith("—")  else None,
            "cascade_level": int(level[0]) if not level.startswith("—") else None,
            "cascade_type":  ctype   if not ctype.startswith("—")  else None,
            "closure_type":  self.closure_type.text().strip(),
            "fibre_in":      self.fibre_in.value()  if self.fibre_in.value()  > 0 else None,
            "fibre_out":     self.fibre_out.value() if self.fibre_out.value() > 0 else None,
            "status":        self.status.currentText(),
            "notes":         self.notes.text().strip(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# MAP TOOL
# ═══════════════════════════════════════════════════════════════════════════

class PlaceJointMapTool(QgsMapToolEmitPoint):
    """Click inside or near a chamber to place a joint inside it."""

    placed = pyqtSignal(str)

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        # Find nearest chamber
        chamber_feat, pt_27700 = _find_chamber_at(
            self._canvas, self._project, event.pos()
        )

        if chamber_feat is None:
            QMessageBox.warning(None, "Conductor",
                "No chamber found near that location.\n\n"
                "Click closer to an existing chamber.\n"
                "Joints must be placed inside chambers.")
            return

        chamber_id   = chamber_feat["chamber_id"]
        chamber_pt   = chamber_feat.geometry().asPoint()
        pop_id       = chamber_feat["pop_id"]

        joint_layer = self._project.get_layer("joints")
        if not joint_layer:
            QMessageBox.critical(None, "Conductor", "Joints layer not found.")
            return

        joint_id = _next_joint_id(joint_layer, self._project.area_id)

        dlg = PlaceJointDialog(
            joint_id=joint_id,
            chamber_id=chamber_id,
            chamber_name=chamber_id,
            area_id=self._project.area_id,
            pop_id=pop_id,
        )

        if dlg.exec_() != QDialog.Accepted:
            return

        attrs = dlg.get_attributes()

        # Write joint at same coordinates as chamber
        feat = QgsFeature(joint_layer.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(chamber_pt))

        for fname, fvalue in attrs.items():
            idx = joint_layer.fields().indexOf(fname)
            if idx >= 0 and fvalue is not None:
                feat.setAttribute(idx, fvalue)

        joint_layer.startEditing()
        if joint_layer.addFeature(feat):
            joint_layer.commitChanges()
            joint_layer.triggerRepaint()

            # Auto-update chamber_function to JOINT
            chamber_layer = self._project.get_layer("chambers")
            if chamber_layer:
                chamber_layer.startEditing()
                try:
                    for cf in chamber_layer.getFeatures():
                        if cf["chamber_id"] == chamber_id:
                            idx = chamber_layer.fields().indexOf("chamber_function")
                            if idx >= 0:
                                chamber_layer.changeAttributeValue(cf.id(), idx, "JOINT")
                            break
                    chamber_layer.commitChanges()
                    chamber_layer.triggerRepaint()
                except Exception:
                    chamber_layer.rollBack()

            # Make layer visible
            tree_layer = QgsProject.instance().layerTreeRoot().findLayer(joint_layer.id())
            if tree_layer:
                tree_layer.setItemVisibilityChecked(True)

            self.placed.emit(joint_id)
        else:
            joint_layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to write joint feature.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._canvas.unsetMapTool(self)
