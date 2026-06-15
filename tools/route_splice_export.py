# -*- coding: utf-8 -*-
"""
route_splice_export.py  —  Conductor FTTP Network Design Plugin
Route Splice Export: click a premises OR a joint on the map, traces the full
route back to the cabinet, and exports a single self-contained HTML document
covering every joint's splice schedule in route order — with per-drop fibre
detail tables showing tube, fibre colour, drop ID and address.
Sandboxed tool — no changes to splice_plan.py or fibre_trace.py.
"""

import os
import webbrowser
from collections import defaultdict, deque

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QFileDialog, QMessageBox, QSizePolicy
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QCursor

from qgis.core import (
    QgsProject, QgsFeatureRequest, QgsRectangle,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem, NULL
)
from qgis.gui import QgsMapTool

from ..conductor_utils import get_layer, val, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID
from ..conductor_utils import safe_write_text

from .splice_plan import (
    get_assignments_for_joint, get_joint_info,
    IEC_COLOURS, IEC_HEX, IEC_BORDER, TUBE_COLOURS,
    fibre_colour_name, fibre_hex, fibre_border, tube_css,
    fd, tube_pill, splice_link, short_cable
)

from .validate_routes import _build_index, _build_cable_node_index, trace_premises

SNAP_RADIUS_PX = 18


# ── Network helpers ───────────────────────────────────────────────────────────

def _all_joints_on_route(path):
    joints = [h for h in path if "JNT-" in str(h) or "CBT-" in str(h)]
    return list(reversed(joints))


def _find_joint_route(start_joint_id, cable_layer, joint_layer):
    if not cable_layer or not joint_layer:
        return [], "Layer not found"

    adjacency = defaultdict(list)
    for feat in cable_layer.getFeatures():
        fn = str(feat["from_node"]) if feat["from_node"] and feat["from_node"] != NULL else ""
        tn = str(feat["to_node"])   if feat["to_node"]   and feat["to_node"]   != NULL else ""
        if fn and tn:
            adjacency[fn].append((str(feat["cable_id"]), tn))
            adjacency[tn].append((str(feat["cable_id"]), fn))

    visited = {start_joint_id}
    queue   = deque([(start_joint_id, [start_joint_id])])
    while queue:
        node, path = queue.popleft()
        if "CAB" in node.upper() or "POP" in node.upper():
            rev    = list(reversed(path))
            joints = [n for n in rev if "JNT-" in n or "CBT-" in n]
            return joints, f"Route found — {len(joints)} joints"
        for cable_id, neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [cable_id, neighbor]))

    return [], f"Could not find cabinet from {start_joint_id}"


def _trace_from_premises(uprn, area_id, project):
    bundle_layer   = get_layer("bundles",    project)
    ddct_layer     = get_layer("drop_ducts", project)
    joint_layer    = get_layer("joints",     project)
    cable_layer    = get_layer("cables",     project)

    bundle_idx     = _build_index(bundle_layer, "uprn")     if bundle_layer else {}
    ddct_idx       = _build_index(ddct_layer,   "uprn")     if ddct_layer   else {}
    joint_idx      = _build_index(joint_layer,  "joint_id") if joint_layer  else {}
    cable_node_idx = _build_cable_node_index(cable_layer)   if cable_layer  else {}

    status, path, reason, _loss_db = trace_premises(
        uprn, area_id, bundle_idx, ddct_idx, joint_idx, cable_node_idx
    )
    joints = _all_joints_on_route(path)
    return status, joints, reason, path


# ── Address lookup ────────────────────────────────────────────────────────────

def _build_address_index(project):
    """Build UPRN → address string lookup from premises layer."""
    idx = {}
    layer = get_layer("premises", project)
    if not layer:
        return idx
    for feat in layer.getFeatures():
        uprn = feat["uprn"]
        if uprn and uprn != NULL:
            a1 = str(feat["address_1"] or "") if "address_1" in [f.name() for f in feat.fields()] else ""
            a2 = str(feat["address_2"] or "") if "address_2" in [f.name() for f in feat.fields()] else ""
            pc = str(feat["postcode"]   or "") if "postcode"  in [f.name() for f in feat.fields()] else ""
            addr = ", ".join(p for p in [a1, a2, pc] if p) or str(uprn)
            idx[str(uprn)] = addr
    return idx


