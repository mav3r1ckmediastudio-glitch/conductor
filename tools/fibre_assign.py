# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QProgressBar, QFrame
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsProject, QgsFeature, NULL
import traceback
from ..conductor_utils import get_layer, fld, val, LayerEditContext

IEC_COLOURS = ['Blue','Orange','Green','Brown','Slate','White','Red','Black','Yellow','Violet','Rose','Aqua']

def fibre_colour(fib): return IEC_COLOURS[(fib - 1) % 12]
def tube_for_fibre(n, fpt=12): return ((n - 1) // fpt) + 1
def pos_in_tube(n, fpt=12):    return ((n - 1) % fpt) + 1

_PROJECT_REF = [None]  # module-level project reference





def build_graph():
    """
    Build the network graph for fibre assignment.

    Aerial spans are real cables in the cables layer (cable_type='AERIAL').
    from_node and to_node on aerial cables are CBT joint_ids.
    Aerial drops are in drop_ducts with from_chamber = CBT joint_id.

    Returns:
        cables     - dict of cable_id -> feature
        joints     - dict of joint_id -> feature
        bundles    - dict of joint_id -> [bundle features]  (underground drops keyed by from_joint)
        cbt_drops  - dict of cbt_joint_id -> [drop_duct features] (aerial drops keyed by from_chamber)
        from_node  - dict of node_id -> [cable features] leaving that node
        cabinet    - str, the cabinet pop_id
    """
    cable_layer  = get_layer("Cables")
    joint_layer  = get_layer("Joints")
    bundle_layer = get_layer("Bundles")
    drop_layer   = get_layer("drop_ducts")

    if not cable_layer or not joint_layer:
        raise RuntimeError("Cables or Joints layer not found")

    cables    = {}
    joints    = {}
    bundles   = {}
    cbt_drops = {}
    from_node = {}

    # Index cables
    for feat in cable_layer.getFeatures():
        cid = str(feat["cable_id"])
        cables[cid] = feat
        fn = val(feat["from_node"])
        if fn:
            from_node.setdefault(str(fn), []).append(feat)

    # Index joints
    for feat in joint_layer.getFeatures():
        jid = str(feat["joint_id"])
        joints[jid] = feat

    # Index underground bundles by from_joint
    if bundle_layer:
        for feat in bundle_layer.getFeatures():
            fj = val(feat["from_joint"])
            if fj:
                bundles.setdefault(str(fj), []).append(feat)

    # Index aerial drops by from_chamber (= CBT joint_id)
    # Only include drops with drop_type = 'PIA_AERIAL_DROP' to avoid
    # confusing underground drop_ducts (which also have from_chamber set)
    if drop_layer:
        for feat in drop_layer.getFeatures():
            fc = val(feat["from_chamber"])
            dt = str(val(feat["drop_type"]) or "")
            if fc and dt == "PIA_AERIAL_DROP":
                cbt_drops.setdefault(str(fc), []).append(feat)

    # Find all cabinets — cables must be digitised cabinet->outward (from_node_type=POP)
    cabinets = []
    for feat in cable_layer.getFeatures():
        if val(feat["from_node_type"]) == "POP":
            cab = str(feat["from_node"])
            if cab not in cabinets:
                cabinets.append(cab)

    return cables, joints, bundles, cbt_drops, from_node, cabinets


FROZEN_STATES = {"INSTALLED", "LIVE"}


def sticky_allocate(consumers, cap):
    """Stable, freeze-aware port allocation.

    consumers: list of dicts with keys asset, sort_key, port (int|None), status.
    Returns (occupied {port:asset}, port_of {asset:port}, flags [str]).
    Stored ports are honoured (sticky); INSTALLED/LIVE are frozen; the rest fill
    the lowest free ports deterministically by sort_key.
    """
    occupied = {}
    port_of = {}
    flags = []
    stored = [c for c in consumers if c["port"] and 1 <= c["port"] <= cap]
    fresh = [c for c in consumers if not (c["port"] and 1 <= c["port"] <= cap)]
    for c in sorted(stored, key=lambda x: (x["status"] not in FROZEN_STATES, x["port"], x["sort_key"])):
        p = c["port"]
        if p in occupied:
            flags.append("COLLISION port " + str(p) + ": " + str(occupied[p]) + " vs " + str(c["asset"]))
        else:
            occupied[p] = c["asset"]
            port_of[c["asset"]] = p
    free = [p for p in range(1, cap + 1) if p not in occupied]
    for c in sorted(fresh, key=lambda x: x["sort_key"]):
        if free:
            p = free.pop(0)
            occupied[p] = c["asset"]
            port_of[c["asset"]] = p
        else:
            flags.append("OVERCAP: " + str(c["asset"]) + " (no free port within cap " + str(cap) + ")")
    for c in consumers:
        if c["status"] in FROZEN_STATES and c["asset"] not in port_of:
            flags.append("FROZEN_UNPLACED: " + str(c["asset"]) + " (status=" + str(c["status"]) + ")")
    return occupied, port_of, flags


def assign_fibres(log_fn=None):
    # Cascade-aware fibre assignment (v2).
    # Every splitter consumes exactly ONE input fibre; its outputs map to the
    # downstream consumers (1:8 splitters for a 1:4; bundles/drops for a 1:8).
    # Express fibres dark-store at the splitter where they are no longer needed.
    # CBT feeds are routed via through-splices at the tail-attach joint.
    # Returns (assignments, joint_updates).
    def log(m):
        if log_fn:
            log_fn(m)

    def S(v):
        return None if v is None or v == NULL else str(v)

    cab_layer = get_layer("Cables")
    jnt_layer = get_layer("Joints")
    bdl_layer = get_layer("Bundles")
    dd_layer  = get_layer("drop_ducts")
    if not cab_layer or not jnt_layer:
        raise RuntimeError("Cables or Joints layer not found")

    cables = []
    for f in cab_layer.getFeatures():
        cables.append({
            "id":   S(f["cable_id"]),
            "from": S(f["from_node"]),
            "to":   S(f["to_node"]),
            "type": S(f["cable_type"]),
            "fc":   int(fld(f, "fibre_count", 48) or 48),
        })

    splitters = {}
    node_type = {}
    joint_status = {}
    joint_fport = {}
    _jflds = [fld_.name() for fld_ in jnt_layer.fields()]
    for f in jnt_layer.getFeatures():
        jid = S(f["joint_id"])
        node_type[jid] = S(f["joint_type"])
        joint_status[jid] = (S(f["status"]) or "PROPOSED")
        if "feeder_port" in _jflds:
            _fp = f["feeder_port"]
            joint_fport[jid] = (int(_fp) if _fp not in (None, NULL) else None)
        if fld(f, "has_splitter", False) in (True, 1):
            splitters[jid] = S(f["split_ratio"])

    def feeder_of(n):
        for c in cables:
            if c["to"] == n and c["type"] != "CBT_TAIL":
                return c
        return None

    def tail_of(cbt):
        for c in cables:
            if c["type"] == "CBT_TAIL" and c["from"] == cbt:
                return c
        return None

    def trace_up(node, excl=None):
        seen = set()
        path = []
        while node and node not in seen:
            seen.add(node)
            path.append(node)
            if node in splitters and node != excl:
                return node, path
            fc = feeder_of(node)
            if not fc:
                return None, path
            node = fc["from"]
        return None, path

    def ug_bundles(j):
        out = []
        if bdl_layer:
            for b in bdl_layer.getFeatures():
                if S(b["from_joint"]) == j:
                    out.append((S(b["bundle_id"]), S(b["uprn"])))
        return sorted(out)

    def cbt_drops(c):
        out = []
        if dd_layer:
            for d in dd_layer.getFeatures():
                if S(d["from_chamber"]) == c:
                    out.append((S(d["ddct_id"]), S(d["uprn"])))
        return sorted(out)

    def children_of(p):
        kids = []
        for sp, r in splitters.items():
            if r != "1:8":
                continue
            is_cbt = node_type.get(sp) == "CBT"
            if is_cbt:
                t = tail_of(sp)
                innode = t["to"] if t else None
            else:
                fc = feeder_of(sp)
                innode = fc["from"] if fc else None
            par, _ = trace_up(innode, excl=sp)
            if par == p:
                kids.append((len(_), sp, is_cbt))
        kids.sort(key=lambda x: (x[0], x[1]))
        return kids

    assignments = []
    counter = [0]
    joint_updates = {}
    port_updates = {}

    def rec(cable, fib, role, joint=None, bundle=None, splitter=None, sc=None, sf=None):
        counter[0] += 1
        assignments.append({
            "assign_id":       "ASN-" + str(counter[0]).zfill(4),
            "cable_id":        cable,
            "tube_number":     tube_for_fibre(fib),
            "fibre_number":    pos_in_tube(fib),
            "fibre_role":      role,
            "joint_id":        joint,
            "bundle_id":       bundle,
            "splitter_id":     splitter,
            "splice_to_cable": sc,
            "splice_to_tube":  (tube_for_fibre(sf) if sf else None),
            "splice_to_fibre": (pos_in_tube(sf) if sf else None),
            "colour":          fibre_colour(pos_in_tube(fib)),
        })

    # FEEDER PROPAGATION: light the path from the cabinet to the first splitter
    def cable_leaving(node):
        for c in cables:
            if c["from"] == node and c["type"] != "CBT_TAIL":
                return c
        return None

    for c0 in cables:
        if c0["type"] == "CBT_TAIL":
            continue
        if c0["from"] in node_type:
            continue  # originates at a joint, not the cabinet
        cur = c0
        guard = 0
        while cur and guard < 50:
            guard += 1
            nxt_node = cur["to"]
            if nxt_node in splitters:
                break  # first splitter reached; its input cable handled by stage logic
            nxt = cable_leaving(nxt_node)
            if not nxt:
                break
            for fnum in range(1, cur["fc"] + 1):
                rec(cur["id"], fnum, "THROUGH_SPLICE", joint=nxt_node, sc=nxt["id"], sf=fnum)
            cur = nxt

    # STAGE 1: feeder splitters (1:4)
    for p, ratio in splitters.items():
        if ratio != "1:4":
            continue
        inc = feeder_of(p)
        if not inc:
            log("Warning: no feeder for " + str(p) + "; skipping")
            continue
        spid = p + "-SP"
        rec(inc["id"], 1, "SPLITTER_INPUT", joint=p, splitter=spid)
        kids = children_of(p)
        try:
            fcap = int(str(ratio).split(":")[1])
        except Exception:
            fcap = len(kids)
        fcons = [{"asset": child, "sort_key": (dist, child),
                  "port": joint_fport.get(child),
                  "status": joint_status.get(child, "PROPOSED")}
                 for (dist, child, is_cbt) in kids]
        f_occ, f_pof, f_flags = sticky_allocate(fcons, fcap)
        for fl in f_flags:
            log("  ! " + str(p) + " " + fl)
        joint_updates.setdefault(p, {}).update({"fibre_in": inc["fc"], "fibre_out": len(f_pof)})
        log("Stage-1 " + str(p) + " (" + str(ratio) + ") input " + str(inc["id"]) + " F1 -> " + str(len(f_pof)) + " ports")
        for pt in range(1, fcap + 1):
            if pt in f_occ:
                child = f_occ[pt]
                rec(spid, pt, "SPLITTER_OUTPUT", joint=p, bundle=child, splitter=spid)
                log("  PO" + str(pt) + " -> " + str(child))
                joint_updates.setdefault(child, {})["feeder_port"] = pt
        cbt_by_attach = {}
        for (dist, child, is_cbt) in kids:
            if is_cbt:
                t = tail_of(child)
                if t:
                    cbt_by_attach.setdefault(t["to"], []).append((child, t["id"]))
        for attach, items in cbt_by_attach.items():
            carry = feeder_of(attach)
            if not carry:
                continue
            for k, (child, tailid) in enumerate(items, 1):
                rec(carry["id"], k, "THROUGH_SPLICE", joint=attach, sc=tailid, sf=1)
                rec(tailid, 1, "THROUGH_SPLICE", joint=attach, sc=carry["id"], sf=k)
        for fnum in range(2, inc["fc"] + 1):
            rec(inc["id"], fnum, "DARK_STORAGE", joint=p)

    # STAGE 2: terminal splitters (1:8 and any non-1:4)
    def _terminal_consumers(splitter_id, is_cbt):
        layer = dd_layer if is_cbt else bdl_layer
        keyf  = "from_chamber" if is_cbt else "from_joint"
        idf   = "ddct_id" if is_cbt else "bundle_id"
        lname = "Drop Ducts" if is_cbt else "Bundles"
        rows = []
        if layer:
            has_port = "splitter_port" in [fld.name() for fld in layer.fields()]
            for f in layer.getFeatures():
                if S(f[keyf]) != splitter_id:
                    continue
                if is_cbt and S(f["drop_type"]) != "PIA_AERIAL_DROP":
                    continue
                pv = f["splitter_port"] if has_port else None
                rows.append({
                    "asset":    S(f[idf]),
                    "sort_key": (S(f[idf]) or ""),
                    "port":     (int(pv) if pv not in (None, NULL) else None),
                    "status":   (S(f["status"]) or "PROPOSED"),
                    "layer":    lname,
                })
        return rows

    for sp, ratio in splitters.items():
        if ratio == "1:4":
            continue
        is_cbt = node_type.get(sp) == "CBT"
        inc = tail_of(sp) if is_cbt else feeder_of(sp)
        if not inc:
            log("Warning: no input for " + str(sp) + "; skipping")
            continue
        cons = _terminal_consumers(sp, is_cbt)
        spid = sp + "-SP"
        try:
            cap = int(str(ratio).split(":")[1])
        except Exception:
            cap = 8
        occupied, port_of, flags = sticky_allocate(cons, cap)
        for fl in flags:
            log("  ! " + str(sp) + " " + fl)
        rec(inc["id"], 1, "SPLITTER_INPUT", joint=sp, splitter=spid)
        joint_updates.setdefault(sp, {}).update({"fibre_in": 1, "fibre_out": len(port_of)})
        log("Stage-2 " + str(sp) + " (" + str(ratio) + ") input " + str(inc["id"]) + " F1 -> " + str(len(port_of)) + "/" + str(cap))
        for p in range(1, cap + 1):
            if p in occupied:
                asset = occupied[p]
                rec(spid, p, "SPLITTER_OUTPUT", joint=sp, bundle=asset, splitter=spid)
                lname = next((c["layer"] for c in cons if c["asset"] == asset), None)
                if lname:
                    port_updates[(lname, asset)] = p
            else:
                rec(spid, p, "SPLITTER_OUTPUT_SPARE", joint=sp, splitter=spid)
        if not is_cbt:
            for fnum in range(2, inc["fc"] + 1):
                rec(inc["id"], fnum, "DARK_STORAGE", joint=sp)

    log("Total assignments: " + str(len(assignments)))
    return assignments, joint_updates, port_updates


def write_joint_attributes(joint_updates, log_fn=None):
    def log(msg):
        if log_fn: log_fn(msg)

    layer = get_layer("Joints")
    if not layer:
        log("Warning: Joints layer not found — skipping joint attribute update")
        return

    fields = {f.name(): i for i, f in enumerate(layer.fields())}
    layer.startEditing()
    updated = 0
    try:
        for feat in layer.getFeatures():
            jid = str(feat["joint_id"])
            if jid not in joint_updates:
                continue
            upd = joint_updates[jid]
            for field, value in upd.items():
                idx = fields.get(field)
                if idx is not None and value is not None:
                    layer.changeAttributeValue(feat.id(), idx, value)
            updated += 1
        layer.commitChanges()
        layer.triggerRepaint()
        log(f"Updated {updated} joint attribute records")
    except Exception as e:
        layer.rollBack()
        raise RuntimeError(f"write_joint_attributes failed: {e}") from e


def write_consumer_ports(port_updates, log_fn=None):
    def log(msg):
        if log_fn: log_fn(msg)
    if not port_updates:
        log("No splitter ports to persist")
        return
    by_layer = {}
    for (lyr_name, asset), port in port_updates.items():
        by_layer.setdefault(lyr_name, {})[asset] = port
    for lyr_name, mapping in by_layer.items():
        layer = get_layer(lyr_name)
        if not layer:
            log("Warning: " + lyr_name + " not found; skipping port persistence")
            continue
        idcol = "bundle_id" if lyr_name == "Bundles" else "ddct_id"
        fields = {f.name(): i for i, f in enumerate(layer.fields())}
        if "splitter_port" not in fields:
            log("Warning: " + lyr_name + " has no splitter_port field; run schema migration")
            continue
        idx = fields["splitter_port"]
        layer.startEditing()
        updated = 0
        try:
            for feat in layer.getFeatures():
                a = feat[idcol]
                a = None if a is None or a == NULL else str(a)
                if a in mapping:
                    layer.changeAttributeValue(feat.id(), idx, mapping[a])
                    updated += 1
            layer.commitChanges()
            log("Persisted " + str(updated) + " splitter ports to " + lyr_name)
        except Exception as e:
            layer.rollBack()
            raise RuntimeError("write_consumer_ports failed for " + lyr_name + ": " + str(e)) from e


def write_assignments(assignments, log_fn=None):
    def log(msg):
        if log_fn: log_fn(msg)
    layer = get_layer("Fibre Assignments")
    if not layer:
        raise RuntimeError("Fibre Assignments layer not found")
    # Clear existing
    layer.startEditing()
    try:
        layer.selectAll()
        layer.deleteSelectedFeatures()
        layer.commitChanges()
        log("Cleared existing assignments")
    except Exception as e:
        layer.rollBack()
        raise RuntimeError(f"Failed to clear existing assignments: {e}") from e
    # Write new
    layer.startEditing()
    try:
        fields = layer.fields()
        added  = 0
        for a in assignments:
            feat = QgsFeature(fields)
            feat["assign_id"]       = a["assign_id"]
            feat["cable_id"]        = a["cable_id"]
            feat["tube_number"]     = a["tube_number"]
            feat["fibre_number"]    = a["fibre_number"]
            feat["fibre_role"]      = a["fibre_role"]
            feat["joint_id"]        = a["joint_id"]        or NULL
            feat["bundle_id"]       = a["bundle_id"]       or NULL
            feat["splitter_id"]     = a["splitter_id"]     or NULL
            feat["splice_to_cable"] = a["splice_to_cable"] or NULL
            feat["splice_to_tube"]  = a["splice_to_tube"]  or NULL
            feat["splice_to_fibre"] = a["splice_to_fibre"] or NULL
            feat["notes"]           = a["colour"]
            layer.addFeature(feat)
            added += 1
        layer.commitChanges()
        log(f"Written {added} assignment records")
        return added
    except Exception as e:
        layer.rollBack()
        raise RuntimeError(f"Failed to write assignments: {e}") from e


class AssignWorker(QThread):
    log      = pyqtSignal(str)
    finished = pyqtSignal(list, dict, dict, str)

    def __init__(self):
        super().__init__()
        self._project_ref = None

    def run(self):
        try:
            if self._project_ref:
                _PROJECT_REF[0] = self._project_ref
            assignments, joint_updates, port_updates = assign_fibres(log_fn=lambda m: self.log.emit(m))
            self.finished.emit(assignments, joint_updates, port_updates, "")
        except Exception:
            self.finished.emit([], {}, {}, traceback.format_exc())


class FibreAssignDialog(QDialog):
    def __init__(self, iface, parent=None, project=None):
        super().__init__(parent)
        self.iface = iface
        self._project = project
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Conductor - Auto-Assign Fibres")
        self.setMinimumSize(600, 440)
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        header = QLabel("Auto-Assign Fibres")
        header.setStyleSheet("font-size:15px; font-weight:600; color:#E8EDF2;")
        root.addWidget(header)

        sub = QLabel("Walks the network from cabinet outward, assigning tube and fibre numbers. "
                     "Handles underground splitters, through-splices, and aerial drops.\n\n"
                     "Splitter fibre usage: F1 = input, F2 onwards = port outputs. "
                     "A 1:4 uses 5 fibres (F1–F5); a 1:8 uses 9 fibres (F1–F9). "
                     "Onward splices begin at the next fibre after the last port.")
        sub.setWordWrap(True)
        sub.setStyleSheet("font-size:11px; color:#8B9AAB; margin-bottom:4px;")
        root.addWidget(sub)

        warn = QFrame()
        warn.setStyleSheet("QFrame { background:#FFF4E6; border-left:3px solid #C85A00; "
                           "border-radius:0 4px 4px 0; padding:6px 10px; }")
        wl = QLabel("Warning: This will overwrite any existing fibre assignments. "
                    "Run validation first to confirm the network topology is clean.")
        wl.setWordWrap(True)
        wl.setStyleSheet("font-size:11px; color:#7A3D04;")
        QVBoxLayout(warn).addWidget(wl)
        root.addWidget(warn)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setStyleSheet("QTextEdit { background:#0D1117; color:#58D68D; "
                                "border:1px solid #333; border-radius:4px; padding:6px; }")
        root.addWidget(self._log)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        self._progress.setStyleSheet("QProgressBar { border:1px solid #2D3F52; border-radius:3px; background:#0F1923; color:#E8EDF2; height:16px; } "
                                     "QProgressBar::chunk { background:#2c7a4b; }")
        root.addWidget(self._progress)

        btn_row = QHBoxLayout()
        self._btn_run = QPushButton("Run Auto-Assignment")
        self._btn_run.setStyleSheet(
            "QPushButton { background:#00C9B1; color:#0F1923; font-weight:600; padding:7px 18px; "
            "border-radius:4px; font-size:12px; } "
            "QPushButton:hover { background:#1D7A6E; } "
            "QPushButton:disabled { background:#aaa; }"
        )
        self._btn_run.clicked.connect(self._run)
        btn_close = QPushButton("Close")
        btn_close.setStyleSheet("QPushButton { padding:7px 14px; border-radius:4px; background:#1A2332; color:#E8EDF2; "
                                "font-size:12px; border:1px solid #2D3F52; } "
                                "QPushButton:hover { background:#e8e8e8; }")
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(self._btn_run)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _run(self):
        self._log.clear()
        self._btn_run.setEnabled(False)
        self._progress.setVisible(True)
        self._worker = AssignWorker()
        self._worker._project_ref = self._project
        self._worker.log.connect(self._log.append)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_finished(self, assignments, joint_updates, port_updates, error):
        self._progress.setVisible(False)
        self._btn_run.setEnabled(True)
        if error:
            self._log.append("ERROR: " + error)
            return
        try:
            count = write_assignments(assignments, log_fn=self._log.append)
            write_joint_attributes(joint_updates, log_fn=self._log.append)
            write_consumer_ports(port_updates, log_fn=self._log.append)
            self._log.append(f"Done - {count} fibre assignments written.")
        except Exception:
            self._log.append("Write error: " + traceback.format_exc())

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.wait()
        super().closeEvent(event)


def open_fibre_assign_dialog(iface, parent=None, project=None):
    dlg = FibreAssignDialog(iface, parent, project=project)
    dlg.show()
    return dlg
