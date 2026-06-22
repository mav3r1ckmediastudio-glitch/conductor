"""
validate_integrity.py  —  Conductor FTTP Network Design Plugin

Foreign-key / relationship integrity validator. Complements validate_routes.py
(which is route/optical focused) by checking that every cross-layer reference
resolves to a real feature. Catches orphaned FKs anywhere in the model:
dangling from_node/to_node, drop ducts pointing at deleted chambers, fibre
assignments referencing removed cables, etc.

Pure read-only static analysis over the GeoPackage. Safe to run headless.
"""

from qgis.core import QgsProject, NULL
from ..conductor_utils import get_layer, fld


# ── Severity ──────────────────────────────────────────────────────────────────
SEV_ERROR = "ERROR"     # FK has a value but it resolves to nothing -> real orphan
SEV_WARN  = "WARN"      # ambiguous / soft issue worth a look

# Values that are NOT a reference: treat as "unset", skip silently.
def _is_blank(v):
    if v is None or v == NULL:
        return True
    s = str(v).strip()
    return s == "" or s.upper() in ("NULL", "NONE")


def _is_splitter_pseudo_id(v):
    """Splitter virtual handle like 'ENG-CH3-JNT-002-SP'. Written into
    cable_id/splitter_id by the cascade engine; resolves against the splitter
    set (joints with has_splitter=True), NOT the cables/joints PK."""
    if _is_blank(v):
        return False
    return str(v).strip().upper().endswith("-SP")


def _build_splitter_set():
    """{joint_id}-SP for every joint with has_splitter=True."""
    lyr = get_layer("joints")
    if lyr is None:
        return set()
    out = set()
    for feat in lyr.getFeatures():
        jid = fld(feat, "joint_id")
        has = fld(feat, "has_splitter")
        if not _is_blank(jid) and bool(has):
            out.add(str(jid).strip() + "-SP")
    return out


def _pia_pole_chamber_ids():
    """Poles are stored as chamber_type='PIA_POLE' records in the chambers layer
    (place_pole.py writes there, not to the poles layer). Any pole-typed FK can
    legitimately resolve against these. Returns the set of those chamber_ids."""
    lyr = get_layer("chambers")
    if lyr is None:
        return set()
    out = set()
    for feat in lyr.getFeatures():
        ct = fld(feat, "chamber_type")
        cid = fld(feat, "chamber_id")
        if not _is_blank(cid) and str(ct).strip().upper() == "PIA_POLE":
            out.add(str(cid).strip())
    return out


# ── Type discriminator -> target layer(s) ──────────────────────────────────────
# Resolved against live CH33 data: JOINT and CBT both live in the joints layer;
# POP holds a real pop_id in exchange_pops.
NODE_TYPE_LAYER = {
    "CHAMBER": "chambers",
    "JOINT":   "joints",
    "CBT":     "joints",
    "POLE":    "poles",
    "POP":     "exchange_pops",
}

# ── ID field per layer (the primary key each layer is referenced by) ───────────
ID_FIELD = {
    "build_areas":   "area_id",
    "premises":      "uprn",
    "exchange_pops": "pop_id",
    "chambers":      "chamber_id",
    "poles":         "pole_id",
    "ducts":         "duct_id",
    "cables":        "cable_id",
    "joints":        "joint_id",
    "drop_ducts":    "ddct_id",
    "bundles":       "bundle_id",
    "wayleaves":     "wayleave_id",
}


def _build_id_set(layer_key):
    """Return set of all primary-key values present in a layer (as strings)."""
    lyr = get_layer(layer_key)
    if lyr is None:
        return None  # layer missing entirely
    idf = ID_FIELD.get(layer_key)
    out = set()
    for feat in lyr.getFeatures():
        v = fld(feat, idf)
        if not _is_blank(v):
            out.add(str(v).strip())
    return out


