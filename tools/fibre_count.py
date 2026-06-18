# -*- coding: utf-8 -*-
"""
fibre_count.py  —  Conductor FTTP Network Design Plugin
Fibre Count Calculator: walks the cable network from the cabinet outward,
counts premises served downstream of each cable segment, and reports
required vs actual fibre count with a RAG status.
"""

from collections import defaultdict

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QSizePolicy, QAbstractItemView
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

from qgis.core import NULL

from ..conductor_utils import get_layer, fld, val, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID

# ── Constants ─────────────────────────────────────────────────────────────────

# Standard fibre counts available in the market
STANDARD_FIBRE_COUNTS = [2, 4, 6, 8, 12, 24, 48, 96, 144, 288]

# Fibres needed per premises (1 per premises — splitter handles sharing)
FIBRES_PER_PREMISES = 1

# RAG colours
GREEN  = QColor(22, 163,  74)   # sufficient
AMBER  = QColor(217, 119,   6)  # within 10% of capacity
RED    = QColor(220,  38,  38)  # over capacity
GREY   = QColor(120, 120, 120)  # no assignment data


# ── Network analysis ──────────────────────────────────────────────────────────

def _build_downstream_counts(cable_layer, bundle_layer, ddct_layer):
    """
    Walk the cable network from every cabinet outward.
    Returns a dict: cable_id → downstream_premises_count
    """
    if not cable_layer:
        return {}

    # Build adjacency: node → list of (cable_feat, other_node)
    adjacency = defaultdict(list)
    cables = list(cable_layer.getFeatures())
    for feat in cables:
        fn = str(feat["from_node"]) if feat["from_node"] and feat["from_node"] != NULL else ""
        tn = str(feat["to_node"])   if feat["to_node"]   and feat["to_node"]   != NULL else ""
        if fn and tn:
            adjacency[fn].append((feat, tn))
            adjacency[tn].append((feat, fn))

    # Count unique premises per joint/CBT (use sets to avoid double-counting
    # premises that have both a bundle and a drop duct record)
    joint_uprns = defaultdict(set)
    if bundle_layer:
        for feat in bundle_layer.getFeatures():
            fj   = str(feat["from_joint"]) if feat["from_joint"] and feat["from_joint"] != NULL else ""
            uprn = feat["uprn"]
            if fj and uprn and uprn != NULL:
                joint_uprns[fj].add(str(uprn))

    if ddct_layer:
        for feat in ddct_layer.getFeatures():
            fc   = str(feat["from_chamber"]) if feat["from_chamber"] and feat["from_chamber"] != NULL else ""
            uprn = feat["uprn"]
            if fc and uprn and uprn != NULL:
                joint_uprns[fc].add(str(uprn))

    joint_premises = {k: len(v) for k, v in joint_uprns.items()}

    # Find cabinet nodes (CAB or POP)
    all_nodes = set(adjacency.keys())
    cabinet_nodes = {n for n in all_nodes if "CAB" in n.upper() or "POP" in n.upper()}

    if not cabinet_nodes:
        return {}

    # BFS outward from cabinet — assign downstream premise counts to each cable
    cable_downstream = {}
    visited_nodes = set()

    from collections import deque
    queue = deque()
    for cab in cabinet_nodes:
        queue.append(cab)
        visited_nodes.add(cab)

    # First pass — determine traversal order (BFS tree from cabinet)
    traversal_order = []  # list of (cable_id, parent_node, child_node)
    while queue:
        node = queue.popleft()
        for cable_feat, neighbor in adjacency[node]:
            if neighbor not in visited_nodes:
                visited_nodes.add(neighbor)
                cid = str(cable_feat["cable_id"])
                traversal_order.append((cid, node, neighbor, cable_feat))
                queue.append(neighbor)

    # Second pass — walk leaves back to root, accumulating counts
    # node_total[node] = total premises reachable from this node (away from cabinet)
    node_total = defaultdict(int)

    # Seed with direct premise connections
    for node, count in joint_premises.items():
        node_total[node] += count

    # Process in reverse traversal order (leaves first)
    cable_info = {}  # cable_id → (cable_feat, parent_node, child_node)
    for cid, parent, child, feat in traversal_order:
        cable_info[cid] = (feat, parent, child)

    for cid, parent, child, feat in reversed(traversal_order):
        # child's subtotal flows up through this cable to parent
        child_subtotal = node_total[child]
        node_total[parent] += child_subtotal
        cable_downstream[cid] = child_subtotal

    return cable_downstream, cable_info


def _next_standard_size(n):
    """Return the smallest standard fibre count >= n."""
    for s in STANDARD_FIBRE_COUNTS:
        if s >= n:
            return s
    return STANDARD_FIBRE_COUNTS[-1]


# ── Dialog ────────────────────────────────────────────────────────────────────

