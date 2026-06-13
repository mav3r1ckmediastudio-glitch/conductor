# -*- coding: utf-8 -*-
"""
Conductor — Digitise PIA UG Drop Tool (PIA)
Two-click workflow:
  LMB click 1 → start — snaps to PIA_UG_CHAMBER in chambers layer
  LMB click 2 → end   — snaps to premises
  RMB         → save and reset
Writes to drop_ducts with drop_type = PIA_UG_DROP.
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsFeature, QgsGeometry, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeatureRequest, QgsRectangle, QgsDistanceArea, QgsWkbTypes,
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


def _snap_start(canvas, project, pos, radius_px=16):
    """Snap to nearest PIA_UG_CHAMBER."""
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


def _snap_end(canvas, project, pos, radius_px=16):
    """Snap to nearest premises."""
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
    if best_pt is None:
        best_pt = pt
    return best_pt, best_uprn


def _calc_length(p1, p2):
    return line_length_m([p1, p2])


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
        self._pt1 = self._pt2 = self._id1 = self._uprn = None
        self._last_click_pos = None

        # Light purple rubber band
        self._rubber = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._rubber.setColor(QColor(187, 136, 204, 220))
        self._rubber.setWidth(2)

        self._snap_rubber = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
        self._snap_rubber.setColor(QColor(187, 136, 204, 220))
        self._snap_rubber.setIconSize(10)

        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasMoveEvent(self, event):
        self._snap_rubber.reset(QgsWkbTypes.PointGeometry)
        if self._pt1 is None:
            pt, _ = _snap_start(self._canvas, self._project, event.pos())
            if pt: self._snap_rubber.addPoint(_to_canvas(self._canvas, pt), True)
        else:
            pt, _ = _snap_end(self._canvas, self._project, event.pos())
            if pt: self._snap_rubber.addPoint(_to_canvas(self._canvas, pt), True)
            preview = pt or _to_27700(self._canvas, self.toMapCoordinates(event.pos()))
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            self._rubber.addPoint(_to_canvas(self._canvas, self._pt1))
            self._rubber.addPoint(_to_canvas(self._canvas, preview), True)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            if self._pt1 and self._pt2:
                self._save()
            else:
                self._reset()
                _info("Drop cancelled. Click a PIA UG Chamber to begin. Esc to exit.")
            return

        if event.button() != Qt.LeftButton:
            return

        current_pos = (event.pos().x(), event.pos().y())
        if current_pos == self._last_click_pos:
            return
        self._last_click_pos = current_pos

        if self._pt1 is None:
            pt, node_id = _snap_start(self._canvas, self._project, event.pos())
            if pt is None:
                QMessageBox.warning(
                    None, "Conductor — No PIA UG Chamber Found",
                    "No PIA UG Chamber found near that location.\n\n"
                    "PIA UG drops must start from a PIA UG Chamber."
                )
                return
            self._pt1 = pt; self._id1 = node_id
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            self._rubber.addPoint(_to_canvas(self._canvas, pt), True)
            _info(f"Start: PIA UG Chamber {node_id} — now click the premises. RMB to save.")
        else:
            pt, uprn = _snap_end(self._canvas, self._project, event.pos())
            self._pt2 = pt; self._uprn = uprn
            self._rubber.reset(QgsWkbTypes.LineGeometry)
            self._rubber.addPoint(_to_canvas(self._canvas, self._pt1), False)
            self._rubber.addPoint(_to_canvas(self._canvas, self._pt2), True)
            label = f"UPRN {uprn}" if uprn else "Free point"
            _info(f"End: {label} — RMB to save, or click to adjust.")

    def canvasDoubleClickEvent(self, event):
        pass

    def _save(self):
        layer = self._project.get_layer("drop_ducts")
        if not layer:
            QMessageBox.critical(None, "Conductor", "drop_ducts layer not found.")
            self._reset(); return

        drop_id  = _next_id(layer, self._project.area_id)
        length_m = _calc_length(self._pt1, self._pt2)

        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPolylineXY([self._pt1, self._pt2]))

        attrs = {
            "ddct_id":      drop_id,
            "drop_type":    "PIA_UG_DROP",
            "from_chamber": self._id1,
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
            _info(f"{drop_id} saved ({length_m}m) — click next chamber to start another. Esc to exit.")
        else:
            layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to save PIA UG drop.")
            self._reset()

    def _reset(self):
        self._pt1 = self._pt2 = self._id1 = self._uprn = None
        self._last_click_pos = None
        self._rubber.reset(QgsWkbTypes.LineGeometry)
        self._snap_rubber.reset(QgsWkbTypes.PointGeometry)

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
