# -*- coding: utf-8 -*-
"""
Conductor — Place CBT Tool (PIA)
Places a Cabinet Terminal (CBT) as a joint record with joint_type = CBT.
Snaps to the nearest PIA_POLE within 14px. The CBT shares the pole coordinates.
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QCheckBox,
    QPushButton, QFrame, QMessageBox, QScrollArea,
)
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeatureRequest, QgsRectangle, QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE, MONO_STYLE

WARN_STYLE    = f"border:1px solid #E0A000; border-radius:3px; padding:5px 8px; background:#FFFBE6; font-size:11px; color:#7A5000;"


def _next_cbt_id(layer, area_id):
    existing = set()
    prefix = f"{area_id}-CBT-"
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


def _find_nearest_pole(canvas, project, canvas_pos, radius_px=14):
    """Snap to nearest PIA_POLE in the chambers layer within radius_px."""
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
        if feat["chamber_type"] != "PIA_POLE":
            continue
        fp   = feat.geometry().asPoint()
        dist = math.sqrt((fp.x() - pt_27700.x())**2 + (fp.y() - pt_27700.y())**2)
        if dist < best_dist:
            best_dist = dist
            best_feat = feat

    return best_feat, pt_27700


# ═══════════════════════════════════════════════════════════════════════════
# PLACE CBT FORM
# ═══════════════════════════════════════════════════════════════════════════

class PlaceCBTDialog(QDialog):

    def __init__(self, cbt_id, pole_id, area_id, pop_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Place CBT")
        self.setMinimumWidth(500)
        self.setMaximumHeight(680)
        self.setModal(True)

        self._cbt_id  = cbt_id
        self._pole_id = pole_id
        self._area_id = area_id
        self._pop_id  = pop_id
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

        hdr = QLabel(f"  Place CBT  —  {self._cbt_id}")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        sub = QLabel(f"  Mounted on pole: {self._pole_id}")
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

        id_disp = QLineEdit(self._cbt_id)
        id_disp.setReadOnly(True)
        id_disp.setStyleSheet(MONO_STYLE)
        f1.addRow(self._lbl("CBT ID"), id_disp)

        pole_disp = QLineEdit(self._pole_id)
        pole_disp.setReadOnly(True)
        pole_disp.setStyleSheet(MONO_STYLE)
        f1.addRow(self._lbl("Parent Pole"), pole_disp)

        self.cbt_model = QComboBox()
        self.cbt_model.addItems([
            "Evolv Multiport Pushlok 8-port 300m (Corning)",
            "Corning OptiSheath 4-port",
            "Corning OptiSheath 12-port 250m drop",
            "Corning OptiSheath 12-port 350m drop",
        ])
        self.cbt_model.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("CBT Model"), self.cbt_model)

        self.status = QComboBox()
        self.status.addItems(["PROPOSED", "SURVEY", "INSTALLED", "LIVE"])
        self.status.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Status"), self.status)

        fl.addLayout(f1)
        fl.addWidget(self._divider())

        # ── SPLITTER ──────────────────────────────────────────────────────
        fl.addWidget(self._section("SPLITTER  (leave unchecked if this CBT is a through-splice only)"))

        self.has_splitter = QCheckBox("This CBT contains a passive optical splitter")
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
        save = QPushButton("Place CBT"); save.setStyleSheet(BTN_PRIMARY)
        save.clicked.connect(self._on_save); br.addWidget(save)
        root.addLayout(br)

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
        ratio = self.split_ratio.currentText()
        level = self.cascade_level.currentText()
        ctype = self.cascade_type.currentText()
        return {
            "joint_id":      self._cbt_id,
            "joint_type":    "CBT",
            "pole_id":       self._pole_id,
            "chamber_id":    self._pole_id,   # FK — CBT lives on the pole
            "area_id":       self._area_id,
            "pop_id":        self._pop_id,
            "cbt_model":     self.cbt_model.currentText(),
            "has_splitter":  self.has_splitter.isChecked(),
            "split_ratio":   ratio if not ratio.startswith("—") else None,
            "cascade_level": int(level[0]) if not level.startswith("—") else None,
            "cascade_type":  ctype if not ctype.startswith("—") else None,
            "status":        self.status.currentText(),
            "notes":         self.notes.text().strip() or None,
        }


# ═══════════════════════════════════════════════════════════════════════════
# MAP TOOL
# ═══════════════════════════════════════════════════════════════════════════

class PlaceCBTMapTool(QgsMapTool):
    """Click on or near a PIA_POLE to place a CBT on it."""

    placed = pyqtSignal(str)  # emits cbt_id

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self.setCursor(QCursor(Qt.CrossCursor))

        self._snap_rubber = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self._snap_rubber.setColor(QColor(0, 170, 255, 220))
        self._snap_rubber.setIconSize(10)

    def canvasMoveEvent(self, event):
        self._snap_rubber.reset(QgsWkbTypes.PointGeometry)
        pole_feat, _ = _find_nearest_pole(self._canvas, self._project, event.pos())
        if pole_feat:
            fp = pole_feat.geometry().asPoint()
            canvas_pt = self._to_canvas(fp)
            self._snap_rubber.addPoint(canvas_pt, True)

    def _to_canvas(self, pt_27700):
        from qgis.core import QgsCoordinateTransform, QgsCoordinateReferenceSystem
        src_crs = QgsCoordinateReferenceSystem("EPSG:27700")
        dst_crs = self._canvas.mapSettings().destinationCrs()
        if src_crs == dst_crs:
            return pt_27700
        return QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance()).transform(pt_27700)

    def deactivate(self):
        try:
            self._snap_rubber.reset()
            self._canvas.scene().removeItem(self._snap_rubber)
        except Exception:
            pass
        self._canvas.refresh()
        super().deactivate()

    def canvasPressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        # ── SNAP TO NEAREST POLE ──────────────────────────────────────────
        pole_feat, _ = _find_nearest_pole(self._canvas, self._project, event.pos())

        if pole_feat is None:
            QMessageBox.warning(
                None, "Conductor — No Pole Found",
                "No pole found near that location.\n\n"
                "Click closer to an existing pole.\n"
                "CBTs must be mounted on a pole."
            )
            return

        pole_id  = pole_feat["chamber_id"]
        pole_pt  = pole_feat.geometry().asPoint()
        pop_id   = pole_feat["pop_id"]

        joint_layer = self._project.get_layer("joints")
        if not joint_layer:
            QMessageBox.critical(None, "Conductor", "Joints layer not found.")
            return

        # ── CHECK FIELDS ──────────────────────────────────────────────────
        fields = [f.name() for f in joint_layer.fields()]
        missing = [f for f in ("pole_id", "cbt_model") if f not in fields]
        if missing:
            QMessageBox.critical(
                None, "Conductor — Schema Missing",
                f"The joints layer is missing PIA fields: {missing}\n\n"
                "Please run the schema migration before using PIA tools."
            )
            return

        cbt_id = _next_cbt_id(joint_layer, self._project.area_id)

        # ── OPEN FORM ─────────────────────────────────────────────────────
        dlg = PlaceCBTDialog(
            cbt_id=cbt_id,
            pole_id=pole_id,
            area_id=self._project.area_id,
            pop_id=pop_id,
        )

        if dlg.exec_() != QDialog.Accepted:
            return

        attrs = dlg.get_attributes()

        # ── WRITE FEATURE — at pole coordinates ───────────────────────────
        feat = QgsFeature(joint_layer.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(pole_pt))

        for fname, fvalue in attrs.items():
            idx = joint_layer.fields().indexOf(fname)
            if idx >= 0 and fvalue is not None:
                feat.setAttribute(idx, fvalue)

        joint_layer.startEditing()
        if joint_layer.addFeature(feat):
            joint_layer.commitChanges()
            joint_layer.triggerRepaint()

            tree_layer = QgsProject.instance().layerTreeRoot().findLayer(joint_layer.id())
            if tree_layer:
                tree_layer.setItemVisibilityChecked(True)

            self._canvas.flashFeatureIds(
                joint_layer,
                [f.id() for f in joint_layer.getFeatures()
                 if f["joint_id"] == cbt_id]
            )
            self.placed.emit(cbt_id)
        else:
            joint_layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to write CBT feature.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._canvas.unsetMapTool(self)