# ── Relationship contract ──────────────────────────────────────────────────────
# Each check is (source_layer, fk_field, id_field_for_msg, resolver).
# resolver(feat, caches) -> (ok: bool, detail: str)

def _direct(target_key):
    """FK resolves against a single target layer."""
    def resolve(value, caches):
        ids = caches.get(target_key)
        if ids is None:
            return None, f"target layer '{target_key}' missing"
        return (str(value).strip() in ids), f"-> {target_key}"
    return resolve


def _multi(target_keys):
    """FK may resolve against any of several layers (e.g. from_chamber)."""
    def resolve(value, caches):
        v = str(value).strip()
        missing = [k for k in target_keys if caches.get(k) is None]
        for k in target_keys:
            ids = caches.get(k)
            if ids and v in ids:
                return True, f"-> {k}"
        if len(missing) == len(target_keys):
            return None, f"target layers {target_keys} all missing"
        return False, f"not found in {target_keys}"
    return resolve


def _typed(type_field):
    """Polymorphic FK: target layer chosen by a companion *_type field."""
    def resolve_factory(feat):
        t = fld(feat, type_field)
        if _is_blank(t):
            return None, f"no {type_field}"
        tkey = NODE_TYPE_LAYER.get(str(t).strip().upper())
        if tkey is None:
            return None, f"unknown {type_field}={t!r}"
        return tkey, None
    return resolve_factory


# Static (non-polymorphic) FK checks
DIRECT_CHECKS = [
    # (source_layer, fk_field, resolver)
    ("premises",          "area_id",        _direct("build_areas")),
    ("chambers",          "pop_id",         _direct("exchange_pops")),
    ("chambers",          "area_id",        _direct("build_areas")),
    ("ducts",             "from_pole",      _direct("poles")),
    ("ducts",             "to_pole",        _direct("poles")),
    ("ducts",             "wayleave_id",    _direct("wayleaves")),
    ("cables",            "duct_id",        _direct("ducts")),
    ("cables",            "pop_id",         _direct("exchange_pops")),
    ("joints",            "chamber_id",     _direct("chambers")),
    ("joints",            "pole_id",        _direct("poles")),
    ("joints",            "pop_id",         _direct("exchange_pops")),
    ("drop_ducts",        "uprn",           _direct("premises")),
    ("drop_ducts",        "from_pole",      _direct("poles")),
    ("bundles",           "uprn",           _direct("premises")),
    ("bundles",           "from_joint",     _direct("joints")),
    ("bundles",           "ddct_id",        _direct("drop_ducts")),
    ("bundles",           "wayleave_id",    _direct("wayleaves")),
    ("fibre_assignments", "splice_to_cable",_direct("cables")),
    ("fibre_assignments", "joint_id",       _direct("joints")),
    ("customers",         "uprn",           _direct("premises")),
    ("build_tasks",       "pop_id",         _direct("exchange_pops")),
]

# Overloaded: from_chamber is a chamber_id OR a CBT joint_id.
MULTI_CHECKS = [
    ("drop_ducts", "from_chamber", _multi(["chambers", "joints"])),
    # bundle_id in fibre_assignments is overloaded: a real BDL on the bundle path,
    # or a ddct/CBT/joint id on the CBT path (idf branches in fibre_assign.py).
    ("fibre_assignments", "bundle_id", _multi(["bundles", "drop_ducts", "joints"])),
]

# Splitter-aware FK fields: a '-SP' value resolves against the splitter set;
# a non-'-SP' value resolves against the named real layer.
SPLITTER_AWARE_CHECKS = [
    ("fibre_assignments", "cable_id",    "cables"),
    ("fibre_assignments", "splitter_id", "joints"),
]

# Polymorphic typed-node FK checks
TYPED_CHECKS = [
    ("ducts",  "from_node", "from_node_type"),
    ("ducts",  "to_node",   "to_node_type"),
    ("cables", "from_node", "from_node_type"),
    ("cables", "to_node",   "to_node_type"),
]


