# -*- coding: utf-8 -*-
"""
Conductor — Digitise Aerial Span (PIA)
Thin wrapper around DigitiseFibreMapTool.
Automatically sets cable_type = AERIAL.
"""

from .digitise_fibre import DigitiseFibreMapTool, DigitiseFibreDialog
from qgis.PyQt.QtGui import QColor


class DigitiseAerialSpanMapTool(DigitiseFibreMapTool):

    def __init__(self, canvas, project):
        super().__init__(canvas, project)
        self._rubber.setColor(QColor(0, 170, 255, 200))

    def _make_dialog(self, cable_id, from_node, from_type, to_node, to_type, length_m, pop_id, duct_id):
        return DigitiseFibreDialog(
            cable_id=cable_id, area_id=self._project.area_id,
            pop_id=pop_id, from_node=from_node, from_type=from_type,
            to_node=to_node, to_type=to_type, length_m=length_m,
            duct_id=None, default_cable_type="AERIAL",
        )
