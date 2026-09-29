"""The Python tool surface must match shared/tool-spec.json (the TS server is generated from it)."""

import inspect

from staticsight.server import TOOLS, build_server, load_spec

SPEC = load_spec()
TYPE_MAP = {"string": str, "integer": int, "boolean": bool}


def test_tool_names_and_order():
    assert [fn.__name__ for fn in TOOLS] == [t["name"] for t in SPEC["tools"]]


def test_docstrings_match_spec_descriptions():
    for fn, spec in zip(TOOLS, SPEC["tools"]):
        assert inspect.cleandoc(fn.__doc__) == spec["description"], fn.__name__


def test_parameters_match_spec():
    for fn, spec in zip(TOOLS, SPEC["tools"]):
        params = list(inspect.signature(fn).parameters.values())
        assert [p.name for p in params] == [p["name"] for p in spec["params"]], fn.__name__
        for p, sp in zip(params, spec["params"]):
            assert p.annotation in (TYPE_MAP[sp["type"]], sp["type"] if sp["type"] != "integer" else "int",
                                    {"string": "str", "boolean": "bool"}.get(sp["type"])), (fn.__name__, p.name)
            if sp.get("required"):
                assert p.default is inspect.Parameter.empty, (fn.__name__, p.name)
            else:
                assert p.default == sp["default"], (fn.__name__, p.name)


async def test_registered_tool_annotations_follow_spec():
    tools = await build_server().list_tools()
    assert [t.name for t in tools] == [t["name"] for t in SPEC["tools"]]
    spec_ro = {t["name"]: t.get("annotations", {}).get("readOnlyHint", True) for t in SPEC["tools"]}
    for t in tools:
        assert t.annotations and t.annotations.readOnlyHint == spec_ro[t.name], t.name
    assert [n for n, ro in spec_ro.items() if not ro] == ["refresh_semantic_index"]  # the only writer (cache only)
