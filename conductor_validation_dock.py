# -*- coding: utf-8 -*-
"""
Conductor v2 — Right Dock: Validation Summary + Engineer Outputs
Permanent right-hand panel showing live validation counts and quick-launch
output buttons. Registered via iface.addDockWidget(Qt.RightDockWidgetArea).
"""

import os
from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QSizePolicy, QToolButton,
)
from qgis.core import QgsSettings
from .conductor_utils import (
    NAVY, LIGHT, MID, WHITE, GREY, TEAL, GREEN, ORANGE, RED,
    GREEN_BG, ORANGE_BG, RED_BG,
)


_QSS = f"""
    QWidget {{
        background-color: {NAVY};
        color: {WHITE};
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 12px;
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background-color: {NAVY};
        border: none;
    }}
    QScrollBar:vertical {{
        background: {NAVY}; width: 5px; border-radius: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {MID}; border-radius: 2px; min-height: 16px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QPushButton {{
        background: {LIGHT}; color: {WHITE}; border: 1px solid {MID};
        border-radius: 4px; padding: 6px 10px; font-size: 12px; text-align: left;
    }}
    QPushButton:hover {{ border-color: {TEAL}; color: {TEAL}; }}
    QPushButton:disabled {{ color: {MID}; border-color: {LIGHT}; background: {NAVY}; }}
    QLabel {{ color: {WHITE}; background: transparent; }}
    QFrame[frameShape="4"] {{ color: {MID}; }}
"""


