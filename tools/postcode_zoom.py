# -*- coding: utf-8 -*-
"""
Conductor — Postcode Zoom & Lookup
Uses postcodes.io (free, no API key) to:
  - Zoom the map to a UK postcode
  - Auto-fill town/address fields on forms
  - Validate postcodes before saving
Network calls run in a QThread so the GUI never blocks.
"""

import re
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox
from qgis.core import (
    QgsProject, QgsPointXY, QgsRectangle,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, Qgis,
)
from qgis.gui import QgsVertexMarker


API_BASE = "https://api.postcodes.io/postcodes"
TIMEOUT  = 6  # seconds


# ── Worker thread ─────────────────────────────────────────────────────────────

class _PostcodeWorker(QThread):
    """Fetches postcode data in a background thread."""
    result  = pyqtSignal(object)   # emits dict or None

    def __init__(self, postcode, parent=None):
        super().__init__(parent)
        self._postcode = re.sub(r'\s+', '', postcode).upper()

    def run(self):
        try:
            import requests
            r = requests.get(f"{API_BASE}/{self._postcode}", timeout=TIMEOUT)
            data = r.json()
            if data.get('status') == 200:
                self.result.emit(data['result'])
                return
        except Exception:
            pass
        self.result.emit(None)


# ── Synchronous helper (used by forms that need blocking lookup) ───────────────

def _fetch_sync(postcode):
    """Blocking fetch — only call from a non-GUI thread or where blocking is acceptable."""
    try:
        import requests
        pc = re.sub(r'\s+', '', postcode).upper()
        r  = requests.get(f"{API_BASE}/{pc}", timeout=TIMEOUT)
        data = r.json()
        if data.get('status') == 200:
            return data['result']
    except Exception:
        pass
    return None


def _parse_result(result):
    return {
        "easting":        result.get("eastings"),
        "northing":       result.get("northings"),
        "latitude":       result.get("latitude"),
        "longitude":      result.get("longitude"),
        "town":           result.get("parish") or result.get("admin_ward") or "",
        "admin_district": result.get("admin_district") or "",
        "region":         result.get("region") or "",
        "postcode":       result.get("postcode") or "",
    }


# ── Public API ────────────────────────────────────────────────────────────────

def lookup_postcode(postcode):
    """
    Synchronous lookup — returns a result dict or None.
    Used by forms (editingFinished signal) which are already off the hot path.
    Short timeout (6s) prevents indefinite hangs.
    """
    result = _fetch_sync(postcode)
    return _parse_result(result) if result else None


def validate_postcode(postcode):
    """Returns True if postcode exists in postcodes.io."""
    return _fetch_sync(postcode) is not None


def zoom_to_postcode(iface, postcode=None):
    """
    Zoom the QGIS canvas to a UK postcode.
    Network call runs in a QThread — GUI stays responsive.
    If postcode is None, prompts the user for input.
    """
    if not postcode:
        postcode, ok = QInputDialog.getText(
            iface.mainWindow(),
            "Zoom to Postcode",
            "Enter UK Postcode:"
        )
        if not ok or not postcode.strip():
            return
        postcode = postcode.strip()

    worker = _PostcodeWorker(postcode)

    def on_result(result):
        worker.deleteLater()
        if not result:
            iface.messageBar().pushMessage(
                "Conductor", f"Postcode '{postcode}' not found.",
                level=Qgis.Warning, duration=4
            )
            return

        crs_src  = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_dest = QgsProject.instance().crs()
        xform    = QgsCoordinateTransform(crs_src, crs_dest, QgsProject.instance())
        point    = xform.transform(QgsPointXY(result['longitude'], result['latitude']))

        canvas = iface.mapCanvas()
        scale  = 250
        rect   = QgsRectangle(
            point.x()-scale, point.y()-scale,
            point.x()+scale, point.y()+scale,
        )
        canvas.setExtent(rect)

        marker = QgsVertexMarker(canvas)
        marker.setCenter(point)
        marker.setColor(QColor(200, 90, 0))
        marker.setPenWidth(3)
        marker.setIconSize(16)
        marker.setIconType(QgsVertexMarker.ICON_X)
        canvas.refresh()

        district = result.get('admin_district', '')
        parish   = result.get('parish', '')
        loc      = f"{parish}, {district}" if parish else district
        iface.messageBar().pushSuccess(
            "Conductor",
            f"Zoomed to {result['postcode']}  —  {loc}",
        )

    worker.result.connect(on_result)
    worker.start()
