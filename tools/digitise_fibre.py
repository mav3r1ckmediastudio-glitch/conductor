# -*- coding: utf-8 -*-
"""
Conductor — Digitise Fibre Cable Tool
Draws a fibre cable between two joints (or cabinet).
Snaps only to joints and cabinet.
Offers to copy geometry from the parent duct.
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox,
    QPushButton, QFrame, QMessageBox, QScrollArea,
)
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeatureRequest, QgsRectangle, QgsDistanceArea, QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE, MONO_STYLE, CALC_STYLE
from ..conductor_utils import line_length_m

def _next_cable_id(layer, area_id):
    existing = set()
    prefix = f"{area_id}-CBL-"
    for feat in layer.getFeatures():
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


def _calc_length(points):
    return line_length_m(points)


def _snap_to_fibre_node(canvas, project, canvas_pos, radius_px=14):
    """Snap to joints or cabinet."""
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

    snap_layers = [
        ("joints",       "joint_id", "JOINT"),
        ("exchange_pops","pop_id",   "POP"),
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
            dist = math.sqrt((fp.x()-pt_27700.x())**2+(fp.y()-pt_27700.y())**2)
            if dist < best_dist:
                best_dist = dist
                best_pt   = fp
                best_id   = feat[id_field]
                best_type = node_type

    return best_pt, best_id, best_type


def _find_duct_for_nodes(project, from_id, to_id):
    """Try to find a duct that connects the same chambers as the joints being connected."""
    duct_layer = project.get_layer("ducts")
    joint_layer = project.get_layer("joints")
    if not duct_layer or not joint_layer:
        return None

    # Get chamber_ids for the joints
    chambers = {}
    for feat in joint_layer.getFeatures():
        jid = feat["joint_id"]
        if jid in (from_id, to_id):
            chambers[jid] = feat["chamber_id"]

    if len(chambers) < 2:
        return None

    from_cmbr = chambers.get(from_id)
    to_cmbr   = chambers.get(to_id)

    if not from_cmbr or not to_cmbr:
        return None

    for feat in duct_layer.getFeatures():
        fn = feat["from_node"]; tn = feat["to_node"]
        if (fn == from_cmbr and tn == to_cmbr) or (fn == to_cmbr and tn == from_cmbr):
            return feat

    return None


# ═══════════════════════════════════════════════════════════════════════════
# FIBRE CABLE FORM
# ═══════════════════════════════════════════════════════════════════════════

class DigitiseFibreDialog(QDialog):

    def __init__(self, cable_id, area_id, pop_id, from_node, from_type,
                 to_node, to_type, length_m, duct_id=None, parent=None,
                 default_cable_type=None):
        super().__init__(parent)
        self.setWindowTitle("Digitise Fibre Cable")
        self.setMinimumWidth(500)
        self.setMaximumHeight(700)
        self.setModal(True)

        self._cable_id           = cable_id
        self._area_id            = area_id
        self._pop_id             = pop_id
        self._from_node          = from_node
        self._from_type          = from_type
        self._to_node            = to_node
        self._to_type            = to_type
        self._length_m           = length_m
        self._duct_id            = duct_id
        self._default_cable_type = default_cable_type
        self._build_ui()
        if default_cable_type:
            idx = self.cable_type.findText(default_cable_type)
            if idx >= 0:
                self.cable_type.setCurrentIndex(idx)

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

        hdr = QLabel(f"  Fibre Cable  —  {self._cable_id}")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        sub = QLabel(
            f"  {self._from_type}: {self._from_node}  →  "
            f"{self._to_type}: {self._to_node}  ·  {self._length_m} m"
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
        f1.addRow(self._lbl("Cable ID"),   self._ro(self._cable_id))
        f1.addRow(self._lbl("Length (m)"), self._ro(f"{self._length_m} m", CALC_STYLE))

        duct_text = self._duct_id if self._duct_id else "— not matched"
        f1.addRow(self._lbl("Parent Duct"), self._ro(duct_text,
            CALC_STYLE if self._duct_id else MONO_STYLE))

        self.cable_type = QComboBox()
        self.cable_type.addItems(["FEEDER", "DISTRIBUTION", "BACKHAUL", "AERIAL"])
        self.cable_type.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Cable Type *"), self.cable_type)

        self.fibre_count = QComboBox()
        self.fibre_count.addItems(["12", "24", "48", "96", "144"])
        self.fibre_count.setCurrentText("48")
        self.fibre_count.setStyleSheet(INPUT_STYLE)
        self.fibre_count.currentTextChanged.connect(self._update_tubes)
        f1.addRow(self._lbl("Fibre Count *"), self.fibre_count)

        self._tube_display = self._ro("4", CALC_STYLE)
        f1.addRow(self._lbl("Tube Count"), self._tube_display)

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
        save = QPushButton("Save Cable"); save.setStyleSheet(BTN_PRIMARY)
        save.clicked.connect(self.accept); br.addWidget(save)
        root.addLayout(br)

    def _update_tubes(self, count):
        try:
            self._tube_display.setText(str(int(count) // 12))
        except ValueError:
            pass

    def get_attributes(self):
        fc = int(self.fibre_count.currentText())
        return {
            "cable_id":       self._cable_id,
            "area_id":        self._area_id,
            "pop_id":         self._pop_id,
            "duct_id":        self._duct_id or "",
            "cable_type":     self.cable_type.currentText(),
            "fibre_count":    fc,
            "tube_count":     fc // 12,
            "fibre_type":     self.fibre_type.currentText(),
            "from_node":      self._from_node,
            "from_node_type": self._from_type,
            "to_node":        self._to_node,
            "to_node_type":   self._to_type,
            "length_m":       self._length_m,
            "status":         self.status.currentText(),
            "notes":          self.notes.text().strip(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# MAP TOOL
# ═══════════════════════════════════════════════════════════════════════════

class DigitiseFibreMapTool(QgsMapTool):
    """Draw fibre cable — snaps only to joints and cabinet."""

    placed = pyqtSignal(str)

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self._points  = []
        self._node_ids   = []
        self._node_types = []

        self._rubber = QgsRubberBand(self._canvas, QgsWkbTypes.LineGeometry)
        self._rubber.setColor(QColor(29, 122, 110, 200))
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
        snapped_pt, _, _ = _snap_to_fibre_node(self._canvas, self._project, event.pos())
        self._snap_rubber.reset(QgsWkbTypes.PointGeometry)
        if snapped_pt:
            self._snap_rubber.addPoint(self._to_canvas(snapped_pt), True)

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            snapped_pt, node_id, node_type = _snap_to_fibre_node(
                self._canvas, self._project, event.pos()
            )
            if snapped_pt:
                pt_27700 = snapped_pt
                nid, ntype = node_id, node_type
            else:
                pt_27700 = self._to_27700(self.toMapCoordinates(event.pos()))
                nid, ntype = None, None

            self._points.append(pt_27700)
            self._node_ids.append(nid)
            self._node_types.append(ntype)
            self._rubber.addPoint(self._to_canvas(pt_27700), True)

        elif event.button() == Qt.RightButton:
            if len(self._points) < 2:
                QMessageBox.warning(None, "Conductor",
                    "A fibre cable needs at least 2 points.\n"
                    "Left-click to add vertices, right-click to finish.")
                return
            self._finish()

    def canvasDoubleClickEvent(self, event):
        pass

    def _make_dialog(self, cable_id, from_node, from_type, to_node, to_type, length_m, pop_id, duct_id):
        """Create the cable dialog. Override in subclasses to customise defaults."""
        return DigitiseFibreDialog(
            cable_id=cable_id, area_id=self._project.area_id,
            pop_id=pop_id, from_node=from_node, from_type=from_type,
            to_node=to_node, to_type=to_type, length_m=length_m,
            duct_id=duct_id,
        )

    def _finish(self):
        self._rubber.reset()
        self._snap_rubber.reset()

        cable_layer = self._project.get_layer("cables")
        if not cable_layer:
            QMessageBox.critical(None, "Conductor", "fibre_cables layer not found.")
            self._reset(); return

        # Get cabinet for pop_id
        pop_layer = self._project.get_layer("exchange_pops")
        pop_id = ""
        if pop_layer:
            for feat in pop_layer.getFeatures():
                if feat["area_id"] == self._project.area_id:
                    pop_id = feat["pop_id"]; break

        cable_id = _next_cable_id(cable_layer, self._project.area_id)
        length_m = _calc_length(self._points)

        from_node  = self._node_ids[0]   or "unknown"
        from_type  = self._node_types[0] or "UNKNOWN"
        to_node    = self._node_ids[-1]  or "unknown"
        to_type    = self._node_types[-1]or "UNKNOWN"

        # Try to find matching duct
        duct_feat = None
        if from_node != "unknown" and to_node != "unknown":
            duct_feat = _find_duct_for_nodes(
                self._project, from_node, to_node
            )

        duct_id = duct_feat["duct_id"] if duct_feat else None

        # Offer to copy duct geometry
        use_duct_geom = False
        if duct_feat:
            reply = QMessageBox.question(
                None, "Use Duct Geometry?",
                f"Matching duct found: {duct_id}\n\n"
                f"Copy the duct geometry for this fibre cable?\n"
                f"(Recommended — ensures cable follows exact duct path)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            use_duct_geom = reply == QMessageBox.Yes

        dlg = self._make_dialog(cable_id, from_node, from_type, to_node, to_type, length_m, pop_id, duct_id)

        if dlg.exec_() != QDialog.Accepted:
            self._reset(); return

        attrs = dlg.get_attributes()

        # Use duct geometry if chosen, otherwise use digitised points
        if use_duct_geom and duct_feat:
            geom = duct_feat.geometry()
        else:
            geom = QgsGeometry.fromPolylineXY(self._points)

        feat = QgsFeature(cable_layer.fields())
        feat.setGeometry(geom)

        for fname, val in attrs.items():
            idx = cable_layer.fields().indexOf(fname)
            if idx >= 0 and val is not None:
                feat.setAttribute(idx, val)

        cable_layer.startEditing()
        if cable_layer.addFeature(feat):
            cable_layer.commitChanges()
            cable_layer.triggerRepaint()
            tree_layer = QgsProject.instance().layerTreeRoot().findLayer(cable_layer.id())
            if tree_layer:
                tree_layer.setItemVisibilityChecked(True)
            self.placed.emit(attrs["cable_id"])
            # Stay active — ready to draw next cable immediately
        else:
            cable_layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to write fibre cable.")

        self._reset()

    def _reset(self):
        self._points=[]; self._node_ids=[]; self._node_types=[]
        self._rubber.reset(); self._snap_rubber.reset()

    def deactivate(self):
        """Clean up rubber bands when tool is deactivated."""
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
            self._reset(); self._canvas.unsetMapTool(self)
        elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
            if self._points:
                self._points.pop(); self._node_ids.pop()
                self._node_types.pop(); self._rubber.removeLastPoint()
