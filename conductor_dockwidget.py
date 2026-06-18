# -*- coding: utf-8 -*-
"""
Conductor — Dock Panel
Main UI surface. Manages project state and enables/disables tool buttons.
"""

import os
from qgis.PyQt.QtCore import Qt, pyqtSignal, QSize, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QSizePolicy, QSpacerItem,
    QMessageBox, QFileDialog, QTabWidget, QScrollArea,
    QStackedWidget, QGridLayout, QToolButton,
)
from qgis.core import QgsProject, QgsSnappingConfig, QgsTolerance, QgsSettings
from .conductor_utils import (
    NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, GREY, SKY, PURPLE,
    GREEN, RED, GREEN_BG, ORANGE_BG, RED_BG, plugin_version,
)
from .help_system import HelpContentStore, wrap_with_help
from datetime import datetime


class DialPadToggle:
    """
    Generic helper that adds a compact icon-grid ("dial pad") view alongside
    a tab's normal vertical tool list.

    The same QPushButton instances are moved between the list rows and the
    grid cells when the view is toggled, so enabled/disabled state, click
    handlers, and the orange "active tool" highlight all keep working
    unchanged.
    """

    GRID_ICON_SIZE = QSize(34, 34)
    LIST_ICON_SIZE = QSize(28, 28)
    GRID_MIN_HEIGHT = 48

    def __init__(self, dock, settings_key, columns=4):
        self.dock = dock
        self.settings_key = settings_key
        self.columns = columns
        self.sections = []       # [(header_text, [(row, btn, tool_id), ...]), ...]
        self.stack = None
        self.grid_page = None
        self._grid_layout = None
        self._positions = {}     # (row, btn, tool_id) -> (grid_row, grid_col)
        self._is_grid = False
        self._toggle_buttons = []

    def add_section(self, header_text, items):
        """items: list of (row_widget, button, tool_id_or_None)"""
        self.sections.append((header_text, items))

    def make_toggle_button(self):
        btn = QToolButton()
        btn.setCheckable(True)
        btn.setText("\u25A6")
        btn.setToolTip("Toggle compact grid view")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(26, 22)
        btn.setStyleSheet(f"""
            QToolButton {{
                background:{WHITE}; color:{MID}; border:1px solid {MID};
                border-radius:3px; font-size:12px;
            }}
            QToolButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}
            QToolButton:checked {{
                background:{TEAL}; color:{WHITE}; border-color:{TEAL};
            }}
        """)
        btn.clicked.connect(self.toggle)
        self._toggle_buttons.append(btn)
        return btn

    def build(self, list_page):
        """Build the grid page and wrap list_page + grid_page in a QStackedWidget."""
        self.grid_page = self._build_grid_page()

        self.stack = QStackedWidget()
        self.stack.addWidget(list_page)       # index 0 - existing vertical list
        self.stack.addWidget(self.grid_page)  # index 1 - compact grid

        saved = QgsSettings().value(f"Conductor/dialpad_view_{self.settings_key}", "list")
        if saved == "grid":
            self.set_grid(True, persist=False)

        return self.stack

    def _build_grid_page(self):
        page = QWidget()
        page.setStyleSheet(f"background-color: {LIGHT};")
        grid = QGridLayout(page)
        grid.setContentsMargins(12, 12, 12, 16)
        grid.setSpacing(6)
        self._grid_layout = grid

        # Top row: label + toggle button (mirrors the list view's status row)
        top_row = QWidget()
        tr = QHBoxLayout(top_row)
        tr.setContentsMargins(0, 0, 0, 4)
        tr.setSpacing(6)
        lbl = QLabel("Compact view")
        lbl.setStyleSheet(f"color:{MID}; font-size:11px;")
        tr.addWidget(lbl, 1)
        tr.addWidget(self.make_toggle_button())
        grid.addWidget(top_row, 0, 0, 1, self.columns)

        row = 1
        for header_text, items in self.sections:
            if header_text:
                lbl = self.dock._section_label(header_text)
                grid.addWidget(lbl, row, 0, 1, self.columns)
                row += 1
            for idx, item in enumerate(items):
                r = row + idx // self.columns
                c = idx % self.columns
                self._positions[item] = (r, c)
            if items:
                row += (len(items) + self.columns - 1) // self.columns

        grid.setRowStretch(row, 1)
        for col in range(self.columns):
            grid.setColumnStretch(col, 1)
        return page

    def set_grid(self, grid_on, persist=True):
        if grid_on == self._is_grid:
            if self.stack:
                self.stack.setCurrentIndex(1 if grid_on else 0)
            return

        if grid_on:
            for (row_widget, btn, tool_id), (r, c) in self._positions.items():
                row_widget.layout().removeWidget(btn)
                if btn.property("_dialpad_orig_text") is None:
                    btn.setProperty("_dialpad_orig_text", btn.text())
                btn.setText("")
                btn.setIconSize(self.GRID_ICON_SIZE)
                btn.setMinimumHeight(self.GRID_MIN_HEIGHT)
                title = None
                if tool_id:
                    title = self.dock.help_store.get(tool_id).get("title")
                btn.setToolTip(title or (btn.property("_dialpad_orig_text") or ""))
                self._grid_layout.addWidget(btn, r, c)
        else:
            for (row_widget, btn, tool_id), (r, c) in self._positions.items():
                self._grid_layout.removeWidget(btn)
                orig = btn.property("_dialpad_orig_text")
                if orig is not None:
                    btn.setText(orig)
                btn.setIconSize(self.LIST_ICON_SIZE)
                btn.setMinimumHeight(0)
                btn.setToolTip("")
                row_widget.layout().insertWidget(0, btn, 1)

        self._is_grid = grid_on
        if self.stack:
            self.stack.setCurrentIndex(1 if grid_on else 0)
        for tb in self._toggle_buttons:
            tb.setChecked(grid_on)
        if persist:
            QgsSettings().setValue(
                f"Conductor/dialpad_view_{self.settings_key}",
                "grid" if grid_on else "list"
            )

    def toggle(self):
        self.set_grid(not self._is_grid)


