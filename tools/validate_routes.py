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
    STATUS_OK:       QColor("#34D399"),
    STATUS_PARTIAL:  QColor("#FBBF24"),
    STATUS_UNSERVED: QColor("#F87171"),
    STATUS_ERROR:    QColor("#EF4444"),
}

STATUS_BG = {
    STATUS_OK:       QColor("#13241B"),   # subtle green tint on dark
    STATUS_PARTIAL:  QColor("#2A1F0A"),   # subtle amber tint on dark
    STATUS_UNSERVED: QColor("#2A1214"),   # subtle red tint on dark
    STATUS_ERROR:    QColor("#2A1214"),
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


def _fibre_loss_db(length_m, optical):
    """Fibre attenuation loss (dB) for a cable/duct/bundle of the given length (m)."""
    try:
        if length_m is None or length_m == NULL:
            return 0.0
        return (float(length_m) / 1000.0) * optical.get("fibre_atten_db_km", 0.0)
    except Exception:
        return 0.0


def _joint_loss_breakdown(joint_idx, joint_id, optical):
    """Return a breakdown of the through-splice loss for a joint:
    {'total', 'splice', 'splitter', 'splitter_ratio'}. 'splitter' and
    'splitter_ratio' are 0.0 / None unless the joint has a splitter fitted
    (has_splitter / split_ratio)."""
    feats = joint_idx.get(str(joint_id), [])
    if not feats:
        return {"total": 0.0, "splice": 0.0, "splitter": 0.0, "splitter_ratio": None}
    jf = feats[0]
    splice = optical.get("splice_loss_db", 0.0)
    splitter = 0.0
    splitter_ratio = None
    field_names = jf.fields().names()
    has_split = jf["has_splitter"] if "has_splitter" in field_names else None
    if has_split and has_split != NULL:
        ratio = jf["split_ratio"] if "split_ratio" in field_names else None
        if ratio and ratio != NULL:
            from .optical_budget import splitter_loss_for_ratio
            splitter = splitter_loss_for_ratio(str(ratio), optical.get("splitter_loss_db", {}))
            splitter_ratio = str(ratio)
    return {"total": splice + splitter, "splice": splice, "splitter": splitter, "splitter_ratio": splitter_ratio}


def _joint_loss_db(joint_idx, joint_id, optical):
    """Through-splice loss for a joint, plus splitter insertion loss if the
    joint has a splitter fitted (has_splitter / split_ratio)."""
    return _joint_loss_breakdown(joint_idx, joint_id, optical)["total"]


def _copy_breakdown(bd):
    """Deep-ish copy of a per-path breakdown dict (None stays None)."""
    if bd is None:
        return None
    return {k: (list(v) if isinstance(v, list) else v) for k, v in bd.items()}


def _accumulate_breakdown(bd, fibre_db=0.0, fibre_length_m=None, joint=None, connector_db=None):
    """Mutate a per-path breakdown dict in place, adding the given loss
    components. No-op if bd is None (breakdown tracking not requested)."""
    if bd is None:
        return
    bd["fibre_db"] = bd.get("fibre_db", 0.0) + fibre_db
    try:
        if fibre_length_m is not None and fibre_length_m != NULL:
            bd["fibre_length_m"] = bd.get("fibre_length_m", 0.0) + float(fibre_length_m)
    except Exception:
        pass
    if joint is not None:
        if joint["splice"]:
            bd["splice_db"] = bd.get("splice_db", 0.0) + joint["splice"]
            bd["splice_count"] = bd.get("splice_count", 0) + 1
        if joint["splitter"]:
            bd["splitter_db"] = bd.get("splitter_db", 0.0) + joint["splitter"]
            bd.setdefault("splitters", []).append(joint["splitter_ratio"])
    if connector_db is not None:
        bd["connector_db"] = bd.get("connector_db", 0.0) + connector_db


def trace_premises(uprn, area_id,
                   bundle_idx, ddct_idx,
                   joint_idx, cable_node_idx,
                   optical=None, breakdown=None):
    if optical is None:
        from .optical_budget import DEFAULT_OPTICAL, DEFAULT_SPLITTER_LOSS_DB
        optical = dict(DEFAULT_OPTICAL)
        optical["splitter_loss_db"] = dict(DEFAULT_SPLITTER_LOSS_DB)

    path = []

    bundles = bundle_idx.get(str(uprn), [])
    ddcts   = ddct_idx.get(str(uprn), [])

    entry_asset    = None
    entry_type     = None
    entry_length_m = None
    first_joint    = None

    if bundles:
        b = bundles[0]
        entry_asset    = str(b["bundle_id"])
        entry_type     = "bundle"
        entry_length_m = b["length_m"]
        first_joint = str(b["from_joint"]) if b["from_joint"] and b["from_joint"] != NULL else None
    elif ddcts:
        d = ddcts[0]
        entry_asset    = str(d["ddct_id"])
        entry_type     = "drop_duct"
        entry_length_m = d["length_m"]
        fc = d["from_chamber"] if d["from_chamber"] and d["from_chamber"] != NULL else None
        fp = d["from_pole"]    if d["from_pole"]    and d["from_pole"]   != NULL else None
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
                            f"Check from_chamber value on {entry_asset}.", None)
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
                        f"Check from_pole value on {entry_asset}.", None)
        else:
            first_joint = None

    if not first_joint:
        if entry_asset is None:
            # No bundle or drop duct at all — this premises simply hasn't
            # been connected to the network yet. This is a build-plan state,
            # not a broken route, so it's UNSERVED rather than PARTIAL.
            return (STATUS_UNSERVED, path,
                    "No bundle or drop duct connects this premises to the network yet. "
                    "Digitise a Drop Duct or Bundle from this premises to a joint.", None)
        return (STATUS_PARTIAL, path + [entry_asset],
                f"{(entry_type or 'asset').replace('_',' ').title()} {entry_asset} has no from_joint value.", None)

    joints = joint_idx.get(first_joint, [])
    if not joints:
        return (STATUS_PARTIAL, path + [entry_asset],
                f"from_joint '{first_joint}' not found in joints layer. "
                f"Joint may have been deleted or ID mismatch.", None)

    # Loss accrued before the BFS starts: the drop/bundle fibre run from the
    # premises to first_joint, plus first_joint's own splice/splitter loss.
    entry_fibre_loss = _fibre_loss_db(entry_length_m, optical)
    entry_joint      = _joint_loss_breakdown(joint_idx, first_joint, optical)
    entry_loss       = entry_fibre_loss + entry_joint["total"]

    init_bd = {} if breakdown is not None else None
    _accumulate_breakdown(init_bd, fibre_db=entry_fibre_loss,
                          fibre_length_m=entry_length_m, joint=entry_joint)

    # BFS — explore all branches, return shortest path to cabinet
    # State: (current_node, path_so_far, visited_set, loss_so_far_db, breakdown_so_far)
    from collections import deque
    queue = deque()
    queue.append((first_joint, [first_joint], {first_joint}, entry_loss, init_bd))

    best_partial = None
    best_partial_reason = f"No cable connected to joint {first_joint}. Digitise a cable from this joint toward the cabinet."

    while queue:
        current_node, cur_path, visited, cur_loss, cur_bd = queue.popleft()

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
            cable_fibre_loss = _fibre_loss_db(cable["length_m"], optical)
            new_loss = cur_loss + cable_fibre_loss
            new_bd   = _copy_breakdown(cur_bd)
            _accumulate_breakdown(new_bd, fibre_db=cable_fibre_loss, fibre_length_m=cable["length_m"])

            if isinstance(next_node, str) and ("CAB" in next_node.upper() or "POP" in next_node.upper()):
                new_path.append(next_node)
                connector_db  = optical.get("connector_loss_db", 0.0)
                total_loss_db = new_loss + connector_db
                _accumulate_breakdown(new_bd, connector_db=connector_db)
                if breakdown is not None:
                    breakdown.clear()
                    breakdown.update(new_bd)

                # ── Splitter chain validation (Gigaloch rule: 1:8 nearest premises, 1:4 nearest cabinet) ──
                splitter_joints = []  # ordered from premises to cabinet
                for node in new_path:
                    node_s = str(node)
                    if "-JNT-" not in node_s and "-CBT-" not in node_s:
                        continue
                    jfeats = joint_idx.get(node_s, [])
                    if not jfeats:
                        continue
                    jf = jfeats[0]
                    has_sp = jf["has_splitter"] if "has_splitter" in jf.fields().names() else None
                    if has_sp and has_sp != NULL:
                        ratio = str(jf["split_ratio"] or "") if "split_ratio" in jf.fields().names() else ""
                        splitter_joints.append((node_s, ratio))

                if len(splitter_joints) == 0:
                    return (STATUS_PARTIAL, new_path,
                            "No splitters found in path. Gigaloch topology requires a 1:4 spine splitter "
                            "and a 1:8 distribution splitter. Check joints in this route.", None)

                elif len(splitter_joints) == 1:
                    jid, ratio = splitter_joints[0]
                    return (STATUS_PARTIAL, new_path,
                            f"Only one splitter found ({jid}, {ratio or 'ratio not set'}). "
                            f"Gigaloch topology requires exactly two: a 1:8 distribution splitter "
                            f"nearest the premises and a 1:4 spine splitter nearest the cabinet.", None)

                elif len(splitter_joints) > 2:
                    jid, ratio = splitter_joints[2]
                    return (STATUS_PARTIAL, new_path,
                            f"Too many splitters ({len(splitter_joints)}) in path. "
                            f"Gigaloch allows exactly two: 1:8 then 1:4. "
                            f"Excess splitter at {jid} ({ratio or 'ratio not set'}).", None)

                else:
                    # Exactly 2 — validate ratios and order
                    near_jid, near_ratio = splitter_joints[0]  # closest to premises
                    far_jid,  far_ratio  = splitter_joints[1]  # closest to cabinet
                    if near_ratio != "1:8":
                        return (STATUS_PARTIAL, new_path,
                                f"Wrong splitter ratio at distribution joint {near_jid}. "
                                f"The joint nearest the premises should be 1:8, "
                                f"but is set to '{near_ratio or 'not set'}'. "
                                f"Gigaloch rule: 1:8 nearest premises, 1:4 nearest cabinet.", None)
                    if far_ratio != "1:4":
                        return (STATUS_PARTIAL, new_path,
                                f"Wrong splitter ratio at spine joint {far_jid}. "
                                f"The joint nearest the cabinet should be 1:4, "
                                f"but is set to '{far_ratio or 'not set'}'. "
                                f"Gigaloch rule: 1:4 nearest cabinet, 1:8 nearest premises.", None)
                    # Valid chain — genuine STATUS_OK
                    return (STATUS_OK, new_path, f"Route complete — {len(new_path)} hops.", total_loss_db)

            new_visited = visited | {next_node}
            new_path    = new_path + [next_node]
            next_joint  = _joint_loss_breakdown(joint_idx, next_node, optical)
            new_loss    = new_loss + next_joint["total"]
            _accumulate_breakdown(new_bd, joint=next_joint)
            queue.append((next_node, new_path, new_visited, new_loss, new_bd))

            if best_partial is None or len(new_path) > len(best_partial):
                best_partial = new_path
                best_partial_reason = (f"Dead end reached at {next_node} — "                                       f"no onward cable leads to the cabinet.")

    return (STATUS_PARTIAL, best_partial or [first_joint],
            best_partial_reason, None)


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

            from .optical_budget import load_optical, link_budget_db
            optical   = load_optical()
            budget_db = link_budget_db(optical)

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
                    status, path, reason, loss_db = trace_premises(
                        uprn, area_id,
                        bundle_idx, ddct_idx,
                        joint_idx, cable_node_idx,
                        optical=optical,
                    )
                except Exception as e:
                    status  = STATUS_ERROR
                    path    = []
                    reason  = f"Exception during trace: {e}"
                    loss_db = None

                if loss_db is not None:
                    margin_db = budget_db - loss_db
                    link_pass = margin_db >= 0
                else:
                    margin_db = None
                    link_pass = None

                summary[status] = summary.get(status, 0) + 1
                results.append({
                    "uprn":      str(uprn),
                    "address":   str(address),
                    "status":    status,
                    "path":      path,
                    "reason":    reason,
                    "geom":      prem.geometry(),
                    "loss_db":   loss_db,
                    "margin_db": margin_db,
                    "link_pass": link_pass,
                })
                self.result.emit(results[-1])

        except Exception as e:
            self.finished.emit(results, {"error": traceback.format_exc()})
            return

        # ── Splitter integrity scan ───────────────────────────────────────
        # Find joints that have >1 downstream bundle/drop but has_splitter=False/NULL
        # from_chamber on drop_ducts holds either a chamber_id (UG drop) or
        # a joint_id directly (CBT aerial drop) — handle both cases.
        splitter_warnings = []
        try:
            if joint_layer and bundle_layer:
                # Build chamber_id -> joint_id map
                chamber_to_joint = {}
                for feat in joint_layer.getFeatures():
                    cid = str(feat["chamber_id"] or "")
                    jid = str(feat["joint_id"]   or "")
                    if cid and jid:
                        chamber_to_joint[cid] = jid

                # Build downstream count per joint_id
                downstream_counts = {}
                for feat in bundle_layer.getFeatures():
                    jid = str(feat["from_joint"] or "")
                    if jid:
                        downstream_counts[jid] = downstream_counts.get(jid, 0) + 1

                if ddct_layer:
                    for feat in ddct_layer.getFeatures():
                        fc = str(feat["from_chamber"] or "")
                        if not fc:
                            continue
                        # Direct joint_id match (CBT aerial drop)
                        if fc in downstream_counts or fc in chamber_to_joint.values():
                            downstream_counts[fc] = downstream_counts.get(fc, 0) + 1
                        else:
                            # Resolve chamber_id to joint_id
                            resolved = chamber_to_joint.get(fc, "")
                            if resolved:
                                downstream_counts[resolved] = downstream_counts.get(resolved, 0) + 1

                for feat in joint_layer.getFeatures():
                    jid = str(feat["joint_id"] or "")
                    count = downstream_counts.get(jid, 0)
                    if count > 1:
                        has_sp = feat["has_splitter"] if "has_splitter" in feat.fields().names() else None
                        if not has_sp or has_sp == NULL:
                            splitter_warnings.append({
                                "joint_id": jid,
                                "downstream": count,
                                "chamber_id": str(feat["chamber_id"] or ""),
                            })
        except Exception:
            pass

        summary["splitter_warnings"] = splitter_warnings
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
        header.setStyleSheet("font-size:15px; font-weight:600; color:#E8EDF2;")
        root.addWidget(header)

        sub = QLabel("Traces every premises to its cabinet via bundles / drop ducts → joints → cables. Flags any break in the chain.")
        sub.setStyleSheet("font-size:11px; color:#8B9AAB; margin-bottom:4px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self._summary_bar = QFrame()
        self._summary_bar.setStyleSheet("QFrame { background:#1A2332; border:1px solid #2D3F52; border-radius:4px; padding:6px; }")
        bar_layout = QHBoxLayout(self._summary_bar)
        bar_layout.setContentsMargins(8, 4, 8, 4)
        bar_layout.setSpacing(20)

        self._lbl_total    = self._stat_label("Total",    "—", "#E8EDF2")
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
            "QProgressBar { border:1px solid #2D3F52; border-radius:3px; background:#0F1923; color:#E8EDF2; height:18px; font-size:11px; } "
            "QProgressBar::chunk { background:#2c7a4b; border-radius:2px; }"
        )
        root.addWidget(self._progress)

        splitter = QSplitter(Qt.Vertical)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["Status", "UPRN", "Address", "Loss (dB)", "Margin (dB)", "Detail"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(
            "QTableWidget { font-size:12px; background:#1A2332; color:#E8EDF2; gridline-color:#2D3F52; alternate-background-color:#0F1923; }"
            "QTableWidget::item { color:#E8EDF2; }"
            "QTableWidget::item:selected { background:#00C9B1; color:#0F1923; }"
            "QHeaderView::section { background:#0F1923; color:#E8EDF2; font-weight:600; padding:4px; border:none; border-bottom:1px solid #2D3F52; }"
        )
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        splitter.addWidget(self._table)

        detail_frame = QFrame()
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.setSpacing(4)
        detail_header = QLabel("Route detail")
        detail_header.setStyleSheet("font-size:11px; font-weight:600; color:#8B9AAB;")
        detail_layout.addWidget(detail_header)
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(130)
        self._detail.setStyleSheet(
            "QTextEdit { font-family: 'Consolas','Courier New',monospace; "
            "font-size:11px; background:#0F1923; color:#E8EDF2; border:1px solid #2D3F52; border-radius:3px; padding:4px; }"
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
        self._btn_zoom.setStyleSheet("QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; background:#1A2332; color:#E8EDF2; border:1px solid #2D3F52; } QPushButton:hover { background:#2D3F52; border-color:#00C9B1; } QPushButton:disabled { color:#5A6B7A; border-color:#2D3F52; }")
        self._btn_zoom.clicked.connect(self._zoom_to_selected)

        self._btn_export = QPushButton("\u2193  Export CSV")
        self._btn_export.setEnabled(False)
        self._btn_export.setStyleSheet("QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; background:#1A2332; color:#E8EDF2; border:1px solid #2D3F52; } QPushButton:hover { background:#2D3F52; border-color:#00C9B1; } QPushButton:disabled { color:#5A6B7A; border-color:#2D3F52; }")
        self._btn_export.clicked.connect(self._export_csv)

        self._btn_optical = QPushButton("\u2699  Power Budget Settings")
        self._btn_optical.setStyleSheet("QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; background:#1A2332; color:#E8EDF2; border:1px solid #2D3F52; } QPushButton:hover { background:#2D3F52; border-color:#00C9B1; }")
        self._btn_optical.clicked.connect(self._edit_optical)

        self._btn_close = QPushButton("Close")
        self._btn_close.setStyleSheet("QPushButton { padding:7px 14px; border-radius:4px; font-size:12px; background:#1A2332; color:#E8EDF2; border:1px solid #2D3F52; } QPushButton:hover { background:#2D3F52; border-color:#00C9B1; }")
        self._btn_close.clicked.connect(self.close)

        btn_row.addWidget(self._btn_run)
        btn_row.addWidget(self._btn_zoom)
        btn_row.addWidget(self._btn_export)
        btn_row.addWidget(self._btn_optical)
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
        ttl_lbl.setStyleSheet("font-size:10px; color:#8B9AAB; text-transform:uppercase;")
        layout.addWidget(val_lbl)
        layout.addWidget(ttl_lbl)
        w._value_label = val_lbl
        return w

    def _update_stat(self, widget, value):
        widget._value_label.setText(str(value))

    def _edit_optical(self):
        """Open a dialog to edit and persist optical power budget settings,
        then re-run validation so loss/margin figures reflect the change."""
        from .optical_budget import edit_optical_dialog
        edit_optical_dialog(self, on_saved=self._run)

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

        loss_db   = r.get("loss_db")
        margin_db = r.get("margin_db")
        link_pass = r.get("link_pass")

        loss_item   = QTableWidgetItem(f"{loss_db:.2f}" if loss_db is not None else "—")
        margin_item = QTableWidgetItem(f"{margin_db:+.2f}" if margin_db is not None else "—")
        if link_pass is True:
            margin_item.setForeground(QBrush(STATUS_COLOURS[STATUS_OK]))
            margin_item.setFont(QFont("", -1, QFont.Bold))
        elif link_pass is False:
            margin_item.setForeground(QBrush(STATUS_COLOURS[STATUS_UNSERVED]))
            margin_item.setFont(QFont("", -1, QFont.Bold))

        reason_item  = QTableWidgetItem(r["reason"])
        # Plain (non-RAG) cells need an explicit light foreground; with a custom
        # item background set, Qt ignores the widget stylesheet's text colour and
        # falls back to a dark default, which is invisible on the dark row tint.
        _light_fg = QBrush(QColor("#E8EDF2"))
        for item in (uprn_item, address_item, loss_item, reason_item):
            item.setForeground(_light_fg)
        for item in (status_item, uprn_item, address_item, loss_item, margin_item, reason_item):
            item.setData(Qt.UserRole, len(self.results) - 1)
            item.setBackground(QBrush(bg))
        self._table.setItem(row, 0, status_item)
        self._table.setItem(row, 1, uprn_item)
        self._table.setItem(row, 2, address_item)
        self._table.setItem(row, 3, loss_item)
        self._table.setItem(row, 4, margin_item)
        self._table.setItem(row, 5, reason_item)

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

        # Surface splitter integrity warnings
        splitter_warnings = summary.get("splitter_warnings", [])
        if splitter_warnings:
            lines = ["⚠  Splitter integrity warnings", ""]
            lines.append(f"{len(splitter_warnings)} joint(s) have multiple downstream connections but no splitter declared:")
            lines.append("")
            for w in splitter_warnings:
                lines.append(f"  • {w['joint_id']}  (chamber: {w['chamber_id']},  {w['downstream']} downstream connections)")
            lines.append("")
            lines.append("If any of these joints distribute signal via a passive splitter,")
            lines.append("edit the joint and tick 'This joint contains a passive optical splitter'.")
            lines.append("Optical budget calculations will be wrong until this is corrected.")
            self._detail.setPlainText("\n".join(lines))

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
        loss_db   = r.get("loss_db")
        margin_db = r.get("margin_db")
        link_pass = r.get("link_pass")
        if loss_db is not None:
            verdict = "PASS" if link_pass else "FAIL"
            lines.append(f"Optical loss:  {loss_db:.2f} dB")
            lines.append(f"Margin:        {margin_db:+.2f} dB  ({verdict})")
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
        writer.writerow(["UPRN", "Address", "Status", "Loss (dB)", "Margin (dB)", "Link", "Reason", "Path"])
        for r in self.results:
            loss_db   = r.get("loss_db")
            margin_db = r.get("margin_db")
            link_pass = r.get("link_pass")
            writer.writerow([
                r["uprn"], r["address"], r["status"],
                f"{loss_db:.2f}" if loss_db is not None else "",
                f"{margin_db:+.2f}" if margin_db is not None else "",
                "PASS" if link_pass is True else ("FAIL" if link_pass is False else ""),
                r["reason"], " \u2192 ".join(r["path"]),
            ])
        try:
            actual = safe_write_text(path, buf.getvalue(), what="Validation CSV")
        except Exception as e:
            QMessageBox.critical(self, "Export failed",
                                 f"Could not save results \u2014 the file may be open "
                                 f"in another program.\n\n{e}")
            return
        QMessageBox.information(self, "Export complete", f"Results saved to:\n{actual}")



def run_validation_headless(project):
    """
    Run the full route validation synchronously (no QThread/dialog) and return
    a results dict compatible with ConductorValidationDock.push_validation_results().

    Returns:
        {
            "critical":  int,
            "errors":    int,
            "warnings":  int,
            "info":      int,
            "score_pct": int | None,
            "issues":    [ {"severity", "message", "asset_id"} ]
        }
    """
    from ..conductor_utils import get_layer

    LAYER_NAMES = {
        "premises":   "premises",
        "bundles":    "bundles",
        "drop_ducts": "drop_ducts",
        "joints":     "joints",
        "cables":     "cables",
    }

    issues   = []
    counts   = {"critical": 0, "errors": 0, "warnings": 0, "info": 0}
    summary  = {STATUS_OK: 0, STATUS_PARTIAL: 0, STATUS_UNSERVED: 0, STATUS_ERROR: 0}

    try:
        premises_layer = get_layer(LAYER_NAMES["premises"],   project)
        bundle_layer   = get_layer(LAYER_NAMES["bundles"],    project)
        ddct_layer     = get_layer(LAYER_NAMES["drop_ducts"], project)
        joint_layer    = get_layer(LAYER_NAMES["joints"],     project)
        cable_layer    = get_layer(LAYER_NAMES["cables"],     project)

        if not premises_layer or not cable_layer:
            return {**counts, "score_pct": None, "issues": [{
                "severity": "error",
                "message":  "Required layers not found (premises / cables).",
                "asset_id": "",
            }]}

        bundle_idx     = _build_index(bundle_layer, "uprn")    if bundle_layer else {}
        ddct_idx       = _build_index(ddct_layer,   "uprn")    if ddct_layer   else {}
        joint_idx      = _build_index(joint_layer,  "joint_id")
        cable_node_idx = _build_cable_node_index(cable_layer)

        from .optical_budget import load_optical, link_budget_db
        optical   = load_optical()
        budget_db = link_budget_db(optical)

        total   = premises_layer.featureCount()
        routed  = 0

        for prem in premises_layer.getFeatures():
            uprn    = prem["uprn"]
            area_id = prem["area_id"] if "area_id" in prem.fields().names() else ""

            try:
                status, path, reason, loss_db = trace_premises(
                    uprn, area_id,
                    bundle_idx, ddct_idx,
                    joint_idx, cable_node_idx,
                    optical=optical,
                )
            except Exception as e:
                status = STATUS_ERROR
                reason = f"Trace exception: {e}"
                loss_db = None

            summary[status] = summary.get(status, 0) + 1

            if status == STATUS_OK:
                routed += 1
                # Optical budget check
                if loss_db is not None:
                    margin_db = budget_db - loss_db
                    if margin_db < 0:
                        counts["warnings"] += 1
                        issues.append({
                            "severity": "warning",
                            "message":  f"Optical budget fail ({margin_db:+.1f} dB margin)",
                            "asset_id": str(uprn),
                        })
            elif status == STATUS_PARTIAL:
                counts["warnings"] += 1
                issues.append({
                    "severity": "warning",
                    "message":  f"Partial route: {reason}",
                    "asset_id": str(uprn),
                })
            elif status == STATUS_UNSERVED:
                counts["info"] += 1
                issues.append({
                    "severity": "info",
                    "message":  f"Unserved: {reason}",
                    "asset_id": str(uprn),
                })
            elif status == STATUS_ERROR:
                counts["errors"] += 1
                issues.append({
                    "severity": "error",
                    "message":  f"Trace error: {reason}",
                    "asset_id": str(uprn),
                })

        # ── Splitter topology drift scan ──────────────────────────────────────
        try:
            from .splitter_topology import splitter_drift_issues
            _ck = {"warning": "warnings", "error": "errors",
                   "critical": "critical", "info": "info"}
            for it in splitter_drift_issues(joint_layer, cable_layer, bundle_layer, ddct_layer):
                counts[_ck.get(it["severity"], "warnings")] += 1
                issues.append(it)
        except Exception:
            pass

        # ── Score ─────────────────────────────────────────────────────────────
        clean = routed - sum(
            1 for iss in issues
            if iss["severity"] == "warning" and "Optical budget" in iss["message"]
        )
        score_pct = round((clean / total) * 100) if total > 0 else None

    except Exception as e:
        import traceback
        return {**counts, "score_pct": None, "routed": 0, "partial": 0, "total": 0, "issues": [{
            "severity": "critical",
            "message":  f"Validation failed: {traceback.format_exc()}",
            "asset_id": "",
        }]}

    return {
        **counts,
        "score_pct": score_pct,
        "routed":    summary.get(STATUS_OK,      0),
        "partial":   summary.get(STATUS_PARTIAL,  0),
        "total":     total,
        "issues":    issues,
    }


def open_validate_routes_dialog(iface, parent=None, project=None):
    dlg = ValidateRoutesDialog(iface, parent, project=project)
    dlg.show()
    return dlg
