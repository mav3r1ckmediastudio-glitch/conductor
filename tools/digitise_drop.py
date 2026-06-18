# -*- coding: utf-8 -*-
"""
Conductor — Digitise Drop Duct Tool
Multi-vertex rubber-band digitising mirroring native QGIS behaviour:
  LMB         -> add vertex (snaps to joint / chamber / premises)
  Mouse move  -> live floating segment from last vertex to cursor
  LMB on premises -> final vertex snapped to premises point
  RMB         -> finish and save (requires >=2 points)
  Ctrl+Z      -> undo last vertex
  Esc         -> cancel and exit
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
        [("joints",   "joint_id",   "JOINT"),
         ("chambers", "chamber_id", "CHAMBER"),
         ("premises", "uprn",       "PREMISES")],
        snap_radius_px=radius_px, fallback=True, stringify_id=True)


def _next_id(layer, area_id):
    prefix = f"{area_id}-DDCT-"
    used   = set()
    for f in layer.getFeatures():
        v = f["ddct_id"] or ""
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


class DigitiseDropMapTool(QgsMapTool):

    placed = pyqtSignal(str)

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self._points     = []
        self._node_ids   = []
        self._node_types = []

        # Committed path - brown
        self._rubber = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._rubber.setColor(QColor(139, 69, 19, 220))
        self._rubber.setWidth(2)

        # Floating segment - lighter
        self._float_rubber = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._float_rubber.setColor(QColor(139, 69, 19, 120))
        self._float_rubber.setWidth(1)

        # Snap indicator
        self._snap_rubber = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self._snap_rubber.setColor(QColor(200, 90, 0, 220))
        self._snap_rubber.setIconSize(10)

        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasMoveEvent(self, event):
        pt, node_id, node_type = _snap(self._canvas, self._project, event.pos())

        self._snap_rubber.reset(QgsWkbTypes.PointGeometry)
        if node_id and node_type != "FREE":
            self._snap_rubber.addPoint(_to_canvas(self._canvas, pt), True)

        self._float_rubber.reset(QgsWkbTypes.LineGeometry)
        if self._points:
            self._float_rubber.addPoint(_to_canvas(self._canvas, self._points[-1]))
            self._float_rubber.addPoint(_to_canvas(self._canvas, pt), True)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt, node_id, node_type = _snap(self._canvas, self._project, event.pos())

            self._points.append(pt)
            self._node_ids.append(node_id)
            self._node_types.append(node_type)

            self._rubber.reset(QgsWkbTypes.LineGeometry)
            for p in self._points:
                self._rubber.addPoint(_to_canvas(self._canvas, p))
            self._rubber.show()

            if len(self._points) == 1:
                label = f"Joint {node_id}"   if node_type == "JOINT" else \
                        f"Chamber {node_id}" if node_type == "CHAMBER" else "Free point"
                _info(f"Start: {label} - keep clicking to add vertices. RMB to finish.")
            elif node_type == "PREMISES":
                _info(f"Premises UPRN {node_id} - RMB to save.")
            else:
                _info(f"Vertex added ({len(self._points)}) - keep clicking or RMB to finish.")

        elif event.button() == Qt.RightButton:
            if len(self._points) < 2:
                self._reset()
                _info("Drop cancelled - need at least 2 points. Esc to exit.")
                return
            self._save()

    def canvasDoubleClickEvent(self, event):
        pass

    def _save(self):
        layer = self._project.get_layer("drop_ducts")
        if not layer:
            QMessageBox.critical(None, "Conductor", "drop_ducts layer not found.")
            self._reset(); return

        drop_id  = _next_id(layer, self._project.area_id)
        length_m = line_length_m(self._points)

        from_chamber = None
        from_pole    = None
        drop_type    = None
        type1        = self._node_types[0]
        id1          = self._node_ids[0]

        if type1 == "CHAMBER" and id1 and id1 != "0":
            from_chamber = id1
        elif type1 == "JOINT" and id1 and id1 != "0":
            joint_layer = self._project.get_layer("joints")
            if joint_layer:
                for jf in joint_layer.getFeatures():
                    if str(jf["joint_id"]) == str(id1):
                        if str(jf["joint_type"] or "") == "CBT":
                            from_pole    = jf["pole_id"]
                            from_chamber = str(id1)   # CBT joint_id — BFS keys on this
                            drop_type    = "PIA_AERIAL_DROP"
                        else:
                            from_chamber = jf["chamber_id"]
                        break

        uprn = None
        last_id   = self._node_ids[-1]
        last_type = self._node_types[-1]
        if last_type == "PREMISES" and last_id and last_id.isdigit():
            uprn = int(last_id)

        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPolylineXY(self._points))

        attrs = {
            "ddct_id":      drop_id,
            "uprn":         uprn,
            "area_id":      self._project.area_id,
            "from_chamber": from_chamber,
            "from_pole":    from_pole,
            "length_m":     length_m,
            "status":       "PROPOSED",
            "drop_type":    drop_type,
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
            self.placed.emit(drop_id)
            _push_undo(
                self._project, "drop_ducts", "ADD",
                "ddct_id", drop_id,
                {f: feat[f] for f in feat.fields().names()},
                feat.geometry(),
                "Digitise Drop Duct " + str(drop_id)
            )
            self._reset()
            _info(f"{drop_id} saved ({length_m:.0f}m) - click to start next drop. Esc to exit.")
        else:
            layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to save drop duct.")
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
