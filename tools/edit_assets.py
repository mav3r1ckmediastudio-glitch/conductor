# -*- coding: utf-8 -*-
"""
Conductor — Edit Asset Tools
Click-to-edit for: Cabinet/POP, Chamber, Duct, Joint, Cable, Drop Duct, Bundle.
"""

import math
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QFrame, QMessageBox, QScrollArea, QCheckBox,
)
from qgis.core import (
    QgsProject, QgsFeatureRequest, QgsRectangle,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsWkbTypes,
)
from qgis.gui import QgsMapTool
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE, MONO_STYLE

# ── SHARED HELPERS ────────────────────────────────────────────────────────────

def _find_feature(canvas, project, layer_names, canvas_pos, radius_px=12):
    """Find nearest feature from a list of layers."""
    canvas_crs = canvas.mapSettings().destinationCrs()
    target_crs = QgsCoordinateReferenceSystem("EPSG:27700")
    canvas_pt  = canvas.getCoordinateTransform().toMapCoordinates(canvas_pos)

    if canvas_crs != target_crs:
        xform = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
        pt_27700 = xform.transform(canvas_pt)
    else:
        pt_27700 = canvas_pt

    radius = canvas.mapUnitsPerPixel() * radius_px
    rect   = QgsRectangle(
        pt_27700.x()-radius, pt_27700.y()-radius,
        pt_27700.x()+radius, pt_27700.y()+radius,
    )

    for layer_name in layer_names:
        layer = project.get_layer(layer_name)
        if not layer or layer.featureCount() == 0:
            continue
        for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
            return layer_name, layer, feat

    return None, None, None


def _fv(feat, name, default=""):
    v = feat[name]
    return default if v is None or str(v) == "NULL" else v


def _lbl(t):
    l = QLabel(t); l.setStyleSheet(LABEL_STYLE); return l

def _section(t):
    l = QLabel(t); l.setStyleSheet(SECTION_STYLE); return l

def _divider():
    f = QFrame(); f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{MID}; margin:4px 0px;"); return f

def _inp(ph=""):
    e = QLineEdit(); e.setPlaceholderText(ph); e.setStyleSheet(INPUT_STYLE); return e

def _ro(t):
    e = QLineEdit(str(t)); e.setReadOnly(True); e.setStyleSheet(MONO_STYLE); return e

def _combo(items, current=""):
    c = QComboBox(); c.addItems(items); c.setStyleSheet(INPUT_STYLE)
    idx = c.findText(current)
    if idx >= 0: c.setCurrentIndex(idx)
    return c

def _spin(default=0, lo=0, hi=999):
    s = QSpinBox(); s.setMinimum(lo); s.setMaximum(hi)
    s.setValue(int(default) if default else 0)
    s.setStyleSheet(INPUT_STYLE); return s

def _dspin(default=0.0, lo=0.0, hi=99.9, step=0.1):
    s = QDoubleSpinBox(); s.setMinimum(lo); s.setMaximum(hi)
    s.setSingleStep(step); s.setValue(float(default) if default else 0.0)
    s.setStyleSheet(INPUT_STYLE); return s

def _scrolled_form(root_layout, build_fn):
    scroll = QScrollArea(); scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setStyleSheet(f"background:{LIGHT}; border:none;")
    fw = QFrame(); fw.setStyleSheet(f"background:{LIGHT};")
    fl = QVBoxLayout(fw); fl.setContentsMargins(20,14,20,8); fl.setSpacing(8)
    build_fn(fl)
    scroll.setWidget(fw)
    root_layout.addWidget(scroll)


def _save_attrs(layer, feat, attrs):
    layer.startEditing()
    for fname, fvalue in attrs.items():
        idx = layer.fields().indexOf(fname)
        if idx >= 0:
            layer.changeAttributeValue(feat.id(), idx, fvalue if fvalue != "" else None)
    if layer.commitChanges():
        layer.triggerRepaint()
        return True
    layer.rollBack()
    return False


