# -*- coding: utf-8 -*-
"""
Conductor — New Project Wizard
Collects project details and creates a new Conductor GeoPackage
with all 14 layers per the v0.4 data model.
"""

import os
import re

from qgis.PyQt.QtCore import Qt, QRegExp
from qgis.PyQt.QtGui import QRegExpValidator
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QFileDialog,
    QFrame, QMessageBox, QProgressBar, QSizePolicy,
)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFields,
    QgsWkbTypes, QgsCoordinateReferenceSystem,
    QgsVectorFileWriter,
)
from qgis.PyQt.QtCore import QVariant
from .conductor_utils import NAVY, TEAL, ORANGE, LIGHT, WHITE, MID

V = QVariant

def _f(name, typ, length=0):
    return (name, typ, length)

# ═══════════════════════════════════════════════════════════════════════════
# LAYER SCHEMA — v0.4
# (layer_name, geometry_type, [(field_name, QVariant.Type, length)])
# geometry_type: "Point" | "LineString" | "Polygon" | "None"
# ═══════════════════════════════════════════════════════════════════════════

LAYER_SCHEMA = [

    ("build_areas", "Polygon", [
        _f("area_id",      V.String,  20),
        _f("area_name",    V.String, 100),
        _f("country_code", V.String,   4),
        _f("build_code",   V.String,   6),
        _f("phase",        V.Int,      0),
        _f("status",       V.String,  20),
        _f("designer",     V.String,  60),
        _f("project_mgr",  V.String,  60),
        _f("notes",        V.String, 500),
    ]),

    ("premises", "Point", [
        _f("uprn",            V.LongLong,  0),
        _f("uprn_confirmed",  V.Bool,      0),
        _f("address_1",       V.String,  100),
        _f("address_2",       V.String,  100),
        _f("town",            V.String,   60),
        _f("postcode",        V.String,    8),
        _f("premise_type",    V.String,   20),
        _f("mdu_units",       V.Int,       0),
        _f("mdu_parent_uprn", V.LongLong,  0),
        _f("current_tech",    V.String,   20),
        _f("current_speed",   V.Int,       0),
        _f("demand_tier",     V.String,   10),
        _f("registered",      V.Bool,      0),
        _f("voucher_ref",     V.String,   30),
        _f("area_id",         V.String,   20),
        _f("notes",           V.String,  500),
    ]),

    ("exchange_pops", "Point", [
        _f("pop_id",            V.String,  30),
        _f("pop_name",          V.String, 100),
        _f("area_id",           V.String,  20),
        _f("pop_type",          V.String,  20),
        _f("operator",          V.String,  60),
        _f("address",           V.String, 200),
        _f("postcode",          V.String,   8),
        _f("dux_shelves",       V.Int,      0),
        _f("calix_shelves",     V.Int,      0),
        _f("gpon_cards",        V.Int,      0),
        _f("gpon_optics",       V.Int,      0),
        _f("battery_sets",      V.Int,      0),
        _f("patch_panels",      V.Int,      0),
        _f("has_aggreg_router", V.Bool,     0),
        _f("max_customers",     V.Int,      0),
        _f("power_supply",      V.String,  20),
        _f("lease_expiry",      V.String,  10),
        _f("status",            V.String,  20),
        _f("photo_ref",         V.String, 200),
        _f("notes",             V.String, 500),
    ]),

    ("chambers", "Point", [
        _f("chamber_id",          V.String,  40),
        _f("chamber_seq",         V.Int,      0),
        _f("spur_suffix",         V.String,   6),
        _f("compass_dir",         V.String,   1),
        _f("pop_id",              V.String,  30),
        _f("area_id",             V.String,  20),
        _f("chamber_type",        V.String,  20),
        _f("ring_count",          V.Int,      0),
        _f("owner",               V.String,  60),
        _f("pia_ref",             V.String,  40),
        _f("lid_type",            V.String,  20),
        _f("depth_m",             V.Double,   0),
        _f("installed_date",      V.String,  10),
        _f("status",              V.String,  20),
        _f("photo_ref",           V.String, 200),
        _f("notes",               V.String, 500),
        _f("openreach_ref",       V.String,  40),
        _f("pole_type",           V.String,  20),
        _f("attachment_height_m", V.Double,   0),
        _f("surface_type",        V.String,  20),  # PIA UG chambers: FOOTWAY/VERGE/CARRIAGEWAY/PRIVATE
    ]),

    ("poles", "Point", [
        _f("pole_id",        V.String,  30),
        _f("area_id",        V.String,  20),
        _f("pole_type",      V.String,  10),
        _f("owner",          V.String,  60),
        _f("pia_ref",        V.String,  40),
        _f("height_m",       V.Double,   0),
        _f("condition",      V.String,  20),
        _f("installed_date", V.String,  10),
        _f("status",         V.String,  20),
        _f("photo_ref",      V.String, 200),
        _f("notes",          V.String, 500),
    ]),

    ("ducts", "LineString", [
        _f("duct_id",        V.String,  40),
        _f("duct_seq",       V.Int,      0),
        _f("spur_suffix",    V.String,   6),
        _f("compass_leg",    V.String,   1),
        _f("from_node",      V.String,  40),
        _f("from_node_type", V.String,  10),
        _f("to_node",        V.String,  40),
        _f("to_node_type",   V.String,  10),
        _f("pop_id",         V.String,  30),
        _f("area_id",        V.String,  20),
        _f("duct_type",      V.String,  20),
        _f("shotgun_spare",  V.Bool,     0),
        _f("pia_ref",        V.String,  40),
        _f("owner",          V.String,  60),
        _f("length_m",       V.Double,   0),
        _f("surface_type",   V.String,  30),
        _f("depth_m",        V.Double,   0),
        _f("permit_ref",     V.String,  40),
        _f("permit_expiry",  V.String,  10),
        _f("wayleave_req",   V.Bool,     0),
        _f("wayleave_id",    V.String,  30),
        _f("installed_date", V.String,  10),
        _f("status",         V.String,  20),
        _f("notes",          V.String, 500),
        _f("from_pole",      V.String,  30),
        _f("to_pole",        V.String,  30),
        _f("openreach_ref",  V.String,  40),
    ]),

    ("cables", "LineString", [
        _f("cable_id",       V.String,  30),
        _f("area_id",        V.String,  20),
        _f("pop_id",         V.String,  30),
        _f("duct_id",        V.String,  40),
        _f("cable_type",     V.String,  20),
        _f("fibre_count",    V.Int,      0),
        _f("tube_count",     V.Int,      0),
        _f("fibre_type",     V.String,  20),
        _f("from_node",      V.String,  40),
        _f("from_node_type", V.String,  20),
        _f("to_node",        V.String,  40),
        _f("to_node_type",   V.String,  20),
        _f("length_m",       V.Double,   0),
        _f("installed_date", V.String,  10),
        _f("status",         V.String,  20),
        _f("notes",          V.String, 500),
    ]),

    ("fibre_assignments", "None", [
        _f("assign_id",       V.String,  50),
        _f("cable_id",        V.String,  30),
        _f("tube_number",     V.Int,      0),
        _f("fibre_number",    V.Int,      0),
        _f("fibre_role",      V.String,  20),
        _f("splitter_id",     V.String,  30),
        _f("splice_to_cable", V.String,  30),
        _f("splice_to_tube",  V.Int,      0),
        _f("splice_to_fibre", V.Int,      0),
        _f("joint_id",        V.String,  30),
        _f("bundle_id",       V.String,  30),
        _f("notes",           V.String, 500),
    ]),

    ("joints", "Point", [
        _f("joint_id",       V.String,  30),
        _f("chamber_id",     V.String,  40),
        _f("area_id",        V.String,  20),
        _f("pop_id",         V.String,  30),
        _f("joint_type",     V.String,  20),
        _f("has_splitter",   V.Bool,     0),
        _f("split_ratio",    V.String,  10),
        _f("cascade_level",  V.Int,      0),
        _f("cascade_type",   V.String,  20),
        _f("closure_type",   V.String,  40),
        _f("fibre_in",       V.Int,      0),
        _f("fibre_out",      V.Int,      0),
        _f("installed_date", V.String,  10),
        _f("status",         V.String,  20),
        _f("photo_ref",      V.String, 200),
        _f("notes",          V.String, 500),
        _f("pole_id",        V.String,  30),
        _f("cbt_model",      V.String,  40),
    ]),

    ("drop_ducts", "LineString", [
        _f("ddct_id",       V.String,  30),
        _f("uprn",          V.LongLong, 0),
        _f("area_id",       V.String,  20),
        _f("from_chamber",  V.String,  40),
        _f("length_m",      V.Double,   0),
        _f("installed_date",V.String,  10),
        _f("status",        V.String,  20),
        _f("wayleave_req",  V.Bool,     0),
        _f("wayleave_id",   V.String,  30),
        _f("notes",         V.String, 500),
        _f("drop_type",     V.String,  30),
        _f("from_pole",     V.String,  30),
    ]),

    ("bundles", "LineString", [
        _f("bundle_id",      V.String,  30),
        _f("uprn",           V.LongLong, 0),
        _f("area_id",        V.String,  20),
        _f("from_joint",     V.String,  30),
        _f("ddct_id",        V.String,  30),
        _f("fibre_count",    V.Int,      0),
        _f("length_m",       V.Double,   0),
        _f("ont_serial",     V.String,  40),
        _f("installed_date", V.String,  10),
        _f("status",         V.String,  20),
        _f("wayleave_req",   V.Bool,     0),
        _f("wayleave_id",    V.String,  30),
        _f("notes",          V.String, 500),
    ]),

    ("surveys", "Point", [
        _f("survey_id",        V.String,  30),
        _f("survey_type",      V.String,  20),
        _f("surveyor",         V.String,  60),
        _f("survey_date",      V.String,  10),
        _f("area_id",          V.String,  20),
        _f("asset_type",       V.String,  20),
        _f("asset_id",         V.String,  40),
        _f("condition",        V.String,  20),
        _f("obstruction",      V.Bool,     0),
        _f("obstruction_note", V.String, 200),
        _f("pia_available",    V.Bool,     0),
        _f("photo_ref",        V.String, 200),
        _f("notes",            V.String, 500),
    ]),

    ("wayleaves", "Polygon", [
        _f("wayleave_id",     V.String,  30),
        _f("area_id",         V.String,  20),
        _f("landowner",       V.String, 100),
        _f("contact_name",    V.String,  60),
        _f("contact_email",   V.String, 100),
        _f("contact_phone",   V.String,  20),
        _f("wayleave_type",   V.String,  20),
        _f("status",          V.String,  20),
        _f("date_approached", V.String,  10),
        _f("date_granted",    V.String,  10),
        _f("expiry_date",     V.String,  10),
        _f("annual_fee",      V.Double,   0),
        _f("doc_ref",         V.String, 200),
        _f("notes",           V.String, 500),
    ]),

    ("build_tasks", "LineString", [
        _f("task_id",        V.String,  30),
        _f("job_number",     V.String,  20),
        _f("area_id",        V.String,  20),
        _f("pop_id",         V.String,  30),
        _f("task_name",      V.String, 100),
        _f("task_type",      V.String,  30),
        _f("contractor",     V.String,  60),
        _f("planned_start",  V.String,  10),
        _f("planned_end",    V.String,  10),
        _f("actual_start",   V.String,  10),
        _f("actual_end",     V.String,  10),
        _f("duct_length_m",  V.Double,   0),
        _f("chamber_count",  V.Int,      0),
        _f("permit_ref",     V.String,  40),
        _f("permit_expiry",  V.String,  10),
        _f("status",         V.String,  20),
        _f("completion_pct", V.Int,      0),
        _f("notes",          V.String, 500),
    ]),

    ("customers", "Point", [
        _f("customer_id",    V.String,  30),
        _f("uprn",           V.LongLong, 0),
        _f("area_id",        V.String,  20),
        _f("account_ref",    V.String,  40),
        _f("service_type",   V.String,  20),
        _f("product",        V.String,  60),
        _f("ont_serial",     V.String,  40),
        _f("connected_date", V.String,  10),
        _f("status",         V.String,  20),
        _f("notes",          V.String, 200),
    ]),
]

