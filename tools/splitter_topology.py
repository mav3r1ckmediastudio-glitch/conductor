# -*- coding: utf-8 -*-
"""Topology-derived splitter validation (validate-only).

Derives splitter presence and role from network structure and compares against
the declared has_splitter / split_ratio fields, returning drift issues for the
validation dock. Does NOT write — declared fields remain the source of truth.

Reliability:
  * presence + role (feeder vs terminal) are derived from graph structure
  * feeder ratio = downstream terminal count (all visible in the graph)
  * terminal ratio is NOT inferred (an under-filled module is invisible); the
    declared value is kept and only checked for oversubscription
"""
from qgis.core import NULL

_STD_MODULES = [2, 4, 8, 16, 32]


def _roundup(n):
    for s in _STD_MODULES:
        if n <= s:
            return s
    return n


def _S(v):
    return None if v is None or v == NULL else str(v)


def derive_splitter_topology(joint_layer, cable_layer, bundle_layer, ddct_layer):
    """Return (derived {jid: ratio}, roles {jid: FEEDER|TERMINAL},
    terminals {jid: consumer_count}, feeders {jid: downstream_terminal_count})."""
    cables = [{"from": _S(f["from_node"]), "to": _S(f["to_node"]),
               "type": _S(f["cable_type"])} for f in cable_layer.getFeatures()]
    node_type = {}
    for f in joint_layer.getFeatures():
        node_type[_S(f["joint_id"])] = _S(f["joint_type"])

    def out_cables(n):
        return [c for c in cables if c["from"] == n and c["type"] != "CBT_TAIL"]

    def bundle_count(j):
        if not bundle_layer:
            return 0
        return sum(1 for f in bundle_layer.getFeatures() if _S(f["from_joint"]) == j)

    def drop_count(c):
        if not ddct_layer:
            return 0
        return sum(1 for f in ddct_layer.getFeatures()
                   if _S(f["from_chamber"]) == c and _S(f["drop_type"]) == "PIA_AERIAL_DROP")

    terminals = {}
    for j in node_type:
        n = drop_count(j) if node_type.get(j) == "CBT" else bundle_count(j)
        if n > 0:
            terminals[j] = n

    def downstream_terminals(node):
        found, seen, stack = set(), set(), [node]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            if x in terminals:
                found.add(x)
            for c in out_cables(x):
                stack.append(c["to"])
        return found

    feeders = {}
    for j in node_type:
        if j in terminals:
            continue
        term_branches = sum(1 for c in out_cables(j) if downstream_terminals(c["to"]))
        if term_branches >= 2:
            feeders[j] = len(downstream_terminals(j))

    derived, roles = {}, {}
    for t, cons in terminals.items():
        derived[t] = "1:%d" % _roundup(cons)
        roles[t] = "TERMINAL"
    for fdr, tc in feeders.items():
        derived[fdr] = "1:%d" % _roundup(tc)
        roles[fdr] = "FEEDER"
    return derived, roles, terminals, feeders


def splitter_drift_issues(joint_layer, cable_layer, bundle_layer, ddct_layer):
    """Compare derived topology against declared has_splitter/split_ratio.
    Returns a list of {severity, message, asset_id} for the validation dock."""
    if not joint_layer or not cable_layer:
        return []
    declared = {}
    for f in joint_layer.getFeatures():
        if f["has_splitter"] in (True, 1):
            declared[_S(f["joint_id"])] = _S(f["split_ratio"])

    derived, roles, terminals, feeders = derive_splitter_topology(
        joint_layer, cable_layer, bundle_layer, ddct_layer)

    issues = []
    for t, cons in terminals.items():
        decl = declared.get(t)
        if decl:
            try:
                cap = int(str(decl).split(":")[1])
                if cons > cap:
                    issues.append({"severity": "error", "asset_id": t,
                        "message": "Splitter oversubscribed: %d consumers exceed declared %s" % (cons, decl)})
            except Exception:
                pass
    for j, d in derived.items():
        if j not in declared:
            issues.append({"severity": "warning", "asset_id": j,
                "message": "Topology indicates a %s splitter but has_splitter is not set" % d})
    for j, decl in declared.items():
        if j not in derived:
            issues.append({"severity": "warning", "asset_id": j,
                "message": "Marked has_splitter=%s but topology shows no premises or downstream split (stale)" % decl})
        elif j in feeders and decl and decl != derived[j]:
            issues.append({"severity": "warning", "asset_id": j,
                "message": "Declared %s but topology serves %d terminals -> %s" % (decl, feeders[j], derived[j])})
    return issues
