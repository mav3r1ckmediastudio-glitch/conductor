# -*- coding: utf-8 -*-
"""
Conductor v2 — Right Dock: Selected Asset Inspector
Shows attributes of whatever the user clicks on the map canvas.
Registered via iface.addDockWidget(Qt.RightDockWidgetArea) and tabified
below the Validation dock.
"""

from qgis.PyQt.QtCore import Qt, QTimer, QEvent, QPoint
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QScrollArea, QSizePolicy, QToolButton, QPushButton, QDialog,
)
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProject, QgsFeatureRequest, QgsRectangle, QgsPointXY,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem, NULL,
)
from qgis.gui import QgsMapToolEmitPoint
from .conductor_utils import (
    NAVY, LIGHT, MID, WHITE, GREY, TEAL, GREEN, ORANGE, RED,
    get_layer,
)


# ── Asset type config ─────────────────────────────────────────────────────────
# Maps layer name → (display_name, id_field, colour, fields_to_show)
ASSET_CONFIG = {
    # (display_name, id_field, accent, fields, icon_png)
    "chambers": (
        "Chamber / Pole", "chamber_id", TEAL,
        [("ID",          "chamber_id"),
         ("Type",        "chamber_type"),
         ("Owner",       "owner"),
         ("Status",      "status"),
         ("PIA Ref",     "pia_ref"),
         ("Pole Type",   "pole_type"),
         ("OR Ref",      "openreach_ref"),
         ("Notes",       "notes")],
        "place_chamber.png",
    ),
    "joints": (
        "Joint / Closure", "joint_id", "#A78BFA",
        [("ID",           "joint_id"),
         ("Type",         "joint_type"),
         ("Closure",      "closure_type"),
         ("Has Splitter", "has_splitter"),
         ("Split Ratio",  "split_ratio"),
         ("Cascade Lvl",  "cascade_level"),
         ("Status",       "status"),
         ("Notes",        "notes")],
        "place_joint.png",
    ),
    "cables": (
        "Cable", "cable_id", "#60A5FA",
        [("ID",          "cable_id"),
         ("Type",        "cable_type"),
         ("Fibres",      "fibre_count"),
         ("Tubes",       "tube_count"),
         ("Length (m)",  "length_m"),
         ("From",        "from_node"),
         ("To",          "to_node"),
         ("Status",      "status")],
        "digitise_cable.png",
    ),
    "bundles": (
        "Bundle (Drop)", "bundle_id", GREEN,
        [("ID",          "bundle_id"),
         ("UPRN",        "uprn"),
         ("From Joint",  "from_joint"),
         ("Fibres",      "fibre_count"),
         ("Length (m)",  "length_m"),
         ("Status",      "status"),
         ("Wayleave",    "wayleave_req")],
        "digitise_bundle.png",
    ),
    "drop_ducts": (
        "Drop Duct", "ddct_id", ORANGE,
        [("ID",          "ddct_id"),
         ("UPRN",        "uprn"),
         ("From",        "from_chamber"),
         ("Length (m)",  "length_m"),
         ("Drop Type",   "drop_type"),
         ("Status",      "status"),
         ("Wayleave",    "wayleave_req")],
        "digitise_drop_duct.png",
    ),
    "premises": (
        "Premises", "uprn", WHITE,
        [("UPRN",        "uprn"),
         ("Address",     "address_1"),
         ("Address 2",   "address_2"),
         ("Town",        "town"),
         ("Postcode",    "postcode"),
         ("Type",        "premise_type"),
         ("Tech",        "current_tech"),
         ("Registered",  "registered")],
        "import_premises_addressbase.png",
    ),
    "exchange_pops": (
        "Cabinet / POP", "pop_id", TEAL,
        [("ID",          "pop_id"),
         ("Name",        "pop_name"),
         ("Type",        "pop_type"),
         ("Operator",    "operator"),
         ("Status",      "status"),
         ("Max Cust.",   "max_customers"),
         ("Address",     "address")],
        "place_cabinet_pop.png",
    ),
}

