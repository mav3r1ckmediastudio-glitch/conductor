# -*- coding: utf-8 -*-
"""
Conductor — FTTP Network Design Plugin for QGIS
Main plugin class. Handles toolbar, menu, and dock panel lifecycle.
"""

import os
from qgis.PyQt.QtCore import Qt, QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsProject

from .conductor_dockwidget import ConductorDockWidget
from .conductor_utils import plugin_version


class Conductor:
    """Main plugin class — instantiated once by QGIS on load."""

    PLUGIN_NAME = "Conductor"
    MENU_LABEL = "&Conductor"

    def __init__(self, iface):
        """
        :param iface: QgsInterface — live reference to the QGIS application interface.
        """
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)

        self.actions = []
        self.menu = self.MENU_LABEL
        self.toolbar = self.iface.addToolBar(self.PLUGIN_NAME)
        self.toolbar.setObjectName("ConductorToolbar")

        self.dockwidget = None
        self._toggle_action = None  # toolbar/menu action for the dock panel

    # ── ICON HELPER ────────────────────────────────────────────────────────────

    def _icon(self, filename):
        path = os.path.join(self.plugin_dir, "icons", filename)
        return QIcon(path)

    # ── ACTION HELPER ──────────────────────────────────────────────────────────

    def _add_action(
        self,
        icon_filename,
        text,
        callback,
        enabled=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None,
    ):
        icon = self._icon(icon_filename)
        action = QAction(icon, text, parent or self.iface.mainWindow())
        action.triggered.connect(callback)
        action.setEnabled(enabled)

        if status_tip:
            action.setStatusTip(status_tip)
        if whats_this:
            action.setWhatsThis(whats_this)
        if add_to_toolbar:
            self.toolbar.addAction(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    # ── PLUGIN LIFECYCLE ───────────────────────────────────────────────────────

    def initGui(self):
        """Called by QGIS to set up the plugin UI."""

        # Primary action — toggles the dock panel
        self._toggle_action = self._add_action(
            icon_filename="conductor.png",
            text="Open Conductor Panel",
            callback=self._toggle_dockwidget,
            status_tip="Open or close the Conductor FTTP design panel",
            whats_this="Toggle the Conductor network design panel",
        )
        self._toggle_action.setCheckable(True)

        # Separator
        self.toolbar.addSeparator()

        # About action — menu only
        self._add_action(
            icon_filename="conductor.png",
            text="About Conductor",
            callback=self._show_about,
            add_to_toolbar=False,
            status_tip="About Conductor",
        )

    def unload(self):
        """Called by QGIS when the plugin is unloaded. Clean up everything."""
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)

        del self.toolbar

        if self.dockwidget:
            self.iface.removeDockWidget(self.dockwidget)
            self.dockwidget.close()
            self.dockwidget = None

    # ── DOCK PANEL ─────────────────────────────────────────────────────────────

    def _toggle_dockwidget(self):
        """Show or hide the Conductor dock panel."""
        if self.dockwidget is None:
            self._create_dockwidget()
            return  # _create_dockwidget shows it — nothing more to do

        if self.dockwidget.isVisible():
            self.dockwidget.hide()
            self._toggle_action.setChecked(False)
        else:
            self.dockwidget.show()
            self._toggle_action.setChecked(True)

    def _create_dockwidget(self):
        """Instantiate, register, and immediately show the dock panel."""
        self.dockwidget = ConductorDockWidget(self.iface)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
        self.dockwidget.show()
        self._toggle_action.setChecked(True)

        # Keep toolbar button in sync when user closes the panel via the X
        self.dockwidget.visibilityChanged.connect(self._on_dock_visibility_changed)

    def _on_dock_visibility_changed(self, visible):
        if self._toggle_action:
            self._toggle_action.setChecked(visible)

    # ── ABOUT ──────────────────────────────────────────────────────────────────

    def _show_about(self):
        QMessageBox.information(
            self.iface.mainWindow(),
            "About Conductor",
            (
                f"<b>Conductor v{plugin_version()}</b><br>"
                "FTTP Network Design Plugin for QGIS<br><br>"
                "Full-lifecycle fibre network design, build tracking, "
                "and inventory management — stored in a portable GeoPackage.<br><br>"
                "Built for UK FTTP operators.<br>"
                "© 2026 Mav3r1ck Media Studio"
            ),
        )
