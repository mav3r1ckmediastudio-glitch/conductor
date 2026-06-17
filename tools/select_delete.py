# -*- coding: utf-8 -*-
"""
Conductor — Select & Delete / Move Asset Tools
Click any Conductor asset to select it, then delete or move it.
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QColor
from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QPushButton, QLabel, QMessageBox
from ..conductor_utils import NAVY, WHITE, MID, TEAL, LIGHT
from qgis.core import (
    QgsProject, QgsFeatureRequest, QgsRectangle,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsGeometry, QgsPointXY, QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from ..conductor_utils import get_layer, fld, val, LayerEditContext

# Layers to search when clicking — in priority order
SEARCHABLE_LAYERS = [
    "exchange_pops",
    "chambers",
    "joints",
    "ducts",
    "cables",
    "drop_ducts",
    "bundles",
    # "build_areas" intentionally excluded — deleting the build area polygon
    # via the delete tool risks corrupting the entire project state.
    # Use the dedicated Redraw Build Area workflow instead.
    "surveys",
    "wayleaves",
    "build_tasks",
    "customers",
    "premises",
]

LAYER_LABELS = {
    "exchange_pops":  "Cabinet / POP",
    "chambers":       "Chamber",
    "joints":         "Joint",
    "ducts":          "Duct",
    "cables":         "Fibre Cable",
    "drop_ducts":     "Drop Duct",
    "bundles":        "Bundle",
    "build_areas":    "Build Area",
    "surveys":        "Survey Record",
    "wayleaves":      "Wayleave",
    "build_tasks":    "Build Task",
    "customers":      "Customer",
    "premises":       "Premises",
}

# ID field per layer
ID_FIELDS = {
    "exchange_pops":  "pop_id",
    "chambers":       "chamber_id",
    "joints":         "joint_id",
    "ducts":          "duct_id",
    "cables":         "cable_id",
    "drop_ducts":     "ddct_id",
    "bundles":        "bundle_id",
    "build_areas":    "area_id",
    "surveys":        "survey_id",
    "wayleaves":      "wayleave_id",
    "build_tasks":    "task_id",
    "customers":      "customer_id",
    "premises":       "uprn",
}


def _find_feature_at(canvas, project, canvas_pos):
    """
    Search all Conductor layers for a feature near the clicked point.
    Returns (layer_name, layer, feature) or (None, None, None).
    """
    canvas_crs = canvas.mapSettings().destinationCrs()
    target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
    canvas_pt  = canvas.getCoordinateTransform().toMapCoordinates(canvas_pos)

    # Transform click to EPSG:27700
    if canvas_crs != target_crs:
        xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
        pt_27700 = xform.transform(canvas_pt)
    else:
        pt_27700 = canvas_pt

    radius = canvas.mapUnitsPerPixel() * 12

    # For point layers use a small bbox; for line/polygon layers use slightly larger
    for layer_name in SEARCHABLE_LAYERS:
        layer = project.get_layer(layer_name)
        if not layer or layer.featureCount() == 0:
            continue

        search_rect = QgsRectangle(
            pt_27700.x() - radius, pt_27700.y() - radius,
            pt_27700.x() + radius, pt_27700.y() + radius,
        )

        request = QgsFeatureRequest().setFilterRect(search_rect)
        for feat in layer.getFeatures(request):
            return layer_name, layer, feat

    return None, None, None


# ═══════════════════════════════════════════════════════════════════════════
# DELETE TOOL
# ═══════════════════════════════════════════════════════════════════════════

def _pick_asset_to_delete(matches):
    """Several assets overlap — ask the user which one to delete.
    Returns (layer_name, layer, feat) or None if cancelled."""
    dlg = QDialog()
    dlg.setWindowTitle("Multiple Assets Found")
    dlg.setMinimumWidth(380)
    dlg.setModal(True)
    root = QVBoxLayout(dlg); root.setSpacing(0); root.setContentsMargins(0, 0, 0, 0)

    hdr = QLabel("  Multiple Assets Found")
    hdr.setFixedHeight(40)
    hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
    root.addWidget(hdr)

    body = QVBoxLayout(); body.setContentsMargins(12, 12, 12, 12); body.setSpacing(6)
    info = QLabel("These assets overlap at the point you clicked. Choose which one to delete:")
    info.setWordWrap(True)
    body.addWidget(info)

    result = {"choice": None}

    for layer_name, layer, feat, _dist in matches:
        id_field = ID_FIELDS.get(layer_name, "fid")
        asset_id = str(feat[id_field]) if id_field in [f.name() for f in feat.fields()] else str(feat.id())
        label    = LAYER_LABELS.get(layer_name, layer_name)
        btn = QPushButton(f"{label}  —  {asset_id}")
        btn.setStyleSheet(
            f"QPushButton {{ padding:8px 12px; text-align:left; border:1px solid {MID}; "
            f"border-radius:4px; }} QPushButton:hover {{ border-color:#E05050; background:#FFF0F0; }}"
        )
        def _choose(_checked=False, ln=layer_name, ly=layer, ft=feat):
            result["choice"] = (ln, ly, ft)
            dlg.accept()
        btn.clicked.connect(_choose)
        body.addWidget(btn)

    cancel_btn = QPushButton("Cancel")
    cancel_btn.setStyleSheet(
        f"QPushButton {{ padding:7px 14px; border-radius:4px; font-size:12px; border:1px solid {MID}; }} "
        f"QPushButton:hover {{ background:{LIGHT}; }}"
    )
    cancel_btn.clicked.connect(dlg.reject)
    body.addWidget(cancel_btn)
    root.addLayout(body)
    dlg.exec_()
    return result["choice"]


class DeleteAssetMapTool(QgsMapTool):
    """Click a Conductor asset to delete it. When multiple assets overlap,
    a picker dialog lets the user choose which one to delete."""

    deleted = pyqtSignal(str, str)  # layer_name, asset_id

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self.setCursor(QCursor(Qt.ForbiddenCursor))

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        from .edit_assets import _find_features
        matches = _find_features(self._canvas, self._project, list(SEARCHABLE_LAYERS), event.pos())

        if not matches:
            QMessageBox.information(None, "Conductor",
                "No Conductor asset found at that location.\n"
                "Click closer to an asset, or press Esc to cancel.")
            return

        if len(matches) == 1:
            layer_name, layer, feat, _ = matches[0]
        else:
            picked = _pick_asset_to_delete(matches)
            if picked is None:
                return
            layer_name, layer, feat = picked

        label    = LAYER_LABELS.get(layer_name, layer_name)
        id_field = ID_FIELDS.get(layer_name, "fid")
        asset_id = str(feat[id_field]) if id_field in [f.name() for f in feat.fields()] else str(feat.id())

        name_candidates = ["pop_name", "area_name", "chamber_id", "task_name", "landowner"]
        display_name = ""
        for nc in name_candidates:
            v = feat[nc] if nc in [f.name() for f in feat.fields()] else None
            if v and str(v) != "NULL":
                display_name = f" — {v}"
                break

        reply = QMessageBox.question(
            None,
            "Delete Asset",
            f"Delete this {label}?\n\n"
            f"ID: {asset_id}{display_name}\n\n"
            f"This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        layer.startEditing()
        if layer.deleteFeature(feat.id()):
            layer.commitChanges()
            layer.triggerRepaint()
            self.deleted.emit(layer_name, asset_id)
        else:
            layer.rollBack()
            QMessageBox.critical(None, "Error", f"Failed to delete {label}.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._canvas.unsetMapTool(self)


# ═══════════════════════════════════════════════════════════════════════════
# MOVE TOOL
# ═══════════════════════════════════════════════════════════════════════════

class MoveAssetMapTool(QgsMapTool):
    """
    Two-click move: first click selects the asset, second click sets new location.
    Only works on point geometry assets.
    """

    moved = pyqtSignal(str, str)  # layer_name, asset_id

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas       = canvas
        self._project      = project
        self._selected_layer = None
        self._selected_feat  = None
        self._selected_name  = None

        # Highlight rubber band
        self._rubber = QgsRubberBand(self._canvas, QgsWkbTypes.PointGeometry)
        self._rubber.setColor(QColor(200, 90, 0, 200))
        self._rubber.setIconSize(14)

        self.setCursor(QCursor(Qt.SizeAllCursor))

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        canvas_crs = self._canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
        canvas_pt  = self.toMapCoordinates(event.pos())

        if canvas_crs != target_crs:
            xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
            pt_27700 = xform.transform(canvas_pt)
        else:
            pt_27700 = canvas_pt

        if self._selected_feat is None:
            # FIRST CLICK — select an asset
            layer_name, layer, feat = _find_feature_at(
                self._canvas, self._project, event.pos()
            )

            if feat is None:
                QMessageBox.information(None, "Conductor",
                    "No Conductor asset found at that location.\n"
                    "Click on an asset to select it for moving.")
                return

            # Only point geometry can be moved with this tool
            if layer.geometryType() != QgsWkbTypes.PointGeometry:
                QMessageBox.warning(None, "Conductor",
                    "Only point assets (cabinets, chambers, poles, splitters) "
                    "can be moved with this tool.\n\n"
                    "To move lines or polygons, use the QGIS node editor.")
                return

            self._selected_layer = layer
            self._selected_feat  = feat
            self._selected_name  = layer_name

            # Show highlight at current position
            self._rubber.reset(QgsWkbTypes.PointGeometry)
            self._rubber.addPoint(feat.geometry().asPoint(), True)

            label    = LAYER_LABELS.get(layer_name, layer_name)
            id_field = ID_FIELDS.get(layer_name, "fid")
            asset_id = str(feat[id_field])
            self._canvas.setToolTip(f"Moving {label}: {asset_id}")

            from qgis.PyQt.QtWidgets import QApplication
            QApplication.instance().activeWindow() and None  # suppress warning
            # Update status bar message
            try:
                from qgis.utils import iface
                iface.messageBar().pushInfo(
                    "Conductor",
                    f"{label} {asset_id} selected — now click the new location."
                )
            except Exception:
                pass

        else:
            # SECOND CLICK — move to new location
            layer    = self._selected_layer
            feat     = self._selected_feat
            layer_name = self._selected_name

            label    = LAYER_LABELS.get(layer_name, layer_name)
            id_field = ID_FIELDS.get(layer_name, "fid")
            asset_id = str(feat[id_field])

            reply = QMessageBox.question(
                None, "Confirm Move",
                f"Move {label} {asset_id} to new location?\n\n"
                f"New position: E {pt_27700.x():.1f}  N {pt_27700.y():.1f}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )

            if reply != QMessageBox.Yes:
                self._reset_selection()
                return

            new_geom = QgsGeometry.fromPointXY(pt_27700)
            layer.startEditing()
            if layer.changeGeometry(feat.id(), new_geom):
                layer.commitChanges()
                layer.triggerRepaint()
                self._rubber.reset()
                self.moved.emit(layer_name, asset_id)

                # If it was a cabinet, prompt to renumber chambers
                if layer_name == "exchange_pops":
                    reply2 = QMessageBox.question(
                        None, "Renumber Chambers?",
                        "The cabinet has moved.\n\n"
                        "Would you like to recalculate compass directions and "
                        "renumber chambers based on the new cabinet position?\n\n"
                        "Note: this will update chamber IDs — make sure no "
                        "job packs have been issued with the old IDs.",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    if reply2 == QMessageBox.Yes:
                        self._renumber_chambers(pt_27700, asset_id)
            else:
                layer.rollBack()
                QMessageBox.critical(None, "Error", f"Failed to move {label}.")

            self._reset_selection()

    def _reset_selection(self):
        self._selected_layer = None
        self._selected_feat  = None
        self._selected_name  = None
        self._rubber.reset()

    def _renumber_chambers(self, new_cab_pt, pop_id):
        """Recalculate compass direction and IDs for all chambers in this build area."""
        import math
        from .place_chamber import _compass_direction, DIRECTION_BASE

        chamber_layer = self._project.get_layer("chambers")
        if not chamber_layer or chamber_layer.featureCount() == 0:
            return

        area_id = self._project.area_id

        # Group chambers by direction, sort by distance from cabinet
        chambers_by_dir = {"N": [], "S": [], "E": [], "W": []}
        feats_to_update = []

        for feat in chamber_layer.getFeatures():
            if feat["area_id"] != area_id:
                continue
            pt = feat.geometry().asPoint()
            direction = _compass_direction(pt, new_cab_pt)
            dist = math.sqrt(
                (pt.x() - new_cab_pt.x()) ** 2 +
                (pt.y() - new_cab_pt.y()) ** 2
            )
            chambers_by_dir[direction].append((dist, feat))

        # Sort each direction by distance and assign new IDs
        chamber_layer.startEditing()
        updated = 0
        for direction, items in chambers_by_dir.items():
            items.sort(key=lambda x: x[0])
            base = DIRECTION_BASE[direction]
            for i, (_, feat) in enumerate(items):
                new_seq = base + i
                spur = feat["spur_suffix"] or ""
                suffix = f"({spur})" if spur else ""
                new_id = f"{area_id}-CMBR-{new_seq:04d}{suffix}"

                id_idx  = chamber_layer.fields().indexOf("chamber_id")
                seq_idx = chamber_layer.fields().indexOf("chamber_seq")
                dir_idx = chamber_layer.fields().indexOf("compass_dir")

                chamber_layer.changeAttributeValue(feat.id(), id_idx, new_id)
                chamber_layer.changeAttributeValue(feat.id(), seq_idx, new_seq)
                chamber_layer.changeAttributeValue(feat.id(), dir_idx, direction)
                updated += 1

        chamber_layer.commitChanges()
        chamber_layer.triggerRepaint()

        QMessageBox.information(None, "Renumbered",
            f"✓  {updated} chambers renumbered based on new cabinet position.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reset_selection()
            self._canvas.unsetMapTool(self)
