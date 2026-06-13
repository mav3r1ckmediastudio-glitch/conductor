# -*- coding: utf-8 -*-
# splice_plan.py  -  Conductor FTTP Network Design Plugin
# Generates a self-contained HTML splice plan for a selected joint.

import os
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QMessageBox, QFrame
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, NULL
from ..conductor_utils import get_layer, fld, val, LayerEditContext
from ..conductor_utils import safe_write_text

IEC_COLOURS = ['Blue','Orange','Green','Brown','Slate','White','Red','Black','Yellow','Violet','Rose','Aqua']
IEC_HEX     = ['#3B82F6','#F97316','#22C55E','#92400E','#94A3B8','#FFFFFF','#EF4444','#1C1C1C','#EAB308','#8B5CF6','#F9A8D4','#06B6D4']
IEC_BORDER  = [None,None,None,None,None,'#999',None,'#555',None,None,'#e879a0',None]

TUBE_COLOURS = [
    ('#1A6FBF','#E3EEFA','#0D3D6E'),
    ('#E6760A','#FEF0DC','#7A3D04'),
    ('#1D8C4A','#DFF5E8','#0B4A26'),
    ('#8B4513','#F5E6D8','#4A2009'),
]



def fibre_colour_name(fib_in_tube): return IEC_COLOURS[(fib_in_tube - 1) % 12]
def fibre_hex(fib_in_tube):         return IEC_HEX[(fib_in_tube - 1) % 12]
def fibre_border(fib_in_tube):      return IEC_BORDER[(fib_in_tube - 1) % 12]
def tube_css(tube_num):
    idx = min(tube_num - 1, len(TUBE_COLOURS) - 1)
    return TUBE_COLOURS[idx]

def get_joints(project=None):
    layer = get_layer('Joints', project)
    if not layer: return []
    joints = []
    for feat in layer.getFeatures():
        jid = val(feat['joint_id'])
        if jid: joints.append(jid)
    return sorted(joints)

def get_assignments_for_joint(joint_id, project=None):
    layer = get_layer('fibre_assignments', project)
    if not layer: return []

    # Check if this is a CBT joint
    joint_layer = get_layer('joints', project)
    is_cbt = False
    cbt_cable = None
    if joint_layer:
        for feat in joint_layer.getFeatures():
            if str(val(feat['joint_id']) or '') == joint_id:
                if str(val(feat['joint_type']) or '') == 'CBT':
                    is_cbt = True
                break

    # Load local assignments for this joint
    result = []
    local_cables = set()
    for feat in layer.getFeatures():
        if val(feat['joint_id']) == joint_id:
            rec = {
                'assign_id':       val(feat['assign_id']),
                'cable_id':        val(feat['cable_id']),
                'tube_number':     val(feat['tube_number']),
                'fibre_number':    val(feat['fibre_number']),
                'fibre_role':      val(feat['fibre_role']),
                'splitter_id':     val(feat['splitter_id']),
                'splice_to_cable': val(feat['splice_to_cable']),
                'splice_to_tube':  val(feat['splice_to_tube']),
                'splice_to_fibre': val(feat['splice_to_fibre']),
                'bundle_id':       val(feat['bundle_id']),
                'notes':           val(feat['notes']),
            }
            result.append(rec)
            if rec['cable_id']:
                local_cables.add(rec['cable_id'])

    # For CBT joints: also load all assignments on the same cable(s)
    # attributed to other joints — these are pass-through fibres
    if is_cbt and local_cables:
        local_fibs = {(r['cable_id'], r['tube_number'], r['fibre_number']) for r in result}
        for feat in layer.getFeatures():
            cable_id = val(feat['cable_id'])
            if cable_id not in local_cables:
                continue
            tube = val(feat['tube_number'])
            fib  = val(feat['fibre_number'])
            if (cable_id, tube, fib) in local_fibs:
                continue  # already loaded
            role = str(val(feat['fibre_role']) or '')
            if role in ('THROUGH_SPLICE',):
                continue  # skip synthetic splices
            result.append({
                'assign_id':       val(feat['assign_id']),
                'cable_id':        cable_id,
                'tube_number':     tube,
                'fibre_number':    fib,
                'fibre_role':      'PASS_THROUGH' if role not in ('DARK_STORAGE',) else 'DARK_STORAGE',
                'splitter_id':     None,
                'splice_to_cable': None,
                'splice_to_tube':  None,
                'splice_to_fibre': None,
                'bundle_id':       val(feat['bundle_id']),
                'notes':           val(feat['notes']),
            })

    return result

