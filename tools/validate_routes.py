"""
validate_routes.py  —  Conductor FTTP Network Design Plugin
Fibre route validator: traces every premises back to its cabinet via
bundles/drop_ducts → joints → cables, reporting breaks with reasons.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QFrame, QSplitter, QTextEdit, QWidget
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QBrush
from qgis.core import (
    QgsProject, QgsFeatureRequest, QgsGeometry, QgsPointXY,
    QgsRectangle, QgsMapLayer, QgsWkbTypes, NULL
)
from qgis.gui import QgsRubberBand
import traceback
from ..conductor_utils import get_layer, fld, val, LayerEditContext


# ── Status constants ──────────────────────────────────────────────────────────

STATUS_OK       = "ROUTED"
STATUS_PARTIAL  = "PARTIAL"
STATUS_UNSERVED = "UNSERVED"
STATUS_ERROR    = "ERROR"

STATUS_COLOURS = {
    STATUS_OK:       QColor("#1a6b3c"),
    STATUS_PARTIAL:  QColor("#b85c00"),
    STATUS_UNSERVED: QColor("#c0392b"),
    STATUS_ERROR:    QColor("#7f0000"),
}

STATUS_BG = {
    STATUS_OK:       QColor("#eaf7ee"),
    STATUS_PARTIAL:  QColor("#fff4e6"),
    STATUS_UNSERVED: QColor("#fdecea"),
    STATUS_ERROR:    QColor("#fdecea"),
}

# Display order when the table is sorted by Status — ROUTED first (all good),
# then PARTIAL (in the build plan but broken — needs attention), then
# UNSERVED (not connected yet — expected for most of an in-progress build),
# then ERROR.
STATUS_SORT_RANK = {
    STATUS_OK:       0,
    STATUS_PARTIAL:  1,
    STATUS_UNSERVED: 2,
    STATUS_ERROR:    3,
}


class _StatusTableItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by STATUS_SORT_RANK instead of alphabetically."""

    def __lt__(self, other):
        try:
            return (STATUS_SORT_RANK.get(self.text(), 99)
                    < STATUS_SORT_RANK.get(other.text(), 99))
        except Exception:
            return super().__lt__(other)

MAX_HOPS = 50

# Asset ID substring -> (layer name, ID field). Used to resolve a break-point
# asset ID (from a PARTIAL trace path) back to a feature so we can zoom/highlight it.
BREAK_ASSET_LAYERS = [
    ("-JNT-",  "joints",     "joint_id"),
    ("-CBL-",  "cables",     "cable_id"),
    ("-DDCT-", "drop_ducts", "ddct_id"),
    ("-BDL-",  "bundles",    "bundle_id"),
    ("-DUCT-", "ducts",      "duct_id"),
    ("-CMBR-", "chambers",   "chamber_id"),
]


def find_break_asset(path, project=None):
    """
    Given a PARTIAL trace path (list of asset IDs, last = break point),
    walk it from the end backwards and return the first asset that resolves
    to a real feature: (asset_id, layer_display_name, geometry).
    Returns None if nothing in the path can be resolved.
    """
    for asset_id in reversed(path or []):
        asset_id = str(asset_id)
        for substr, layer_name, id_field in BREAK_ASSET_LAYERS:
            if substr not in asset_id:
                continue
            layer = get_layer(layer_name, project)
            if layer is None:
                continue
            for feat in layer.getFeatures():
                if str(feat[id_field]) == asset_id:
                    geom = feat.geometry()
                    if geom and not geom.isEmpty():
                        return (asset_id, layer.name(), geom)
            break  # matched a prefix but no feature found — don't try other prefixes for this id
    return None


# ── Layer helpers ─────────────────────────────────────────────────────────────



def _build_index(layer, key_field):
    idx = {}
    if layer is None:
        return idx
    for feat in layer.getFeatures():
        val = feat[key_field]
        if val and val != NULL:
            idx.setdefault(str(val), []).append(feat)
    return idx


def _build_cable_node_index(cable_layer):
    idx = {}
    if cable_layer is None:
        return idx
    for feat in cable_layer.getFeatures():
        for field in ("from_node", "to_node"):
            val = feat[field]
            if val and val != NULL:
                idx.setdefault(str(val), []).append(feat)
    return idx


