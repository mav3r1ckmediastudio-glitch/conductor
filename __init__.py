# -*- coding: utf-8 -*-
"""
Conductor — FTTP Network Design Plugin for QGIS
Entry point called by QGIS on plugin load.
"""


def classFactory(iface):
    """
    Called by QGIS when the plugin is loaded.
    :param iface: QgsInterface — the QGIS interface instance.
    """
    from .conductor import Conductor
    return Conductor(iface)
