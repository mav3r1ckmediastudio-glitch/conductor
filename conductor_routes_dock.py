# -*- coding: utf-8 -*-
"""
Conductor v2 — Bottom Panel: Routes / Assets Table
Permanent bottom panel showing all routed features with status, length, and key
attributes. Registered via iface.addDockWidget(Qt.BottomDockWidgetArea).
"""

from qgis.PyQt.QtCore import Qt, QSize, QSortFilterProxyModel, QAbstractTableModel
from qgis.PyQt.QtGui import QColor, QBrush, QFont
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QTableView, QHeaderView, QLineEdit,
    QComboBox, QSizePolicy, QToolButton, QAbstractItemView,
)
from qgis.core import QgsSettings
from .conductor_utils import (
    NAVY, LIGHT, MID, WHITE, GREY, TEAL, GREEN, ORANGE, RED,
)


_QSS = f"""
    QWidget {{
        background-color: {NAVY};
        color: {WHITE};
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 12px;
    }}
    QTableView {{
        background-color: {NAVY};
        color: {WHITE};
        border: none;
        gridline-color: {MID};
        selection-background-color: #1E3A52;
        selection-color: {WHITE};
    }}
    QTableView::item {{ padding: 3px 8px; border: none; }}
    QHeaderView::section {{
        background-color: {LIGHT};
        color: {GREY};
        border: none;
        border-right: 1px solid {MID};
        border-bottom: 1px solid {MID};
        padding: 4px 8px;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.8px;
    }}
    QHeaderView::section:last {{ border-right: none; }}
    QLineEdit {{
        background: {LIGHT}; color: {WHITE}; border: 1px solid {MID};
        border-radius: 3px; padding: 4px 8px; font-size: 11px;
    }}
    QLineEdit:focus {{ border-color: {TEAL}; }}
    QComboBox {{
        background: {LIGHT}; color: {WHITE}; border: 1px solid {MID};
        border-radius: 3px; padding: 3px 8px; font-size: 11px;
    }}
    QComboBox QAbstractItemView {{
        background: {LIGHT}; color: {WHITE}; border: 1px solid {MID};
        selection-background-color: {TEAL}; selection-color: #0F1923;
    }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QScrollBar:vertical {{
        background: {NAVY}; width: 5px; border-radius: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {MID}; border-radius: 2px; min-height: 16px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar:horizontal {{
        background: {NAVY}; height: 5px; border-radius: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {MID}; border-radius: 2px; min-width: 20px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
    QPushButton {{
        background: {LIGHT}; color: {WHITE}; border: 1px solid {MID};
        border-radius: 3px; padding: 4px 10px; font-size: 11px;
    }}
    QPushButton:hover {{ border-color: {TEAL}; color: {TEAL}; }}
    QLabel {{ color: {WHITE}; background: transparent; }}
"""

_COLUMNS = ["Route ID", "Status", "From", "To", "Length", "Assets", "Fibres", "Capacity", "Updated", "Engineer"]
_STATUS_COLOURS = {
    "Routed":   GREEN,
    "Partial":  ORANGE,
    "Unserved": RED,
}