def _build_drop_uprn_index(project):
    """Build drop_id/bundle_id → UPRN lookup from bundles and drop_ducts."""
    idx = {}
    bundle_layer = get_layer("bundles",    project)
    ddct_layer   = get_layer("drop_ducts", project)

    if bundle_layer:
        for feat in bundle_layer.getFeatures():
            bid  = val(feat["bundle_id"])
            uprn = feat["uprn"]
            if bid and uprn and uprn != NULL:
                idx[str(bid)] = str(uprn)

    if ddct_layer:
        for feat in ddct_layer.getFeatures():
            did  = val(feat["ddct_id"])
            uprn = feat["uprn"]
            if did and uprn and uprn != NULL:
                idx[str(did)] = str(uprn)

    return idx


# ── Cable info lookup ─────────────────────────────────────────────────────────

def _build_cable_info_index(project):
    """Build cable_id → {fibre_count, cable_type, from_node, to_node, length_m} lookup."""
    idx = {}
    layer = get_layer("cables", project)
    if not layer:
        return idx
    for feat in layer.getFeatures():
        cid = val(feat["cable_id"])
        if cid:
            idx[cid] = {
                "fibre_count": val(feat["fibre_count"]) or 0,
                "cable_type":  val(feat["cable_type"])  or "",
                "from_node":   val(feat["from_node"])   or "",
                "to_node":     val(feat["to_node"])     or "",
                "length_m":    val(feat["length_m"])    or "",
            }
    return idx


# ── HTML generation ───────────────────────────────────────────────────────────

