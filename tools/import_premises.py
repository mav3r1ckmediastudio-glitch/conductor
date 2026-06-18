# -*- coding: utf-8 -*-
"""
Conductor — Import Premises Tool
Imports premises from an OS AddressBase CSV **or Shapefile** into the premises layer.
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
    QgsFeatureRequest, QgsVectorLayer,
)
from ..conductor_utils import get_layer, fld, val, LayerEditContext, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, BTN_PRIMARY, BTN_SECONDARY, BTN_TEAL, INPUT_STYLE, LABEL_STYLE, SECTION_STYLE, MONO_STYLE

GREEN  = "#1D7A6E"

# ── OS ADDRESSBASE COLUMN DETECTION ──────────────────────────────────────────
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

# ── CLASSIFICATION ────────────────────────────────────────────────────────────
def _classify_premise(code):
    if not code:
        return "RESIDENTIAL"
    c = str(code).strip().upper()
    if c.startswith("R"):
        return "RESIDENTIAL"
    elif c.startswith("C"):
        return "BUSINESS"
    elif c.startswith("X"):
        return "BUSINESS"
    elif c.startswith("M"):
        return "OTHER"
    else:
        return "RESIDENTIAL"


def _detect_column(headers, candidates):
    for c in candidates:
        if c in headers:
            return c
    return None


# ── CSV HELPERS ───────────────────────────────────────────────────────────────
def _read_csv_preview(filepath, max_rows=5):
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
    except Exception:
        return [], []


def _count_csv_rows(filepath):
    try:
        with open(filepath, newline='', encoding='utf-8-sig') as f:
            return sum(1 for _ in f) - 1
    except Exception as e:
        from ..conductor_utils import log
        log(f"_count_csv_rows failed for {filepath}: {e}")
        return 0


# ── SHP HELPERS ───────────────────────────────────────────────────────────────
def _read_shp_preview(filepath, max_rows=5):
    """Return (field_names, preview_rows_as_dicts, feature_count, layer)."""
    lyr = QgsVectorLayer(filepath, "preview", "ogr")
    if not lyr.isValid():
        return [], [], 0, None
    fields = [f.name() for f in lyr.fields()]
    rows = []
    for i, feat in enumerate(lyr.getFeatures()):
        if i >= max_rows:
            break
        rows.append({f: str(feat[f]) for f in fields})
    return fields, rows, lyr.featureCount(), lyr


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
        self._col_map     = {}
        self._source_type = None   # "csv" or "shp"
        self._shp_layer   = None   # QgsVectorLayer kept open for import
        self._shp_count   = 0
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

        hdr = QLabel("  Import Premises — OS AddressBase CSV / Shapefile")
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
        fl.addWidget(self._section("SOURCE FILE"))
        file_row = QHBoxLayout()
        self._file_display = QLineEdit()
        self._file_display.setPlaceholderText("Browse to OS AddressBase CSV or Shapefile…")
        self._file_display.setReadOnly(True)
        self._file_display.setStyleSheet(MONO_STYLE)
        file_row.addWidget(self._file_display)
        browse = QPushButton("Browse…")
        browse.setStyleSheet(BTN_TEAL)
        browse.clicked.connect(self._browse_file)
        file_row.addWidget(browse)
        fl.addLayout(file_row)

        # Source type badge + info row
        info_row = QHBoxLayout()
        self._source_badge = QLabel("")
        self._source_badge.setStyleSheet(
            f"background:{TEAL}; color:{WHITE}; font-size:10px; font-weight:bold;"
            f"padding:2px 8px; border-radius:3px;"
        )
        self._source_badge.setVisible(False)
        info_row.addWidget(self._source_badge)
        self._file_info = QLabel("No file selected")
        self._file_info.setStyleSheet(f"color:{MID}; font-size:11px;")
        info_row.addWidget(self._file_info)
        info_row.addStretch()
        fl.addLayout(info_row)

        fl.addWidget(self._divider())

        # ── COLUMN MAPPING ────────────────────────────────────────────────
        fl.addWidget(self._section("COLUMN MAPPING"))
        self._mapping_note = QLabel("Load a file to enable column mapping.")
        self._mapping_note.setStyleSheet(f"color:{MID}; font-size:11px;")
        self._mapping_note.setWordWrap(True)
        fl.addWidget(self._mapping_note)

        self._shp_geom_note = QLabel(
            "\u2139\ufe0f  Shapefile: coordinates will be read from feature geometry. "
            "Easting/Northing columns are optional \u2014 map them only if you want "
            "to override the geometry with attribute values."
        )
        self._shp_geom_note.setStyleSheet(f"color:{TEAL}; font-size:11px;")
        self._shp_geom_note.setWordWrap(True)
        self._shp_geom_note.setVisible(False)
        fl.addWidget(self._shp_geom_note)

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
            if field == "uprn":
                label += " *"
            elif field in ("easting", "northing"):
                label += " (CSV req / SHP opt)"
            self._mapping_form.addRow(self._lbl(label), combo)

        fl.addLayout(self._mapping_form)
        fl.addWidget(self._divider())

        # ── FILTERS ───────────────────────────────────────────────────────
        fl.addWidget(self._section("FILTERS"))

        self._filter_build_area = QCheckBox("Only import premises within the Build Area polygon")
        self._filter_build_area.setChecked(False)
        self._filter_build_area.setVisible(False)  # clipping now happens when build area is drawn

        self._filter_residential = QCheckBox("Include Residential premises")
        self._filter_residential.setChecked(True)
        self._filter_residential.setStyleSheet(f"font-size:12px; color:{WHITE};")
        fl.addWidget(self._filter_residential)

        self._filter_business = QCheckBox("Include Business premises")
        self._filter_business.setChecked(True)
        self._filter_business.setStyleSheet(f"font-size:12px; color:{WHITE};")
        fl.addWidget(self._filter_business)

        fl.addWidget(self._divider())

        # ── PREVIEW / SUMMARY ─────────────────────────────────────────────
        fl.addWidget(self._section("PREVIEW"))
        self._preview_label = QLabel("Load a file to see a preview.")
        self._preview_label.setStyleSheet(f"color:{MID}; font-size:11px;")
        self._preview_label.setWordWrap(True)
        fl.addWidget(self._preview_label)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"font-size:13px; font-weight:bold; color:{TEAL};")
        fl.addWidget(self._count_label)

        scroll.setWidget(fw)
        root.addWidget(scroll)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setStyleSheet(f"QProgressBar::chunk {{ background:{TEAL}; }}")
        root.addWidget(self._progress)

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

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open OS AddressBase file", "",
            "AddressBase Files (*.csv *.txt *.shp);;CSV Files (*.csv *.txt);;Shapefiles (*.shp)"
        )
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext == ".shp":
            self._load_shp(path)
        else:
            self._load_csv(path)

    # ── CSV ───────────────────────────────────────────────────────────────

    def _load_csv(self, path):
        self._filepath    = path
        self._source_type = "csv"
        self._shp_layer   = None
        self._file_display.setText(os.path.basename(path))
        self._source_badge.setText("CSV")
        self._source_badge.setVisible(True)
        self._shp_geom_note.setVisible(False)

        headers, preview_rows = _read_csv_preview(path)
        if not headers:
            QMessageBox.warning(self, "Error", "Could not read CSV file.")
            return

        self._headers = headers
        row_count = _count_csv_rows(path)
        self._file_info.setText(
            f"{row_count:,} rows  \u00b7  {len(headers)} columns  \u00b7  "
            f"{os.path.getsize(path) // 1024:,} KB"
        )
        self._file_info.setStyleSheet(f"color:{TEAL}; font-size:11px;")
        self._mapping_note.setText(
            "Conductor will auto-detect AddressBase columns. "
            "Adjust if your CSV uses different headers."
        )
        self._populate_combos(headers)

        if preview_rows:
            sample = preview_rows[0]
            easting_col  = _detect_column(headers, COLUMN_CANDIDATES["easting"])
            northing_col = _detect_column(headers, COLUMN_CANDIDATES["northing"])
            postcode_col = _detect_column(headers, COLUMN_CANDIDATES["postcode"])
            bits = []
            if easting_col:  bits.append(f"E={sample.get(easting_col,'?')}")
            if northing_col: bits.append(f"N={sample.get(northing_col,'?')}")
            if postcode_col: bits.append(f"PC={sample.get(postcode_col,'?')}")
            self._preview_label.setText("Sample row: " + "  ".join(bits))
            self._preview_label.setStyleSheet(f"color:{WHITE}; font-size:11px;")

        self._import_btn.setEnabled(True)
        self._update_count_estimate(row_count)

    # ── SHP ───────────────────────────────────────────────────────────────

    def _load_shp(self, path):
        fields, preview_rows, feat_count, lyr = _read_shp_preview(path)
        if not lyr:
            QMessageBox.warning(self, "Error",
                "Could not open Shapefile. Check the .shp, .dbf and .prj files are present.")
            return

        self._filepath    = path
        self._source_type = "shp"
        self._shp_layer   = lyr
        self._shp_count   = feat_count
        self._headers     = fields
        self._file_display.setText(os.path.basename(path))
        self._source_badge.setText("SHP")
        self._source_badge.setVisible(True)
        self._shp_geom_note.setVisible(True)

        crs_desc = lyr.crs().authid() if lyr.crs().isValid() else "unknown CRS"
        self._file_info.setText(
            f"{feat_count:,} features  \u00b7  {len(fields)} fields  \u00b7  CRS: {crs_desc}"
        )
        self._file_info.setStyleSheet(f"color:{TEAL}; font-size:11px;")
        self._mapping_note.setText(
            "Map attribute fields below. Easting/Northing are optional \u2014 "
            "geometry will be used when not mapped."
        )
        self._populate_combos(fields)

        if preview_rows:
            sample = preview_rows[0]
            postcode_col = _detect_column(fields, COLUMN_CANDIDATES["postcode"])
            uprn_col     = _detect_column(fields, COLUMN_CANDIDATES["uprn"])
            bits = []
            if uprn_col:     bits.append(f"UPRN={sample.get(uprn_col,'?')}")
            if postcode_col: bits.append(f"PC={sample.get(postcode_col,'?')}")
            bits.append(f"CRS={crs_desc}")
            self._preview_label.setText("Sample feature: " + "  ".join(bits))
            self._preview_label.setStyleSheet(f"color:{WHITE}; font-size:11px;")

        self._import_btn.setEnabled(True)
        self._update_count_estimate(feat_count)

    # ── SHARED COMBO POPULATION ───────────────────────────────────────────

    def _populate_combos(self, headers):
        for field, combo in self._col_combos.items():
            combo.clear()
            combo.addItem("— not mapped —")
            combo.addItems(headers)
            combo.setEnabled(True)
            detected = _detect_column(headers, COLUMN_CANDIDATES[field])
            if detected:
                idx = combo.findText(detected)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                    combo.setStyleSheet(INPUT_STYLE + f"color:{TEAL};")

    def _update_count_estimate(self, total):
        ba_layer = self._project.get_layer("build_areas")
        if ba_layer and ba_layer.featureCount() > 0 and self._filter_build_area.isChecked():
            self._count_label.setText(
                f"~{total:,} records in source \u2014 will filter to Build Area polygon on import."
            )
        else:
            self._count_label.setText(f"{total:,} premises will be imported.")

    # ── IMPORT DISPATCH ───────────────────────────────────────────────────

    def _get_col(self, field):
        combo = self._col_combos.get(field)
        if not combo:
            return None
        v = combo.currentText()
        return v if not v.startswith("\u2014") else None

    def _on_import(self):
        if not self._get_col("uprn"):
            QMessageBox.warning(self, "Missing Column",
                "Please map the 'UPRN' column before importing.")
            return

        if self._source_type == "csv":
            for required in ("easting", "northing"):
                if not self._get_col(required):
                    QMessageBox.warning(self, "Missing Column",
                        f"Please map the '{required}' column before importing.\n"
                        f"(These are optional for Shapefiles but required for CSV.)")
                    return

        premises_layer = self._project.get_layer("premises")
        if not premises_layer:
            QMessageBox.critical(self, "Error", "Premises layer not found.")
            return

        build_area_geom = None
        if self._filter_build_area.isChecked():
            ba_layer = self._project.get_layer("build_areas")
            if ba_layer and ba_layer.featureCount() > 0:
                matched = None
                first   = None
                for feat in ba_layer.getFeatures():
                    if first is None:
                        first = feat.geometry()
                    if str(feat["area_id"]) == str(self._project.area_id):
                        matched = feat.geometry()
                        break
                build_area_geom = matched or first

        project_crs = QgsProject.instance().crs()

        self._import_btn.setEnabled(False)
        self._progress.setVisible(True)

        if self._source_type == "shp":
            self._run_shp_import(premises_layer, build_area_geom, project_crs)
        else:
            self._run_csv_import(premises_layer, build_area_geom)

    # ── CSV IMPORT ────────────────────────────────────────────────────────

    def _run_csv_import(self, premises_layer, build_area_geom):
        total_rows = _count_csv_rows(self._filepath)
        self._progress.setMaximum(max(total_rows, 1))

        imported = skipped_area = skipped_type = skipped_dupe = errors = 0
        existing_uprns = self._get_existing_uprns(premises_layer)
        premises_layer.startEditing()

        try:
            with open(self._filepath, newline='', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    self._progress.setValue(i + 1)
                    try:
                        easting  = float(row.get(self._get_col("easting"),  0))
                        northing = float(row.get(self._get_col("northing"), 0))
                    except (ValueError, TypeError):
                        errors += 1; continue
                    if easting == 0 or northing == 0:
                        errors += 1; continue

                    pt = QgsPointXY(easting, northing)
                    if build_area_geom:
                        if not build_area_geom.intersects(QgsGeometry.fromPointXY(pt)):
                            skipped_area += 1; continue

                    try:
                        uprn_col = self._get_col("uprn")
                        uprn = int(row.get(uprn_col, 0)) if uprn_col else 0
                    except (ValueError, TypeError):
                        uprn = 0

                    if uprn and uprn in existing_uprns:
                        skipped_dupe += 1; continue

                    class_col  = self._get_col("class_code")
                    class_code = row.get(class_col, "") if class_col else ""
                    premise_type = _classify_premise(class_code)

                    if premise_type == "RESIDENTIAL" and not self._filter_residential.isChecked():
                        skipped_type += 1; continue
                    if premise_type == "BUSINESS" and not self._filter_business.isChecked():
                        skipped_type += 1; continue

                    def sv(field, default="", _row=row):
                        col = self._get_col(field)
                        return str(_row.get(col, default)).strip() if col else default

                    feat = QgsFeature(premises_layer.fields())
                    feat.setGeometry(QgsGeometry.fromPointXY(pt))
                    self._set_attrs(feat, premises_layer, uprn, sv, premise_type)

                    if premises_layer.addFeature(feat):
                        imported += 1
                        if uprn: existing_uprns.add(uprn)
                    else:
                        errors += 1

        except Exception as e:
            premises_layer.rollBack()
            QMessageBox.critical(self, "Import Error", str(e))
            self._import_btn.setEnabled(True)
            self._progress.setVisible(False)
            return

        premises_layer.commitChanges()
        self._finish_import(premises_layer, imported, skipped_area, skipped_dupe, skipped_type, errors)

    # ── SHP IMPORT ────────────────────────────────────────────────────────

    def _run_shp_import(self, premises_layer, build_area_geom, project_crs):
        lyr = self._shp_layer
        total = self._shp_count
        self._progress.setMaximum(max(total, 1))

        src_crs = lyr.crs()
        need_transform = src_crs.isValid() and project_crs.isValid() and src_crs != project_crs
        transform = QgsCoordinateTransform(src_crs, project_crs, QgsProject.instance()) if need_transform else None

        imported = skipped_area = skipped_type = skipped_dupe = errors = 0
        existing_uprns = self._get_existing_uprns(premises_layer)
        premises_layer.startEditing()

        try:
            for i, src_feat in enumerate(lyr.getFeatures()):
                self._progress.setValue(i + 1)

                east_col = self._get_col("easting")
                nrth_col = self._get_col("northing")
                if east_col and nrth_col:
                    try:
                        easting  = float(src_feat[east_col])
                        northing = float(src_feat[nrth_col])
                        geom = QgsGeometry.fromPointXY(QgsPointXY(easting, northing))
                    except (ValueError, TypeError, KeyError):
                        geom = src_feat.geometry()
                        if transform:
                            geom.transform(transform)
                else:
                    geom = src_feat.geometry()
                    if transform:
                        geom.transform(transform)

                if geom.isEmpty() or geom.isNull():
                    errors += 1; continue

                centroid = geom.centroid().asPoint()

                if build_area_geom:
                    if not build_area_geom.intersects(geom):
                        skipped_area += 1; continue

                uprn_col = self._get_col("uprn")
                try:
                    uprn = int(src_feat[uprn_col]) if uprn_col else 0
                except (ValueError, TypeError, KeyError):
                    uprn = 0

                if uprn and uprn in existing_uprns:
                    skipped_dupe += 1; continue

                class_col = self._get_col("class_code")
                try:
                    class_code = str(src_feat[class_col]) if class_col else ""
                except (KeyError, Exception):
                    class_code = ""
                premise_type = _classify_premise(class_code)

                if premise_type == "RESIDENTIAL" and not self._filter_residential.isChecked():
                    skipped_type += 1; continue
                if premise_type == "BUSINESS" and not self._filter_business.isChecked():
                    skipped_type += 1; continue

                def sv(field, default="", _feat=src_feat):
                    col = self._get_col(field)
                    if not col:
                        return default
                    try:
                        v = _feat[col]
                        return str(v).strip() if v is not None else default
                    except (KeyError, Exception):
                        return default

                dest_feat = QgsFeature(premises_layer.fields())
                dest_feat.setGeometry(QgsGeometry.fromPointXY(centroid))
                self._set_attrs(dest_feat, premises_layer, uprn, sv, premise_type)

                if premises_layer.addFeature(dest_feat):
                    imported += 1
                    if uprn: existing_uprns.add(uprn)
                else:
                    errors += 1

        except Exception as e:
            premises_layer.rollBack()
            QMessageBox.critical(self, "Import Error", str(e))
            self._import_btn.setEnabled(True)
            self._progress.setVisible(False)
            return

        premises_layer.commitChanges()
        self._finish_import(premises_layer, imported, skipped_area, skipped_dupe, skipped_type, errors)

    # ── SHARED HELPERS ────────────────────────────────────────────────────

    def _get_existing_uprns(self, premises_layer):
        existing = set()
        for feat in premises_layer.getFeatures():
            u = feat["uprn"]
            if u:
                try:
                    existing.add(int(u))
                except (ValueError, TypeError):
                    pass
        return existing

    def _set_attrs(self, feat, premises_layer, uprn, sv, premise_type):
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

    def _finish_import(self, premises_layer, imported, skipped_area, skipped_dupe, skipped_type, errors):
        premises_layer.triggerRepaint()
        tree_layer = QgsProject.instance().layerTreeRoot().findLayer(premises_layer.id())
        if tree_layer:
            tree_layer.setItemVisibilityChecked(True)

        self._progress.setVisible(False)

        summary = f"Import complete.\n\n\u2713  {imported:,} premises imported\n"
        if skipped_area:  summary += f"\u2296  {skipped_area:,} outside Build Area (skipped)\n"
        if skipped_dupe:  summary += f"\u2296  {skipped_dupe:,} duplicate UPRNs (skipped)\n"
        if skipped_type:  summary += f"\u2296  {skipped_type:,} filtered by type (skipped)\n"
        if errors:        summary += f"\u26a0  {errors:,} rows/features with errors (skipped)\n"

        QMessageBox.information(self, "Import Complete", summary)
        self.accept()
