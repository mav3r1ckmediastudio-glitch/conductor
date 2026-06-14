# -*- coding: utf-8 -*-
"""
Conductor — Dock Panel
Main UI surface. Manages project state and enables/disables tool buttons.
"""

import os
from qgis.PyQt.QtCore import Qt, pyqtSignal, QSize
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QSizePolicy, QSpacerItem,
    QMessageBox, QFileDialog, QTabWidget, QScrollArea,
)
from qgis.core import QgsProject, QgsSnappingConfig, QgsTolerance
from .conductor_utils import NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, SKY, PURPLE
from .help_system import HelpContentStore, wrap_with_help

SKY    = "#00AAFF"   # PIA aerial colour
PURPLE = "#7B2D8B"   # PIA underground colour


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
        container.setStyleSheet(f"#ConductorContainer {{ background-color: {LIGHT}; }}")

        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        # Postcode search bar
        pc_bar = QWidget()
        pc_bar.setStyleSheet(f"background:{NAVY}; padding:0px;")
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

        root.addWidget(self._tabs)
        self.setWidget(container)

    def _build_design_tab(self):
        """Build the existing Design tab content."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet(f"background:{LIGHT}; border:none;")

        content = QWidget()
        content.setStyleSheet(f"background-color: {LIGHT};")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(12, 16, 12, 16)
        cl.setSpacing(8)

        # Project status label
        self._status_label = QLabel("No project open")
        self._status_label.setStyleSheet(f"color:{MID}; font-size:11px; padding-bottom:4px;")
        cl.addWidget(self._status_label)

        # PROJECT
        cl.addWidget(self._section_label("PROJECT"))
        cl.addWidget(self._primary_button("＋  New Project", self._on_new_project, icon="new_project.svg"))
        cl.addWidget(self._secondary_button("Open Project", self._on_open_project, icon="open_project.svg"))
        cl.addWidget(self._divider())

        # DESIGN
        cl.addWidget(self._section_label("DESIGN"))
        for label, slot, icon in [
            ("Build Areas",                    self._on_draw_build_area,   "build_areas.svg"),
            ("Import Premises (AddressBase)",   self._on_import_premises,  "import_premises_addressbase.svg"),
            ("Place Cabinet / POP",             self._on_place_pop,        "place_cabinet_pop.svg"),
            ("Edit Cabinet / POP",              self._on_edit_pop,         "edit_cabinet_pop.svg"),
            ("Digitise Duct",                   self._on_digitise_duct,    "digitise_duct.svg"),
            ("Digitise Cable",                  self._on_digitise_fibre,   "digitise_cable.svg"),
            ("Digitise Drop Duct",              self._on_digitise_drop,    "digitise_drop_duct.svg"),
            ("Digitise Bundle",                 self._on_digitise_bundle,  "digitise_bundle.svg"),
            ("Place Chamber",                   self._on_place_chamber,    "place_chamber.svg"),
            ("Place Joint",                     self._on_place_joint,      "place_joint.svg"),
        ]:
            cl.addWidget(self._tool_button(label, slot, icon=icon))
        cl.addWidget(self._divider())

        # CROSSINGS (not PIA-specific — available in Design tab)
        cl.addWidget(self._section_label("CROSSINGS"))
        for label, slot, icon in [
            ("Digitise Road Crossing",    self._on_digitise_road_crossing,    "digitise_road_crossing.svg"),
            ("Digitise Stream Crossing",  self._on_digitise_stream_crossing,  "digitise_stream_crossing.svg"),
        ]:
            cl.addWidget(self._tool_button(label, slot, icon=icon))
        cl.addWidget(self._divider())

        # FIBRE
        cl.addWidget(self._section_label("FIBRE"))
        for label, slot, icon in [
            ("Assign Fibre Roles",      self._on_assign_fibres,        "assign_fibre_roles.svg"),
            ("Fibre Trace",             self._on_fibre_trace,          "fibre_trace.svg"),
            ("Fibre Count Calculator",  self._on_fibre_count,          "fibre_count_calculator.svg"),
            ("Route Splice Export",     self._on_route_splice_export,  "route_splice_export.svg"),
        ]:
            cl.addWidget(self._tool_button(label, slot, icon=icon))
        cl.addWidget(self._divider())

        # BUILD
        cl.addWidget(self._section_label("BUILD"))
        for label, slot, icon in [
            ("Add Build Task",       self._placeholder,    "add_build_task.svg"),
            ("Generate Job Pack",    self._placeholder,    "generate_job_pack.svg"),
            ("Splice Plan Export",   self._on_splice_plan, "splice_plan_export.svg"),
            ("Single Line Diagram",  self._on_sld,         "single_line_diagram.svg"),
        ]:
            cl.addWidget(self._tool_button(label, slot, icon=icon))
        cl.addWidget(self._divider())

        # TOOLS
        cl.addWidget(self._section_label("TOOLS"))
        for label, slot, icon in [
            ("Delete Asset",             self._on_delete_asset,    "delete_asset.svg"),
            ("Move Asset",               self._on_move_asset,      "move_asset.svg"),
            ("Validate Fibre Routes",    self._on_validate_routes, "validate_fibre_routes.svg"),
            ("Bill of Materials",        self._on_bom,             "bill_of_materials.svg"),
            ("BDUK Export",              self._placeholder,        "bduk_export.svg"),
            ("Cabinet Cost Calculator",  self._placeholder,        "cabinet_cost_calculator.svg"),
        ]:
            cl.addWidget(self._tool_button(label, slot, icon=icon))

        cl.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        footer = QLabel("Conductor v0.1.0  ·  Mav3r1ck Media Studio")
        footer.setStyleSheet(f"color:{MID}; font-size:10px; padding:8px 0px;")
        footer.setAlignment(Qt.AlignCenter)
        cl.addWidget(footer)

        scroll_area.setWidget(content)
        return scroll_area

    def _build_pia_tab(self):
        """Build the PIA tab content."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet(f"background:{LIGHT}; border:none;")

        content = QWidget()
        content.setStyleSheet(f"background-color: {LIGHT};")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(12, 16, 12, 16)
        cl.setSpacing(8)

        # Info label
        info = QLabel("Physical Infrastructure Access tools for pole-mounted and Openreach subduct routes.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{MID}; font-size:11px; padding-bottom:6px;")
        cl.addWidget(info)

        # CIVIL
        cl.addWidget(self._section_label("CIVIL"))
        for label, slot, icon in [
            ("Place Pole",              self._on_place_pole,           "place_pole.svg"),
            ("Place PIA UG Chamber",    self._on_place_pia_chamber,     "place_pia_ug_chamber.svg"),
            ("Digitise Aerial Span",    self._on_digitise_aerial_span,  "digitise_aerial_span.svg"),
            ("Digitise PIA UG Duct",    self._on_digitise_pia_ug_duct,  "digitise_pia_ug_duct.svg"),
        ]:
            cl.addWidget(self._tool_button(label, slot, icon=icon))
        cl.addWidget(self._divider())

        # OPTICAL
        cl.addWidget(self._section_label("OPTICAL"))
        for label, slot, icon in [
            ("Place CBT",               self._on_place_cbt,            "place_cbt.svg"),
            ("Digitise Aerial Drop",    self._on_digitise_aerial_drop, "digitise_aerial_drop.svg"),
            ("Digitise PIA UG Drop",    self._on_digitise_pia_ug_drop, "digitise_pia_ug_drop.svg"),
        ]:
            cl.addWidget(self._tool_button(label, slot, icon=icon))

        cl.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        pia_footer = QLabel("PIA tools  ·  Conductor v0.1.0")
        pia_footer.setStyleSheet(f"color:{MID}; font-size:10px; padding:8px 0px;")
        pia_footer.setAlignment(Qt.AlignCenter)
        cl.addWidget(pia_footer)

        scroll_area.setWidget(content)
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
        title.setStyleSheet(f"color:{WHITE}; font-size:16px; font-weight:bold; letter-spacing:2px; padding-left:8px;")
        layout.addWidget(title)
        layout.addStretch()

        sub = QLabel("FTTP Design")
        sub.setStyleSheet(f"color:{TEAL}; font-size:11px;")
        layout.addWidget(sub)
        return header

    # ── WIDGET FACTORIES ───────────────────────────────────────────────────────

    def _section_label(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color:{TEAL}; font-size:10px; font-weight:bold; letter-spacing:1px; padding:4px 0px 2px 0px;")
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
            QPushButton {{ background:{NAVY}; color:{WHITE}; border:none; border-radius:4px;
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
            QPushButton {{ background:{WHITE}; color:{NAVY}; border:1px solid {MID};
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
            QPushButton {{ background:{WHITE}; color:{NAVY}; border:1px solid {MID};
                           border-radius:4px; padding:4px 12px; font-size:12px; text-align:left; min-height:28px; }}
            QPushButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}
            QPushButton:pressed {{ background:{LIGHT}; }}
            QPushButton:disabled {{ color:{MID}; border-color:{MID}; background:{LIGHT}; }}
            QPushButton[conductor_active=true] {{ background:{ORANGE}; color:{WHITE}; border-color:{ORANGE}; font-weight:bold; }}
        """)
        ic = self._icon(icon)
        if ic:
            btn.setIcon(ic)
            btn.setIconSize(QSize(28, 28))
        btn.setEnabled(False)
        btn.clicked.connect(callback)
        self._tool_buttons.append(btn)
        if not hasattr(self, '_btn_map'):
            self._btn_map = {}
        self._btn_map[callback] = btn
        if icon:
            tool_id = os.path.splitext(icon)[0]
            return wrap_with_help(btn, tool_id, self.help_store)
        return btn

    def _activate_tool(self, callback):
        """Highlight the button for this callback and enable snapping. Call at the start of each tool handler."""
        btn = getattr(self, '_btn_map', {}).get(callback)
        self._set_active_button(btn)
        self._enable_conductor_snapping()

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
        line.setStyleSheet(f"color:{MID}; margin:2px 0px;")
        return line

    # ── PROJECT STATE ──────────────────────────────────────────────────────────

    def set_project(self, conductor_project):
        """Called after a project is created or opened."""
        self._project = conductor_project
        name = conductor_project.project_name
        code = conductor_project.area_id
        self._status_label.setText(f"▸  {name}  ({code})")
        self._status_label.setStyleSheet(f"color:{TEAL}; font-size:11px; font-weight:bold; padding-bottom:4px;")
        for btn in self._tool_buttons:
            btn.setEnabled(True)
        try:
            self.iface.mapCanvas().mapToolSet.connect(self._on_map_tool_set)
        except Exception:
            pass

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
            "DigitiseAerialSpanMapTool", "DigitisePIAUGDuctMapTool",
            "DigitiseAerialDropMapTool", "DigitisePIAUGDropMapTool",
            "DigitiseCrossingMapTool",
        )
        if new_tool is None or type(new_tool).__name__ not in conductor_tool_types:
            self._clear_active_button()

    # ── CALLBACKS — DESIGN TAB ─────────────────────────────────────────────────

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
        self._activate_tool(handler)
        import importlib
        mod = importlib.import_module(".tools." + module, __package__)
        tool = getattr(mod, cls_name)(self.iface.mapCanvas(), self._project)
        getattr(tool, signal).connect(on_success)
        self.iface.mapCanvas().setMapTool(tool)
        self.iface.messageBar().pushInfo("Conductor", info)

    def _on_place_pop(self):
        self._run_map_tool(
            self._on_place_pop, 'place_pop', 'PlacePOPMapTool', 'placed',
            lambda pid: self.iface.messageBar().pushSuccess( "Conductor", f"Cabinet {pid} placed successfully." ),
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
            lambda aid: self.iface.messageBar().pushSuccess( "Conductor", f"Build Area {aid} saved." ),
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
            lambda cid: self.iface.messageBar().pushSuccess( "Conductor", f"CBT {cid} placed." ),
            'Click on a pole to place a CBT. Press Esc to cancel.')

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

    def _on_validate_routes(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        from .tools.validate_routes import open_validate_routes_dialog
        self._validate_dlg = open_validate_routes_dialog(self.iface, self, project=self._project)

    def _on_digitise_road_crossing(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        self._activate_tool(self._on_digitise_road_crossing)
        self.iface.messageBar().pushInfo(
            "Conductor", "Road Crossing tool — coming soon."
        )

    def _on_digitise_stream_crossing(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        self._activate_tool(self._on_digitise_stream_crossing)
        self.iface.messageBar().pushInfo(
            "Conductor", "Stream Crossing tool — coming soon."
        )

    # ── CALLBACKS — PIA TAB ────────────────────────────────────────────────────








    def _placeholder(self):
        QMessageBox.information(self, "Coming Soon",
            "This tool is not yet implemented.\nIt will be added in a future update.")

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