SEARCH_ORDER = [
    "chambers", "joints", "exchange_pops",
    "cables", "bundles", "drop_ducts", "premises",
]

TOLERANCE_MM = 3.0   # map units tolerance for point/line identify


_QSS = f"""
    QWidget {{
        background-color: {NAVY};
        color: {WHITE};
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 12px;
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background-color: {NAVY};
        border: none;
    }}
    QScrollBar:vertical {{
        background: {NAVY}; width: 5px; border-radius: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {MID}; border-radius: 2px; min-height: 16px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QLabel {{ color: {WHITE}; background: transparent; }}
    QPushButton {{
        background: {LIGHT}; color: {WHITE}; border: 1px solid {MID};
        border-radius: 4px; padding: 5px 10px; font-size: 11px; text-align: left;
    }}
    QPushButton:hover {{ border-color: {TEAL}; color: {TEAL}; }}
"""


# ── Shared stacked-asset picker ───────────────────────────────────────────────

def pick_stacked_asset(matches, action_verb="inspect"):
    """Show a picker dialog when multiple assets overlap at the clicked point.

    `matches` is a list of (layer_name, feat) tuples. Returns the chosen
    (layer_name, feat), or None if cancelled. Shared by both the standalone
    asset dock and the validation dock's embedded inspector so the stacked-
    asset picker behaves identically wherever you click.
    """
    dlg = QDialog()
    dlg.setWindowTitle("Multiple Assets Found")
    dlg.setMinimumWidth(380)
    dlg.setModal(True)
    root = QVBoxLayout(dlg)
    root.setSpacing(0)
    root.setContentsMargins(0, 0, 0, 0)

    hdr = QLabel("  Multiple Assets Found")
    hdr.setFixedHeight(40)
    hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
    root.addWidget(hdr)

    body = QVBoxLayout()
    body.setContentsMargins(12, 12, 12, 12)
    body.setSpacing(6)
    info = QLabel(f"These assets overlap at the point you clicked. Choose which one to {action_verb}:")
    info.setWordWrap(True)
    body.addWidget(info)

    result = {"choice": None}

    for layer_name, feat in matches:
        cfg = ASSET_CONFIG.get(layer_name)
        if cfg:
            display_name = cfg[0]
            id_field     = cfg[1]
        else:
            display_name = layer_name
            id_field     = "fid"
        try:
            asset_id = str(feat[id_field])
        except Exception:
            asset_id = str(feat.id())

        btn = QPushButton(f"{display_name}  \u2014  {asset_id}")
        btn.setStyleSheet(
            f"QPushButton {{ padding:8px 12px; text-align:left; border:1px solid {MID}; "
            f"border-radius:4px; }} QPushButton:hover {{ border-color:{TEAL}; background:{LIGHT}; }}"
        )
        def _choose(_checked=False, ln=layer_name, ft=feat):
            result["choice"] = (ln, ft)
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


