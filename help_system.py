# -*- coding: utf-8 -*-
"""
help_system.py

Generic, data-driven help system for Conductor.

Usage:
    from .help_system import HelpContentStore, attach_help_button

    # Once at plugin init / dock widget init:
    self.help_store = HelpContentStore(self.plugin_dir)

    # When building each tool's row:
    row = attach_help_button(button_widget, "fibre_trace", self.help_store)
    layout.addWidget(row)
"""

import json
import os

from qgis.PyQt import QtCore, QtWidgets
from .conductor_utils import NAVY, TEAL, ORANGE, LIGHT, WHITE, MID


class HelpContentStore:
    """Loads and provides access to help content entries."""

    def __init__(self, plugin_dir, filename="help_content.json"):
        self._path = os.path.join(plugin_dir, filename)
        self._content = {}
        self.reload()

    def reload(self):
        """Re-read the help content file from disk."""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._content = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            # Don't let a malformed help file break the plugin - just log
            # and fall back to empty content.
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(
                f"Conductor: failed to load help content: {e}",
                "Conductor",
                Qgis.Warning,
            )
            self._content = {}

    def get(self, tool_id):
        """Return the help entry dict for tool_id, or a placeholder dict."""
        return self._content.get(tool_id, {
            "title": tool_id,
            "status": "missing",
            "purpose": "No help content available for this tool yet.",
            "how_to": "",
            "common_mistakes": "",
            "related_tools": [],
        })

    def all_tool_ids(self):
        return list(self._content.keys())


class HelpDialog(QtWidgets.QDialog):
    """
    Generic help dialog. Pass a HelpContentStore and the tool_id to show.
    Related tools are shown as buttons that swap the dialog's content
    in-place rather than opening new dialogs.
    """

    def __init__(self, store, tool_id, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Conductor Help")
        self.setMinimumWidth(440)
        self.setStyleSheet(f"QDialog {{ background-color: {LIGHT}; }}")

        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(14, 14, 14, 14)
        self._layout.setSpacing(8)

        self.title_label = QtWidgets.QLabel()
        self.title_label.setStyleSheet(
            f"font-weight: bold; font-size: 13pt; color: {NAVY};"
        )
        self._layout.addWidget(self.title_label)

        self.body = QtWidgets.QTextBrowser()
        self.body.setOpenExternalLinks(False)
        self.body.setStyleSheet(
            f"QTextBrowser {{ background-color: {WHITE}; color: {NAVY};"
            f" border: 1px solid {MID}; border-radius: 4px; padding: 8px;"
            f" font-size: 12px; }}"
        )
        self._layout.addWidget(self.body)

        self.related_row = QtWidgets.QHBoxLayout()
        self._layout.addLayout(self.related_row)

        close_row = QtWidgets.QHBoxLayout()
        close_row.addStretch()
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setCursor(QtCore.Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background:{WHITE}; color:{NAVY}; border:1px solid {MID};"
            f" border-radius:4px; padding:6px 16px; font-size:12px; }}"
            f"QPushButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}"
            f"QPushButton:pressed {{ background:{LIGHT}; }}"
        )
        close_btn.clicked.connect(self.close)
        close_row.addWidget(close_btn)
        self._layout.addLayout(close_row)

        self.show_tool(tool_id)

    def show_tool(self, tool_id):
        entry = self.store.get(tool_id)

        title = entry.get("title", tool_id)
        if entry.get("status") == "placeholder":
            title += "  (not yet implemented)"
        self.title_label.setText(title)

        parts = []
        if entry.get("purpose"):
            parts.append(f"<b>Purpose</b><br>{entry['purpose']}")
        if entry.get("how_to"):
            how_to_html = entry["how_to"].replace("\n", "<br>")
            parts.append(f"<b>How To Use</b><br>{how_to_html}")
        if entry.get("common_mistakes"):
            parts.append(
                f"<b>Common Mistakes</b><br>{entry['common_mistakes']}"
            )
        if not parts:
            parts.append("<i>No help content available for this tool yet.</i>")

        self.body.setHtml("<br><br>".join(parts))

        # Clear and rebuild related-tool buttons
        while self.related_row.count():
            item = self.related_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        related = entry.get("related_tools", [])
        if related:
            label = QtWidgets.QLabel("Related:")
            label.setStyleSheet(f"color:{NAVY}; font-size:11px;")
            self.related_row.addWidget(label)
            for related_id in related:
                related_title = self.store.get(related_id).get("title", related_id)
                btn = QtWidgets.QPushButton(related_title)
                btn.setCursor(QtCore.Qt.PointingHandCursor)
                btn.setStyleSheet(
                    f"QPushButton {{ background:{WHITE}; color:{TEAL}; border:1px solid {TEAL};"
                    f" border-radius:4px; padding:3px 10px; font-size:11px; }}"
                    f"QPushButton:hover {{ background:{TEAL}; color:{WHITE}; }}"
                )
                btn.clicked.connect(lambda _, rid=related_id: self.show_tool(rid))
                self.related_row.addWidget(btn)
            self.related_row.addStretch()


def make_info_button(tool_id, store, parent=None):
    """
    Create a small circular (i) button that opens the HelpDialog for
    tool_id when clicked. Returns the QToolButton.
    """
    btn = QtWidgets.QToolButton(parent)
    btn.setText("i")
    btn.setToolTip("Help")
    btn.setCursor(QtCore.Qt.PointingHandCursor)
    btn.setFixedSize(20, 20)
    btn.setStyleSheet(
        f"QToolButton {{"
        f"  border: 1px solid {MID};"
        f"  border-radius: 10px;"
        f"  background-color: {WHITE};"
        f"  color: {NAVY};"
        f"  font-weight: bold;"
        f"  font-size: 10pt;"
        f"}}"
        f"QToolButton:hover {{ background-color: {TEAL}; color: {WHITE}; border-color: {TEAL}; }}"
        f"QToolButton:pressed {{ background-color: {NAVY}; color: {WHITE}; border-color: {NAVY}; }}"
    )

    def _open():
        dlg = HelpDialog(store, tool_id, parent=parent)
        dlg.exec_()

    btn.clicked.connect(_open)
    return btn


def wrap_with_help(widget, tool_id, store, parent=None):
    """
    Wrap an existing widget (typically a QPushButton) in a horizontal row
    with a help (i) button to its right. Returns the wrapping QWidget,
    ready to be added to a layout in place of the original widget.
    """
    row = QtWidgets.QWidget(parent)
    row_layout = QtWidgets.QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(4)
    row_layout.addWidget(widget, 1)
    row_layout.addWidget(make_info_button(tool_id, store, parent=row))
    return row


def attach_help_button(target_layout, tool_id, store):
    """
    Convenience: create an info button for tool_id and add it to
    target_layout (a QLayout).
    """
    btn = make_info_button(tool_id, store)
    target_layout.addWidget(btn)
    return btn