def trace_premises(uprn, area_id,
                   bundle_idx, ddct_idx,
                   joint_idx, cable_node_idx):
    path = []

    bundles = bundle_idx.get(str(uprn), [])
    ddcts   = ddct_idx.get(str(uprn), [])

    entry_asset = None
    entry_type  = None
    first_joint = None

    if bundles:
        b = bundles[0]
        entry_asset = str(b["bundle_id"])
        entry_type  = "bundle"
        first_joint = str(b["from_joint"]) if b["from_joint"] and b["from_joint"] != NULL else None
    elif ddcts:
        d = ddcts[0]
        entry_asset = str(d["ddct_id"])
        entry_type  = "drop_duct"
        fc = d["from_chamber"] if d["from_chamber"] and d["from_chamber"] != NULL else None
        fp = d["from_pole"]    if d["from_pole"]    and d["from_pole"]    != NULL else None
        if fc:
            matched = [jf for jlist in joint_idx.values()
                       for jf in jlist
                       if str(jf["joint_id"]) == str(fc)]
            if matched:
                first_joint = str(matched[0]["joint_id"])
            else:
                # from_chamber holds a joint_id directly — try it
                if str(fc) in joint_idx:
                    first_joint = str(fc)
                else:
                    path.append(entry_asset)
                    path.append(str(fc))
                    return (STATUS_PARTIAL, path,
                            f"Drop duct from joint {fc} but joint not found. "
                            f"Check from_chamber value on {entry_asset}.")
        elif fp:
            # PIA_AERIAL_DROP — from_pole holds a pole_id, not a joint_id.
            # Find the CBT joint mounted on that pole.
            matched = [jf for jlist in joint_idx.values()
                       for jf in jlist
                       if str(jf["joint_type"] or "") == "CBT"
                       and str(jf["pole_id"]) == str(fp)]
            if matched:
                first_joint = str(matched[0]["joint_id"])
            else:
                path.append(entry_asset)
                path.append(str(fp))
                return (STATUS_PARTIAL, path,
                        f"Aerial drop from pole {fp} but no CBT found on that pole. "
                        f"Check from_pole value on {entry_asset}.")
        else:
            first_joint = None

    if not first_joint:
        if entry_asset is None:
            # No bundle or drop duct at all — this premises simply hasn't
            # been connected to the network yet. This is a build-plan state,
            # not a broken route, so it's UNSERVED rather than PARTIAL.
            return (STATUS_UNSERVED, path,
                    "No bundle or drop duct connects this premises to the network yet. "
                    "Digitise a Drop Duct or Bundle from this premises to a joint.")
        return (STATUS_PARTIAL, path + [entry_asset],
                f"{(entry_type or 'asset').replace('_',' ').title()} {entry_asset} has no from_joint value.")

    joints = joint_idx.get(first_joint, [])
    if not joints:
        return (STATUS_PARTIAL, path + [entry_asset],
                f"from_joint '{first_joint}' not found in joints layer. "
                f"Joint may have been deleted or ID mismatch.")

    # BFS — explore all branches, return shortest path to cabinet
    # State: (current_node, path_so_far, visited_set)
    from collections import deque
    queue = deque()
    queue.append((first_joint, [first_joint], {first_joint}))

    best_partial = None
    best_partial_reason = f"No cable connected to joint {first_joint}. Digitise a cable from this joint toward the cabinet."

    while queue:
        current_node, cur_path, visited = queue.popleft()

        if len(cur_path) > MAX_HOPS * 2:
            continue  # safety cap

        cables = cable_node_idx.get(current_node, [])
        if not cables:
            if best_partial is None:
                best_partial = cur_path
                best_partial_reason = (f"No cable connected to joint {current_node}. "
                                       f"Digitise a cable from this joint toward the cabinet.")
            continue

        for cable in cables:
            fn = str(cable["from_node"]) if cable["from_node"] and cable["from_node"] != NULL else ""
            tn = str(cable["to_node"])   if cable["to_node"]   and cable["to_node"]   != NULL else ""
            next_node = tn if fn == current_node else fn

            if not next_node or next_node in visited:
                continue

            cable_id = str(cable["cable_id"])
            new_path = cur_path + [cable_id]

            if isinstance(next_node, str) and ("CAB" in next_node.upper() or "POP" in next_node.upper()):
                new_path.append(next_node)
                return (STATUS_OK, new_path, f"Route complete — {len(new_path)} hops.")

            new_visited = visited | {next_node}
            new_path    = new_path + [next_node]
            queue.append((next_node, new_path, new_visited))

            if best_partial is None or len(new_path) > len(best_partial):
                best_partial = new_path
                best_partial_reason = (f"Dead end reached at {next_node} — "                                       f"no onward cable leads to the cabinet.")

    return (STATUS_PARTIAL, best_partial or [first_joint],
            best_partial_reason)