class ConductorValidationDock(QDockWidget):
    """Right-hand permanent panel: Validation Summary + Engineer Outputs."""

    def __init__(self, main_dock, iface, parent=None):
        super().__init__("Validation & Outputs", parent or iface.mainWindow())
        self.main_dock = main_dock   # ConductorDockWidget reference
        self.iface = iface
        self.setObjectName("ConductorValidationDock")
        self.setMinimumWidth(260)
        self.setFeatures(
            QDockWidget.DockWidgetMovable |
            QDockWidget.DockWidgetFloatable |
            QDockWidget.DockWidgetClosable
        )

        # Restore geometry
        settings = QgsSettings()
        floating = settings.value("Conductor/v2/val_dock_floating", False, type=bool)
        self.setFloating(floating)

        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        container = QWidget()
        container.setObjectName("ConductorValContainer")
        container.setStyleSheet(_QSS)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(container)
        self.setWidget(scroll)

        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(44)
        hdr.setStyleSheet(f"background:{NAVY}; border-bottom:1px solid {MID};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 12, 0)
        hl.setSpacing(8)
        title_lbl = QLabel("VALIDATION SUMMARY")
        title_lbl.setStyleSheet(
            f"color:{WHITE}; font-size:11px; font-weight:700; letter-spacing:1.5px;"
        )
        hl.addWidget(title_lbl, 1)

        self._updated_lbl = QLabel("No project")
        self._updated_lbl.setStyleSheet(f"color:{MID}; font-size:10px;")
        hl.addWidget(self._updated_lbl)

        refresh_btn = QToolButton()
        refresh_btn.setText("↻")
        refresh_btn.setToolTip("Re-run validation")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setStyleSheet(f"""
            QToolButton {{ background:{LIGHT}; color:{WHITE}; border:1px solid {MID};
                           border-radius:3px; font-size:13px; }}
            QToolButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}
        """)
        refresh_btn.clicked.connect(self._on_refresh)
        hl.addWidget(refresh_btn)
        root.addWidget(hdr)

        # ── Count badges ────────────────────────────────────────────────────
        badge_area = QWidget()
        badge_area.setStyleSheet(f"background:{LIGHT}; border-bottom:1px solid {MID};")
        bl = QHBoxLayout(badge_area)
        bl.setContentsMargins(8, 8, 8, 8)
        bl.setSpacing(6)

        self._badge_critical = self._count_badge(bl, "0", "Critical", RED,    "#3B1212")
        self._badge_errors   = self._count_badge(bl, "0", "Errors",   ORANGE, "#3B2A0A")
        self._badge_warnings = self._count_badge(bl, "0", "Warnings", "#FACC15", "#302800")
        self._badge_info     = self._count_badge(bl, "0", "Info",     TEAL,   "#0A2622")
        root.addWidget(badge_area)

        # Progress bar row
        pb_row = QWidget()
        pb_row.setStyleSheet(f"background:{LIGHT};")
        pbl = QHBoxLayout(pb_row)
        pbl.setContentsMargins(12, 0, 12, 8)
        pbl.setSpacing(8)
        self._progress_lbl = QLabel("Network validation")
        self._progress_lbl.setStyleSheet(f"color:{GREY}; font-size:10px;")
        pbl.addWidget(self._progress_lbl, 1)
        self._pct_lbl = QLabel("–")
        self._pct_lbl.setStyleSheet(f"color:{TEAL}; font-size:10px; font-weight:bold;")
        pbl.addWidget(self._pct_lbl)
        root.addWidget(pb_row)

        # ── Issues list ─────────────────────────────────────────────────────
        root.addWidget(self._divider())
        issues_hdr = QWidget()
        ih = QHBoxLayout(issues_hdr)
        ih.setContentsMargins(12, 8, 12, 6)
        ih.setSpacing(0)
        issues_title = QLabel("ISSUES")
        issues_title.setStyleSheet(f"color:{GREY}; font-size:9px; font-weight:700; letter-spacing:2px;")
        ih.addWidget(issues_title)
        root.addWidget(issues_hdr)

        self._issues_container = QWidget()
        self._issues_container.setStyleSheet("background:transparent;")
        self._issues_layout = QVBoxLayout(self._issues_container)
        self._issues_layout.setContentsMargins(8, 0, 8, 8)
        self._issues_layout.setSpacing(2)
        self._placeholder_lbl = QLabel("Run validation to see issues.")
        self._placeholder_lbl.setStyleSheet(f"color:{MID}; font-size:11px; padding:8px 4px;")
        self._issues_layout.addWidget(self._placeholder_lbl)
        root.addWidget(self._issues_container)

        # ── Engineer Outputs ────────────────────────────────────────────────
        root.addWidget(self._divider())
        out_hdr = QWidget()
        oh = QHBoxLayout(out_hdr)
        oh.setContentsMargins(12, 8, 12, 4)
        oh.setSpacing(0)
        out_title = QLabel("ENGINEER OUTPUTS")
        out_title.setStyleSheet(f"color:{GREY}; font-size:9px; font-weight:700; letter-spacing:2px;")
        oh.addWidget(out_title)
        root.addWidget(out_hdr)

        out_area = QWidget()
        out_area.setStyleSheet("background:transparent;")
        ol = QVBoxLayout(out_area)
        ol.setContentsMargins(8, 4, 8, 12)
        ol.setSpacing(4)

        self._out_buttons = {}
        for label, key in [
            ("Splice Plan Export",  "splice_plan"),
            ("Route Splice Export", "route_splice"),
            ("Single Line Diagram", "sld"),
            ("Bill of Materials",   "bom"),
        ]:
            btn = QPushButton(label)
            btn.setEnabled(False)
            btn.clicked.connect(lambda _checked, k=key: self._on_output(k))
            ol.addWidget(btn)
            self._out_buttons[key] = btn

        root.addWidget(out_area)
        root.addStretch(1)

    def _count_badge(self, layout, value, caption, fg, bg):
        cell = QWidget()
        cell.setStyleSheet(
            f"background:{bg}; border:1px solid {fg}; border-radius:6px;"
        )
        cl = QVBoxLayout(cell)
        cl.setContentsMargins(4, 6, 4, 6)
        cl.setSpacing(1)

        v_lbl = QLabel(value)
        v_lbl.setAlignment(Qt.AlignCenter)
        v_lbl.setStyleSheet(
            f"color:{fg}; font-size:20px; font-weight:700; border:none; background:transparent;"
        )
        cl.addWidget(v_lbl)

        c_lbl = QLabel(caption)
        c_lbl.setAlignment(Qt.AlignCenter)
        c_lbl.setStyleSheet(f"color:{fg}; font-size:9px; border:none; background:transparent; opacity:0.8;")
        cl.addWidget(c_lbl)

        layout.addWidget(cell, 1)
        return v_lbl   # return value label for later updates

    def _divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color:{MID}; background:{MID}; margin:0px;")
        return line

    # ── DATA ────────────────────────────────────────────────────────────────────

    def set_project(self, project):
        """Enable output buttons and trigger first validation pass."""
        self._project = project
        for btn in self._out_buttons.values():
            btn.setEnabled(True)
        self._on_refresh()

    def push_validation_results(self, results):
        """
        Accept a dict with keys:
          critical (int), errors (int), warnings (int), info (int),
          score_pct (int or None),
          issues (list of dicts: {severity, message, asset_id})
        """
        self._badge_critical.setText(str(results.get("critical", 0)))
        self._badge_errors.setText(str(results.get("errors", 0)))
        self._badge_warnings.setText(str(results.get("warnings", 0)))
        self._badge_info.setText(str(results.get("info", 0)))

        pct = results.get("score_pct")
        if pct is not None:
            self._pct_lbl.setText(f"{pct}%")
            c = GREEN if pct >= 90 else (ORANGE if pct >= 70 else RED)
            self._pct_lbl.setStyleSheet(f"color:{c}; font-size:10px; font-weight:bold;")
        else:
            self._pct_lbl.setText("–")

        from datetime import datetime
        self._updated_lbl.setText(f"Updated {datetime.now().strftime('%H:%M')}")

        # Rebuild issues list
        while self._issues_layout.count():
            item = self._issues_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        issues = results.get("issues", [])
        if not issues:
            lbl = QLabel("No issues found  ✓")
            lbl.setStyleSheet(f"color:{GREEN}; font-size:11px; padding:8px 4px;")
            self._issues_layout.addWidget(lbl)
        else:
            colours = {"critical": RED, "error": ORANGE, "warning": "#FACC15", "info": TEAL}
            for issue in issues[:20]:   # cap display at 20
                sev = issue.get("severity", "info").lower()
                row = self._issue_row(
                    sev, issue.get("message", ""), issue.get("asset_id", ""),
                    colours.get(sev, GREY)
                )
                self._issues_layout.addWidget(row)
            if len(issues) > 20:
                more = QLabel(f"+ {len(issues)-20} more issues")
                more.setStyleSheet(f"color:{MID}; font-size:10px; padding:4px 4px;")
                self._issues_layout.addWidget(more)

    def _issue_row(self, severity, message, asset_id, colour):
        row = QWidget()
        row.setStyleSheet(
            f"background:{LIGHT}; border-left:3px solid {colour}; "
            f"border-radius:3px; margin-bottom:1px;"
        )
        rl = QHBoxLayout(row)
        rl.setContentsMargins(8, 5, 8, 5)
        rl.setSpacing(6)

        msg = QLabel(message)
        msg.setStyleSheet(f"color:{WHITE}; font-size:11px; border:none; background:transparent;")
        msg.setWordWrap(False)
        msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        rl.addWidget(msg, 1)

        if asset_id:
            aid = QLabel(asset_id)
            aid.setStyleSheet(f"color:{GREY}; font-size:10px; border:none; background:transparent;")
            rl.addWidget(aid)

        zoom_btn = QToolButton()
        zoom_btn.setText("⊙")
        zoom_btn.setToolTip(f"Zoom to {asset_id}")
        zoom_btn.setCursor(Qt.PointingHandCursor)
        zoom_btn.setFixedSize(20, 20)
        zoom_btn.setStyleSheet(f"""
            QToolButton {{ background:transparent; border:none; color:{MID}; font-size:12px; }}
            QToolButton:hover {{ color:{TEAL}; }}
        """)
        rl.addWidget(zoom_btn)
        return row

    def _on_refresh(self):
        """Attempt to run validation if a project is open."""
        if not hasattr(self, "_project") or not self._project:
            return
        try:
            from .tools.validate_routes import run_validation_headless
            results = run_validation_headless(self._project)
            self.push_validation_results(results)
        except Exception:
            # Validation module may not support headless mode yet — show stub
            self.push_validation_results({
                "critical": 0, "errors": 0, "warnings": 0, "info": 0,
                "score_pct": None, "issues": []
            })
            self._placeholder_lbl = QLabel("Validation not available in headless mode.")
            self._issues_layout.addWidget(self._placeholder_lbl)

    def _on_output(self, key):
        """Delegate to main dock callbacks."""
        handlers = {
            "splice_plan":  getattr(self.main_dock, "_on_splice_plan",         None),
            "route_splice": getattr(self.main_dock, "_on_route_splice_export",  None),
            "sld":          getattr(self.main_dock, "_on_sld",                  None),
            "bom":          getattr(self.main_dock, "_on_bom",                  None),
        }
        h = handlers.get(key)
        if h:
            h()

    # ── CLOSE ────────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        QgsSettings().setValue("Conductor/v2/val_dock_floating", self.isFloating())
        super().closeEvent(event)
