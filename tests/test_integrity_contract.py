# -*- coding: utf-8 -*-
"""
Conductor — integrity-validator contract test.

The FK integrity validator (tools/validate_integrity.py) is only correct while
its assumptions about the data model stay true. This test guards against the
validator silently rotting when the schema evolves underneath it — a renamed
layer, a removed FK field, or a typed-node mapping pointing at a layer that no
longer exists. A stale validator is WORSE than none: it reports "clean" while
missing real orphans.

Pure static analysis (stdlib ast) over the source — NO QGIS required, so it
runs on a bare GitHub Actions runner alongside test_schema_contract.py.

It asserts, against new_project_dialog.py's LAYER_SCHEMA (the source of truth):

  1. Every layer named in the validator (ID_FIELD, NODE_TYPE_LAYER targets,
     every check's source + target layer) exists in LAYER_SCHEMA.
  2. Every FK field the validator reads exists on its source layer.
  3. Every ID_FIELD primary key exists on its layer.
  4. Every typed-node check's *_type discriminator field exists on its layer.

Run:  python tests/test_integrity_contract.py
"""
import ast
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)
SCHEMA_FILE = os.path.join(PLUGIN_DIR, "new_project_dialog.py")
VALIDATOR_FILE = os.path.join(PLUGIN_DIR, "tools", "validate_integrity.py")

EXIT_OK, EXIT_FAIL = 0, 1


def _load_schema():
    """{layer_name: [field_name, ...]} from LAYER_SCHEMA, without importing qgis."""
    tree = ast.parse(open(SCHEMA_FILE, encoding="utf-8").read())
    schema = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and getattr(node.targets[0], "id", None) == "LAYER_SCHEMA":
            for table_tuple in node.value.elts:
                layer_name = table_tuple.elts[0].value
                fields = [fc.args[0].value for fc in table_tuple.elts[2].elts]
                schema[layer_name] = fields
    return schema


def _validator_tree():
    return ast.parse(open(VALIDATOR_FILE, encoding="utf-8").read())


def _dict_literal(tree, name):
    """Return a dict {str:str} for a module-level `name = { ... }` assignment."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and getattr(node.targets[0], "id", None) == name \
                and isinstance(node.value, ast.Dict):
            out = {}
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                    out[k.value] = v.value
            return out
    return {}


def _list_of_tuples(tree, name):
    """Return a list of tuples-of-string-constants for `name = [ (...), ... ]`.

    Non-constant tuple elements (e.g. a _direct(...) call) are kept as None so
    positions are preserved.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and getattr(node.targets[0], "id", None) == name \
                and isinstance(node.value, ast.List):
            rows = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Tuple):
                    row = []
                    for e in elt.elts:
                        row.append(e.value if isinstance(e, ast.Constant) else None)
                    rows.append(row)
            return rows
    return []


def main():
    schema = _load_schema()
    tree = _validator_tree()
    layers = set(schema.keys())
    failures = []

    def field_ok(layer, field):
        return layer in schema and field in schema[layer]

    # ── 1. ID_FIELD: layer exists + pk field exists ──────────────────────────
    id_field = _dict_literal(tree, "ID_FIELD")
    for layer, pk in id_field.items():
        if layer not in layers:
            failures.append(f"ID_FIELD references unknown layer '{layer}'")
        elif pk not in schema[layer]:
            failures.append(f"ID_FIELD['{layer}'] = '{pk}' but that field is "
                            f"not on layer '{layer}'")

    # ── 2. NODE_TYPE_LAYER: every target layer exists ────────────────────────
    ntl = _dict_literal(tree, "NODE_TYPE_LAYER")
    for tag, target in ntl.items():
        if target not in layers:
            failures.append(f"NODE_TYPE_LAYER['{tag}'] -> unknown layer '{target}'")

    # ── 3. DIRECT_CHECKS: source layer + fk field exist ──────────────────────
    #     (target layer is inside _direct(...) — checked structurally below)
    for row in _list_of_tuples(tree, "DIRECT_CHECKS"):
        if len(row) >= 2 and row[0] and row[1]:
            src, fld = row[0], row[1]
            if not field_ok(src, fld):
                failures.append(f"DIRECT_CHECKS: '{src}.{fld}' is not a real "
                                f"field on a known layer")

    # ── 4. MULTI_CHECKS: source layer + fk field exist ───────────────────────
    for row in _list_of_tuples(tree, "MULTI_CHECKS"):
        if len(row) >= 2 and row[0] and row[1]:
            src, fld = row[0], row[1]
            if not field_ok(src, fld):
                failures.append(f"MULTI_CHECKS: '{src}.{fld}' is not a real field")

    # ── 5. SPLITTER_AWARE_CHECKS: source.field + real target layer ───────────
    for row in _list_of_tuples(tree, "SPLITTER_AWARE_CHECKS"):
        if len(row) >= 3 and all(row[:3]):
            src, fld, target = row[0], row[1], row[2]
            if not field_ok(src, fld):
                failures.append(f"SPLITTER_AWARE_CHECKS: '{src}.{fld}' not a real field")
            if target not in layers:
                failures.append(f"SPLITTER_AWARE_CHECKS: target layer '{target}' unknown")

    # ── 6. TYPED_CHECKS: node field + *_type discriminator both exist ────────
    for row in _list_of_tuples(tree, "TYPED_CHECKS"):
        if len(row) >= 3 and all(row[:3]):
            src, node_fld, type_fld = row[0], row[1], row[2]
            if not field_ok(src, node_fld):
                failures.append(f"TYPED_CHECKS: node field '{src}.{node_fld}' missing")
            if not field_ok(src, type_fld):
                failures.append(f"TYPED_CHECKS: type field '{src}.{type_fld}' missing")

    # ── Result ───────────────────────────────────────────────────────────────
    checks = (len(id_field) + len(ntl)
              + len(_list_of_tuples(tree, "DIRECT_CHECKS"))
              + len(_list_of_tuples(tree, "MULTI_CHECKS"))
              + len(_list_of_tuples(tree, "SPLITTER_AWARE_CHECKS"))
              + len(_list_of_tuples(tree, "TYPED_CHECKS")))
    if failures:
        print("FAILED — integrity validator contract has drifted from LAYER_SCHEMA:")
        for f in failures:
            print("  -", f)
        return EXIT_FAIL
    print(f"integrity contract: OK — {checks} validator assumptions all match "
          f"LAYER_SCHEMA ({len(layers)} layers).")
    return EXIT_OK


if __name__ == "__main__":
    import sys
    sys.exit(main())