class ConductorAssetDock(QDockWidget):
    """Right-hand panel: Selected Asset Inspector."""

    def __init__(self, main_dock, iface, parent=None):
        super().__init__("Selected Asset", parent or iface.mainWindow())
        self.main_dock  = main_dock
        self.iface      = iface
        self._project   = None
        self._click_conn = None
        self.setObjectName("ConductorAssetDock")
        self.setMinimumWidth(260)
        self.setFeatures(
            QDockWidget.DockWidgetMovable |
            QDockWidget.DockWidgetFloatable |
            QDockWidget.DockWidgetClosable
        )
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        container = QWidget()
        container.setStyleSheet(_QSS)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(container)
        self.setWidget(scroll)

        self._root = QVBoxLayout(container)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; border-bottom:1px solid {MID};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 12, 0)
        hl.setSpacing(8)

        self._title_lbl = QLabel("SELECTED ASSET")
        self._title_lbl.setMinimumWidth(0)
        self._title_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._title_lbl.setStyleSheet(
            f"color:{WHITE}; font-size:11px; font-weight:700; letter-spacing:1.5px;"
        )
        hl.addWidget(self._title_lbl, 1)

        clear_btn = QToolButton()
        clear_btn.setText("✕")
        clear_btn.setToolTip("Clear selection")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setFixedSize(24, 24)
        clear_btn.setStyleSheet(f"""
            QToolButton {{ background:{LIGHT}; color:{WHITE}; border:1px solid {MID};
                           border-radius:3px; font-size:11px; }}
            QToolButton:hover {{ border-color:{RED}; color:{RED}; }}
        """)
        clear_btn.clicked.connect(self._clear)
        hl.addWidget(clear_btn)
        self._root.addWidget(hdr)

        # ── Empty state ──────────────────────────────────────────────────────
        self._empty_widget = QWidget()
        el = QVBoxLayout(self._empty_widget)
        el.setContentsMargins(16, 24, 16, 24)
        el.setSpacing(8)
        icon_lbl = QLabel("⊙")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(f"color:{MID}; font-size:28px;")
        el.addWidget(icon_lbl)
        hint_lbl = QLabel("Click any asset on the map\nto inspect its attributes")
        hint_lbl.setAlignment(Qt.AlignCenter)
        hint_lbl.setWordWrap(True)
        hint_lbl.setMinimumWidth(0)
        hint_lbl.setStyleSheet(f"color:{MID}; font-size:11px;")
        el.addWidget(hint_lbl)
        self._root.addWidget(self._empty_widget)

        # ── Asset content (hidden until something selected) ──────────────────
        self._content_widget = QWidget()
        self._content_widget.setVisible(False)
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        self._root.addWidget(self._content_widget)

        self._root.addStretch(1)

    # ── Project / canvas wiring ───────────────────────────────────────────────

    def set_project(self, project):
        self._project = project
        canvas = self.iface.mapCanvas()
        # Install event filter on canvas viewport to intercept mouse clicks.
        # Guard against double-install: removeEventFilter is a no-op if not
        # already installed, so this keeps exactly one filter regardless of how
        # many times set_project is called (timer push + project-open).
        vp = canvas.viewport()
        vp.removeEventFilter(self)
        vp.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Intercept canvas mouse press to identify the clicked asset.

        Only fires the inspector when the user is in plain navigation mode.
        If any Conductor map tool (Edit/Delete/Move/Place/Digitise) is active,
        we bail out so that tool's own click handling — including its stacked-
        asset picker — runs without interference.
        """
        if (event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
                and self._project):
            canvas = self.iface.mapCanvas()
            active_tool = canvas.mapTool()
            # Skip if a Conductor tool is driving the canvas. Conductor tools
            # live in the conductor_v2.tools package; match on the tool's module.
            if active_tool is not None:
                mod = type(active_tool).__module__ or ""
                if ".tools." in mod or mod.endswith("select_delete") or mod.endswith("edit_assets"):
                    return False
            # Convert pixel pos to map point
            pixel_pt = event.pos()
            map_pt = canvas.getCoordinateTransform().toMapCoordinates(
                pixel_pt.x(), pixel_pt.y()
            )
            # Use QTimer so we don't block the event
            QTimer.singleShot(50, lambda: self._on_canvas_click(map_pt))
        return False   # never consume the event

    # ── Map click handler ────────────────────────────────────────────────────

    def _on_canvas_click(self, point):
        """Identify the clicked feature across all asset layers.
        When multiple assets overlap, show a picker so the user can choose which to inspect.
        """
        if not self._project:
            return

        canvas = self.iface.mapCanvas()

        # Convert tolerance from mm to map units
        dpm    = canvas.mapSettings().outputDpi() / 25.4
        tol_px = TOLERANCE_MM * dpm
        tol_mu = tol_px * canvas.mapUnitsPerPixel()

        search_rect = QgsRectangle(
            point.x() - tol_mu, point.y() - tol_mu,
            point.x() + tol_mu, point.y() + tol_mu,
        )

        # Collect ALL hits across all layers
        matches = []  # list of (layer_name, feat)
        canvas_crs = canvas.mapSettings().destinationCrs()
        for layer_name in SEARCH_ORDER:
            layer = get_layer(layer_name, self._project)
            if not layer or not layer.isValid():
                continue

            layer_crs = layer.crs()
            if canvas_crs != layer_crs:
                xform = QgsCoordinateTransform(canvas_crs, layer_crs, QgsProject.instance())
                rect  = xform.transformBoundingBox(search_rect)
            else:
                rect = search_rect

            for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
                matches.append((layer_name, feat))

        if not matches:
            return

        if len(matches) == 1:
            self._show_asset(matches[0][0], matches[0][1])
            return

        # Multiple stacked assets — show picker
        chosen = self._pick_stacked_asset(matches)
        if chosen:
            self._show_asset(chosen[0], chosen[1])

    def _pick_stacked_asset(self, matches):
        """Show a picker dialog when multiple assets overlap at the clicked point.
        Returns (layer_name, feat) for the chosen asset, or None if cancelled.
        """
        dlg = QDialog()
        dlg.setWindowTitle("Multiple Assets Found")
        dlg.setMinimumWidth(380)
        dlg.setModal(True)
        root = QVBoxLayout(dlg)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr = QLabel("  Multiple Assets Found")
        hdr.setFixedHeight(40)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        body = QVBoxLayout()
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(6)
        info = QLabel("These assets overlap at the point you clicked. Choose which one to inspect:")
        info.setWordWrap(True)
        body.addWidget(info)

        result = {"choice": None}

        for layer_name, feat in matches:
            cfg = ASSET_CONFIG.get(layer_name)
            if cfg:
                display_name = cfg[0]
                id_field     = cfg[1]
            else:
                display_name = layer_name
                id_field     = "fid"
            try:
                asset_id = str(feat[id_field])
            except Exception:
                asset_id = str(feat.id())

            btn = QPushButton(f"{display_name}  —  {asset_id}")
            btn.setStyleSheet(
                f"QPushButton {{ padding:8px 12px; text-align:left; border:1px solid {MID}; "
                f"border-radius:4px; }} QPushButton:hover {{ border-color:{TEAL}; background:{LIGHT}; }}"
            )
            def _choose(_checked=False, ln=layer_name, ft=feat):
                result["choice"] = (ln, ft)
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

    # ── Display ──────────────────────────────────────────────────────────────

    def _show_asset(self, layer_name, feat):
        """Populate the panel with the clicked feature's attributes."""
        cfg = ASSET_CONFIG.get(layer_name)
        if not cfg:
            return

        display_name, id_field, accent, fields, icon_png = cfg
        asset_id = str(feat[id_field] or "") if id_field in feat.fields().names() else "—"

        # Clear content
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # ── Asset type badge + ID ────────────────────────────────────────────
        badge = QWidget()
        badge.setStyleSheet(
            f"background:{LIGHT}; border-left:4px solid {accent}; "
            f"border-bottom:1px solid {MID};"
        )
        bl = QHBoxLayout(badge)
        bl.setContentsMargins(8, 8, 12, 8)
        bl.setSpacing(8)

        # Asset icon
        import os as _os
        _icon_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'icons', icon_png)
        if _os.path.exists(_icon_path):
            from qgis.PyQt.QtGui import QIcon, QPixmap
            from qgis.PyQt.QtCore import QSize
            icon_lbl = QLabel()
            icon_lbl.setFixedSize(28, 28)
            icon_lbl.setAlignment(Qt.AlignCenter)
            icon_lbl.setPixmap(QIcon(_icon_path).pixmap(QSize(24, 24)))
            icon_lbl.setStyleSheet("background:transparent; border:none;")
            bl.addWidget(icon_lbl)

        type_lbl = QLabel(display_name.upper())
        type_lbl.setMinimumWidth(0)
        type_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        type_lbl.setStyleSheet(
            f"color:{accent}; font-size:9px; font-weight:700; letter-spacing:2px;"
        )
        bl.addWidget(type_lbl, 1)

        id_lbl = QLabel(asset_id)
        id_lbl.setMinimumWidth(0)
        id_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        id_lbl.setStyleSheet(f"color:{GREY}; font-size:10px;")
        id_lbl.setToolTip(asset_id)
        bl.addWidget(id_lbl)

        self._content_layout.addWidget(badge)

        # ── Field rows ───────────────────────────────────────────────────────
        field_names = feat.fields().names()
        rows_widget = QWidget()
        rows_widget.setStyleSheet("background:transparent;")
        rl = QVBoxLayout(rows_widget)
        rl.setContentsMargins(0, 4, 0, 4)
        rl.setSpacing(0)

        for label, field in fields:
            if field not in field_names:
                continue
            val = feat[field]
            if val is None or val == NULL or str(val).strip() == "":
                continue

            row = QWidget()
            row.setMinimumWidth(0)
            row.setStyleSheet(
                f"background:transparent; border-bottom:1px solid {NAVY};"
            )
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(12, 6, 12, 6)
            row_l.setSpacing(8)

            key = QLabel(label)
            key.setMinimumWidth(0)
            key.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            key.setStyleSheet(f"color:{GREY}; font-size:10px;")
            key.setFixedWidth(80)
            row_l.addWidget(key)

            val_lbl = QLabel(str(val))
            val_lbl.setMinimumWidth(0)
            val_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            val_lbl.setStyleSheet(f"color:{WHITE}; font-size:11px; font-weight:500;")
            val_lbl.setToolTip(str(val))
            row_l.addWidget(val_lbl, 1)

            rl.addWidget(row)

        self._content_layout.addWidget(rows_widget)

        # ── Action buttons ───────────────────────────────────────────────────
        actions = QWidget()
        actions.setStyleSheet(f"background:{LIGHT}; border-top:1px solid {MID};")
        al = QHBoxLayout(actions)
        al.setContentsMargins(8, 8, 8, 8)
        al.setSpacing(6)

        zoom_btn = QPushButton("⊙  Zoom To")
        zoom_btn.setCursor(Qt.PointingHandCursor)
        zoom_btn.clicked.connect(lambda: self._zoom_to(feat, layer_name))
        al.addWidget(zoom_btn)

        edit_btn = QPushButton("✎  Edit")
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.clicked.connect(
            lambda: self.main_dock._on_edit_asset() if hasattr(self.main_dock, "_on_edit_asset") else None
        )
        al.addWidget(edit_btn)

        self._content_layout.addWidget(actions)

        # Show content, hide empty state
        self._empty_widget.setVisible(False)
        self._content_widget.setVisible(True)
        self._title_lbl.setText(f"SELECTED ASSET")

    def _zoom_to(self, feat, layer_name):
        """Zoom map canvas to the selected feature."""
        layer = get_layer(layer_name, self._project)
        if not layer:
            return
        canvas = self.iface.mapCanvas()
        geom = feat.geometry()
        if geom and not geom.isEmpty():
            canvas_crs = canvas.mapSettings().destinationCrs()
            layer_crs  = layer.crs()
            if canvas_crs != layer_crs:
                geom.transform(QgsCoordinateTransform(
                    layer_crs, canvas_crs, QgsProject.instance()
                ))
            bbox = geom.boundingBox()
            bbox.grow(max(bbox.width(), bbox.height(), 50) * 0.5)
            canvas.setExtent(bbox)
            canvas.refresh()

    def _clear(self):
        self._empty_widget.setVisible(True)
        self._content_widget.setVisible(False)
        self._title_lbl.setText("SELECTED ASSET")

    def closeEvent(self, event):
        super().closeEvent(event)
