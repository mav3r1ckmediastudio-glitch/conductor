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
# Sourced from Gigaloch's current material costs sheet. Maintained here as the
# single source of unit pricing; edit DEFAULT_COSTS when supplier prices change.
DEFAULT_COSTS = {
    # ── Fibre cable — per metre by core count ─────────────────────────────
    "cable_12f_m":          0.47,
    "cable_24f_m":          0.54,
    "cable_48f_m":          0.62,
    "cable_72f_m":          0.65,
    "cable_96f_m":          0.99,
    "cable_aerial_48f_m":   0.59,   # 48F aerial HDPE G657A1
    "cable_aerial_24f_m":   0.54,   # 24F aerial drop cable
    "cable_7mm_m":          0.11,   # 7mm fibre bundle

    # ── Duct — per metre ──────────────────────────────────────────────────
    "shotgun_duct_m":       1.33,
    "flexi_duct_m":         1.17,
    "duct_16mm_m":          0.44,
    "duct_16mm_connector":  5.66,   # per join
    "duct_16mm_end_stop":   2.21,   # per end
    "duct_7mm_m":           0.14,
    "duct_7mm_end_stop":    0.67,   # per drop
    "drop_duct_m":          0.14,

    # ── Chambers (own — includes lid) ────────────────────────────────────
    "chamber_small_each":  175.10,
    "chamber_large_each":  301.49,

    # ── Joint closures ────────────────────────────────────────────────────
    "joint_cmj_each":       66.81,  # Prysmian CMJ
    "joint_fdnir_each":    122.38,  # FDNIR-AXBCWX
    "joint_fsttb_a_each":   49.55,  # FSTTB-AXBTA11
    "joint_fsttb_b_each":   46.57,  # FSTTB-AXXTA31
    "joint_gland_each":     10.28,  # Prysmian circular port entry gland (per joint)

    # ── Splitter modules (fitted into joint) ─────────────────────────────
    "splitter_1x2_each":   20.00,
    "splitter_1x4_each":    8.06,
    "splitter_1x8_each":    8.62,
    "splitter_1x16_each":  80.00,
    "splitter_1x32_each": 120.00,

    # ── PIA aerial ────────────────────────────────────────────────────────
    "pole_each":           250.00,
    "cbt_8port_each":      101.80,  # Evolv Multiport Pushlok 8-port 300m (standard)
    "cbt_4port_each":       92.16,  # Corning OptiSheath 4-port
    "cbt_12port_250m_each": 219.00, # Corning OptiSheath 12-port 250m
    "cbt_12port_350m_each": 316.03, # Corning OptiSheath 12-port 350m
    "cbt_pole_bracket":     29.19,  # 2-way ROC CBT pole bracket hinge (per CBT)
    "cbt_anti_creeper":      6.40,  # Mills external fibre locking mechanism (per CBT)
    "aerial_dead_end":       2.17,  # PLP dead end per aerial span end

    # ── Home installation ─────────────────────────────────────────────────
    "ont_each":             33.36,
    "ont_base_plate_each":   4.62,
    "toby_box_each":         4.15,
    "home_entry_kit_each":  27.79,
    "router_each":          45.53,

    # ── Network equipment (cabinet active) ───────────────────────────────
    "cabinet_each":       4039.72,
    "aggreg_router_each": 8000.00,
    "dux_shelf_each":      900.00,
    "eaton_apr48_each":    202.00,
    "mgmt_switch_each":    200.00,
    "calix_shelf_each":    556.63,
    "gpon_card_each":     4200.00,
    "gpon_optic_each":     110.00,
    "battery_each":        145.00,  # Yuasa NP65-12l
    "battery_shelf_each":   40.00,
    "patch_panel_each":     60.00,
    "pdu_13a_each":         45.00,
    "pdu_iec_each":         35.00,
    "rack_shelf_each":      20.00,
    "lc_upc_1gb_each":       9.00,
    "lc_upc_duplex_each":    5.00,
    "electrical_hookup_each": 24.96,
    "armoured_cable_m":      3.50,

    # ── Crossings ─────────────────────────────────────────────────────────
    "road_crossing_each": 1500.00,
    "stream_crossing_each": 800.00,
    "scaffold_bar_each":    34.62,

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

def _area_features(layer, area_id=None):
    """Yield features from layer, optionally restricted to a single area_id.
    If area_id is None, yields every feature (whole-project behaviour)."""
    if area_id is None:
        for feat in layer.getFeatures():
            yield feat
        return
    field_names = [f.name() for f in layer.fields()]
    if "area_id" not in field_names:
        for feat in layer.getFeatures():
            yield feat
        return
    for feat in layer.getFeatures():
        fa = feat["area_id"]
        if fa and fa != NULL and str(fa) == str(area_id):
            yield feat


def build_bom(costs=None, project=None, area_id=None):
    """Build a BoM dict. If area_id is given, restrict to features whose
    area_id matches; otherwise covers the whole project."""
    if costs is None:
        costs = load_costs()

    bom = {
        "Summary":        [],
        "Fibre Cable":    [],
        "Drop & Bundle":  [],
        "Joints":         [],
        "Duct":           [],
        "PIA":            [],
        "Home Install":   [],
        "Network Equip":  [],
    }

    # ── Cable cost lookup by fibre count ─────────────────────────────────
    CABLE_COST_MAP = {
        12:  costs.get("cable_12f_m",        0.47),
        24:  costs.get("cable_24f_m",        0.54),
        48:  costs.get("cable_48f_m",        0.62),
        72:  costs.get("cable_72f_m",        0.65),
        96:  costs.get("cable_96f_m",        0.99),
    }

    # ── Joint cost lookup by closure_type ────────────────────────────────
    JOINT_COST_MAP = {
        "Prysmian CMJ":    costs.get("joint_cmj_each",    66.81),
        "FDNIR-AXBCWX":   costs.get("joint_fdnir_each",  122.38),
        "FSTTB-AXBTA11":  costs.get("joint_fsttb_a_each", 49.55),
        "FSTTB-AXXTA31":  costs.get("joint_fsttb_b_each", 46.57),
    }

    # ── CBT cost lookup by model ──────────────────────────────────────────
    CBT_COST_MAP = {
        "Evolv Multiport Pushlok 8-port 300m (Corning)": costs.get("cbt_8port_each",       101.80),
        "Corning OptiSheath 4-port":                     costs.get("cbt_4port_each",         92.16),
        "Corning OptiSheath 12-port 250m drop":          costs.get("cbt_12port_250m_each",  219.00),
        "Corning OptiSheath 12-port 350m drop":          costs.get("cbt_12port_350m_each",  316.03),
    }

    # ── Cables ────────────────────────────────────────────────────────────
    cable_layer = get_layer("Cables", project)
    if cable_layer:
        groups = {}
        for feat in _area_features(cable_layer, area_id):
            ct     = _str(feat["cable_type"]) or "FEEDER"
            fc     = int(feat["fibre_count"]) if feat["fibre_count"] and feat["fibre_count"] != NULL else 48
            ft     = _str(feat["fibre_type"]) or "G.652D"
            length = _round2(feat["length_m"])
            is_aerial = ct.upper() in ("AERIAL",)
            is_tail   = ct.upper() == "CBT_TAIL"
            key = (fc, ft, ct, is_aerial, is_tail)
            if key not in groups:
                groups[key] = {"count": 0, "length_m": 0.0}
            groups[key]["count"]    += 1
            groups[key]["length_m"] += length

        for (fc, ft, ct, is_aerial, is_tail), vals in sorted(groups.items()):
            qty = round(vals["length_m"], 1)
            if is_aerial:
                unit_cost = costs.get("cable_aerial_48f_m", 0.59) if fc >= 48 else costs.get("cable_aerial_24f_m", 0.54)
                desc = f"{fc}F Aerial Cable G657A1 ({ct})"
                tab  = "PIA"
            elif is_tail:
                unit_cost = CABLE_COST_MAP.get(fc, costs.get("cable_48f_m", 0.62))
                desc = f"{fc}F CBT Tail Cable"
                tab  = "PIA"
            else:
                unit_cost = CABLE_COST_MAP.get(fc, costs.get("cable_48f_m", 0.62))
                desc = f"{fc}F {ft} Cable ({ct})"
                tab  = "Fibre Cable"
            bom[tab].append({
                "description": desc,
                "unit": "m", "qty": qty,
                "unit_cost": unit_cost, "total": _cost(qty, unit_cost),
                "notes": f"{vals['count']} cable(s)",
            })

    # ── Bundles ───────────────────────────────────────────────────────────
    bundle_layer = get_layer("Bundles", project)
    if bundle_layer:
        bgroups = {}
        for feat in _area_features(bundle_layer, area_id):
            fc     = int(feat["fibre_count"]) if feat["fibre_count"] and feat["fibre_count"] != NULL else 1
            length = _round2(feat["length_m"])
            bgroups[fc] = bgroups.get(fc, {"count": 0, "length_m": 0.0})
            bgroups[fc]["count"]    += 1
            bgroups[fc]["length_m"] += length
        for fc, vals in sorted(bgroups.items()):
            unit_cost = costs.get("cable_7mm_m", 0.11)
            qty = round(vals["length_m"], 1)
            bom["Drop & Bundle"].append({
                "description": f"{fc}F Fibre Bundle (drop)",
                "unit": "m", "qty": qty,
                "unit_cost": unit_cost, "total": _cost(qty, unit_cost),
                "notes": f"{vals['count']} bundle(s)",
            })

    # ── Drop Ducts ────────────────────────────────────────────────────────
    ddct_layer = get_layer("Drop Ducts", project)
    ddct_count  = 0
    aerial_drop_len   = 0.0
    aerial_drop_count = 0
    if ddct_layer:
        total_len = 0.0
        for feat in _area_features(ddct_layer, area_id):
            dt = _str(feat["drop_type"]).upper()
            if dt == "PIA_AERIAL_DROP":
                aerial_drop_len   += _round2(feat["length_m"])
                aerial_drop_count += 1
            else:
                total_len  += _round2(feat["length_m"])
                ddct_count += 1
        if ddct_count:
            unit_cost = costs.get("drop_duct_m", 0.14)
            qty = round(total_len, 1)
            bom["Drop & Bundle"].append({
                "description": "7mm Speedpipe Drop Duct",
                "unit": "m", "qty": qty,
                "unit_cost": unit_cost, "total": _cost(qty, unit_cost),
                "notes": f"{ddct_count} drop(s)",
            })
            # 7mm end stop — 1 per drop
            uc_es = costs.get("duct_7mm_end_stop", 0.67)
            bom["Drop & Bundle"].append({
                "description": "7mm Duct End Stop",
                "unit": "each", "qty": ddct_count,
                "unit_cost": uc_es, "total": _cost(ddct_count, uc_es),
                "notes": "1 per drop",
            })

    # ── Joints ────────────────────────────────────────────────────────────
    joint_layer = get_layer("Joints", project)
    joint_count = 0
    cbt_groups  = {}
    if joint_layer:
        joint_groups    = {}
        splitter_groups = {}
        for feat in _area_features(joint_layer, area_id):
            jt = _str(feat["joint_type"]) or "SPLICE"
            ct = _str(feat["closure_type"]) or "Prysmian CMJ"
            if jt == "CBT":
                model = _str(feat["cbt_model"]) or "Evolv Multiport Pushlok 8-port 300m (Corning)"
                cbt_groups[model] = cbt_groups.get(model, 0) + 1
                continue
            key = (jt, ct)
            joint_groups[key] = joint_groups.get(key, 0) + 1
            joint_count += 1
            if feat["has_splitter"] and feat["has_splitter"] != NULL and feat["has_splitter"]:
                sr = _str(feat["split_ratio"]) or "Unknown"
                splitter_groups[sr] = splitter_groups.get(sr, 0) + 1

        for (jt, ct), count in sorted(joint_groups.items()):
            unit_cost = JOINT_COST_MAP.get(ct, costs.get("joint_cmj_each", 66.81))
            bom["Joints"].append({
                "description": f"Joint Closure — {ct}",
                "unit": "each", "qty": count,
                "unit_cost": unit_cost, "total": _cost(count, unit_cost),
                "notes": jt.replace("_", " ").title(),
            })

        # Port entry gland — 1 per joint
        if joint_count:
            uc_g = costs.get("joint_gland_each", 10.28)
            bom["Joints"].append({
                "description": "Prysmian Port Entry Gland",
                "unit": "each", "qty": joint_count,
                "unit_cost": uc_g, "total": _cost(joint_count, uc_g),
                "notes": "1 per joint closure",
            })

        for sr, count in sorted(splitter_groups.items()):
            ratio_map = {
                "1:2": "splitter_1x2_each", "1:4": "splitter_1x4_each",
                "1:8": "splitter_1x8_each", "1:16": "splitter_1x16_each",
                "1:32": "splitter_1x32_each",
            }
            unit_cost = costs.get(ratio_map.get(sr, "splitter_1x8_each"), 8.62)
            bom["Joints"].append({
                "description": f"Splitter Module {sr}",
                "unit": "each", "qty": count,
                "unit_cost": unit_cost, "total": _cost(count, unit_cost),
                "notes": "Passive optical splitter, fitted into joint",
            })

    # ── Ducts ─────────────────────────────────────────────────────────────
    duct_layer = get_layer("Ducts", project)
    if duct_layer:
        duct_fields           = [f.name() for f in duct_layer.fields()]
        duct_groups           = {}
        road_crossing_count   = 0
        stream_crossing_count = 0
        scaffold_bar_count    = 0
        for feat in _area_features(duct_layer, area_id):
            dt     = _str(feat["duct_type"]) or "STANDARD"
            st     = _str(feat["surface_type"]) or "Unknown"
            length = _round2(feat["length_m"])
            key    = (dt, st)
            if key not in duct_groups:
                duct_groups[key] = {"count": 0, "length_m": 0.0}
            duct_groups[key]["count"]    += 1
            duct_groups[key]["length_m"] += length
            if st.upper() == "ROAD":
                road_crossing_count += 1
            elif st.upper() == "WATERCOURSE":
                stream_crossing_count += 1
            if "sleeve_type" in duct_fields and _str(feat["sleeve_type"]).upper() == "SCAFFOLD_BAR":
                scaffold_bar_count += 1

        for (dt, st), vals in sorted(duct_groups.items()):
            if "SHOTGUN" in dt.upper():
                unit_cost = costs.get("shotgun_duct_m", 1.33)
            elif "FLEXI" in dt.upper():
                unit_cost = costs.get("flexi_duct_m", 1.17)
            elif "7MM" in dt.upper():
                unit_cost = costs.get("duct_7mm_m", 0.14)
            else:
                unit_cost = costs.get("duct_16mm_m", 0.44)
            qty = round(vals["length_m"], 1)
            bom["Duct"].append({
                "description": f"{dt.replace('_',' ').title()} Duct ({st.replace('_',' ').title()})",
                "unit": "m", "qty": qty,
                "unit_cost": unit_cost, "total": _cost(qty, unit_cost),
                "notes": f"{vals['count']} run(s)",
            })

        if road_crossing_count:
            uc = costs.get("road_crossing_each", 1500.00)
            bom["Duct"].append({
                "description": "Road Crossing (works/permit allowance)",
                "unit": "each", "qty": road_crossing_count,
                "unit_cost": uc, "total": _cost(road_crossing_count, uc), "notes": "",
            })
        if stream_crossing_count:
            uc = costs.get("stream_crossing_each", 800.00)
            bom["Duct"].append({
                "description": "Stream Crossing (consent allowance)",
                "unit": "each", "qty": stream_crossing_count,
                "unit_cost": uc, "total": _cost(stream_crossing_count, uc), "notes": "",
            })
        if scaffold_bar_count:
            uc = costs.get("scaffold_bar_each", 34.62)
            bom["Duct"].append({
                "description": "Scaff Bar (duct sleeve)",
                "unit": "each", "qty": scaffold_bar_count,
                "unit_cost": uc, "total": _cost(scaffold_bar_count, uc), "notes": "",
            })

    # ── Chambers (own — self-build, costed) ──────────────────────────────
    chamber_layer = get_layer("Chambers", project)
    if chamber_layer:
        fields      = [f.name() for f in chamber_layer.fields()]
        small_count = 0
        large_count = 0
        pole_count  = 0
        for feat in _area_features(chamber_layer, area_id):
            ct = _str(feat["chamber_type"])
            if ct == "PIA_POLE":
                pole_count += 1
                continue
            if ct == "PIA_UG_CHAMBER":
                continue  # PIA — not costed
            size = _str(feat["chamber_size"]) if "chamber_size" in fields else "SMALL"
            if size == "LARGE":
                large_count += 1
            else:
                small_count += 1

        if small_count:
            uc = costs.get("chamber_small_each", 175.10)
            bom["Duct"].append({
                "description": "Chamber — Small (inc. lid)",
                "unit": "each", "qty": small_count,
                "unit_cost": uc, "total": _cost(small_count, uc), "notes": "",
            })
        if large_count:
            uc = costs.get("chamber_large_each", 301.49)
            bom["Duct"].append({
                "description": "Chamber — Large (inc. lid)",
                "unit": "each", "qty": large_count,
                "unit_cost": uc, "total": _cost(large_count, uc), "notes": "",
            })
        if pole_count:
            uc = costs.get("pole_each", 250.00)
            bom["PIA"].append({
                "description": "PIA Pole Attachment",
                "unit": "each", "qty": pole_count,
                "unit_cost": uc, "total": _cost(pole_count, uc),
                "notes": "Openreach PIA pole",
            })

    # ── CBTs ──────────────────────────────────────────────────────────────
    total_cbt_count = sum(cbt_groups.values())
    for model, count in sorted(cbt_groups.items()):
        unit_cost = CBT_COST_MAP.get(model, costs.get("cbt_8port_each", 101.80))
        bom["PIA"].append({
            "description": f"CBT — {model}",
            "unit": "each", "qty": count,
            "unit_cost": unit_cost, "total": _cost(count, unit_cost),
            "notes": "Pole-mounted terminal",
        })
    if total_cbt_count:
        uc_b = costs.get("cbt_pole_bracket", 29.19)
        bom["PIA"].append({
            "description": "CBT Pole Bracket Hinge (2-way ROC)",
            "unit": "each", "qty": total_cbt_count,
            "unit_cost": uc_b, "total": _cost(total_cbt_count, uc_b),
            "notes": "1 per CBT",
        })
        uc_ac = costs.get("cbt_anti_creeper", 6.40)
        bom["PIA"].append({
            "description": "Anti-Creeper (Mills external locking)",
            "unit": "each", "qty": total_cbt_count,
            "unit_cost": uc_ac, "total": _cost(total_cbt_count, uc_ac),
            "notes": "1 per CBT",
        })

    # ── Aerial spans — dead ends ──────────────────────────────────────────
    cable_layer2 = get_layer("Cables", project)
    if cable_layer2:
        aerial_span_count = sum(
            1 for f in _area_features(cable_layer2, area_id)
            if _str(f["cable_type"]).upper() == "AERIAL"
        )
        if aerial_span_count:
            dead_end_qty = aerial_span_count * 2  # one at each end
            uc_de = costs.get("aerial_dead_end", 2.17)
            bom["PIA"].append({
                "description": "PLP Dead End (aerial cable)",
                "unit": "each", "qty": dead_end_qty,
                "unit_cost": uc_de, "total": _cost(dead_end_qty, uc_de),
                "notes": f"2 per span × {aerial_span_count} span(s)",
            })

    if aerial_drop_count:
        uc = costs.get("cable_aerial_24f_m", 0.54)
        qty = round(aerial_drop_len, 1)
        bom["PIA"].append({
            "description": "24F Aerial Drop Cable",
            "unit": "m", "qty": qty,
            "unit_cost": uc, "total": _cost(qty, uc),
            "notes": f"{aerial_drop_count} drop(s)",
        })

    # ── Home installation — per routed customer ───────────────────────────
    customer_layer = get_layer("Customers", project)
    routed_count   = 0
    if customer_layer:
        fields = [f.name() for f in customer_layer.fields()]
        for feat in _area_features(customer_layer, area_id):
            status = _str(feat["status"]).upper() if "status" in fields else ""
            if status in ("ROUTED", "LIVE", "INSTALLED"):
                routed_count += 1

    if not routed_count:
        # Fall back to routed premises count
        premises_layer = get_layer("Premises", project)
        if premises_layer:
            fields = [f.name() for f in premises_layer.fields()]
            for feat in _area_features(premises_layer, area_id):
                status = _str(feat["status"]).upper() if "status" in fields else ""
                if status == "ROUTED":
                    routed_count += 1

    if routed_count:
        for desc, key, default in [
            ("ONT",                   "ont_each",             33.36),
            ("ONT Base Plate",        "ont_base_plate_each",   4.62),
            ("Toby Box",              "toby_box_each",         4.15),
            ("Home Entry Kit",        "home_entry_kit_each",  27.79),
        ]:
            uc = costs.get(key, default)
            bom["Home Install"].append({
                "description": desc,
                "unit": "each", "qty": routed_count,
                "unit_cost": uc, "total": _cost(routed_count, uc),
                "notes": f"{routed_count} routed premises",
            })

    # ── Network equipment (per cabinet) ───────────────────────────────────
    pop_layer = get_layer("exchange_pops", project)
    if pop_layer:
        for feat in _area_features(pop_layer, area_id):
            cab_id = _str(feat["pop_id"])
            for desc, key, default in [
                ("Cabinet Enclosure",              "cabinet_each",        4039.72),
                ("Aggregation Router",             "aggreg_router_each",  8000.00),
                ("Eaton DU-X Rectifier Shelf",     "dux_shelf_each",       900.00),
                ("Eaton APR48-ES",                 "eaton_apr48_each",     202.00),
                ("Ubiquity Edgeswitch (mgmt)",     "mgmt_switch_each",     200.00),
                ("Calix E7-2 Shelf + Install Kit", "calix_shelf_each",     556.63),
                ("Calix E7-2 GPON-8 Card",         "gpon_card_each",      4200.00),
                ("Calix GPON SFP",                 "gpon_optic_each",      110.00),
                ("Yuasa NP65-12l Battery",         "battery_each",         145.00),
                ("19in Battery Shelf",            "battery_shelf_each",    40.00),
                ("Electrical Hookup",              "electrical_hookup_each", 24.96),
            ]:
                uc = costs.get(key, default)
                bom["Network Equip"].append({
                    "description": desc,
                    "unit": "each", "qty": 1,
                    "unit_cost": uc, "total": _cost(1, uc),
                    "notes": cab_id,
                })

    # ── Summary ───────────────────────────────────────────────────────────
    def _total_cost(rows):
        return round(sum(r["total"] for r in rows if isinstance(r.get("total"), (int, float))), 2)

    all_rows = (bom["Fibre Cable"] + bom["Drop & Bundle"] + bom["Joints"] +
                bom["Duct"] + bom["PIA"] + bom["Home Install"] + bom["Network Equip"])
    grand_total = round(sum(r["total"] for r in all_rows if isinstance(r.get("total"), (int, float))), 2)

    bom["Summary"] = [
        {"description": "Fibre Cable",   "unit": "", "qty": "", "unit_cost": "", "total": _total_cost(bom["Fibre Cable"]),   "notes": f"{len(bom['Fibre Cable'])} line(s)"},
        {"description": "Drop & Bundle", "unit": "", "qty": "", "unit_cost": "", "total": _total_cost(bom["Drop & Bundle"]), "notes": f"{len(bom['Drop & Bundle'])} line(s)"},
        {"description": "Joints",        "unit": "", "qty": "", "unit_cost": "", "total": _total_cost(bom["Joints"]),        "notes": f"{len(bom['Joints'])} line(s)"},
        {"description": "Duct",          "unit": "", "qty": "", "unit_cost": "", "total": _total_cost(bom["Duct"]),          "notes": f"{len(bom['Duct'])} line(s)"},
        {"description": "PIA",           "unit": "", "qty": "", "unit_cost": "", "total": _total_cost(bom["PIA"]),           "notes": f"{len(bom['PIA'])} line(s)"},
        {"description": "Home Install",  "unit": "", "qty": "", "unit_cost": "", "total": _total_cost(bom["Home Install"]),  "notes": f"{len(bom['Home Install'])} line(s)"},
        {"description": "Network Equip", "unit": "", "qty": "", "unit_cost": "", "total": _total_cost(bom["Network Equip"]), "notes": f"{len(bom['Network Equip'])} line(s)"},
        {"description": "",              "unit": "", "qty": "", "unit_cost": "", "total": "",          "notes": ""},
        {"description": "TOTAL",         "unit": "", "qty": "", "unit_cost": "", "total": grand_total, "notes": "ex. VAT"},
    ]

    return bom


# ── Dialog ────────────────────────────────────────────────────────────────────

def edit_costs_dialog(parent, on_saved=None):
    """Open a dialog to edit and persist unit costs (£ ex. VAT).
    Calls on_saved() after the user saves changes. Shared between the
    BoM dialog and the Cabinet Cost Calculator."""
    from qgis.PyQt.QtWidgets import (QDialog, QFormLayout, QDialogButtonBox,
                                      QScrollArea, QWidget, QVBoxLayout)
    costs = load_costs()

    dlg = QDialog(parent)
    dlg.setWindowTitle("Edit Unit Costs (£ ex. VAT)")
    dlg.setMinimumWidth(380)
    root = QVBoxLayout(dlg)

    scroll = QScrollArea(); scroll.setWidgetResizable(True)
    fw = QWidget(); fl = QFormLayout(fw); fl.setSpacing(6)

    LABELS = {
        # Fibre cable
        "cable_12f_m":           "12F fibre cable (per m)",
        "cable_24f_m":           "24F fibre cable (per m)",
        "cable_48f_m":           "48F fibre cable (per m)",
        "cable_72f_m":           "72F fibre cable (per m)",
        "cable_96f_m":           "96F fibre cable (per m)",
        "cable_aerial_48f_m":    "48F aerial cable G657A1 (per m)",
        "cable_aerial_24f_m":    "24F aerial drop cable (per m)",
        "cable_7mm_m":           "7mm fibre bundle (per m)",
        # Duct
        "shotgun_duct_m":        "Shotgun duct (per m)",
        "flexi_duct_m":          "Flexi-duct (per m)",
        "duct_16mm_m":           "16mm duct (per m)",
        "duct_16mm_connector":   "16mm duct connector (each)",
        "duct_16mm_end_stop":    "16mm duct end stop (each)",
        "duct_7mm_m":            "7mm duct (per m)",
        "duct_7mm_end_stop":     "7mm duct end stop (each)",
        "drop_duct_m":           "Drop duct 7mm (per m)",
        # Chambers
        "chamber_small_each":    "Chamber — Small inc. lid (each)",
        "chamber_large_each":    "Chamber — Large inc. lid (each)",
        # Joints
        "joint_cmj_each":        "Joint — Prysmian CMJ (each)",
        "joint_fdnir_each":      "Joint — FDNIR-AXBCWX (each)",
        "joint_fsttb_a_each":    "Joint — FSTTB-AXBTA11 (each)",
        "joint_fsttb_b_each":    "Joint — FSTTB-AXXTA31 (each)",
        "joint_gland_each":      "Port entry gland (per joint)",
        # Splitters
        "splitter_1x2_each":     "Splitter module 1:2 (each)",
        "splitter_1x4_each":     "Splitter module 1:4 (each)",
        "splitter_1x8_each":     "Splitter module 1:8 (each)",
        "splitter_1x16_each":    "Splitter module 1:16 (each)",
        "splitter_1x32_each":    "Splitter module 1:32 (each)",
        # PIA aerial
        "pole_each":             "PIA pole attachment (each)",
        "cbt_8port_each":        "CBT 8-port Evolv 300m (each)",
        "cbt_4port_each":        "CBT 4-port Corning (each)",
        "cbt_12port_250m_each":  "CBT 12-port Corning 250m (each)",
        "cbt_12port_350m_each":  "CBT 12-port Corning 350m (each)",
        "cbt_pole_bracket":      "CBT pole bracket hinge (each)",
        "cbt_anti_creeper":      "Anti-creeper locking mechanism (each)",
        "aerial_dead_end":       "PLP dead end per span end (each)",
        # Home install
        "ont_each":              "ONT (each)",
        "ont_base_plate_each":   "ONT base plate (each)",
        "toby_box_each":         "Toby box (each)",
        "home_entry_kit_each":   "Home entry kit (each)",
        "router_each":           "Router (each)",
        # Network equipment
        "cabinet_each":          "Cabinet enclosure (each)",
        "aggreg_router_each":    "Aggregation router (each)",
        "dux_shelf_each":        "Eaton DU-X rectifier shelf (each)",
        "eaton_apr48_each":      "Eaton APR48-ES (each)",
        "mgmt_switch_each":      "Ubiquity Edgeswitch mgmt (each)",
        "calix_shelf_each":      "Calix E7-2 shelf + install kit (each)",
        "gpon_card_each":        "Calix GPON-8 card (each)",
        "gpon_optic_each":       "Calix GPON SFP (each)",
        "battery_each":          "Yuasa NP65-12l battery (each)",
        "battery_shelf_each":    "19in battery shelf (each)",
        "electrical_hookup_each": "Electrical hookup (each)",
        "armoured_cable_m":      "3-core armoured cable (per m)",
        # Crossings
        "road_crossing_each":    "Road crossing allowance (each)",
        "stream_crossing_each":  "Stream crossing allowance (each)",
        "scaffold_bar_each":     "Scaff bar (each)",
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
        if on_saved:
            on_saved()


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
        header.setStyleSheet(f"font-size:15px; font-weight:600; color:{WHITE};")
        root.addWidget(header)

        sub = QLabel("Aggregated quantities and costs from all fibre and civil layers. Unit costs editable — prices ex. VAT.")
        sub.setStyleSheet("font-size:11px; color:#8B9AAB; margin-bottom:4px;")
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
        edit_costs_dialog(self, on_saved=self._run)

    def _run(self):
        try:
            self.bom = build_bom(costs=load_costs(), project=self._project)
        except Exception:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.critical(self, "BoM Error", traceback.format_exc())
            return

        self._tabs.clear()

        tab_colours = {
            "Summary":        NAVY,
            "Fibre Cable":    "#6A0080",
            "Drop & Bundle":  ORANGE,
            "Joints":         TEAL,
            "Duct":           "#444444",
            "PIA":            "#8B4513",
            "Home Install":   "#2E7D32",
            "Network Equip":  "#1565C0",
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
