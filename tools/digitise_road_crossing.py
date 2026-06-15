# -*- coding: utf-8 -*-
"""
Conductor — Digitise Road Crossing (Crossings)
Thin wrapper around DigitiseDuctMapTool.
Locks surface_type = ROAD, since a road crossing is by definition
a duct segment that crosses under a road.
"""

from .digitise_duct import DigitiseDuctMapTool
from qgis.PyQt.QtGui import QColor


class DigitiseRoadCrossingMapTool(DigitiseDuctMapTool):

    def __init__(self, canvas, project):
        super().__init__(canvas, project)
        # Distinct colour on the canvas while digitising a crossing
        self._rubber.setColor(QColor(230, 90, 0, 200))

    def _make_dialog(self, duct_id, duct_seq, compass_leg, area_id, pop_id,
                      from_node, from_node_type, to_node, to_node_type, length_m):
        dlg = super()._make_dialog(
            duct_id, duct_seq, compass_leg, area_id, pop_id,
            from_node, from_node_type, to_node, to_node_type, length_m,
        )
        dlg.setWindowTitle("Digitise Road Crossing")

        idx = dlg.surface_type.findText("ROAD")
        if idx >= 0:
            dlg.surface_type.setCurrentIndex(idx)
        dlg.surface_type.setEnabled(False)

        dlg.permit_ref.setPlaceholderText("S50 / road opening permit reference (if applicable)")

        return dlg
