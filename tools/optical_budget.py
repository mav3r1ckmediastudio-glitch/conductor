"""
optical_budget.py — Conductor FTTP Network Design Plugin
Optical power budget defaults, persistence, and settings dialog used by the
Fibre Route Validator's per-premises loss/margin calculation.

UK GPON/XGS-PON defaults assume G.652D fibre at 1310/1550nm.
"""

import re
import math

from qgis.core import QgsSettings


OPTICAL_SETTINGS_PREFIX = "conductor/optical_budget/"


# ── Defaults ───────────────────────────────────────────────────────────────

DEFAULT_OPTICAL = {
    "fibre_atten_db_km": 0.25,   # G.652D @ 1310/1550nm
    "splice_loss_db":    0.10,   # per fusion splice (through joint)
    "connector_loss_db": 1.50,   # flat termination allowance — POP + CBT + ONT (3 x 0.5dB)
    "link_class":        "B+",
    "safety_margin_db":  3.0,
}

DEFAULT_SPLITTER_LOSS_DB = {
    "1:2":  3.5,
    "1:4":  7.0,
    "1:8":  10.5,
    "1:16": 14.0,
    "1:32": 17.5,
}

# GPON/XGS-PON optical link class budgets (Tx min — Rx sensitivity), dB
LINK_CLASS_BUDGET_DB = {
    "B+": 28.0,
    "C+": 32.0,
}

_SPLITTER_KEY_MAP = {
    "1:2":  "splitter_1_2_db",
    "1:4":  "splitter_1_4_db",
    "1:8":  "splitter_1_8_db",
    "1:16": "splitter_1_16_db",
    "1:32": "splitter_1_32_db",
}


# ── Persistence ───────────────────────────────────────────────────────────

def load_optical():
    """Load optical power budget settings from QgsSettings, falling back to
    defaults. Returns a dict with all DEFAULT_OPTICAL keys plus a nested
    'splitter_loss_db' dict keyed by split_ratio string (e.g. '1:8')."""
    s = QgsSettings()
    optical = {}
    for key, default in DEFAULT_OPTICAL.items():
        val = s.value(OPTICAL_SETTINGS_PREFIX + key, None)
        if val is None:
            optical[key] = default
        elif key == "link_class":
            optical[key] = str(val)
        else:
            optical[key] = float(val)

    splitter_loss_db = {}
    for ratio, default in DEFAULT_SPLITTER_LOSS_DB.items():
        setting_key = _SPLITTER_KEY_MAP[ratio]
        val = s.value(OPTICAL_SETTINGS_PREFIX + setting_key, None)
        splitter_loss_db[ratio] = float(val) if val is not None else default
    optical["splitter_loss_db"] = splitter_loss_db
    return optical


def save_optical(optical):
    """Persist optical power budget settings to QgsSettings."""
    s = QgsSettings()
    for key in DEFAULT_OPTICAL:
        if key in optical:
            s.setValue(OPTICAL_SETTINGS_PREFIX + key, optical[key])
    splitter_loss_db = optical.get("splitter_loss_db", {})
    for ratio, setting_key in _SPLITTER_KEY_MAP.items():
        if ratio in splitter_loss_db:
            s.setValue(OPTICAL_SETTINGS_PREFIX + setting_key, float(splitter_loss_db[ratio]))


# ── Loss / budget helpers ────────────────────────────────────────────────

def splitter_loss_for_ratio(ratio_str, splitter_loss_db):
    """Return the insertion loss (dB) for a split_ratio string such as
    '1:8'. Falls back to a theoretical 10*log10(N) + 1.5dB excess-loss
    estimate for ratios not present in the table."""
    if not ratio_str:
        return 0.0
    ratio_str = str(ratio_str).strip()
    if ratio_str in splitter_loss_db:
        return splitter_loss_db[ratio_str]
    m = re.match(r"1\s*:\s*(\d+)", ratio_str)
    if m:
        n = int(m.group(1))
        if n > 0:
            return 10 * math.log10(n) + 1.5
    return 0.0


def link_budget_db(optical):
    """Return the usable loss budget (dB) for the configured link class,
    after deducting the configured safety margin."""
    cls = optical.get("link_class", "B+")
    budget = LINK_CLASS_BUDGET_DB.get(cls, LINK_CLASS_BUDGET_DB["B+"])
    return budget - optical.get("safety_margin_db", DEFAULT_OPTICAL["safety_margin_db"])


