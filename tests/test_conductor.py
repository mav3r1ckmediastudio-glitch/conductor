# -*- coding: utf-8 -*-
"""
Conductor - test suite for pure / deterministic logic.

Runs two ways:
  * pytest from the QGIS plugins directory:  python -m pytest conductor/tests
  * directly inside QGIS:  import conductor.tests.test_conductor as t; t.run()

Most tests need the QGIS Python (qgis.core), so run them in the QGIS
environment rather than a bare interpreter.
"""

import os

from conductor import conductor_utils as cu
from conductor.tools import digitise_duct as dd
from conductor.tools import place_chamber as pc


# -- IEC 60794 fibre colour tables --
def test_iec_colour_cycle_is_12():
    for n in range(1, 13):
        assert cu.fibre_colour_name(n) == cu.fibre_colour_name(n + 12)

def test_iec_first_and_last():
    assert cu.fibre_colour_name(1) == "Blue"
    assert cu.fibre_colour_name(12) == "Aqua"
    assert cu.fibre_colour_name(13) == "Blue"

def test_iec_hex_is_valid_7char():
    for n in range(1, 13):
        h = cu.fibre_hex(n)
        assert isinstance(h, str) and len(h) == 7 and h[0] == "#"


# -- Tube / position arithmetic (12 fibres per tube) --
def test_tube_and_position_boundaries():
    assert (cu.tube_for_fibre(1),  cu.pos_in_tube(1))  == (1, 1)
    assert (cu.tube_for_fibre(12), cu.pos_in_tube(12)) == (1, 12)
    assert (cu.tube_for_fibre(13), cu.pos_in_tube(13)) == (2, 1)
    assert (cu.tube_for_fibre(24), cu.pos_in_tube(24)) == (2, 12)
    assert (cu.tube_for_fibre(25), cu.pos_in_tube(25)) == (3, 1)

def test_tube_pos_roundtrip():
    for n in range(1, 145):
        t, p = cu.tube_for_fibre(n), cu.pos_in_tube(n)
        assert (t - 1) * 12 + p == n


# -- Compass quadrant classifier (drives leg / direction numbering) --
class _Pt:
    def __init__(self, x, y): self._x, self._y = x, y
    def x(self): return self._x
    def y(self): return self._y

def test_compass_cardinals():
    o = _Pt(0, 0)
    assert cu.compass_quadrant(o, _Pt(0,  10)) == "N"
    assert cu.compass_quadrant(o, _Pt(10,  0)) == "E"
    assert cu.compass_quadrant(o, _Pt(0, -10)) == "S"
    assert cu.compass_quadrant(o, _Pt(-10, 0)) == "W"

def test_compass_boundary_at_45_is_east():
    # Boundary convention (matches the original _compass_leg): a bearing of
    # exactly 45deg (due NE) classifies as "E"; just west of it (more
    # northerly) classifies as "N". Locking this prevents silent ID drift.
    o = _Pt(0, 0)
    assert cu.compass_quadrant(o, _Pt(10, 10)) == "E"   # bearing 45 -> E
    assert cu.compass_quadrant(o, _Pt(9, 10))  == "N"   # bearing <45 -> N
    assert cu.compass_quadrant(o, _Pt(10, 9))  == "E"   # bearing >45 -> E


# -- Numbering conventions: LOCK these so a refactor cannot renumber assets --
def test_duct_leg_base_unchanged():
    assert dd.LEG_BASE == {"N": 1, "S": 100, "E": 200, "W": 300}
    assert dd.LEG_MAX  == {"N": 99, "S": 199, "E": 299, "W": 399}

def test_chamber_direction_base_unchanged():
    assert pc.DIRECTION_BASE == {"N": 1, "S": 1001, "W": 2001, "E": 3001}


# -- Geodesic length (needs qgis.core) --
def test_line_length_100m():
    from qgis.core import QgsPointXY
    pts = [QgsPointXY(400000, 400000), QgsPointXY(400000, 400100)]
    L = cu.line_length_m(pts)
    assert abs(L - 100.0) < 1.0, L

def test_line_length_two_pt_equals_polyline():
    from qgis.core import (QgsPointXY, QgsDistanceArea, QgsCoordinateReferenceSystem, QgsProject)
    p1, p2 = QgsPointXY(400000, 400000), QgsPointXY(400123, 400077)
    da = QgsDistanceArea(); da.setEllipsoid("WGS84")
    da.setSourceCrs(QgsCoordinateReferenceSystem("EPSG:27700"), QgsProject.instance().transformContext())
    assert cu.line_length_m([p1, p2]) == round(da.measureLine(p1, p2), 1)


# -- Field access helpers --
def test_fld_on_dict():
    assert cu.fld({"a": 5}, "a") == 5
    assert cu.fld({"a": 5}, "missing", "dft") == "dft"

def test_val_handles_null():
    from qgis.core import NULL
    assert cu.val(None) is None
    assert cu.val(NULL) is None
    assert cu.val(7) == 7


# -- Version single-sourcing --
def test_plugin_version_matches_metadata():
    here = os.path.dirname(os.path.dirname(__file__))
    import configparser
    cfg = configparser.ConfigParser(); cfg.read(os.path.join(here, "metadata.txt"), encoding="utf-8")
    assert cu.plugin_version() == cfg.get("general", "version")


# -- Locked-file fallback --
def test_safe_write_text_roundtrip():
    import tempfile
    p = os.path.join(tempfile.gettempdir(), "conductor_test_rt.txt")
    out = cu.safe_write_text(p, "hello", what="unit test")
    assert out == p and open(p, encoding="utf-8").read() == "hello"
    os.remove(p)

def test_safe_write_text_locked_falls_back():
    import tempfile, stat, glob
    d = tempfile.gettempdir()
    p = os.path.join(d, "conductor_test_locked.txt")
    with open(p, "w") as f: f.write("old")
    os.chmod(p, stat.S_IREAD)
    try:
        out = cu.safe_write_text(p, "new", what="unit test")
        assert out != p and os.path.exists(out)
    finally:
        os.chmod(p, stat.S_IWRITE)
        for g in glob.glob(os.path.join(d, "conductor_test_locked*")):
            try: os.chmod(g, stat.S_IWRITE); os.remove(g)
            except OSError: pass


# -- Built-in runner (so the suite runs without pytest installed) --
def run():
    import traceback
    tests = sorted(n for n, o in globals().items() if n.startswith("test_") and callable(o))
    passed, failed = 0, []
    for name in tests:
        try:
            globals()[name](); passed += 1
        except Exception as e:
            failed.append((name, "".join(traceback.format_exception_only(type(e), e)).strip()))
    print(f"PASSED {passed}/{len(tests)}")
    for name, err in failed:
        print(f"  FAIL {name}: {err}")
    return passed, failed


if __name__ == "__main__":
    run()
