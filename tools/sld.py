# -*- coding: utf-8 -*-
# sld.py  -  Conductor FTTP Network Design Plugin
# Generates a full-network Single Line Diagram as self-contained HTML.

import os
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, NULL
from ..conductor_utils import get_layer, fld, val, LayerEditContext

NAVY   = '#1A3A5C'
TEAL   = '#1D7A6E'
ORANGE = '#C85A00'
AERIAL = '#00AAFF'
GREEN  = '#00CC00'
BROWN  = '#8B4513'
GRAY   = '#5F5E5A'

CABLE_COLOURS = {
    'SPINE':        NAVY,
    'DISTRIBUTION': TEAL,
    'FEEDER':       NAVY,
    'AERIAL':       AERIAL,
    'DROP':         BROWN,
}



def build_network(project=None):
    def get(name):
        if project:
            return project.get_layer(name)
        return get_layer(name)

    cables = {}; joints = {}; bundles = {}; aerial_drops = {}
    from_node = {}; premises_map = {}
    cabinet = None; area_id = ''

    layer = get('premises')
    if layer:
        for feat in layer.getFeatures():
            uprn = str(val(feat['uprn']) or '')
            a1   = val(feat['address_1']) or ''
            a2   = val(feat['address_2']) or ''
            pc   = val(feat['postcode'])  or ''
            premises_map[uprn] = ', '.join(p for p in [a1, a2, pc] if p)

    layer = get('cables')
    if layer:
        for feat in layer.getFeatures():
            cid = str(feat['cable_id'])
            cables[cid] = {
                'cable_id':    cid,
                'cable_type':  val(feat['cable_type']) or 'SPINE',
                'fibre_count': int(val(feat['fibre_count']) or 48),
                'length_m':    round(float(val(feat['length_m']) or 0), 1),
                'from_node':   str(val(feat['from_node']) or ''),
                'to_node':     str(val(feat['to_node']) or ''),
            }
            fn = val(feat['from_node'])
            if fn: from_node.setdefault(str(fn), []).append(cid)
            if val(feat['from_node_type']) == 'POP':
                cabinet = str(feat['from_node'])
                area_id = str(val(feat['area_id']) or '')

    layer = get('joints')
    if layer:
        for feat in layer.getFeatures():
            jid = str(feat['joint_id'])
            joints[jid] = {
                'joint_id':    jid,
                'joint_type':  val(feat['joint_type']) or 'SPLICE',
                'has_splitter':bool(val(feat['has_splitter'])),
                'split_ratio': val(feat['split_ratio']),
                'chamber_id':  val(feat['chamber_id']),
            }

    layer = get('bundles')
    if layer:
        for feat in layer.getFeatures():
            bid  = str(feat['bundle_id'])
            uprn = str(val(feat['uprn']) or '')
            fj   = str(val(feat['from_joint']) or '')
            bundles.setdefault(fj, []).append({
                'bundle_id':   bid,
                'uprn':        uprn,
                'address':     premises_map.get(uprn, uprn or 'Unknown'),
                'fibre_count': int(val(feat['fibre_count']) or 2),
                'length_m':    round(float(val(feat['length_m']) or 0), 1),
            })

    # Load aerial drops keyed by from_chamber (CBT joint_id)
    # Only include PIA_AERIAL_DROP records to avoid picking up underground drops
    layer = get('drop_ducts')
    if layer:
        for feat in layer.getFeatures():
            fc = val(feat['from_chamber'])
            dt = str(val(feat['drop_type']) or '')
            if fc and dt == 'PIA_AERIAL_DROP':
                uprn    = str(val(feat['uprn']) or '')
                ddct_id = str(val(feat['ddct_id']) or '')
                length  = round(float(val(feat['length_m']) or 0), 1)
                aerial_drops.setdefault(str(fc), []).append({
                    'ddct_id': ddct_id,
                    'uprn':    uprn,
                    'address': premises_map.get(uprn, uprn or 'Unknown'),
                    'length_m': length,
                })

    return cables, joints, bundles, aerial_drops, from_node, cabinet, area_id