def get_joint_info(joint_id, project=None):
    layer = get_layer('Joints', project)
    if not layer: return {}
    for feat in layer.getFeatures():
        if val(feat['joint_id']) == joint_id:
            return {
                'joint_id':    val(feat['joint_id']),
                'chamber_id':  val(feat['chamber_id']),
                'pop_id':      val(feat['pop_id']),
                'joint_type':  val(feat['joint_type']),
                'has_splitter':bool(val(feat['has_splitter'])),
                'split_ratio': val(feat['split_ratio']),
                'closure_type':val(feat['closure_type']),
            }
    return {}

def fd(fib_in_tube):
    hex_c  = fibre_hex(fib_in_tube)
    border = fibre_border(fib_in_tube)
    bstyle = ('border:1px solid ' + border + ';') if border else ''
    name   = fibre_colour_name(fib_in_tube)
    return ('<span style="display:inline-flex;align-items:center;gap:5px;">'
            '<span style="width:11px;height:11px;border-radius:50%;flex-shrink:0;'
            'background:' + hex_c + ';' + bstyle + '"></span>'
            '<span style="font-size:11px;">F' + str(fib_in_tube) + ' &middot; ' + name + '</span>'
            '</span>')

def tube_pill(tube_num):
    col, bg, txt = tube_css(tube_num)
    return ('<span style="display:inline-block;border-radius:3px;font-size:10px;'
            'font-weight:bold;padding:1px 6px;white-space:nowrap;'
            'background:' + bg + ';color:' + txt + ';">T' + str(tube_num) + '</span>')

def splice_link(tube_num):
    col, bg, txt = tube_css(tube_num)
    return ('<div style="display:flex;align-items:center;justify-content:center;gap:0;">'
            '<div style="width:7px;height:7px;border-radius:50%;background:' + col + ';"></div>'
            '<div style="flex:1;height:2px;min-width:20px;background:' + col + ';"></div>'
            '<div style="width:7px;height:7px;border-radius:50%;background:' + col + ';"></div>'
            '</div>'
            '<div style="font-size:8px;color:#5F5E5A;text-align:center;">SPLICE</div>')

def short_cable(cable_id):
    if not cable_id: return ''
    parts = cable_id.split('-')
    return parts[-1] if parts else cable_id