# ── Worker thread ─────────────────────────────────────────────────────────────

class ValidateWorker(QThread):
    progress  = pyqtSignal(int, int)
    result    = pyqtSignal(dict)
    finished  = pyqtSignal(list, dict)

    def __init__(self, layer_names, project=None):
        super().__init__()
        self._layer_names = layer_names
        self._project = project

    def run(self):
        results = []
        summary = {STATUS_OK: 0, STATUS_PARTIAL: 0, STATUS_UNSERVED: 0, STATUS_ERROR: 0}
        try:
            premises_layer = get_layer(self._layer_names["premises"], self._project)
            bundle_layer   = get_layer(self._layer_names["bundles"],   self._project)
            ddct_layer     = get_layer(self._layer_names["drop_ducts"], self._project)
            joint_layer    = get_layer(self._layer_names["joints"],    self._project)
            cable_layer    = get_layer(self._layer_names["cables"],    self._project)

            if not premises_layer:
                self.finished.emit([], {"error": "Premises layer not found."})
                return
            if not cable_layer:
                self.finished.emit([], {"error": "Cables layer not found."})
                return

            bundle_idx     = _build_index(bundle_layer, "uprn")   if bundle_layer else {}
            ddct_idx       = _build_index(ddct_layer,   "uprn")   if ddct_layer   else {}
            joint_idx      = _build_index(joint_layer,  "joint_id")
            cable_node_idx = _build_cable_node_index(cable_layer)


            premises_list = list(premises_layer.getFeatures())
            total = len(premises_list)

            for i, prem in enumerate(premises_list):
                self.progress.emit(i + 1, total)
                uprn    = prem["uprn"]
                fields = prem.fields().names()
                if "address_1" in fields:
                    a1 = str(prem["address_1"] or "")
                    a2 = str(prem["address_2"] or "") if "address_2" in fields else ""
                    pc = str(prem["postcode"] or "")  if "postcode"  in fields else ""
                    address = ", ".join(p for p in [a1, a2, pc] if p)
                elif "address" in fields:
                    address = str(prem["address"] or "")
                else:
                    address = str(uprn)
                area_id = prem["area_id"] if "area_id" in prem.fields().names() else ""

                try:
                    status, path, reason = trace_premises(
                        uprn, area_id,
                        bundle_idx, ddct_idx,
                        joint_idx, cable_node_idx,
                    )
                except Exception as e:
                    status = STATUS_ERROR
                    path   = []
                    reason = f"Exception during trace: {e}"

                summary[status] = summary.get(status, 0) + 1
                results.append({
                    "uprn":    str(uprn),
                    "address": str(address),
                    "status":  status,
                    "path":    path,
                    "reason":  reason,
                    "geom":    prem.geometry(),
                })
                self.result.emit(results[-1])

        except Exception as e:
            self.finished.emit(results, {"error": traceback.format_exc()})
            return

        self.finished.emit(results, summary)


# ── Results dialog ────────────────────────────────────────────────────────────