def render_node(node_id, cables, joints, bundles, aerial_drops, from_node, visited, depth=0):
    if node_id in visited: return ''
    visited.add(node_id)
    H = []

    outbound = from_node.get(node_id, [])
    joint    = joints.get(node_id)
    jbundles = bundles.get(node_id, [])
    jdrops   = aerial_drops.get(node_id, [])

    if joint:
        has_sp  = joint['has_splitter']
        ratio   = joint['split_ratio'] or ''
        jtype   = joint['joint_type']
        cmbr    = joint['chamber_id'] or ''
        jid     = joint['joint_id']

        is_cbt  = (jtype == 'CBT')

        if is_cbt:
            sp_label = 'CBT &mdash; Pole: ' + cmbr
            box_cls  = 'node-joint node-cbt'
        elif has_sp:
            sp_label = ratio + ' splitter'
            box_cls  = 'node-joint node-splitter'
        elif jtype == 'END_OF_LINE':
            sp_label = 'End of line'
            box_cls  = 'node-joint node-eol'
        else:
            sp_label = 'Pass-through'
            box_cls  = 'node-joint'

        H.append('<div class="tree-node">')
        H.append('<div class="' + box_cls + '">')
        H.append('<div class="node-id">' + jid + '</div>')
        H.append('<div class="node-meta">' + sp_label + '</div>')
        if cmbr and not is_cbt:
            H.append('<div class="node-chamber">' + cmbr + '</div>')
        H.append('</div>')

        # Underground bundles
        if jbundles:
            H.append('<div class="bundle-list">')
            for b in jbundles:
                bid    = b['bundle_id']
                addr   = b['address']
                blen   = b['length_m']
                bfibre = b['fibre_count']
                H.append('<div class="bundle-row">')
                H.append('<div class="bundle-line"></div>')
                H.append('<div class="bundle-box">')
                H.append('<span class="bundle-id">' + bid + '</span>')
                H.append('<span class="bundle-addr">' + addr + '</span>')
                H.append('<span class="bundle-meta">' + str(bfibre) + 'F &middot; ' + str(blen) + 'm</span>')
                H.append('</div></div>')
            H.append('</div>')

        # Aerial drops
        if jdrops:
            H.append('<div class="aerial-list">')
            for d in jdrops:
                did  = d['ddct_id']
                addr = d['address']
                dlen = d['length_m']
                H.append('<div class="aerial-row">')
                H.append('<div class="aerial-line"></div>')
                H.append('<div class="aerial-box">')
                H.append('<span class="aerial-id">&#x1F4F6; ' + did + '</span>')
                H.append('<span class="aerial-addr">' + addr + '</span>')
                H.append('<span class="aerial-meta">' + str(dlen) + 'm &middot; Aerial drop</span>')
                H.append('</div></div>')
            H.append('</div>')

        # Children (onward cables)
        if outbound:
            H.append('<div class="children">')
            for cid in outbound:
                cable = cables.get(cid)
                if not cable: continue
                to_node = cable['to_node']
                ctype   = cable['cable_type']
                fibre_c = cable['fibre_count']
                length  = cable['length_m']
                col     = CABLE_COLOURS.get(ctype, NAVY)
                is_aerial = (ctype == 'AERIAL')
                line_style = 'border-left:3px ' + ('dashed' if is_aerial else 'solid') + ' ' + col + ';'
                H.append('<div class="cable-branch">')
                H.append('<div class="cable-line" style="' + line_style + '"></div>')
                H.append('<div class="cable-label" style="color:' + col + ';">' + cid + ' &middot; ' + str(fibre_c) + 'F &middot; ' + str(length) + 'm' + (' &#x1F4F6;' if is_aerial else '') + '</div>')
                H.append(render_node(to_node, cables, joints, bundles, aerial_drops, from_node, visited, depth+1))
                H.append('</div>')
            H.append('</div>')
        elif not jbundles and not jdrops:
            H.append('<div class="dark-storage">&#x1F4E6; Dark storage &mdash; do not disturb</div>')
        H.append('</div>')

    return '\n'.join(H)