CSS = """
:root{--navy:#1A3A5C;--teal:#1D7A6E;--mid:#CBD5E1;--bg:#F4F6F9;--gray:#5F5E5A;--gray-light:#F1EFE8;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Courier New',Courier,monospace;background:var(--bg);color:#1A1A1A;font-size:12px;line-height:1.4;}
.page{max-width:960px;margin:0 auto;padding:20px;}
.route-header{background:var(--navy);color:white;border-radius:10px;padding:14px 18px;margin-bottom:18px;}
.route-title{font-size:16px;font-weight:bold;}
.route-sub{font-size:10px;color:#9FB4CC;margin-top:3px;}
.route-strip{display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.15);}
.rnode{padding:3px 8px;border-radius:4px;font-size:10px;font-weight:bold;white-space:nowrap;background:rgba(255,255,255,0.12);color:white;}
.rnode.cab{background:#16A34A;}.rnode.prem{background:#DC2626;}
.rarrow{color:#9FB4CC;font-size:12px;}
.legend{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px;padding:8px 12px;background:white;border-radius:6px;border:1px solid var(--mid);}
.leg-item{display:flex;align-items:center;gap:4px;font-size:9px;color:#555;}
.leg-dot{width:10px;height:10px;border-radius:50%;}
.joint-card{background:white;border-radius:8px;border:1px solid var(--mid);overflow:hidden;margin-bottom:0;}
.joint-card.cbt-card{border-color:var(--teal);border-width:1.5px;}
.joint-card.branch-card{border-color:#F97316;border-width:1.5px;}
.joint-head{display:flex;align-items:center;}
.joint-icon{width:64px;min-width:64px;height:56px;display:flex;flex-direction:column;align-items:center;justify-content:center;background:var(--navy);color:white;font-size:9px;gap:2px;}
.joint-icon.cbt{background:var(--teal);}.joint-icon.branch{background:#7A3D04;}
.joint-icon-dot{width:20px;height:20px;border-radius:50%;border:2px solid white;display:flex;align-items:center;justify-content:center;font-size:8px;font-weight:bold;}
.joint-info{padding:6px 10px;flex:1;}
.joint-id{font-size:12px;font-weight:bold;color:var(--navy);}
.joint-meta{font-size:9px;color:#888;margin-top:1px;}
.joint-hop{font-size:9px;background:var(--bg);border:1px solid var(--mid);border-radius:3px;padding:2px 6px;color:var(--gray);white-space:nowrap;margin-right:10px;}
.cables-row{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid #F0F0F0;}
.cable-in{padding:6px 10px;border-right:1px solid #F0F0F0;}
.cable-out{padding:6px 10px;}
.cable-label{font-size:9px;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;}
.cable-id{font-size:11px;font-weight:bold;color:var(--navy);}
.cable-fibres{margin-top:3px;display:flex;gap:2px;flex-wrap:wrap;}
.fibre-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;}
.summary-bar{padding:5px 10px;border-top:1px solid #F0F0F0;display:flex;align-items:center;gap:8px;background:#FAFBFC;flex-wrap:wrap;}
.chip{font-size:9px;padding:2px 6px;border-radius:3px;font-weight:bold;}
.chip-splice{background:#E3EEFA;color:#0D3D6E;}
.chip-drop{background:#DFF5E8;color:#0B4A26;}
.chip-dark{background:#F1EFE8;color:#444441;}
.chip-pass{background:#FEF0DC;color:#7A3D04;}
.fibre-bar{display:flex;height:6px;border-radius:3px;overflow:hidden;flex:1;min-width:80px;}
.fb-s{background:#3B82F6;}.fb-d{background:#22C55E;}.fb-k{background:var(--mid);}.fb-p{background:#F97316;}
.drops-section{border-top:1px solid #E8F5E9;}
.drops-head{padding:4px 10px;background:#E8F5E9;font-size:9px;font-weight:bold;color:#0B4A26;text-transform:uppercase;letter-spacing:0.5px;}
table.dt{width:100%;border-collapse:collapse;}
table.dt th{font-size:9px;color:#0B4A26;padding:3px 8px;text-align:left;font-weight:bold;background:#F0FBF4;border-bottom:1px solid #C0DDC7;}
table.dt td{padding:4px 8px;font-size:10px;border-bottom:0.5px solid #F0F0F0;vertical-align:middle;}
table.dt tr:last-child td{border-bottom:none;}
.tp{display:inline-block;font-size:9px;font-weight:bold;padding:1px 5px;border-radius:3px;}
.t1{background:#E3EEFA;color:#0D3D6E;}.t2{background:#FEF0DC;color:#7A3D04;}.t3{background:#DFF5E8;color:#0B4A26;}.t4{background:#F5E6D8;color:#4A2009;}
.fc{display:flex;align-items:center;gap:5px;}
.did{font-family:'Courier New',monospace;font-size:10px;color:var(--navy);font-weight:bold;}
.dtype{font-size:9px;padding:1px 5px;border-radius:3px;}
.dtype-b{background:#DFF5E8;color:#0B4A26;}
.dtype-a{background:#E1F5EE;color:#085041;}
.conn-wrap{display:flex;align-items:stretch;height:36px;}
.conn-col{display:flex;flex-direction:column;align-items:center;width:64px;min-width:64px;}
.conn-line{width:2px;flex:1;}
.conn-line.ug{background:#1A3A5C;}
.conn-line.aerial{background:repeating-linear-gradient(to bottom,#1D7A6E 0px,#1D7A6E 4px,transparent 4px,transparent 8px);}
.conn-line.drop{background:repeating-linear-gradient(to bottom,#DC2626 0px,#DC2626 4px,transparent 4px,transparent 8px);}
.conn-arrow{width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;}
.conn-arrow.ug{border-top:8px solid #1A3A5C;}
.conn-arrow.aerial{border-top:8px solid #1D7A6E;}
.conn-arrow.drop{border-top:8px solid #DC2626;}
.conn-info{flex:1;display:flex;align-items:center;padding-left:8px;}
.conn-lbl{font-size:9px;padding:2px 6px;border-radius:3px;border:1px solid #E2E8F0;background:var(--bg);color:#888;white-space:nowrap;}
.conn-lbl.aerial{border-color:#9FE1CB;color:#0F6E56;background:#E1F5EE;}
.conn-lbl.drop{border-color:#FCA5A5;color:#DC2626;background:#FCEBEB;}
.branch-stub{position:absolute;left:32px;top:18px;display:flex;align-items:center;pointer-events:none;}
.prem-card{background:white;border-radius:8px;border:2px solid #DC2626;padding:10px 14px;display:flex;align-items:center;gap:10px;}
.prem-dot{width:28px;height:28px;border-radius:50%;background:#DC2626;color:white;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0;}
.prem-addr{font-size:12px;font-weight:bold;color:var(--navy);}
.prem-uprn{font-size:9px;color:#888;}
.footer{margin-top:16px;padding-top:10px;border-top:1px solid var(--mid);display:flex;justify-content:space-between;font-size:10px;color:var(--gray);}
@media print{body{background:white;}.page{padding:8px;}.joint-card{break-inside:avoid;page-break-after:auto;}.route-header{break-inside:avoid;}}
"""

