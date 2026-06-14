# -*- coding: utf-8 -*-
"""
Conductor — Import Premises Tool
Imports premises from an OS AddressBase CSV into the premises layer.
Filters to the current Build Area polygon.
"""

import csv
import os
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QFrame, QMessageBox, QFileDialog, QProgressBar,
    QScrollArea, QCheckBox, QSpinBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox,
)
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeatureRequest,
)
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, BTN_TEAL, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE, MONO_STYLE

GREEN  = "#1D7A6E"

# ── OS ADDRESSBASE COLUMN DETECTION ──────────────────────────────────────────
# AddressBase CSV headers vary slightly — we try common variants

COLUMN_CANDIDATES = {
    "uprn":       ["UPRN", "uprn"],
    "address_1":  ["BUILDING_NAME", "building_name", "SAO_TEXT", "PAO_TEXT",
                   "FULL_ADDRESS", "ADDRESS", "address"],
    "address_2":  ["STREET_DESCRIPTION", "street_description", "THOROUGHFARE_NAME"],
    "town":       ["TOWN_NAME", "town_name", "POST_TOWN", "post_town"],
    "postcode":   ["POSTCODE", "postcode", "POST_CODE"],
    "easting":    ["X_COORDINATE", "x_coordinate", "EASTING", "easting", "GEO_X"],
    "northing":   ["Y_COORDINATE", "y_coordinate", "NORTHING", "northing", "GEO_Y"],
    "class_code": ["CLASSIFICATION_CODE", "classification_code", "CLASS_CODE",
                   "BLPU_STATE_CODE", "ADDRESSBASE_PREMIUM_CLASS"],
}

# AddressBase classification codes → premise_type
# C = Commercial, L = Land, M = Military, O = Other, P = Parent Shell
# R = Residential, U = Unclassified, X = Dual Use
def _classify_premise(code):
    if not code:
        return "RESIDENTIAL"
    c = str(code).strip().upper()
    if c.startswith("R"):
        return "RESIDENTIAL"
    elif c.startswith("C"):
        return "BUSINESS"
    elif c.startswith("X"):
        return "BUSINESS"  # dual use — treat as business
    elif c.startswith("M"):
        return "OTHER"
    else:
        return "RESIDENTIAL"  # default


def _detect_column(headers, candidates):
    """Find the first matching column name from candidates."""
    for c in candidates:
        if c in headers:
            return c
    return None


