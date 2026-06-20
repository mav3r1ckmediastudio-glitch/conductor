# -*- coding: utf-8 -*-
"""
Conductor — Project Manager
Loads a Conductor GeoPackage into QGIS with layer groups and symbology.
"""

import os
from qgis.core import (
    QgsProject, QgsVectorLayer,
    QgsSymbol, QgsSingleSymbolRenderer,
    QgsWkbTypes,
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QMessageBox
from .conductor_utils import NAVY, TEAL, ORANGE, LIGHT, WHITE, MID, SKY, PURPLE, gpkg_str

from .new_project_dialog import LAYER_GROUPS, LAYER_DISPLAY_NAMES

# ── SYMBOLOGY ─────────────────────────────────────────────────────────────────
# point  → (colour, size_mm)
# line   → (colour, width_mm)
# polygon→ (fill_colour, border_colour, border_width, fill_alpha 0-255)

SYMBOLOGY = {
    "build_areas":       ("polygon", "#1A3A5C", "#1D7A6E", 0.5, 18),
    "premises":          ("point",   "#888888", 1.8),
    "exchange_pops":     ("point",   "#C85A00", 4.0),
    "chambers":          ("point",   "#1A3A5C", 2.4),
        "ducts":             ("line",    "#1A3A5C", 0.7),
    "cables":            ("line",    "#FF00FF", 0.35),
    "drop_ducts":        ("line",    "#8B4513", 0.5),
    "fibre_assignments": None,
    "joints":            ("point",   "#888888", 2.0),  # default grey — rule-based per joint_type/has_splitter
    "bundles":           ("line",    "#00FF00", 0.35),
    "surveys":           ("point",   "#E0A000", 2.2),
    "wayleaves":         ("polygon", "#E0A000", "#C85A00", 0.5, 20),
    "build_tasks":       ("line",    "#C85A00", 1.0),
    "customers":         ("point",   "#1D7A6E", 2.2),
}


def _apply_symbology(layer):
    from qgis.core import (
        QgsMarkerSymbol, QgsRuleBasedRenderer,
    )

    name     = layer.name()
    internal = next((k for k, v in LAYER_DISPLAY_NAMES.items() if v == name), name)
    spec     = SYMBOLOGY.get(internal)
    if not spec:
        return

    kind = spec[0]

    if kind == "point":
        _, colour, size = spec

        if internal == "exchange_pops":
            sym = QgsMarkerSymbol.createSimple({
                "name": "square", "color": "#C85A00",
                "outline_color": "#FFFFFF", "outline_width": "0.8", "size": "5",
            })
            layer.setRenderer(QgsSingleSymbolRenderer(sym))

        elif internal == "chambers":
            # Rule-based: PIA_POLE → sky blue circle; PIA_UG_CHAMBER → purple square; default → white square
            root_rule = QgsRuleBasedRenderer.Rule(None)
            chamber_rules = [
                ("PIA_POLE",       "chamber_type = 'PIA_POLE'",       "circle", "#00AAFF", "#000000", "0.4", "4",   "Pole (PIA)"),
                ("PIA_UG_CHAMBER", "chamber_type = 'PIA_UG_CHAMBER'", "square", "#7B2D8B", "#FFFFFF", "0.4", "3.5", "PIA UG Chamber"),
                ("Default",        "ELSE",                             "square", "#FFFFFF",  "#1A3A5C", "0.4", "4",  "Chamber"),
            ]
            for key, expr, shape, fill, outline, outline_w, size, label in chamber_rules:
                sym = QgsMarkerSymbol.createSimple({
                    "name": shape, "color": fill,
                    "outline_color": outline, "outline_width": outline_w, "size": size,
                })
                rule = QgsRuleBasedRenderer.Rule(sym)
                rule.setLabel(label)
                if expr != "ELSE":
                    rule.setFilterExpression(expr)
                else:
                    rule.setIsElse(True)
                root_rule.appendChild(rule)
            layer.setRenderer(QgsRuleBasedRenderer(root_rule))

        elif internal == "joints":
            root_rule = QgsRuleBasedRenderer.Rule(None)
            rules = [
                ("END_OF_LINE",       "joint_type = 'END_OF_LINE'",                                  "#C0392B", "End of Line"),
                ("Primary",           "has_splitter = 1 AND cascade_level = 1",                      "#1A3A5C", "Primary Splitter"),
                ("Secondary",         "has_splitter = 1 AND cascade_level = 2",                      "#C85A00", "Secondary Splitter"),
                ("Direct 1:32",       "has_splitter = 1 AND cascade_type = 'DIRECT_1_32'",           "#1D7A6E", "Direct 1:32"),
                ("Blowing Point",     "joint_type = 'BLOWING_POINT'",                                "#AAAAAA", "Blowing Point"),
                ("Splice",            "ELSE",                                                         "#666666", "Splice"),
            ]
            for key, expr, colour, label in rules:
                sym = QgsMarkerSymbol.createSimple({
                    "name": "circle", "color": colour,
                    "outline_color": "#FFFFFF", "outline_width": "0.3", "size": "3",
                })
                rule = QgsRuleBasedRenderer.Rule(sym)
                rule.setLabel(label)
                if expr != "ELSE":
                    rule.setFilterExpression(expr)
                else:
                    rule.setIsElse(True)
                root_rule.appendChild(rule)

            # CBT — black rectangle, sized to sit inside the PIA_POLE blue circle
            cbt_sym = QgsMarkerSymbol.createSimple({
                "name": "rectangle", "color": "#000000",
                "outline_color": "#000000", "outline_width": "0.2",
                "size": "2.0", "scale_method": "diameter",
                "size_x": "2.0", "size_y": "1.2",
            })
            cbt_rule = QgsRuleBasedRenderer.Rule(cbt_sym)
            cbt_rule.setLabel("CBT")
            cbt_rule.setFilterExpression("joint_type = 'CBT'")
            root_rule.insertChild(0, cbt_rule)

            layer.setRenderer(QgsRuleBasedRenderer(root_rule))
        else:
            sym = QgsSymbol.defaultSymbol(QgsWkbTypes.PointGeometry)
            sym.setColor(QColor(colour))
            sym.setSize(size)
            layer.setRenderer(QgsSingleSymbolRenderer(sym))

    elif kind == "line":
        _, colour, width = spec
        sym = QgsSymbol.defaultSymbol(QgsWkbTypes.LineGeometry)
        sym.setColor(QColor(colour))
        sym.setWidth(width)
        layer.setRenderer(QgsSingleSymbolRenderer(sym))

    elif kind == "polygon":
        _, fill_col, border_col, border_w, alpha = spec
        sym = QgsSymbol.defaultSymbol(QgsWkbTypes.PolygonGeometry)
        sl = sym.symbolLayer(0)
        c = QColor(fill_col)
        c.setAlpha(alpha)
        sl.setColor(c)
        sl.setStrokeColor(QColor(border_col))
        sl.setStrokeWidth(border_w)
        layer.setRenderer(QgsSingleSymbolRenderer(sym))

    layer.triggerRepaint()



# ── LABELLING ──────────────────────────────────────────────────────────────────────────────

def _apply_labels(layer):
    from qgis.core import (
        QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
        QgsTextFormat, QgsTextBufferSettings, QgsUnitTypes,
    )
    from qgis.PyQt.QtGui import QFont, QColor

    name     = layer.name()
    internal = next((k for k, v in LAYER_DISPLAY_NAMES.items() if v == name), name)

    def length_expr(id_field):
        return id_field + " || '  ' || round(\"length_m\", 1) || 'm'"

    LINE  = QgsPalLayerSettings.Line
    POINT = QgsPalLayerSettings.AroundPoint

    config = {
        "exchange_pops": ("pop_id",                   False, "#1A3A5C", 9, POINT, True,  True),
        "chambers":      ("chamber_id",               False, "#1A3A5C", 9, POINT, True,  True),
        "joints":        ("joint_id",                 False, "#1D7A6E", 9, POINT, True,  True, QgsPalLayerSettings.QuadrantAboveRight),
        "poles":         ("pole_id",                  False, "#1A3A5C", 9, POINT, True,  True),
        "ducts":         (length_expr("\"duct_id\""),   True,  "#555555", 7, LINE,  False, False),
        "drop_ducts":    (length_expr("\"ddct_id\""),   True,  "#8B4513", 7, LINE,  False, False),
        "build_areas":   ("area_id",                  False, "#1A3A5C", 9, POINT, False, False),
    }

    spec = config.get(internal)
    if not spec:
        return

    field, is_expr, colour, size, placement, bold, use_buffer, *rest = spec
    quad = rest[0] if rest else QgsPalLayerSettings.QuadrantAboveLeft

    font = QFont("Arial", size)
    font.setBold(bold)

    text_format = QgsTextFormat()
    text_format.setFont(font)
    text_format.setSize(size)
    text_format.setColor(QColor(colour))

    if use_buffer:
        buf = QgsTextBufferSettings()
        buf.setEnabled(True)
        buf.setSize(1.0)
        buf.setSizeUnit(QgsUnitTypes.RenderMillimeters)
        buf.setColor(QColor(255, 255, 255))
        text_format.setBuffer(buf)

    settings = QgsPalLayerSettings()
    settings.fieldName    = field
    settings.isExpression = is_expr
    settings.enabled      = True
    settings.placement    = placement
    settings.setFormat(text_format)

    if placement == POINT:
        settings.quadOffset = quad
        settings.dist       = 2.0
        settings.distUnits  = QgsUnitTypes.RenderMillimeters

    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


class ConductorProject:
    """Represents an open Conductor project."""

    def __init__(self, gpkg_path, project_name, country_code,
                 build_code, designer, project_mgr):
        self.gpkg_path    = gpkg_path
        self.project_name = project_name
        self.country_code = country_code
        self.build_code   = build_code
        self.designer     = designer
        self.project_mgr  = project_mgr
        self.area_id      = f"{country_code}-{build_code}"
        self.layers       = {}

    def load_into_qgis(self):
        root = QgsProject.instance().layerTreeRoot()

        existing = root.findGroup(f"Conductor — {self.project_name}")
        if existing:
            # Remove all map layers registered under this group from the
            # project registry before removing the group node — otherwise
            # they remain as orphaned duplicates in the registry.
            def _collect_layer_ids(node):
                ids = []
                from qgis.core import QgsLayerTree
                if QgsLayerTree.isLayer(node):
                    ids.append(node.layerId())
                for child in node.children():
                    ids.extend(_collect_layer_ids(child))
                return ids
            stale_ids = _collect_layer_ids(existing)
            if stale_ids:
                QgsProject.instance().removeMapLayers(stale_ids)
            root.removeChildNode(existing)

        top = root.insertGroup(0, f"Conductor — {self.project_name}")
        top.setExpanded(True)

        for group_name, layer_names in LAYER_GROUPS.items():
            sub = top.addGroup(group_name)
            sub.setExpanded(group_name == "Reference")

            for layer_name in layer_names:
                display = LAYER_DISPLAY_NAMES.get(layer_name, layer_name)
                uri = f"{self.gpkg_path}|layername={layer_name}"
                layer = QgsVectorLayer(uri, display, "ogr")

                if not layer.isValid():
                    continue

                _apply_symbology(layer)
                _apply_labels(layer)
                QgsProject.instance().addMapLayer(layer, False)
                sub.addLayer(layer)
                self.layers[layer_name] = layer

        QgsProject.instance().setTitle(f"Conductor — {self.project_name}")


        return True

    def get_layer(self, layer_name):
        """Return layer by internal name. Auto-heals stale references after plugin reloads."""
        from qgis.core import QgsProject
        from .new_project_dialog import LAYER_DISPLAY_NAMES

        # Try cached reference first
        layer = self.layers.get(layer_name)
        if layer is not None:
            try:
                _ = layer.featureCount()  # test if still alive
                return layer
            except RuntimeError:
                pass  # stale — fall through to live search

        # Search live map layers by display name and gpkg source
        display = LAYER_DISPLAY_NAMES.get(layer_name, layer_name)
        gpkg = self.gpkg_path.replace(os.sep, "/")
        for name, lyr in QgsProject.instance().mapLayers().items():
            try:
                if lyr.name() == display:
                    src = lyr.source().replace(os.sep, "/")
                    if gpkg in src:
                        _ = lyr.featureCount()
                        self.layers[layer_name] = lyr  # update cache
                        return lyr
            except RuntimeError:
                pass

        return None




def ensure_port_schema(gpkg_path):
    """Idempotently add sticky-port columns to an existing project GeoPackage.

    splitter_port (Int) on bundles + drop_ducts, feeder_port (Int) on joints.
    Safe to call on every project open — adds only what is missing and is a
    no-op once present. New projects already get these from the template.
    Returns a list of (table, field) actually added.
    """
    from qgis.core import QgsVectorLayer, QgsField
    from qgis.PyQt.QtCore import QVariant
    wanted = {
        "bundles":    [("splitter_port", QVariant.Int)],
        "drop_ducts": [("splitter_port", QVariant.Int)],
        "joints":     [("feeder_port",   QVariant.Int)],
    }
    added = []
    for table, want_fields in wanted.items():
        lyr = QgsVectorLayer(f"{gpkg_path}|layername={table}", table, "ogr")
        if not lyr.isValid():
            continue
        have = [f.name() for f in lyr.fields()]
        missing = [QgsField(n, t) for (n, t) in want_fields if n not in have]
        if not missing:
            continue
        if lyr.dataProvider().addAttributes(missing):
            lyr.updateFields()
            added.extend((table, f.name()) for f in missing)
    return added


def load_existing_project(gpkg_path):
    if not os.path.exists(gpkg_path):
        raise FileNotFoundError(f"GeoPackage not found: {gpkg_path}")

    ensure_port_schema(gpkg_path)

    project_name = os.path.splitext(os.path.basename(gpkg_path))[0]
    country_code = ""
    build_code   = ""
    designer     = ""
    project_mgr  = ""

    ba_layer = QgsVectorLayer(
        f"{gpkg_path}|layername=build_areas", "tmp", "ogr"
    )
    if ba_layer.isValid() and ba_layer.featureCount() > 0:
        feat = next(ba_layer.getFeatures())
        project_name = gpkg_str(feat, "area_name",    project_name)
        country_code = gpkg_str(feat, "country_code", "SCOT")
        build_code   = gpkg_str(feat, "build_code",   "XXX")
        designer     = gpkg_str(feat, "designer",     "")
        project_mgr  = gpkg_str(feat, "project_mgr",  "")
    else:
        # No build_areas found — use safe defaults
        country_code = "SCOT"
        build_code   = "XXX"

    return ConductorProject(
        gpkg_path=gpkg_path,
        project_name=project_name,
        country_code=country_code,
        build_code=build_code,
        designer=designer,
        project_mgr=project_mgr,
    )