class FibreCountDialog(QDialog):

    def __init__(self, iface, parent=None, project=None):
        super().__init__(parent)
        self.iface    = iface
        self._project = project
        self.setWindowTitle("Conductor — Fibre Count Calculator")
        self.setMinimumWidth(780)
        self.setMinimumHeight(500)
        self._build_ui()
        self._run()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # Header
        title = QLabel("Fibre Count Calculator")
        title.setStyleSheet(f"font-size:15px; font-weight:700; color:{NAVY};")
        root.addWidget(title)

        sub = QLabel(
            "Shows the number of premises served downstream of each cable segment, "
            "the fibres required, and the recommended cable size."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"font-size:11px; color:#555;")
        root.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{MID};")
        root.addWidget(sep)

        # Summary row
        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet(f"font-size:12px; color:{NAVY}; font-weight:600;")
        root.addWidget(self._summary_lbl)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "Cable ID", "Type", "From Node", "To Node",
            "Premises\nDownstream", "Fibres\nRequired", "Installed\nFibre Count"
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(
            f"QTableWidget {{ font-size:11px; background:{WHITE}; gridline-color:{MID}; }}"
            f"QTableWidget::item:selected {{ background:{TEAL}; color:{WHITE}; }}"
            f"QHeaderView::section {{ background:{NAVY}; color:{WHITE}; "
            f"font-weight:600; padding:4px; border:none; }}"
        )
        root.addWidget(self._table)

        # Legend
        legend = QHBoxLayout()
        for colour, label in [
            ("#16A34A", "✔  Sufficient capacity"),
            ("#D97706", "⚠  Within 10% of capacity"),
            ("#DC2626", "✘  Over capacity"),
        ]:
            dot = QLabel(f"<span style='color:{colour}; font-weight:700;'>{label}</span>")
            dot.setStyleSheet("font-size:10px;")
            legend.addWidget(dot)
        legend.addStretch()
        root.addLayout(legend)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color:{MID};")
        root.addWidget(sep2)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_refresh = QPushButton("↻  Recalculate")
        self._btn_refresh.setStyleSheet(
            f"QPushButton {{ padding:6px 14px; border-radius:4px; font-size:11px; "
            f"background:{TEAL}; color:{WHITE}; border:none; font-weight:600; }}"
            f"QPushButton:hover {{ background:#155f56; }}"
        )
        self._btn_close = QPushButton("Close")
        self._btn_close.setStyleSheet(
            f"QPushButton {{ padding:6px 14px; border-radius:4px; font-size:11px; "
            f"border:1px solid {MID}; }}"
            f"QPushButton:hover {{ background:#e8e8e8; }}"
        )
        self._btn_refresh.clicked.connect(self._run)
        self._btn_close.clicked.connect(self.close)
        btn_row.addWidget(self._btn_refresh)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

    def _run(self):
        cable_layer  = get_layer("Cables",     self._project)
        bundle_layer = get_layer("bundles",    self._project)
        ddct_layer   = get_layer("drop_ducts", self._project)

        if not cable_layer:
            self._summary_lbl.setText("⚠  Cables layer not found.")
            return

        result = _build_downstream_counts(cable_layer, bundle_layer, ddct_layer)
        if not result:
            self._summary_lbl.setText("⚠  Could not build network graph. Check cable topology.")
            return

        cable_downstream, cable_info = result

        # Get installed fibre counts from layer
        installed = {}
        for feat in cable_layer.getFeatures():
            cid = str(feat["cable_id"])
            fc  = feat["fibre_count"]
            installed[cid] = int(fc) if fc and fc != NULL else 0

        # Build rows
        rows = []
        over_count  = 0
        amber_count = 0
        ok_count    = 0

        for cid, (feat, parent, child) in sorted(cable_info.items()):
            premises    = cable_downstream.get(cid, 0)
            cable_type  = str(feat["cable_type"]) if feat["cable_type"] and feat["cable_type"] != NULL else ""
            # CBT_TAIL carries 1 fibre into the CBT splitter regardless of premises count
            if cable_type == "CBT_TAIL":
                required = 1
            else:
                required = premises * FIBRES_PER_PREMISES
            recommended = _next_standard_size(required) if required > 0 else 0
            actual      = installed.get(cid, 0)
            if actual == 0:
                rag = GREY
            elif actual < required:
                rag = RED
                over_count += 1
            elif actual < required * 1.1 + 1:
                rag = AMBER
                amber_count += 1
            else:
                rag = GREEN
                ok_count += 1

            rows.append((cid, cable_type, parent, child, premises, required, actual, recommended, rag))

        # Sort by premises descending (highest demand first)
        rows.sort(key=lambda r: r[4], reverse=True)

        self._table.setRowCount(len(rows))
        for i, (cid, ctype, parent, child, premises, required, actual, recommended, rag) in enumerate(rows):
            items = [
                QTableWidgetItem(cid),
                QTableWidgetItem(ctype),
                QTableWidgetItem(parent),
                QTableWidgetItem(child),
                QTableWidgetItem(str(premises)),
                QTableWidgetItem(f"{required}  (min {recommended}F)"),
                QTableWidgetItem(str(actual) + "F" if actual else "—"),
            ]
            for j, item in enumerate(items):
                item.setTextAlignment(Qt.AlignVCenter | (Qt.AlignRight if j >= 4 else Qt.AlignLeft))
                # Colour the last three columns by RAG
                if j >= 4:
                    item.setForeground(rag)
                    font = QFont()
                    font.setBold(True)
                    item.setFont(font)
                self._table.setItem(i, j, item)

        total = len(rows)
        summary_parts = [f"{total} cable segment{'s' if total != 1 else ''}"]
        if ok_count:    summary_parts.append(f"<span style='color:#16A34A;'>{ok_count} OK</span>")
        if amber_count: summary_parts.append(f"<span style='color:#D97706;'>{amber_count} tight</span>")
        if over_count:  summary_parts.append(f"<span style='color:#DC2626;'>{over_count} over capacity</span>")
        self._summary_lbl.setText("  —  ".join(summary_parts))
        self._summary_lbl.setTextFormat(Qt.RichText)


# ── Entry point ───────────────────────────────────────────────────────────────

def open_fibre_count_dialog(iface, parent=None, project=None):
    dlg = FibreCountDialog(iface, parent=parent, project=project)
    dlg.show()
    return dlg
