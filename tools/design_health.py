# -*- coding: utf-8 -*-
# design_health.py — Conductor FTTP Design Plugin
# "Would this network work if it were built right now?" — a single go/no-go
# readiness check run before exporting a BoM or HLD pack.
#
# This is an AGGREGATOR, not a new analysis engine. It runs the existing
# headless validators and re-weighs their findings under one specific lens:
# whether the network as currently drawn would physically function if built.
# That lens is deliberately STRICTER than the route validator's own severities
# (Design Health owns its opinion; it does not change the validator):
#
#   - Optical-budget fail and partial routes are WARNINGS in validate_routes,
#     but here they BLOCK: a premises over budget would be dark, and a partial
#     route is not a working connection.
#   - Unserved premises are NOT a failure: a partial build still works for the
#     premises that ARE connected. They are surfaced as a caution so the
#     designer knows the design is incomplete, not broken.
#
# Tiers:
#   ERROR    -> would NOT work if built (blocks export)   -> verdict NO-GO
#   WARNING  -> would work, but you should know           -> verdict CAUTION
#   INFO     -> completeness / cost only                  -> verdict GO (passes)

from ..conductor_utils import get_layer, val

# Verdict constants
GO      = "GO"
CAUTION = "CAUTION"
NOGO    = "NO-GO"


def _add(issues, tier, category, message, asset_id="", layer=""):
    issues.append({
        "tier":     tier,        # "error" | "warning" | "info"
        "category": category,    # short grouping label
        "message":  message,
        "asset_id": str(asset_id or ""),
        "layer":    layer,
    })


def design_health(project=None):
    """Run the readiness check. Returns:
      {
        "verdict": "GO" | "CAUTION" | "NO-GO",
        "headline": str,                      # one-line plain-English summary
        "error_count": int,
        "warning_count": int,
        "info_count": int,
        "routed": int, "total": int,          # connection coverage
        "issues": [ {tier, category, message, asset_id, layer}, ... ],
        "ran": {"routes": bool, "integrity": bool, "chambers": bool},
      }
    The lens is "would it work if built". Any error -> NO-GO; warnings only ->
    CAUTION; clean -> GO.
    """
    issues = []
    ran = {"routes": False, "integrity": False, "chambers": False}
    routed = total = 0

    # ── 1. Route / optical validation ────────────────────────────────────────
    # Re-weight: optical-fail, partial, trace-error all BLOCK; unserved cautions.
    try:
        from .validate_routes import run_validation_headless
        r = run_validation_headless(project)
        ran["routes"] = True
        routed = r.get("routed", 0)
        total  = r.get("total", 0)
        for it in r.get("issues", []):
            msg = it.get("message", "")
            sev = it.get("severity", "")
            aid = it.get("asset_id", "")
            if "Optical budget fail" in msg:
                _add(issues, "error", "Optical budget",
                     "Premises over optical budget — would be dark if built: " + msg,
                     aid, "premises")
            elif msg.startswith("Partial route") or sev == "error" and "Trace" in msg:
                _add(issues, "error", "Incomplete route",
                     "Premises not fully connected — would not work if built: " + msg,
                     aid, "premises")
            elif sev == "error":
                _add(issues, "error", "Route error", msg, aid, "premises")
            elif msg.startswith("Unserved"):
                # A partial build still works for who IS connected — caution only.
                pass  # counted in coverage below, not listed per-premises (can be thousands)
            elif "oversubscribed" in msg.lower():
                _add(issues, "error", "Splitter oversubscribed",
                     "Splitter has more consumers than ports — cannot connect all: " + msg,
                     it.get("asset_id", ""), "joints")
            elif sev == "warning":
                _add(issues, "warning", "Topology drift", msg, aid, "joints")
            elif sev == "critical":
                _add(issues, "error", "Validation failure", msg, aid, "")
        # Coverage caution: unserved premises = incomplete design (not broken).
        unserved = total - routed
        if unserved > 0:
            _add(issues, "warning", "Incomplete design",
                 "%d of %d premises have no route yet — the built portion works, "
                 "but the design is not complete." % (unserved, total),
                 "", "premises")
    except Exception as e:
        _add(issues, "error", "Check failed",
             "Route validation could not run: %s" % e, "", "")

    # ── 2. Network / FK integrity ────────────────────────────────────────────
    # Broken cross-layer references = signal cannot route = would not work.
    try:
        from .validate_integrity import run_integrity_check_headless
        ig = run_integrity_check_headless()
        ran["integrity"] = True
        for it in ig.get("issues", []):
            sev = it.get("severity", "error")
            detail = "%s.%s -> %s (%s)" % (
                it.get("layer", "?"), it.get("field", "?"),
                it.get("value", "?"), it.get("detail", ""))
            if sev == "error":
                _add(issues, "error", "Broken connectivity",
                     "Reference does not resolve — topology is broken: " + detail,
                     it.get("value", ""), it.get("layer", ""))
            else:
                _add(issues, "warning", "Reference warning", detail,
                     it.get("value", ""), it.get("layer", ""))
    except Exception as e:
        _add(issues, "warning", "Integrity check unavailable",
             "Network integrity check could not run: %s" % e, "", "")

    # ── 3. Chamber sizing completeness (cost honesty, not function) ───────────
    # Does NOT affect whether the network works — affects whether the BoM is
    # right. INFO tier: passes, but the designer should know.
    try:
        ch = get_layer("chambers")
        if ch is not None and ch.fields().indexOf("chamber_size") >= 0:
            ran["chambers"] = True
            unsized = 0
            for f in ch.getFeatures():
                ctype = str(val(f["chamber_type"]) or "")
                if ctype == "PIA_UG_CHAMBER":
                    continue  # PIA chambers are not costed by size
                size = str(val(f["chamber_size"]) or "")
                if size not in ("SMALL", "LARGE"):
                    unsized += 1
            if unsized > 0:
                _add(issues, "info", "Cost accuracy",
                     "%d chamber(s) have no size set and will be costed as SMALL "
                     "in the BoM. Set their size for an accurate cost." % unsized,
                     "", "chambers")
    except Exception as e:
        _add(issues, "info", "Chamber check skipped",
             "Chamber sizing check could not run: %s" % e, "", "")

    # ── Verdict ──────────────────────────────────────────────────────────────
    error_count   = sum(1 for i in issues if i["tier"] == "error")
    warning_count = sum(1 for i in issues if i["tier"] == "warning")
    info_count    = sum(1 for i in issues if i["tier"] == "info")

    if error_count > 0:
        verdict = NOGO
        headline = ("%d blocking issue(s): the network as drawn would not fully "
                    "work if built." % error_count)
    elif warning_count > 0:
        verdict = CAUTION
        headline = ("No blocking faults — the built network would work. %d "
                    "caution(s) to review (often just incomplete design)."
                    % warning_count)
    else:
        verdict = GO
        headline = "The network as drawn would work if built. No faults found."

    return {
        "verdict": verdict,
        "headline": headline,
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "routed": routed,
        "total": total,
        "issues": issues,
        "ran": ran,
    }
