# -*- coding: utf-8 -*-
"""
Conductor — Draw Build Area Tool
Polygon capture tool. Must be the first step in any Conductor project.
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox,
    QPushButton, QFrame, QMessageBox,
)
from qgis.core import (
    QgsWkbTypes,
    QgsFeature, QgsGeometry, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsRectangle,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE

# ═══════════════════════════════════════════════════════════════════════════
# BUILD AREA FORM
# ═══════════════════════════════════════════════════════════════════════════

class BuildAreaDialog(QDialog):

    def __init__(self, area_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Define Build Area")
        self.setMinimumWidth(460)
        self.setModal(True)
        self._area_id = area_id
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

        hdr = QLabel(f"  Build Area  —  {self._area_id}")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        sub = QLabel("  Polygon digitised on map")
        sub.setFixedHeight(24)
        sub.setStyleSheet(f"background:{TEAL}; color:{WHITE}; font-size:11px; padding-left:8px;")
        root.addWidget(sub)

        fw = QFrame(); fw.setStyleSheet(f"background:{LIGHT};")
        fl = QVBoxLayout(fw); fl.setContentsMargins(20, 14, 20, 8); fl.setSpacing(8)

        fl.addWidget(self._section("IDENTITY"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)

        self.area_name = QLineEdit()
        self.area_name.setPlaceholderText("e.g. Tarvin Village")
        self.area_name.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Area Name *"), self.area_name)

        self.phase = QSpinBox()
        self.phase.setMinimum(1); self.phase.setMaximum(99); self.phase.setValue(1)
        self.phase.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Phase"), self.phase)

        self.status = QComboBox()
        self.status.addItems(["PLANNED", "HLD", "MLD", "LLD", "BUILD", "LIVE"])
        self.status.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Status"), self.status)

        fl.addLayout(f1)
        fl.addWidget(self._divider())

        fl.addWidget(self._section("NOTES"))
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Free text notes (optional)")
        self.notes.setStyleSheet(INPUT_STYLE)
        fl.addWidget(self.notes)

        root.addWidget(fw)

        br = QHBoxLayout(); br.setContentsMargins(20, 12, 20, 16); br.addStretch()
        cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
        cancel.clicked.connect(self.reject); br.addWidget(cancel)
        save = QPushButton("Save Build Area"); save.setStyleSheet(BTN_PRIMARY)
        save.clicked.connect(self._on_save); br.addWidget(save)
        root.addLayout(br)

    def _on_save(self):
        if not self.area_name.text().strip():
            QMessageBox.warning(self, "Required", "Area Name is required.")
            return
        self.accept()

    def get_attributes(self):
        return {
            "area_id":    self._area_id,
            "area_name":  self.area_name.text().strip(),
            "phase":      self.phase.value(),
            "status":     self.status.currentText(),
            "notes":      self.notes.text().strip(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# MAP TOOL — click points to build polygon, double-click to finish
# ═══════════════════════════════════════════════════════════════════════════

class DrawBuildAreaMapTool(QgsMapTool):

    drawn = pyqtSignal(str)  # emits area_id

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self._points  = []   # canvas CRS points

        # Rubber band for live preview
        self._rubber = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self._rubber.setColor(QColor(28, 122, 110, 160))
        self._rubber.setFillColor(QColor(28, 122, 110, 40))
        self._rubber.setWidth(2)

        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasPressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt = self.toMapCoordinates(event.pos())
            self._points.append(pt)
            self._rubber.addPoint(pt, True)
        elif event.button() == Qt.RightButton:
            if len(self._points) < 3:
                QMessageBox.warning(None, "Conductor",
                    "A Build Area needs at least 3 points.\nKeep left-clicking to add corners,\nthen right-click to finish.")
                return
            self._finish()

    def canvasDoubleClickEvent(self, event):
        # Swallowed — right-click finishes the polygon
        pass

    def _to_27700(self, canvas_pt):
        canvas_crs = self._canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
        if canvas_crs == target_crs:
            return canvas_pt
        xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
        return xform.transform(canvas_pt)

    def _finish(self):
        self._rubber.reset()

        layer = self._project.get_layer("build_areas")
        if not layer:
            QMessageBox.critical(None, "Conductor", "build_areas layer not found.")
            return

        dlg = BuildAreaDialog(area_id=self._project.area_id)
        if dlg.exec_() != QDialog.Accepted:
            self._points = []
            return

        # Convert all points to EPSG:27700
        pts_27700 = [self._to_27700(p) for p in self._points]
        geom = QgsGeometry.fromPolygonXY([pts_27700])

        feat = QgsFeature(layer.fields())
        feat.setGeometry(geom)
        attrs = dlg.get_attributes()

        # Also write country_code and build_code from project
        attrs["country_code"] = self._project.country_code
        attrs["build_code"]   = self._project.build_code

        for fname, fvalue in attrs.items():
            idx = layer.fields().indexOf(fname)
            if idx >= 0:
                feat.setAttribute(idx, fvalue)

        layer.startEditing()
        if layer.addFeature(feat):
            layer.commitChanges()
            layer.triggerRepaint()

            # Make layer visible
            tree_layer = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
            if tree_layer:
                tree_layer.setItemVisibilityChecked(True)

            self.drawn.emit(attrs["area_id"])
        else:
            layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to write Build Area.")

        self._points = []
        self._canvas.unsetMapTool(self)

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
            self._rubber.reset()
            self._points = []
            self._canvas.unsetMapTool(self)
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if len(self._points) >= 3:
                self._finish()