def generate_html(joint_id, output_path, project=None):
    joint_info  = get_joint_info(joint_id, project=project)
    assignments = get_assignments_for_joint(joint_id, project=project)
    if not assignments:
        raise RuntimeError('No fibre assignments found for ' + joint_id + '. Run Auto-Assign first.')

    # Organise by role
    splices    = [a for a in assignments if a['fibre_role'] == 'THROUGH_SPLICE' and a['cable_id'] is not None]
    sp_inputs  = [a for a in assignments if a['fibre_role'] == 'SPLITTER_INPUT']
    sp_outputs = [a for a in assignments if a['fibre_role'] in ('SPLITTER_OUTPUT','SPLITTER_OUTPUT_SPARE')]
    drops      = [a for a in assignments if a['fibre_role'] in ('AERIAL_DROP', 'BUNDLE_DROP')]
    dark       = [a for a in assignments if a['fibre_role'] == 'DARK_STORAGE']
    pass_through_pre = [a for a in assignments if a['fibre_role'] == 'PASS_THROUGH']

    # Pair through-splices: from-side only (splice_to_cable is set)
    splice_pairs = [a for a in splices if a['splice_to_cable'] is not None
                    and a['splice_to_fibre'] is not None]
    # Deduplicate - only show each physical splice once (from side)
    seen_pairs = set()
    unique_splices = []
    for a in splice_pairs:
        key = tuple(sorted([
            (a['cable_id'], a['tube_number'], a['fibre_number']),
            (a['splice_to_cable'], a['splice_to_tube'], a['splice_to_fibre'])
        ]))
        if key not in seen_pairs:
            seen_pairs.add(key)
            unique_splices.append(a)

    # Stats
    n_splices  = len(unique_splices)
    n_splitters = len(sp_inputs)
    n_active   = len([a for a in sp_outputs if a['fibre_role'] == 'SPLITTER_OUTPUT']) + len(drops)
    n_spare_f  = len(dark)
    # total fibres on incoming cable
    all_cables = set(a['cable_id'] for a in assignments if a['cable_id'])
    total_f    = 0
    cable_layer = get_layer('Cables', project)
    if cable_layer:
        for feat in cable_layer.getFeatures():
            if val(feat['cable_id']) in all_cables:
                fc = val(feat['fibre_count'])
                if fc and int(fc) > total_f: total_f = int(fc)

    split_ratio = joint_info.get('split_ratio','')
    pop_id      = joint_info.get('pop_id','')
    chamber_id  = joint_info.get('chamber_id','')
    closure     = joint_info.get('closure_type','') or 'FDC'
    jtype       = joint_info.get('joint_type','SPLICE')

    # Group splices by tube
    by_tube = {}
    for a in unique_splices:
        t = a['tube_number'] or 1
        by_tube.setdefault(t, []).append(a)
    for t in by_tube: by_tube[t].sort(key=lambda x: x['fibre_number'] or 0)

    # Dark storage by tube
    dark_by_tube = {}
    for a in dark:
        t = a['tube_number'] or 1
        dark_by_tube.setdefault(t, []).append(a)

    CSS = (
        ':root{--navy:#1A3A5C;--mid:#CBD5E1;--bg:#F4F6F9;--gray:#5F5E5A;--gray-light:#F1EFE8;}'
        '*{box-sizing:border-box;margin:0;padding:0;}'
        'body{font-family:Courier New,Courier,monospace;background:var(--bg);color:#1A1A1A;font-size:13px;line-height:1.5;}'
        '.page{max-width:960px;margin:0 auto;padding:20px;}'
        '.header{background:var(--navy);color:white;border-radius:10px;padding:16px 20px;margin-bottom:14px;}'
        '.header-top{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;}'
        '.header-title{font-size:20px;font-weight:bold;letter-spacing:0.5px;}'
        '.header-sub{font-size:11px;color:#9FB4CC;margin-top:3px;}'
        '.header-loc{font-size:11px;color:#9FB4CC;text-align:right;}'
        '.meta-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px;}'
        '.meta-card{background:rgba(255,255,255,0.09);border-radius:6px;padding:7px 10px;}'
        '.meta-label{font-size:9px;color:#9FB4CC;text-transform:uppercase;letter-spacing:0.8px;}'
        '.meta-value{font-size:16px;font-weight:bold;color:white;margin-top:1px;}'
        '.legends{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;}'
        '.legend-box{background:white;border:0.5px solid var(--mid);border-radius:6px;padding:7px 12px;flex:1;min-width:200px;}'
        '.legend-title{font-size:9px;font-weight:bold;color:var(--gray);text-transform:uppercase;letter-spacing:0.8px;margin-bottom:6px;}'
        '.legend-items{display:flex;flex-wrap:wrap;gap:5px;}'
        '.legend-item{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--gray);}'
        '.section-wrap{background:white;border-radius:8px;border:0.5px solid var(--mid);margin-bottom:10px;overflow:hidden;}'
        '.section-head{padding:7px 12px;font-size:10px;font-weight:bold;text-transform:uppercase;letter-spacing:0.8px;border-bottom:1px solid var(--mid);display:flex;align-items:center;gap:8px;}'
        '.splice-table{width:100%;border-collapse:collapse;}'
        '.splice-table th{font-size:9px;text-transform:uppercase;letter-spacing:0.6px;color:var(--gray);padding:4px 8px;border-bottom:1px solid var(--mid);text-align:left;background:#FAFBFC;}'
        '.splice-table td{padding:4px 8px;vertical-align:middle;border-bottom:0.5px solid #EEF0F3;}'
        '.splice-table tr:last-child td{border-bottom:none;}'
        '.splitter-section{background:#FAECE7;border:1.5px solid #C03A1A;border-radius:8px;padding:14px 16px;margin-bottom:10px;}'
        '.splitter-head{font-size:11px;font-weight:bold;color:#6B1D0A;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px;}'
        '.splitter-layout{display:flex;align-items:center;gap:0;flex-wrap:wrap;}'
        '.sp-outputs{margin-left:10px;flex:1;display:flex;flex-direction:column;gap:3px;}'
        '.sp-out-row{display:flex;align-items:center;gap:6px;}'
        '.po-pill{font-size:10px;font-weight:bold;padding:1px 6px;border-radius:3px;background:white;border:1px solid #C03A1A;color:#6B1D0A;flex-shrink:0;min-width:30px;text-align:center;}'
        '.po-yes{color:#0F6E56;}'
        '.po-no{color:#B4B2A9;font-style:italic;}'
        '.spare-block{background:var(--gray-light);border-radius:8px;padding:12px 14px;margin-bottom:10px;}'
        '.spare-title{font-size:10px;font-weight:bold;color:var(--gray);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;}'
        '.spare-bar-bg{height:10px;background:#D3D1C7;border-radius:5px;}'
        '.spare-stats{display:flex;justify-content:space-between;font-size:10px;color:var(--gray);margin-top:4px;}'
        '.footer{margin-top:16px;padding-top:10px;border-top:1px solid var(--mid);display:flex;justify-content:space-between;font-size:10px;color:var(--gray);}'
        '@media print{body{background:white;}.page{padding:8px;}.section-wrap{break-inside:avoid;}.splitter-section{break-inside:avoid;}}'
    )

    # Build HTML
    H = []
    H.append('<!DOCTYPE html><html lang="en"><head>')
    H.append('<meta charset="UTF-8">')
    H.append('<title>' + joint_id + ' &middot; Splice Plan</title>')
    H.append('<style>' + CSS + '</style>')
    H.append('</head><body><div class="page">')

    # Header
    H.append('<div class="header">')
    H.append('<div class="header-top"><div>')
    H.append('<div class="header-title">' + joint_id + '</div>')
    H.append('<div class="header-sub">Splice Plan &middot; Closure: ' + closure + ' &middot; Type: ' + jtype + ' &middot; Owner: Gigaloch</div>')
    H.append('</div><div class="header-loc">' + (pop_id or '') + '<br>' + (chamber_id or '') + '</div></div>')
    H.append('<div class="meta-grid">')
    H.append('<div class="meta-card"><div class="meta-label">Splices</div><div class="meta-value">' + str(n_splices) + '</div></div>')
    H.append('<div class="meta-card"><div class="meta-label">Splitters</div><div class="meta-value">' + (str(n_splitters) + ' x ' + str(split_ratio) if n_splitters else '0') + '</div></div>')
    H.append('<div class="meta-card"><div class="meta-label">Active ports</div><div class="meta-value">' + str(n_active) + '</div></div>')
    H.append('<div class="meta-card"><div class="meta-label">Spare fibres</div><div class="meta-value">' + str(n_spare_f) + ' / ' + str(total_f) + '</div></div>')
    H.append('</div></div>')

    # Legend
    H.append('<div class="legends"><div class="legend-box">')
    H.append('<div class="legend-title">Tube colour coding</div><div class="legend-items">')
    tube_names = ['Blue','Orange','Green','Brown']
    for i, tn in enumerate(tube_names):
        col, bg, txt = tube_css(i + 1)
        H.append('<div class="legend-item"><span style="display:inline-block;border-radius:3px;font-size:10px;font-weight:bold;padding:1px 6px;background:' + bg + ';color:' + txt + ';">T' + str(i+1) + '</span>' + tn + '</div>')
    H.append('</div></div><div class="legend-box">')
    H.append('<div class="legend-title">Fibre colours &mdash; IEC 60794</div><div class="legend-items">')
    for i in range(12):
        brd = ('border:1px solid ' + IEC_BORDER[i] + ';') if IEC_BORDER[i] else ''
        H.append('<div class="legend-item"><span style="width:11px;height:11px;border-radius:50%;display:inline-block;background:' + IEC_HEX[i] + ';' + brd + '"></span>' + str(i+1) + ' ' + IEC_COLOURS[i][:3] + '</div>')
    H.append('</div></div></div>')

    # Splitter section
    for sp_in in sp_inputs:
        sp_id   = sp_in['splitter_id'] or ''
        sp_cab  = sp_in['cable_id'] or ''
        sp_tube = sp_in['tube_number'] or 1
        sp_fib  = sp_in['fibre_number'] or 1
        outputs = [a for a in sp_outputs if a['splitter_id'] == sp_id]
        H.append('<div class="splitter-section">')
        H.append('<div class="splitter-head">' + str(split_ratio) + ' Passive Splitter &mdash; ' + tube_pill(sp_tube) + ' ' + fd(sp_fib) + ' input &rarr; ' + sp_id + '</div>')
        H.append('<div class="splitter-layout">')
        col_t, bg_t, txt_t = tube_css(sp_tube)
        H.append('<div style="font-size:11px;color:' + txt_t + ';font-weight:bold;padding:6px 10px;background:' + bg_t + ';border-radius:4px;">' + short_cable(sp_cab) + '<br>' + tube_pill(sp_tube) + ' ' + fd(sp_fib) + '</div>')
        H.append('<div style="width:30px;height:2px;background:#C03A1A;flex-shrink:0;"></div>')
        H.append('<div style="background:white;border:2px solid #C03A1A;border-radius:6px;padding:8px 16px;text-align:center;flex-shrink:0;"><div style="font-size:18px;font-weight:bold;color:#6B1D0A;">' + str(split_ratio) + '</div></div>')
        H.append('<div class="sp-outputs">')
        for port_idx, out in enumerate(outputs):
            port_label = 'PO' + str(port_idx + 1)
            bun_id     = out.get('bundle_id')
            out_fib    = out['fibre_number'] or 1
            out_tube   = out['tube_number'] or 1
            H.append('<div class="sp-out-row"><div style="width:20px;height:2px;background:#C03A1A;flex-shrink:0;"></div>')
            H.append('<div class="po-pill">' + port_label + '</div>')
            if bun_id:
                H.append('<div class="po-yes">' + bun_id + ' ' + tube_pill(out_tube) + ' ' + fd(out_fib) + '</div>')
            else:
                H.append('<div class="po-no">unassigned &mdash; future customer</div>')
            H.append('</div>')
        H.append('</div></div></div>')

    # Splice sections by tube
    for tube_num in sorted(by_tube.keys()):
        rows = by_tube[tube_num]
        col_t, bg_t, txt_t = tube_css(tube_num)
        H.append('<div class="section-wrap">')
        H.append('<div class="section-head" style="background:' + bg_t + ';color:' + txt_t + ';">' + tube_pill(tube_num) + ' Tube ' + str(tube_num) + ' &mdash; Through splices (' + str(len(rows)) + ')</div>')
        H.append('<table class="splice-table"><thead><tr>')
        H.append('<th style="width:120px;">From cable</th><th style="width:50px;">Tube</th><th style="width:90px;">Fibre</th>')
        H.append('<th style="width:110px;text-align:center;">Link</th>')
        H.append('<th style="width:50px;">Tube</th><th style="width:90px;">Fibre</th><th>To cable</th>')
        H.append('</tr></thead><tbody>')
        for a in rows:
            from_fib  = a['fibre_number'] or 1
            to_fib    = a['splice_to_fibre'] or 1
            to_tube   = a['splice_to_tube'] or 1
            to_cable  = short_cable(a['splice_to_cable'])
            from_cable = short_cable(a['cable_id'])
            H.append('<tr>')
            H.append('<td>' + from_cable + '</td>')
            H.append('<td>' + tube_pill(tube_num) + '</td>')
            H.append('<td>' + fd(from_fib) + '</td>')
            H.append('<td>' + splice_link(tube_num) + '</td>')
            H.append('<td>' + tube_pill(to_tube) + '</td>')
            H.append('<td>' + fd(to_fib) + '</td>')
            H.append('<td>' + to_cable + '</td>')
            H.append('</tr>')
        H.append('</tbody></table></div>')

    # Drops section (aerial and bundle)
    if drops:
        H.append('<div class="spare-block" style="border-color:#00AAFF;">')
        H.append('<div class="spare-title" style="color:#00AAFF;">Active drops &mdash; connected premises</div>')
        H.append('<table style="width:100%;border-collapse:collapse;font-size:11px;margin-top:6px;">')
        H.append('<thead><tr style="background:#F0F8FF;">')
        H.append('<th style="padding:4px 8px;text-align:left;border-bottom:1px solid #CBD5E1;">Tube</th>')
        H.append('<th style="padding:4px 8px;text-align:left;border-bottom:1px solid #CBD5E1;">Fibre</th>')
        H.append('<th style="padding:4px 8px;text-align:left;border-bottom:1px solid #CBD5E1;">Colour</th>')
        H.append('<th style="padding:4px 8px;text-align:left;border-bottom:1px solid #CBD5E1;">Drop ID</th>')
        H.append('<th style="padding:4px 8px;text-align:left;border-bottom:1px solid #CBD5E1;">Type</th>')
        H.append('</tr></thead><tbody>')
        for d in sorted(drops, key=lambda x: (x['tube_number'] or 0, x['fibre_number'] or 0)):
            t   = d['tube_number'] or 1
            f   = d['fibre_number'] or 1
            col_t, bg_t, txt_t = tube_css(t)
            fib_abs = (t - 1) * 12 + f
            clr = fibre_colour_name(fib_abs)
            drop_id = d.get('bundle_id') or '—'
            role = 'Aerial' if d['fibre_role'] == 'AERIAL_DROP' else 'Bundle'
            H.append('<tr>')
            H.append('<td style="padding:3px 8px;"><span style="font-size:10px;padding:1px 5px;border-radius:3px;background:' + bg_t + ';color:' + txt_t + ';font-weight:bold;">T' + str(t) + '</span></td>')
            H.append('<td style="padding:3px 8px;font-weight:bold;">' + fd(f) + '</td>')
            H.append('<td style="padding:3px 8px;">' + clr + '</td>')
            H.append('<td style="padding:3px 8px;font-family:Courier New;">' + drop_id + '</td>')
            H.append('<td style="padding:3px 8px;color:#00AAFF;">' + role + '</td>')
            H.append('</tr>')
        H.append('</tbody></table></div>')

    # Pass-through fibres (CBT only — fibres continuing onward along aerial chain)
    pass_through = [a for a in assignments if a['fibre_role'] == 'PASS_THROUGH']
    if pass_through:
        pt_by_tube = {}
        for a in pass_through:
            t = a['tube_number'] or 1
            pt_by_tube.setdefault(t, []).append(a['fibre_number'])
        H.append('<div class="spare-block" style="border-color:#888;background:#F8F8F8;">')
        H.append('<div class="spare-title" style="color:#888;">Pass-through fibres &mdash; onward along aerial chain</div>')
        for t, fibs in sorted(pt_by_tube.items()):
            col_t, bg_t, txt_t = tube_css(t)
            fibs_s = sorted([f for f in fibs if f])
            if fibs_s:
                fib_range = 'F' + str(fibs_s[0]) + '-' + str(fibs_s[-1])
                H.append('<span style="font-size:10px;padding:2px 8px;border-radius:3px;background:' + bg_t + ';color:' + txt_t + ';margin-right:4px;">T' + str(t) + ' &middot; ' + fib_range + ' (' + str(len(fibs_s)) + ' fibres)</span>')
        H.append('</div>')

    # Spare / dark storage
    if dark:
        H.append('<div class="spare-block">')
        H.append('<div class="spare-title">Spare / dark storage &mdash; do not disturb</div>')
        dark_tubes = {}
        for a in dark:
            t = a['tube_number'] or 1
            dark_tubes.setdefault(t, []).append(a['fibre_number'])
        for t, fibs in sorted(dark_tubes.items()):
            col_t, bg_t, txt_t = tube_css(t)
            fibs_sorted = sorted([f for f in fibs if f])
            fib_range = 'F' + str(fibs_sorted[0]) + '-' + str(fibs_sorted[-1]) if fibs_sorted else ''
            H.append('<span style="font-size:10px;padding:2px 8px;border-radius:3px;background:' + bg_t + ';color:' + txt_t + ';margin-right:4px;">T' + str(t) + ' &middot; ' + fib_range + ' (' + str(len(fibs)) + ' fibres spare)</span>')
        active_f = total_f - n_spare_f
        pct      = int((active_f / total_f * 100)) if total_f else 0
        H.append('<div style="margin-top:8px;"><div class="spare-bar-bg"><div style="height:10px;background:#888;border-radius:5px;width:' + str(pct) + '%;"></div></div>')
        H.append('<div class="spare-stats"><span>' + str(active_f) + ' fibres active</span><span>' + str(n_active) + ' assigned &middot; ' + str(n_spare_f) + ' spare &middot; ' + str(total_f) + ' total</span></div></div>')
        H.append('</div>')

    # Footer
    H.append('<div class="footer">')
    H.append('<span>' + joint_id + ' &middot; Splice Plan &middot; Gigaloch</span>')
    H.append('<span>Print: Ctrl+P &middot; Works offline &middot; ' + joint_id + '.html</span>')
    H.append('</div>')
    H.append('</div></body></html>')

    html = '\n'.join(H)
    return safe_write_text(output_path, html, what="Splice plan")

