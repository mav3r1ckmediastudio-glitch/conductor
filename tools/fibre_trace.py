# -*- coding: utf-8 -*-
"""
fibre_trace.py  —  Conductor FTTP Network Design Plugin
Interactive fibre trace: click a premises on the map to highlight its full
route back to the cabinet via bundles/drop_ducts → joints → cables.
Rubber-band colours distinguish asset types. A docked info panel shows the
hop-by-hop breakdown and any break reason.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit, QSizePolicy
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QCursor

from qgis.core import (
    QgsProject, QgsFeatureRequest, QgsRectangle, QgsWkbTypes,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem, NULL
)
from qgis.gui import QgsMapTool, QgsRubberBand

from ..conductor_utils import (
    get_layer, fld, val, NAVY, TEAL, ORANGE, LIGHT, WHITE, MID,
    GREEN, RED, GREEN_BG, RED_BG,
)

# Reuse the trace engine from validate_routes
from .validate_routes import (
    _build_index, _build_cable_node_index,
    STATUS_OK, STATUS_PARTIAL, STATUS_UNSERVED
)
from .optical_budget import calculate_link_budget, splitter_loss_for_ratio

# ── Rubber-band colour ───────────────────────────────────────────────────────
YELLOW      = QColor(255, 230,   0, 128)   # single highlight colour for all hops
CLR_ENTRY   = YELLOW
CLR_JOINT   = YELLOW
CLR_CABLE   = YELLOW
CLR_CAB     = YELLOW
CLR_PREM    = YELLOW
CLR_BREAK   = QColor(255,  30,  30, 128)   # red only for breaks

SNAP_RADIUS_PX = 18   # pixels for premises snap


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _geom_for_feature_id(layer, fid):
    """Return the QgsGeometry for a layer feature with the given field value."""
    if layer is None:
        return None
    for feat in layer.getFeatures():
        if str(feat[fid[0]]) == str(fid[1]):
            return feat.geometry()
    return None


def _geom_for_cable(cable_layer, cable_id):
    return _geom_for_feature_id(cable_layer, ("cable_id", cable_id))


def _geom_for_joint(joint_layer, joint_id):
    return _geom_for_feature_id(joint_layer, ("joint_id", joint_id))


def _geom_for_bundle(bundle_layer, uprn):
    """Return geometry of first bundle for this UPRN."""
    if bundle_layer is None:
        return None
    for feat in bundle_layer.getFeatures():
        if str(feat["uprn"]) == str(uprn):
            return feat.geometry()
    return None


def _geom_for_ddct(ddct_layer, uprn):
    """Return geometry of first drop duct for this UPRN."""
    if ddct_layer is None:
        return None
    for feat in ddct_layer.getFeatures():
        if str(feat["uprn"]) == str(uprn):
            return feat.geometry()
    return None


def _to_canvas_crs(geom, canvas):
    """Transform geometry from EPSG:27700 to canvas CRS if needed."""
    if geom is None or geom.isEmpty():
        return geom
    src = QgsCoordinateReferenceSystem("EPSG:27700")
    dst = canvas.mapSettings().destinationCrs()
    if src == dst:
        return geom
    xform = QgsCoordinateTransform(src, dst, QgsProject.instance())
    from qgis.core import QgsGeometry; g = QgsGeometry(geom)
    g.transform(xform)
    return g


# ── Info panel dialog ─────────────────────────────────────────────────────────

class FibreTracePanel(QDialog):
    """Floating panel showing trace result. Stays on top while tool is active."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        self._tool = None  # set by set_panel
        self.setWindowTitle("Conductor — Fibre Trace")
        self.setMinimumWidth(380)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(10, 10, 10, 10)

        # Status bar
        self._status_lbl = QLabel("Click a premises on the map to trace its route.")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(f"font-size:12px; color:{WHITE}; font-weight:600;")
        root.addWidget(self._status_lbl)

        # Colour legend
        legend = QHBoxLayout()
        legend.setSpacing(12)
        dot = QLabel("●")
        dot.setStyleSheet("color:#FFE600; font-size:14px;")
        lbl = QLabel("Highlighted route")
        lbl.setStyleSheet("font-size:10px; color:#8B9AAB;")
        legend.addWidget(dot)
        legend.addWidget(lbl)
        legend.addStretch()
        root.addLayout(legend)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{MID};")
        root.addWidget(sep)

        # Detail text — fixed height so long hop lists scroll internally
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(130)
        self._detail.setStyleSheet(
            "QTextEdit { font-family: 'Consolas','Courier New',monospace; "
            f"font-size:11px; background:{LIGHT}; border:1px solid {MID}; "
            "border-radius:3px; padding:4px; }"
        )
        root.addWidget(self._detail)

        # ── Optical budget card ────────────────────────────────────
        self._budget_box = QFrame()
        self._budget_box.setStyleSheet(
            f"QFrame#budgetBox {{ border:1px solid {MID}; border-radius:4px; }}"
        )
        self._budget_box.setObjectName("budgetBox")
        budget_layout = QVBoxLayout(self._budget_box)
        budget_layout.setContentsMargins(10, 8, 10, 8)
        budget_layout.setSpacing(6)

        budget_hdr = QHBoxLayout()
        budget_title = QLabel("Optical budget")
        budget_title.setStyleSheet(f"font-size:12px; font-weight:600; color:{WHITE};")
        self._budget_badge = QLabel("")
        self._budget_badge.setStyleSheet(
            "font-size:11px; font-weight:600; padding:2px 10px; border-radius:8px;"
        )
        budget_hdr.addWidget(budget_title)
        budget_hdr.addStretch()
        budget_hdr.addWidget(self._budget_badge)
        budget_layout.addLayout(budget_hdr)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(8)
        self._metric_loss,      loss_card      = self._build_metric_card("Total loss")
        self._metric_margin,    margin_card    = self._build_metric_card("Margin")
        self._metric_splitters, splitters_card = self._build_metric_card("Splitters")
        metrics_row.addWidget(loss_card)
        metrics_row.addWidget(margin_card)
        metrics_row.addWidget(splitters_card)
        budget_layout.addLayout(metrics_row)

        self._breakdown_btn = QPushButton("Show breakdown")
        self._breakdown_btn.setStyleSheet(
            f"QPushButton {{ text-align:left; border:none; color:{TEAL}; "
            "font-size:11px; padding:0; }}"
        )
        self._breakdown_btn.clicked.connect(self._toggle_breakdown)
        budget_layout.addWidget(self._breakdown_btn)

        self._breakdown_lbl = QLabel("")
        self._breakdown_lbl.setStyleSheet(f"font-size:11px; color:{WHITE};")
        self._breakdown_lbl.setTextFormat(Qt.RichText)
        self._breakdown_lbl.setVisible(False)
        budget_layout.addWidget(self._breakdown_lbl)

        root.addWidget(self._budget_box)
        self._budget_box.setVisible(False)

        btn_row = QHBoxLayout()
        self._btn_clear = QPushButton("Clear Trace")
        self._btn_clear.setStyleSheet(
            f"QPushButton {{ padding:5px 12px; border-radius:4px; font-size:11px; "
            f"border:1px solid {MID}; }} QPushButton:hover {{ background:#e8e8e8; }}"
        )
        self._btn_close = QPushButton("Close")
        self._btn_close.setStyleSheet(
            f"QPushButton {{ padding:5px 12px; border-radius:4px; font-size:11px; "
            f"border:1px solid {MID}; }} QPushButton:hover {{ background:#e8e8e8; }}"
        )
        btn_row.addWidget(self._btn_clear)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

    def _build_metric_card(self, caption):
        """Return (value_label, card_frame) for a small metric card used in
        the optical budget box (caption above, value below)."""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:{MID}; border-radius:4px; }}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)
        cap_lbl = QLabel(caption)
        cap_lbl.setStyleSheet("font-size:10px; color:#8B9AAB;")
        val_lbl = QLabel("—")
        val_lbl.setStyleSheet(f"font-size:14px; font-weight:600; color:{WHITE};")
        lay.addWidget(cap_lbl)
        lay.addWidget(val_lbl)
        return val_lbl, card

    def _toggle_breakdown(self):
        showing = self._breakdown_lbl.isVisible()
        self._breakdown_lbl.setVisible(not showing)
        self._breakdown_btn.setText("Hide breakdown" if not showing else "Show breakdown")
        self._resize_to_content()

    def _resize_to_content(self):
        """Grow/shrink the dialog's height to fit its current contents
        (e.g. after the budget card or breakdown table is shown/hidden),
        keeping the user's chosen width."""
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())

    def show_result(self, uprn, address, status, path, reason, budget=None):
        if status == STATUS_OK:
            status_text = f"✔  ROUTED  —  {address}"
            colour = "#16A34A"
        elif status == STATUS_PARTIAL:
            status_text = f"⚠  PARTIAL / BREAK  —  {address}"
            colour = ORANGE
        else:
            status_text = f"✘  UNSERVED  —  {address}"
            colour = "#DC2626"

        self._status_lbl.setText(status_text)
        self._status_lbl.setStyleSheet(f"font-size:12px; color:{colour}; font-weight:600;")

        lines = [
            f"Address: {address}",
            f"UPRN:    {uprn}",
            f"Status:  {status}",
            f"Reason:  {reason}",
            "",
            f"Path ({len(path)} hop{'s' if len(path) != 1 else ''}):",
        ]
        for i, node in enumerate(path):
            prefix = "  └─ " if i == len(path) - 1 else "  ├─ "
            lines.append(f"{prefix}{node}")
        if not path:
            lines.append("  (no path traced)")

        self._detail.setPlainText("\n".join(lines))

        self._update_budget_box(budget)
        self._resize_to_content()

    def _update_budget_box(self, budget):
        """Show/populate the optical budget card, or hide it if there's no
        loss figure to show (route not complete)."""
        if not budget or budget.get("loss_db") is None:
            self._budget_box.setVisible(False)
            return

        loss_db   = budget["loss_db"]
        margin_db = budget["margin_db"]
        link_pass = budget["link_pass"]
        breakdown = budget.get("breakdown") or {}
        optical   = budget.get("optical") or {}

        # ── Topology validation ──────────────────────────────────────
        splitter_list   = breakdown.get("splitters", [])
        topology_error  = None
        from collections import Counter
        for ratio, count in Counter(splitter_list).items():
            if count > 1:
                topology_error = (
                    f"Invalid topology: path passes through {count}× {ratio} splitters. "
                    "Check CBT tail routing — each CBT must connect directly to the UG joint, "
                    "not chain through other CBTs."
                )
                break

        if topology_error:
            self._budget_badge.setText("ERROR")
            self._budget_badge.setStyleSheet(
                "font-size:11px; font-weight:600; padding:2px 10px; border-radius:8px; "
                f"background:{RED_BG}; color:{RED};"
            )
            self._metric_loss.setText(f"{loss_db:.2f} dB")
            self._metric_margin.setText("N/A")
            self._metric_margin.setStyleSheet(f"font-size:14px; font-weight:600; color:{RED};")
            self._metric_splitters.setText(" + ".join(splitter_list) if splitter_list else "none")
            self._breakdown_lbl.setText(
                f'<p style="color:{RED}; font-size:11px;">⚠️ {topology_error}</p>'
                + self._format_breakdown_html(loss_db, breakdown, optical)
            )
            self._breakdown_lbl.setVisible(True)
            self._breakdown_btn.setText("Hide breakdown")
            self._budget_box.setVisible(True)
            return
        # ── Normal PASS / FAIL ────────────────────────────────────────
        if link_pass:
            self._budget_badge.setText("PASS")
            self._budget_badge.setStyleSheet(
                "font-size:11px; font-weight:600; padding:2px 10px; border-radius:8px; "
                f"background:{GREEN_BG}; color:{GREEN};"
            )
        else:
            self._budget_badge.setText("FAIL")
            self._budget_badge.setStyleSheet(
                "font-size:11px; font-weight:600; padding:2px 10px; border-radius:8px; "
                f"background:{RED_BG}; color:{RED};"
            )

        self._metric_loss.setText(f"{loss_db:.2f} dB")
        self._metric_margin.setText(f"{margin_db:+.2f} dB")
        self._metric_margin.setStyleSheet(
            f"font-size:14px; font-weight:600; color:{GREEN if link_pass else RED};"
        )

        splitters = breakdown.get("splitters", [])
        self._metric_splitters.setText(" + ".join(splitters) if splitters else "none")

        self._breakdown_lbl.setText(self._format_breakdown_html(loss_db, breakdown, optical))
        self._breakdown_lbl.setVisible(False)
        self._breakdown_btn.setText("Show breakdown")

        self._budget_box.setVisible(True)

    @staticmethod
    def _format_breakdown_html(loss_db, breakdown, optical):
        rows = []

        fibre_km = breakdown.get("fibre_length_m", 0.0) / 1000.0
        rows.append((f"Fibre attenuation ({fibre_km:.2f} km)", breakdown.get("fibre_db", 0.0)))

        splice_count = breakdown.get("splice_count", 0)
        if splice_count:
            per_splice = optical.get("splice_loss_db", 0.0)
            rows.append((f"Splices ({splice_count} × {per_splice:.2f} dB)",
                          breakdown.get("splice_db", 0.0)))

        for ratio in breakdown.get("splitters", []):
            loss = splitter_loss_for_ratio(ratio, optical.get("splitter_loss_db", {}))
            rows.append((f"Splitter {ratio}", loss))

        connector_db = breakdown.get("connector_db", 0.0)
        if connector_db:
            _connector_count = 3  # POP patch panel + CBT entry + ONT
            _per_connector   = connector_db / _connector_count
            rows.append((f"Connectors ({_connector_count} × {_per_connector:.2f} dB)", connector_db))

        cells = "".join(
            f"<tr><td>{label}</td>"
            f"<td style=\'text-align:right; padding-left:10px;\'>{value:.2f} dB</td></tr>"
            for label, value in rows
        )
        cells += (
            f"<tr><td style=\'border-top:1px solid {MID}; font-weight:600;\'>Total</td>"
            f"<td style=\'border-top:1px solid {MID}; text-align:right; "
            f"padding-left:10px; font-weight:600;\'>{loss_db:.2f} dB</td></tr>"
        )
        return f"<table width=\'100%\' cellspacing=\'0\' cellpadding=\'2\'>{cells}</table>"

    def clear(self):
        self._status_lbl.setText("Click a premises on the map to trace its route.")
        self._status_lbl.setStyleSheet(f"font-size:12px; color:{WHITE}; font-weight:600;")
        self._detail.clear()
        self._budget_box.setVisible(False)

    def closeEvent(self, event):
        if self._tool:
            try:
                self._tool._clear_bands()
                self._tool._canvas.refresh()
                self._tool._canvas.unsetMapTool(self._tool)
            except Exception:
                pass
        super().closeEvent(event)


