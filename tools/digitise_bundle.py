# -*- coding: utf-8 -*-
"""
Conductor - Digitise Bundle Tool
Multi-vertex rubber-band digitising mirroring native QGIS behaviour:
  LMB click 1      -> start, snaps to joint
  LMB (subsequent) -> add vertices freely, snaps to drop_duct vertices
  Mouse move       -> live floating segment + snap to drop_duct vertices
  LMB on premises  -> snaps to premises point
  RMB              -> finish and save (requires >=2 points)
  Ctrl+Z           -> undo last vertex
  Esc              -> cancel and exit
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeatureRequest, QgsRectangle, QgsWkbTypes,
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
        [("joints",   "joint_id", "JOINT"),
         ("premises", "uprn",     "PREMISES")],
        snap_radius_px=radius_px, fallback=True, stringify_id=True)


def _snap_to_drop_duct_vertex(canvas, project, canvas_pos, radius_px=14):
    """Snap to any vertex of any drop_duct line so bundle mirrors duct route exactly."""
    canvas_crs = canvas.mapSettings().destinationCrs()
    target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
    canvas_pt  = canvas.getCoordinateTransform().toMapCoordinates(canvas_pos)
    if canvas_crs != target_crs:
        xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
        pt_27700 = xform.transform(canvas_pt)
    else:
        pt_27700 = canvas_pt

    radius = canvas.mapUnitsPerPixel() * radius_px
    rect   = QgsRectangle(
        pt_27700.x()-radius, pt_27700.y()-radius,
        pt_27700.x()+radius, pt_27700.y()+radius,
    )

    layer = project.get_layer("drop_ducts")
    if not layer:
        return None

    best_dist = radius
    best_pt   = None

    for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
        geom = feat.geometry()
        if geom is None:
            continue
        for v in geom.vertices():
            dist = math.sqrt((v.x() - pt_27700.x())**2 + (v.y() - pt_27700.y())**2)
            if dist < best_dist:
                best_dist = dist
                best_pt   = QgsPointXY(v.x(), v.y())

    return best_pt


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
        self._canvas  = canvas
        self._project = project
        self._points     = []
        self._node_ids   = []
        self._node_types = []

        # Committed path - amber
        self._rubber = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._rubber.setColor(QColor(212, 134, 10, 220))
        self._rubber.setWidth(2)

        # Floating segment - lighter amber
        self._float_rubber = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._float_rubber.setColor(QColor(212, 134, 10, 110))
        self._float_rubber.setWidth(1)

        # Snap indicator
        self._snap_rubber = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self._snap_rubber.setColor(QColor(200, 90, 0, 220))
        self._snap_rubber.setIconSize(10)

        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasMoveEvent(self, event):
        pt, node_id, node_type = _snap(self._canvas, self._project, event.pos())

        # Secondary snap: drop_duct vertices when no primary snap and mid-draw
        duct_pt = None
        if self._points and (not node_id or node_type == "FREE"):
            duct_pt = _snap_to_drop_duct_vertex(self._canvas, self._project, event.pos())

        snap_target = pt if (node_id and node_type != "FREE") else (duct_pt if duct_pt else pt)

        self._snap_rubber.reset(QgsWkbTypes.PointGeometry)
        if node_id and node_type != "FREE":
            self._snap_rubber.addPoint(_to_canvas(self._canvas, pt), True)
        elif duct_pt:
            self._snap_rubber.addPoint(_to_canvas(self._canvas, duct_pt), True)

        self._float_rubber.reset(QgsWkbTypes.LineGeometry)
        if self._points:
            self._float_rubber.addPoint(_to_canvas(self._canvas, self._points[-1]))
            self._float_rubber.addPoint(_to_canvas(self._canvas, snap_target), True)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt, node_id, node_type = _snap(self._canvas, self._project, event.pos())

            # Fallback to drop_duct vertex snap mid-draw
            if (not node_id or node_type == "FREE") and self._points:
                duct_pt = _snap_to_drop_duct_vertex(self._canvas, self._project, event.pos())
                if duct_pt:
                    pt = duct_pt
                    node_id   = None
                    node_type = "FREE"

            self._points.append(pt)
            self._node_ids.append(node_id)
            self._node_types.append(node_type)

            self._rubber.reset(QgsWkbTypes.LineGeometry)
            for p in self._points:
                self._rubber.addPoint(_to_canvas(self._canvas, p))
            self._rubber.show()

            if len(self._points) == 1:
                label = f"Joint {node_id}" if node_type == "JOINT" else "Free point"
                # Warn if start joint has no splitter — bundles must originate from splitter joints
                if node_type == "JOINT" and node_id:
                    joint_layer = self._project.get_layer("joints")
                    if joint_layer:
                        for jf in joint_layer.getFeatures():
                            if str(jf["joint_id"]) == str(node_id):
                                if not jf["has_splitter"]:
                                    _info(f"WARNING: {node_id} has no splitter — bundles should start from a splitter joint.")
                                else:
                                    _info(f"Start: {label} (splitter {jf['split_ratio']}) - click to add vertices. RMB to finish.")
                                break
                    else:
                        _info(f"Start: {label} - click to add vertices along drop duct route. RMB to finish.")
                else:
                    _info(f"Start: {label} - click to add vertices along drop duct route. RMB to finish.")
            elif node_type == "PREMISES":
                _info(f"Premises UPRN {node_id} - RMB to save.")
            else:
                _info(f"Vertex added ({len(self._points)}) - keep clicking or RMB to finish.")

        elif event.button() == Qt.RightButton:
            if len(self._points) < 2:
                self._reset()
                _info("Bundle cancelled - need at least 2 points. Esc to exit.")
                return
            self._save()

    def canvasDoubleClickEvent(self, event):
        pass

    def _save(self):
        layer = self._project.get_layer("bundles")
        if not layer:
            QMessageBox.critical(None, "Conductor", "bundles layer not found.")
            self._reset(); return

        bundle_id = _next_id(layer, self._project.area_id)
        length_m  = line_length_m(self._points)

        from_joint = self._node_ids[0] if self._node_types[0] == "JOINT" else None

        uprn = None
        if self._node_types[-1] == "PREMISES" and self._node_ids[-1]:
            last_id = self._node_ids[-1]
            if last_id and str(last_id).isdigit():
                uprn = int(last_id)

        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPolylineXY(self._points))

        attrs = {
            "bundle_id":   bundle_id,
            "area_id":     self._project.area_id,
            "from_joint":  from_joint,
            "uprn":        uprn,
            "fibre_count": 2,
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
            _info(f"{bundle_id} saved ({length_m:.0f}m) - click next joint. Esc to exit.")
        else:
            layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to save bundle.")
            self._reset()

    def _reset(self):
        self._points     = []
        self._node_ids   = []
        self._node_types = []
        self._rubber.reset(QgsWkbTypes.LineGeometry)
        self._float_rubber.reset(QgsWkbTypes.LineGeometry)
        self._snap_rubber.reset(QgsWkbTypes.PointGeometry)

    def deactivate(self):
        for rb in (self._rubber, self._float_rubber, self._snap_rubber):
            try: rb.reset(); self._canvas.scene().removeItem(rb)
            except Exception: pass
        self._canvas.refresh()
        super().deactivate()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reset()
            self._canvas.unsetMapTool(self)
        elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
            if self._points:
                self._points.pop()
                self._node_ids.pop()
                self._node_types.pop()
                self._rubber.reset(QgsWkbTypes.LineGeometry)
                for p in self._points:
                    self._rubber.addPoint(_to_canvas(self._canvas, p))
                _info(f"Vertex removed - {len(self._points)} remaining.")