def _base_dialog(title, asset_id, subtitle=""):
    dlg = QDialog(); dlg.setWindowTitle(title)
    dlg.setMinimumWidth(500); dlg.setMaximumHeight(720); dlg.setModal(True)
    root = QVBoxLayout(dlg); root.setSpacing(0); root.setContentsMargins(0,0,0,0)

    hdr = QLabel(f"  {title}  —  {asset_id}")
    hdr.setFixedHeight(44)
    hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
    root.addWidget(hdr)

    if subtitle:
        sub = QLabel(f"  {subtitle}")
        sub.setFixedHeight(24)
        sub.setStyleSheet(f"background:{TEAL}; color:{WHITE}; font-size:11px; padding-left:8px;")
        root.addWidget(sub)

    return dlg, root


# ═══════════════════════════════════════════════════════════════════════════
# EDIT CHAMBER
# ═══════════════════════════════════════════════════════════════════════════

def _edit_chamber_dialog(feat):
    cid = _fv(feat, "chamber_id")
    dlg, root = _base_dialog("Edit Chamber", cid,
        f"Direction: {_fv(feat,'compass_dir')}  ·  Cabinet: {_fv(feat,'pop_id')}")

    widgets = {}
    def build(fl):
        fl.addWidget(_section("IDENTITY"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)
        f1.addRow(_lbl("Chamber ID"), _ro(cid))

        widgets['chamber_function'] = _combo(
            ["ACCESS", "JOINT", "BURIED_JOINT"], _fv(feat,"chamber_function","ACCESS"))
        f1.addRow(_lbl("Chamber Function"), widgets['chamber_function'])

        widgets['ring_count'] = _spin(_fv(feat,"ring_count",4), 0, 10)
        f1.addRow(_lbl("Ring Count"), widgets['ring_count'])

        widgets['owner'] = _inp("Owner")
        widgets['owner'].setText(_fv(feat,"owner"))
        f1.addRow(_lbl("Owner"), widgets['owner'])

        widgets['pia_ref'] = _inp("Openreach PIA reference")
        widgets['pia_ref'].setText(_fv(feat,"pia_ref"))
        f1.addRow(_lbl("PIA Reference"), widgets['pia_ref'])

        widgets['lid_type'] = _combo(
            ["— not set —","STEEL_CONCRETE","IRON","COMPOSITE","RECESSED"],
            _fv(feat,"lid_type","— not set —"))
        f1.addRow(_lbl("Lid Type"), widgets['lid_type'])

        widgets['depth_m'] = _dspin(_fv(feat,"depth_m",0), 0, 5, 0.1)
        f1.addRow(_lbl("Depth (m)"), widgets['depth_m'])

        widgets['status'] = _combo(
            ["PROPOSED","SURVEY","INSTALLED"], _fv(feat,"status","PROPOSED"))
        f1.addRow(_lbl("Status"), widgets['status'])

        fl.addLayout(f1)
        fl.addWidget(_divider())
        fl.addWidget(_section("NOTES"))
        widgets['notes'] = _inp("Free text notes")
        widgets['notes'].setText(_fv(feat,"notes"))
        fl.addWidget(widgets['notes'])

    _scrolled_form(root, build)

    br = QHBoxLayout(); br.setContentsMargins(20,12,20,16); br.addStretch()
    cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
    cancel.clicked.connect(dlg.reject); br.addWidget(cancel)
    save = QPushButton("Save Changes"); save.setStyleSheet(BTN_PRIMARY)
    save.clicked.connect(dlg.accept); br.addWidget(save)
    root.addLayout(br)

    def get_attrs():
        lid = widgets['lid_type'].currentText()
        return {
            "chamber_function": widgets['chamber_function'].currentText(),
            "ring_count":       widgets['ring_count'].value() or None,
            "owner":            widgets['owner'].text().strip(),
            "pia_ref":          widgets['pia_ref'].text().strip(),
            "lid_type":         lid if not lid.startswith("—") else "",
            "depth_m":          widgets['depth_m'].value() or None,
            "status":           widgets['status'].currentText(),
            "notes":            widgets['notes'].text().strip(),
        }

    return dlg, get_attrs


# ═══════════════════════════════════════════════════════════════════════════
# EDIT DUCT
# ═══════════════════════════════════════════════════════════════════════════

def _edit_duct_dialog(feat):
    did = _fv(feat, "duct_id")
    dlg, root = _base_dialog("Edit Duct", did,
        f"Length: {_fv(feat,'length_m','?')} m  ·  Leg: {_fv(feat,'compass_leg')}")

    widgets = {}
    def build(fl):
        fl.addWidget(_section("DUCT"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)
        f1.addRow(_lbl("Duct ID"), _ro(did))
        f1.addRow(_lbl("Length (m)"), _ro(f"{_fv(feat,'length_m','?')} m"))

        widgets['duct_type'] = _combo(
            ["SHOTGUN","PIA_AERIAL","PIA_SUBDUCT","OWN_DUCT"], _fv(feat,"duct_type","SHOTGUN"))
        f1.addRow(_lbl("Duct Type"), widgets['duct_type'])

        widgets['shotgun_spare'] = QCheckBox("Second barrel available (SHOTGUN only)")
        widgets['shotgun_spare'].setStyleSheet(f"font-size:12px; color:{NAVY};")
        widgets['shotgun_spare'].setChecked(bool(_fv(feat,"shotgun_spare",True)))
        f1.addRow(_lbl(""), widgets['shotgun_spare'])

        widgets['pia_ref'] = _inp("Openreach PIA reference")
        widgets['pia_ref'].setText(_fv(feat,"pia_ref"))
        f1.addRow(_lbl("PIA Reference"), widgets['pia_ref'])

        widgets['surface_type'] = _combo(
            ["FIELD","VERGE","ROAD","PRIVATE","MIXED","AERIAL"], _fv(feat,"surface_type","FIELD"))
        f1.addRow(_lbl("Surface Type"), widgets['surface_type'])

        widgets['depth_m'] = _dspin(_fv(feat,"depth_m",0), 0, 3, 0.1)
        f1.addRow(_lbl("Depth (m)"), widgets['depth_m'])

        widgets['permit_ref'] = _inp("S50 / S171 reference")
        widgets['permit_ref'].setText(_fv(feat,"permit_ref"))
        f1.addRow(_lbl("Permit Ref"), widgets['permit_ref'])

        widgets['wayleave_req'] = QCheckBox("Private wayleave required")
        widgets['wayleave_req'].setStyleSheet(f"font-size:12px; color:{NAVY};")
        widgets['wayleave_req'].setChecked(bool(_fv(feat,"wayleave_req",False)))
        f1.addRow(_lbl(""), widgets['wayleave_req'])

        widgets['status'] = _combo(
            ["PROPOSED","SURVEY","PERMITTED","INSTALLED"], _fv(feat,"status","PROPOSED"))
        f1.addRow(_lbl("Status"), widgets['status'])

        fl.addLayout(f1)
        fl.addWidget(_divider())
        fl.addWidget(_section("NOTES"))
        widgets['notes'] = _inp()
        widgets['notes'].setText(_fv(feat,"notes"))
        fl.addWidget(widgets['notes'])

    _scrolled_form(root, build)

    br = QHBoxLayout(); br.setContentsMargins(20,12,20,16); br.addStretch()
    cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
    cancel.clicked.connect(dlg.reject); br.addWidget(cancel)
    save = QPushButton("Save Changes"); save.setStyleSheet(BTN_PRIMARY)
    save.clicked.connect(dlg.accept); br.addWidget(save)
    root.addLayout(br)

    def get_attrs():
        return {
            "duct_type":    widgets['duct_type'].currentText(),
            "shotgun_spare":widgets['shotgun_spare'].isChecked(),
            "pia_ref":      widgets['pia_ref'].text().strip(),
            "surface_type": widgets['surface_type'].currentText(),
            "depth_m":      widgets['depth_m'].value() or None,
            "permit_ref":   widgets['permit_ref'].text().strip(),
            "wayleave_req": widgets['wayleave_req'].isChecked(),
            "status":       widgets['status'].currentText(),
            "notes":        widgets['notes'].text().strip(),
        }
    return dlg, get_attrs


# ═══════════════════════════════════════════════════════════════════════════
# EDIT JOINT
# ═══════════════════════════════════════════════════════════════════════════

def _edit_joint_dialog(feat):
    jid = _fv(feat, "joint_id")
    dlg, root = _base_dialog("Edit Joint", jid,
        f"Chamber: {_fv(feat,'chamber_id')}")

    widgets = {}
    def build(fl):
        fl.addWidget(_section("JOINT"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)
        f1.addRow(_lbl("Joint ID"), _ro(jid))

        widgets['joint_type'] = _combo(
            ["SPLICE","BLOWING_POINT","END_OF_LINE"], _fv(feat,"joint_type","SPLICE"))
        widgets['joint_type'].currentTextChanged.connect(
            lambda t: widgets['has_splitter'].setEnabled(t=="SPLICE")
        )
        f1.addRow(_lbl("Joint Type"), widgets['joint_type'])

        widgets['closure_type'] = _inp("e.g. Commscope ADP-FS4")
        widgets['closure_type'].setText(_fv(feat,"closure_type"))
        f1.addRow(_lbl("Closure Model"), widgets['closure_type'])

        widgets['status'] = _combo(
            ["PROPOSED","SURVEY","INSTALLED","LIVE"], _fv(feat,"status","PROPOSED"))
        f1.addRow(_lbl("Status"), widgets['status'])

        fl.addLayout(f1)
        fl.addWidget(_divider())
        fl.addWidget(_section("SPLITTER"))

        widgets['has_splitter'] = QCheckBox("Contains a passive optical splitter")
        widgets['has_splitter'].setStyleSheet(f"font-size:12px; color:{NAVY}; font-weight:bold;")
        widgets['has_splitter'].setChecked(bool(_fv(feat,"has_splitter",False)))
        widgets['has_splitter'].setEnabled(_fv(feat,"joint_type","SPLICE")=="SPLICE")
        fl.addWidget(widgets['has_splitter'])

        f2 = QFormLayout(); f2.setSpacing(8); f2.setLabelAlignment(Qt.AlignRight)
        widgets['split_ratio'] = _combo(
            ["— none —","1:2","1:4","1:8","1:16","1:32"], _fv(feat,"split_ratio","— none —"))
        f2.addRow(_lbl("Split Ratio"), widgets['split_ratio'])

        widgets['cascade_level'] = _combo(
            ["— none —","1 — Primary","2 — Secondary"],
            f"{_fv(feat,'cascade_level','')} —" if _fv(feat,'cascade_level') else "— none —")
        f2.addRow(_lbl("Cascade Level"), widgets['cascade_level'])

        widgets['cascade_type'] = _combo(
            ["— none —","URBAN_1_2_1_16","RURAL_1_4_1_8","DIRECT_1_32"],
            _fv(feat,"cascade_type","— none —"))
        f2.addRow(_lbl("Cascade Type"), widgets['cascade_type'])
        fl.addLayout(f2)

        fl.addWidget(_divider())
        fl.addWidget(_section("NOTES"))
        widgets['notes'] = _inp()
        widgets['notes'].setText(_fv(feat,"notes"))
        fl.addWidget(widgets['notes'])

    _scrolled_form(root, build)

    br = QHBoxLayout(); br.setContentsMargins(20,12,20,16); br.addStretch()
    cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
    cancel.clicked.connect(dlg.reject); br.addWidget(cancel)
    save = QPushButton("Save Changes"); save.setStyleSheet(BTN_PRIMARY)
    save.clicked.connect(dlg.accept); br.addWidget(save)
    root.addLayout(br)

    def get_attrs():
        ratio = widgets['split_ratio'].currentText()
        level = widgets['cascade_level'].currentText()
        ctype = widgets['cascade_type'].currentText()
        return {
            "joint_type":    widgets['joint_type'].currentText(),
            "has_splitter":  widgets['has_splitter'].isChecked(),
            "split_ratio":   ratio  if not ratio.startswith("—") else None,
            "cascade_level": int(level[0]) if not level.startswith("—") else None,
            "cascade_type":  ctype  if not ctype.startswith("—") else None,
            "closure_type":  widgets['closure_type'].text().strip(),
            "status":        widgets['status'].currentText(),
            "notes":         widgets['notes'].text().strip(),
        }
    return dlg, get_attrs


# ═══════════════════════════════════════════════════════════════════════════
# EDIT CABLE
# ═══════════════════════════════════════════════════════════════════════════

def _edit_cable_dialog(feat):
    cid = _fv(feat, "cable_id")
    dlg, root = _base_dialog("Edit Cable", cid,
        f"Length: {_fv(feat,'length_m','?')} m  ·  {_fv(feat,'fibre_count','?')}F")

    widgets = {}
    def build(fl):
        fl.addWidget(_section("CABLE"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)
        f1.addRow(_lbl("Cable ID"), _ro(cid))
        f1.addRow(_lbl("Length (m)"), _ro(f"{_fv(feat,'length_m','?')} m"))

        widgets['cable_type'] = _combo(
            ["FEEDER","DISTRIBUTION","BACKHAUL"], _fv(feat,"cable_type","FEEDER"))
        f1.addRow(_lbl("Cable Type"), widgets['cable_type'])

        widgets['fibre_count'] = _combo(
            ["12","24","48","96","144"], str(_fv(feat,"fibre_count","48")))
        f1.addRow(_lbl("Fibre Count"), widgets['fibre_count'])

        widgets['fibre_type'] = _combo(
            ["G.652D","G.657A1","G.657A2"], _fv(feat,"fibre_type","G.652D"))
        f1.addRow(_lbl("Fibre Type"), widgets['fibre_type'])

        widgets['status'] = _combo(
            ["PROPOSED","SURVEY","INSTALLED","LIVE"], _fv(feat,"status","PROPOSED"))
        f1.addRow(_lbl("Status"), widgets['status'])

        fl.addLayout(f1)
        fl.addWidget(_divider())
        fl.addWidget(_section("NOTES"))
        widgets['notes'] = _inp()
        widgets['notes'].setText(_fv(feat,"notes"))
        fl.addWidget(widgets['notes'])

    _scrolled_form(root, build)

    br = QHBoxLayout(); br.setContentsMargins(20,12,20,16); br.addStretch()
    cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
    cancel.clicked.connect(dlg.reject); br.addWidget(cancel)
    save = QPushButton("Save Changes"); save.setStyleSheet(BTN_PRIMARY)
    save.clicked.connect(dlg.accept); br.addWidget(save)
    root.addLayout(br)

    def get_attrs():
        fc = int(widgets['fibre_count'].currentText())
        return {
            "cable_type":  widgets['cable_type'].currentText(),
            "fibre_count": fc,
            "tube_count":  fc // 12,
            "fibre_type":  widgets['fibre_type'].currentText(),
            "status":      widgets['status'].currentText(),
            "notes":       widgets['notes'].text().strip(),
        }
    return dlg, get_attrs


# ═══════════════════════════════════════════════════════════════════════════
# EDIT DROP DUCT
# ═══════════════════════════════════════════════════════════════════════════

def _edit_drop_duct_dialog(feat):
    did = _fv(feat, "ddct_id")
    dlg, root = _base_dialog("Edit Drop Duct", did,
        f"Length: {_fv(feat,'length_m','?')} m  ·  UPRN: {_fv(feat,'uprn')}")

    widgets = {}
    def build(fl):
        fl.addWidget(_section("DROP DUCT  (7mm speedpipe)"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)
        f1.addRow(_lbl("Drop Duct ID"), _ro(did))
        f1.addRow(_lbl("UPRN"), _ro(_fv(feat,"uprn")))
        f1.addRow(_lbl("Length (m)"), _ro(f"{_fv(feat,'length_m','?')} m"))

        widgets['status'] = _combo(
            ["PROPOSED","SURVEY","INSTALLED"], _fv(feat,"status","PROPOSED"))
        f1.addRow(_lbl("Status"), widgets['status'])

        widgets['wayleave_req'] = QCheckBox("Private wayleave required")
        widgets['wayleave_req'].setStyleSheet(f"font-size:12px; color:{NAVY};")
        widgets['wayleave_req'].setChecked(bool(_fv(feat,"wayleave_req",False)))
        f1.addRow(_lbl(""), widgets['wayleave_req'])

        fl.addLayout(f1)
        fl.addWidget(_divider())
        fl.addWidget(_section("NOTES"))
        widgets['notes'] = _inp()
        widgets['notes'].setText(_fv(feat,"notes"))
        fl.addWidget(widgets['notes'])

    _scrolled_form(root, build)

    br = QHBoxLayout(); br.setContentsMargins(20,12,20,16); br.addStretch()
    cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
    cancel.clicked.connect(dlg.reject); br.addWidget(cancel)
    save = QPushButton("Save Changes"); save.setStyleSheet(BTN_PRIMARY)
    save.clicked.connect(dlg.accept); br.addWidget(save)
    root.addLayout(br)

    def get_attrs():
        return {
            "status":       widgets['status'].currentText(),
            "wayleave_req": widgets['wayleave_req'].isChecked(),
            "notes":        widgets['notes'].text().strip(),
        }
    return dlg, get_attrs


# ═══════════════════════════════════════════════════════════════════════════
# EDIT BUNDLE
# ═══════════════════════════════════════════════════════════════════════════

def _edit_bundle_dialog(feat):
    bid = _fv(feat, "bundle_id")
    dlg, root = _base_dialog("Edit Bundle", bid,
        f"Length: {_fv(feat,'length_m','?')} m  ·  UPRN: {_fv(feat,'uprn')}")

    widgets = {}
    def build(fl):
        fl.addWidget(_section("BUNDLE  (1F or 2F to ONT)"))
        f1 = QFormLayout(); f1.setSpacing(8); f1.setLabelAlignment(Qt.AlignRight)
        f1.addRow(_lbl("Bundle ID"), _ro(bid))
        f1.addRow(_lbl("UPRN"), _ro(_fv(feat,"uprn")))
        f1.addRow(_lbl("Length (m)"), _ro(f"{_fv(feat,'length_m','?')} m"))

        widgets['fibre_count'] = _combo(["1","2"], str(_fv(feat,"fibre_count","2")))
        f1.addRow(_lbl("Fibre Count"), widgets['fibre_count'])

        widgets['ont_serial'] = _inp("ONT serial — populate on installation day")
        widgets['ont_serial'].setText(_fv(feat,"ont_serial"))
        f1.addRow(_lbl("ONT Serial"), widgets['ont_serial'])

        widgets['status'] = _combo(
            ["PROPOSED","SURVEY","INSTALLED","LIVE","CEASED"], _fv(feat,"status","PROPOSED"))
        f1.addRow(_lbl("Status"), widgets['status'])

        widgets['wayleave_req'] = QCheckBox("Private wayleave required")
        widgets['wayleave_req'].setStyleSheet(f"font-size:12px; color:{NAVY};")
        widgets['wayleave_req'].setChecked(bool(_fv(feat,"wayleave_req",False)))
        f1.addRow(_lbl(""), widgets['wayleave_req'])

        fl.addLayout(f1)
        fl.addWidget(_divider())
        fl.addWidget(_section("NOTES"))
        widgets['notes'] = _inp()
        widgets['notes'].setText(_fv(feat,"notes"))
        fl.addWidget(widgets['notes'])

    _scrolled_form(root, build)

    br = QHBoxLayout(); br.setContentsMargins(20,12,20,16); br.addStretch()
    cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
    cancel.clicked.connect(dlg.reject); br.addWidget(cancel)
    save = QPushButton("Save Changes"); save.setStyleSheet(BTN_PRIMARY)
    save.clicked.connect(dlg.accept); br.addWidget(save)
    root.addLayout(br)

    def get_attrs():
        return {
            "fibre_count":  int(widgets['fibre_count'].currentText()),
            "ont_serial":   widgets['ont_serial'].text().strip(),
            "status":       widgets['status'].currentText(),
            "wayleave_req": widgets['wayleave_req'].isChecked(),
            "notes":        widgets['notes'].text().strip(),
        }
    return dlg, get_attrs


# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED EDIT MAP TOOL
# ═══════════════════════════════════════════════════════════════════════════

def _edit_pop_dialog(feat):
    """Adapter for the Cabinet/POP edit dialog so it fits the same
    dialog_fn(feat) -> (dlg, get_attrs) pattern as the other asset types."""
    from .place_pop import CabinetDialog
    pop_id  = _fv(feat, "pop_id", "unknown")
    area_id = _fv(feat, "area_id", "")
    dlg = CabinetDialog(point=None, pop_id=pop_id, area_id=area_id, existing_feat=feat)
    return dlg, dlg.get_attributes


EDIT_LAYER_MAP = {
    "exchange_pops": ("exchange_pops", _edit_pop_dialog,      "pop_id"),
    "chambers":   ("chambers",   _edit_chamber_dialog,  "chamber_id"),
    "ducts":      ("ducts",      _edit_duct_dialog,     "duct_id"),
    "joints":     ("joints",     _edit_joint_dialog,    "joint_id"),
    "cables":     ("cables",     _edit_cable_dialog,    "cable_id"),
    "drop_ducts": ("drop_ducts", _edit_drop_duct_dialog,"ddct_id"),
    "bundles":    ("bundles",    _edit_bundle_dialog,   "bundle_id"),
}

# Priority order for click detection
EDIT_SEARCH_ORDER = ["exchange_pops","chambers","joints","ducts","cables","drop_ducts","bundles"]


class EditAssetMapTool(QgsMapTool):
    """
    Click any Conductor asset to edit it.
    Searches exchange_pops (cabinets/POPs), chambers, joints, ducts, cables,
    drop ducts, and bundles.
    """

    edited = pyqtSignal(str, str)  # layer_name, asset_id

    def __init__(self, canvas, project):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        layer_name, layer, feat = _find_feature(
            self._canvas, self._project, EDIT_SEARCH_ORDER, event.pos()
        )

        if feat is None:
            QMessageBox.information(None, "Conductor",
                "No editable asset found at that location.\n"
                "Click closer to a cabinet, chamber, duct, joint, cable, drop duct, or bundle.")
            return

        if layer_name not in EDIT_LAYER_MAP:
            return

        _, dialog_fn, id_field = EDIT_LAYER_MAP[layer_name]
        asset_id = str(feat[id_field])

        dlg, get_attrs = dialog_fn(feat)
        if dlg.exec_() != QDialog.Accepted:
            return

        attrs = get_attrs()
        if _save_attrs(layer, feat, attrs):
            self.edited.emit(layer_name, asset_id)
        else:
            QMessageBox.critical(None, "Error", f"Failed to save changes to {asset_id}.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._canvas.unsetMapTool(self)
