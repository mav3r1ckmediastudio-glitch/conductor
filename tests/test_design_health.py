# -*- coding: utf-8 -*-
# test_design_health.py — verdict-logic regression for Design Health.
# Pure logic test: stubs the two headless validators so it needs no live data
# or QGIS layers. Verifies the "would it work if built" tiering:
#   - optical-fail / partial / orphaned-FK  -> error  -> NO-GO
#   - unserved premises                     -> warning -> CAUTION (not blocked)
#   - clean                                 -> GO
import sys, os

# Make the package importable
HERE = os.path.dirname(os.path.abspath(__file__))
PKG_PARENT = os.path.dirname(os.path.dirname(HERE))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)


def _run(routes_result, integ_result, chambers_unsized=0):
    """Call design_health with the two validators + chamber scan stubbed."""
    import conductor_v2.tools.design_health as DH
    import conductor_v2.tools.validate_routes as VR
    import conductor_v2.tools.validate_integrity as VI
    _vr, _vi, _gl = (VR.run_validation_headless,
                     VI.run_integrity_check_headless,
                     DH.get_layer)
    try:
        VR.run_validation_headless = lambda project: routes_result
        VI.run_integrity_check_headless = lambda: integ_result
        # Stub chambers via get_layer returning a tiny fake.
        class _FakeField:
            def __init__(self, n): self._n = n
            def indexOf(self, name): return 0 if name == "chamber_size" else 1
        class _Feat:
            def __init__(self, size): self._size = size
            def __getitem__(self, k):
                return {"chamber_type": "STANDARD", "chamber_size": self._size}[k]
        class _FakeLayer:
            def fields(self): return _FakeField("chamber_size")
            def getFeatures(self):
                return [_Feat(None) for _ in range(chambers_unsized)]
        DH.get_layer = lambda name: _FakeLayer() if name == "chambers" else None
        return DH.design_health(project=None)
    finally:
        VR.run_validation_headless = _vr
        VI.run_integrity_check_headless = _vi
        DH.get_layer = _gl


def main():
    import conductor_v2.tools.design_health as DH
    passed = 0; failed = 0
    def check(name, cond):
        nonlocal passed, failed
        if cond:
            passed += 1; print("PASS ", name)
        else:
            failed += 1; print("FAIL ", name)

    clean_routes = {"routed": 4, "total": 4, "issues": []}
    clean_integ  = {"issues": []}

    # 1. Fully clean -> GO
    r = _run(clean_routes, clean_integ, chambers_unsized=0)
    check("clean -> GO", r["verdict"] == DH.GO)

    # 2. Unserved premises only -> CAUTION (built part works), not NO-GO
    partial_cov = {"routed": 2, "total": 4,
                   "issues": [
                       {"severity": "info", "message": "Unserved: no bundle", "asset_id": "U1"},
                       {"severity": "info", "message": "Unserved: no bundle", "asset_id": "U2"},
                   ]}
    r = _run(partial_cov, clean_integ)
    check("unserved-only -> CAUTION", r["verdict"] == DH.CAUTION)
    check("unserved-only -> 0 errors", r["error_count"] == 0)

    # 3. Optical budget fail -> NO-GO (premises would be dark)
    optfail = {"routed": 3, "total": 3,
               "issues": [{"severity": "warning",
                           "message": "Optical budget fail (-2.0 dB margin)",
                           "asset_id": "U9"}]}
    r = _run(optfail, clean_integ)
    check("optical-fail -> NO-GO", r["verdict"] == DH.NOGO)

    # 4. Orphaned FK -> NO-GO (broken topology)
    orphan = {"issues": [{"layer": "cables", "field": "to_node",
                          "value": "JNT-999", "fid": 1,
                          "severity": "error", "detail": "not found in joints"}]}
    r = _run(clean_routes, orphan)
    check("orphaned-FK -> NO-GO", r["verdict"] == DH.NOGO)

    # 5. Partial route -> NO-GO (not a working connection)
    partial = {"routed": 1, "total": 2,
               "issues": [{"severity": "warning",
                           "message": "Partial route: no drop_duct",
                           "asset_id": "U5"}]}
    r = _run(partial, clean_integ)
    check("partial-route -> NO-GO", r["verdict"] == DH.NOGO)

    # 6. Unsized chambers only -> still GO (info tier, cost not function)
    r = _run(clean_routes, clean_integ, chambers_unsized=5)
    check("unsized-chambers -> GO (info only)", r["verdict"] == DH.GO)
    check("unsized-chambers -> info recorded", r["info_count"] == 1)

    print("\ndesign health: %d/%d checks passed" % (passed, passed + failed))
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