def generate_sld(output_path, project=None):
    cables, joints, bundles, aerial_drops, from_node, cabinet, area_id = build_network(project=project)
    if not cabinet:
        raise RuntimeError('No cabinet found in project.')

    total_cables  = len(cables)
    total_joints  = len(joints)
    total_bundles = sum(len(v) for v in bundles.values())
    total_drops   = sum(len(v) for v in aerial_drops.values())
    total_length  = round(sum(c['length_m'] for c in cables.values()), 1)
    splitters     = [j for j in joints.values() if j['has_splitter']]

    visited   = set()
    outbound  = from_node.get(cabinet, [])
    tree_html = ''
    for cid in outbound:
        cable = cables.get(cid)
        if not cable: continue
        col   = CABLE_COLOURS.get(cable['cable_type'], NAVY)
        tree_html += '<div class="cable-branch">'
        tree_html += '<div class="cable-line" style="border-color:' + col + ';"></div>'
        tree_html += '<div class="cable-label" style="color:' + col + ';">' + cid + ' &middot; ' + str(cable['fibre_count']) + 'F &middot; ' + str(cable['length_m']) + 'm</div>'
        tree_html += render_node(cable['to_node'], cables, joints, bundles, aerial_drops, from_node, visited)
        tree_html += '</div>'

    CSS = (
        ':root{--navy:#1A3A5C;--teal:#1D7A6E;--orange:#C85A00;--aerial:#00AAFF;--mid:#CBD5E1;--bg:#F4F6F9;}'
        '*{box-sizing:border-box;margin:0;padding:0;}'
        'body{font-family:Consolas,Courier New,monospace;background:var(--bg);color:#1A1A1A;font-size:12px;line-height:1.5;}'
        '.page{max-width:1100px;margin:0 auto;padding:20px;}'
        '.header{background:var(--navy);color:white;border-radius:8px;padding:16px 20px;margin-bottom:16px;}'
        '.header-title{font-size:20px;font-weight:bold;letter-spacing:1px;}'
        '.header-sub{font-size:11px;color:#9FB4CC;margin-top:3px;}'
        '.stat-row{display:flex;gap:16px;margin-top:12px;flex-wrap:wrap;}'
        '.stat{background:rgba(255,255,255,0.1);border-radius:5px;padding:6px 12px;}'
        '.stat-val{font-size:18px;font-weight:bold;color:white;}'
        '.stat-lbl{font-size:9px;color:#9FB4CC;text-transform:uppercase;letter-spacing:0.8px;}'
        '.cabinet{display:inline-flex;align-items:center;gap:10px;background:var(--orange);color:white;'
        'border-radius:6px;padding:10px 16px;font-weight:bold;font-size:13px;margin-bottom:8px;}'
        '.cab-icon{font-size:18px;}'
        '.tree-node{margin-left:0;}'
        '.children{margin-left:32px;border-left:2px solid var(--mid);padding-left:0;}'
        '.cable-branch{position:relative;margin-top:0;}'
        '.cable-line{border-left:3px solid var(--navy);height:24px;margin-left:15px;}'
        '.cable-label{font-size:11px;font-weight:600;padding:2px 0 2px 20px;margin-left:15px;'
        'border-left:3px solid;border-bottom:3px solid;border-color:inherit;display:inline-block;margin-bottom:4px;}'
        '.node-joint{background:white;border:2px solid var(--mid);border-radius:6px;'
        'padding:8px 12px;display:inline-block;min-width:220px;margin:4px 0;}'
        '.node-splitter{border-color:var(--teal);}'
        '.node-eol{border-color:#888;background:#f5f5f5;}'
        '.node-cbt{border-color:var(--aerial);background:#F0F8FF;}'
        '.node-id{font-size:12px;font-weight:bold;color:var(--navy);}'
        '.node-meta{font-size:10px;color:var(--teal);font-weight:600;margin-top:2px;}'
        '.node-cbt .node-meta{color:var(--aerial);}'
        '.node-chamber{font-size:10px;color:#888;margin-top:1px;}'
        '.bundle-list{margin:6px 0 6px 24px;border-left:2px dashed #00CC00;padding-left:8px;}'
        '.bundle-row{display:flex;align-items:flex-start;gap:6px;margin:3px 0;}'
        '.bundle-line{width:14px;height:2px;background:#00CC00;margin-top:10px;flex-shrink:0;}'
        '.bundle-box{background:#F0FFF0;border:1px solid #00CC00;border-radius:4px;padding:4px 8px;font-size:11px;}'
        '.bundle-id{color:#006600;font-weight:600;display:block;}'
        '.bundle-addr{color:#1A1A1A;display:block;margin-top:1px;}'
        '.bundle-meta{color:#888;font-size:10px;display:block;margin-top:1px;}'
        '.aerial-list{margin:6px 0 6px 24px;border-left:2px dashed #00AAFF;padding-left:8px;}'
        '.aerial-row{display:flex;align-items:flex-start;gap:6px;margin:3px 0;}'
        '.aerial-line{width:14px;height:2px;background:#00AAFF;margin-top:10px;flex-shrink:0;}'
        '.aerial-box{background:#F0F8FF;border:1px solid #00AAFF;border-radius:4px;padding:4px 8px;font-size:11px;}'
        '.aerial-id{color:#005E8B;font-weight:600;display:block;}'
        '.aerial-addr{color:#1A1A1A;display:block;margin-top:1px;}'
        '.aerial-meta{color:#888;font-size:10px;display:block;margin-top:1px;}'
        '.dark-storage{font-size:11px;color:#888;margin:6px 0 6px 16px;font-style:italic;}'
        '.legend{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;background:white;'
        'border:1px solid var(--mid);border-radius:6px;padding:10px 14px;}'
        '.leg-item{display:flex;align-items:center;gap:6px;font-size:11px;color:#444;}'
        '.leg-line{width:24px;height:4px;border-radius:2px;}'
        '.footer{margin-top:20px;padding-top:10px;border-top:1px solid var(--mid);'
        'font-size:10px;color:#888;display:flex;justify-content:space-between;}'
        '@media print{body{background:white;font-size:10px;}'
        '.page{padding:8px;max-width:100%;}'
        '.header{border-radius:0;margin-bottom:10px;}'
        '.node-joint{break-inside:avoid;}'
        '.children{break-inside:avoid;}}'
    )

    H = []
    H.append('<!DOCTYPE html><html lang="en"><head>')
    H.append('<meta charset="UTF-8">')
    H.append('<title>' + area_id + ' &middot; Single Line Diagram</title>')
    H.append('<style>' + CSS + '</style>')
    H.append('</head><body><div class="page">')

    H.append('<div class="header">')
    H.append('<div class="header-title">' + area_id + ' &middot; Single Line Diagram</div>')
    H.append('<div class="header-sub">Full network topology &middot; Cabinet to customer &middot; Gigaloch</div>')
    H.append('<div class="stat-row">')
    for lbl, val in [('Cables', total_cables), ('Joints', total_joints),
                     ('UG customers', total_bundles), ('Aerial drops', total_drops),
                     ('Splitters', len(splitters)), ('Total cable (m)', total_length)]:
        H.append('<div class="stat"><div class="stat-val">' + str(val) + '</div><div class="stat-lbl">' + lbl + '</div></div>')
    H.append('</div></div>')

    H.append('<div class="legend">')
    for lbl, col, dashed in [('Spine/Feeder cable', NAVY, False), ('Aerial span cable', AERIAL, True),
                              ('UG bundle', GREEN, False), ('Aerial drop', '#00AAFF', False)]:
        style = 'height:4px;width:24px;border-radius:2px;background:' + col + ';'
        if dashed:
            style = 'height:0;width:24px;border-top:3px dashed ' + col + ';'
        H.append('<div class="leg-item"><div style="' + style + '"></div>' + lbl + '</div>')
    H.append('</div>')

    H.append('<div class="cabinet"><span class="cab-icon">&#x1F4E6;</span>' + cabinet + ' &middot; Cabinet</div>')
    H.append('<div class="tree">' + tree_html + '</div>')

    H.append('<div class="footer">')
    H.append('<span>' + area_id + ' &middot; Single Line Diagram &middot; Gigaloch</span>')
    H.append('<span>Print: Ctrl+P &middot; Save as PDF from print dialog</span>')
    H.append('</div>')
    H.append('</div></body></html>')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(H))
    return output_path


