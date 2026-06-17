# -*- coding: utf-8 -*-
"""
conductor_utils.py  —  Conductor FTTP Network Design Plugin
Shared utilities: layer lookup, field access, constants, IEC colour tables.
Import from here rather than duplicating across tool files.
"""

import math
from qgis.core import (
    QgsProject, NULL, Qgis, QgsMessageLog, QgsRectangle, QgsFeatureRequest,
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
GREEN  = "#1A6B3C"
RED    = "#C0392B"
GREEN_BG  = "#EAF7EE"
ORANGE_BG = "#FFF4E6"
RED_BG    = "#FDECEA"

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


# ── Logging ────────────────────────────────────────────────────────

def log(message, level="warning"):
    """Write a message to the QGIS 'Conductor' log panel. Use inside except
    blocks so failures are recorded instead of silently swallowed.
    level: "info" | "warning" | "critical"."""
    lvl = {"info": Qgis.Info, "warning": Qgis.Warning,
           "critical": Qgis.Critical}.get(level, Qgis.Warning)
    try:
        QgsMessageLog.logMessage(str(message), "Conductor", lvl)
    except Exception:
        pass


def plugin_version():
    """Return the plugin version string from metadata.txt (single source)."""
    import os, configparser
    try:
        cfg = configparser.ConfigParser()
        cfg.read(os.path.join(os.path.dirname(__file__), "metadata.txt"), encoding="utf-8")
        return cfg.get("general", "version", fallback="1.0.0")
    except Exception:
        return "1.0.0"


def safe_write_text(path, text, what="file"):
    """Write text to `path` (utf-8). If the file is locked (open in another
    program, or held by OneDrive sync) the write is redirected to a
    timestamped sibling so the export is never lost. Returns the path actually
    written. Other errors are logged and re-raised."""
    import os, datetime
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return path
    except PermissionError:
        base, ext = os.path.splitext(path)
        alt = f"{base}_{datetime.datetime.now():%Y%m%d_%H%M%S}{ext}"
        log(f"{what}: '{os.path.basename(path)}' is locked; saved instead as "
            f"'{os.path.basename(alt)}'", "warning")
        with open(alt, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return alt
    except Exception as e:
        log(f"{what}: failed to write '{path}': {e}", "critical")
        raise


# ── External link helper ───────────────────────────────────────────────────
def open_url_with_fragment(url_string):
    """
    Open url_string (typically a file:// URL with a #fragment, e.g. the
    bundled manual at conductor_manual.html#cabinetcost) in the user's
    default browser, preserving the fragment/query string.

    On Windows, both QDesktopServices.openUrl() and webbrowser.open() strip
    everything after the file path for file:// URLs (verified empirically -
    they go through os.startfile()/ShellExecute, which resolves the file
    path via its extension association and discards the rest of the URL).
    To work around this, find the default browser executable via the
    registry and launch it directly with the full URL as an argument -
    browsers parse #fragments from argv correctly.

    Falls back to webbrowser.open() (no fragment) if anything above fails,
    so the manual still opens - just possibly on its Overview page.
    """
    import sys
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice"
            ) as k:
                progid, _ = winreg.QueryValueEx(k, "ProgId")
            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT, f"{progid}\\shell\\open\\command"
            ) as k:
                cmd, _ = winreg.QueryValueEx(k, "")

            import shlex
            parts = shlex.split(cmd, posix=False)
            parts = [p.strip('"') for p in parts]
            # Replace the %1 placeholder (or append if absent) with our URL
            if "%1" in parts:
                parts = [url_string if p == "%1" else p for p in parts]
            else:
                parts.append(url_string)

            import subprocess
            subprocess.Popen(parts)
            return True
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(
                f"Conductor: open_url_with_fragment direct-launch failed "
                f"({e}), falling back to webbrowser.open()",
                "Conductor", Qgis.Warning,
            )

    import webbrowser
    return webbrowser.open(url_string)


# ═══════════════════════════════════════════════════════════════════════════
# UNDO STACK
# Lightweight inverse-action undo for single-asset operations.
# Supports ADD, DELETE, MOVE, EDIT actions with max 5 entries.
# ═══════════════════════════════════════════════════════════════════════════

class UndoStack:
    """Inverse-action undo/redo stack for Conductor.

    Each entry is a dict:
        {
            "description": str,          # human-readable label
            "layer_name":  str,          # e.g. "chambers"
            "action":      str,          # "ADD" | "DELETE" | "MOVE" | "EDIT"
            "feature_id":  int | None,   # QgsFeature fid (for DELETE/MOVE/EDIT)
            "attrs":       dict | None,  # field name → value snapshot
            "geometry":    QgsGeometry,  # geometry snapshot
        }

    Excluded by design (too expensive or complex to invert):
        - Import premises
        - Cookie-cutter clip
        - Auto-assign fibres
        - Validate routes (read-only)
    """

    MAX_SIZE = 5

    def __init__(self):
        from collections import deque
        self._undo = deque(maxlen=self.MAX_SIZE)
        self._redo = deque(maxlen=self.MAX_SIZE)

    def push(self, entry):
        """Push a new action onto the undo stack. Clears the redo stack."""
        self._undo.append(entry)
        self._redo.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo_description(self):
        return self._undo[-1]["description"] if self._undo else ""

    def redo_description(self):
        return self._redo[-1]["description"] if self._redo else ""

    def undo(self, project):
        """Pop from undo stack, apply inverse, push to redo stack.
        Returns description string or None on failure."""
        if not self._undo:
            return None
        entry = self._undo.pop()
        try:
            inverse = _apply_inverse(entry, project)
            self._redo.append(inverse)
            return entry["description"]
        except Exception as e:
            log(f"Undo failed: {e}", level="warning")
            return None

    def redo(self, project):
        """Pop from redo stack, re-apply action, push to undo stack.
        Returns description string or None on failure."""
        if not self._redo:
            return None
        entry = self._redo.pop()
        try:
            inverse = _apply_inverse(entry, project)
            self._undo.append(inverse)
            return entry["description"]
        except Exception as e:
            log(f"Redo failed: {e}", level="warning")
            return None

    def clear(self):
        self._undo.clear()
        self._redo.clear()