WKB_MAP = {
    "Point":      QgsWkbTypes.Point,
    "LineString":  QgsWkbTypes.LineString,
    "Polygon":    QgsWkbTypes.Polygon,
    "None":       QgsWkbTypes.NoGeometry,
}

LAYER_DISPLAY_NAMES = {
    "build_areas":       "Build Areas",
    "premises":          "Premises",
    "exchange_pops":     "Exchanges & POPs",
    "chambers":          "Chambers",
    "poles":             "Poles",
    "ducts":             "Ducts",
    "cables":      "Cables",
    "fibre_assignments": "Fibre Assignments",
    "joints":            "Joints",
    "drop_ducts":        "Drop Ducts",
    "bundles":           "Bundles",
    "surveys":           "Survey Records",
    "wayleaves":         "Wayleaves",
    "build_tasks":       "Build Tasks",
    "customers":         "Customers",
}

LAYER_GROUPS = {
    "Reference":              ["build_areas", "premises"],
    "Active Equipment":       ["exchange_pops"],
    "Fibre Network":          ["joints", "bundles", "cables", "fibre_assignments"],
    "Civil Last Mile":        ["drop_ducts"],
    "Passive Infrastructure": ["chambers", "ducts"],
    "Survey & Wayleave":      ["surveys", "wayleaves"],
    "Build & Progress":       ["build_tasks"],
    "Customers":              ["customers"],
}