def _tube_pill_html(t):
    classes = {1:"t1",2:"t2",3:"t3",4:"t4"}
    return f'<span class="tp {classes.get(t,"t1")}">T{t}</span>'

def _fibre_dot_html(f_abs):
    hex_c  = IEC_HEX[(f_abs-1)%12]
    border = IEC_BORDER[(f_abs-1)%12]
    bstyle = f'border:1px solid {border};' if border else ''
    return f'<div class="fibre-dot" style="background:{hex_c};{bstyle}"></div>'

def _fibre_cell_html(tube, fibre):
    f_abs  = (tube-1)*12 + fibre
    hex_c  = IEC_HEX[(f_abs-1)%12]
    border = IEC_BORDER[(f_abs-1)%12]
    bstyle = f'border:1px solid {border};' if border else ''
    name   = IEC_COLOURS[(f_abs-1)%12]
    return (f'<div class="fc">'
            f'<div class="fibre-dot" style="background:{hex_c};{bstyle}"></div>'
            f'F{fibre} {name}'
            f'</div>')


def _generate_route_html(joints_in_order, route_label, output_path, project=None,
                         cable_path=None):
    if not joints_in_order:
        raise RuntimeError("No joints found on route.")

    # Pre-build lookup indexes
    address_idx  = _build_address_index(project)
    drop_uprn    = _build_drop_uprn_index(project)
    cable_info   = _build_cable_info_index(project)

    # Build ordered cable list between joints from the BFS path
    # cable_path is the raw BFS path [joint, cable, joint, cable, ..., CAB]
    # We extract (cable_id, from_joint, to_joint) tuples in route order
    cable_segments = []  # list of (cable_id, is_aerial)
    if cable_path:
        nodes = cable_path
        for i in range(0, len(nodes)-1, 2):
            if i+1 < len(nodes):
                cid = str(nodes[i+1]) if i+1 < len(nodes) else ""
                if cid and "CBL-" in cid:
                    info = cable_info.get(cid, {})
                    is_aerial = str(info.get("cable_type","")).upper() in ("AERIAL","PIA_AERIAL")
                    cable_segments.append((cid, is_aerial, info))
    # Reverse to match joints_in_order (cabinet outward)
    cable_segments = list(reversed(cable_segments))

    H = []
    H.append('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">')
    H.append(f'<title>{route_label} · Route Splice Plan</title>')
    H.append(f'<style>{CSS}</style>')
    H.append('</head><body><div class="page">')

    # Route header
    H.append('<div class="route-header">')
    H.append(f'<div class="route-title">Route Splice Plan</div>')
    H.append(f'<div class="route-sub">{route_label} &middot; {len(joints_in_order)} joint{"s" if len(joints_in_order)!=1 else ""} &middot; Gigaloch &middot; Exported from Conductor</div>')
    H.append('<div class="route-strip">')
    H.append('<div class="rnode cab">CAB</div>')
    for jid in joints_in_order:
        short = jid.split('-')[-1]
        H.append(f'<div class="rarrow">→</div><div class="rnode">{short}</div>')
    H.append('<div class="rarrow">→</div><div class="rnode prem">PREM</div>')
    H.append('</div></div>')

    # Legend
    H.append('<div class="legend">')
    for colour, label in [("#3B82F6","Through splice"),("#22C55E","Active drop"),
                          ("#CBD5E1","Dark / spare"),("#F97316","Pass-through / branch")]:
        H.append(f'<div class="leg-item"><div class="leg-dot" style="background:{colour};"></div>{label}</div>')
    H.append('<div class="leg-item"><div style="width:20px;height:2px;background:#1A3A5C;display:inline-block;"></div> UG route</div>')
    H.append('<div class="leg-item"><div style="width:20px;border-top:2px dashed #1D7A6E;display:inline-block;"></div> Aerial route</div>')
    H.append('</div>')

    # One section per joint
    for hop_idx, joint_id in enumerate(joints_in_order):
        info        = get_joint_info(joint_id, project=project)
        assignments = get_assignments_for_joint(joint_id, project=project)

        jtype   = str(info.get('joint_type','SPLICE') or 'SPLICE')
        closure = str(info.get('closure_type','FDC')  or 'FDC')
        pop_id  = str(info.get('pop_id','')   or '')
        chamber = str(info.get('chamber_id','') or '')
        split_r = str(info.get('split_ratio','') or '')
        is_cbt  = 'CBT' in joint_id

        splices    = [a for a in assignments if a['fibre_role'] == 'THROUGH_SPLICE' and a['cable_id']]
        sp_inputs  = [a for a in assignments if a['fibre_role'] == 'SPLITTER_INPUT']
        sp_outputs = [a for a in assignments if a['fibre_role'] in ('SPLITTER_OUTPUT','SPLITTER_OUTPUT_SPARE')]
        drops      = [a for a in assignments if a['fibre_role'] in ('AERIAL_DROP','BUNDLE_DROP')]
        dark       = [a for a in assignments if a['fibre_role'] == 'DARK_STORAGE']
        pass_thru  = [a for a in assignments if a['fibre_role'] == 'PASS_THROUGH']

        seen = set()
        unique_splices = []
        for a in [x for x in splices if x['splice_to_cable'] and x['splice_to_fibre']]:
            key = tuple(sorted([(a['cable_id'],a['tube_number'],a['fibre_number']),
                                (a['splice_to_cable'],a['splice_to_tube'],a['splice_to_fibre'])]))
            if key not in seen:
                seen.add(key)
                unique_splices.append(a)

        n_drop    = len(drops)
        n_pass    = len(pass_thru)
        n_dark    = len(dark)
        total_f   = 0
        all_cables = set(a['cable_id'] for a in assignments if a['cable_id'])
        cl = get_layer('Cables', project)
        if cl:
            for feat in cl.getFeatures():
                if val(feat['cable_id']) in all_cables:
                    fc = val(feat['fibre_count'])
                    if fc and int(fc) > total_f:
                        total_f = int(fc)
        # Cap splice count to total fibres on cable to avoid double-counting
        # at CBT joints where both cable ends appear in assignments
        n_splices = min(len(unique_splices), total_f) if total_f else len(unique_splices)

        # Work out cable in and cable out for this hop
        seg_in  = cable_segments[hop_idx-1] if hop_idx > 0 and hop_idx-1 < len(cable_segments) else None
        seg_out = cable_segments[hop_idx]   if hop_idx < len(cable_segments) else None

        card_class = "joint-card" + (" cbt-card" if is_cbt else "")
        H.append(f'<div class="{card_class}">')

        # Joint header
        icon_class = "joint-icon cbt" if is_cbt else "joint-icon"
        icon_letter = "C" if is_cbt else "J"
        icon_label  = "AERIAL" if is_cbt else "UG"
        H.append(f'<div class="joint-head">')
        H.append(f'<div class="{icon_class}"><div class="joint-icon-dot">{icon_letter}</div><div>{icon_label}</div></div>')
        H.append(f'<div class="joint-info"><div class="joint-id">{joint_id}</div>')
        meta_parts = [p for p in [closure, chamber, pop_id] if p]
        H.append(f'<div class="joint-meta">{" &middot; ".join(meta_parts)}</div></div>')
        H.append(f'<div class="joint-hop">Hop {hop_idx+1} of {len(joints_in_order)}</div>')
        H.append('</div>')

        # Cables row
        H.append('<div class="cables-row">')
        # Cable in
        H.append('<div class="cable-in"><div class="cable-label">Cable in</div>')
        if seg_in:
            cid, _, cinfo = seg_in
            H.append(f'<div class="cable-id">{short_cable(cid)} ({cinfo.get("fibre_count","")}F {cinfo.get("cable_type","")})</div>')
        elif hop_idx == 0:
            H.append('<div class="cable-id">From cabinet</div>')
        H.append('</div>')
        # Cable out
        H.append('<div class="cable-out"><div class="cable-label">Cable out</div>')
        if seg_out:
            cid, _, cinfo = seg_out
            if n_drop and not seg_out:
                H.append(f'<div class="cable-id">{n_drop} × drops</div>')
            else:
                H.append(f'<div class="cable-id">{short_cable(cid)} ({cinfo.get("fibre_count","")}F {cinfo.get("cable_type","")})</div>')
        elif n_drop:
            H.append(f'<div class="cable-id">{n_drop} × aerial/bundle drops</div>')
        H.append('</div>')
        H.append('</div>')

        # Summary bar
        H.append('<div class="summary-bar">')
        if n_splices: H.append(f'<div class="chip chip-splice">{n_splices} splices</div>')
        if n_drop:    H.append(f'<div class="chip chip-drop">{n_drop} drops</div>')
        if n_pass:    H.append(f'<div class="chip chip-pass">{n_pass} pass-through</div>')
        if n_dark:    H.append(f'<div class="chip chip-dark">{n_dark} dark</div>')
        if total_f:
            s_pct = int(n_splices/total_f*100) if total_f else 0
            d_pct = int(n_drop/total_f*100)    if total_f else 0
            p_pct = int(n_pass/total_f*100)    if total_f else 0
            k_pct = 100 - s_pct - d_pct - p_pct
            H.append(f'<div class="fibre-bar"><div class="fb-s" style="width:{s_pct}%;"></div>'
                     f'<div class="fb-d" style="width:{d_pct}%;"></div>'
                     f'<div class="fb-p" style="width:{p_pct}%;"></div>'
                     f'<div class="fb-k" style="width:{k_pct}%;"></div></div>')
        H.append('</div>')

        # Drop detail table
        if drops:
            is_aerial_drop = drops[0]['fibre_role'] == 'AERIAL_DROP'
            label_text = "Aerial drops at this joint" if is_aerial_drop else "Bundle drops at this joint"
            H.append(f'<div class="drops-section"><div class="drops-head">&#8627; {label_text}</div>')
            H.append('<table class="dt"><thead><tr>')
            H.append('<th>Tube</th><th>Fibre</th><th>Drop ID</th><th>Address</th><th>Type</th>')
            H.append('</tr></thead><tbody>')

            for d in sorted(drops, key=lambda x: (x['tube_number'] or 0, x['fibre_number'] or 0)):
                t       = d['tube_number']  or 1
                f       = d['fibre_number'] or 1
                drop_id = d.get('bundle_id') or '—'
                role    = d['fibre_role']

                # Address lookup via UPRN
                uprn    = drop_uprn.get(str(drop_id), "")
                address = address_idx.get(uprn, uprn or "—")

                dtype_class = "dtype dtype-a" if role == 'AERIAL_DROP' else "dtype dtype-b"
                dtype_label = "Aerial" if role == 'AERIAL_DROP' else "Bundle"

                H.append('<tr>')
                H.append(f'<td>{_tube_pill_html(t)}</td>')
                H.append(f'<td>{_fibre_cell_html(t, f)}</td>')
                H.append(f'<td><span class="did">{drop_id}</span></td>')
                H.append(f'<td>{address}</td>')
                H.append(f'<td><span class="{dtype_class}">{dtype_label}</span></td>')
                H.append('</tr>')

            H.append('</tbody></table></div>')

        H.append('</div>')  # joint-card

        # Connector arrow to next joint
        if hop_idx < len(joints_in_order) - 1:
            next_seg = cable_segments[hop_idx] if hop_idx < len(cable_segments) else None
            if next_seg:
                cid, is_aer, cinfo = next_seg
                aer_class  = "aerial" if is_aer else "ug"
                length_str = f"{cinfo.get('length_m','')}m" if cinfo.get('length_m') else ""
                fc_str     = f"{cinfo.get('fibre_count','')}F" if cinfo.get('fibre_count') else ""
                ct_str     = cinfo.get('cable_type','')
                lbl_parts  = [p for p in [short_cable(cid), fc_str, ct_str, length_str] if p]
                H.append('<div class="conn-wrap">')
                H.append(f'<div class="conn-col"><div class="conn-line {aer_class}"></div><div class="conn-arrow {aer_class}"></div></div>')
                H.append(f'<div class="conn-info"><div class="conn-lbl {aer_class}">{" &middot; ".join(lbl_parts)}</div></div>')
                H.append('</div>')
            else:
                H.append('<div class="conn-wrap"><div class="conn-col"><div class="conn-line ug"></div><div class="conn-arrow ug"></div></div></div>')

    # Final arrow to premises
    H.append('<div class="conn-wrap">')
    H.append('<div class="conn-col"><div class="conn-line drop"></div><div class="conn-arrow drop"></div></div>')
    H.append('<div class="conn-info"><div class="conn-lbl drop">Aerial / bundle drop to premises</div></div>')
    H.append('</div>')

    # Premises card
    H.append(f'<div class="prem-card"><div class="prem-dot">&#8962;</div>')
    H.append(f'<div><div class="prem-addr">{route_label}</div>')
    H.append(f'<div class="prem-uprn">Route Splice Plan &middot; {len(joints_in_order)} joints &middot; Gigaloch</div></div></div>')

    # Footer
    H.append(f'<div class="footer"><span>{route_label} &middot; Route Splice Plan &middot; Gigaloch</span>')
    H.append('<span>Print: Ctrl+P &middot; Works offline</span></div>')
    H.append('</div></body></html>')

    html = '\n'.join(H)
    return safe_write_text(output_path, html, what="Route splice plan")


