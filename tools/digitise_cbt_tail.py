# -*- coding: utf-8 -*-
"""
Conductor — Digitise CBT Tail
Standalone tool. Click a CBT to anchor the start, trace back to a UG joint
or chamber, right-click to finish. Saves to cables layer with cable_type=CBT_TAIL.
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
    QgsFeatureRequest, QgsRectangle, QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from ..conductor_utils import (
    get_layer, LayerEditContext,
    NAVY, TEAL, ORANGE, LIGHT, WHITE, MID,
    BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE,
    SECTION_STYLE, MONO_STYLE, CALC_STYLE,
    line_length_m,
)


def _next_tail_id(cable_layer, area_id):
    existing = set()
    prefix = f"{area_id}-TAIL-"
    for feat in cable_layer.getFeatures():
        cid = feat["cable_id"] or ""
        if cid.startswith(prefix):
            try:
                existing.add(int(cid.replace(prefix, "")))
            except ValueError:
                pass
    n = 1
    while n in existing:
        n += 1
    return f"{prefix}{n:03d}"


def _snap_to_cbt(canvas, project, canvas_pos, radius_px=14):
    """Snap to joints with joint_type = CBT."""
    canvas_crs = canvas.mapSettings().destinationCrs()
    target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
    canvas_pt  = canvas.getCoordinateTransform().toMapCoordinates(canvas_pos)
    if canvas_crs != target_crs:
        xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
        pt_27700 = xform.transform(canvas_pt)
    else:
        pt_27700 = canvas_pt

    radius = canvas.mapUnitsPerPixel() * radius_px
    rect = QgsRectangle(
        pt_27700.x() - radius, pt_27700.y() - radius,
        pt_27700.x() + radius, pt_27700.y() + radius,
    )
    layer = project.get_layer("joints")
    if not layer:
        return None, None

    best_dist = radius
    best_feat = None
    for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
        if feat["joint_type"] != "CBT":
            continue
        fp   = feat.geometry().asPoint()
        dist = math.sqrt((fp.x() - pt_27700.x())**2 + (fp.y() - pt_27700.y())**2)
        if dist < best_dist:
            best_dist = dist
            best_feat = feat

    if best_feat:
        return best_feat.geometry().asPoint(), best_feat["joint_id"]
    return None, None


def _snap_to_ug_node(canvas, project, canvas_pos, radius_px=14):
    """Snap to joints or chambers -- UG end of the tail."""
    canvas_crs = canvas.mapSettings().destinationCrs()
    target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
    canvas_pt  = canvas.getCoordinateTransform().toMapCoordinates(canvas_pos)
    if canvas_crs != target_crs:
        xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
        pt_27700 = xform.transform(canvas_pt)
    else:
        pt_27700 = canvas_pt

    radius = canvas.mapUnitsPerPixel() * radius_px
    rect = QgsRectangle(
        pt_27700.x() - radius, pt_27700.y() - radius,
        pt_27700.x() + radius, pt_27700.y() + radius,
    )
    snap_layers = [
        ("joints",   "joint_id",   "JOINT"),
        ("chambers", "chamber_id", "CHAMBER"),
    ]
    best_dist = radius
    best_pt   = None
    best_id   = None
    best_type = None
    for layer_name, id_field, node_type in snap_layers:
        layer = project.get_layer(layer_name)
        if not layer or layer.featureCount() == 0:
            continue
        for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
            fp   = feat.geometry().asPoint()
            dist = math.sqrt((fp.x() - pt_27700.x())**2 + (fp.y() - pt_27700.y())**2)
            if dist < best_dist:
                best_dist = dist
                best_pt   = fp
                best_id   = feat[id_field]
                best_type = node_type
    return best_pt, best_id, best_type


# =============================================================================
# DIALOG
# =============================================================================

class DigitiseCBTTailDialog(QDialog):

    def __init__(self, tail_id, cbt_id, ug_node_id, ug_node_type, length_m,
                 area_id, pop_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CBT Tail")
        self.setMinimumWidth(480)
        self.setModal(True)

        self._tail_id      = tail_id
        self._cbt_id       = cbt_id
        self._ug_node_id   = ug_node_id
        self._ug_node_type = ug_node_type
        self._length_m     = length_m
        self._area_id      = area_id
        self._pop_id       = pop_id
        self._build_ui()

    def _lbl(self, t):
        l = QLabel(t); l.setStyleSheet(LABEL_STYLE); return l

    def _section(self, t):
        l = QLabel(t); l.setStyleSheet(SECTION_STYLE); return l

    def _divider(self):
        f = QFrame(); f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"color:{MID}; margin:4px 0px;"); return f

    def _ro(self, t, style=MONO_STYLE):
        e = QLineEdit(str(t)); e.setReadOnly(True); e.setStyleSheet(style)
        return e

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr = QLabel(f"  CBT Tail  --  {self._tail_id}")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        sub = QLabel(
            f"  CBT: {self._cbt_id}  ->  "
            f"{self._ug_node_type}: {self._ug_node_id}  .  {self._length_m} m"
        )
        sub.setFixedHeight(24)
        sub.setStyleSheet(f"background:{TEAL}; color:{WHITE}; font-size:11px; padding-left:8px;")
        root.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{LIGHT}; border:none;")

        fw = QFrame(); fw.setStyleSheet(f"background:{LIGHT};")
        fl = QVBoxLayout(fw); fl.setContentsMargins(20, 14, 20, 8); fl.setSpacing(8)

        fl.addWidget(self._section("IDENTITY"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)
        f1.addRow(self._lbl("Tail ID"),      self._ro(self._tail_id))
        f1.addRow(self._lbl("From (CBT)"),   self._ro(self._cbt_id))
        f1.addRow(self._lbl("To (UG Node)"), self._ro(f"{self._ug_node_type}: {self._ug_node_id}"))
        f1.addRow(self._lbl("Length (m)"),   self._ro(f"{self._length_m} m", CALC_STYLE))

        self.fibre_count = QComboBox()
        self.fibre_count.addItems(["1"])
        self.fibre_count.setCurrentText("1")
        self.fibre_count.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Fibre Count *"), self.fibre_count)

        self.fibre_type = QComboBox()
        self.fibre_type.addItems(["G.652D", "G.657A1", "G.657A2"])
        self.fibre_type.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Fibre Type"), self.fibre_type)

        self.status = QComboBox()
        self.status.addItems(["PROPOSED", "SURVEY", "INSTALLED", "LIVE"])
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

        br = QHBoxLayout(); br.setContentsMargins(20, 12, 20, 16); br.addStretch()
        cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
        cancel.clicked.connect(self.reject); br.addWidget(cancel)
        save = QPushButton("Save Tail"); save.setStyleSheet(BTN_PRIMARY)
        save.clicked.connect(self.accept); br.addWidget(save)
        root.addLayout(br)

    def get_attributes(self):
        return {
            "cable_id":       self._tail_id,
            "area_id":        self._area_id,
            "pop_id":         self._pop_id,
            "duct_id":        "",
            "cable_type":     "CBT_TAIL",
            "fibre_count":    int(self.fibre_count.currentText()),
            "tube_count":     0,
            "fibre_type":     self.fibre_type.currentText(),
            "from_node":      self._cbt_id,
            "from_node_type": "CBT",
            "to_node":        self._ug_node_id,
            "to_node_type":   self._ug_node_type,
            "length_m":       self._length_m,
            "status":         self.status.currentText(),
            "notes":          self.notes.text().strip(),
        }


# =============================================================================
# MAP TOOL
# =============================================================================

class DigitiseCBTTailMapTool(QgsMapTool):
    """
    Two-phase standalone tool:
      Phase 1 — click a CBT to anchor the start (snaps to CBTs only)
      Phase 2 — trace route back to UG joint/chamber, right-click to finish
    Ctrl+Z undoes last vertex. Esc cancels.
    """

    placed = pyqtSignal(str)

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project

        self._phase    = 1   # 1 = waiting for CBT click, 2 = drawing tail
        self._cbt_id   = None
        self._points   = []
        self._end_id   = None
        self._end_type = None

        self._rubber = QgsRubberBand(self._canvas, QgsWkbTypes.LineGeometry)
        self._rubber.setColor(QColor(255, 140, 0, 220))
        self._rubber.setWidth(2)

        self._snap_rubber = QgsRubberBand(self._canvas, QgsWkbTypes.PointGeometry)
        self._snap_rubber.setColor(QColor(200, 90, 0, 220))
        self._snap_rubber.setIconSize(10)

        self.setCursor(QCursor(Qt.CrossCursor))

    def _to_27700(self, canvas_pt):
        canvas_crs = self._canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
        if canvas_crs == target_crs:
            return canvas_pt
        xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
        return xform.transform(canvas_pt)

    def _to_canvas(self, pt_27700):
        canvas_crs = self._canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
        if canvas_crs == target_crs:
            return pt_27700
        xform = QgsCoordinateTransform(target_crs, canvas_crs, QgsProject.instance())
        return xform.transform(pt_27700)

    def canvasMoveEvent(self, event):
        self._snap_rubber.reset(QgsWkbTypes.PointGeometry)
        if self._phase == 1:
            pt, _ = _snap_to_cbt(self._canvas, self._project, event.pos())
        else:
            pt, _, _ = _snap_to_ug_node(self._canvas, self._project, event.pos())
        if pt:
            self._snap_rubber.addPoint(self._to_canvas(pt), True)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._phase == 1:
                pt, cbt_id = _snap_to_cbt(self._canvas, self._project, event.pos())
                if not pt:
                    QMessageBox.warning(None, "Conductor -- CBT Tail",
                        "No CBT found near that location.\nClick directly on a CBT to start the tail.")
                    return
                self._cbt_id = cbt_id
                self._points = [pt]
                self._rubber.addPoint(self._to_canvas(pt), True)
                self._phase = 2
            else:
                snapped_pt, node_id, node_type = _snap_to_ug_node(
                    self._canvas, self._project, event.pos()
                )
                if snapped_pt:
                    pt             = snapped_pt
                    self._end_id   = node_id
                    self._end_type = node_type
                else:
                    pt             = self._to_27700(self.toMapCoordinates(event.pos()))
                    self._end_id   = None
                    self._end_type = None
                self._points.append(pt)
                self._rubber.addPoint(self._to_canvas(pt), True)

        elif event.button() == Qt.RightButton:
            if self._phase == 1:
                self._canvas.unsetMapTool(self)
            else:
                self._finish()

    def canvasDoubleClickEvent(self, event):
        pass

    def _finish(self):
        self._rubber.reset()
        self._snap_rubber.reset()

        if len(self._points) < 2:
            QMessageBox.warning(None, "Conductor -- CBT Tail",
                "Need at least 2 points.\nLeft-click to add vertices, right-click to finish.")
            return

        if not self._end_id:
            QMessageBox.warning(None, "Conductor -- CBT Tail",
                "The tail end must snap to a joint or chamber.\n\n"
                "Click closer to the UG joint or chamber before right-clicking to finish.")
            self._reset()
            return

        cable_layer = self._project.get_layer("cables")
        if not cable_layer:
            QMessageBox.critical(None, "Conductor", "Cables layer not found.")
            self._reset()
            return

        pop_layer = self._project.get_layer("exchange_pops")
        pop_id = ""
        if pop_layer:
            for feat in pop_layer.getFeatures():
                if feat["area_id"] == self._project.area_id:
                    pop_id = feat["pop_id"]
                    break

        tail_id  = _next_tail_id(cable_layer, self._project.area_id)
        length_m = round(line_length_m(self._points), 1)

        # Hard stop if tail exceeds 350m. This is a buildability limit, not a
        # preference: the pole-mounted CBT (Corning OptiSheath 12-port 350m
        # drop) is rated for a drop reach of 350m, so a longer tail cannot be
        # built with the specified hardware. The designer must shorten the run
        # (reposition the CBT or the underground joint) before saving. The
        # 50m-rounded figure is shown for reference only; the true measured
        # length is what gets stored, so per-metre costing stays accurate.
        CBT_TAIL_MAX_M = 350
        if length_m > CBT_TAIL_MAX_M:
            rounded = round(length_m / 50) * 50
            QMessageBox.critical(
                None,
                "CBT Tail — Length Exceeded",
                f"This CBT tail is {length_m:.0f}m (~{rounded:.0f}m rounded to nearest 50m), "
                f"which exceeds the {CBT_TAIL_MAX_M}m maximum drop reach of the "
                f"pole-mounted CBT.\n\n"
                f"A tail this long cannot be built with the specified CBT hardware. "
                f"Reposition the CBT or the underground joint to shorten the run, "
                f"then re-digitise.\n\n"
                f"This route has not been saved.",
                QMessageBox.Ok
            )
            self._reset()
            return

        dlg = DigitiseCBTTailDialog(
            tail_id      = tail_id,
            cbt_id       = self._cbt_id,
            ug_node_id   = self._end_id,
            ug_node_type = self._end_type,
            length_m     = length_m,
            area_id      = self._project.area_id,
            pop_id       = pop_id,
        )

        if dlg.exec_() != QDialog.Accepted:
            self._reset()
            return

        attrs = dlg.get_attributes()
        geom  = QgsGeometry.fromPolylineXY(self._points)

        feat = QgsFeature(cable_layer.fields())
        feat.setGeometry(geom)
        for fname, fvalue in attrs.items():
            idx = cable_layer.fields().indexOf(fname)
            if idx >= 0 and fvalue is not None:
                feat.setAttribute(idx, fvalue)

        cable_layer.startEditing()
        if cable_layer.addFeature(feat):
            cable_layer.commitChanges()
            cable_layer.triggerRepaint()
            tree_layer = QgsProject.instance().layerTreeRoot().findLayer(cable_layer.id())
            if tree_layer:
                tree_layer.setItemVisibilityChecked(True)
            self.placed.emit(tail_id)
        else:
            cable_layer.rollBack()
            QMessageBox.critical(None, "Conductor -- Error", "Failed to write CBT tail.")

        self._reset()
        # Stay active -- ready to draw next tail immediately
        self._phase = 1

    def _reset(self):
        self._phase    = 1
        self._cbt_id   = None
        self._points   = []
        self._end_id   = None
        self._end_type = None
        self._rubber.reset()
        self._snap_rubber.reset()

    def deactivate(self):
        try:
            self._rubber.reset()
            self._canvas.scene().removeItem(self._rubber)
        except Exception:
            pass
        try:
            self._snap_rubber.reset()
            self._canvas.scene().removeItem(self._snap_rubber)
        except Exception:
            pass
        self._canvas.refresh()
        super().deactivate()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reset()
            self._canvas.unsetMapTool(self)
        elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
            if self._phase == 2 and len(self._points) > 1:
                self._points.pop()
                self._rubber.removeLastPoint()
                self._end_id   = None
                self._end_type = None