def calculate_link_budget(uprn, area_id, bundle_idx, ddct_idx, joint_idx,
                           cable_node_idx, optical=None):
    """Trace a premises back to the cabinet (as trace_premises does) and
    additionally compute the optical power budget for that route.

    Returns a dict:
        status, path, reason          -- as returned by trace_premises
        loss_db, budget_db, margin_db -- None if the route isn't complete
        link_pass                     -- True/False, or None if no loss_db
        optical                       -- the settings dict used
        breakdown                     -- per-element loss breakdown dict,
                                          only populated when status is OK:
            fibre_db, fibre_length_m, splice_db, splice_count,
            splitter_db, splitters (list of ratio strings), connector_db

    This is the single source of truth for optical budget figures shown in
    the Fibre Trace popup and (in future) on the SLD export -- both should
    call this rather than re-deriving loss figures independently.
    """
    from .validate_routes import trace_premises

    if optical is None:
        optical = load_optical()

    breakdown = {}
    status, path, reason, loss_db = trace_premises(
        uprn, area_id, bundle_idx, ddct_idx, joint_idx, cable_node_idx,
        optical=optical, breakdown=breakdown,
    )

    result = {
        "status": status,
        "path": path,
        "reason": reason,
        "loss_db": loss_db,
        "optical": optical,
        "breakdown": breakdown,
    }

    if loss_db is not None:
        budget_db = link_budget_db(optical)
        result["budget_db"] = budget_db
        result["margin_db"] = budget_db - loss_db
        result["link_pass"] = result["margin_db"] >= 0
    else:
        result["budget_db"] = None
        result["margin_db"] = None
        result["link_pass"] = None

    return result


# ── Settings dialog ──────────────────────────────────────────────────────

def edit_optical_dialog(parent, on_saved=None):
    """Open a dialog to edit and persist the optical power budget settings
    used by the Fibre Route Validator's loss/margin calculation."""
    from qgis.PyQt.QtWidgets import (
        QDialog, QFormLayout, QDialogButtonBox, QScrollArea, QWidget,
        QVBoxLayout, QLabel, QDoubleSpinBox, QComboBox, QPushButton
    )

    optical = load_optical()

    dlg = QDialog(parent)
    dlg.setWindowTitle("Optical Power Budget Settings")
    dlg.setMinimumWidth(380)
    root = QVBoxLayout(dlg)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    fw = QWidget()
    fl = QFormLayout(fw)
    fl.setSpacing(6)

    spinboxes = {}

    def _add_spin(key, label, maximum=100.0, decimals=2):
        sb = QDoubleSpinBox()
        sb.setDecimals(decimals)
        sb.setMinimum(0)
        sb.setMaximum(maximum)
        sb.setSuffix(" dB")
        sb.setValue(optical.get(key, DEFAULT_OPTICAL.get(key, 0.0)))
        fl.addRow(QLabel(label), sb)
        spinboxes[key] = sb

    _add_spin("fibre_atten_db_km", "Fibre attenuation (per km)", maximum=10.0)
    _add_spin("splice_loss_db",    "Splice loss (per fusion splice)", maximum=5.0)
    _add_spin("connector_loss_db", "Termination loss (POP + CBT + ONT, flat)", maximum=10.0)
    _add_spin("safety_margin_db",  "Safety margin", maximum=10.0)

    link_combo = QComboBox()
    for cls, budget in LINK_CLASS_BUDGET_DB.items():
        link_combo.addItem(f"{cls}  ({budget:.0f} dB budget)", cls)
    current_idx = link_combo.findData(optical.get("link_class", "B+"))
    if current_idx >= 0:
        link_combo.setCurrentIndex(current_idx)
    fl.addRow(QLabel("Link class"), link_combo)

    fl.addRow(QLabel("<b>Splitter insertion loss</b>"))

    splitter_loss_db = optical.get("splitter_loss_db", dict(DEFAULT_SPLITTER_LOSS_DB))
    splitter_spinboxes = {}
    for ratio, default in DEFAULT_SPLITTER_LOSS_DB.items():
        sb = QDoubleSpinBox()
        sb.setDecimals(2)
        sb.setMinimum(0)
        sb.setMaximum(40.0)
        sb.setSuffix(" dB")
        sb.setValue(splitter_loss_db.get(ratio, default))
        fl.addRow(QLabel(f"Splitter {ratio}"), sb)
        splitter_spinboxes[ratio] = sb

    scroll.setWidget(fw)
    root.addWidget(scroll)

    reset_btn = QPushButton("Reset to Defaults")

    def _reset():
        for k, sb in spinboxes.items():
            sb.setValue(DEFAULT_OPTICAL[k])
        for ratio, sb in splitter_spinboxes.items():
            sb.setValue(DEFAULT_SPLITTER_LOSS_DB[ratio])
        idx = link_combo.findData(DEFAULT_OPTICAL["link_class"])
        if idx >= 0:
            link_combo.setCurrentIndex(idx)

    reset_btn.clicked.connect(_reset)
    root.addWidget(reset_btn)

    btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    root.addWidget(btns)

    if dlg.exec_() == QDialog.Accepted:
        new_optical = {k: sb.value() for k, sb in spinboxes.items()}
        new_optical["link_class"] = link_combo.currentData()
        new_optical["splitter_loss_db"] = {r: sb.value() for r, sb in splitter_spinboxes.items()}
        save_optical(new_optical)
        if on_saved:
            on_saved()