class ConductorDockWidget(QDockWidget):

    closingPlugin = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__("Conductor", parent or iface.mainWindow())
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.help_store = HelpContentStore(self.plugin_dir)
        self._project = None          # ConductorProject when open
        self._tool_buttons = []       # buttons that need a project to be enabled
        self._active_tool_btn = None  # currently active tool button (highlighted)
        self._snapping_prev = None    # saved QgsSnappingConfig before Conductor enables snapping
        from .conductor_utils import UndoStack
        self._undo_stack = UndoStack()

        self.setObjectName("ConductorDockWidget")
        self.setMinimumWidth(280)
        self.setFeatures(
            QDockWidget.DockWidgetMovable |
            QDockWidget.DockWidgetFloatable |
            QDockWidget.DockWidgetClosable
        )
        self._open_dialogs = []
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        container = QWidget()
        container.setObjectName("ConductorContainer")

        # ── Global dark theme QSS ─────────────────────────────────────────
        container.setStyleSheet(f"""
            #ConductorContainer {{
                background-color: {NAVY};
                color: {WHITE};
            }}
            QWidget {{
                background-color: {NAVY};
                color: {WHITE};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QScrollArea, QScrollArea > QWidget > QWidget {{
                background-color: {NAVY};
                border: none;
            }}
            QScrollBar:vertical {{
                background: {NAVY};
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {MID};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QTabWidget::pane {{
                border: none;
                background: {NAVY};
            }}
            QTabBar::tab {{
                background: {NAVY};
                color: {GREY};
                padding: 6px 14px;
                border: none;
                border-bottom: 2px solid transparent;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.5px;
            }}
            QTabBar::tab:selected {{
                color: {TEAL};
                border-bottom: 2px solid {TEAL};
            }}
            QTabBar::tab:hover {{
                color: {WHITE};
            }}
            QLineEdit {{
                background: {LIGHT};
                color: {WHITE};
                border: 1px solid {MID};
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 12px;
                selection-background-color: {TEAL};
            }}
            QLineEdit:focus {{
                border-color: {TEAL};
            }}
            QComboBox {{
                background: {LIGHT};
                color: {WHITE};
                border: 1px solid {MID};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QComboBox:focus {{
                border-color: {TEAL};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView {{
                background: {LIGHT};
                color: {WHITE};
                border: 1px solid {MID};
                selection-background-color: {TEAL};
                selection-color: #0F1923;
            }}
            QSpinBox, QDoubleSpinBox {{
                background: {LIGHT};
                color: {WHITE};
                border: 1px solid {MID};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QSpinBox:focus, QDoubleSpinBox:focus {{
                border-color: {TEAL};
            }}
            QCheckBox {{
                color: {WHITE};
                font-size: 12px;
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border-radius: 3px;
                border: 1px solid {MID};
                background: {LIGHT};
            }}
            QCheckBox::indicator:checked {{
                background: {TEAL};
                border-color: {TEAL};
            }}
            QPushButton {{
                background: {LIGHT};
                color: {WHITE};
                border: 1px solid {MID};
                border-radius: 4px;
                padding: 5px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {TEAL};
                color: {TEAL};
            }}
            QPushButton:pressed {{
                background: {MID};
            }}
            QPushButton:disabled {{
                color: {MID};
                border-color: {LIGHT};
                background: {NAVY};
            }}
            QPushButton[conductor_active=true] {{
                background: {TEAL};
                color: #0F1923;
                border-color: {TEAL};
                font-weight: bold;
            }}
            QLabel {{
                color: {WHITE};
                background: transparent;
            }}
            QFrame[frameShape="4"], QFrame[frameShape="5"] {{
                color: {MID};
            }}
            QProgressBar {{
                background: {LIGHT};
                border: none;
                border-radius: 3px;
                height: 6px;
                text-align: center;
                font-size: 10px;
                color: {WHITE};
            }}
            QProgressBar::chunk {{
                background: {TEAL};
                border-radius: 3px;
            }}
            QToolTip {{
                background: {LIGHT};
                color: {WHITE};
                border: 1px solid {MID};
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 11px;
            }}
        """)

        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        # Postcode search bar
        pc_bar = QWidget()
        pc_bar.setStyleSheet(f"background:#0A1219; padding:0px; border-bottom: 1px solid {MID};")
        pc_layout = QHBoxLayout(pc_bar)
        pc_layout.setContentsMargins(8, 6, 8, 6)
        pc_layout.setSpacing(6)

        self._pc_input = QLineEdit()
        self._pc_input.setPlaceholderText("Zoom to postcode…")
        self._pc_input.setStyleSheet(
            f"border:1px solid {TEAL}; border-radius:3px; padding:4px 8px; "
            f"background:{WHITE}; font-size:12px; color:{NAVY};"
        )
        self._pc_input.returnPressed.connect(self._on_postcode_zoom)
        pc_layout.addWidget(self._pc_input)

        pc_btn = QPushButton("Go")
        pc_btn.setFixedWidth(36)
        pc_btn.setStyleSheet(
            f"background:{TEAL}; color:{WHITE}; border:none; border-radius:3px; "
            f"padding:4px; font-size:12px; font-weight:bold;"
        )
        pc_btn.clicked.connect(self._on_postcode_zoom)
        pc_layout.addWidget(pc_btn)
        root.addWidget(pc_bar)

        # Project summary panel
        root.addWidget(self._build_summary_panel())

        # ── ACTIVE TOOL STATUS BAR ────────────────────────────────────────
        self._active_tool_bar = self._build_active_tool_bar()
        root.addWidget(self._active_tool_bar)
        self._active_tool_bar.setVisible(False)  # hidden until a tool activates

        # ── TAB WIDGET ────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background: {LIGHT};
            }}
            QTabWidget::tab-bar {{
                alignment: left;
            }}
            QTabBar {{
                background: {NAVY};
            }}
            QTabBar::tab {{
                background: {NAVY};
                color: {MID};
                padding: 8px 0px;
                min-width: 120px;
                font-size: 12px;
                font-weight: bold;
                letter-spacing: 2px;
                border: none;
                border-bottom: 3px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: {WHITE};
                border-bottom: 3px solid {TEAL};
                background: {NAVY};
            }}
            QTabBar::tab:hover {{
                color: {WHITE};
            }}
        """)

        self._tabs.addTab(self._build_design_tab(), "DESIGN")
        self._tabs.addTab(self._build_pia_tab(), "PIA")

        # Combined grid-mode toggle, shown in the tab bar's top-right corner
        # so it applies to whichever tab (Design / PIA) is currently active.
        grid_btn = QToolButton()
        grid_btn.setCheckable(True)
        grid_btn.setText("\u25A6 Grid view")
        grid_btn.setToolTip("Toggle compact grid view for this tab")
        grid_btn.setCursor(Qt.PointingHandCursor)
        grid_btn.setStyleSheet(f"""
            QToolButton {{
                background:{NAVY}; color:{MID}; border:1px solid {MID};
                border-radius:3px; font-size:11px; padding:4px 8px;
                margin-right:4px;
            }}
            QToolButton:hover {{ border-color:{TEAL}; color:{WHITE}; }}
            QToolButton:checked {{
                background:{TEAL}; color:{WHITE}; border-color:{TEAL};
            }}
        """)
        grid_btn.clicked.connect(self._on_grid_mode_clicked)
        self._grid_mode_btn = grid_btn
        # Keep this button in sync whenever either tab's view is toggled
        # via the compact view's own internal toggle.
        self._design_toggle._toggle_buttons.append(grid_btn)
        self._pia_toggle._toggle_buttons.append(grid_btn)
        self._tabs.setCornerWidget(grid_btn, Qt.TopRightCorner)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        root.addWidget(self._tabs)
        self.setWidget(container)

    # ── PROJECT SUMMARY PANEL ────────────────────────────────────────────────

    def _build_summary_panel(self):
        """Persistent project summary panel shown above the tabs, regardless
        of which tab (Design / PIA) is currently active."""
        panel = QWidget()
        panel.setStyleSheet(f"background:{LIGHT}; border-radius:6px; border:1px solid {MID};")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)

        # Header row: status text + refresh button
        header_row = QWidget()
        hr = QHBoxLayout(header_row)
        hr.setContentsMargins(0, 0, 0, 0)
        hr.setSpacing(6)

        self._summary_updated_label = QLabel("Project summary")
        self._summary_updated_label.setStyleSheet(f"color:{MID}; font-size:11px;")
        hr.addWidget(self._summary_updated_label, 1)

        refresh_btn = QPushButton("\u21BB")
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setToolTip("Refresh project summary")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background:{WHITE}; color:{NAVY}; border:1px solid {MID};
                border-radius:3px; font-size:13px; padding:0px;
            }}
            QPushButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}
        """)
        refresh_btn.clicked.connect(self._on_refresh_summary)
        hr.addWidget(refresh_btn)
        outer.addWidget(header_row)

        # Row 1: premises / routed / partial / unserved
        row1 = QWidget()
        g1 = QHBoxLayout(row1)
        g1.setContentsMargins(0, 0, 0, 0)
        g1.setSpacing(6)
        self._sum_premises = self._stat_cell(g1, "--", "premises")
        self._sum_routed   = self._stat_cell(g1, "--", "routed",   fg=GREEN,  bg=GREEN_BG)
        self._sum_partial  = self._stat_cell(g1, "--", "partial",  fg=ORANGE, bg=ORANGE_BG)
        self._sum_unserved = self._stat_cell(g1, "--", "unserved", fg=RED,    bg=RED_BG)
        outer.addWidget(row1)

        # Row 2: fibre length / duct length / estimated materials cost
        row2 = QWidget()
        g2 = QHBoxLayout(row2)
        g2.setContentsMargins(0, 0, 0, 0)
        g2.setSpacing(6)
        self._sum_fibre = self._stat_cell(g2, "--", "fibre")
        self._sum_duct  = self._stat_cell(g2, "--", "duct")
        self._sum_cost  = self._stat_cell(g2, "--", "est. materials")
        outer.addWidget(row2)

        return panel

    def _stat_cell(self, layout, value_text, caption, fg=None, bg=None):
        """A small bordered cell showing a value over a caption, used in the
        project summary panel. Returns the value QLabel for later updates."""
        cell = QWidget()
        cell.setStyleSheet(
            f"background:{LIGHT}; border:1px solid {MID}; border-radius:6px;"
        )
        cl = QVBoxLayout(cell)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.setSpacing(0)

        value_lbl = QLabel(value_text)
        value_lbl.setAlignment(Qt.AlignCenter)
        value_lbl.setStyleSheet(f"color:{fg or WHITE}; font-size:16px; font-weight:700; border:none; background:transparent;")
        cl.addWidget(value_lbl)

        cap_lbl = QLabel(caption)
        cap_lbl.setAlignment(Qt.AlignCenter)
        cap_lbl.setStyleSheet(f"color:{GREY}; font-size:10px; border:none; background:transparent;")
        cl.addWidget(cap_lbl)

        layout.addWidget(cell, 1)
        return value_lbl

    def _reset_summary_panel(self):
        """Show placeholder dashes when no project is open / nothing computed yet."""
        for lbl in (self._sum_premises, self._sum_routed, self._sum_partial,
                    self._sum_unserved, self._sum_fibre, self._sum_duct, self._sum_cost):
            lbl.setText("--")
        self._summary_updated_label.setText("Project summary")

    def _on_refresh_summary(self):
        if not self._project:
            self._reset_summary_panel()
            return

        try:
            from .tools.project_summary import compute_summary
            data = compute_summary(project=self._project)
        except Exception as e:
            QMessageBox.warning(self, "Project summary", f"Could not compute project summary:\n{e}")
            return

        self._sum_premises.setText(str(data["premises"]))
        self._sum_routed.setText(str(data["routed"]))
        self._sum_partial.setText(str(data["partial"]))
        self._sum_unserved.setText(str(data["unserved"]))
        self._sum_fibre.setText(f"{data['fibre_km']:.1f} km")
        self._sum_duct.setText(f"{data['duct_km']:.1f} km")
        self._sum_cost.setText(f"\u00A3{data['materials_cost']:,.0f}")

        stamp = datetime.now().strftime("%H:%M")
        suffix = "  (partial)" if data.get("error") else ""
        self._summary_updated_label.setText(f"Project summary \u00B7 updated {stamp}{suffix}")
        if data.get("error"):
            self._summary_updated_label.setToolTip(data["error"])
        else:
            self._summary_updated_label.setToolTip("")

    # ── GRID-MODE TOGGLE (shared between Design / PIA tabs) ──────────────────

    def _active_dialpad_toggle(self):
        return self._pia_toggle if self._tabs.currentIndex() == 1 else self._design_toggle

    def _on_grid_mode_clicked(self, checked):
        self._active_dialpad_toggle().set_grid(checked)

    def _on_tab_changed(self, index):
        self._grid_mode_btn.setChecked(self._active_dialpad_toggle()._is_grid)

    def _collapsible_section(self, title, tool_count, start_expanded=True):
        """Collapsible section header with chevron toggle and count badge."""
        # Header
        header = QWidget()
        header.setStyleSheet(
            f"QWidget {{ background:{LIGHT}; border-radius:4px; border-top: 1px solid {MID}; }}"
            f"QWidget:hover {{ background:#243347; }}"
        )
        header.setCursor(Qt.PointingHandCursor)
        header.setFixedHeight(36)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 0, 8, 0)
        h_layout.setSpacing(6)

        chevron = QLabel("▾" if start_expanded else "▸")
        chevron.setStyleSheet(f"color:{TEAL}; font-size:11px; background:transparent;")
        chevron.setFixedWidth(14)
        h_layout.addWidget(chevron)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color:{WHITE}; font-size:11px; font-weight:700; "
            f"letter-spacing:1px; background:transparent;"
        )
        h_layout.addWidget(title_lbl, 1)

        badge = QLabel(str(tool_count))
        badge.setStyleSheet(
            f"color:{GREY}; font-size:9px; font-weight:700; background:transparent;"
        )
        h_layout.addWidget(badge)

        # Content container
        section_content = QWidget()
        section_content.setStyleSheet("background:transparent;")
        section_layout = QVBoxLayout(section_content)
        section_layout.setContentsMargins(0, 4, 0, 6)
        section_layout.setSpacing(1)
        section_content.setVisible(start_expanded)

        _state = [start_expanded]
        def _toggle(event=None):
            _state[0] = not _state[0]
            section_content.setVisible(_state[0])
            chevron.setText("▾" if _state[0] else "▸")
        header.mousePressEvent = _toggle

        # Defer visibility so Qt layout doesn't reset it — capture by value
        from qgis.PyQt.QtCore import QTimer
        _exp = start_expanded
        _sc  = section_content
        _chv = chevron
        QTimer.singleShot(0, lambda exp=_exp, sc=_sc, chv=_chv: (
            sc.setVisible(exp),
            chv.setText("▾" if exp else "▸")
        ))

        return header, section_content, section_layout

    # ── RECENT TOOLS ─────────────────────────────────────────────────────────

    _MAX_RECENT = 5

    def _record_recent_tool(self, tool_name):
        """Persist a tool name + timestamp to QgsSettings and refresh the UI."""
        import json
        from datetime import datetime
        settings = QgsSettings()
        raw = settings.value("Conductor/v2/recent_tools", "[]")
        try:
            recent = json.loads(raw)
        except Exception:
            recent = []

        # Remove existing entry for this tool so it bubbles to top
        recent = [r for r in recent if r.get("name") != tool_name]
        recent.insert(0, {"name": tool_name, "ts": datetime.now().isoformat()})
        recent = recent[:self._MAX_RECENT]
        settings.setValue("Conductor/v2/recent_tools", json.dumps(recent))

        if hasattr(self, "_recent_tools_container"):
            self._refresh_recent_tools_ui()

    def _load_recent_tools(self):
        import json
        settings = QgsSettings()
        raw = settings.value("Conductor/v2/recent_tools", "[]")
        try:
            return json.loads(raw)
        except Exception:
            return []

    def _refresh_recent_tools_ui(self):
        """Rebuild the Recent Tools list widget from QgsSettings."""
        from datetime import datetime
        container = self._recent_tools_container
        layout = container.layout()
        # Clear existing rows
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        recent = self._load_recent_tools()
        if not recent:
            lbl = QLabel("No tools used yet.")
            lbl.setStyleSheet(f"color:{MID}; font-size:10px; padding:4px 0px;")
            layout.addWidget(lbl)
            return

        now = datetime.now()
        for entry in recent:
            name = entry.get("name", "")
            ts_str = entry.get("ts", "")
            # Human-readable relative time
            try:
                ts = datetime.fromisoformat(ts_str)
                delta = int((now - ts).total_seconds() / 60)
                if delta < 1:
                    age = "Just now"
                elif delta == 1:
                    age = "1 min ago"
                elif delta < 60:
                    age = f"{delta} min ago"
                else:
                    age = f"{delta//60} hr ago"
            except Exception:
                age = ""

            row = QWidget()
            row.setStyleSheet(
                f"QWidget {{ background:transparent; border-radius:3px; }}"
                f"QWidget:hover {{ background:{LIGHT}; }}"
            )
            row.setCursor(Qt.PointingHandCursor)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 3, 4, 3)
            rl.setSpacing(6)

            dot = QLabel("○")
            dot.setStyleSheet(f"color:{TEAL}; font-size:9px; background:transparent;")
            dot.setFixedWidth(12)
            rl.addWidget(dot)

            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(f"color:{WHITE}; font-size:11px; background:transparent;")
            rl.addWidget(name_lbl, 1)

            age_lbl = QLabel(age)
            age_lbl.setStyleSheet(f"color:{MID}; font-size:10px; background:transparent;")
            rl.addWidget(age_lbl)

            # Click to re-activate tool by name lookup
            _name = name
            row.mousePressEvent = lambda e, n=_name: self._reactivate_tool_by_name(n)
            layout.addWidget(row)

    def _reactivate_tool_by_name(self, name):
        """Find the tool callback by display label and invoke it."""
        # Build a name→callback map on first call
        if not hasattr(self, "_label_to_callback"):
            self._label_to_callback = {
                "Import Premises (AddressBase)": self._on_import_premises,
                "Build Areas":                   self._on_draw_build_area,
                "Place Cabinet / POP":           self._on_place_pop,
                "Edit Cabinet / POP":            self._on_edit_pop,
                "Place Chamber":                 self._on_place_chamber,
                "Digitise Duct":                 self._on_digitise_duct,
                "Digitise Drop Duct":            self._on_digitise_drop,
                "Road Crossing":                 self._on_digitise_road_crossing,
                "Stream Crossing":               self._on_digitise_stream_crossing,
                "Digitise Cable":                self._on_digitise_fibre,
                "Digitise Bundle":               self._on_digitise_bundle,
                "Place Joint":                   self._on_place_joint,
                "Assign Fibre Roles":            self._on_assign_fibres,
                "Fibre Trace":                   self._on_fibre_trace,
                "Fibre Count":                   self._on_fibre_count,
                "Validate Fibre Routes":         self._on_validate_routes,
                "Splice Plan Export":            self._on_splice_plan,
                "Route Splice Export":           self._on_route_splice_export,
                "Single Line Diagram":           self._on_sld,
                "Bill of Materials":             self._on_bom,
                "Cabinet Cost":                  self._on_cabinet_cost_calculator,
                "Edit Asset":                    self._on_edit_asset,
                "Delete Asset":                  self._on_delete_asset,
                "Move Asset":                    self._on_move_asset,
                # PIA
                "Place Pole":                    self._on_place_pole,
                "Place PIA UG Chamber":          self._on_place_pia_chamber,
                "Digitise Aerial Span":          self._on_digitise_aerial_span,
                "Digitise PIA UG Duct":          self._on_digitise_pia_ug_duct,
                "Place CBT":                     self._on_place_cbt,
                "Draw CBT Tail":                 self._on_digitise_cbt_tail,
                "Digitise Aerial Drop":          self._on_digitise_aerial_drop,
                "Digitise PIA UG Drop":          self._on_digitise_pia_ug_drop,
            }
        cb = self._label_to_callback.get(name)
        if cb:
            cb()

    def _build_active_tool_bar(self):
        """Thin 36px strip between summary and tabs showing current tool state."""
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet(
            f"background:{LIGHT}; border-top:1px solid {MID}; border-bottom:1px solid {MID};"
        )
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(8, 0, 8, 0)
        bl.setSpacing(8)

        self._tool_bar_icon = QLabel("⬤")
        self._tool_bar_icon.setFixedWidth(14)
        self._tool_bar_icon.setStyleSheet(f"color:{TEAL}; font-size:10px;")
        bl.addWidget(self._tool_bar_icon)

        self._tool_bar_name = QLabel("—")
        self._tool_bar_name.setStyleSheet(f"color:{WHITE}; font-size:12px; font-weight:600;")
        bl.addWidget(self._tool_bar_name)

        self._tool_bar_hint = QLabel("Right-click to finish · Esc to cancel")
        self._tool_bar_hint.setStyleSheet(f"color:{GREY}; font-size:10px;")
        bl.addWidget(self._tool_bar_hint, 1)

        dismiss_btn = QToolButton()
        dismiss_btn.setText("✕")
        dismiss_btn.setFixedSize(20, 20)
        dismiss_btn.setToolTip("Cancel active tool (Esc)")
        dismiss_btn.setCursor(Qt.PointingHandCursor)
        dismiss_btn.setStyleSheet(f"""
            QToolButton {{ background:transparent; border:none; color:{GREY}; font-size:12px; }}
            QToolButton:hover {{ color:{RED}; }}
        """)
        dismiss_btn.clicked.connect(self._on_cancel_active_tool)
        bl.addWidget(dismiss_btn)

        return bar

    def _show_active_tool(self, name, hint="Right-click to finish · Esc to cancel"):
        """Show the active tool status bar with tool name and hint text."""
        self._tool_bar_name.setText(name)
        self._tool_bar_hint.setText(hint)
        self._active_tool_bar.setVisible(True)
        # Also record in recent tools
        self._record_recent_tool(name)

    def _hide_active_tool_bar(self):
        """Hide the active tool status bar."""
        self._active_tool_bar.setVisible(False)

    def _on_cancel_active_tool(self):
        """Dismiss the active map tool (equivalent to Esc)."""
        try:
            self.iface.mapCanvas().unsetMapTool(self.iface.mapCanvas().mapTool())
        except Exception:
            pass
        self._clear_active_button()
        self._hide_active_tool_bar()

    def _build_design_tab(self):
        """Design tab with collapsible grouped tool sections."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet(f"background:{NAVY}; border:none;")

        container = QWidget()
        container.setStyleSheet(f"background:{NAVY};")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(2)

        toggle = DialPadToggle(self, "design", columns=4)
        self._design_toggle = toggle

        # Project status
        self._status_label = QLabel("No project open")
        self._status_label.setStyleSheet(f"color:{MID}; font-size:11px; padding:2px 4px 6px 4px;")
        cl.addWidget(self._status_label)

        # ── PROJECT (always visible, not collapsible) ──────────────────
        proj_lbl = self._section_label("PROJECT")
        cl.addWidget(proj_lbl)

        project_items = []
        row = self._primary_button("\uFF0B  New Project", self._on_new_project, icon="new_project.svg")
        cl.addWidget(row)
        project_items.append(self._dialpad_item(row, "new_project.svg"))

        row = self._secondary_button("Open Project", self._on_open_project, icon="open_project.svg")
        cl.addWidget(row)
        project_items.append(self._dialpad_item(row, "open_project.svg"))

        # Undo / Redo
        undo_row_widget = QWidget()
        undo_row_widget.setStyleSheet("background:transparent;")
        undo_row = QHBoxLayout(undo_row_widget)
        undo_row.setSpacing(4)
        undo_row.setContentsMargins(0, 2, 0, 4)
        self._btn_undo = QPushButton("\u21a9  Undo")
        self._btn_undo.setToolTip("Undo last action (Ctrl+Z)")
        self._btn_undo.setEnabled(False)
        self._btn_undo.setStyleSheet(
            f"QPushButton {{ background:{LIGHT}; color:{WHITE}; border:1px solid {MID};"
            f" border-radius:4px; padding:4px 8px; font-size:11px; }}"
            f"QPushButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}"
            f"QPushButton:disabled {{ color:{MID}; border-color:{LIGHT}; }}")
        self._btn_undo.clicked.connect(self._on_undo)
        self._btn_redo = QPushButton("\u21aa  Redo")
        self._btn_redo.setToolTip("Redo (Ctrl+Shift+Z)")
        self._btn_redo.setEnabled(False)
        self._btn_redo.setStyleSheet(
            f"QPushButton {{ background:{LIGHT}; color:{WHITE}; border:1px solid {MID};"
            f" border-radius:4px; padding:4px 8px; font-size:11px; }}"
            f"QPushButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}"
            f"QPushButton:disabled {{ color:{MID}; border-color:{LIGHT}; }}")
        self._btn_redo.clicked.connect(self._on_redo)
        undo_row.addWidget(self._btn_undo)
        undo_row.addWidget(self._btn_redo)
        cl.addWidget(undo_row_widget)
        cl.addWidget(self._divider())
        toggle.add_section("PROJECT", project_items)

        # ── RECENT TOOLS ──────────────────────────────────────────────
        recent_header_row = QWidget()
        rhr = QHBoxLayout(recent_header_row)
        rhr.setContentsMargins(0, 6, 0, 0)
        rhr.setSpacing(0)
        recent_lbl = self._section_label("RECENT TOOLS")
        rhr.addWidget(recent_lbl, 1)
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(18)
        clear_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{MID}; border:none; font-size:10px; padding:0 4px; }}"
            f"QPushButton:hover {{ color:{TEAL}; }}"
        )
        def _clear_recent():
            QgsSettings().setValue("Conductor/v2/recent_tools", "[]")
            self._refresh_recent_tools_ui()
        clear_btn.clicked.connect(_clear_recent)
        rhr.addWidget(clear_btn)
        cl.addWidget(recent_header_row)

        self._recent_tools_container = QWidget()
        self._recent_tools_container.setStyleSheet("background:transparent;")
        rtl = QVBoxLayout(self._recent_tools_container)
        rtl.setContentsMargins(0, 2, 0, 6)
        rtl.setSpacing(0)
        cl.addWidget(self._recent_tools_container)
        # Populate immediately on build
        QTimer.singleShot(0, self._refresh_recent_tools_ui)

        cl.addWidget(self._divider())

        # ── Helper to build a collapsible group ───────────────────────
        all_dialpad_items = []
        def _add_group(group_title, tools, expanded=True):
            hdr, grp_content, grp_layout = self._collapsible_section(
                group_title, len(tools), start_expanded=expanded)
            cl.addWidget(hdr)
            cl.addWidget(grp_content)
            items = []
            for label, slot, icon in tools:
                btn_row = self._tool_button(label, slot, icon=icon)
                grp_layout.addWidget(btn_row)
                items.append(self._dialpad_item(btn_row, icon))
            all_dialpad_items.extend(items)
            toggle.add_section(group_title, items)

        # ── WORKFLOW ──────────────────────────────────────────────────
        _add_group("WORKFLOW", [
            ("Import Premises (AddressBase)", self._on_import_premises,  "import_premises_addressbase.svg"),
            ("Build Areas",                   self._on_draw_build_area,  "build_areas.svg"),
            ("Place Cabinet / POP",           self._on_place_pop,        "place_cabinet_pop.svg"),
        ], expanded=True)

        # ── CIVIL ─────────────────────────────────────────────────────
        _add_group("CIVIL", [
            ("Edit Cabinet / POP",    self._on_edit_pop,                  "edit_cabinet_pop.svg"),
            ("Place Chamber",         self._on_place_chamber,             "place_chamber.svg"),
            ("Digitise Duct",         self._on_digitise_duct,             "digitise_duct.svg"),
            ("Digitise Drop Duct",    self._on_digitise_drop,             "digitise_drop_duct.svg"),
            ("Road Crossing",         self._on_digitise_road_crossing,    "digitise_road_crossing.svg"),
            ("Stream Crossing",       self._on_digitise_stream_crossing,  "digitise_stream_crossing.svg"),
        ], expanded=True)

        # ── FIBRE ─────────────────────────────────────────────────────
        _add_group("FIBRE", [
            ("Digitise Cable",       self._on_digitise_fibre,   "digitise_cable.svg"),
            ("Digitise Bundle",      self._on_digitise_bundle,  "digitise_bundle.svg"),
            ("Place Joint",          self._on_place_joint,      "place_joint.svg"),
            ("Assign Fibre Roles",   self._on_assign_fibres,    "assign_fibre_roles.svg"),
        ], expanded=True)

        # ── ANALYSIS ──────────────────────────────────────────────────
        _add_group("ANALYSIS", [
            ("Fibre Trace",           self._on_fibre_trace,          "fibre_trace.svg"),
            ("Fibre Count",           self._on_fibre_count,          "fibre_count_calculator.svg"),
            ("Validate Fibre Routes", self._on_validate_routes,      "validate_fibre_routes.svg"),
        ], expanded=False)

        # ── OUTPUTS ───────────────────────────────────────────────────
        _add_group("OUTPUTS", [
            ("Splice Plan Export",    self._on_splice_plan,              "splice_plan_export.svg"),
            ("Route Splice Export",   self._on_route_splice_export,      "route_splice_export.svg"),
            ("Single Line Diagram",   self._on_sld,                      "single_line_diagram.svg"),
            ("Bill of Materials",     self._on_bom,                      "bill_of_materials.svg"),
            ("Cabinet Cost",          self._on_cabinet_cost_calculator,   "cabinet_cost_calculator.svg"),
        ], expanded=False)

        # ── TOOLS ─────────────────────────────────────────────────────
        _add_group("TOOLS", [
            ("Edit Asset",    self._on_edit_asset,    "edit_cabinet_pop.svg"),
            ("Delete Asset",  self._on_delete_asset,  "delete_asset.svg"),
            ("Move Asset",    self._on_move_asset,    "move_asset.svg"),
        ], expanded=False)

        cl.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        footer = QLabel(f"Conductor v2  \u00B7  Mav3r1ck Media Studio")
        footer.setStyleSheet(f"color:{MID}; font-size:10px; padding:8px 0px;")
        footer.setAlignment(Qt.AlignCenter)
        cl.addWidget(footer)

        stack = toggle.build(container)
        scroll_area.setWidget(stack)
        return scroll_area


    def _build_pia_tab(self):
        """PIA tab with collapsible grouped tool sections — mirrors Design tab pattern."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet(f"background:{NAVY}; border:none;")

        container = QWidget()
        container.setStyleSheet(f"background:{NAVY};")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(2)

        toggle = DialPadToggle(self, "pia", columns=4)
        self._pia_toggle = toggle

        # Info label
        info = QLabel("Physical Infrastructure Access tools for pole-mounted and Openreach subduct routes.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{MID}; font-size:11px; padding:0px 4px 6px 4px;")
        cl.addWidget(info)

        # ── Helper (same pattern as Design tab) ───────────────────────
        def _add_pia_group(group_title, tools, expanded=True):
            hdr, grp_content, grp_layout = self._collapsible_section(
                group_title, len(tools), start_expanded=expanded)
            cl.addWidget(hdr)
            cl.addWidget(grp_content)
            items = []
            for label, slot, icon in tools:
                btn_row = self._tool_button(label, slot, icon=icon)
                grp_layout.addWidget(btn_row)
                items.append(self._dialpad_item(btn_row, icon))
            toggle.add_section(group_title, items)

        # ── POLES & CBTs ──────────────────────────────────────────────
        _add_pia_group("POLES & CBTs", [
            ("Place Pole",     self._on_place_pole,          "place_pole.svg"),
            ("Place CBT",      self._on_place_cbt,           "place_cbt.svg"),
            ("Draw CBT Tail",  self._on_digitise_cbt_tail,   "digitise_cbt_tail.svg"),
        ], expanded=True)

        # ── AERIAL ────────────────────────────────────────────────────
        _add_pia_group("AERIAL", [
            ("Digitise Aerial Span", self._on_digitise_aerial_span,  "digitise_aerial_span.svg"),
            ("Digitise Aerial Drop", self._on_digitise_aerial_drop,  "digitise_aerial_drop.svg"),
        ], expanded=True)

        # ── PIA UNDERGROUND ───────────────────────────────────────────
        _add_pia_group("PIA UNDERGROUND", [
            ("Place PIA UG Chamber", self._on_place_pia_chamber,    "place_pia_ug_chamber.svg"),
            ("Digitise PIA UG Duct", self._on_digitise_pia_ug_duct, "digitise_pia_ug_duct.svg"),
            ("Digitise PIA UG Drop", self._on_digitise_pia_ug_drop, "digitise_pia_ug_drop.svg"),
        ], expanded=True)

        cl.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        pia_footer = QLabel(f"PIA tools  \u00B7  Conductor v{plugin_version()}")
        pia_footer.setStyleSheet(f"color:{MID}; font-size:10px; padding:8px 0px;")
        pia_footer.setAlignment(Qt.AlignCenter)
        cl.addWidget(pia_footer)

        stack = toggle.build(container)
        scroll_area.setWidget(stack)
        return scroll_area


    def _build_header(self):
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(f"background-color:{NAVY};")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 0, 12, 0)

        icon_path = os.path.join(self.plugin_dir, "icons", "conductor.png")
        if os.path.exists(icon_path):
            ico = QLabel()
            ico.setPixmap(QIcon(icon_path).pixmap(26, 26))
            layout.addWidget(ico)

        title = QLabel("CONDUCTOR")
        title.setStyleSheet(f"color:{WHITE}; font-size:15px; font-weight:700; letter-spacing:3px; padding-left:8px; font-family: 'Segoe UI', Arial, sans-serif;")
        layout.addWidget(title)
        layout.addStretch()

        sub = QLabel("FTTP Design")
        sub.setStyleSheet(f"color:{TEAL}; font-size:10px; font-weight:600; letter-spacing:1px; padding-right:8px;")
        layout.addWidget(sub)

        settings_btn = QToolButton()
        settings_ic = self._icon("optical_budget_calculator.svg")
        if settings_ic:
            settings_btn.setIcon(settings_ic)
            settings_btn.setIconSize(QSize(20, 20))
        else:
            settings_btn.setText("\u2699")
        settings_btn.setToolTip("Optical budget settings")
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.setStyleSheet(f"""
            QToolButton {{ background:transparent; border:none; padding:2px; }}
            QToolButton:hover {{ background:rgba(255,255,255,40); border-radius:4px; }}
        """)
        settings_btn.clicked.connect(self._on_optical_budget)
        layout.addWidget(settings_btn)
        return header

    # ── WIDGET FACTORIES ───────────────────────────────────────────────────────

    def _dialpad_item(self, row, icon):
        """Extract the (row_widget, button, tool_id) tuple from a help-wrapped row widget."""
        btn = row.layout().itemAt(0).widget()
        tool_id = os.path.splitext(icon)[0] if icon else None
        return (row, btn, tool_id)

    def _section_label(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color:{GREY}; font-size:9px; font-weight:700; letter-spacing:2px; padding:10px 0px 4px 0px;")
        return l

    def _icon(self, name):
        """Load a tool icon from the icons/ directory. Returns None if not found."""
        if not name:
            return None
        path = os.path.join(self.plugin_dir, 'icons', name)
        if os.path.isfile(path):
            return QIcon(path)
        return None

    def _primary_button(self, text, callback, icon=None):
        btn = QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{ background:{TEAL}; color:#0F1923; border:none; border-radius:4px;
                           padding:8px 12px; font-size:12px; font-weight:bold; text-align:left; }}
            QPushButton:hover {{ background:{TEAL}; }}
            QPushButton:pressed {{ background:{ORANGE}; }}
        """)
        btn.setCursor(Qt.PointingHandCursor)
        ic = self._icon(icon)
        if ic:
            btn.setIcon(ic)
            btn.setIconSize(QSize(28, 28))
        btn.clicked.connect(callback)
        if icon:
            tool_id = os.path.splitext(icon)[0]
            return wrap_with_help(btn, tool_id, self.help_store)
        return btn

    def _secondary_button(self, text, callback, icon=None):
        btn = QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{WHITE}; border:1px solid {MID};
                           border-radius:4px; padding:6px 12px; font-size:12px; text-align:left; }}
            QPushButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}
            QPushButton:pressed {{ background:{LIGHT}; }}
        """)
        btn.setCursor(Qt.PointingHandCursor)
        ic = self._icon(icon)
        if ic:
            btn.setIcon(ic)
            btn.setIconSize(QSize(28, 28))
        btn.clicked.connect(callback)
        if icon:
            tool_id = os.path.splitext(icon)[0]
            return wrap_with_help(btn, tool_id, self.help_store)
        return btn

    def _tool_button(self, text, callback, icon=None):
        """A button that requires an open project — starts disabled."""
        btn = QPushButton(text)
        btn.setCheckable(False)
        btn.setProperty("conductor_active", False)
        btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{WHITE}; border:none; border-left:2px solid transparent;
                           border-radius:0px; padding:4px 12px; font-size:12px; text-align:left; min-height:32px; }}
            QPushButton:hover {{ background:{LIGHT}; color:{TEAL}; border-left:2px solid {TEAL}; }}
            QPushButton:pressed {{ background:{MID}; }}
            QPushButton:disabled {{ color:{MID}; }}
            QPushButton:disabled {{ color:{MID}; border-color:{MID}; background:{LIGHT}; }}
            QPushButton[conductor_active=true] {{ background:{ORANGE}; color:{WHITE}; border-color:{ORANGE}; font-weight:bold; }}
        """)
        ic = self._icon(icon)
        if ic:
            btn.setIcon(ic)
            btn.setIconSize(QSize(28, 28))
        btn.setEnabled(False)
        btn.clicked.connect(callback)
        btn._conductor_callback = callback  # strong ref for _refresh_tool_states
        self._tool_buttons.append(btn)
        if not hasattr(self, '_btn_map'):
            self._btn_map = {}
        self._btn_map[callback] = btn
        if icon:
            tool_id = os.path.splitext(icon)[0]
            return wrap_with_help(btn, tool_id, self.help_store)
        return btn

    def _activate_tool(self, callback):
        """Highlight the button for this callback. Call at the start of each tool handler."""
        btn = getattr(self, '_btn_map', {}).get(callback)
        self._set_active_button(btn)

    def _enable_conductor_snapping(self):
        """Enable vertex+segment snapping for digitise tools, saving previous config for restore."""
        try:
            qgs_project = QgsProject.instance()
            config = qgs_project.snappingConfig()
            self._snapping_prev = QgsSnappingConfig(config)   # deep copy
            config.setEnabled(True)
            config.setMode(QgsSnappingConfig.AllLayers)
            config.setType(QgsSnappingConfig.VertexAndSegment)
            config.setUnits(QgsTolerance.Pixels)
            config.setTolerance(12)
            qgs_project.setSnappingConfig(config)
        except Exception:
            pass  # never crash a tool activation due to snapping

    def _restore_snapping(self):
        """Restore the snapping config that was in place before Conductor enabled it."""
        if self._snapping_prev is not None:
            try:
                QgsProject.instance().setSnappingConfig(self._snapping_prev)
            except Exception:
                pass
            self._snapping_prev = None

    def _set_active_button(self, btn):
        """Highlight the active tool button; clear the previous one."""
        if self._active_tool_btn and self._active_tool_btn is not btn:
            self._active_tool_btn.setProperty("conductor_active", False)
            self._active_tool_btn.style().unpolish(self._active_tool_btn)
            self._active_tool_btn.style().polish(self._active_tool_btn)
        self._active_tool_btn = btn
        if btn:
            btn.setProperty("conductor_active", True)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _clear_active_button(self):
        """Called when the map tool is deactivated externally (Esc, another tool)."""
        self._hide_active_tool_bar()
        if self._active_tool_btn:
            self._active_tool_btn.setProperty("conductor_active", False)
            self._active_tool_btn.style().unpolish(self._active_tool_btn)
            self._active_tool_btn.style().polish(self._active_tool_btn)
            self._active_tool_btn = None
        self._restore_snapping()
        if hasattr(self, '_fibre_trace_tool') and self._fibre_trace_tool:
            try:
                self._fibre_trace_tool._clear_bands()
                self.iface.mapCanvas().refresh()
            except Exception:
                pass

    def _divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color:{MID}; margin:4px 0px; background:{MID};")
        return line

    # ── PROJECT STATE ──────────────────────────────────────────────────────────

    def set_project(self, conductor_project):
        """Called after a project is created or opened."""
        self._project = conductor_project
        name = conductor_project.project_name
        code = conductor_project.area_id
        self._status_label.setText(f"▸  {name}  ({code})")
        self._status_label.setStyleSheet(f"color:{TEAL}; font-size:11px; font-weight:500; padding-bottom:2px; letter-spacing:0.3px;")
        # Tool availability derived from project state
        self._refresh_tool_states()
        # Clear undo stack on project change
        self._undo_stack.clear()
        self._update_undo_buttons()
        # Set up keyboard shortcuts if not already done
        if not hasattr(self, "_shortcut_undo"):
            self._setup_shortcuts()
        try:
            self.iface.mapCanvas().mapToolSet.connect(self._on_map_tool_set)
        except Exception:
            pass

        # Auto-refresh summary 2.5s after any commit to key layers
        from qgis.PyQt.QtCore import QTimer
        if not hasattr(self, '_summary_timer'):
            self._summary_timer = QTimer(self)
            self._summary_timer.setSingleShot(True)
            self._summary_timer.timeout.connect(self._on_refresh_summary)

        def _schedule_refresh(*args):
            self._summary_timer.start(2500)

        for layer_name in ("bundles", "drop_ducts", "cables", "joints", "premises"):
            layer = conductor_project.get_layer(layer_name)
            if layer:
                try:
                    layer.afterCommitChanges.connect(_schedule_refresh)
                except Exception:
                    pass

        self._on_refresh_summary()
        # Notify secondary docks if they have been registered by conductor.py
        if hasattr(self, "_val_dock") and self._val_dock:
            try:
                self._val_dock.set_project(conductor_project)
            except Exception:
                pass
        if hasattr(self, "_routes_dock") and self._routes_dock:
            try:
                self._routes_dock.set_project(conductor_project)
            except Exception:
                pass

    def _refresh_tool_states(self):
        """Enable/disable tools based on project state (ground-truth from gpkg).

        Stage 0 — no project:        all tools disabled
        Stage 1 — project created:   Import Premises only
        Stage 2 — premises imported: + Draw Build Area
        Stage 3 — build area drawn:  + Place Cabinet / POP
        Stage 4 — cabinet placed:    + all remaining tools
        """
        if not self._project:
            for btn in self._tool_buttons:
                btn.setEnabled(False)
            return

        def _count(layer_name):
            try:
                layer = self._project.get_layer(layer_name)
                return layer.featureCount() if layer and layer.isValid() else 0
            except Exception:
                return 0

        has_premises   = _count("premises")      > 0
        has_build_area = _count("build_areas")   > 0
        has_cabinet    = _count("exchange_pops") > 0

        always_on = {self._on_new_project, self._on_open_project}
        enabled = set(always_on) | {self._on_import_premises}
        if has_premises:
            enabled |= {self._on_draw_build_area}
        if has_premises and has_build_area:
            enabled |= {self._on_place_pop}
        if has_premises and has_build_area and has_cabinet:
            enabled = None  # unlock everything

        for btn in self._tool_buttons:
            cb = getattr(btn, '_conductor_callback', None)
            if enabled is None:
                btn.setEnabled(True)
            else:
                btn.setEnabled(cb in enabled)

    def _on_map_tool_set(self, new_tool, old_tool):
        """Deactivate button highlight if the tool was cleared externally."""
        conductor_tool_types = (
            "DrawBuildAreaMapTool", "PlacePOPMapTool", "EditPOPMapTool",
            "PlaceChamberMapTool", "PlaceJointMapTool",
            "DigitiseDuctMapTool", "DigitiseFibreMapTool",
            "DigitiseDropMapTool", "DigitiseBundleMapTool",
            "EditAssetMapTool", "DeleteAssetMapTool", "MoveAssetMapTool",
            # PIA tools
            "PlacePoleMapTool", "PlaceCBTMapTool", "PlacePIAChamberMapTool",
            "DigitiseAerialSpanMapTool", "DigitisePIAUGDuctMapTool", "DigitiseCBTTailMapTool",
            "DigitiseAerialDropMapTool", "DigitisePIAUGDropMapTool",
        )
        if new_tool is None or type(new_tool).__name__ not in conductor_tool_types:
            self._clear_active_button()

    # ── CALLBACKS — DESIGN TAB ─────────────────────────────────────────────────

    # ── Undo / Redo ───────────────────────────────────────────────────────────

    def push_undo(self, entry):
        """Push an undo entry. Called by tool _finish() after successful commit."""
        self._undo_stack.push(entry)
        self._update_undo_buttons()

    def _update_undo_buttons(self):
        can_undo = self._undo_stack.can_undo()
        can_redo = self._undo_stack.can_redo()
        self._btn_undo.setEnabled(can_undo)
        self._btn_redo.setEnabled(can_redo)
        self._btn_undo.setToolTip(
            f"Undo: {self._undo_stack.undo_description()} (Ctrl+Z)"
            if can_undo else "Nothing to undo")
        self._btn_redo.setToolTip(
            f"Redo: {self._undo_stack.redo_description()} (Ctrl+Shift+Z)"
            if can_redo else "Nothing to redo")

    def _on_undo(self):
        if not self._project:
            return
        desc = self._undo_stack.undo(self._project)
        if desc:
            self.iface.messageBar().pushSuccess("Conductor", f"Undid: {desc}")
        self._update_undo_buttons()

    def _on_redo(self):
        if not self._project:
            return
        desc = self._undo_stack.redo(self._project)
        if desc:
            self.iface.messageBar().pushSuccess("Conductor", f"Redid: {desc}")
        self._update_undo_buttons()

    def keyPressEvent(self, event):
        """Intercept Ctrl+Z (undo) and Ctrl+Shift+Z (redo)."""
        from qgis.PyQt.QtCore import Qt
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_Z:
                if event.modifiers() & Qt.ShiftModifier:
                    self._on_redo()
                else:
                    self._on_undo()
                event.accept()
                return
        super().keyPressEvent(event)

    def _setup_shortcuts(self):
        """Set up application-level shortcuts for undo/redo.
        QShortcut on the main window fires regardless of which widget has focus,
        unlike keyPressEvent on the dock which QGIS intercepts first."""
        from qgis.PyQt.QtWidgets import QShortcut
        from qgis.PyQt.QtGui import QKeySequence
        from qgis.PyQt.QtCore import Qt

        undo_sc = QShortcut(QKeySequence("Ctrl+Z"), self.iface.mainWindow())
        undo_sc.setContext(Qt.ApplicationShortcut)
        undo_sc.activated.connect(self._on_undo)
        self._shortcut_undo = undo_sc  # keep reference

        redo_sc = QShortcut(QKeySequence("Ctrl+Shift+Z"), self.iface.mainWindow())
        redo_sc.setContext(Qt.ApplicationShortcut)
        redo_sc.activated.connect(self._on_redo)
        self._shortcut_redo = redo_sc  # keep reference

    def _on_new_project(self):
        from .new_project_dialog import NewProjectDialog
        from .project_manager import ConductorProject

        dlg = NewProjectDialog(self)
        if dlg.exec_() == NewProjectDialog.Accepted:
            project = ConductorProject(
                gpkg_path    = dlg.result_gpkg,
                project_name = dlg.result_project_name,
                country_code = dlg.result_country_code,
                build_code   = dlg.result_build_code,
                designer     = dlg.result_designer,
                project_mgr  = dlg.result_project_mgr,
            )
            try:
                project.load_into_qgis()
                self.set_project(project)
                QMessageBox.information(
                    self, "Project Created",
                    f"✓  {project.project_name} created successfully.\n\n"
                    f"GeoPackage: {project.gpkg_path}\n\n"
                    f"14 layers have been added to the QGIS layer panel under "
                    f"'Conductor — {project.project_name}'."
                )
            except Exception as e:
                QMessageBox.critical(self, "Error Loading Project", str(e))

    def _on_open_project(self):
        from .project_manager import load_existing_project

        path, _ = QFileDialog.getOpenFileName(
            self, "Open Conductor Project", "", "GeoPackage (*.gpkg)"
        )
        if not path:
            return
        try:
            project = load_existing_project(path)
            project.load_into_qgis()
            self.set_project(project)
        except Exception as e:
            QMessageBox.critical(self, "Error Opening Project", str(e))

    def _run_map_tool(self, handler, module, cls_name, signal, on_success, info):
        """Generic activator for click-on-map tools: guard that a project is
        open, highlight the tool button, lazily import and start the map tool,
        connect its success signal, then show the usage prompt. Replaces ~19
        near-identical handler bodies with one parameterised path."""
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        try:
            self._activate_tool(handler)
            # Show active tool bar with the info hint
            self._show_active_tool(
                cls_name.replace("MapTool", "").replace("Digitise", "Digitise ").strip(),
                info
            )
            import importlib
            mod = importlib.import_module(".tools." + module, __package__)
            tool = getattr(mod, cls_name)(self.iface.mapCanvas(), self._project)
            getattr(tool, signal).connect(on_success)
            # CRITICAL: keep a strong Python reference to the map tool, otherwise
            # PyQt/SIP may garbage-collect the wrapper once this method returns,
            # leaving a dead tool that shows no cursor and ignores clicks.
            self._active_map_tool = tool
            self.iface.mapCanvas().setMapTool(tool)
            self.iface.mapCanvas().setFocus()
            self._enable_conductor_snapping()
            self.iface.messageBar().pushInfo("Conductor", info)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            QMessageBox.critical(
                self, "Conductor — Tool activation failed",
                f"Could not start the tool '{cls_name}'.\n\n{e}\n\n{tb}"
            )

    def _on_place_pop(self):
        self._run_map_tool(
            self._on_place_pop, 'place_pop', 'PlacePOPMapTool', 'placed',
            lambda pid: [self.iface.messageBar().pushSuccess( "Conductor", f"Cabinet {pid} placed successfully." ), self._refresh_tool_states()],
            'Click on the map to place a Cabinet / POP. Press Esc to cancel.')

    def _on_edit_pop(self):
        self._run_map_tool(
            self._on_edit_pop, 'place_pop', 'EditPOPMapTool', 'edited',
            lambda pid: self.iface.messageBar().pushSuccess( "Conductor", f"Cabinet {pid} updated successfully." ),
            'Click on an existing cabinet to edit it. Press Esc to cancel.')

    def _on_delete_asset(self):
        self._run_map_tool(
            self._on_delete_asset, 'select_delete', 'DeleteAssetMapTool', 'deleted',
            lambda ln, aid: self.iface.messageBar().pushSuccess( "Conductor", f"{aid} deleted from {ln}." ),
            'Click any asset to delete it. Press Esc to cancel.')

    def _on_move_asset(self):
        self._run_map_tool(
            self._on_move_asset, 'select_delete', 'MoveAssetMapTool', 'moved',
            lambda ln, aid: self.iface.messageBar().pushSuccess( "Conductor", f"{aid} moved successfully." ),
            'Click an asset to select it, then click the new location. Esc to cancel.')

    def _on_draw_build_area(self):
        self._run_map_tool(
            self._on_draw_build_area, 'build_area', 'DrawBuildAreaMapTool', 'drawn',
            lambda aid: [self.iface.messageBar().pushSuccess( "Conductor", f"Build Area {aid} saved." ), self._refresh_tool_states()],
            'Left-click to add corners. Right-click to finish the polygon. Esc to cancel.')

    def _on_digitise_duct(self):
        self._run_map_tool(
            self._on_digitise_duct, 'digitise_duct', 'DigitiseDuctMapTool', 'placed',
            lambda did: self.iface.messageBar().pushSuccess( "Conductor", f"Duct {did} saved." ),
            'Left-click to add vertices. Snaps to chambers/poles/cabinet. Right-click to finish. Ctrl+Z to undo last point. Esc to cancel.')

    def _on_edit_asset(self):
        self._run_map_tool(
            self._on_edit_asset, 'edit_assets', 'EditAssetMapTool', 'edited',
            lambda ln, aid: self.iface.messageBar().pushSuccess( "Conductor", f"{aid} updated." ),
            'Click any asset to edit it. Esc to cancel.')

    def _on_digitise_bundle(self):
        self._run_map_tool(
            self._on_digitise_bundle, 'digitise_bundle', 'DigitiseBundleMapTool', 'placed',
            lambda bid: self.iface.messageBar().pushSuccess( "Conductor", f"Bundle {bid} saved." ),
            'First click: snap to a secondary splitter joint. Second click: snap to premises/ONT. RMB to save. Esc to cancel.')

    def _on_place_joint(self):
        self._run_map_tool(
            self._on_place_joint, 'place_joint', 'PlaceJointMapTool', 'placed',
            lambda jid: self.iface.messageBar().pushSuccess( "Conductor", f"Joint {jid} placed." ),
            'Click on or near a chamber to place a joint inside it. Esc to cancel.')

    def _on_digitise_fibre(self):
        self._run_map_tool(
            self._on_digitise_fibre, 'digitise_fibre', 'DigitiseFibreMapTool', 'placed',
            lambda cid: self.iface.messageBar().pushSuccess( "Conductor", f"Fibre cable {cid} saved." ),
            'Left-click to add vertices — snaps to joints and cabinet only. Right-click to finish. Ctrl+Z to undo. Esc to cancel.')

    def _on_digitise_drop(self):
        self._run_map_tool(
            self._on_digitise_drop, 'digitise_drop', 'DigitiseDropMapTool', 'placed',
            lambda did: self.iface.messageBar().pushSuccess( "Conductor", f"Drop cable {did} saved." ),
            'First click: snap to a joint (secondary splitter). Last click: snap to a premises point. Esc to cancel.')

    def _on_place_chamber(self):
        self._run_map_tool(
            self._on_place_chamber, 'place_chamber', 'PlaceChamberMapTool', 'placed',
            lambda cid: self.iface.messageBar().pushSuccess( "Conductor", f"Chamber {cid} placed." ),
            'Click on the map to place a Chamber. Press Esc to cancel.')

    def _on_place_pole(self):
        self._run_map_tool(
            self._on_place_pole, 'place_pole', 'PlacePoleMapTool', 'placed',
            lambda pid: self.iface.messageBar().pushSuccess( "Conductor", f"Pole {pid} placed." ),
            'Click on the map to place a Pole. Press Esc to cancel.')

    def _on_place_pia_chamber(self):
        self._run_map_tool(
            self._on_place_pia_chamber, 'place_pia_chamber', 'PlacePIAChamberMapTool', 'placed',
            lambda cid: self.iface.messageBar().pushSuccess( "Conductor", f"PIA UG Chamber {cid} placed." ),
            'Click on the map to place a PIA UG Chamber. Press Esc to cancel.')

    def _on_digitise_aerial_span(self):
        self._run_map_tool(
            self._on_digitise_aerial_span, 'digitise_aerial_span', 'DigitiseAerialSpanMapTool', 'placed',
            lambda sid: self.iface.messageBar().pushSuccess( "Conductor", f"Aerial Span {sid} saved." ),
            'Click a start pole, click an end pole, then right-click to save. Esc to cancel.')

    def _on_digitise_pia_ug_duct(self):
        self._run_map_tool(
            self._on_digitise_pia_ug_duct, 'digitise_pia_ug_duct', 'DigitisePIAUGDuctMapTool', 'placed',
            lambda did: self.iface.messageBar().pushSuccess( "Conductor", f"PIA UG Duct {did} saved." ),
            'Click vertices to draw PIA UG duct. Snaps to PIA chambers and poles. Right-click to finish. Ctrl+Z to undo. Esc to cancel.')

    def _on_place_cbt(self):
        self._run_map_tool(
            self._on_place_cbt, 'place_cbt', 'PlaceCBTMapTool', 'placed',
            lambda cid: self.iface.messageBar().pushSuccess("Conductor", f"CBT {cid} placed."),
            'Click on a pole to place a CBT. Press Esc to cancel.')

    def _on_digitise_cbt_tail(self):
        self._run_map_tool(
            self._on_digitise_cbt_tail, 'digitise_cbt_tail', 'DigitiseCBTTailMapTool', 'placed',
            lambda tid: self.iface.messageBar().pushSuccess("Conductor", f"CBT Tail {tid} saved."),
            'Click a CBT to start the tail. Trace back to the UG joint. Right-click to finish. Esc to cancel.')

    def _on_digitise_aerial_drop(self):
        self._run_map_tool(
            self._on_digitise_aerial_drop, 'digitise_aerial_drop', 'DigitiseAerialDropMapTool', 'placed',
            lambda did: self.iface.messageBar().pushSuccess( "Conductor", f"Aerial Drop {did} saved." ),
            'Click a pole or CBT, click the premises, then right-click to save. Esc to cancel.')

    def _on_digitise_pia_ug_drop(self):
        self._run_map_tool(
            self._on_digitise_pia_ug_drop, 'digitise_pia_ug_drop', 'DigitisePIAUGDropMapTool', 'placed',
            lambda did: self.iface.messageBar().pushSuccess( "Conductor", f"PIA UG Drop {did} saved." ),
            'Click a PIA UG Chamber, click the premises, then right-click to save. Esc to cancel.')






    def _on_import_premises(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        from .tools.import_premises import ImportPremisesDialog
        dlg = ImportPremisesDialog(self._project, parent=self)
        dlg.exec_()
        self._refresh_tool_states()


    def _on_postcode_zoom(self):
        pc = self._pc_input.text().strip()
        if not pc:
            return
        from .tools.postcode_zoom import zoom_to_postcode
        zoom_to_postcode(self.iface, pc)
        self._pc_input.clear()







    def _on_sld(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        from .tools.sld import open_sld_dialog
        self._sld_dlg = open_sld_dialog(self.iface, self, project=self._project)

    def _on_splice_plan(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        from .tools.splice_plan import open_splice_plan_dialog
        self._splice_dlg = open_splice_plan_dialog(self.iface, self, project=self._project)

    def _on_assign_fibres(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        from .tools.fibre_assign import open_fibre_assign_dialog
        self._assign_dlg = open_fibre_assign_dialog(self.iface, self, project=self._project)
        if self._assign_dlg:
            self._assign_dlg.finished.connect(lambda _: self._on_refresh_summary())

    def _on_fibre_trace(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        self._activate_tool(self._on_fibre_trace)
        from .tools.fibre_trace import activate_fibre_trace
        self._fibre_trace_tool, self._fibre_trace_panel = activate_fibre_trace(
            self.iface, self._project, parent=self
        )

    def _on_fibre_count(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        from .tools.fibre_count import open_fibre_count_dialog
        self._fibre_count_dlg = open_fibre_count_dialog(self.iface, parent=self, project=self._project)

    def _on_route_splice_export(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        self._activate_tool(self._on_route_splice_export)
        from .tools.route_splice_export import activate_route_splice_export
        self._route_splice_tool, self._route_splice_panel = activate_route_splice_export(
            self.iface, self._project, parent=self
        )

    def _on_bom(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        from .tools.bom import open_bom_dialog
        self._bom_dlg = open_bom_dialog(self.iface, self, project=self._project)

    def _on_cabinet_cost_calculator(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        from .tools.cabinet_cost import open_cabinet_cost_dialog
        self._cabinet_cost_dlg = open_cabinet_cost_dialog(self.iface, self, project=self._project)

    def _on_optical_budget(self):
        """Open the optical power budget settings used by the Fibre Route
        Validator's loss/margin calculation. Settings are global (QgsSettings),
        so no project needs to be open to view or edit them."""
        from .tools.optical_budget import edit_optical_dialog
        edit_optical_dialog(self)

    def _on_validate_routes(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        from .tools.validate_routes import open_validate_routes_dialog
        self._validate_dlg = open_validate_routes_dialog(self.iface, self, project=self._project)
        if self._validate_dlg:
            self._validate_dlg.finished.connect(lambda _: self._on_refresh_summary())

    def _on_digitise_road_crossing(self):
        self._run_map_tool(
            self._on_digitise_road_crossing, 'digitise_road_crossing', 'DigitiseRoadCrossingMapTool', 'placed',
            lambda did: self.iface.messageBar().pushSuccess( "Conductor", f"Road Crossing {did} saved." ),
            'Left-click to add vertices across the road. Snaps to chambers/poles/cabinet. Right-click to finish. Ctrl+Z to undo last point. Esc to cancel.')

    def _on_digitise_stream_crossing(self):
        self._run_map_tool(
            self._on_digitise_stream_crossing, 'digitise_stream_crossing', 'DigitiseStreamCrossingMapTool', 'placed',
            lambda did: self.iface.messageBar().pushSuccess( "Conductor", f"Stream Crossing {did} saved." ),
            'Left-click to add vertices across the watercourse. Snaps to chambers/poles/cabinet. Right-click to finish. Ctrl+Z to undo last point. Esc to cancel.')

    # ── CALLBACKS — PIA TAB ────────────────────────────────────────────────────








    # ── CLOSE ─────────────────────────────────────────────────────────────────

    def _track_dialog(self, dlg):
        """Register a tool dialog so it closes when the panel unloads."""
        if dlg is not None:
            self._open_dialogs.append(dlg)
            try:
                dlg.finished.connect(lambda: self._open_dialogs.remove(dlg) if dlg in self._open_dialogs else None)
            except Exception:
                pass
        return dlg

    def _close_all_dialogs(self):
        for dlg in list(self._open_dialogs):
            try:
                dlg.close()
            except Exception:
                pass
        self._open_dialogs.clear()

    def closeEvent(self, event):
        self._close_all_dialogs()
        if hasattr(self, '_fibre_trace_tool') and self._fibre_trace_tool:
            try:
                self._fibre_trace_tool._clear_bands()
                self.iface.mapCanvas().refresh()
            except Exception:
                pass
        self.closingPlugin.emit()
        super().closeEvent(event)