class RoutesTableModel(QAbstractTableModel):
    """Minimal read-only table model for routes data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []     # list of dicts

    def load(self, rows):
        self.beginResetModel()
        self._data = rows
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._data):
            return None
        row = self._data[index.row()]
        col = index.column()
        keys = ["route_id", "status", "from_node", "to_node", "length",
                "assets", "fibres", "capacity", "updated", "engineer"]
        key = keys[col]
        value = row.get(key, "–")

        if role == Qt.DisplayRole:
            return str(value)
        if role == Qt.ForegroundRole and col == 1:
            colour = _STATUS_COLOURS.get(str(value), GREY)
            return QBrush(QColor(colour))
        if role == Qt.FontRole and col == 1:
            f = QFont()
            f.setBold(True)
            return f
        return None

    def get_row(self, row_index):
        if 0 <= row_index < len(self._data):
            return self._data[row_index]
        return None


class ConductorRoutesDock(QDockWidget):
    """Bottom panel: Routes / Assets table with filter and CSV export."""

    def __init__(self, main_dock, iface, parent=None):
        super().__init__("Routes", parent or iface.mainWindow())
        self.main_dock = main_dock
        self.iface = iface
        self._project = None
        self.setObjectName("ConductorRoutesDock")
        self.setMinimumHeight(160)
        self.setFeatures(
            QDockWidget.DockWidgetMovable |
            QDockWidget.DockWidgetFloatable |
            QDockWidget.DockWidgetClosable
        )
        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        container = QWidget()
        container.setObjectName("ConductorRoutesContainer")
        container.setStyleSheet(_QSS)
        self.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ─────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(38)
        toolbar.setStyleSheet(f"background:{LIGHT}; border-bottom:1px solid {MID};")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(8, 0, 8, 0)
        tl.setSpacing(8)

        # Title + count badge
        title_lbl = QLabel("ROUTES")
        title_lbl.setStyleSheet(f"color:{WHITE}; font-size:11px; font-weight:700; letter-spacing:1.5px;")
        tl.addWidget(title_lbl)

        self._count_badge = QLabel("0")
        self._count_badge.setFixedSize(26, 20)
        self._count_badge.setAlignment(Qt.AlignCenter)
        self._count_badge.setStyleSheet(
            f"background:{MID}; color:{WHITE}; border-radius:3px; font-size:10px; font-weight:bold;"
        )
        tl.addWidget(self._count_badge)
        tl.addStretch(1)

        # Filter combo
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["All Routes", "Routed", "Partial", "Unserved"])
        self._filter_combo.setFixedWidth(130)
        self._filter_combo.currentTextChanged.connect(self._apply_filter)
        tl.addWidget(self._filter_combo)

        # Search box
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search routes…")
        self._search_box.setFixedWidth(160)
        self._search_box.textChanged.connect(self._apply_filter)
        tl.addWidget(self._search_box)

        # Icon buttons: grid view / export
        grid_btn = QToolButton()
        grid_btn.setText("⊞")
        grid_btn.setToolTip("Toggle column layout")
        grid_btn.setFixedSize(26, 26)
        grid_btn.setStyleSheet(f"""
            QToolButton {{ background:{NAVY}; border:1px solid {MID}; color:{GREY};
                           border-radius:3px; font-size:14px; }}
            QToolButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}
        """)
        tl.addWidget(grid_btn)

        export_btn = QToolButton()
        export_btn.setText("↑CSV")
        export_btn.setToolTip("Export routes table to CSV")
        export_btn.setFixedHeight(26)
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.clicked.connect(self._on_export_csv)
        export_btn.setStyleSheet(f"""
            QToolButton {{ background:{NAVY}; border:1px solid {MID}; color:{GREY};
                           border-radius:3px; font-size:10px; padding:0 6px; }}
            QToolButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}
        """)
        tl.addWidget(export_btn)

        refresh_btn = QToolButton()
        refresh_btn.setText("↻")
        refresh_btn.setToolTip("Refresh routes table")
        refresh_btn.setFixedSize(26, 26)
        refresh_btn.clicked.connect(self.refresh)
        refresh_btn.setStyleSheet(f"""
            QToolButton {{ background:{NAVY}; border:1px solid {MID}; color:{GREY};
                           border-radius:3px; font-size:14px; }}
            QToolButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}
        """)
        tl.addWidget(refresh_btn)

        root.addWidget(toolbar)

        # ── Table ────────────────────────────────────────────────────────────
        self._model = RoutesTableModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)   # search all columns

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(28)

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        hh.setSortIndicatorShown(True)
        self._table.setSortingEnabled(True)

        # Sensible default column widths
        col_widths = [90, 80, 90, 110, 75, 60, 60, 75, 65, 80]
        for i, w in enumerate(col_widths):
            self._table.setColumnWidth(i, w)

        self._table.clicked.connect(self._on_row_clicked)
        root.addWidget(self._table)

        # ── Empty state ──────────────────────────────────────────────────────
        self._empty_lbl = QLabel("Open a project to see routes.")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setStyleSheet(f"color:{MID}; font-size:11px; padding:16px;")
        root.addWidget(self._empty_lbl)
        self._empty_lbl.setVisible(True)
        self._table.setVisible(False)

    # ── DATA ────────────────────────────────────────────────────────────────────

    def set_project(self, project):
        self._project = project
        self.refresh()

    def refresh(self):
        if not self._project:
            self._table.setVisible(False)
            self._empty_lbl.setVisible(True)
            self._count_badge.setText("0")
            return
        rows = self._load_routes()
        self._model.load(rows)
        self._apply_filter()
        self._table.setVisible(True)
        self._empty_lbl.setVisible(False)
        self._count_badge.setText(str(len(rows)))

    def _load_routes(self):
        """Build a row list from the cables/bundles/drop_ducts layers."""
        rows = []
        if not self._project:
            return rows
        try:
            # Build from cables layer as a proxy for routes (no dedicated routes layer in v1 schema)
            cables_layer = self._project.get_layer("cables")
            if not cables_layer or not cables_layer.isValid():
                return rows

            for feat in cables_layer.getFeatures():
                geom = feat.geometry()
                length_m = geom.length() if geom and not geom.isEmpty() else 0

                status_raw = feat["installation_status"] if "installation_status" in feat.fields().names() else ""
                if status_raw in ("routed", "ROUTED", "in service", "In Service"):
                    status = "Routed"
                elif status_raw in ("partial", "PARTIAL"):
                    status = "Partial"
                else:
                    status = "Unserved"

                cable_id = feat["cable_id"] if "cable_id" in feat.fields().names() else str(feat.id())
                from_node = feat["from_node"] if "from_node" in feat.fields().names() else "–"
                to_node   = feat["to_node"]   if "to_node"   in feat.fields().names() else "–"
                fibre_count = feat["fibre_count"] if "fibre_count" in feat.fields().names() else 0

                rows.append({
                    "route_id":  cable_id,
                    "status":    status,
                    "from_node": from_node or "–",
                    "to_node":   to_node or "–",
                    "length":    f"{length_m/1000:.2f} km" if length_m >= 100 else f"{length_m:.0f} m",
                    "assets":    "–",
                    "fibres":    str(fibre_count) if fibre_count else "–",
                    "capacity":  "–",
                    "updated":   "–",
                    "engineer":  "–",
                })
        except Exception as e:
            print(f"[Conductor Routes] load error: {e}")
        return rows

    def _apply_filter(self):
        status_filter = self._filter_combo.currentText()
        search_text   = self._search_box.text().strip()

        # Apply status filter via regex on column 1 (Status)
        if status_filter == "All Routes":
            self._proxy.setFilterFixedString(search_text)
            self._proxy.setFilterKeyColumn(-1)
        else:
            # Two-stage: status first, then search text applied as regex on all
            self._proxy.setFilterKeyColumn(1)
            self._proxy.setFilterFixedString(status_filter)

        # Update visible count in badge
        self._count_badge.setText(str(self._proxy.rowCount()))

    def _on_row_clicked(self, proxy_index):
        """Zoom map canvas to the selected route's geometry."""
        if not self._project:
            return
        try:
            src_index = self._proxy.mapToSource(proxy_index)
            row_data = self._model.get_row(src_index.row())
            if not row_data:
                return
            cable_id = row_data.get("route_id")
            cables_layer = self._project.get_layer("cables")
            if not cables_layer:
                return
            feats = [f for f in cables_layer.getFeatures()
                     if str(f["cable_id"]) == str(cable_id)]
            if feats and feats[0].geometry():
                from qgis.core import QgsRectangle
                bbox = feats[0].geometry().boundingBox()
                bbox.scale(2.0)
                self.iface.mapCanvas().setExtent(bbox)
                self.iface.mapCanvas().refresh()
        except Exception:
            pass

    def _on_export_csv(self):
        from qgis.PyQt.QtWidgets import QFileDialog
        import csv
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Routes to CSV", "routes.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            rows = [self._model.get_row(i) for i in range(self._model.rowCount())]
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else [])
                writer.writeheader()
                writer.writerows(rows)
            self.iface.messageBar().pushSuccess("Conductor", f"Routes exported to {path}")
        except Exception as e:
            self.iface.messageBar().pushCritical("Conductor", f"CSV export failed: {e}")

    # ── CLOSE ────────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        super().closeEvent(event)