class ValidateRoutesDialog(QDialog):

    LAYER_NAMES = {
        "premises":   "premises",
        "bundles":    "bundles",
        "drop_ducts": "drop_ducts",
        "joints":     "joints",
        "cables":     "cables",
    }

    def __init__(self, iface, parent=None, project=None):
        super().__init__(parent)
        self.iface   = iface
        self.project = project
        self.results = []
        self._worker = None
        self._bands  = []   # active QgsRubberBand highlights for the "break" asset
        self._setup_ui()

    # ── Highlight management ──────────────────────────────────────────────────

    def _clear_bands(self):
        canvas = self.iface.mapCanvas()
        for band in self._bands:
            try:
                band.reset()
                canvas.scene().removeItem(band)
            except Exception:
                pass
        self._bands = []

    def _to_canvas_crs(self, geom):
        """Reproject a geometry from EPSG:27700 (Conductor layer CRS) to the
        canvas/project CRS, if they differ. Returns a transformed copy."""
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform
        src = QgsCoordinateReferenceSystem("EPSG:27700")
        geom = QgsGeometry(geom)
        if src != canvas_crs:
            xform = QgsCoordinateTransform(src, canvas_crs, QgsProject.instance())
            geom.transform(xform)
        return geom

    def _highlight_geometry(self, geom):
        """geom must already be in canvas CRS (see _to_canvas_crs)."""
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()

        if geom.type() == QgsWkbTypes.PointGeometry:
            band = QgsRubberBand(canvas, QgsWkbTypes.PointGeometry)
            band.setColor(QColor("#e63946"))
            band.setIconSize(16)
            band.setIcon(QgsRubberBand.ICON_CIRCLE)
        else:
            band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
            band.setColor(QColor("#e63946"))
            band.setWidth(4)
        band.setZValue(1000)
        band.setToGeometry(geom, canvas_crs)
        self._bands.append(band)

    def _setup_ui(self):
        self.setWindowTitle("Conductor — Validate Fibre Routes")
        self.setMinimumSize(820, 560)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        header = QLabel("Fibre Route Validator")
        header.setStyleSheet("font-size:15px; font-weight:600; color:#1a1a1a;")
        root.addWidget(header)

        sub = QLabel("Traces every premises to its cabinet via bundles / drop ducts → joints → cables. Flags any break in the chain.")
        sub.setStyleSheet("font-size:11px; color:#555; margin-bottom:4px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self._summary_bar = QFrame()
        self._summary_bar.setStyleSheet("QFrame { background:#f5f5f5; border:1px solid #ddd; border-radius:4px; padding:6px; }")
        bar_layout = QHBoxLayout(self._summary_bar)
        bar_layout.setContentsMargins(8, 4, 8, 4)
        bar_layout.setSpacing(20)

        self._lbl_total    = self._stat_label("Total",    "—", "#444")
        self._lbl_routed   = self._stat_label("Routed",   "—", STATUS_COLOURS[STATUS_OK].name())
        self._lbl_partial  = self._stat_label("Partial",  "—", STATUS_COLOURS[STATUS_PARTIAL].name())
        self._lbl_unserved = self._stat_label("Unserved", "—", STATUS_COLOURS[STATUS_UNSERVED].name())

        for w in (self._lbl_total, self._lbl_routed, self._lbl_partial, self._lbl_unserved):
            bar_layout.addWidget(w)
        bar_layout.addStretch()
        root.addWidget(self._summary_bar)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        self._progress.setStyleSheet(
            "QProgressBar { border:1px solid #ccc; border-radius:3px; background:#f0f0f0; height:18px; font-size:11px; } "
            "QProgressBar::chunk { background:#2c7a4b; border-radius:2px; }"
        )
        root.addWidget(self._progress)

        splitter = QSplitter(Qt.Vertical)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Status", "UPRN", "Address", "Detail"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(
            "QTableWidget { font-size:12px; gridline-color:#e8e8e8; }"
            "QTableWidget::item:selected { background:#d0e8ff; color:#000; }"
            "QHeaderView::section { background:#f0f0f0; font-weight:600; padding:4px; border:none; border-bottom:1px solid #ccc; }"
        )
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        splitter.addWidget(self._table)

        detail_frame = QFrame()
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.setSpacing(4)
        detail_header = QLabel("Route detail")
        detail_header.setStyleSheet("font-size:11px; font-weight:600; color:#444;")
        detail_layout.addWidget(detail_header)
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(130)
        self._detail.setStyleSheet(
            "QTextEdit { font-family: 'Consolas','Courier New',monospace; "
            "font-size:11px; background:#fafafa; border:1px solid #ddd; border-radius:3px; padding:4px; }"
        )
        detail_layout.addWidget(self._detail)
        splitter.addWidget(detail_frame)
        splitter.setSizes([360, 130])
        root.addWidget(splitter)

        btn_row = QHBoxLayout()

        self._btn_run = QPushButton("\u25b6  Run Validation")
        self._btn_run.setStyleSheet(
            "QPushButton { background:#2c7a4b; color:#fff; font-weight:600; padding:7px 18px; border-radius:4px; font-size:12px; } "
            "QPushButton:hover { background:#245f3a; } "
            "QPushButton:disabled { background:#aaa; }"
        )
        self._btn_run.clicked.connect(self._run)

        self._btn_zoom = QPushButton("\u233e  Zoom to Selected")
        self._btn_zoom.setEnabled(False)
        self._btn_zoom.setStyleSheet("QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; border:1px solid #bbb; } QPushButton:hover { background:#e8e8e8; } QPushButton:disabled { color:#aaa; }")
        self._btn_zoom.clicked.connect(self._zoom_to_selected)

        self._btn_export = QPushButton("\u2193  Export CSV")
        self._btn_export.setEnabled(False)
        self._btn_export.setStyleSheet("QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; border:1px solid #bbb; } QPushButton:hover { background:#e8e8e8; } QPushButton:disabled { color:#aaa; }")
        self._btn_export.clicked.connect(self._export_csv)

        self._btn_close = QPushButton("Close")
        self._btn_close.setStyleSheet("QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; border:1px solid #bbb; } QPushButton:hover { background:#e8e8e8; }")
        self._btn_close.clicked.connect(self.close)

        btn_row.addWidget(self._btn_run)
        btn_row.addWidget(self._btn_zoom)
        btn_row.addWidget(self._btn_export)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

    def _stat_label(self, title, value, colour):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(f"font-size:20px; font-weight:700; color:{colour};")
        ttl_lbl = QLabel(title)
        ttl_lbl.setStyleSheet("font-size:10px; color:#777; text-transform:uppercase;")
        layout.addWidget(val_lbl)
        layout.addWidget(ttl_lbl)
        w._value_label = val_lbl
        return w

    def _update_stat(self, widget, value):
        widget._value_label.setText(str(value))

    def _run(self):
        self._table.setRowCount(0)
        self.results = []
        self._detail.clear()
        self._clear_bands()
        self._btn_run.setEnabled(False)
        self._btn_zoom.setEnabled(False)
        self._btn_export.setEnabled(False)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._update_stat(self._lbl_total,    "\u2026")
        self._update_stat(self._lbl_routed,   "\u2014")
        self._update_stat(self._lbl_partial,  "\u2014")
        self._update_stat(self._lbl_unserved, "\u2014")

        self._worker = ValidateWorker(self.LAYER_NAMES, project=self.project)
        self._worker.progress.connect(self._on_progress)
        self._worker.result.connect(self._on_result)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, done, total):
        self._progress.setMaximum(total)
        self._progress.setValue(done)
        self._progress.setFormat(f"Checking {done} / {total}")
        self._update_stat(self._lbl_total, total)

    def _on_result(self, r):
        self.results.append(r)
        row = self._table.rowCount()
        self._table.insertRow(row)
        status = r["status"]
        colour = STATUS_COLOURS[status]
        bg     = STATUS_BG[status]
        status_item  = _StatusTableItem(status)
        status_item.setForeground(QBrush(colour))
        status_item.setFont(QFont("", -1, QFont.Bold))
        uprn_item    = QTableWidgetItem(r["uprn"])
        address_item = QTableWidgetItem(r["address"])
        reason_item  = QTableWidgetItem(r["reason"])
        for item in (status_item, uprn_item, address_item, reason_item):
            item.setData(Qt.UserRole, len(self.results) - 1)
            item.setBackground(QBrush(bg))
        self._table.setItem(row, 0, status_item)
        self._table.setItem(row, 1, uprn_item)
        self._table.setItem(row, 2, address_item)
        self._table.setItem(row, 3, reason_item)

    def _on_finished(self, results, summary):
        self._progress.setVisible(False)
        self._btn_run.setEnabled(True)
        if "error" in summary:
            self._detail.setPlainText(f"Validation error:\n{summary['error']}")
            return
        self._update_stat(self._lbl_routed,   summary.get(STATUS_OK, 0))
        self._update_stat(self._lbl_partial,  summary.get(STATUS_PARTIAL, 0))
        self._update_stat(self._lbl_unserved, summary.get(STATUS_UNSERVED, 0))
        if results:
            self._btn_export.setEnabled(True)
        self._table.sortItems(0)

    def _on_row_selected(self):
        rows = self._table.selectedItems()
        if not rows:
            return
        idx = rows[0].data(Qt.UserRole)
        if idx is None or idx >= len(self.results):
            return
        r = self.results[idx]
        self._btn_zoom.setEnabled(r["geom"] is not None and not r["geom"].isEmpty())
        self._show_detail(r)

    def _show_detail(self, r):
        lines = [
            f"UPRN:    {r['uprn']}",
            f"Address: {r['address']}",
            f"Status:  {r['status']}",
            f"Reason:  {r['reason']}",
        ]
        if r["status"] == STATUS_PARTIAL:
            found = find_break_asset(r["path"], self.project)
            if found:
                asset_id, layer_name, _geom = found
                lines.append(f"Issue at: {asset_id}  ({layer_name}) \u2014 Zoom to Selected will jump here.")
        lines += ["", "Path:"]
        if r["path"]:
            for i, node in enumerate(r["path"]):
                prefix = "  \u2514\u2500 " if i == len(r["path"]) - 1 else "  \u251c\u2500 "
                lines.append(f"{prefix}{node}")
        else:
            lines.append("  (no path traced)")
        self._detail.setPlainText("\n".join(lines))

    def _zoom_to_selected(self):
        rows = self._table.selectedItems()
        if not rows:
            return
        idx = rows[0].data(Qt.UserRole)
        if idx is None or idx >= len(self.results):
            return
        r = self.results[idx]
        self._clear_bands()
        canvas = self.iface.mapCanvas()

        # For PARTIAL results, try to zoom to the actual break-point asset
        # (e.g. the joint with no onward cable, or the bundle/drop duct with
        # a bad from_joint) rather than just the premises location.
        if r["status"] == STATUS_PARTIAL:
            found = find_break_asset(r["path"], self.project)
            if found:
                asset_id, layer_name, geom = found
                geom = self._to_canvas_crs(geom)
                extent = geom.boundingBox()
                extent.scale(3.0)  # pad so the asset isn't a single pixel
                if extent.width() < 20 or extent.height() < 20:
                    extent = QgsRectangle(
                        extent.center().x() - 25, extent.center().y() - 25,
                        extent.center().x() + 25, extent.center().y() + 25,
                    )
                canvas.setExtent(extent)
                self._highlight_geometry(geom)
                canvas.refresh()
                return

        geom = r["geom"]
        if geom and not geom.isEmpty():
            pt = geom.asPoint()
            buf = 50
            extent = QgsRectangle(pt.x() - buf, pt.y() - buf, pt.x() + buf, pt.y() + buf)
            canvas.setExtent(extent)
            canvas.refresh()

    def closeEvent(self, event):
        self._clear_bands()
        super().closeEvent(event)

    def _export_csv(self):
        from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "Export Validation Results", "", "CSV files (*.csv)")
        if not path:
            return
        if not path.endswith(".csv"):
            path += ".csv"
        import io
        from ..conductor_utils import safe_write_text, log
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["UPRN", "Address", "Status", "Reason", "Path"])
        for r in self.results:
            writer.writerow([r["uprn"], r["address"], r["status"], r["reason"], " \u2192 ".join(r["path"])])
        try:
            actual = safe_write_text(path, buf.getvalue(), what="Validation CSV")
        except Exception as e:
            QMessageBox.critical(self, "Export failed",
                                 f"Could not save results \u2014 the file may be open "
                                 f"in another program.\n\n{e}")
            return
        QMessageBox.information(self, "Export complete", f"Results saved to:\n{actual}")


def open_validate_routes_dialog(iface, parent=None, project=None):
    dlg = ValidateRoutesDialog(iface, parent, project=project)
    dlg.show()
    return dlg
