"""diff() behavior on hand-built snapshots (no SDK install needed)."""
from whatchanged.diff import FieldChange, Moved, diff


def req(path="/v1/a", body=None, ctype="application/json", method="POST"):
    return {"method": method, "path": path, "template": path, "query": [], "content_type": ctype,
            "headers": {}, "body": body}


def wire(call="", request=None, error=None):
    w = {"call": call, "request": request, "n_requests": 1 if request else 0}
    if error:
        w["client_error"] = error
    return w


def method(params=(), wires=None):
    return {"params": [{"name": n, "kind": "KEYWORD_ONLY", "required": r, "type": t, "type_key": t}
                       for n, r, t in params],
            "wire": wires or {}, "skipped": []}


def snap(**methods):
    return {"methods": methods}


def run(a, b):
    return diff(a, b, "1", "2")


def test_renamed_method_hitting_same_endpoint_is_moved_not_removed():
    old = snap(**{"conv.agents.create": method(wires={"base": wire(request=req("/v1/agents"))})})
    new = snap(**{"agents.create": method(wires={"base": wire(request=req("/v1/agents"))})})
    ch = run(old, new)
    assert ch.moved == [Moved("conv.agents.create", "agents.create")]
    assert not ch.breaking and not ch.added


def test_removed_method_and_new_required_param_are_breaking():
    old = snap(gone=method(), keep=method([("a", False, "str")]))
    new = snap(keep=method([("a", False, "str"), ("b", True, "int")]))
    kinds = {(b.method, b.kind) for b in run(old, new).breaking}
    assert kinds == {("gone", "removed method"), ("keep", "new required param")}


def test_equal_types_are_not_reported_but_different_types_are():
    old = snap(m=method([("x", False, "int"), ("y", False, "str")]))
    new = snap(m=method([("x", False, "int"), ("y", False, "int")]))
    assert [t.param for t in run(old, new).types] == ["y"]


def test_body_change_is_a_wire_change_but_json_key_order_is_not():
    old = snap(m=method(wires={"base": wire("c", req(body={"a": 1, "b": 2}))}))
    same = snap(m=method(wires={"base": wire("c", req(body={"b": 2, "a": 1}))}))
    diffd = snap(m=method(wires={"base": wire("c", req(body={"a": 1, "b": 3}))}))
    assert run(old, same).wire == []
    ch = run(old, diffd)
    assert ch.wire[0].groups[0].changes == [FieldChange("json `b`", "2", "3")]


def test_client_error_appearing_is_breaking_and_disappearing_is_a_wire_change():
    ok = snap(m=method(wires={"base": wire("c", req())}))
    bad = snap(m=method(wires={"base": wire("c", None, "TypeError")}))
    assert run(ok, bad).breaking[0].kind == "client_error appeared"
    assert run(bad, ok).wire[0].groups[0].changes[0].before == "raises TypeError"


def test_variants_with_different_inputs_are_not_compared():
    old = snap(m=method(wires={"s": wire("status='a'", req(body={"s": "a"}))}))
    new = snap(m=method(wires={"s": wire("status='b'", req(body={"s": "b"}))}))
    ch = run(old, new)
    assert ch.wire == [] and len(ch.incomparable) == 1
