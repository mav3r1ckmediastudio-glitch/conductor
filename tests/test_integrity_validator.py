# -*- coding: utf-8 -*-
"""
Conductor — FK integrity validator test.

Proves tools/validate_integrity.py BOTH:
  (a) passes a clean fixture set (no false positives), and
  (b) fires on a deliberately injected orphan (no false negatives).

The validator was developed against TARVIN VILLAGE 002, whose data is clean —
so a positive-only check could pass while the validator was silently broken.
This test injects a known orphan to prove the alarm actually rings.

Requires QGIS (memory layers). Run inside the QGIS Python env, or via the
CI job that has python-qgis available:

    python3 -m conductor_v2.tests.test_integrity_validator
"""
import sys

EXIT_OK, EXIT_FAIL = 0, 1


def _build_fixtures(with_orphan):
    from qgis.core import QgsVectorLayer, QgsFeature, QgsField
    from qgis.PyQt.QtCore import QVariant

    def mk(name, rows, spec):
        lyr = QgsVectorLayer("None?crs=EPSG:27700", name, "memory")
        pr = lyr.dataProvider()
        pr.addAttributes([QgsField(n, t) for n, t in spec])
        lyr.updateFields()
        feats = []
        for r in rows:
            f = QgsFeature(lyr.fields())
            for n, _ in spec:
                f.setAttribute(n, r.get(n))
            feats.append(f)
        pr.addFeatures(feats)
        return lyr

    S, B = QVariant.String, QVariant.Bool
    joints = mk("joints",
        [{"joint_id": "JNT-001", "has_splitter": False}],
        [("joint_id", S), ("has_splitter", B), ("chamber_id", S),
         ("pole_id", S), ("pop_id", S)])
    chambers = mk("chambers", [],
        [("chamber_id", S), ("chamber_type", S), ("pop_id", S), ("area_id", S)])
    to_node = "JNT-999" if with_orphan else "JNT-001"
    cables = mk("cables",
        [{"cable_id": "CBL-001", "from_node": "JNT-001", "from_node_type": "JOINT",
          "to_node": to_node, "to_node_type": "JOINT"}],
        [("cable_id", S), ("from_node", S), ("from_node_type", S),
         ("to_node", S), ("to_node_type", S), ("duct_id", S),
         ("pop_id", S), ("splice_to_cable", S)])
    return {"joints": joints, "chambers": chambers, "cables": cables}


def _run(with_orphan):
    from conductor_v2.tools import validate_integrity as vi
    fixtures = _build_fixtures(with_orphan)
    orig = vi.get_layer
    vi.get_layer = lambda name, project=None: fixtures.get(name)
    try:
        return vi.run_integrity_check_headless()
    finally:
        vi.get_layer = orig


def main():
    failures = []

    # (a) clean fixtures -> zero errors
    clean = _run(with_orphan=False)
    if clean["error_count"] != 0:
        failures.append(f"clean fixture produced {clean['error_count']} false positive(s): "
                        f"{clean['issues']}")
    else:
        print("PASS  clean fixture -> 0 errors (no false positives)")

    # (b) orphan injected -> caught, naming JNT-999
    dirty = _run(with_orphan=True)
    caught = dirty["error_count"] >= 1 and any(i["value"] == "JNT-999" for i in dirty["issues"])
    if not caught:
        failures.append(f"orphan NOT caught: errors={dirty['error_count']} issues={dirty['issues']}")
    else:
        print("PASS  injected JNT-999 orphan -> caught (no false negatives)")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print("  -", f)
        return EXIT_FAIL
    print("\nintegrity validator: 2/2 checks passed")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