# ═══════════════════════════════════════════════════════════════════════════
# DIALOG
# ═══════════════════════════════════════════════════════════════════════════

class NewProjectDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conductor — New Project")
        self.setMinimumWidth(540)
        self.setModal(True)
        self._gpkg_path = ""
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QLabel("  New Conductor Project")
        header.setFixedHeight(48)
        header.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:15px; font-weight:bold;")
        root.addWidget(header)

        # Form
        fw = QFrame()
        fw.setStyleSheet(f"background:{LIGHT};")
        fl = QVBoxLayout(fw)
        fl.setContentsMargins(24, 20, 24, 8)
        fl.setSpacing(4)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        ls = f"color:{NAVY}; font-weight:bold; font-size:12px;"
        ins = f"border:1px solid {MID}; border-radius:3px; padding:5px 8px; background:{WHITE}; font-size:12px;"

        def lbl(t):
            l = QLabel(t); l.setStyleSheet(ls); return l
        def inp(ph="", ml=100):
            e = QLineEdit(); e.setPlaceholderText(ph); e.setMaxLength(ml); e.setStyleSheet(ins); return e

        self.project_name = inp("e.g. Tyndrum Rural FTTP")
        form.addRow(lbl("Project Name *"), self.project_name)

        self.country_code = QComboBox()
        self.country_code.addItems(["SCOT", "ENG", "WAL", "NIR"])
        self.country_code.setStyleSheet(ins)
        form.addRow(lbl("Country *"), self.country_code)

        self.build_code = inp("e.g. TTY", 6)
        self.build_code.setValidator(QRegExpValidator(QRegExp("[A-Z0-9]{1,6}"), self))
        self.build_code.setToolTip("2–6 uppercase letters/numbers. Used in all asset IDs e.g. SCOT-TTY-DUCT-001")
        form.addRow(lbl("Build Area Code *"), self.build_code)

        self.designer = inp("Designer name")
        form.addRow(lbl("Designer"), self.designer)

        self.project_mgr = inp("Project manager name")
        form.addRow(lbl("Project Manager"), self.project_mgr)

        fl.addLayout(form)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{MID}; margin:12px 0px;")
        fl.addWidget(sep)

        fl.addWidget(lbl("GeoPackage Save Location *"))
        pr = QHBoxLayout()
        self.gpkg_path_display = QLineEdit()
        self.gpkg_path_display.setPlaceholderText("Choose where to save the .gpkg file…")
        self.gpkg_path_display.setReadOnly(True)
        self.gpkg_path_display.setStyleSheet(ins + f"background:{MID};")
        pr.addWidget(self.gpkg_path_display)
        bb = QPushButton("Browse…")
        bb.setStyleSheet(f"background:{TEAL}; color:{WHITE}; border:none; border-radius:3px; padding:6px 14px; font-size:12px; font-weight:bold;")
        bb.clicked.connect(self._browse)
        pr.addWidget(bb)
        fl.addLayout(pr)

        hint = QLabel("All 14 Conductor layers will be created in the GeoPackage with EPSG:27700.")
        hint.setStyleSheet(f"color:{MID}; font-size:10px; padding-top:2px;")
        fl.addWidget(hint)
        root.addWidget(fw)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setStyleSheet(f"QProgressBar::chunk {{ background:{TEAL}; }}")
        root.addWidget(self.progress)

        br = QHBoxLayout()
        br.setContentsMargins(24, 12, 24, 16)
        br.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(f"background:{WHITE}; color:{NAVY}; border:1px solid {MID}; border-radius:3px; padding:7px 20px; font-size:12px;")
        cancel.clicked.connect(self.reject)
        br.addWidget(cancel)
        self.create_btn = QPushButton("Create Project")
        self.create_btn.setStyleSheet(f"background:{NAVY}; color:{WHITE}; border:none; border-radius:3px; padding:7px 20px; font-size:12px; font-weight:bold;")
        self.create_btn.clicked.connect(self._on_create)
        br.addWidget(self.create_btn)
        root.addLayout(br)

    def _browse(self):
        code = self.build_code.text().strip() or "conductor"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Conductor GeoPackage",
            os.path.expanduser(f"~/Documents/{code}.gpkg"),
            "GeoPackage (*.gpkg)"
        )
        if path:
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"
            self._gpkg_path = path
            self.gpkg_path_display.setText(path)

    def _validate(self):
        errors = []
        if not self.project_name.text().strip():
            errors.append("Project Name is required.")
        code = self.build_code.text().strip()
        if not code:
            errors.append("Build Area Code is required.")
        elif not re.match(r'^[A-Z0-9]{2,6}$', code):
            errors.append("Build Area Code must be 2–6 uppercase letters or numbers.")
        if not self._gpkg_path:
            errors.append("Please choose a save location for the GeoPackage.")
        return errors

    def _on_create(self):
        errors = self._validate()
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return
        self.create_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(LAYER_SCHEMA))
        self.progress.setValue(0)
        try:
            self._create_geopackage()
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error Creating Project", str(e))
            self.create_btn.setEnabled(True)
            self.progress.setVisible(False)

    def _create_geopackage(self):
        gpkg = self._gpkg_path
        os.makedirs(os.path.dirname(gpkg) or ".", exist_ok=True)
        if os.path.exists(gpkg):
            os.remove(gpkg)

        crs = QgsCoordinateReferenceSystem("EPSG:27700")
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.fileEncoding = "UTF-8"
        first = True

        for i, (layer_name, geom_type_str, field_defs) in enumerate(LAYER_SCHEMA):
            mem_uri = "none" if geom_type_str == "None" else f"{geom_type_str}?crs=EPSG:27700"
            mem_layer = QgsVectorLayer(mem_uri, layer_name, "memory")
            mem_layer.startEditing()
            try:
                for fname, ftype, flen in field_defs:
                    field = QgsField(name=fname, type=ftype)
                    if flen > 0:
                        field.setLength(flen)
                    mem_layer.addAttribute(field)
                mem_layer.commitChanges()
            except Exception as e:
                mem_layer.rollBack()
                raise RuntimeError(f"Failed to build schema for layer '{layer_name}': {e}") from e

            options.layerName = layer_name
            options.actionOnExistingFile = (
                QgsVectorFileWriter.CreateOrOverwriteFile if first
                else QgsVectorFileWriter.CreateOrOverwriteLayer
            )
            first = False

            error, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
                mem_layer, gpkg,
                QgsProject.instance().transformContext(),
                options
            )
            if error != QgsVectorFileWriter.NoError:
                raise RuntimeError(f"Failed to write layer '{layer_name}': {msg}")

            self.progress.setValue(i + 1)

        self.result_gpkg         = gpkg
        self.result_project_name = self.project_name.text().strip()
        self.result_country_code = self.country_code.currentText()
        self.result_build_code   = self.build_code.text().strip().upper()
        self.result_designer     = self.designer.text().strip()
        self.result_project_mgr  = self.project_mgr.text().strip()