class SLDDialog(QDialog):
    def __init__(self, iface, parent=None, project=None):
        super().__init__(parent)
        self.iface = iface
        self._project = project
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle('Conductor - Single Line Diagram')
        self.setMinimumSize(420, 160)
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)
        header = QLabel('Generate Single Line Diagram')
        header.setStyleSheet('font-size:14px;font-weight:600;color:#1A3A5C;')
        root.addWidget(header)
        sub = QLabel('Generates a full network diagram from cabinet to customer. Print to PDF via Ctrl+P.')
        sub.setWordWrap(True)
        sub.setStyleSheet('font-size:11px;color:#555;')
        root.addWidget(sub)
        row = QHBoxLayout()
        row.addWidget(QLabel('Save to:'))
        self._path_label = QLabel('(choose folder)')
        self._path_label.setStyleSheet('color:#555;font-size:11px;')
        row.addWidget(self._path_label, 1)
        btn_browse = QPushButton('Browse')
        btn_browse.clicked.connect(self._browse)
        row.addWidget(btn_browse)
        root.addLayout(row)
        from qgis.core import QgsSettings
        saved = QgsSettings().value('conductor/sld_dir', '')
        self._out_dir = saved if saved and os.path.exists(saved) else os.path.expanduser('~')
        if self._out_dir != os.path.expanduser('~'):
            self._path_label.setText(self._out_dir)
        btn_row = QHBoxLayout()
        self._btn_gen = QPushButton('Generate SLD')
        self._btn_gen.setStyleSheet(
            'QPushButton{background:#1A3A5C;color:#fff;font-weight:600;padding:7px 18px;border-radius:4px;font-size:12px;}'
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
        d = QFileDialog.getExistingDirectory(self, 'Select output folder', self._out_dir)
        if d:
            self._out_dir = d
            self._path_label.setText(d)
            QgsSettings().setValue('conductor/sld_dir', d)

    def _generate(self):
        if self._out_dir == os.path.expanduser('~'):
            QMessageBox.warning(self, 'No folder selected',
                'Please click Browse and choose a folder to save the SLD to.')
            return
        out_path = os.path.join(self._out_dir, 'SLD.html')
        try:
            generate_sld(out_path, project=self._project)
            reply = QMessageBox.question(
                self, 'Done',
                'SLD saved to:\n' + out_path + '\n\nOpen in browser?',
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                import webbrowser
                webbrowser.open('file:///' + out_path.replace(os.sep, '/'))
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

def open_sld_dialog(iface, parent=None, project=None):
    dlg = SLDDialog(iface, parent, project=project)
    dlg.show()
    return dlg
