# -*- coding: utf-8 -*-
"""
Conductor — schema contract test.

This test prevents the class of bug found in the v1.0.1 PIA audit, where a
map tool's get_attributes()/attrs dict used a key that did not exist as a
field on the GeoPackage layer it was writing to. Because every write path
uses the pattern:

    idx = layer.fields().indexOf(fname)
    if idx >= 0 and fvalue is not None:
        feat.setAttribute(idx, fvalue)

...a mismatched key is silently dropped at runtime — no error, no log, just
quietly missing data. That makes this exactly the kind of bug that won't be
noticed until someone goes looking for data that was never saved.

This test is pure static analysis (the `ast` module) over the source files,
so it requires NO QGIS install and can run with a bare `python3`:

    python3 -m conductor.tests.test_schema_contract
    python3 conductor/tests/test_schema_contract.py

It does the following for every (tool_file, target_layer) pair in TARGETS:
  1. Parses new_project_dialog.py's LAYER_SCHEMA to get the authoritative
     list of field names for target_layer.
  2. Parses the tool file's source, finds the dict literal that is written
     to the layer (either the return value of get_attributes(), or a local
     `attrs = {...}` assignment for the two-click drop/bundle tools).
  3. Asserts every string key in that dict is a real field on target_layer.

If you add a new map tool that writes to a layer, add an entry to TARGETS —
that's the contract this test enforces.
"""

import ast
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)
TOOLS_DIR = os.path.join(PLUGIN_DIR, "tools")
SCHEMA_FILE = os.path.join(PLUGIN_DIR, "new_project_dialog.py")


# ── 1. Extract LAYER_SCHEMA field names per layer, via AST ────────────────

def _load_schema():
    """Return {layer_name: [field_name, ...]} from new_project_dialog.py,
    without importing the module (it imports qgis.core)."""
    tree = ast.parse(open(SCHEMA_FILE, encoding="utf-8").read())
    schema = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and getattr(node.targets[0], "id", None) == "LAYER_SCHEMA":
            for table_tuple in node.value.elts:
                # table_tuple = (layer_name, geom_type, [_f("field", ...), ...])
                layer_name = table_tuple.elts[0].value
                fields = []
                for field_call in table_tuple.elts[2].elts:
                    # field_call = _f("field_name", V.X, length)
                    fields.append(field_call.args[0].value)
                schema[layer_name] = fields
    return schema


# ── 2. Extract the attribute-dict keys a tool writes ───────────────────────

def _dict_keys(dict_node):
    keys = []
    for k in dict_node.keys:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.append(k.value)
        else:
            # Non-literal key (e.g. an f-string or variable) — can't check
            # statically; skip it rather than false-failing.
            pass
    return keys


def _keys_from_get_attributes(tree):
    """Find `def get_attributes(self): ... return {...}` and return its keys."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_attributes":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    return _dict_keys(sub.value)
    return None


def _keys_from_attrs_assignment(tree):
    """Find `attrs = {...}` and return its keys (digitise_drop/bundle style)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and getattr(node.targets[0], "id", None) == "attrs" \
                and isinstance(node.value, ast.Dict):
            return _dict_keys(node.value)
    return None


def _slice_str(slice_node):
    """Extract a string constant from a subscript slice (py3.8 wraps in Index)."""
    node = slice_node
    if node.__class__.__name__ == "Index":  # Python 3.8 compatibility
        node = node.value
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keys_from_feature_writes(tree, var="feat"):
    """Find `feat["field"] = ...` subscript writes and return the field keys.

    For tools that build a feature field-by-field in a write loop
    (e.g. fibre_assign.py) instead of via a single dict literal. Only
    assignment *targets* on `var` with a string-literal key are collected,
    so `feat["x"]` reads and variable-keyed writes are ignored.
    """
    keys = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Subscript) \
                        and isinstance(tgt.value, ast.Name) \
                        and tgt.value.id == var:
                    k = _slice_str(tgt.slice)
                    if k is not None:
                        keys.append(k)
    return keys


# ── 3. Tool file -> target layer mapping ───────────────────────────────────
# Add an entry here for every map tool that writes a feature to a layer.
# extractor: "get_attributes" (dialog.get_attributes() pattern),
#            "attrs_var"      (local `attrs = {...}` in _save/_finish), or
#            "feat_writes"    (feat["field"] = ... loop, e.g. fibre_assign.py)

TARGETS = [
    ("place_pop.py",            "exchange_pops", "get_attributes"),
    ("place_chamber.py",        "chambers",      "get_attributes"),
    ("place_pole.py",           "chambers",      "get_attributes"),
    ("place_pia_chamber.py",    "chambers",      "get_attributes"),
    ("place_joint.py",          "joints",        "get_attributes"),
    ("place_cbt.py",            "joints",        "get_attributes"),
    ("digitise_duct.py",        "ducts",         "get_attributes"),
    ("digitise_pia_ug_duct.py", "ducts",         "get_attributes"),
    ("digitise_fibre.py",       "cables",        "get_attributes"),
    ("build_area.py",           "build_areas",   "get_attributes"),
    ("digitise_drop.py",        "drop_ducts",    "attrs_var"),
    ("digitise_pia_ug_drop.py", "drop_ducts",    "attrs_var"),
    ("digitise_bundle.py",      "bundles",       "attrs_var"),
    ("fibre_assign.py",         "fibre_assignments", "feat_writes"),
]

_SCHEMA = _load_schema()


def _check(filename, layer, extractor):
    path = os.path.join(TOOLS_DIR, filename)
    tree = ast.parse(open(path, encoding="utf-8").read())

    if extractor == "get_attributes":
        keys = _keys_from_get_attributes(tree)
    elif extractor == "attrs_var":
        keys = _keys_from_attrs_assignment(tree)
    elif extractor == "feat_writes":
        keys = _keys_from_feature_writes(tree)
    else:
        keys = None

    assert keys, f"{filename}: could not locate attribute dict via {extractor!r}"
    assert layer in _SCHEMA, f"{filename}: unknown layer {layer!r} in LAYER_SCHEMA"

    valid = set(_SCHEMA[layer])
    unknown = [k for k in keys if k not in valid]
    assert not unknown, (
        f"{filename}: writes key(s) {unknown} to layer '{layer}', but "
        f"'{layer}' has no such field(s) in LAYER_SCHEMA (new_project_dialog.py). "
        f"These values will be silently dropped on save."
    )


# ── Tests (one per target, so failures are easy to attribute) ──────────────

def _make_test(filename, layer, extractor):
    def _t():
        _check(filename, layer, extractor)
    _t.__name__ = f"test_schema_contract__{filename.replace('.py','')}"
    return _t


for _filename, _layer, _extractor in TARGETS:
    _fn = _make_test(_filename, _layer, _extractor)
    globals()[_fn.__name__] = _fn


# -- Built-in runner (matches test_conductor.py's convention) --
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
    import sys
    _passed, _failed = run()
    sys.exit(1 if _failed else 0)
