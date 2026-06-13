# -*- coding: utf-8 -*-
"""
Conductor — Place PIA UG Chamber Tool (PIA)
Places an Openreach underground chamber as a chamber record
with chamber_type = PIA_UG_CHAMBER.
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox,
    QPushButton, QFrame, QMessageBox, QScrollArea,
)
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
)
from qgis.gui import QgsMapToolEmitPoint
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE, MONO_STYLE

def _next_piac_id(layer, area_id):
    existing = set()
    prefix = f"{area_id}-PIAC-"
    for feat in layer.getFeatures():
        cid = feat["chamber_id"] or ""
        if cid.startswith(prefix):
            try:
                existing.add(int(cid.replace(prefix, "")))
            except ValueError:
                pass
    n = 1
    while n in existing:
        n += 1
    return f"{prefix}{n:03d}"


class PlacePIAChamberDialog(QDialog):

    def __init__(self, chamber_id, area_id, pop_id, point, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Place PIA UG Chamber")
        self.setMinimumWidth(500)
        self.setMaximumHeight(580)
        self.setModal(True)
        self._chamber_id = chamber_id
        self._area_id    = area_id
        self._pop_id     = pop_id
        self._point      = point
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

        hdr = QLabel(f"  Place PIA UG Chamber  —  {self._chamber_id}")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        coords = QLabel(f"  E {self._point.x():.1f}  N {self._point.y():.1f}  (EPSG:27700)")
        coords.setFixedHeight(24)
        coords.setStyleSheet(f"background:{TEAL}; color:{WHITE}; font-size:11px; padding-left:8px;")
        root.addWidget(coords)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{LIGHT}; border:none;")

        fw = QFrame(); fw.setStyleSheet(f"background:{LIGHT};")
        fl = QVBoxLayout(fw); fl.setContentsMargins(20, 14, 20, 8); fl.setSpacing(8)

        fl.addWidget(self._section("IDENTITY"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)

        id_disp = QLineEdit(self._chamber_id)
        id_disp.setReadOnly(True); id_disp.setStyleSheet(MONO_STYLE)
        f1.addRow(self._lbl("Chamber ID"), id_disp)

        self.openreach_ref = QLineEdit()
        self.openreach_ref.setPlaceholderText("Openreach chamber reference (optional)")
        self.openreach_ref.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Openreach Ref"), self.openreach_ref)

        self.status = QComboBox()
        self.status.addItems(["PROPOSED", "SURVEY", "INSTALLED"])
        self.status.setStyleSheet(INPUT_STYLE)
        f1.addRow(self._lbl("Status"), self.status)

        fl.addLayout(f1)
        fl.addWidget(self._divider())

        fl.addWidget(self._section("PHYSICAL"))
        f2 = QFormLayout(); f2.setSpacing(8); f2.setLabelAlignment(Qt.AlignRight)

        self.surface_type = QComboBox()
        self.surface_type.addItems(["— not set —", "FOOTWAY", "VERGE", "CARRIAGEWAY", "PRIVATE"])
        self.surface_type.setStyleSheet(INPUT_STYLE)
        f2.addRow(self._lbl("Surface Type"), self.surface_type)

        fl.addLayout(f2)
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
        save = QPushButton("Place Chamber"); save.setStyleSheet(BTN_PRIMARY)
        save.clicked.connect(self.accept); br.addWidget(save)
        root.addLayout(br)

    def get_attributes(self):
        st = self.surface_type.currentText()
        return {
            "chamber_id":    self._chamber_id,
            "chamber_type":  "PIA_UG_CHAMBER",
            "area_id":       self._area_id,
            "pop_id":        self._pop_id,
            "openreach_ref": self.openreach_ref.text().strip() or None,
            "surface_type":  st if not st.startswith("—") else None,
            "status":        self.status.currentText(),
            "notes":         self.notes.text().strip() or None,
        }


class PlacePIAChamberMapTool(QgsMapToolEmitPoint):

    placed = pyqtSignal(str)

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        pop_layer = self._project.get_layer("exchange_pops")
        pop_id = None
        if pop_layer:
            for feat in pop_layer.getFeatures():
                if feat["area_id"] == self._project.area_id:
                    pop_id = feat["pop_id"]
                    break

        chamber_layer = self._project.get_layer("chambers")
        if not chamber_layer:
            QMessageBox.critical(None, "Conductor", "chambers layer not found.")
            return

        canvas_crs = self._canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
        canvas_pt  = self.toMapCoordinates(event.pos())
        if canvas_crs != target_crs:
            xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
            point = xform.transform(canvas_pt)
        else:
            point = canvas_pt

        chamber_id = _next_piac_id(chamber_layer, self._project.area_id)

        dlg = PlacePIAChamberDialog(
            chamber_id=chamber_id, area_id=self._project.area_id,
            pop_id=pop_id, point=point,
        )
        if dlg.exec_() != QDialog.Accepted:
            return

        attrs = dlg.get_attributes()
        feat = QgsFeature(chamber_layer.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(point))
        for fname, val in attrs.items():
            idx = chamber_layer.fields().indexOf(fname)
            if idx >= 0 and val is not None:
                feat.setAttribute(idx, val)

        chamber_layer.startEditing()
        if chamber_layer.addFeature(feat):
            chamber_layer.commitChanges()
            chamber_layer.triggerRepaint()
            tree_layer = QgsProject.instance().layerTreeRoot().findLayer(chamber_layer.id())
            if tree_layer:
                tree_layer.setItemVisibilityChecked(True)
            self._canvas.flashFeatureIds(
                chamber_layer,
                [f.id() for f in chamber_layer.getFeatures() if f["chamber_id"] == chamber_id]
            )
            self.placed.emit(chamber_id)
        else:
            chamber_layer.rollBack()
            QMessageBox.critical(None, "Error", "Failed to write PIA UG Chamber feature.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._canvas.unsetMapTool(self)