def run_integrity_check_headless():
    """
    Run all FK checks. Returns a dict:
      {
        "ok": bool,                 # True if zero ERROR-severity orphans
        "error_count": int,
        "warn_count": int,
        "checked": int,             # total FK values examined (non-blank)
        "issues": [ {layer, field, value, fid, severity, detail}, ... ],
        "missing_layers": [...],
      }
    """
    # Build PK caches once
    caches = {}
    missing_layers = []
    for key in set(ID_FIELD.keys()):
        ids = _build_id_set(key)
        caches[key] = ids
        if ids is None:
            missing_layers.append(key)
    # Poles live in two places: the (often empty) poles layer AND PIA_POLE
    # chambers. Union them so pole-typed FKs resolve against the true universe.
    _pole_universe = set(caches.get("poles") or set()) | _pia_pole_chamber_ids()
    caches["poles"] = _pole_universe
    caches["_splitters"] = _build_splitter_set()

    issues = []
    checked = 0

    def record(layer_key, field, value, fid, severity, detail):
        issues.append({
            "layer": layer_key, "field": field, "value": str(value),
            "fid": fid, "severity": severity, "detail": detail,
        })

    # Direct + multi
    for layer_key, field, resolver in DIRECT_CHECKS + MULTI_CHECKS:
        lyr = get_layer(layer_key)
        if lyr is None:
            continue
        if lyr.fields().indexOf(field) < 0:
            continue
        for feat in lyr.getFeatures():
            v = fld(feat, field)
            if _is_blank(v):
                continue
            checked += 1
            ok, detail = resolver(str(v).strip(), caches)
            if ok is None:
                record(layer_key, field, v, feat.id(), SEV_WARN, detail)
            elif not ok:
                record(layer_key, field, v, feat.id(), SEV_ERROR, detail)

    # Polymorphic typed checks
    for layer_key, node_field, type_field in TYPED_CHECKS:
        lyr = get_layer(layer_key)
        if lyr is None:
            continue
        if lyr.fields().indexOf(node_field) < 0:
            continue
        typer = _typed(type_field)
        for feat in lyr.getFeatures():
            v = fld(feat, node_field)
            if _is_blank(v):
                continue
            checked += 1
            tkey, warn = typer(feat)
            if tkey is None:
                record(layer_key, node_field, v, feat.id(), SEV_WARN,
                       warn or "unresolved type")
                continue
            ids = caches.get(tkey)
            if ids is None:
                record(layer_key, node_field, v, feat.id(), SEV_WARN,
                       f"target layer '{tkey}' missing")
            elif str(v).strip() not in ids:
                record(layer_key, node_field, v, feat.id(), SEV_ERROR,
                       f"{type_field} says {tkey}, id not found there")

    # Splitter-aware checks: '-SP' -> splitter set, else -> named real layer.
    for layer_key, field, real_layer in SPLITTER_AWARE_CHECKS:
        lyr = get_layer(layer_key)
        if lyr is None:
            continue
        if lyr.fields().indexOf(field) < 0:
            continue
        for feat in lyr.getFeatures():
            v = fld(feat, field)
            if _is_blank(v):
                continue
            checked += 1
            vs = str(v).strip()
            if _is_splitter_pseudo_id(vs):
                if vs not in caches["_splitters"]:
                    record(layer_key, field, v, feat.id(), SEV_ERROR,
                           "splitter pseudo-id has no has_splitter=True joint")
            else:
                ids = caches.get(real_layer)
                if ids is not None and vs not in ids:
                    record(layer_key, field, v, feat.id(), SEV_ERROR,
                           "-> " + real_layer)

    error_count = sum(1 for i in issues if i["severity"] == SEV_ERROR)
    warn_count  = sum(1 for i in issues if i["severity"] == SEV_WARN)

    return {
        "ok": error_count == 0,
        "error_count": error_count,
        "warn_count": warn_count,
        "checked": checked,
        "issues": issues,
        "missing_layers": missing_layers,
    }