def _read_csv_preview(filepath, max_rows=5):
    """Read headers and first few rows for preview."""
    try:
        with open(filepath, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = []
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append(row)
        return headers, rows
    except Exception as e:
        return [], []


def _count_csv_rows(filepath):
    try:
        with open(filepath, newline='', encoding='utf-8-sig') as f:
            return sum(1 for _ in f) - 1  # minus header
    except Exception as e:
        from ..conductor_utils import log
        log(f"_count_csv_rows failed for {filepath}: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# IMPORT DIALOG
# ═══════════════════════════════════════════════════════════════════════════

class ImportPremisesDialog(QDialog):

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Premises — OS AddressBase")
        self.setMinimumWidth(580)
        self.setMinimumHeight(500)
        self.setMaximumHeight(800)
        self.setModal(True)

        self._project     = project
        self._filepath    = ""
        self._headers     = []
        self._col_map     = {}   # conductor_field → csv_column
        self._build_ui()

    def _lbl(self, t):
        l = QLabel(t); l.setStyleSheet(LABEL_STYLE); return l

    def _section(self, t):
        l = QLabel(t); l.setStyleSheet(SECTION_STYLE); return l

    def _divider(self):
        f = QFrame(); f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"color:{MID}; margin:4px 0px;"); return f

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr = QLabel("  Import Premises — OS AddressBase CSV")
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; color:{WHITE}; font-size:13px; font-weight:bold;")
        root.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background:{LIGHT}; border:none;")

        fw = QFrame(); fw.setStyleSheet(f"background:{LIGHT};")
        fl = QVBoxLayout(fw); fl.setContentsMargins(20, 14, 20, 8); fl.setSpacing(10)

        # ── FILE SELECTION ────────────────────────────────────────────────
        fl.addWidget(self._section("CSV FILE"))
        file_row = QHBoxLayout()
        self._file_display = QLineEdit()
        self._file_display.setPlaceholderText("Browse to your OS AddressBase CSV…")
        self._file_display.setReadOnly(True)
        self._file_display.setStyleSheet(MONO_STYLE)
        file_row.addWidget(self._file_display)
        browse = QPushButton("Browse…")
        browse.setStyleSheet(BTN_TEAL)
        browse.clicked.connect(self._browse_csv)
        file_row.addWidget(browse)
        fl.addLayout(file_row)

        self._file_info = QLabel("No file selected")
        self._file_info.setStyleSheet(f"color:{MID}; font-size:11px;")
        fl.addWidget(self._file_info)

        fl.addWidget(self._divider())

        # ── COLUMN MAPPING ────────────────────────────────────────────────
        fl.addWidget(self._section("COLUMN MAPPING"))
        mapping_note = QLabel(
            "Conductor will auto-detect AddressBase columns. "
            "Adjust if your CSV uses different headers."
        )
        mapping_note.setStyleSheet(f"color:{MID}; font-size:11px;")
        mapping_note.setWordWrap(True)
        fl.addWidget(mapping_note)

        self._mapping_form = QFormLayout()
        self._mapping_form.setSpacing(6)
        self._mapping_form.setLabelAlignment(Qt.AlignRight)

        self._col_combos = {}
        for field, candidates in COLUMN_CANDIDATES.items():
            combo = QComboBox()
            combo.setStyleSheet(INPUT_STYLE)
            combo.setEnabled(False)
            self._col_combos[field] = combo
            label = field.replace("_", " ").title()
            if field in ("uprn", "easting", "northing"):
                label += " *"
            self._mapping_form.addRow(self._lbl(label), combo)

        fl.addLayout(self._mapping_form)
        fl.addWidget(self._divider())

        # ── FILTERS ───────────────────────────────────────────────────────
        fl.addWidget(self._section("FILTERS"))

        self._filter_build_area = QCheckBox(
            f"Only import premises within the Build Area polygon"
        )
        self._filter_build_area.setChecked(True)
        self._filter_build_area.setStyleSheet(f"font-size:12px; color:{NAVY};")
        fl.addWidget(self._filter_build_area)

        self._filter_residential = QCheckBox("Include Residential premises")
        self._filter_residential.setChecked(True)
        self._filter_residential.setStyleSheet(f"font-size:12px; color:{NAVY};")
        fl.addWidget(self._filter_residential)

        self._filter_business = QCheckBox("Include Business premises")
        self._filter_business.setChecked(True)
        self._filter_business.setStyleSheet(f"font-size:12px; color:{NAVY};")
        fl.addWidget(self._filter_business)

        fl.addWidget(self._divider())

        # ── PREVIEW / SUMMARY ─────────────────────────────────────────────
        fl.addWidget(self._section("PREVIEW"))
        self._preview_label = QLabel("Load a CSV file to see a preview.")
        self._preview_label.setStyleSheet(f"color:{MID}; font-size:11px;")
        self._preview_label.setWordWrap(True)
        fl.addWidget(self._preview_label)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"font-size:13px; font-weight:bold; color:{TEAL};")
        fl.addWidget(self._count_label)

        scroll.setWidget(fw)
        root.addWidget(scroll)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setStyleSheet(f"QProgressBar::chunk {{ background:{TEAL}; }}")
        root.addWidget(self._progress)

        # Buttons
        br = QHBoxLayout(); br.setContentsMargins(20, 12, 20, 16); br.addStretch()
        cancel = QPushButton("Cancel"); cancel.setStyleSheet(BTN_SECONDARY)
        cancel.clicked.connect(self.reject); br.addWidget(cancel)
        self._import_btn = QPushButton("Import Premises")
        self._import_btn.setStyleSheet(BTN_PRIMARY)
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._on_import)
        br.addWidget(self._import_btn)
        root.addLayout(br)

    # ── FILE HANDLING ─────────────────────────────────────────────────────

    def _browse_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open OS AddressBase CSV", "", "CSV Files (*.csv *.txt)"
        )
        if not path:
            return

        self._filepath = path
        self._file_display.setText(os.path.basename(path))

        headers, preview_rows = _read_csv_preview(path)
        if not headers:
            QMessageBox.warning(self, "Error", "Could not read CSV file.")
            return

        self._headers = headers
        row_count = _count_csv_rows(path)
        self._file_info.setText(
            f"{row_count:,} rows  ·  {len(headers)} columns  ·  "
            f"{os.path.getsize(path) // 1024:,} KB"
        )
        self._file_info.setStyleSheet(f"color:{TEAL}; font-size:11px;")

        # Populate column mapping combos
        for field, combo in self._col_combos.items():
            combo.clear()
            combo.addItem("— not mapped —")
            combo.addItems(headers)
            combo.setEnabled(True)

            # Auto-detect
            detected = _detect_column(headers, COLUMN_CANDIDATES[field])
            if detected:
                idx = combo.findText(detected)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                    combo.setStyleSheet(INPUT_STYLE + f"color:{TEAL};")

        # Preview
        if preview_rows:
            sample = preview_rows[0]
            easting_col  = _detect_column(headers, COLUMN_CANDIDATES["easting"])
            northing_col = _detect_column(headers, COLUMN_CANDIDATES["northing"])
            postcode_col = _detect_column(headers, COLUMN_CANDIDATES["postcode"])

            preview_text = "Sample row: "
            bits = []
            if easting_col:  bits.append(f"E={sample.get(easting_col,'?')}")
            if northing_col: bits.append(f"N={sample.get(northing_col,'?')}")
            if postcode_col: bits.append(f"PC={sample.get(postcode_col,'?')}")
            self._preview_label.setText(preview_text + "  ".join(bits))
            self._preview_label.setStyleSheet(f"color:{NAVY}; font-size:11px;")

        self._import_btn.setEnabled(True)
        self._update_count_estimate(row_count)

    def _update_count_estimate(self, total):
        ba_layer = self._project.get_layer("build_areas")
        if ba_layer and ba_layer.featureCount() > 0 and self._filter_build_area.isChecked():
            self._count_label.setText(
                f"~{total:,} rows in CSV — will filter to Build Area polygon on import."
            )
        else:
            self._count_label.setText(f"{total:,} premises will be imported.")

    # ── IMPORT ────────────────────────────────────────────────────────────

    def _get_col(self, field):
        combo = self._col_combos.get(field)
        if not combo:
            return None
        val = combo.currentText()
        return val if not val.startswith("—") else None

    def _on_import(self):
        # Validate required columns
        for required in ("uprn", "easting", "northing"):
            if not self._get_col(required):
                QMessageBox.warning(self, "Missing Column",
                    f"Please map the '{required}' column before importing.")
                return

        premises_layer = self._project.get_layer("premises")
        if not premises_layer:
            QMessageBox.critical(self, "Error", "Premises layer not found.")
            return

        # Get Build Area geometry for filtering
        build_area_geom = None
        if self._filter_build_area.isChecked():
            ba_layer = self._project.get_layer("build_areas")
            if ba_layer and ba_layer.featureCount() > 0:
                # Try matching by area_id first, fall back to first polygon
                matched = None
                first   = None
                for feat in ba_layer.getFeatures():
                    if first is None:
                        first = feat.geometry()
                    if str(feat["area_id"]) == str(self._project.area_id):
                        matched = feat.geometry()
                        break
                build_area_geom = matched or first

        self._import_btn.setEnabled(False)
        self._progress.setVisible(True)

        # Count rows for progress
        total_rows = _count_csv_rows(self._filepath)
        self._progress.setMaximum(max(total_rows, 1))

        imported = 0
        skipped_area = 0
        skipped_type = 0
        skipped_dupe = 0
        errors = 0

        # Get existing UPRNs to avoid duplicates
        existing_uprns = set()
        for feat in premises_layer.getFeatures():
            u = feat["uprn"]
            if u:
                existing_uprns.add(int(u))

        premises_layer.startEditing()

        try:
            with open(self._filepath, newline='', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)

                for i, row in enumerate(reader):
                    self._progress.setValue(i + 1)

                    # Get coordinates
                    try:
                        easting  = float(row.get(self._get_col("easting"),  0))
                        northing = float(row.get(self._get_col("northing"), 0))
                    except (ValueError, TypeError):
                        errors += 1
                        continue

                    if easting == 0 or northing == 0:
                        errors += 1
                        continue

                    pt = QgsPointXY(easting, northing)

                    # Filter to Build Area
                    if build_area_geom:
                        pt_geom = QgsGeometry.fromPointXY(pt)
                        if not build_area_geom.intersects(pt_geom):
                            skipped_area += 1
                            continue

                    # Get UPRN
                    try:
                        uprn_col = self._get_col("uprn")
                        uprn = int(row.get(uprn_col, 0)) if uprn_col else 0
                    except (ValueError, TypeError):
                        uprn = 0

                    # Skip duplicates
                    if uprn and uprn in existing_uprns:
                        skipped_dupe += 1
                        continue

                    # Classify premise type
                    class_col = self._get_col("class_code")
                    class_code = row.get(class_col, "") if class_col else ""
                    premise_type = _classify_premise(class_code)

                    # Filter by type
                    if premise_type == "RESIDENTIAL" and not self._filter_residential.isChecked():
                        skipped_type += 1
                        continue
                    if premise_type == "BUSINESS" and not self._filter_business.isChecked():
                        skipped_type += 1
                        continue

                    # Build feature
                    feat = QgsFeature(premises_layer.fields())
                    feat.setGeometry(QgsGeometry.fromPointXY(pt))

                    def sv(field, default=""):
                        col = self._get_col(field)
                        return str(row.get(col, default)).strip() if col else default

                    attrs = {
                        "uprn":           uprn if uprn else None,
                        "uprn_confirmed": True,
                        "address_1":      sv("address_1"),
                        "address_2":      sv("address_2"),
                        "town":           sv("town"),
                        "postcode":       sv("postcode").upper(),
                        "premise_type":   premise_type,
                        "area_id":        self._project.area_id,
                        "demand_tier":    "NONE",
                        "registered":     False,
                    }

                    for fname, fvalue in attrs.items():
                        idx = premises_layer.fields().indexOf(fname)
                        if idx >= 0 and fvalue is not None:
                            feat.setAttribute(idx, fvalue)

                    if premises_layer.addFeature(feat):
                        imported += 1
                        if uprn:
                            existing_uprns.add(uprn)
                    else:
                        errors += 1

        except Exception as e:
            premises_layer.rollBack()
            QMessageBox.critical(self, "Import Error", str(e))
            self._import_btn.setEnabled(True)
            self._progress.setVisible(False)
            return

        premises_layer.commitChanges()
        premises_layer.triggerRepaint()

        # Make layer visible
        tree_layer = QgsProject.instance().layerTreeRoot().findLayer(
            premises_layer.id()
        )
        if tree_layer:
            tree_layer.setItemVisibilityChecked(True)

        self._progress.setVisible(False)

        summary = (
            f"Import complete.\n\n"
            f"✓  {imported:,} premises imported\n"
        )
        if skipped_area:
            summary += f"⊘  {skipped_area:,} outside Build Area (skipped)\n"
        if skipped_dupe:
            summary += f"⊘  {skipped_dupe:,} duplicate UPRNs (skipped)\n"
        if skipped_type:
            summary += f"⊘  {skipped_type:,} filtered by type (skipped)\n"
        if errors:
            summary += f"⚠  {errors:,} rows with errors (skipped)\n"

        QMessageBox.information(self, "Import Complete", summary)
        self.accept()
