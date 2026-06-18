# -*- coding: utf-8 -*-
"""
Conductor - Digitise PIA UG Drop Tool (PIA)
Multi-vertex rubber-band digitising mirroring native QGIS behaviour:
  LMB click 1       -> start, snaps to PIA_UG_CHAMBER
  LMB (subsequent)  -> add vertices freely along pavement/verge
  Mouse move        -> live floating segment from last vertex to cursor
  LMB on premises   -> snaps to premises point
  RMB               -> finish and save (requires >=2 points)
  Ctrl+Z            -> undo last vertex
  Esc               -> cancel and exit
Writes to drop_ducts with drop_type = PIA_UG_DROP.
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsFeature, QgsGeometry, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeatureRequest, QgsRectangle, QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from ..conductor_utils import get_layer, fld, val, LayerEditContext
from ..conductor_utils import line_length_m, to_project_crs


def _to_27700(canvas, canvas_pt):
    return to_project_crs(canvas, canvas_pt)


def _to_canvas(canvas, pt):
    src = QgsCoordinateReferenceSystem("EPSG:27700")
    dst = canvas.mapSettings().destinationCrs()
    if src == dst: return pt
    return QgsCoordinateTransform(src, dst, QgsProject.instance()).transform(pt)


def _cursor_to_27700(canvas, event_pos):
    canvas_pt = canvas.getCoordinateTransform().toMapCoordinates(event_pos)
    return _to_27700(canvas, canvas_pt)


def _snap_start(canvas, project, pos, radius_px=16):
    canvas_pt = canvas.getCoordinateTransform().toMapCoordinates(pos)
    pt = _to_27700(canvas, canvas_pt)
    r  = canvas.mapUnitsPerPixel() * radius_px
    rect = QgsRectangle(pt.x()-r, pt.y()-r, pt.x()+r, pt.y()+r)
    best_dist = r; best_pt = None; best_id = None
    layer = project.get_layer("chambers")
    if layer:
        for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
            if feat["chamber_type"] != "PIA_UG_CHAMBER":
                continue
            fp = feat.geometry().asPoint()
            d  = math.hypot(fp.x()-pt.x(), fp.y()-pt.y())
            if d < best_dist:
                best_dist = d; best_pt = fp; best_id = feat["chamber_id"]
    return best_pt, best_id


def _snap_premises(canvas, project, pos, radius_px=16):
    canvas_pt = canvas.getCoordinateTransform().toMapCoordinates(pos)
    pt = _to_27700(canvas, canvas_pt)
    r  = canvas.mapUnitsPerPixel() * radius_px
    rect = QgsRectangle(pt.x()-r, pt.y()-r, pt.x()+r, pt.y()+r)
    best_dist = r; best_pt = None; best_uprn = None
    layer = project.get_layer("premises")
    if layer:
        for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
            fp = feat.geometry().asPoint()
            d  = math.hypot(fp.x()-pt.x(), fp.y()-pt.y())
            if d < best_dist:
                best_dist = d; best_pt = fp; best_uprn = str(feat["uprn"])
    return best_pt, best_uprn


def _next_id(layer, area_id):
    prefix = f"{area_id}-UGDROP-"
    used = set()
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
    except Exception: pass


class DigitisePIAUGDropMapTool(QgsMapTool):

    placed = pyqtSignal(str)

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self._points   = []
        self._start_id = None
        self._uprn     = None

        # Committed path - light purple
        self._rubber = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._rubber.setColor(QColor(187, 136, 204, 220))
        self._rubber.setWidth(2)

        # Floating segment - lighter
        self._float_rubber = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._float_rubber.setColor(QColor(187, 136, 204, 120))
        self._float_rubber.setWidth(1)

        # Snap indicator
        self._snap_rubber = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self._snap_rubber.setColor(QColor(187, 136, 204, 220))
        self._snap_rubber.setIconSize(10)

        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasMoveEvent(self, event):
        self._snap_rubber.reset(QgsWkbTypes.PointGeometry)

        if not self._points:
            pt, _ = _snap_start(self._canvas, self._project, event.pos())
            if pt:
                self._snap_rubber.addPoint(_to_canvas(self._canvas, pt), True)
        else:
            pt_premises, _ = _snap_premises(self._canvas, self._project, event.pos())
            cursor_pt = pt_premises if pt_premises else _cursor_to_27700(self._canvas, event.pos())
            if pt_premises:
                self._snap_rubber.addPoint(_to_canvas(self._canvas, pt_premises), True)
            self._float_rubber.reset(QgsWkbTypes.LineGeometry)
            self._float_rubber.addPoint(_to_canvas(self._canvas, self._points[-1]))
            self._float_rubber.addPoint(_to_canvas(self._canvas, cursor_pt), True)

    def canvasPressEvent(self, event):
        if event.button() == Qt.RightButton:
            if len(self._points) >= 2:
                self._save()
            else:
                self._reset()
                _info("Drop cancelled. Click a PIA UG Chamber to begin. Esc to exit.")
            return

        if event.button() != Qt.LeftButton:
            return

        if not self._points:
            pt, chamber_id = _snap_start(self._canvas, self._project, event.pos())
            if pt is None:
                QMessageBox.warning(
                    None, "Conductor - No PIA UG Chamber Found",
                    "No PIA UG Chamber found near that location.\n\n"
                    "PIA UG drops must start from a PIA UG Chamber."
                )
                return
            self._points.append(pt)
            self._start_id = chamber_id
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            self._rubber.addPoint(_to_canvas(self._canvas, pt), True)
            _info(f"Start: PIA UG Chamber {chamber_id} - click to add vertices along route. RMB to save.")
        else:
            pt_premises, uprn = _snap_premises(self._canvas, self._project, event.pos())
            if pt_premises:
                pt = pt_premises
                self._uprn = uprn
                _info(f"Premises UPRN {uprn} - RMB to save.")
            else:
                pt = _cursor_to_27700(self._canvas, event.pos())
                _info(f"Vertex added ({len(self._points) + 1}) - keep clicking or RMB to finish.")

            self._points.append(pt)
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            for p in self._points:
                self._rubber.addPoint(_to_canvas(self._canvas, p))
            self._rubber.show()

    def canvasDoubleClickEvent(self, event):
        pass

    def _save(self):
        layer = self._project.get_layer("drop_ducts")
        if not layer:
            QMessageBox.critical(None, "Conductor", "drop_ducts layer not found.")
            self._reset(); return

        drop_id  = _next_id(layer, self._project.area_id)
        length_m = line_length_m(self._points)

        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPolylineXY(self._points))

        attrs = {
            "ddct_id":      drop_id,
            "drop_type":    "PIA_UG_DROP",
            "from_chamber": self._start_id,
            "uprn":         int(self._uprn) if self._uprn and self._uprn.isdigit() else None,
            "area_id":      self._project.area_id,
            "length_m":     length_m,
            "status":       "PROPOSED",
        }
        for k, v in attrs.items():
            idx = layer.fields().indexOf(k)
            if idx >= 0 and v is not None:
                feat.setAttribute(idx, v)

        layer.startEditing()
        if layer.addFeature(feat):
            layer.commitChanges(); layer.triggerRepaint()
            tl = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
            if tl: tl.setItemVisibilityChecked(True)
            self.placed.emit(drop_id)
            self._reset()
            _info(f"{drop_id} saved ({length_m:.0f}m) - click next chamber to start another. Esc to exit.")
        else:
            layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to save PIA UG drop.")
            self._reset()

    def _reset(self):
        self._points   = []
        self._start_id = None
        self._uprn     = None
        for rb in (self._rubber, self._float_rubber, self._snap_rubber):
            rb.reset()

    def deactivate(self):
        for rb in (self._rubber, self._float_rubber, self._snap_rubber):
            try: rb.reset(); self._canvas.scene().removeItem(rb)
            except Exception: pass
        self._canvas.refresh()
        super().deactivate()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reset(); self._canvas.unsetMapTool(self)
        elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
            if len(self._points) > 1:
                self._points.pop()
                self._rubber.reset(QgsWkbTypes.LineGeometry)
                for p in self._points:
                    self._rubber.addPoint(_to_canvas(self._canvas, p))
                _info(f"Vertex removed - {len(self._points)} remaining.")
