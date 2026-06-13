# -*- coding: utf-8 -*-
"""
bom.py  —  Conductor FTTP Network Design Plugin
Bill of Materials: aggregates fibre and civil layer quantities
into a categorised material list with unit costs and totals.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QTabWidget, QWidget, QDoubleSpinBox, QAbstractItemView
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QBrush, QFont
from qgis.core import QgsProject, NULL
import traceback
from qgis.core import QgsSettings

COST_SETTINGS_PREFIX = "conductor/bom_costs/"


def load_costs():
    """Load unit costs from QgsSettings, falling back to DEFAULT_COSTS."""
    s = QgsSettings()
    costs = {}
    for key, default in DEFAULT_COSTS.items():
        val = s.value(COST_SETTINGS_PREFIX + key, None)
        costs[key] = float(val) if val is not None else default
    return costs


def save_costs(costs):
    """Persist unit costs to QgsSettings."""
    s = QgsSettings()
    for key, val in costs.items():
        s.setValue(COST_SETTINGS_PREFIX + key, float(val))

from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID


# ── Default unit costs (£) ────────────────────────────────────────────────────
# Sourced from Gigaloch material costs sheet (2022 — update as needed)
DEFAULT_COSTS = {
    "shotgun_duct_m":       1.05,
    "duct_16mm_m":          0.37,
    "duct_7mm_m":           0.17,
    "cable_spine_m":        0.66,   # 48F micro-blown
    "cable_7mm_m":          0.11,   # 7mm fibre
    "chamber_each":       175.10,
    "joint_each":         139.99,
    "splitter_1x8_each":   61.75,
    "splitter_1x4_each":  149.81,
    "splitter_1x2_each":   20.00,   # estimate
    "splitter_1x16_each":  80.00,   # estimate
    "splitter_1x32_each": 120.00,   # estimate
    "bundle_m":             0.11,   # same as 7mm fibre
    "drop_duct_m":          0.17,
    "ont_each":            36.75,
    "road_crossing_each": 1500.00,
    "pole_each":           250.00,   # estimate
    "cbt_each":            180.00,   # estimate
    "aerial_cable_m":        0.85,   # aerial self-support
    "aerial_drop_m":         0.22,   # aerial drop wire
}




def _round2(v):
    try:
        return round(float(v), 2) if v and v != NULL else 0.0
    except Exception:
        return 0.0


def _str(v):
    return str(v) if v and v != NULL else ""


def _cost(qty, unit_cost):
    return round(qty * unit_cost, 2)


# ── Aggregation ───────────────────────────────────────────────────────────────

def build_bom(costs=None, project=None):
    if costs is None:
        costs = load_costs()

    bom = {
        "Summary":       [],
        "Fibre Cable":   [],
        "Drop & Bundle": [],
        "Joints":        [],
        "Duct":          [],
        "PIA":           [],
    }

    # ── Cables ────────────────────────────────────────────────────────────────
    cable_layer = get_layer("Cables", project)
    if cable_layer:
        cable_groups = {}
        for feat in cable_layer.getFeatures():
            fc     = int(feat["fibre_count"]) if feat["fibre_count"] and feat["fibre_count"] != NULL else 0
            ft     = _str(feat["fibre_type"]) or "Unknown"
            ct     = _str(feat["cable_type"]) or "FEEDER"
            key    = (fc, ft, ct)
            length = _round2(feat["length_m"])
            if key not in cable_groups:
                cable_groups[key] = {"count": 0, "length_m": 0.0}
            cable_groups[key]["count"]    += 1
            cable_groups[key]["length_m"] += length

        for (fc, ft, ct), vals in sorted(cable_groups.items()):
            unit_cost = costs.get("cable_spine_m", 0.66)
            qty       = round(vals["length_m"], 1)
            bom["Fibre Cable"].append({
                "description": f"{fc}F {ft} Cable ({ct})",
                "unit":        "m",
                "qty":         qty,
                "unit_cost":   unit_cost,
                "total":       _cost(qty, unit_cost),
                "notes":       f"{vals['count']} cable(s)",
            })

    # ── Bundles ───────────────────────────────────────────────────────────────
    bundle_layer = get_layer("Bundles", project)
    if bundle_layer:
        bundle_groups = {}
        for feat in bundle_layer.getFeatures():
            fc     = int(feat["fibre_count"]) if feat["fibre_count"] and feat["fibre_count"] != NULL else 1
            length = _round2(feat["length_m"])
            if fc not in bundle_groups:
                bundle_groups[fc] = {"count": 0, "length_m": 0.0}
            bundle_groups[fc]["count"]    += 1
            bundle_groups[fc]["length_m"] += length

        for fc, vals in sorted(bundle_groups.items()):
            unit_cost = costs.get("bundle_m", 0.11)
            qty       = round(vals["length_m"], 1)
            bom["Drop & Bundle"].append({
                "description": f"{fc}F Bundle (premises drop)",
                "unit":        "m",
                "qty":         qty,
                "unit_cost":   unit_cost,
                "total":       _cost(qty, unit_cost),
                "notes":       f"{vals['count']} bundle(s)",
            })

    # ── Drop Ducts ────────────────────────────────────────────────────────────
    ddct_layer = get_layer("Drop Ducts", project)
    if ddct_layer:
        total_len   = 0.0
        total_count = 0
        for feat in ddct_layer.getFeatures():
            total_len   += _round2(feat["length_m"])
            total_count += 1
        if total_count:
            unit_cost = costs.get("drop_duct_m", 0.17)
            qty       = round(total_len, 1)
            bom["Duct"].append({
                "description": "7mm Speedpipe Drop Duct",
                "unit":        "m",
                "qty":         qty,
                "unit_cost":   unit_cost,
                "total":       _cost(qty, unit_cost),
                "notes":       f"{total_count} drop(s)",
            })

    # ── Joints ────────────────────────────────────────────────────────────────
    joint_layer = get_layer("Joints", project)
    if joint_layer:
        joint_groups    = {}
        splitter_groups = {}
        for feat in joint_layer.getFeatures():
            jt  = _str(feat["joint_type"]) or "SPLICE"
            ct  = _str(feat["closure_type"]) or "Standard"
            key = (jt, ct)
            joint_groups[key] = joint_groups.get(key, 0) + 1
            if feat["has_splitter"] and feat["has_splitter"] != NULL and feat["has_splitter"]:
                sr = _str(feat["split_ratio"]) or "Unknown"
                splitter_groups[sr] = splitter_groups.get(sr, 0) + 1

        for (jt, ct), count in sorted(joint_groups.items()):
            unit_cost = costs.get("joint_each", 139.99)
            bom["Joints"].append({
                "description": f"Joint Closure — {jt.replace('_',' ').title()}",
                "unit":        "each",
                "qty":         count,
                "unit_cost":   unit_cost,
                "total":       _cost(count, unit_cost),
                "notes":       ct or "Standard",
            })

        for sr, count in sorted(splitter_groups.items()):
            # Pick cost by ratio
            ratio_map = {
                "1:2": "splitter_1x2_each", "1:4": "splitter_1x4_each",
                "1:8": "splitter_1x8_each", "1:16": "splitter_1x16_each",
                "1:32": "splitter_1x32_each",
            }
            cost_key  = ratio_map.get(sr, "splitter_1x8_each")
            unit_cost = costs.get(cost_key, 61.75)
            bom["Joints"].append({
                "description": f"Splitter {sr}",
                "unit":        "each",
                "qty":         count,
                "unit_cost":   unit_cost,
                "total":       _cost(count, unit_cost),
                "notes":       "Passive optical splitter",
            })

    # ── Ducts ─────────────────────────────────────────────────────────────────
    duct_layer = get_layer("Ducts", project)
    if duct_layer:
        duct_groups = {}
        for feat in duct_layer.getFeatures():
            dt     = _str(feat["duct_type"]) or "STANDARD"
            st     = _str(feat["surface_type"]) or "Unknown"
            key    = (dt, st)
            length = _round2(feat["length_m"])
            if key not in duct_groups:
                duct_groups[key] = {"count": 0, "length_m": 0.0}
            duct_groups[key]["count"]    += 1
            duct_groups[key]["length_m"] += length

        for (dt, st), vals in sorted(duct_groups.items()):
            if "SHOTGUN" in dt.upper():
                unit_cost = costs.get("shotgun_duct_m", 1.05)
            elif "7MM" in dt.upper():
                unit_cost = costs.get("duct_7mm_m", 0.17)
            else:
                unit_cost = costs.get("duct_16mm_m", 0.37)
            qty = round(vals["length_m"], 1)
            bom["Duct"].append({
                "description": f"{dt.replace('_',' ').title()} Duct ({st.replace('_',' ').title()})",
                "unit":        "m",
                "qty":         qty,
                "unit_cost":   unit_cost,
                "total":       _cost(qty, unit_cost),
                "notes":       f"{vals['count']} run(s)",
            })


    # ── PIA (Poles, CBTs, Aerial Cable, Aerial Drops) ─────────────────────────
    chamber_layer = get_layer("Chambers", project)
    if chamber_layer:
        pole_count = 0
        for feat in chamber_layer.getFeatures():
            pt = _str(feat["pole_type"]) if "pole_type" in [f.name() for f in feat.fields()] else ""
            if pt:
                pole_count += 1
        if pole_count:
            unit_cost = costs.get("pole_each", 250.00)
            bom["PIA"].append({
                "description": "PIA Pole",
                "unit":        "each",
                "qty":         pole_count,
                "unit_cost":   unit_cost,
                "total":       _cost(pole_count, unit_cost),
                "notes":       "Openreach PIA pole attachment",
            })

    joint_layer2 = get_layer("Joints", project)
    if joint_layer2:
        cbt_count = sum(1 for f in joint_layer2.getFeatures() if _str(f["joint_type"]) == "CBT")
        if cbt_count:
            unit_cost = costs.get("cbt_each", 180.00)
            bom["PIA"].append({
                "description": "CBT (Connectorised Block Terminal)",
                "unit":        "each",
                "qty":         cbt_count,
                "unit_cost":   unit_cost,
                "total":       _cost(cbt_count, unit_cost),
                "notes":       "Pole-mounted terminal box",
            })

    cable_layer2 = get_layer("Cables", project)
    if cable_layer2:
        aerial_groups = {}
        for feat in cable_layer2.getFeatures():
            if _str(feat["cable_type"]).upper() != "AERIAL":
                continue
            fc  = int(feat["fibre_count"]) if feat["fibre_count"] and feat["fibre_count"] != NULL else 0
            key = fc
            length = _round2(feat["length_m"])
            if key not in aerial_groups:
                aerial_groups[key] = {"count": 0, "length_m": 0.0}
            aerial_groups[key]["count"]    += 1
            aerial_groups[key]["length_m"] += length
        for fc, vals in sorted(aerial_groups.items()):
            unit_cost = costs.get("aerial_cable_m", 0.85)
            qty = round(vals["length_m"], 1)
            bom["PIA"].append({
                "description": f"{fc}F Aerial Self-Support Cable",
                "unit":        "m",
                "qty":         qty,
                "unit_cost":   unit_cost,
                "total":       _cost(qty, unit_cost),
                "notes":       f"{vals['count']} span(s)",
            })

    ddct_layer2 = get_layer("Drop Ducts", project)
    if ddct_layer2:
        aerial_drop_len   = 0.0
        aerial_drop_count = 0
        for feat in ddct_layer2.getFeatures():
            if _str(feat["drop_type"]).upper() == "PIA_AERIAL_DROP":
                aerial_drop_len   += _round2(feat["length_m"])
                aerial_drop_count += 1
        if aerial_drop_count:
            unit_cost = costs.get("aerial_drop_m", 0.22)
            qty = round(aerial_drop_len, 1)
            bom["PIA"].append({
                "description": "PIA Aerial Drop Wire",
                "unit":        "m",
                "qty":         qty,
                "unit_cost":   unit_cost,
                "total":       _cost(qty, unit_cost),
                "notes":       f"{aerial_drop_count} drop(s)",
            })

    # ── Summary ───────────────────────────────────────────────────────────────
    def _total_cost(rows):
        return round(sum(r["total"] for r in rows), 2)

    all_rows = (bom["Fibre Cable"] + bom["Drop & Bundle"] +
                bom["Joints"] + bom["Duct"] + bom["PIA"])
    grand_total = round(sum(r["total"] for r in all_rows), 2)

    bom["Summary"] = [
        {"description": "Fibre Cable",    "unit": "",     "qty": "", "unit_cost": "", "total": _total_cost(bom["Fibre Cable"]),   "notes": f"{len(bom['Fibre Cable'])} line(s)"},
        {"description": "Drop & Bundle",  "unit": "",     "qty": "", "unit_cost": "", "total": _total_cost(bom["Drop & Bundle"]), "notes": f"{len(bom['Drop & Bundle'])} line(s)"},
        {"description": "Joints",         "unit": "",     "qty": "", "unit_cost": "", "total": _total_cost(bom["Joints"]),        "notes": f"{len(bom['Joints'])} line(s)"},
        {"description": "Duct",           "unit": "",     "qty": "", "unit_cost": "", "total": _total_cost(bom["Duct"]),          "notes": f"{len(bom['Duct'])} line(s)"},
        {"description": "PIA",            "unit": "",     "qty": "", "unit_cost": "", "total": _total_cost(bom["PIA"]),           "notes": f"{len(bom['PIA'])} line(s)"},
        {"description": "",               "unit": "",     "qty": "", "unit_cost": "", "total": "",                                "notes": ""},
        {"description": "TOTAL",          "unit": "",     "qty": "", "unit_cost": "", "total": grand_total,                       "notes": "ex. VAT"},
    ]

    return bom


# ── Dialog ────────────────────────────────────────────────────────────────────

class BomDialog(QDialog):

    def __init__(self, iface, parent=None, project=None):
        super().__init__(parent)
        self.iface = iface
        self._project = project
        self.bom   = {}
        self._setup_ui()
        self._run()

    def _setup_ui(self):
        self.setWindowTitle("Conductor — Bill of Materials")
        self.setMinimumSize(780, 520)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        header = QLabel("Bill of Materials")
        header.setStyleSheet(f"font-size:15px; font-weight:600; color:{NAVY};")
        root.addWidget(header)

        sub = QLabel("Aggregated quantities and costs from all fibre and civil layers. Unit costs editable — prices ex. VAT.")
        sub.setStyleSheet("font-size:11px; color:#555; margin-bottom:4px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabBar::tab {{ padding:6px 14px; font-size:11px; }} "
            f"QTabBar::tab:selected {{ background:{NAVY}; color:#fff; border-radius:3px 3px 0 0; }}"
        )
        root.addWidget(self._tabs)

        btn_row = QHBoxLayout()

        self._btn_refresh = QPushButton("↺  Refresh")
        self._btn_refresh.setStyleSheet(
            f"QPushButton {{ background:{TEAL}; color:#fff; font-weight:600; "
            f"padding:7px 16px; border-radius:4px; font-size:12px; }} "
            f"QPushButton:hover {{ background:#155f56; }}"
        )
        self._btn_refresh.clicked.connect(self._run)

        self._btn_export = QPushButton("↓  Export Excel")
        self._btn_export.setStyleSheet(
            "QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; border:1px solid #bbb; } "
            "QPushButton:hover { background:#e8e8e8; }"
        )
        self._btn_export.clicked.connect(self._export_csv)

        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(
            "QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; border:1px solid #bbb; } "
            "QPushButton:hover { background:#e8e8e8; }"
        )
        btn_close.clicked.connect(self.close)

        self._btn_costs = QPushButton("£  Edit Costs")
        self._btn_costs.setStyleSheet(
            "QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; border:1px solid #bbb; } "
            "QPushButton:hover { background:#e8e8e8; }"
        )
        self._btn_costs.clicked.connect(self._edit_costs)

        btn_row.addWidget(self._btn_refresh)
        btn_row.addWidget(self._btn_export)
        btn_row.addWidget(self._btn_costs)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _edit_costs(self):
        """Open a dialog to edit and persist unit costs."""
        from qgis.PyQt.QtWidgets import (QDialog, QFormLayout, QDialogButtonBox,
                                          QScrollArea, QWidget, QVBoxLayout)
        costs = load_costs()

        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Unit Costs (£ ex. VAT)")
        dlg.setMinimumWidth(380)
        root = QVBoxLayout(dlg)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        fw = QWidget(); fl = QFormLayout(fw); fl.setSpacing(6)

        LABELS = {
            "shotgun_duct_m":    "Shotgun duct (per m)",
            "duct_16mm_m":       "16mm duct (per m)",
            "duct_7mm_m":        "7mm duct (per m)",
            "cable_spine_m":     "Spine cable (per m)",
            "cable_7mm_m":       "7mm fibre cable (per m)",
            "chamber_each":      "Chamber (each)",
            "joint_each":        "Joint closure (each)",
            "splitter_1x2_each": "Splitter 1:2 (each)",
            "splitter_1x4_each": "Splitter 1:4 (each)",
            "splitter_1x8_each": "Splitter 1:8 (each)",
            "splitter_1x16_each":"Splitter 1:16 (each)",
            "splitter_1x32_each":"Splitter 1:32 (each)",
            "bundle_m":          "Bundle (per m)",
            "drop_duct_m":       "Drop duct (per m)",
            "ont_each":          "ONT (each)",
            "road_crossing_each":"Road crossing (each)",
            "pole_each":         "Pole (each)",
            "cbt_each":          "CBT (each)",
            "aerial_cable_m":    "Aerial cable (per m)",
            "aerial_drop_m":     "Aerial drop wire (per m)",
        }

        spinboxes = {}
        for key, default in DEFAULT_COSTS.items():
            label = LABELS.get(key, key)
            sb = QDoubleSpinBox()
            sb.setDecimals(2); sb.setMinimum(0); sb.setMaximum(99999)
            sb.setValue(costs.get(key, default))
            sb.setPrefix("£ ")
            fl.addRow(QLabel(label), sb)
            spinboxes[key] = sb

        scroll.setWidget(fw)
        root.addWidget(scroll)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(lambda: [sb.setValue(DEFAULT_COSTS[k]) for k, sb in spinboxes.items()])
        root.addWidget(reset_btn)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        root.addWidget(btns)

        if dlg.exec_() == QDialog.Accepted:
            new_costs = {k: sb.value() for k, sb in spinboxes.items()}
            save_costs(new_costs)
            self._run()

    def _run(self):
        try:
            self.bom = build_bom(costs=load_costs(), project=self._project)
        except Exception:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.critical(self, "BoM Error", traceback.format_exc())
            return

        self._tabs.clear()

        tab_colours = {
            "Summary":       NAVY,
            "Fibre Cable":   "#6A0080",
            "Drop & Bundle": ORANGE,
            "Joints":        TEAL,
            "Duct":          "#444444",
            "PIA":           "#8B4513",
        }

        for tab_name, rows in self.bom.items():
            table = self._make_table(rows, tab_colours.get(tab_name, NAVY),
                                     is_summary=(tab_name == "Summary"))
            self._tabs.addTab(table, tab_name)

    def _make_table(self, rows, accent, is_summary=False):
        cols = ["Description", "Unit", "Qty", "Unit Cost (£)", "Total (£)", "Notes"]
        table = QTableWidget(len(rows), len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setStyleSheet(
            "QTableWidget { font-size:12px; gridline-color:#e8e8e8; }"
            f"QHeaderView::section {{ background:{accent}; color:#fff; font-weight:600; "
            "padding:5px; border:none; }}"
        )

        for r, row in enumerate(rows):
            is_total_row = str(row.get("description", "")) == "TOTAL"
            is_blank_row = str(row.get("description", "")) == ""

            desc_val  = str(row.get("description", ""))
            unit_val  = str(row.get("unit", ""))
            qty_val   = str(row.get("qty", ""))
            cost_val  = f"£{row['unit_cost']:.2f}" if row.get("unit_cost") != "" and row.get("unit_cost") is not None else ""
            total_val = f"£{row['total']:.2f}"     if row.get("total") != ""     and row.get("total")     is not None else ""
            note_val  = str(row.get("notes", ""))

            items = [
                QTableWidgetItem(desc_val),
                QTableWidgetItem(unit_val),
                QTableWidgetItem(qty_val),
                QTableWidgetItem(cost_val),
                QTableWidgetItem(total_val),
                QTableWidgetItem(note_val),
            ]

            for col, item in enumerate(items):
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if is_total_row:
                    item.setFont(QFont("Arial", 11, QFont.Bold))
                    item.setBackground(QBrush(QColor("#e8f4fd")))
                elif is_blank_row:
                    item.setBackground(QBrush(QColor("#f0f0f0")))
                else:
                    item.setFont(QFont("Arial", 10))
                if col == 5:
                    item.setForeground(QBrush(QColor("#777")))
                table.setItem(r, col, item)

        return table

    def _export_csv(self):
        from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox
        import xlwt

        path, _ = QFileDialog.getSaveFileName(
            self, "Export BoM", "BoM.xls", "Excel files (*.xls)"
        )
        if not path:
            return
        if not path.endswith(".xls"):
            path += ".xls"

        wb = xlwt.Workbook(encoding="utf-8")

        # Styles
        def _style(bold=False, bg_colour=None, align_right=False, font_size=10):
            style = xlwt.XFStyle()
            font = xlwt.Font()
            font.name      = "Calibri"
            font.height    = font_size * 20
            font.bold      = bold
            font.colour_index = 0x01 if (bg_colour in ("navy","teal","purple","orange","grey")) else 0x00
            style.font = font
            if align_right:
                al = xlwt.Alignment()
                al.horz = xlwt.Alignment.HORZ_RIGHT
                style.alignment = al
            if bg_colour:
                pat = xlwt.Pattern()
                pat.pattern = xlwt.Pattern.SOLID_PATTERN
                colour_map = {
                    "navy":   0x19,
                    "teal":   0x0E,
                    "purple": 0x14,
                    "orange": 0x34,
                    "grey":   0x17,
                    "light":  0x2C,
                    "stripe": 0x2B,
                }
                pat.pattern_fore_colour = colour_map.get(bg_colour, 0x01)
                style.pattern = pat
            return style

        tab_styles = {
            "Summary":       "navy",
            "Fibre Cable":   "purple",
            "Drop & Bundle": "orange",
            "Joints":        "teal",
            "Duct":          "grey",
            "PIA":           "orange",
        }

        headers = ["Description", "Unit", "Qty", "Unit Cost (GBP)", "Total (GBP)", "Notes"]
        col_widths = [8000, 1800, 2000, 3200, 2800, 5000]

        for tab_name, rows in self.bom.items():
            ws   = wb.add_sheet(tab_name)
            hcol = tab_styles.get(tab_name, "navy")

            hdr_style  = _style(bold=True,  bg_colour=hcol,   font_size=10)
            norm_style = _style(bold=False)
            bold_style = _style(bold=True,  font_size=11)
            num_style  = _style(bold=False, align_right=True)
            num_bold   = _style(bold=True,  align_right=True,  font_size=11)
            stripe_style = _style(bold=False, bg_colour="stripe")
            stripe_num   = _style(bold=False, bg_colour="stripe", align_right=True)

            # Set column widths
            for col, w in enumerate(col_widths):
                ws.col(col).width = w

            # Header row
            for col, hdr in enumerate(headers):
                ws.write(0, col, hdr, hdr_style)

            # Data rows
            for r, row in enumerate(rows, 1):
                desc  = row.get("description", "")
                unit  = row.get("unit", "")
                qty   = row.get("qty", "")
                ucost = row.get("unit_cost", "")
                total = row.get("total", "")
                notes = row.get("notes", "")

                is_total = str(desc) == "TOTAL"
                is_blank = str(desc) == ""
                is_stripe = (r % 2 == 0)

                if is_total:
                    ws.write(r, 0, desc,  bold_style)
                    ws.write(r, 1, unit,  bold_style)
                    ws.write(r, 2, "",    bold_style)
                    ws.write(r, 3, "",    num_bold)
                    ws.write(r, 4, total if total != "" else "", num_bold)
                    ws.write(r, 5, notes, bold_style)
                else:
                    ls  = stripe_style if is_stripe else norm_style
                    ns  = stripe_num   if is_stripe else num_style
                    ws.write(r, 0, desc,  ls)
                    ws.write(r, 1, unit,  ls)
                    ws.write(r, 2, qty   if qty   != "" else "", ns)
                    ws.write(r, 3, ucost if ucost != "" else "", ns)
                    ws.write(r, 4, total if total != "" else "", ns)
                    ws.write(r, 5, notes, ls)

        from ..conductor_utils import log
        try:
            wb.save(path)
        except PermissionError:
            # File is locked — almost always open in Excel, or held by OneDrive.
            import os, datetime
            log(f"BoM export: permission denied writing {path} (file locked?)", "warning")
            base, ext = os.path.splitext(path)
            alt = f"{base}_{datetime.datetime.now():%Y%m%d_%H%M%S}{ext}"
            try:
                wb.save(alt)
            except Exception as e:
                log(f"BoM export: fallback save also failed: {e}", "critical")
                QMessageBox.critical(
                    self, "Export failed",
                    "Could not save the BoM.\n\n"
                    f"'{os.path.basename(path)}' appears to be open in another "
                    "program (e.g. Excel) or locked by OneDrive sync.\n\n"
                    "Close the file, or choose a different location, and try again.")
                return
            QMessageBox.information(
                self, "Export complete (renamed)",
                f"'{os.path.basename(path)}' was locked (open in Excel?), so the "
                f"BoM was saved as:\n{alt}")
            return
        except Exception as e:
            log(f"BoM export failed: {e}", "critical")
            QMessageBox.critical(self, "Export failed",
                                 f"Could not save the BoM:\n{e}")
            return
        QMessageBox.information(self, "Export complete",
                                f"BoM exported to:\n{path}")


def open_bom_dialog(iface, parent=None, project=None):
    dlg = BomDialog(iface, parent, project=project)
    dlg.show()
    return dlg
