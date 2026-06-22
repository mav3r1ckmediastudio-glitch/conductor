import os
# -*- coding: utf-8 -*-
"""
Conductor v2 — Right Dock: Validation Summary + Engineer Outputs
Permanent right-hand panel showing live validation counts and quick-launch
output buttons. Registered via iface.addDockWidget(Qt.RightDockWidgetArea).
"""

import os
from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QSizePolicy, QToolButton,
    QSplitter,
)
from qgis.core import QgsSettings
from .conductor_utils import (
    NAVY, LIGHT, MID, WHITE, GREY, TEAL, GREEN, ORANGE, RED,
    GREEN_BG, ORANGE_BG, RED_BG,
)


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
    QPushButton {{
        background: {LIGHT}; color: {WHITE}; border: 1px solid {MID};
        border-radius: 4px; padding: 6px 10px; font-size: 12px; text-align: left;
    }}
    QPushButton:hover {{ border-color: {TEAL}; color: {TEAL}; }}
    QPushButton:disabled {{ color: {MID}; border-color: {LIGHT}; background: {NAVY}; }}
    QLabel {{ color: {WHITE}; background: transparent; }}
    QFrame[frameShape="4"] {{ color: {MID}; }}
"""


class ConductorValidationDock(QDockWidget):
    """Right-hand permanent panel: Validation Summary + Engineer Outputs."""

    def __init__(self, main_dock, iface, parent=None):
        super().__init__("Validation & Outputs", parent or iface.mainWindow())
        self.main_dock = main_dock   # ConductorDockWidget reference
        self.iface = iface
        self.setObjectName("ConductorValidationDock")
        self.setMinimumWidth(300)
        self.setMaximumWidth(480)
        self.resize(320, self.height())
        self.setFeatures(
            QDockWidget.DockWidgetMovable |
            QDockWidget.DockWidgetFloatable |
            QDockWidget.DockWidgetClosable
        )

        # Restore geometry
        settings = QgsSettings()
        floating = settings.value("Conductor/v2/val_dock_floating", False, type=bool)
        self.setFloating(floating)

        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Three-pane splitter: validation top, selected asset middle, route inspector bottom
        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet(f"""
            QSplitter {{ background:{NAVY}; }}
            QSplitter::handle {{ background:{MID}; height:2px; }}
        """)
        splitter.setHandleWidth(2)
        self.setWidget(splitter)

        # ── Pane 1: Validation Summary ───────────────────────────────────────
        val_pane = QWidget()
        val_pane.setStyleSheet(_QSS)
        val_scroll = QScrollArea()
        val_scroll.setWidgetResizable(True)
        val_scroll.setFrameShape(QFrame.NoFrame)
        val_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        val_scroll.setWidget(val_pane)
        splitter.addWidget(val_scroll)

        root = QVBoxLayout(val_pane)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; border-bottom:1px solid {MID};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 12, 0)
        hl.setSpacing(8)
        title_lbl = QLabel("VALIDATION SUMMARY")
        title_lbl.setStyleSheet(
            f"color:{WHITE}; font-size:11px; font-weight:700; letter-spacing:1.5px;"
        )
        hl.addWidget(title_lbl, 1)

        self._updated_lbl = QLabel("No project")
        self._updated_lbl.setStyleSheet(f"color:{MID}; font-size:10px;")
        hl.addWidget(self._updated_lbl)

        refresh_btn = QToolButton()
        refresh_btn.setText("↻")
        refresh_btn.setToolTip("Re-run validation")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setStyleSheet(f"""
            QToolButton {{ background:{LIGHT}; color:{WHITE}; border:1px solid {MID};
                           border-radius:3px; font-size:13px; }}
            QToolButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}
        """)
        refresh_btn.clicked.connect(self._on_refresh)
        hl.addWidget(refresh_btn)
        root.addWidget(hdr)

        # ── Count badges ────────────────────────────────────────────────────
        badge_area = QWidget()
        badge_area.setStyleSheet(f"background:{LIGHT}; border-bottom:1px solid {MID};")
        bl = QHBoxLayout(badge_area)
        bl.setContentsMargins(6, 6, 6, 6)
        bl.setSpacing(4)

        self._badge_critical, self._badge_critical_val = self._count_badge(bl, "0", "Critical",  RED,       "#3B1212")
        self._badge_errors,   self._badge_errors_val   = self._count_badge(bl, "0", "Errors",    ORANGE,    "#3B2A0A")
        self._badge_warnings, self._badge_warnings_val = self._count_badge(bl, "0", "Warnings",  "#FACC15", "#302800")
        self._badge_info,     self._badge_info_val     = self._count_badge(bl, "0", "Info",      TEAL,      "#0A2622")
        root.addWidget(badge_area)

        # Progress bar row
        pb_row = QWidget()
        pb_row.setStyleSheet(f"background:{LIGHT};")
        pbl = QHBoxLayout(pb_row)
        pbl.setContentsMargins(12, 0, 12, 8)
        pbl.setSpacing(8)
        self._progress_lbl = QLabel("Network validation")
        self._progress_lbl.setStyleSheet(f"color:{GREY}; font-size:10px;")
        pbl.addWidget(self._progress_lbl, 1)
        self._pct_lbl = QLabel("–")
        self._pct_lbl.setStyleSheet(f"color:{TEAL}; font-size:10px; font-weight:bold;")
        pbl.addWidget(self._pct_lbl)
        root.addWidget(pb_row)

        # ── Issues list ─────────────────────────────────────────────────────
        root.addWidget(self._divider())
        issues_hdr = QWidget()
        ih = QHBoxLayout(issues_hdr)
        ih.setContentsMargins(12, 8, 12, 6)
        ih.setSpacing(0)
        issues_title = QLabel("ISSUES")
        issues_title.setStyleSheet(f"color:{GREY}; font-size:9px; font-weight:700; letter-spacing:2px;")
        ih.addWidget(issues_title)
        root.addWidget(issues_hdr)

        self._issues_container = QWidget()
        self._issues_container.setMinimumWidth(0)
        self._issues_container.setStyleSheet("background:transparent;")
        self._issues_layout = QVBoxLayout(self._issues_container)
        self._issues_layout.setContentsMargins(8, 0, 8, 8)
        self._issues_layout.setSpacing(2)
        self._placeholder_lbl = QLabel("Run validation to see issues.")
        self._placeholder_lbl.setStyleSheet(f"color:{MID}; font-size:11px; padding:8px 4px;")
        self._issues_layout.addWidget(self._placeholder_lbl)
        root.addWidget(self._issues_container)

        # ── Engineer Outputs ────────────────────────────────────────────────
        root.addWidget(self._divider())
        out_hdr = QWidget()
        oh = QHBoxLayout(out_hdr)
        oh.setContentsMargins(12, 8, 12, 4)
        oh.setSpacing(0)
        out_title = QLabel("ENGINEER OUTPUTS")
        out_title.setStyleSheet(f"color:{GREY}; font-size:9px; font-weight:700; letter-spacing:2px;")
        oh.addWidget(out_title)
        root.addWidget(out_hdr)

        out_area = QWidget()
        out_area.setStyleSheet("background:transparent;")
        ol = QVBoxLayout(out_area)
        ol.setContentsMargins(8, 4, 8, 12)
        ol.setSpacing(4)

        self._out_buttons = {}
        for label, key in [
            ("Splice Plan Export",  "splice_plan"),
            ("Route Splice Export", "route_splice"),
            ("Single Line Diagram", "sld"),
            ("Bill of Materials",   "bom"),
        ]:
            btn = QPushButton(label)
            btn.setEnabled(False)
            btn.clicked.connect(lambda _checked, k=key: self._on_output(k))
            ol.addWidget(btn)
            self._out_buttons[key] = btn

        root.addWidget(out_area)
        root.addStretch(1)

        # ── Pane 2: Selected Asset ───────────────────────────────────────────
        self._asset_pane = QWidget()
        self._asset_pane.setStyleSheet(_QSS)
        asset_scroll = QScrollArea()
        asset_scroll.setWidgetResizable(True)
        asset_scroll.setFrameShape(QFrame.NoFrame)
        asset_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        asset_scroll.setWidget(self._asset_pane)
        splitter.addWidget(asset_scroll)
        self._build_asset_pane()

        # ── Pane 3: Route Inspector ──────────────────────────────────────────
        self._route_pane = QWidget()
        self._route_pane.setStyleSheet(_QSS)
        route_scroll = QScrollArea()
        route_scroll.setWidgetResizable(True)
        route_scroll.setFrameShape(QFrame.NoFrame)
        route_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        route_scroll.setWidget(self._route_pane)
        splitter.addWidget(route_scroll)
        self._build_route_pane()

        # Set initial proportions: 50% / 25% / 25%
        splitter.setSizes([400, 200, 200])
        self._splitter = splitter

    # ── Asset pane ──────────────────────────────────────────────────────────────

    def _build_asset_pane(self):
        root = QVBoxLayout(self._asset_pane)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(f"background:{LIGHT}; border-bottom:1px solid {MID};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 12, 0)
        title = QLabel("SELECTED ASSET")
        title.setStyleSheet(f"color:{GREY}; font-size:9px; font-weight:700; letter-spacing:2px;")
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        hl.addWidget(title, 1)
        self._asset_clear_btn = QToolButton()
        self._asset_clear_btn.setText("✕")
        self._asset_clear_btn.setFixedSize(20, 20)
        self._asset_clear_btn.setCursor(Qt.PointingHandCursor)
        self._asset_clear_btn.setStyleSheet(f"""
            QToolButton {{ background:transparent; border:none; color:{MID}; font-size:11px; }}
            QToolButton:hover {{ color:{RED}; }}
        """)
        self._asset_clear_btn.clicked.connect(self._clear_asset)
        hl.addWidget(self._asset_clear_btn)
        root.addWidget(hdr)

        # Empty state
        self._asset_empty = QLabel("Click any asset on the map")
        self._asset_empty.setAlignment(Qt.AlignCenter)
        self._asset_empty.setMinimumWidth(0)
        self._asset_empty.setStyleSheet(f"color:{MID}; font-size:11px; padding:16px;")
        root.addWidget(self._asset_empty)

        # Content area (hidden until asset clicked)
        self._asset_content = QWidget()
        self._asset_content.setVisible(False)
        self._asset_content.setMinimumWidth(0)
        self._asset_content_layout = QVBoxLayout(self._asset_content)
        self._asset_content_layout.setContentsMargins(0, 0, 0, 0)
        self._asset_content_layout.setSpacing(0)
        root.addWidget(self._asset_content)
        root.addStretch(1)

    def show_asset(self, layer_name, feat, accent=None):
        """Populate the Selected Asset pane with a clicked feature."""
        from .conductor_asset_dock import ASSET_CONFIG
        cfg = ASSET_CONFIG.get(layer_name)
        if not cfg:
            return
        display_name, id_field, colour, fields, _icon_png = cfg
        if accent:
            colour = accent

        asset_id = str(feat[id_field] or "") if id_field in feat.fields().names() else "—"

        # Clear old content
        while self._asset_content_layout.count():
            item = self._asset_content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Type badge + ID row
        badge = QWidget()
        badge.setMinimumWidth(0)
        badge.setStyleSheet(
            f"background:{LIGHT}; border-left:4px solid {colour}; border-bottom:1px solid {MID};"
        )
        bl = QHBoxLayout(badge)
        bl.setContentsMargins(10, 8, 8, 8)
        bl.setSpacing(8)

        # Text column
        text_col = QWidget()
        text_col.setMinimumWidth(0)
        text_col.setStyleSheet("background:transparent;")
        tcl = QVBoxLayout(text_col)
        tcl.setContentsMargins(0, 0, 0, 0)
        tcl.setSpacing(2)
        type_lbl = QLabel(display_name.upper())
        type_lbl.setMinimumWidth(0)
        type_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        type_lbl.setStyleSheet(f"color:{colour}; font-size:9px; font-weight:700; letter-spacing:2px;")
        tcl.addWidget(type_lbl)
        id_lbl = QLabel(asset_id)
        id_lbl.setMinimumWidth(0)
        id_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        id_lbl.setStyleSheet(f"color:{WHITE}; font-size:11px; font-weight:600;")
        id_lbl.setToolTip(asset_id)
        tcl.addWidget(id_lbl)
        bl.addWidget(text_col, 1)

        # Asset icon (right side of badge) — use icon_png from ASSET_CONFIG
        if _icon_png:
            from qgis.PyQt.QtGui import QIcon
            from qgis.PyQt.QtCore import QSize
            _icons_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icons')
            icon_path = os.path.join(_icons_dir, _icon_png)
            if os.path.exists(icon_path):
                icon_lbl = QLabel()
                icon_lbl.setFixedSize(36, 36)
                icon_lbl.setStyleSheet(f"background:{NAVY}; border-radius:6px;")
                icon_lbl.setPixmap(QIcon(icon_path).pixmap(QSize(28, 28)))
                icon_lbl.setAlignment(Qt.AlignCenter)
                bl.addWidget(icon_lbl)

        self._asset_content_layout.addWidget(badge)

        # Field rows
        field_names = feat.fields().names()
        from qgis.core import NULL
        for label, field in fields:
            if field not in field_names:
                continue
            val = feat[field]
            if val is None or val == NULL or str(val).strip() == "":
                continue
            row = QWidget()
            row.setMinimumWidth(0)
            row.setStyleSheet(f"border-bottom:1px solid {NAVY};")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 5, 10, 5)
            rl.setSpacing(8)
            key_lbl = QLabel(label)
            key_lbl.setFixedWidth(76)
            key_lbl.setMinimumWidth(0)
            key_lbl.setStyleSheet(f"color:{GREY}; font-size:10px;")
            rl.addWidget(key_lbl)
            val_lbl = QLabel(str(val))
            val_lbl.setMinimumWidth(0)
            val_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            val_lbl.setStyleSheet(f"color:{WHITE}; font-size:11px;")
            val_lbl.setToolTip(str(val))
            rl.addWidget(val_lbl, 1)
            self._asset_content_layout.addWidget(row)

        # Zoom button
        zoom_btn = QPushButton("⊙  Zoom To")
        zoom_btn.setMinimumWidth(0)
        zoom_btn.setCursor(Qt.PointingHandCursor)
        zoom_btn.clicked.connect(lambda: self._zoom_to_asset(feat, layer_name))
        zoom_btn.setStyleSheet(f"""
            QPushButton {{ background:{LIGHT}; color:{TEAL}; border:1px solid {MID};
                           border-radius:3px; padding:5px 10px; font-size:11px; margin:6px; }}
            QPushButton:hover {{ border-color:{TEAL}; }}
        """)
        self._asset_content_layout.addWidget(zoom_btn)

        self._asset_empty.setVisible(False)
        self._asset_content.setVisible(True)

    def _clear_asset(self):
        self._asset_empty.setVisible(True)
        self._asset_content.setVisible(False)

    def _zoom_to_asset(self, feat, layer_name):
        from .conductor_utils import get_layer
        from qgis.core import QgsCoordinateTransform, QgsProject
        layer = get_layer(layer_name, getattr(self, '_project', None))
        if not layer:
            return
        canvas = self.iface.mapCanvas()
        geom = feat.geometry()
        if geom and not geom.isEmpty():
            geom.transform(QgsCoordinateTransform(
                layer.crs(), canvas.mapSettings().destinationCrs(), QgsProject.instance()
            ))
            bbox = geom.boundingBox()
            bbox.grow(max(bbox.width(), bbox.height(), 50) * 0.5)
            canvas.setExtent(bbox)
            canvas.refresh()

    # ── Network Integrity detail popup ───────────────────────────────────────────
    LAYER_DISPLAY = {
        "joints": "Joints", "cables": "Cables", "ducts": "Ducts",
        "drop_ducts": "Drop Ducts", "bundles": "Bundles", "chambers": "Chambers",
        "fibre_assignments": "Fibre Assignments", "premises": "Premises",
        "exchange_pops": "Exchanges & POPs", "poles": "Poles",
        "build_tasks": "Build Tasks", "customers": "Customers",
    }

    def _show_integrity_detail(self, integ):
        from qgis.PyQt.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
            QScrollArea, QWidget, QFrame
        )
        from .conductor_utils import get_layer
        dlg = QDialog(self)
        dlg.setWindowTitle("Network Integrity — broken links")
        dlg.setMinimumSize(560, 420)
        dlg.setStyleSheet(_QSS)
        lay = QVBoxLayout(dlg); lay.setContentsMargins(16, 16, 16, 16); lay.setSpacing(10)

        issues = integ.get("issues", [])
        errors = [i for i in issues if i.get("severity") == "ERROR"]
        head = QLabel(f"{len(errors)} broken reference{'s' if len(errors) != 1 else ''} "
                      f"— a link points at an asset that does not exist.")
        head.setWordWrap(True)
        head.setStyleSheet(f"color:{WHITE}; font-size:12px;")
        lay.addWidget(head)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(6)

        for it in errors:
            lname = it.get("layer", ""); fid = it.get("fid"); field = it.get("field", "")
            value = it.get("value", ""); detail = it.get("detail", "")
            disp = self.LAYER_DISPLAY.get(lname, lname)
            card = QWidget()
            card.setStyleSheet(f"background:{LIGHT}; border-left:3px solid {RED}; border-radius:3px;")
            cl = QHBoxLayout(card); cl.setContentsMargins(10, 8, 10, 8); cl.setSpacing(10)
            txt = QLabel(f"<b>{disp}</b> · <span style='color:{GREY}'>{field}</span> → "
                         f"<span style='color:{RED}'>{value}</span><br>"
                         f"<span style='color:{GREY}; font-size:10px'>{detail}</span>")
            txt.setStyleSheet(f"color:{WHITE}; font-size:11px;")
            txt.setWordWrap(True)
            cl.addWidget(txt, 1)
            zbtn = QPushButton("⊙ Zoom")
            zbtn.setCursor(Qt.PointingHandCursor); zbtn.setFixedWidth(70)
            def _mkzoom(ln=lname, fd=fid):
                def _go():
                    lyr = get_layer(ln, getattr(self, "_project", None))
                    if not lyr or fd is None:
                        return
                    feat = lyr.getFeature(fd)
                    if feat is not None:
                        self._zoom_to_asset(feat, ln)
                return _go
            zbtn.clicked.connect(_mkzoom())
            cl.addWidget(zbtn, 0)
            bl.addWidget(card)

        bl.addStretch(1)
        scroll.setWidget(body); lay.addWidget(scroll, 1)

        close = QPushButton("Close"); close.clicked.connect(dlg.accept)
        lay.addWidget(close, 0)
        dlg.exec_()

    # ── Route Inspector pane ─────────────────────────────────────────────────────

    def _build_route_pane(self):
        root = QVBoxLayout(self._route_pane)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QWidget()
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(f"background:{LIGHT}; border-bottom:1px solid {MID};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 12, 0)
        title = QLabel("ROUTE INSPECTOR")
        title.setMinimumWidth(0)
        title.setStyleSheet(f"color:{GREY}; font-size:9px; font-weight:700; letter-spacing:2px;")
        hl.addWidget(title)
        root.addWidget(hdr)

        self._route_empty = QLabel("Select a route in the table below")
        self._route_empty.setAlignment(Qt.AlignCenter)
        self._route_empty.setMinimumWidth(0)
        self._route_empty.setStyleSheet(f"color:{MID}; font-size:11px; padding:16px;")
        root.addWidget(self._route_empty)

        self._route_content = QWidget()
        self._route_content.setVisible(False)
        self._route_content.setMinimumWidth(0)
        self._route_content_layout = QVBoxLayout(self._route_content)
        self._route_content_layout.setContentsMargins(10, 8, 10, 8)
        self._route_content_layout.setSpacing(6)
        root.addWidget(self._route_content)
        root.addStretch(1)

    def show_route(self, route_data):
        """Populate the Route Inspector pane from a routes table row dict."""
        while self._route_content_layout.count():
            item = self._route_content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Route ID + status header
        id_row = QWidget()
        id_row.setMinimumWidth(0)
        il = QHBoxLayout(id_row)
        il.setContentsMargins(0, 0, 0, 0)
        id_lbl = QLabel(f"Route: {route_data.get('route_id', '—')}")
        id_lbl.setMinimumWidth(0)
        id_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        id_lbl.setStyleSheet(f"color:{WHITE}; font-size:11px; font-weight:600;")
        il.addWidget(id_lbl, 1)

        status = route_data.get('status', '')
        sc = GREEN if status == 'Routed' else (ORANGE if status == 'Partial' else RED)
        st_lbl = QLabel(status)
        st_lbl.setStyleSheet(f"""
            color:{sc}; font-size:9px; font-weight:700;
            border:1px solid {sc}; border-radius:3px; padding:1px 5px;
        """)
        il.addWidget(st_lbl)
        self._route_content_layout.addWidget(id_row)

        # From → To
        path_lbl = QLabel(
            f"{route_data.get('from_node','—')}  →  {route_data.get('to_node','—')}"
        )
        path_lbl.setMinimumWidth(0)
        path_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        path_lbl.setStyleSheet(f"color:{GREY}; font-size:10px;")
        path_lbl.setToolTip(path_lbl.text())
        self._route_content_layout.addWidget(path_lbl)

        # Stats row
        stats = QWidget()
        stats.setMinimumWidth(0)
        sl = QHBoxLayout(stats)
        sl.setContentsMargins(0, 4, 0, 0)
        sl.setSpacing(4)
        for val, label in [
            (route_data.get('length','–'),   'Length'),
            (route_data.get('fibres','–'),   'Fibres'),
            (route_data.get('capacity','–'), 'Capacity'),
        ]:
            cell = QWidget()
            cell.setMinimumWidth(0)
            cell.setStyleSheet(f"background:{LIGHT}; border-radius:4px;")
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(6, 4, 6, 4)
            cl.setSpacing(1)
            v = QLabel(str(val))
            v.setAlignment(Qt.AlignCenter)
            v.setMinimumWidth(0)
            v.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            v.setStyleSheet(f"color:{WHITE}; font-size:13px; font-weight:700;")
            l = QLabel(label)
            l.setAlignment(Qt.AlignCenter)
            l.setMinimumWidth(0)
            l.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            l.setStyleSheet(f"color:{GREY}; font-size:8px;")
            cl.addWidget(v)
            cl.addWidget(l)
            sl.addWidget(cell, 1)
        self._route_content_layout.addWidget(stats)

        self._route_empty.setVisible(False)
        self._route_content.setVisible(True)

    def clear_route(self):
        self._route_empty.setVisible(True)
        self._route_content.setVisible(False)

    # ── COUNT BADGE ──────────────────────────────────────────────────────────────

    def _count_badge(self, layout, value, caption, fg, bg):
        """Returns (value_label, caption_label) tuple. Cell expands to fill equal share."""
        from qgis.PyQt.QtWidgets import QSizePolicy as QSP
        cell = QFrame()
        cell.setStyleSheet(
            f"QFrame {{ background:{bg}; border:1px solid {fg}; border-radius:5px; }}"
        )
        cell.setSizePolicy(QSP.Expanding, QSP.Preferred)
        cell.setMinimumWidth(0)
        cl = QVBoxLayout(cell)
        cl.setContentsMargins(1, 4, 1, 4)
        cl.setSpacing(1)

        v_lbl = QLabel(value)
        v_lbl.setAlignment(Qt.AlignCenter)
        v_lbl.setMinimumWidth(0)
        v_lbl.setSizePolicy(QSP.Ignored, QSP.Preferred)
        v_lbl.setStyleSheet(
            f"color:{fg}; font-size:15px; font-weight:700; border:none; background:transparent;"
        )
        cl.addWidget(v_lbl)

        c_lbl = QLabel(caption)
        c_lbl.setAlignment(Qt.AlignCenter)
        c_lbl.setMinimumWidth(0)
        c_lbl.setSizePolicy(QSP.Expanding, QSP.Preferred)
        c_lbl.setStyleSheet(
            f"color:{fg}; font-size:8px; border:none; background:transparent;"
        )
        cl.addWidget(c_lbl)

        layout.addWidget(cell, 1)
        return v_lbl, c_lbl   # (value_label, caption_label)

    def _divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color:{MID}; background:{MID}; margin:0px;")
        return line

    # ── DATA ────────────────────────────────────────────────────────────────────

    def set_project(self, project):
        """Enable output buttons, wire canvas clicks, and trigger first validation pass."""
        self._project = project
        for btn in self._out_buttons.values():
            btn.setEnabled(True)
        # Wire canvas click via event filter
        canvas = self.iface.mapCanvas()
        canvas.viewport().removeEventFilter(self)
        canvas.viewport().installEventFilter(self)
        self._on_refresh()

    def eventFilter(self, obj, event):
        from qgis.PyQt.QtCore import QEvent, QTimer
        from .conductor_utils import conductor_tool_active
        if (event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
                and self._project
                and not conductor_tool_active(self.iface.mapCanvas())):
            canvas = self.iface.mapCanvas()
            pt = event.pos()
            map_pt = canvas.getCoordinateTransform().toMapCoordinates(pt.x(), pt.y())
            QTimer.singleShot(50, lambda: self._identify_asset(map_pt))
        return False

    def _identify_asset(self, map_pt):
        from qgis.core import QgsFeatureRequest, QgsRectangle, QgsCoordinateTransform, QgsProject
        from .conductor_asset_dock import SEARCH_ORDER, pick_stacked_asset
        from .conductor_utils import get_layer
        canvas = self.iface.mapCanvas()
        tol = canvas.mapUnitsPerPixel() * 8
        rect = QgsRectangle(map_pt.x()-tol, map_pt.y()-tol, map_pt.x()+tol, map_pt.y()+tol)
        canvas_crs = canvas.mapSettings().destinationCrs()

        # Collect ALL hits across all layers (stacked assets)
        matches = []
        for layer_name in SEARCH_ORDER:
            layer = get_layer(layer_name, self._project)
            if not layer or not layer.isValid():
                continue
            if canvas_crs != layer.crs():
                xform = QgsCoordinateTransform(canvas_crs, layer.crs(), QgsProject.instance())
                search = xform.transformBoundingBox(rect)
            else:
                search = rect
            for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(search)):
                matches.append((layer_name, feat))

        if not matches:
            return
        if len(matches) == 1:
            self.show_asset(matches[0][0], matches[0][1])
            return

        # Multiple stacked assets — show the shared picker
        chosen = pick_stacked_asset(matches)
        if chosen:
            self.show_asset(chosen[0], chosen[1])

    def push_validation_results(self, results):
        """
        Accept a dict with keys:
          critical (int), errors (int), warnings (int), info (int),
          score_pct (int or None),
          issues (list of dicts: {severity, message, asset_id})
        """
        self._badge_critical.setText(str(results.get("critical", 0)))
        self._badge_errors.setText(str(results.get("errors", 0)))
        self._badge_warnings.setText(str(results.get("warnings", 0)))
        self._badge_info.setText(str(results.get("info", 0)))

        pct = results.get("score_pct")
        if pct is not None:
            self._pct_lbl.setText(f"{pct}%")
            c = GREEN if pct >= 90 else (ORANGE if pct >= 70 else RED)
            self._pct_lbl.setStyleSheet(f"color:{c}; font-size:10px; font-weight:bold;")
        else:
            self._pct_lbl.setText("–")

        from datetime import datetime
        self._updated_lbl.setText(f"Updated {datetime.now().strftime('%H:%M')}")

        # Force badge row to reflow to actual dock width
        from qgis.PyQt.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.widget().updateGeometry())

        # Rebuild issues list
        while self._issues_layout.count():
            item = self._issues_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        issues = results.get("issues", [])
        routed  = results.get("routed",  0)
        partial = results.get("partial", 0)
        total   = results.get("total",   0)

        # ── Connection summary row ───────────────────────────────────────────
        summary_row = QWidget()
        summary_row.setMinimumWidth(0)
        summary_row.setStyleSheet(
            f"background:{LIGHT}; border-left:3px solid {GREEN}; "
            f"border-radius:3px; margin-bottom:4px;"
        )
        sr_layout = QHBoxLayout(summary_row)
        sr_layout.setContentsMargins(8, 6, 8, 6)
        sr_layout.setSpacing(12)

        def _stat(val, label, colour):
            w = QWidget()
            w.setMinimumWidth(0)
            w.setStyleSheet("background:transparent;")
            vl = QVBoxLayout(w)
            vl.setContentsMargins(0,0,0,0)
            vl.setSpacing(0)
            n = QLabel(str(val))
            n.setAlignment(Qt.AlignCenter)
            n.setMinimumWidth(0)
            n.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            n.setStyleSheet(f"color:{colour}; font-size:14px; font-weight:700; border:none; background:transparent;")
            c = QLabel(label)
            c.setAlignment(Qt.AlignCenter)
            c.setMinimumWidth(0)
            c.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            c.setStyleSheet(f"color:{colour}; font-size:8px; border:none; background:transparent;")
            vl.addWidget(n)
            vl.addWidget(c)
            return w

        unserved = total - routed - partial if total > 0 else results.get("info", 0)
        sr_layout.addWidget(_stat(routed,  "Routed",   GREEN),  1)
        sr_layout.addWidget(_stat(partial, "Partial",  ORANGE), 1)
        sr_layout.addWidget(_stat(unserved,"Unserved", GREY),   1)
        if total > 0:
            sr_layout.addWidget(_stat(total, "Total", WHITE), 1)
        self._issues_layout.addWidget(summary_row)

        # ── Network Integrity row (FK/reference check) ───────────────────────
        integ = results.get("integrity")
        ni_row = QWidget(); ni_row.setMinimumWidth(0)
        ni_l = QHBoxLayout(ni_row); ni_l.setContentsMargins(8, 6, 8, 6); ni_l.setSpacing(8)
        name_lbl = QLabel("Network Integrity")
        name_lbl.setStyleSheet(f"color:{WHITE}; font-size:11px; border:none; background:transparent;")
        ni_l.addWidget(name_lbl, 1)
        status_lbl = QLabel(); status_lbl.setStyleSheet("border:none; background:transparent;")
        if integ is None:
            ni_row.setStyleSheet(f"background:{LIGHT}; border-left:3px solid {GREY}; border-radius:3px; margin-bottom:4px;")
            status_lbl.setText("–")
            status_lbl.setStyleSheet(f"color:{GREY}; font-size:11px; border:none; background:transparent;")
        elif integ.get("error_count", 0) == 0:
            ni_row.setStyleSheet(f"background:{LIGHT}; border-left:3px solid {GREEN}; border-radius:3px; margin-bottom:4px;")
            status_lbl.setText(f"{integ.get('checked', 0):,} checked  ✓")
            status_lbl.setStyleSheet(f"color:{GREEN}; font-size:11px; font-weight:bold; border:none; background:transparent;")
        else:
            n = integ["error_count"]
            ni_row.setStyleSheet(f"background:#1d1213; border-left:3px solid {RED}; border-radius:3px; margin-bottom:4px;")
            status_lbl.setText(f"{n} broken link{'s' if n != 1 else ''}  ›")
            status_lbl.setStyleSheet(f"color:{RED}; font-size:11px; font-weight:bold; border:none; background:transparent;")
            ni_row.setCursor(Qt.PointingHandCursor)
            ni_row.setToolTip("Click to see broken links")
            def _open_integ(ev, data=integ):
                self._show_integrity_detail(data)
            ni_row.mousePressEvent = _open_integ
        ni_l.addWidget(status_lbl, 0)
        self._issues_layout.addWidget(ni_row)

        # ── Separate out unserved info items from real issues ────────────────
        unserved_issues = [i for i in issues if i.get("severity") == "info"
                           and "Unserved" in i.get("message", "")]
        real_issues     = [i for i in issues if i not in unserved_issues]

        if not real_issues and not unserved_issues:
            lbl = QLabel("No issues found  ✓")
            lbl.setMinimumWidth(0)
            lbl.setStyleSheet(f"color:{GREEN}; font-size:11px; padding:8px 4px;")
            self._issues_layout.addWidget(lbl)
        else:
            colours = {"critical": RED, "error": ORANGE, "warning": "#FACC15", "info": TEAL}

            # Real issues (critical / error / warning / non-unserved info) — list individually
            for issue in real_issues[:50]:
                sev = issue.get("severity", "info").lower()
                row = self._issue_row(
                    sev, issue.get("message", ""), issue.get("asset_id", ""),
                    colours.get(sev, GREY)
                )
                self._issues_layout.addWidget(row)
            if len(real_issues) > 50:
                more = QLabel(f"+ {len(real_issues)-50} more issues")
                more.setMinimumWidth(0)
                more.setStyleSheet(f"color:{MID}; font-size:10px; padding:4px 4px;")
                self._issues_layout.addWidget(more)

            # Unserved — single collapsed summary line, not 1158 rows
            if unserved_issues:
                n = len(unserved_issues)
                row = self._issue_row(
                    "info",
                    f"{n} premises not yet connected to network",
                    "",
                    TEAL
                )
                self._issues_layout.addWidget(row)

    def _issue_row(self, severity, message, asset_id, colour):
        from qgis.PyQt.QtCore import Qt as _Qt

        row = QWidget()
        row.setMinimumWidth(0)
        row.setStyleSheet(
            f"background:{LIGHT}; border-left:3px solid {colour}; "
            f"border-radius:3px; margin-bottom:1px;"
        )
        rl = QHBoxLayout(row)
        rl.setContentsMargins(8, 5, 8, 5)
        rl.setSpacing(6)

        # QSizePolicy.Ignored = Qt completely disregards the label's text width,
        # so a long message can never force the container wider than the dock.
        msg = QLabel(message)
        msg.setStyleSheet(f"color:{WHITE}; font-size:11px; border:none; background:transparent;")
        msg.setWordWrap(False)
        msg.setMinimumWidth(0)
        msg.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        msg.setTextInteractionFlags(_Qt.TextSelectableByMouse)
        msg.setToolTip(message)
        rl.addWidget(msg, 1)

        if asset_id:
            aid = QLabel(asset_id)
            aid.setStyleSheet(f"color:{GREY}; font-size:10px; border:none; background:transparent;")
            aid.setMinimumWidth(0)
            rl.addWidget(aid, 0)

        zoom_btn = QToolButton()
        zoom_btn.setText("⊙")
        zoom_btn.setToolTip(f"Zoom to {asset_id}")
        zoom_btn.setCursor(Qt.PointingHandCursor)
        zoom_btn.setFixedSize(20, 20)
        zoom_btn.setStyleSheet(f"""
            QToolButton {{ background:transparent; border:none; color:{MID}; font-size:12px; }}
            QToolButton:hover {{ color:{TEAL}; }}
        """)
        rl.addWidget(zoom_btn, 0)
        return row

    def _on_refresh(self):
        """Attempt to run validation if a project is open."""
        if not hasattr(self, "_project") or not self._project:
            return
        try:
            from .tools.validate_routes import run_validation_headless
            results = run_validation_headless(self._project)
            # Network integrity (FK/reference) check — runs with every refresh.
            try:
                from .tools.validate_integrity import run_integrity_check_headless
                results["integrity"] = run_integrity_check_headless()
            except Exception:
                results["integrity"] = None  # unavailable -> row shows a dash
            self.push_validation_results(results)
        except Exception:
            # Validation module may not support headless mode yet — show stub
            self.push_validation_results({
                "critical": 0, "errors": 0, "warnings": 0, "info": 0,
                "score_pct": None, "issues": []
            })
            self._placeholder_lbl = QLabel("Validation not available in headless mode.")
            self._issues_layout.addWidget(self._placeholder_lbl)

    def _on_output(self, key):
        """Delegate to main dock callbacks."""
        handlers = {
            "splice_plan":  getattr(self.main_dock, "_on_splice_plan",         None),
            "route_splice": getattr(self.main_dock, "_on_route_splice_export",  None),
            "sld":          getattr(self.main_dock, "_on_sld",                  None),
            "bom":          getattr(self.main_dock, "_on_bom",                  None),
        }
        h = handlers.get(key)
        if h:
            h()

    # ── CLOSE ────────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        QgsSettings().setValue("Conductor/v2/val_dock_floating", self.isFloating())
        super().closeEvent(event)
