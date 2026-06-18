# -*- coding: utf-8 -*-
"""
Conductor — Digitise Stream Crossing (Crossings)
Thin wrapper around DigitiseDuctMapTool.
Locks surface_type = WATERCOURSE, since a stream crossing is by definition
a duct segment that crosses under a watercourse.
"""

from .digitise_duct import DigitiseDuctMapTool
from qgis.PyQt.QtGui import QColor


class DigitiseStreamCrossingMapTool(DigitiseDuctMapTool):

    def __init__(self, canvas, project):
        super().__init__(canvas, project)
        # Distinct colour on the canvas while digitising a crossing
        self._rubber.setColor(QColor(0, 130, 200, 200))

    def _make_dialog(self, duct_id, duct_seq, compass_leg, area_id, pop_id,
                      from_node, from_node_type, to_node, to_node_type, length_m):
        dlg = super()._make_dialog(
            duct_id, duct_seq, compass_leg, area_id, pop_id,
            from_node, from_node_type, to_node, to_node_type, length_m,
        )
        dlg.setWindowTitle("Digitise Stream Crossing")

        idx = dlg.surface_type.findText("WATERCOURSE")
        if idx >= 0:
            dlg.surface_type.setCurrentIndex(idx)
        dlg.surface_type.setEnabled(False)

        dlg.permit_ref.setPlaceholderText("Land drainage / watercourse consent reference (if applicable)")

        return dlg