def _apply_inverse(entry, project):
    """Apply the inverse of an undo entry and return the inverse entry
    (so it can be pushed onto the redo stack)."""
    from qgis.core import QgsFeature, QgsGeometry
    NULL = None

    layer_name = entry["layer_name"]
    action     = entry["action"]
    layer      = get_layer(layer_name, project)

    if not layer or not layer.isValid():
        raise RuntimeError(f"Layer '{layer_name}' not found or invalid.")

    if action == "ADD":
        # Inverse of ADD is DELETE — remove the feature we added
        feat_id = entry["feature_id"]
        if feat_id is None:
            # Find by primary key
            id_field = entry.get("id_field")
            id_value = entry.get("id_value")
            feat_id = None
            if id_field and id_value:
                for f in layer.getFeatures():
                    if str(f[id_field]) == str(id_value):
                        feat_id = f.id()
                        break
        if feat_id is None:
            raise RuntimeError("Cannot find feature to undo ADD.")

        # Snapshot before deleting (for redo)
        feat = next(layer.getFeatures(), None)
        for f in layer.getFeatures():
            if f.id() == feat_id:
                feat = f
                break

        inverse = {
            "description": entry["description"],
            "layer_name":  layer_name,
            "action":      "DELETE",
            "feature_id":  None,
            "attrs":       {f: feat[f] for f in feat.fields().names()},
            "geometry":    QgsGeometry(feat.geometry()),
            "id_field":    entry.get("id_field"),
            "id_value":    entry.get("id_value"),
        }

        layer.startEditing()
        layer.deleteFeature(feat_id)
        layer.commitChanges()
        layer.triggerRepaint()
        return inverse

    elif action == "DELETE":
        # Inverse of DELETE is ADD — re-add the feature
        attrs   = entry["attrs"]
        geom    = entry["geometry"]
        inverse = {
            "description": entry["description"],
            "layer_name":  layer_name,
            "action":      "ADD",
            "feature_id":  None,
            "attrs":       attrs,
            "geometry":    QgsGeometry(geom),
            "id_field":    entry.get("id_field"),
            "id_value":    entry.get("id_value"),
        }
        feat = QgsFeature(layer.fields())
        feat.setGeometry(geom)
        for fname, fvalue in (attrs or {}).items():
            idx = layer.fields().indexOf(fname)
            if idx >= 0:
                feat.setAttribute(idx, fvalue)
        layer.startEditing()
        layer.addFeature(feat)
        layer.commitChanges()
        layer.triggerRepaint()
        # Update feature_id for next undo
        id_field = entry.get("id_field")
        id_value = entry.get("id_value")
        if id_field and id_value:
            for f in layer.getFeatures():
                if str(f[id_field]) == str(id_value):
                    inverse["feature_id"] = f.id()
                    break
        return inverse

    elif action == "MOVE":
        # Inverse of MOVE is MOVE back to old geometry
        feat_id  = entry["feature_id"]
        old_geom = entry["geometry"]
        feat = next((f for f in layer.getFeatures() if f.id() == feat_id), None)
        if feat is None:
            raise RuntimeError("Cannot find feature to undo MOVE.")
        inverse = {
            "description": entry["description"],
            "layer_name":  layer_name,
            "action":      "MOVE",
            "feature_id":  feat_id,
            "attrs":       None,
            "geometry":    QgsGeometry(feat.geometry()),
            "id_field":    entry.get("id_field"),
            "id_value":    entry.get("id_value"),
        }
        layer.startEditing()
        layer.changeGeometry(feat_id, old_geom)
        layer.commitChanges()
        layer.triggerRepaint()
        return inverse

    elif action == "EDIT":
        # Inverse of EDIT is re-write old attribute values
        feat_id  = entry["feature_id"]
        old_attrs = entry["attrs"]
        feat = next((f for f in layer.getFeatures() if f.id() == feat_id), None)
        if feat is None:
            raise RuntimeError("Cannot find feature to undo EDIT.")
        # Snapshot current attrs for redo
        inverse = {
            "description": entry["description"],
            "layer_name":  layer_name,
            "action":      "EDIT",
            "feature_id":  feat_id,
            "attrs":       {f: feat[f] for f in feat.fields().names()},
            "geometry":    QgsGeometry(feat.geometry()),
            "id_field":    entry.get("id_field"),
            "id_value":    entry.get("id_value"),
        }
        layer.startEditing()
        for fname, fvalue in (old_attrs or {}).items():
            idx = layer.fields().indexOf(fname)
            if idx >= 0:
                layer.changeAttributeValue(feat_id, idx, fvalue)
        layer.commitChanges()
        layer.triggerRepaint()
        return inverse

    else:
        raise RuntimeError(f"Unknown action type: {action}")