# ── Map tool ──────────────────────────────────────────────────────────────────

class RouteSpliceMapTool(QgsMapTool):

    def __init__(self, canvas, project, iface, panel):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self._iface   = iface
        self._panel   = panel
        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasPressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self._handle_click(event.pos())

    def _handle_click(self, canvas_pos):
        canvas_pt = self.toMapCoordinates(canvas_pos)
        src_crs   = self._canvas.mapSettings().destinationCrs()
        dst_crs   = QgsCoordinateReferenceSystem("EPSG:27700")

        if src_crs != dst_crs:
            xform    = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
            pt_27700 = xform.transform(canvas_pt)
        else:
            pt_27700 = canvas_pt

        scale  = self._canvas.mapUnitsPerPixel()
        radius = SNAP_RADIUS_PX * scale

        from qgis.core import QgsGeometry, QgsPointXY
        rect = QgsRectangle(
            pt_27700.x() - radius, pt_27700.y() - radius,
            pt_27700.x() + radius, pt_27700.y() + radius
        )

        clicked_type = None
        clicked_feat = None
        best_dist    = float("inf")

        for layer_name, feat_type in [("premises","premises"),("joints","joint")]:
            layer = get_layer(layer_name, self._project)
            if not layer:
                continue
            for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
                geom = feat.geometry()
                if geom and not geom.isEmpty():
                    pt_geom = QgsGeometry.fromPointXY(QgsPointXY(pt_27700))
                    d = geom.distance(pt_geom)
                    if d < best_dist:
                        best_dist    = d
                        clicked_feat = feat
                        clicked_type = feat_type

        if clicked_feat is None:
            self._iface.messageBar().pushInfo(
                "Route Splice Export",
                "No premises or joint found near click. Try clicking closer to a point."
            )
            return

        self._panel.set_status("Tracing route…")

        if clicked_type == "premises":
            uprn    = clicked_feat["uprn"]
            fields  = clicked_feat.fields().names()
            area_id = str(clicked_feat["area_id"]) if "area_id" in fields else ""
            a1 = str(clicked_feat["address_1"] or "") if "address_1" in fields else ""
            a2 = str(clicked_feat["address_2"] or "") if "address_2" in fields else ""
            pc = str(clicked_feat["postcode"]   or "") if "postcode"  in fields else ""
            label = ", ".join(p for p in [a1, a2, pc] if p) or str(uprn)

            status, joints, reason, path = _trace_from_premises(uprn, area_id, self._project)
            if not joints:
                self._panel.set_status(f"⚠  No route found: {reason}")
                return
            self._panel.ready(label, joints, path, self._project)

        else:
            joint_id    = str(clicked_feat["joint_id"])
            cable_layer = get_layer("cables", self._project)
            joint_layer = get_layer("joints", self._project)
            joints, reason = _find_joint_route(joint_id, cable_layer, joint_layer)
            if not joints:
                self._panel.set_status(f"⚠  {reason}")
                return
            self._panel.ready(joint_id, joints, None, self._project)

    def deactivate(self):
        super().deactivate()


