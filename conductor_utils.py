# -*- coding: utf-8 -*-
"""
conductor_utils.py  —  Conductor FTTP Network Design Plugin
Shared utilities: layer lookup, field access, constants, IEC colour tables.
Import from here rather than duplicating across tool files.
"""

import math
from qgis.core import (
    QgsProject, NULL, QgsRectangle, QgsFeatureRequest,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsDistanceArea, QgsGeometry,
)

# ── Project CRS ─────────────────────────────────────────────────
# Single source of truth for the working CRS. UK national grid (OSGB36).
PROJECT_CRS = "EPSG:27700"

# ── Colour constants ──────────────────────────────────────────────────────────
NAVY   = "#1A3A5C"
TEAL   = "#1D7A6E"
ORANGE = "#C85A00"
LIGHT  = "#F4F7FB"
WHITE  = "#FFFFFF"
MID    = "#CBD5E1"
SKY    = "#00AAFF"
PURPLE = "#7B2D8B"

# ── Derived UI style constants ────────────────────────────────────────────────
BTN_PRIMARY   = f"background:{NAVY}; color:{WHITE}; border:none; border-radius:4px; padding:7px 18px; font-size:12px; font-weight:bold;"
BTN_SECONDARY = f"background:{WHITE}; color:{NAVY}; border:1px solid {MID}; border-radius:4px; padding:7px 18px; font-size:12px;"
BTN_TEAL      = f"background:{TEAL}; color:{WHITE}; border:none; border-radius:4px; padding:7px 18px; font-size:12px; font-weight:bold;"
INPUT_STYLE   = f"border:1px solid {MID}; border-radius:3px; padding:5px 8px; background:{WHITE}; font-size:12px;"
INPUT_WARN    = f"border:1px solid {ORANGE}; border-radius:3px; padding:5px 8px; background:#FFF8F0; font-size:12px;"
LABEL_STYLE   = f"color:{NAVY}; font-weight:bold; font-size:12px;"
SUBLABEL_STYLE= f"color:{MID}; font-size:11px;"
SECTION_STYLE = f"color:{TEAL}; font-size:10px; font-weight:bold; letter-spacing:1px;"
MONO_STYLE    = f"border:1px solid {MID}; border-radius:3px; padding:5px 8px; background:#F0F5FB; font-family:Courier New; font-size:12px; color:{NAVY};"
CALC_STYLE    = f"border:1px solid {TEAL}; border-radius:3px; padding:5px 8px; background:#E6F4F1; font-family:Courier New; font-size:12px; color:{TEAL}; font-weight:bold;"

# ── IEC 60794 fibre colour tables ─────────────────────────────────────────────
IEC_COLOURS = ["Blue","Orange","Green","Brown","Slate","White","Red","Black","Yellow","Violet","Rose","Aqua"]
IEC_HEX     = ["#3B82F6","#F97316","#22C55E","#92400E","#94A3B8","#FFFFFF","#EF4444","#1C1C1C","#EAB308","#8B5CF6","#F9A8D4","#06B6D4"]
IEC_BORDER  = [None,None,None,None,None,"#999",None,"#555",None,None,"#e879a0",None]

