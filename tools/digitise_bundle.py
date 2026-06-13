# -*- coding: utf-8 -*-
"""
Conductor — Digitise Bundle Tool
Two-click workflow:
  LMB click 1 → start point (secondary splitter joint)
  LMB click 2 → end point (premises / ONT)
  RMB         → save and reset
  Esc         → exit
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeatureRequest, QgsRectangle, QgsDistanceArea, QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from ..conductor_utils import get_layer, fld, val, LayerEditContext
from ..conductor_utils import line_length_m, snap_to_node, to_project_crs


def _to_27700(canvas, canvas_pt):
    return to_project_crs(canvas, canvas_pt)


def _to_canvas(canvas, pt_27700):
    src = QgsCoordinateReferenceSystem("EPSG:27700")
    dst = canvas.mapSettings().destinationCrs()
    if src == dst:
        return pt_27700
    return QgsCoordinateTransform(src, dst, QgsProject.instance()).transform(pt_27700)


def _snap(canvas, project, pos, radius_px=16):
    return snap_to_node(canvas, project, pos,
        [("joints", "joint_id", "JOINT"),
         ("premises", "uprn", "PREMISES")],
        snap_radius_px=radius_px, fallback=True, stringify_id=True)


def _calc_length(p1, p2):
    return line_length_m([p1, p2])


def _next_id(layer, area_id):
    prefix = f"{area_id}-BDL-"
    used   = set()
    for f in layer.getFeatures():
        v = f["bundle_id"] or ""
        if v.startswith(prefix):
            try: used.add(int(v[len(prefix):]))
            except ValueError: pass
    n = 1
    while n in used: n += 1
    return f"{prefix}{n:03d}"


def _info(msg):
    try:
        from qgis.utils import iface
        iface.messageBar().pushInfo("Conductor", msg)
    except Exception:
        pass


class DigitiseBundleMapTool(QgsMapTool):

    placed = pyqtSignal(str)

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas         = canvas
        self._project        = project
        self._pt1            = None   # start point (27700) — joint
        self._id1            = None   # joint_id
        self._pt2            = None   # end point (27700) — premises
        self._id2            = None   # uprn
        self._last_click_pos = None   # guard against double-click phantom release

        self._rubber = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._rubber.setColor(QColor(212, 134, 10, 220))   # amber
        self._rubber.setWidth(2)

        self.setCursor(QCursor(Qt.CrossCursor))

    # ── EVENTS ───────────────────────────────────────────────────────────────

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            if self._pt1 and self._pt2:
                self._save()
            else:
                self._reset()
                _info("Bundle cancelled. Click a joint to begin. Esc to exit.")
            return

        if event.button() != Qt.LeftButton:
            return

        # Guard against double-click phantom release
        current_pos = (event.pos().x(), event.pos().y())
        if current_pos == self._last_click_pos:
            return
        self._last_click_pos = current_pos

        pt, node_id, node_type = _snap(self._canvas, self._project, event.pos())

        if self._pt1 is None:
            # First click — must be a joint
            self._pt1 = pt
            self._id1 = node_id if node_type == "JOINT" else None
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            self._rubber.addPoint(_to_canvas(self._canvas, pt), True)
            label = f"Joint {node_id}" if node_type == "JOINT" else "Free point (no joint snapped)"
            _info(f"Start: {label} — now click the premises end point. RMB to save.")

        elif self._pt2 is None:
            # Second click — end point
            self._pt2 = pt
            self._id2 = node_id if node_type == "PREMISES" else None
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            self._rubber.addPoint(_to_canvas(self._canvas, self._pt1), False)
            self._rubber.addPoint(_to_canvas(self._canvas, self._pt2), True)
            label = f"UPRN {node_id}" if node_type == "PREMISES" else "Free point"
            _info(f"End: {label} — RMB to save, or click to adjust.")

        else:
            # Third+ click — update end point
            self._pt2 = pt
            self._id2 = node_id if node_type == "PREMISES" else None
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            self._rubber.addPoint(_to_canvas(self._canvas, self._pt1), False)
            self._rubber.addPoint(_to_canvas(self._canvas, self._pt2), True)
            _info("End point updated — RMB to save.")

    def canvasDoubleClickEvent(self, event):
        pass  # swallow double-click

    # ── SAVE ─────────────────────────────────────────────────────────────────

    def _save(self):
        layer = self._project.get_layer("bundles")
        if not layer:
            QMessageBox.critical(None, "Conductor", "bundles layer not found.")
            self._reset()
            return

        bundle_id = _next_id(layer, self._project.area_id)
        length_m  = _calc_length(self._pt1, self._pt2)

        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPolylineXY([self._pt1, self._pt2]))

        attrs = {
            "bundle_id":   bundle_id,
            "area_id":     self._project.area_id,
            "from_joint":  self._id1,
            "uprn":        int(self._id2) if self._id2 and self._id2.isdigit() else None,
            "fibre_count": 2,       # Gigaloch default — 2F bundle to ONT
            "length_m":    length_m,
            "status":      "PROPOSED",
        }
        for k, v in attrs.items():
            idx = layer.fields().indexOf(k)
            if idx >= 0 and v is not None:
                feat.setAttribute(idx, v)

        layer.startEditing()
        if layer.addFeature(feat):
            layer.commitChanges()
            layer.triggerRepaint()
            tl = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
            if tl: tl.setItemVisibilityChecked(True)
            self.placed.emit(bundle_id)
            self._reset()
            _info(f"{bundle_id} saved ({length_m}m) — click next joint. Esc to exit.")
        else:
            layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to save bundle.")
            self._reset()

    # ── CLEANUP ───────────────────────────────────────────────────────────────

    def _reset(self):
        self._pt1 = self._pt2 = self._id1 = self._id2 = None
        self._last_click_pos = None
        self._rubber.reset(QgsWkbTypes.LineGeometry)

    def deactivate(self):
        try:
            self._rubber.reset()
            self._canvas.scene().removeItem(self._rubber)
        except Exception:
            pass
        self._canvas.refresh()
        super().deactivate()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reset()
            self._canvas.unsetMapTool(self)
