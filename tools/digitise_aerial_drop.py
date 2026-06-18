# -*- coding: utf-8 -*-
"""
Conductor — Digitise Aerial Drop (PIA)
Thin wrapper around DigitiseDropMapTool.
drop_type = PIA_AERIAL_DROP is auto-set when start node is a CBT joint.
No special logic needed — the existing tool handles everything.
"""

from .digitise_drop import DigitiseDropMapTool
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsWkbTypes


class DigitiseAerialDropMapTool(DigitiseDropMapTool):
    """
    Identical to DigitiseDropMapTool.
    Uses a light blue rubber band to distinguish aerial drops visually.
    drop_type is auto-detected in _save() based on whether start node is a CBT.
    """

    def __init__(self, canvas, project):
        super().__init__(canvas, project)
        # Light blue rubber band
        self._rubber.setColor(QColor(102, 204, 255, 220))