def fibre_colour_name(fib_in_tube): return IEC_COLOURS[(fib_in_tube - 1) % 12]
def fibre_hex(fib_in_tube):         return IEC_HEX[(fib_in_tube - 1) % 12]
def fibre_border(fib_in_tube):      return IEC_BORDER[(fib_in_tube - 1) % 12]
def fibre_colour(fib):              return IEC_COLOURS[(fib - 1) % 12]
def tube_for_fibre(n, fpt=12):      return ((n - 1) // fpt) + 1
def pos_in_tube(n, fpt=12):         return ((n - 1) % fpt) + 1

# ── Canonical layer display name map ─────────────────────────────────────────
# Internal name -> QGIS display name as loaded by project_manager
LAYER_DISPLAY_NAMES = {
    "build_areas":       "Build Areas",
    "premises":          "Premises",
    "exchange_pops":     "Exchanges & POPs",
    "chambers":          "Chambers",
    "poles":             "Poles",
    "ducts":             "Ducts",
    "cables":            "Cables",
    "fibre_assignments": "Fibre Assignments",
    "joints":            "Joints",
    "drop_ducts":        "Drop Ducts",
    "bundles":           "Bundles",
    "surveys":           "Survey Records",
    "wayleaves":         "Wayleaves",
    "build_tasks":       "Build Tasks",
    "customers":         "Customers",
}

# ── Layer lookup ──────────────────────────────────────────────────────────────

def get_layer(name, project=None):
    """
    Find a layer by internal name or display name.
    If a ConductorProject is supplied, uses its auto-healing get_layer() first.
    Falls back to searching all loaded map layers by display name.
    """
    if project is not None:
        layer = project.get_layer(name)
        if layer is not None:
            return layer

    display = LAYER_DISPLAY_NAMES.get(name, name)
    for layer in QgsProject.instance().mapLayers().values():
        try:
            if layer.name().lower() in (name.lower(), display.lower()):
                return layer
        except RuntimeError:
            pass
    return None


# ── Safe field access ─────────────────────────────────────────────────────────

def fld(feat, key, default=None):
    """Safely get a field value from a QgsFeature or dict. Returns default on NULL/missing."""
    try:
        if isinstance(feat, dict):
            return feat.get(key, default)
        v = feat[key]
        return default if (v is None or v == NULL) else v
    except Exception:
        return default


def val(v):
    """Return None if v is None or QGIS NULL, else v."""
    return None if (v is None or v == NULL) else v


def gpkg_str(feat, field, default=""):
    """Safely read a string field from a GeoPackage feature, treating NULL as default."""
    v = feat[field]
    if v is None or v == NULL or str(v).strip() == "":
        return default
    return str(v).strip()


# ── Write helper ──────────────────────────────────────────────────────────────

class LayerEditContext:
    """
    Context manager for safe layer edits with automatic rollback on failure.

    Usage:
        with LayerEditContext(layer) as edit:
            layer.addFeature(feat)
        # commits on exit; rolls back if an exception is raised
    """
    def __init__(self, layer):
        self._layer = layer

    def __enter__(self):
        self._layer.startEditing()
        return self._layer

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._layer.commitChanges()
            self._layer.triggerRepaint()
        else:
            self._layer.rollBack()
        return False  # do not suppress exceptions


# ── Geometry helpers ────────────────────────────────────────────────

def project_crs():
    """Return the project working CRS as a QgsCoordinateReferenceSystem."""
    return QgsCoordinateReferenceSystem(PROJECT_CRS)


def to_project_crs(canvas, map_pt):
    """
    Transform a point already in the canvas/map CRS into the project CRS
    (EPSG:27700). Returns the point unchanged if the canvas is already in
    the project CRS. Mirrors the former per-tool `_to_27700` helpers.
    """
    src = canvas.mapSettings().destinationCrs()
    dst = project_crs()
    if src == dst:
        return map_pt
    return QgsCoordinateTransform(src, dst, QgsProject.instance()).transform(map_pt)


def screen_to_project_crs(canvas, screen_pos):
    """Convert a screen/pixel position to a point in the project CRS."""
    map_pt = canvas.getCoordinateTransform().toMapCoordinates(screen_pos)
    return to_project_crs(canvas, map_pt)


def line_length_m(points):
    """
    Geodesic length in metres of a polyline given as a list of QgsPointXY in
    the project CRS, rounded to 0.1 m. A two-point list yields the same value
    as the former `measureLine(p1, p2)` helpers (single-segment polyline).
    """
    da = QgsDistanceArea()
    da.setEllipsoid("WGS84")
    da.setSourceCrs(project_crs(), QgsProject.instance().transformContext())
    return round(da.measureLength(QgsGeometry.fromPolylineXY(list(points))), 1)


# ── Snapping ───────────────────────────────────────────────────────

def snap_to_node(canvas, project, screen_pos, snap_layers,
                 snap_radius_px=14, fallback=False, stringify_id=False):
    """
    Snap a click to the nearest feature across one or more target layers.

    snap_layers : iterable of (layer_name, id_field, node_type) tuples, tried
                  in order; the closest feature across all of them wins.
    fallback    : if True and nothing is within range, return the raw click
                  point with id "0" and type "FREE" (drop/bundle behaviour);
                  if False, return (None, None, None) (duct behaviour).
    stringify_id: if True, the returned id is str()-cast (drop/bundle); if
                  False, the raw field value is returned (duct).

    Returns (point_in_project_crs, node_id, node_type).
    """
    pt = screen_to_project_crs(canvas, screen_pos)
    radius = canvas.mapUnitsPerPixel() * snap_radius_px
    rect = QgsRectangle(pt.x() - radius, pt.y() - radius,
                        pt.x() + radius, pt.y() + radius)

    best_dist, best_pt, best_id, best_type = radius, None, None, None
    for layer_name, id_field, node_type in snap_layers:
        layer = project.get_layer(layer_name)
        if not layer or layer.featureCount() == 0:
            continue
        for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
            fp = feat.geometry().asPoint()
            dist = math.hypot(fp.x() - pt.x(), fp.y() - pt.y())
            if dist < best_dist:
                best_dist = dist
                best_pt = fp
                best_id = str(feat[id_field]) if stringify_id else feat[id_field]
                best_type = node_type

    if best_pt is None and fallback:
        return pt, "0", "FREE"
    return best_pt, best_id, best_type


# ── Numbering ────────────────────────────────────────────────────

def compass_quadrant(from_pt, to_pt):
    """
    Classify the bearing from `from_pt` (e.g. cabinet) to `to_pt` into one of
    four 90-degree quadrants: "N", "E", "S", or "W". North-biased: bearings
    within 45 deg of due north return "N", etc. This is the shared classifier
    behind duct leg numbering and chamber direction numbering; each asset type
    keeps its own base/sequence map.
    """
    dx = to_pt.x() - from_pt.x()
    dy = to_pt.y() - from_pt.y()
    bearing = (90 - math.degrees(math.atan2(dy, dx))) % 360
    if bearing < 45 or bearing >= 315:
        return "N"
    elif bearing < 135:
        return "E"
    elif bearing < 225:
        return "S"
    else:
        return "W"
