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

    # Find all cabinets (cables whose from_node_type = POP)
    cabinets = []
    for feat in cable_layer.getFeatures():
        if val(feat["from_node_type"]) == "POP":
            cab = str(feat["from_node"])
            if cab not in cabinets:
                cabinets.append(cab)

    return cables, joints, bundles, cbt_drops, from_node, cabinets


def assign_fibres(log_fn=None):
    def log(msg):
        if log_fn: log_fn(msg)

    cables, joints, bundles, cbt_drops, from_node, cabinets = build_graph()
    if not cabinets:
        raise RuntimeError("Could not find cabinet — check that a cable exists with from_node_type = POP")

    log(f"Starting from {len(cabinets)} cabinet(s): " + ", ".join(cabinets))
    assignments   = []
    joint_updates = {}
    counter = [1]

    def next_id():
        aid = counter[0]; counter[0] += 1; return aid

    def make_assign(cable_id, fibre_abs, role, joint_id=None,
                    bundle_id=None, splice_to_cable=None,
                    splice_to_fibre=None, splitter_id=None):
        tube = tube_for_fibre(fibre_abs)
        fib  = pos_in_tube(fibre_abs)
        st   = tube_for_fibre(splice_to_fibre) if splice_to_fibre else None
        assignments.append({
            "assign_id":       "ASN-" + str(next_id()).zfill(4),
            "cable_id":        cable_id,
            "tube_number":     tube,
            "fibre_number":    fib,
            "fibre_role":      role,
            "splitter_id":     splitter_id,
            "splice_to_cable": splice_to_cable,
            "splice_to_tube":  st,
            "splice_to_fibre": splice_to_fibre,
            "joint_id":        joint_id,
            "bundle_id":       bundle_id,
            "colour":          fibre_colour(fib),
        })

    # BFS traversal: queue items are (node_id, in_cable_id, next_fibre)
    # Seed with all cabinets so multi-cabinet projects are fully assigned
    queue   = [(cab, None, 1) for cab in cabinets]
    visited = set()

    while queue:
        node_id, in_cable_id, next_fibre = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)

        outbound = from_node.get(node_id, [])

        if not outbound:
            # End of line — assign local drops first, then dark storage
            fibre_cursor = next_fibre

            # Aerial drops at this CBT
            local_drops_eol = cbt_drops.get(node_id, [])
            if local_drops_eol and in_cable_id:
                for drop in local_drops_eol:
                    drop_id = str(fld(drop, "ddct_id") or "")
                    make_assign(in_cable_id, fibre_cursor, "AERIAL_DROP",
                                joint_id=node_id, bundle_id=drop_id)
                    log(f"  Aerial drop -> {drop_id} T{tube_for_fibre(fibre_cursor)} "
                        f"F{pos_in_tube(fibre_cursor)} ({fibre_colour(pos_in_tube(fibre_cursor))})")
                    fibre_cursor += 1

            # Underground bundles at end of line
            local_bundles_eol = bundles.get(node_id, [])
            if local_bundles_eol and in_cable_id:
                for bun in local_bundles_eol:
                    bun_id = str(fld(bun, "bundle_id") or "")
                    make_assign(in_cable_id, fibre_cursor, "BUNDLE_DROP",
                                joint_id=node_id, bundle_id=bun_id)
                    log(f"  Bundle drop -> {bun_id} T{tube_for_fibre(fibre_cursor)} "
                        f"F{pos_in_tube(fibre_cursor)} ({fibre_colour(pos_in_tube(fibre_cursor))})")
                    fibre_cursor += 1

            # Remaining fibres dark storage
            if in_cable_id:
                in_cable = cables[in_cable_id]
                total_f  = int(fld(in_cable, "fibre_count") or 48)
                remaining = total_f - fibre_cursor + 1
                for f in range(fibre_cursor, total_f + 1):
                    make_assign(in_cable_id, f, "DARK_STORAGE", joint_id=node_id)
                if remaining > 0:
                    log(f"  END OF LINE at {node_id} — {remaining} fibres dark storage")
            continue

        joint        = joints.get(node_id)
        has_splitter = bool(fld(joint, "has_splitter", False)) if joint else False
        split_ratio  = fld(joint, "split_ratio")               if joint else None
        joint_type   = str(fld(joint, "joint_type") or "")     if joint else ""

        local_bundles = bundles.get(node_id, [])
        local_drops   = cbt_drops.get(node_id, [])
        n_local       = len(local_bundles) + len(local_drops)

        log(f"Node: {node_id}  type:{joint_type}  splitter:{has_splitter}"
            + (f"  {split_ratio}" if split_ratio else "")
            + f"  local_drops:{n_local}  outbound:{len(outbound)}")

        if node_id in joints:
            in_cable  = cables.get(in_cable_id) if in_cable_id else None
            total_in  = int(fld(in_cable, "fibre_count") or 48) if in_cable else 0
            total_out = sum(int(fld(c, "fibre_count") or 48) for c in outbound)
            joint_updates[node_id] = {
                "fibre_in":  total_in,
                "fibre_out": total_out + n_local,
            }

        fibre_cursor = next_fibre
        splitter_id  = None

        # ── SPLITTER ─────────────────────────────────────────────────────────
        if has_splitter and split_ratio and in_cable_id:
            splitter_id = node_id + "-SP"
            make_assign(in_cable_id, fibre_cursor, "SPLITTER_INPUT",
                        joint_id=node_id, splitter_id=splitter_id)
            log(f"  Splitter {split_ratio} input T{tube_for_fibre(fibre_cursor)} "
                f"F{pos_in_tube(fibre_cursor)} ({fibre_colour(pos_in_tube(fibre_cursor))})")
            fibre_cursor += 1

            joint_bundles = local_bundles
            try:
                n_outputs = int(split_ratio.split(":")[1])
            except Exception:
                n_outputs = 8

            for port_idx in range(n_outputs):
                port_label = "PO" + str(port_idx + 1)
                if port_idx < len(joint_bundles):
                    bun    = joint_bundles[port_idx]
                    bun_id = str(bun["bundle_id"])
                    make_assign(in_cable_id, fibre_cursor, "SPLITTER_OUTPUT",
                                joint_id=node_id, bundle_id=bun_id, splitter_id=splitter_id)
                    log(f"    {port_label} -> {bun_id} T{tube_for_fibre(fibre_cursor)} "
                        f"F{pos_in_tube(fibre_cursor)} ({fibre_colour(pos_in_tube(fibre_cursor))})")
                else:
                    make_assign(in_cable_id, fibre_cursor, "SPLITTER_OUTPUT_SPARE",
                                joint_id=node_id, splitter_id=splitter_id)
                    log(f"    {port_label} -> spare")
                fibre_cursor += 1

        # ── AERIAL DROPS at intermediate CBT ────────────────────────────────
        # CBT joints with outbound cables consume fibres for their drops BEFORE splicing onward
        elif local_drops and in_cable_id and not has_splitter:
            for drop in local_drops:
                drop_id = str(fld(drop, "ddct_id") or "")
                make_assign(in_cable_id, fibre_cursor, "AERIAL_DROP",
                            joint_id=node_id, bundle_id=drop_id)
                log(f"  Aerial drop -> {drop_id} T{tube_for_fibre(fibre_cursor)} "
                    f"F{pos_in_tube(fibre_cursor)} ({fibre_colour(pos_in_tube(fibre_cursor))})")
                fibre_cursor += 1

        # ── UNDERGROUND BUNDLES (non-splitter) ───────────────────────────────
        elif local_bundles and in_cable_id and not has_splitter:
            for bun in local_bundles:
                bun_id = str(fld(bun, "bundle_id") or "")
                make_assign(in_cable_id, fibre_cursor, "BUNDLE_DROP",
                            joint_id=node_id, bundle_id=bun_id)
                log(f"  Bundle drop -> {bun_id} T{tube_for_fibre(fibre_cursor)} "
                    f"F{pos_in_tube(fibre_cursor)} ({fibre_colour(pos_in_tube(fibre_cursor))})")
                fibre_cursor += 1

        # ── ONWARD SPLICES ────────────────────────────────────────────────────
        max_out_fibres = 0
        for out_cable in outbound:
            out_id    = str(fld(out_cable, "cable_id", "UNKNOWN"))
            total_out = int(fld(out_cable, "fibre_count") or 48)
            if total_out > max_out_fibres:
                max_out_fibres = total_out
            slice_start = fibre_cursor
            log(f"  Splice -> {out_id} ({total_out}F) from F{slice_start}")

            for f in range(total_out):
                in_f  = slice_start + f
                out_f = 1 + f
                if in_cable_id:
                    in_cable = cables[in_cable_id]
                    total_in = int(fld(in_cable, "fibre_count") or 48)
                    if in_f > total_in:
                        make_assign(out_id, out_f, "DARK_STORAGE", joint_id=node_id)
                        continue
                    make_assign(in_cable_id, in_f, "THROUGH_SPLICE",
                                joint_id=node_id,
                                splice_to_cable=out_id, splice_to_fibre=out_f)
                make_assign(out_id, out_f, "THROUGH_SPLICE",
                            joint_id=node_id,
                            splice_to_cable=in_cable_id,
                            splice_to_fibre=in_f if in_cable_id else None)

            to_node = fld(out_cable, "to_node")
            if to_node:
                queue.append((str(to_node), out_id, 1))

        fibre_cursor += max_out_fibres

        # Mark remaining in-cable fibres as dark storage
        if in_cable_id:
            in_cable = cables[in_cable_id]
            total_in = int(fld(in_cable, "fibre_count") or 48)
            if fibre_cursor <= total_in:
                for f in range(fibre_cursor, total_in + 1):
                    make_assign(in_cable_id, f, "DARK_STORAGE", joint_id=node_id)
                log(f"  {total_in - fibre_cursor + 1} fibres -> dark storage on {in_cable_id}")

    log(f"Total assignments: {len(assignments)}")
    return assignments, joint_updates


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
    finished = pyqtSignal(list, dict, str)

    def __init__(self):
        super().__init__()
        self._project_ref = None

    def run(self):
        try:
            if self._project_ref:
                _PROJECT_REF[0] = self._project_ref
            assignments, joint_updates = assign_fibres(log_fn=lambda m: self.log.emit(m))
            self.finished.emit(assignments, joint_updates, "")
        except Exception:
            self.finished.emit([], {}, traceback.format_exc())


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
        header.setStyleSheet("font-size:15px; font-weight:600; color:#1A3A5C;")
        root.addWidget(header)

        sub = QLabel("Walks the network from cabinet outward, assigning tube and fibre numbers. "
                     "Handles underground splitters, through-splices, and aerial drops.")
        sub.setWordWrap(True)
        sub.setStyleSheet("font-size:11px; color:#555; margin-bottom:4px;")
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
        self._progress.setStyleSheet("QProgressBar { border:1px solid #ccc; border-radius:3px; height:16px; } "
                                     "QProgressBar::chunk { background:#2c7a4b; }")
        root.addWidget(self._progress)

        btn_row = QHBoxLayout()
        self._btn_run = QPushButton("Run Auto-Assignment")
        self._btn_run.setStyleSheet(
            "QPushButton { background:#1A3A5C; color:#fff; font-weight:600; padding:7px 18px; "
            "border-radius:4px; font-size:12px; } "
            "QPushButton:hover { background:#1D7A6E; } "
            "QPushButton:disabled { background:#aaa; }"
        )
        self._btn_run.clicked.connect(self._run)
        btn_close = QPushButton("Close")
        btn_close.setStyleSheet("QPushButton { padding:7px 14px; border-radius:4px; "
                                "font-size:12px; border:1px solid #bbb; } "
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

    def _on_finished(self, assignments, joint_updates, error):
        self._progress.setVisible(False)
        self._btn_run.setEnabled(True)
        if error:
            self._log.append("ERROR: " + error)
            return
        try:
            count = write_assignments(assignments, log_fn=self._log.append)
            write_joint_attributes(joint_updates, log_fn=self._log.append)
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
