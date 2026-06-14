# -*- coding: utf-8 -*-
"""
Conductor — Digitise PIA UG Duct Tool (PIA)
Multi-vertex line. Snaps to PIA_UG_CHAMBER and PIA_POLE in chambers layer.
RMB finishes and saves. Tool stays active.

Writes to the `ducts` layer using the same from_node/from_node_type/
to_node/to_node_type convention as DigitiseDuctMapTool, so that PIA UG
duct connectivity is recorded and downstream tools (fibre cable ->
duct matching, route validation, BOM) can see it.

duct_type is written as "PIA_SUBDUCT" — the value already used for
Openreach subduct in the main Digitise Duct tool's duct_type enum —
so Edit Asset's duct_type dropdown recognises it and round-trips
correctly instead of silently resetting to "SHOTGUN".
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox,
    QPushButton, QFrame, QMessageBox, QScrollArea,
)
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeatureRequest, QgsRectangle, QgsDistanceArea, QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE, MONO_STYLE, CALC_STYLE
from ..conductor_utils import line_length_m, to_project_crs

def _next_piad_id(layer, area_id):
    existing = set()
    prefix = f"{area_id}-PIAD-"
    for feat in layer.getFeatures():
        did = feat["duct_id"] or ""
        if did.startswith(prefix):
            try: existing.add(int(did.replace(prefix, "")))
            except ValueError: pass
    n = 1
    while n in existing: n += 1
    return f"{prefix}{n:03d}"


def _calc_length(points):
    return line_length_m(points)


def _snap_to_pia_node(canvas, project, pos, radius_px=14):
    """Snap to PIA_UG_CHAMBER or PIA_POLE in the chambers layer.

    Returns (point, chamber_id, chamber_type) where chamber_type is
    "PIA_UG_CHAMBER" or "PIA_POLE" — used as from_node_type/to_node_type
    on the duct feature. Returns (None, None, None) if nothing in range.
    """
    canvas_pt = canvas.getCoordinateTransform().toMapCoordinates(pos)
    src = canvas.mapSettings().destinationCrs()
    dst = QgsCoordinateReferenceSystem("EPSG:27700")
    pt  = QgsCoordinateTransform(src, dst, QgsProject.instance()).transform(canvas_pt) if src != dst else canvas_pt
    r   = canvas.mapUnitsPerPixel() * radius_px
    rect = QgsRectangle(pt.x()-r, pt.y()-r, pt.x()+r, pt.y()+r)

    best_dist = r; best_pt = None; best_id = None; best_type = None
    layer = project.get_layer("chambers")
    if layer:
        for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
            ct = feat["chamber_type"]
            if ct not in ("PIA_UG_CHAMBER", "PIA_POLE"):
                continue
            fp = feat.geometry().asPoint()
            d  = math.hypot(fp.x()-pt.x(), fp.y()-pt.y())
            if d < best_dist:
                best_dist = d; best_pt = fp; best_id = feat["chamber_id"]; best_type = ct
    return best_pt, best_id, best_type


def _to_canvas(canvas, pt):
    src = QgsCoordinateReferenceSystem("EPSG:27700")
    dst = canvas.mapSettings().destinationCrs()
    if src == dst: return pt
    return QgsCoordinateTransform(src, dst, QgsProject.instance()).transform(pt)


def _to_27700(canvas, canvas_pt):
    return to_project_crs(canvas, canvas_pt)


def _info(msg):
    try:
        from qgis.utils import iface
        iface.messageBar().pushInfo("Conductor", msg)
    except Exception: pass


class DigitisePIAUGDuctDialog(QDialog):

    def __init__(self, duct_id, from_node, from_node_type, to_node, to_node_type,
                 length_m, area_id, pop_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Digitise PIA UG Duct")
        self.setMinimumWidth(500)
        self.setMaximumHeight(520)
        self.setModal(True)
        self._duct_id       = duct_id
        self._from_node     = from_node
        self._from_node_type= from_node_type
        self._to_node       = to_node
        self._to_node_type  = to_node_type
        self._length_m      = length_m
        self._area_id       = area_id
        self._pop_id        = pop_id
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
        root.setSpacing(0); root.setContentsMargins(0,0,0,0)

        hdr = QLabel(f"  Digitise PIA UG Duct  —  {self._duct_id}")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        from_label = self._from_node or "—"
        to_label   = self._to_node or "—"
        sub = QLabel(f"  {from_label}  →  {to_label}  ·  Length: {self._length_m} m")
        sub.setFixedHeight(24)
        sub.setStyleSheet(f"background:{TEAL}; color:{WHITE}; font-size:11px; padding-left:8px;")
        root.addWidget(sub)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{LIGHT}; border:none;")

        fw = QFrame(); fw.setStyleSheet(f"background:{LIGHT};")
        fl = QVBoxLayout(fw); fl.setContentsMargins(20,14,20,8); fl.setSpacing(8)

        fl.addWidget(self._section("IDENTITY"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)

        id_disp = QLineEdit(self._duct_id)
        id_disp.setReadOnly(True); id_disp.setStyleSheet(MONO_STYLE)
        f1.addRow(self._lbl("Duct ID"), id_disp)

        len_disp = QLineEdit(f"{self._length_m} m")
        len_disp.setReadOnly(True); len_disp.setStyleSheet(CALC_STYLE)
        f1.addRow(self._lbl("Length (m)"), len_disp)

        from_disp = QLineEdit(f"{from_label}  ({self._from_node_type or 'UNKNOWN'})")
        from_disp.setReadOnly(True); from_disp.setStyleSheet(MONO_STYLE)
        f1.addRow(self._lbl("From"), from_disp)

        to_disp = QLineEdit(f"{to_label}  ({self._to_node_type or 'UNKNOWN'})")
        to_disp.setReadOnly(True); to_disp.setStyleSheet(MONO_STYLE)
        f1.addRow(self._lbl("To"), to_disp)

        self.openreach_ref = QLineEdit()
        self.openreach_ref.setPlaceholderText("Openreach subduct reference (optional)")
        self.openreach_ref.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Openreach Ref"), self.openreach_ref)

        self.status = QComboBox()
        self.status.addItems(["PROPOSED", "SURVEY", "INSTALLED"])
        self.status.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Status"), self.status)

        fl.addLayout(f1)
        fl.addWidget(self._divider())

        fl.addWidget(self._section("NOTES"))
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Free text notes (optional)")
        self.notes.setStyleSheet(INPUT_STYLE)
        fl.addWidget(self.notes)

        scroll.setWidget(fw)
        root.addWidget(scroll)

        br = QHBoxLayout(); br.setContentsMargins(20,12,20,16); br.addStretch()
        cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
        cancel.clicked.connect(self.reject); br.addWidget(cancel)
        save = QPushButton("Save Duct"); save.setStyleSheet(BTN_PRIMARY)
        save.clicked.connect(self.accept); br.addWidget(save)
        root.addLayout(br)

    def get_attributes(self):
        return {
            "duct_id":        self._duct_id,
            "duct_type":      "PIA_SUBDUCT",
            "from_node":      self._from_node,
            "from_node_type": self._from_node_type,
            "to_node":        self._to_node,
            "to_node_type":   self._to_node_type,
            "length_m":       self._length_m,
            "area_id":        self._area_id,
            "pop_id":         self._pop_id,
            "openreach_ref":  self.openreach_ref.text().strip() or None,
            "status":         self.status.currentText(),
            "notes":          self.notes.text().strip() or None,
        }


class DigitisePIAUGDuctMapTool(QgsMapTool):

    placed = pyqtSignal(str)

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self._points     = []
        self._node_ids   = []
        self._node_types = []

        self._rubber = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._rubber.setColor(QColor(123, 45, 139, 200))
        self._rubber.setWidth(2)

        self._snap_rubber = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self._snap_rubber.setColor(QColor(123, 45, 139, 220))
        self._snap_rubber.setIconSize(10)

        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasMoveEvent(self, event):
        snapped_pt, _, _ = _snap_to_pia_node(self._canvas, self._project, event.pos())
        self._snap_rubber.reset(QgsWkbTypes.PointGeometry)
        if snapped_pt:
            self._snap_rubber.addPoint(_to_canvas(self._canvas, snapped_pt), True)
        if self._points:
            preview = snapped_pt or _to_27700(self._canvas, self.toMapCoordinates(event.pos()))
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            for p in self._points:
                self._rubber.addPoint(_to_canvas(self._canvas, p))
            self._rubber.addPoint(_to_canvas(self._canvas, preview), True)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            if len(self._points) < 2:
                QMessageBox.warning(None, "Conductor", "Need at least 2 points. Keep clicking to add vertices.")
                return
            self._finish()
            return

        if event.button() != Qt.LeftButton:
            return

        snapped_pt, node_id, node_type = _snap_to_pia_node(self._canvas, self._project, event.pos())
        if snapped_pt:
            pt = snapped_pt
        else:
            pt = _to_27700(self._canvas, self.toMapCoordinates(event.pos()))
            node_id = None
            node_type = None

        self._points.append(pt)
        self._node_ids.append(node_id)
        self._node_types.append(node_type)
        self._rubber.addPoint(_to_canvas(self._canvas, pt), True)

    def _finish(self):
        self._rubber.reset(); self._snap_rubber.reset()

        duct_layer = self._project.get_layer("ducts")
        if not duct_layer:
            QMessageBox.critical(None, "Conductor", "Ducts layer not found.")
            self._reset(); return

        pop_id = None
        pop_layer = self._project.get_layer("exchange_pops")
        if pop_layer:
            for feat in pop_layer.getFeatures():
                if feat["area_id"] == self._project.area_id:
                    pop_id = feat["pop_id"]; break

        duct_id  = _next_piad_id(duct_layer, self._project.area_id)
        length_m = _calc_length(self._points)

        from_node      = self._node_ids[0]   or "unknown"
        from_node_type = self._node_types[0] or "UNKNOWN"
        to_node        = self._node_ids[-1]  or "unknown"
        to_node_type   = self._node_types[-1] or "UNKNOWN"

        dlg = DigitisePIAUGDuctDialog(
            duct_id=duct_id,
            from_node=from_node, from_node_type=from_node_type,
            to_node=to_node, to_node_type=to_node_type,
            length_m=length_m, area_id=self._project.area_id, pop_id=pop_id,
        )
        if dlg.exec_() != QDialog.Accepted:
            self._reset(); return

        attrs = dlg.get_attributes()
        feat = QgsFeature(duct_layer.fields())
        feat.setGeometry(QgsGeometry.fromPolylineXY(self._points))
        for fname, fvalue in attrs.items():
            idx = duct_layer.fields().indexOf(fname)
            if idx >= 0 and fvalue is not None:
                feat.setAttribute(idx, fvalue)

        duct_layer.startEditing()
        if duct_layer.addFeature(feat):
            duct_layer.commitChanges(); duct_layer.triggerRepaint()
            tl = QgsProject.instance().layerTreeRoot().findLayer(duct_layer.id())
            if tl: tl.setItemVisibilityChecked(True)
            self.placed.emit(duct_id)
        else:
            duct_layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to write PIA UG Duct feature.")

        self._reset()

    def _reset(self):
        self._points = []; self._node_ids = []; self._node_types = []
        self._rubber.reset(); self._snap_rubber.reset()

    def deactivate(self):
        try: self._rubber.reset(); self._canvas.scene().removeItem(self._rubber)
        except Exception: pass
        try: self._snap_rubber.reset(); self._canvas.scene().removeItem(self._snap_rubber)
        except Exception: pass
        self._canvas.refresh()
        super().deactivate()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reset(); self._canvas.unsetMapTool(self)
        elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
            if self._points:
                self._points.pop(); self._node_ids.pop(); self._node_types.pop()
                self._rubber.removeLastPoint()
