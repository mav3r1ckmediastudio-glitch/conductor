# -*- coding: utf-8 -*-
"""
Conductor \u2014 Cabinet Cost Calculator
For each cabinet (Exchange/POP feature), costs its own active equipment
(DUX/Calix shelves, GPON cards/optics, batteries, patch panels, aggregation
router \u2014 read straight from the cabinet's attributes) and adds the civils/
cable Bill of Materials for that cabinet's area, giving a total build cost
and a \u00a3/premises figure per cabinet plus a project-wide grand total.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from qgis.core import NULL

from ..conductor_utils import get_layer, NAVY, TEAL
from .bom import build_bom, load_costs, edit_costs_dialog


def _int(v):
    try:
        return int(v) if v and v != NULL else 0
    except (TypeError, ValueError):
        return 0


def equipment_cost(feat, costs):
    """Cost of a cabinet's own equipment + build-out, from its attribute
    fields — mirrors the Gigaloch Cabinet Calculator spreadsheet.

    Active equipment (scales with the cabinet's electronics, applies to any
    POP type — cabinet, exchange, datacentre, rooftop):
      - DU-X shelves, and one Inverter per DU-X shelf
      - one Management/OOB Switch per site
      - Calix E7-2 shelves, GPON cards, GPON optics
      - Battery sets, patch panels, aggregation router (if fitted)
      - Sundries (wiring/PDUs) per site

    Cabinet build-out (only for pop_type == CABINET — a new street
    cabinet, as opposed to an existing exchange/datacentre/rooftop site):
      - Cabinet enclosure (inc. fans), groundworks, electrical hookup,
        backhaul install
    """
    dux = _int(feat["dux_shelves"])

    total = 0.0
    total += dux                   * costs.get("dux_shelf_each",   900.00)
    total += dux                   * costs.get("inverter_each",    140.00)
    total += _int(feat["calix_shelves"]) * costs.get("calix_shelf_each", 400.00)
    total += _int(feat["gpon_cards"])    * costs.get("gpon_card_each",  4200.00)
    total += _int(feat["gpon_optics"])   * costs.get("gpon_optic_each",  110.00)
    total += _int(feat["battery_sets"])  * costs.get("battery_set_each", 190.00)
    total += _int(feat["patch_panels"])  * costs.get("patch_panel_each",  60.00)
    if feat["has_aggreg_router"]:
        total += costs.get("aggreg_router_each", 8000.00)

    total += costs.get("mgmt_switch_each", 350.00)
    total += costs.get("sundries_each",    150.00)

    pop_type = feat["pop_type"] if feat["pop_type"] and feat["pop_type"] != NULL else ""
    if str(pop_type).upper() == "CABINET":
        total += costs.get("cabinet_enclosure_each",  1500.00)
        total += costs.get("groundworks_each",        1000.00)
        total += costs.get("electrical_hookup_each",   500.00)
        total += costs.get("backhaul_install_each",    950.00)

    return round(total, 2)


class CabinetCostCalculatorDialog(QDialog):

    def __init__(self, iface, parent=None, project=None):
        super().__init__(parent)
        self.iface = iface
        self._project = project
        self.setWindowTitle("Conductor \u2014 Cabinet Cost Calculator")
        self.setMinimumSize(760, 380)
        self._build_ui()
        self._run()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        header = QLabel("Cabinet Cost Calculator")
        header.setStyleSheet(f"font-size:15px; font-weight:600; color:{WHITE};")
        root.addWidget(header)

        sub = QLabel(
            "Per cabinet: active equipment cost (from the cabinet's own DUX/"
            "Calix shelves, GPON cards/optics, batteries, patch panels, "
            "aggregation router) plus the civils/cable Bill of Materials for "
            "that cabinet's area. Edit unit costs below to update all totals."
        )
        sub.setStyleSheet("font-size:11px; color:#8B9AAB; margin-bottom:4px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["Cabinet", "Area", "Premises", "Equipment", "Civils/Cable", "Total", "\u00a3 / Premises"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self._table)

        self._lbl_total = QLabel("")
        self._lbl_total.setStyleSheet(f"font-size:13px; font-weight:600; color:{WHITE}; padding-top:4px;")
        self._lbl_total.setAlignment(Qt.AlignRight)
        root.addWidget(self._lbl_total)

        btn_row = QHBoxLayout()

        self._btn_refresh = QPushButton("\u21ba  Refresh")
        self._btn_refresh.setStyleSheet(
            f"QPushButton {{ background:{TEAL}; color:#fff; font-weight:600; "
            f"padding:7px 16px; border-radius:4px; font-size:12px; }} "
            f"QPushButton:hover {{ background:#155f56; }}"
        )
        self._btn_refresh.clicked.connect(self._run)

        self._btn_costs = QPushButton("\u00a3  Edit Costs")
        self._btn_costs.setStyleSheet(
            "QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; border:1px solid #bbb; } "
            "QPushButton:hover { background:#e8e8e8; }"
        )
        self._btn_costs.clicked.connect(lambda: edit_costs_dialog(self, on_saved=self._run))

        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(
            "QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; border:1px solid #bbb; } "
            "QPushButton:hover { background:#e8e8e8; }"
        )
        btn_close.clicked.connect(self.close)

        btn_row.addWidget(self._btn_refresh)
        btn_row.addWidget(self._btn_costs)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _run(self):
        self._table.setRowCount(0)

        pop_layer = get_layer("exchange_pops", project=self._project)
        if not pop_layer:
            self._lbl_total.setText("No cabinet (Exchange/POP) layer found in this project.")
            return

        premises_layer = get_layer("premises", project=self._project)
        premises_counts = {}
        if premises_layer:
            for feat in premises_layer.getFeatures():
                a = feat["area_id"]
                if a and a != NULL:
                    a = str(a)
                    premises_counts[a] = premises_counts.get(a, 0) + 1

        costs = load_costs()

        rows = []
        grand_total = 0.0
        for feat in pop_layer.getFeatures():
            area_id = str(feat["area_id"]) if feat["area_id"] and feat["area_id"] != NULL else None
            if not area_id:
                continue
            pop_id = str(feat["pop_id"]) if feat["pop_id"] and feat["pop_id"] != NULL else "\u2014"

            equip_total = equipment_cost(feat, costs)

            bom = build_bom(costs=costs, project=self._project, area_id=area_id)
            civils_total = next((r["total"] for r in bom["Summary"] if r["description"] == "TOTAL"), 0.0)

            total = round(equip_total + civils_total, 2)

            prem_count = premises_counts.get(area_id, 0)
            per_prem = round(total / prem_count, 2) if prem_count else None

            rows.append((pop_id, area_id, prem_count, equip_total, civils_total, total, per_prem))
            grand_total += total

        self._table.setRowCount(len(rows))
        for r, (pop_id, area_id, prem_count, equip_total, civils_total, total, per_prem) in enumerate(rows):
            vals = [
                pop_id,
                area_id,
                str(prem_count),
                f"\u00a3{equip_total:,.2f}",
                f"\u00a3{civils_total:,.2f}",
                f"\u00a3{total:,.2f}",
                f"\u00a3{per_prem:,.2f}" if per_prem is not None else "\u2014",
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c >= 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(r, c, item)

        if not rows:
            self._lbl_total.setText("No cabinets (Exchange/POP features with an area_id) found.")
        elif len(rows) == 1:
            self._lbl_total.setText(f"Project total: \u00a3{grand_total:,.2f}")
        else:
            self._lbl_total.setText(f"Project total ({len(rows)} cabinets): \u00a3{grand_total:,.2f}")


def open_cabinet_cost_dialog(iface, parent=None, project=None):
    dlg = CabinetCostCalculatorDialog(iface, parent, project=project)
    dlg.show()
    return dlg
