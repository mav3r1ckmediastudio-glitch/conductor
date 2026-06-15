"""
project_summary.py — Conductor FTTP Network Design Plugin
Computes the stats shown in the dock widget's persistent project summary
panel: premises validation status counts, fibre/duct lengths, and an
estimated materials cost from the Bill of Materials.

This is intentionally synchronous (no QThread) — for the project sizes
Conductor is designed around (~500 premises) the full route validation
pass completes well within a second, so it can run on a button click
without needing background-thread plumbing.
"""

from ..conductor_utils import get_layer
from .validate_routes import (
    trace_premises, _build_index, _build_cable_node_index,
    STATUS_OK, STATUS_PARTIAL,
)
from .bom import build_bom, load_costs


def _layer_length_km(layer):
    """Sum the length_m field across a layer's features, in km."""
    if layer is None:
        return 0.0
    total = 0.0
    for feat in layer.getFeatures():
        try:
            total += float(feat["length_m"] or 0)
        except (TypeError, ValueError, KeyError):
            pass
    return total / 1000.0


def compute_summary(project=None, costs=None):
    """
    Synchronously compute the project summary dashboard stats.

    Returns a dict:
        {
            "premises":       int,
            "routed":         int,
            "partial":        int,
            "unserved":       int,   # includes any ERROR-status premises
            "fibre_km":       float, # cables + bundles, in km
            "duct_km":        float, # ducts + drop ducts, in km
            "materials_cost": float, # grand total from build_bom()
            "error":          str or None,
        }

    Any layer that can't be found is treated as zero/empty rather than
    raising, so a partially-built project still produces a usable summary.
    """
    summary = {
        "premises": 0,
        "routed": 0,
        "partial": 0,
        "unserved": 0,
        "fibre_km": 0.0,
        "duct_km": 0.0,
        "materials_cost": 0.0,
        "error": None,
    }

    # -- Premises count ------------------------------------------------------
    premises_layer = get_layer("premises", project)
    if premises_layer is not None:
        summary["premises"] = premises_layer.featureCount()

    # -- Route validation (ROUTED / PARTIAL / UNSERVED) ----------------------
    try:
        bundle_layer = get_layer("bundles", project)
        ddct_layer   = get_layer("drop_ducts", project)
        joint_layer  = get_layer("joints", project)
        cable_layer  = get_layer("cables", project)

        if premises_layer is not None and cable_layer is not None:
            bundle_idx     = _build_index(bundle_layer, "uprn")   if bundle_layer else {}
            ddct_idx       = _build_index(ddct_layer,   "uprn")   if ddct_layer   else {}
            joint_idx      = _build_index(joint_layer,  "joint_id")
            cable_node_idx = _build_cable_node_index(cable_layer)

            for prem in premises_layer.getFeatures():
                uprn = prem["uprn"]
                area_id = prem["area_id"] if "area_id" in prem.fields().names() else ""
                try:
                    status, _path, _reason = trace_premises(
                        uprn, area_id,
                        bundle_idx, ddct_idx,
                        joint_idx, cable_node_idx,
                    )
                except Exception:
                    status = None

                if status == STATUS_OK:
                    summary["routed"] += 1
                elif status == STATUS_PARTIAL:
                    summary["partial"] += 1
                else:
                    summary["unserved"] += 1
    except Exception as e:
        summary["error"] = f"Validation step failed: {e}"

    # -- Fibre / duct lengths -------------------------------------------------
    cables_layer      = get_layer("cables", project)
    bundles_layer     = get_layer("bundles", project)
    ducts_layer       = get_layer("ducts", project)
    drop_ducts_layer  = get_layer("drop_ducts", project)

    summary["fibre_km"] = round(
        _layer_length_km(cables_layer) + _layer_length_km(bundles_layer), 2
    )
    summary["duct_km"] = round(
        _layer_length_km(ducts_layer) + _layer_length_km(drop_ducts_layer), 2
    )

    # -- Estimated materials cost (from Bill of Materials) --------------------
    try:
        if costs is None:
            costs = load_costs()
        bom = build_bom(costs=costs, project=project)
        summary["materials_cost"] = bom["Summary"][-1]["total"]
    except Exception as e:
        if summary["error"] is None:
            summary["error"] = f"Cost estimate failed: {e}"

    return summary