class SplicePlanDialog(QDialog):
    def __init__(self, iface, parent=None, project=None):
        super().__init__(parent)
        self.iface = iface
        self._project = project
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle('Conductor - Generate Splice Plan')
        self.setMinimumSize(440, 200)
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        header = QLabel('Generate Splice Plan')
        header.setStyleSheet('font-size:14px;font-weight:600;color:#1A3A5C;')
        root.addWidget(header)

        sub = QLabel('Select a joint to generate a self-contained HTML splice plan.')
        sub.setStyleSheet('font-size:11px;color:#555;')
        sub.setWordWrap(True)
        root.addWidget(sub)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel('Joint:'))
        self._combo = QComboBox()
        self._combo.addItems(get_joints(project=self._project))
        row1.addWidget(self._combo)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel('Save to:'))
        self._path_label = QLabel('(choose folder)')
        self._path_label.setStyleSheet('color:#555;font-size:11px;')
        row2.addWidget(self._path_label, 1)
        btn_browse = QPushButton('Browse')
        btn_browse.clicked.connect(self._browse)
        row2.addWidget(btn_browse)
        root.addLayout(row2)
        from qgis.core import QgsSettings
        saved = QgsSettings().value('conductor/splice_plan_dir', '')
        self._out_dir = saved if saved and os.path.exists(saved) else None
        if self._out_dir:
            self._path_label.setText(self._out_dir)
        else:
            self._path_label.setText("⚠  No folder selected — click Browse before generating")
            self._path_label.setStyleSheet("color:#C85A00; font-size:11px;")

        btn_row = QHBoxLayout()
        self._btn_gen = QPushButton('Generate HTML')
        self._btn_gen.setStyleSheet(
            'QPushButton{background:#1A3A5C;color:#fff;font-weight:600;'
            'padding:7px 18px;border-radius:4px;font-size:12px;}'
            'QPushButton:hover{background:#1D7A6E;}'
        )
        self._btn_gen.clicked.connect(self._generate)
        btn_close = QPushButton('Close')
        btn_close.setStyleSheet('QPushButton{padding:7px 14px;border-radius:4px;font-size:12px;border:1px solid #bbb;}QPushButton:hover{background:#e8e8e8;}')
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(self._btn_gen)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _browse(self):
        from qgis.core import QgsSettings
        d = QFileDialog.getExistingDirectory(self, 'Select output folder', self._out_dir or os.path.expanduser('~'))
        if d:
            self._out_dir = d
            self._path_label.setText(d)
            self._path_label.setStyleSheet("color:#555; font-size:11px;")
            QgsSettings().setValue('conductor/splice_plan_dir', d)

    def _generate(self):
        joint_id = self._combo.currentText()
        if not joint_id:
            QMessageBox.warning(self, 'No joint', 'Please select a joint.')
            return
        if not self._out_dir:
            QMessageBox.warning(self, 'No folder selected',
                'Please click Browse and choose a folder to save the splice plan to.')
            return
        out_path = os.path.join(self._out_dir, joint_id + '.html')
        try:
            out_path = generate_html(joint_id, out_path, project=self._project)
            reply = QMessageBox.question(
                self, 'Done',
                'Splice plan saved to:\n' + out_path + '\n\nOpen in browser?',
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                import webbrowser
                webbrowser.open('file:///' + out_path.replace(os.sep, '/'))
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

def open_splice_plan_dialog(iface, parent=None, project=None):
    dlg = SplicePlanDialog(iface, parent, project=project)
    dlg.show()
    return dlg