# ── Map tool ──────────────────────────────────────────────────────────────────

class FibreTraceMapTool(QgsMapTool):
    """
    Click a premises point → traces its route back to cabinet →
    highlights each hop with colour-coded rubber bands.
    """

    def __init__(self, canvas, project, iface):
        super().__init__(canvas)
        self._canvas  = canvas
        self._project = project
        self._iface   = iface
        self._bands   = []   # list of active QgsRubberBand objects
        self._panel   = None

        self.setCursor(QCursor(Qt.CrossCursor))

    # ── Rubber band management ────────────────────────────────────────────────

    def _clear_bands(self):
        for band in self._bands:
            try:
                band.reset()
                self._canvas.scene().removeItem(band)
            except Exception:
                pass
        self._bands = []

    def _add_line_band(self, geom, colour, width=3):
        if geom is None or geom.isEmpty():
            return
        canvas_crs = self._canvas.mapSettings().destinationCrs()
        band = QgsRubberBand(self._canvas, QgsWkbTypes.LineGeometry)
        band.setColor(colour)
        band.setWidth(width)
        band.setZValue(1000)
        band.setToGeometry(_to_canvas_crs(geom, self._canvas), canvas_crs)
        self._bands.append(band)

    def _add_point_band(self, geom, colour, size=12):
        if geom is None or geom.isEmpty():
            return
        canvas_crs = self._canvas.mapSettings().destinationCrs()
        band = QgsRubberBand(self._canvas, QgsWkbTypes.PointGeometry)
        band.setColor(colour)
        band.setIconSize(size)
        band.setIcon(QgsRubberBand.ICON_CIRCLE)
        band.setZValue(1000)
        band.setToGeometry(_to_canvas_crs(geom, self._canvas), canvas_crs)
        self._bands.append(band)

    # ── Premises snap ─────────────────────────────────────────────────────────

    def _snap_to_premises(self, canvas_pos):
        """Return (feature, distance_px) of nearest premises within snap radius."""
        premises_layer = get_layer("premises", self._project)
        if not premises_layer:
            return None, None

        canvas_pt = self.toMapCoordinates(canvas_pos)
        # Convert snap radius from pixels to map units
        scale  = self._canvas.mapUnitsPerPixel()
        radius = SNAP_RADIUS_PX * scale

        src_crs = self._canvas.mapSettings().destinationCrs()
        dst_crs = QgsCoordinateReferenceSystem("EPSG:27700")

        if src_crs != dst_crs:
            xform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
            pt_27700 = xform.transform(canvas_pt)
        else:
            pt_27700 = canvas_pt

        rect = QgsRectangle(
            pt_27700.x() - radius, pt_27700.y() - radius,
            pt_27700.x() + radius, pt_27700.y() + radius
        )
        req = QgsFeatureRequest().setFilterRect(rect)

        best_feat = None
        best_dist = float("inf")
        for feat in premises_layer.getFeatures(req):
            geom = feat.geometry()
            if geom and not geom.isEmpty():
                dist = geom.distance(
                    QgsRubberBand.ICON_CIRCLE  # dummy — use pt distance below
                )
                # Use centroid distance
                from qgis.core import QgsGeometry, QgsPointXY
                pt_geom = QgsGeometry.fromPointXY(QgsPointXY(pt_27700))
                d = geom.distance(pt_geom)
                if d < best_dist:
                    best_dist = d
                    best_feat = feat

        return best_feat, best_dist

    # ── Canvas events ─────────────────────────────────────────────────────────

    def canvasPressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self._run_trace(event.pos())

    def _run_trace(self, canvas_pos):
        self._clear_bands()
        if self._panel:
            self._panel.clear()

        premises_layer = get_layer("premises",   self._project)
        bundle_layer   = get_layer("bundles",    self._project)
        ddct_layer     = get_layer("drop_ducts", self._project)
        joint_layer    = get_layer("joints",     self._project)
        cable_layer    = get_layer("cables",     self._project)

        if not premises_layer:
            self._iface.messageBar().pushWarning("Fibre Trace", "Premises layer not found.")
            return

        # Find clicked premises
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
        req = QgsFeatureRequest().setFilterRect(rect)

        best_feat = None
        best_dist = float("inf")
        for feat in premises_layer.getFeatures(req):
            geom = feat.geometry()
            if geom and not geom.isEmpty():
                pt_geom = QgsGeometry.fromPointXY(QgsPointXY(pt_27700))
                d = geom.distance(pt_geom)
                if d < best_dist:
                    best_dist = d
                    best_feat = feat

        if best_feat is None:
            self._iface.messageBar().pushInfo(
                "Fibre Trace", "No premises found near click. Try clicking closer to a premises point."
            )
            return

        # Build address string
        fields = best_feat.fields().names()
        if "address_1" in fields:
            a1 = str(best_feat["address_1"] or "")
            a2 = str(best_feat["address_2"] or "") if "address_2" in fields else ""
            pc = str(best_feat["postcode"]   or "") if "postcode"  in fields else ""
            address = ", ".join(p for p in [a1, a2, pc] if p)
        elif "address" in fields:
            address = str(best_feat["address"] or "")
        else:
            address = str(best_feat["uprn"])

        uprn    = best_feat["uprn"]
        area_id = best_feat["area_id"] if "area_id" in fields else ""

        # Highlight premises
        self._add_point_band(best_feat.geometry(), CLR_PREM, size=17)

        # Build indexes and trace
        bundle_idx     = _build_index(bundle_layer, "uprn")   if bundle_layer else {}
        ddct_idx       = _build_index(ddct_layer,   "uprn")   if ddct_layer   else {}
        joint_idx      = _build_index(joint_layer,  "joint_id") if joint_layer else {}
        cable_node_idx = _build_cable_node_index(cable_layer)  if cable_layer  else {}

        try:
            budget = calculate_link_budget(
                uprn, area_id,
                bundle_idx, ddct_idx,
                joint_idx, cable_node_idx,
            )
        except Exception as e:
            self._iface.messageBar().pushCritical("Fibre Trace", f"Trace error: {e}")
            return

        status, path, reason = budget["status"], budget["path"], budget["reason"]

        # ── Draw rubber bands for each hop ────────────────────────────────────

        # Entry asset (bundle or drop duct)
        b_geom = _geom_for_bundle(bundle_layer, uprn)
        if b_geom:
            self._add_line_band(b_geom, CLR_ENTRY, width=5)
        else:
            d_geom = _geom_for_ddct(ddct_layer, uprn)
            if d_geom:
                self._add_line_band(d_geom, CLR_ENTRY, width=5)

        # Walk the path — joints and cables alternate
        for hop in path:
            hop_str = str(hop)
            if "JNT-" in hop_str or "CBT-" in hop_str:
                # Underground joint or CBT (pole-mounted splitter box)
                geom = _geom_for_joint(joint_layer, hop_str)
                self._add_point_band(geom, CLR_JOINT, size=15)
            elif "CBL-" in hop_str or "TAIL-" in hop_str:
                # Any cable segment — feeder, aerial span, or CBT tail
                geom = _geom_for_cable(cable_layer, hop_str)
                self._add_line_band(geom, CLR_CABLE, width=5)
            elif "POL-" in hop_str:
                # Pole node — no geometry in joints layer, skip point band
                # (the aerial span cable bands either side cover it visually)
                pass
            elif "CAB-" in hop_str or "POP-" in hop_str:
                # Cabinet — find in exchange_pops or chambers
                pop_layer = get_layer("exchange_pops", self._project)
                cab_geom  = _geom_for_feature_id(pop_layer, ("pop_id", hop_str)) if pop_layer else None
                self._add_point_band(cab_geom, CLR_CAB, size=19)

        self._canvas.refresh()

        # Show panel
        if self._panel and not self._panel.isVisible():
            self._panel.show()
        if self._panel:
            self._panel.show_result(uprn, address, status, path, reason, budget=budget)

        # Message bar summary
        if status == STATUS_OK:
            self._iface.messageBar().pushSuccess(
                "Fibre Trace", f"{address} — ROUTED ({len(path)} hops)"
            )
        else:
            self._iface.messageBar().pushWarning(
                "Fibre Trace", f"{address} — {status}: {reason}"
            )

    def set_panel(self, panel):
        self._panel = panel
        self._panel._tool = self
        self._panel._btn_clear.clicked.connect(self._on_clear)
        self._panel._btn_close.clicked.connect(self._on_close)

    def _on_clear(self):
        self._clear_bands()
        self._canvas.refresh()
        if self._panel:
            self._panel.clear()

    def _on_close(self):
        self._clear_bands()
        self._canvas.refresh()
        if self._panel:
            self._panel.hide()
        self._canvas.unsetMapTool(self)

    def deactivate(self):
        self._clear_bands()
        self._canvas.refresh()
        if self._panel:
            self._panel.hide()
        super().deactivate()


# ── Entry point ───────────────────────────────────────────────────────────────

def activate_fibre_trace(iface, project, parent=None):
    """Activate the fibre trace map tool and show the info panel."""
    canvas = iface.mapCanvas()
    tool   = FibreTraceMapTool(canvas, project, iface)
    panel  = FibreTracePanel(parent)
    tool.set_panel(panel)
    canvas.setMapTool(tool)
    panel.show()
    iface.messageBar().pushInfo(
        "Conductor — Fibre Trace",
        "Click any premises on the map to trace its route back to the cabinet. Esc to exit."
    )
    return tool, panel