# ── Panel dialog ──────────────────────────────────────────────────────────────

class RouteSplicePanel(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Conductor — Route Splice Export")
        self.setMinimumWidth(420)
        self._tool    = None
        self._joints  = []
        self._path    = None
        self._project = None
        self._label   = ""
        self._out_dir = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        title = QLabel("Route Splice Export")
        title.setStyleSheet(f"font-size:13px; font-weight:700; color:{NAVY};")
        root.addWidget(title)

        self._status_lbl = QLabel("Click a premises or joint on the map to trace its route.")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet("font-size:11px; color:#555;")
        root.addWidget(self._status_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{MID};")
        root.addWidget(sep)

        self._route_lbl = QLabel("")
        self._route_lbl.setWordWrap(True)
        self._route_lbl.setStyleSheet(f"font-size:10px; color:{NAVY};")
        root.addWidget(self._route_lbl)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Save to:"))
        self._path_lbl = QLabel("(choose folder)")
        self._path_lbl.setStyleSheet("font-size:11px; color:#C85A00;")
        folder_row.addWidget(self._path_lbl, 1)
        btn_browse = QPushButton("Browse")
        btn_browse.setStyleSheet(f"padding:4px 10px; font-size:11px; border:1px solid {MID}; border-radius:3px;")
        btn_browse.clicked.connect(self._browse)
        folder_row.addWidget(btn_browse)
        root.addLayout(folder_row)

        btn_row = QHBoxLayout()
        self._btn_export = QPushButton("Export Route Splice Plan")
        self._btn_export.setEnabled(False)
        self._btn_export.setStyleSheet(
            f"QPushButton {{ padding:7px 14px; border-radius:4px; font-size:11px; "
            f"background:{NAVY}; color:{WHITE}; border:none; font-weight:600; }}"
            f"QPushButton:disabled {{ background:#aaa; }}"
            f"QPushButton:hover:enabled {{ background:{TEAL}; }}"
        )
        self._btn_export.clicked.connect(self._export)
        self._btn_close = QPushButton("Close")
        self._btn_close.setStyleSheet(
            f"QPushButton {{ padding:7px 14px; border-radius:4px; font-size:11px; border:1px solid {MID}; }}"
            f"QPushButton:hover {{ background:#e8e8e8; }}"
        )
        self._btn_close.clicked.connect(self.close)
        btn_row.addWidget(self._btn_export)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

        from qgis.core import QgsSettings
        saved = QgsSettings().value('conductor/route_splice_dir', '')
        if saved and os.path.exists(saved):
            self._out_dir = saved
            self._path_lbl.setText(saved)
            self._path_lbl.setStyleSheet("font-size:11px; color:#555;")

    def set_status(self, msg):
        self._status_lbl.setText(msg)
        self._route_lbl.setText("")
        self._btn_export.setEnabled(False)

    def ready(self, label, joints, path, project):
        self._label   = label
        self._joints  = joints
        self._path    = path
        self._project = project
        self._status_lbl.setText(f"✔  Route traced — {len(joints)} joint{'s' if len(joints)!=1 else ''} found.")
        self._route_lbl.setText("CAB  →  " + "  →  ".join(j.split("-")[-1] for j in joints) + "  →  PREM")
        self._btn_export.setEnabled(True)

    def _browse(self):
        from qgis.core import QgsSettings
        d = QFileDialog.getExistingDirectory(self, "Select output folder", self._out_dir or os.path.expanduser("~"))
        if d:
            self._out_dir = d
            self._path_lbl.setText(d)
            self._path_lbl.setStyleSheet("font-size:11px; color:#555;")
            QgsSettings().setValue('conductor/route_splice_dir', d)

    def _export(self):
        if not self._joints:
            QMessageBox.warning(self, "No route", "Please click a premises or joint first.")
            return
        if not self._out_dir:
            QMessageBox.warning(self, "No folder", "Please choose an output folder first.")
            return
        safe  = self._label.replace(",","").replace(" ","_").replace("/","-")[:40]
        fname = f"route_splice_{safe}.html"
        out   = os.path.join(self._out_dir, fname)
        try:
            out = _generate_route_html(self._joints, self._label, out,
                                 project=self._project, cable_path=self._path)
            reply = QMessageBox.question(
                self, "Export complete",
                f"Saved to:\n{out}\n\nOpen in browser?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                webbrowser.open("file:///" + out.replace(os.sep, "/"))
        except Exception as e:
            QMessageBox.critical(self, "Export error", str(e))

    def closeEvent(self, event):
        if self._tool:
            try:
                self._tool._canvas.unsetMapTool(self._tool)
            except Exception:
                pass
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────

def activate_route_splice_export(iface, project, parent=None):
    canvas = iface.mapCanvas()
    panel  = RouteSplicePanel(parent)
    tool   = RouteSpliceMapTool(canvas, project, iface, panel)
    panel._tool = tool
    canvas.setMapTool(tool)
    panel.show()
    iface.messageBar().pushInfo(
        "Conductor — Route Splice Export",
        "Click any premises or joint on the map to trace its route. Esc to exit."
    )
    return tool, panel
