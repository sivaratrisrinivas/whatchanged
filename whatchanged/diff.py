"""Two capture snapshots -> structured changes."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

ABSENT = "(absent)"


@dataclass
class FieldChange:
    field: str
    before: str
    after: str


@dataclass
class Variant:
    key: str
    call: str


@dataclass
class WireGroup:
    """One set of field changes and the call variants that show it."""
    changes: list[FieldChange]
    variants: list[Variant]

    @property
    def signature(self) -> str:
        return signature(self.changes)


@dataclass
class WireItem:
    method: str
    old_method: str | None
    groups: list[WireGroup]


@dataclass
class Breaking:
    method: str
    kind: str
    detail: str


@dataclass
class Moved:
    old: str
    new: str


@dataclass
class TypeChange:
    method: str
    param: str
    before: str
    after: str


@dataclass
class Added:
    method: str
    detail: str


@dataclass
class Skipped:
    method: str
    variant: str
    reason: str


@dataclass
class Incomparable:
    """A variant whose synthesized inputs differ between versions, so its wire isn't compared."""
    method: str
    variant: str
    before: str
    after: str


@dataclass
class Changes:
    old: str
    new: str
    wire: list[WireItem] = field(default_factory=list)
    breaking: list[Breaking] = field(default_factory=list)
    moved: list[Moved] = field(default_factory=list)
    types: list[TypeChange] = field(default_factory=list)
    added: list[Added] = field(default_factory=list)
    skipped: dict[str, list[Skipped]] = field(default_factory=dict)  # by version
    incomparable: list[Incomparable] = field(default_factory=list)


def signature(changes: list[FieldChange]) -> str:
    """Stable identity of a set of field changes, to group identical changes."""
    return json.dumps([[c.field, c.before, c.after] for c in changes])


# ---------------------------------------------------------------- snapshot access

def _requests(method: dict) -> list[dict]:
    return [w["request"] for w in method["wire"].values() if w.get("request")]


def _endpoints(method: dict) -> frozenset:
    return frozenset((r["method"], r["template"]) for r in _requests(method))


def _params_by_name(method: dict) -> dict:
    return {p["name"]: p for p in method["params"]}


def _positional_names(method: dict, among: dict) -> list[str]:
    return [p["name"] for p in method["params"]
            if p["kind"] == "POSITIONAL_OR_KEYWORD" and p["name"] in among]


# ---------------------------------------------------------------- wire comparison

def _pairs_to_multimap(pairs) -> dict:
    """[(k, v), ...] -> {k: v}, with repeated keys collecting their values into a list."""
    out: dict = {}
    for k, v in pairs:
        if k in out:
            out[k] = (out[k] if isinstance(out[k], list) else [out[k]]) + [v]
        else:
            out[k] = v
    return out


def _leaf_changes(prefix, a, b, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            _leaf_changes(f"{prefix}.{k}" if prefix else k, a.get(k, ABSENT), b.get(k, ABSENT), out)
    elif a != b:
        out.append((prefix, a, b))


def _fmt(v):
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True)


def request_changes(a: dict, b: dict) -> list[FieldChange]:
    """Field-level differences between two normalised requests."""
    out: list = []
    for key, label in (("method", "http method"), ("path", "path"), ("content_type", "content-type")):
        if a[key] != b[key]:
            out.append((label, a[key], b[key]))
    for label, old_map, new_map in (
            ("query", _pairs_to_multimap(a["query"]), _pairs_to_multimap(b["query"])),
            ("header", a["headers"], b["headers"])):
        for k in sorted(set(old_map) | set(new_map)):
            if old_map.get(k, ABSENT) != new_map.get(k, ABSENT):
                out.append((f"{label} `{k}`", old_map.get(k, ABSENT), new_map.get(k, ABSENT)))
    old_body, new_body = a["body"], b["body"]
    if a["content_type"] == b["content_type"] and old_body is not None and new_body is not None:
        if a["content_type"] == "multipart/form-data" and isinstance(old_body, list) \
                and isinstance(new_body, list):
            # field order is not semantic, so it is compared as a mapping
            sub: list = []
            _leaf_changes("", _pairs_to_multimap(old_body), _pairs_to_multimap(new_body), sub)
            out += [(f"multipart field `{k}`", x, y) for k, x, y in sub]
        elif a["content_type"] == "application/json":
            sub = []
            _leaf_changes("", old_body, new_body, sub)
            out += [(f"json `{k}`" if k else "json body", x, y) for k, x, y in sub]
        elif old_body != new_body:
            out.append(("body", old_body, new_body))
    elif old_body != new_body:
        out.append(("body", ABSENT if old_body is None else old_body,
                    ABSENT if new_body is None else new_body))
    return [FieldChange(f, _fmt(x), _fmt(y)) for f, x, y in out]


def _summary(request: dict) -> str:
    return f"{request['method']} {request['template']}"


def compare_variant(old_w: dict, new_w: dict):
    """-> ("breaking", detail) | ("wire", [FieldChange]) | None for one variant."""
    old_err, new_err = old_w.get("client_error"), new_w.get("client_error")
    if old_err and new_err:
        return ("wire", [FieldChange("client error", old_err, new_err)]) if old_err != new_err else None
    if new_err:
        return ("breaking", f"`{new_err}` is raised before any request is sent (previously "
                            f"`{_summary(old_w['request'])}`)")
    if old_err:
        return ("wire", [FieldChange("result", f"raises {old_err}", f"sends {_summary(new_w['request'])}")])
    changes = request_changes(old_w["request"], new_w["request"])
    return ("wire", changes) if changes else None


# ---------------------------------------------------------------- method matching

def _group_by_endpoint(methods: dict) -> dict:
    groups: dict = {}
    for name, m in methods.items():
        key = _endpoints(m)
        if key:
            groups.setdefault(key, []).append(name)
    return groups


def _leaf(dotted: str) -> str:
    return dotted.rsplit(".", 1)[-1]


def detect_moves(old_only: dict, new_only: dict) -> dict:
    """{old_name: new_name} for removed+added methods that hit the same endpoint(s)."""
    old_groups, new_groups = _group_by_endpoint(old_only), _group_by_endpoint(new_only)
    moves = {}
    for key, olds in old_groups.items():
        news = new_groups.get(key, [])
        if len(olds) == 1 and len(news) == 1:
            moves[olds[0]] = news[0]
        elif news:
            for old in olds:
                same = [n for n in news if _leaf(n) == _leaf(old)]
                if len(same) == 1:
                    moves[old] = same[0]
    # never map two old methods onto one new method
    claimed: dict = {}
    for old, new in list(moves.items()):
        if new in claimed:
            del moves[old]
            del moves[claimed[new]]
        else:
            claimed[new] = old
    return moves


# ---------------------------------------------------------------- the diff

def _compare_params(name, old_m, new_m, ch: Changes):
    old_params, new_params = _params_by_name(old_m), _params_by_name(new_m)
    for pname in old_params:
        if pname not in new_params:
            ch.breaking.append(Breaking(name, "removed param", f"`{pname}` was removed"))
    for pname, new_p in new_params.items():
        if pname not in old_params:
            if new_p["required"]:
                ch.breaking.append(Breaking(name, "new required param", f"`{pname}: {new_p['type']}`"))
            else:
                ch.added.append(Added(name, f"new optional param `{pname}: {new_p['type']}`"))
            continue
        old_p = old_params[pname]
        if old_p["type_key"] != new_p["type_key"]:
            ch.types.append(TypeChange(name, pname, old_p["type"], new_p["type"]))
        if new_p["required"] and not old_p["required"]:
            ch.breaking.append(Breaking(name, "param became required", f"`{pname}`"))
        elif old_p["required"] and not new_p["required"]:
            ch.types.append(TypeChange(name, pname, "required", "optional"))
    old_order = _positional_names(old_m, new_params)
    new_order = _positional_names(new_m, old_params)
    if old_order != new_order:
        ch.breaking.append(Breaking(name, "positional order changed",
                                    f"`{', '.join(old_order)}` -> `{', '.join(new_order)}`"))


def _compare_wire(name, old_name, old_m, new_m, ch: Changes):
    groups: dict = {}
    for key, old_w in old_m["wire"].items():
        new_w = new_m["wire"].get(key)
        if new_w is None:
            continue
        if old_w["call"] != new_w["call"]:
            # the synthesized inputs differ (e.g. an enum gained a member), so the wire
            # difference says nothing about SDK behavior
            ch.incomparable.append(Incomparable(name, key, old_w["call"], new_w["call"]))
            continue
        result = compare_variant(old_w, new_w)
        if result is None:
            continue
        kind, payload = result
        if kind == "breaking":
            ch.breaking.append(Breaking(name, "client_error appeared", f"`{key}`: {payload}"))
        else:
            group = WireGroup(payload, [])
            groups.setdefault(group.signature, group).variants.append(Variant(key, new_w["call"]))
    if groups:
        ch.wire.append(WireItem(name, old_name, list(groups.values())))


def compare_methods(name, old_name, old_m, new_m, ch: Changes):
    _compare_params(name, old_m, new_m, ch)
    _compare_wire(name, old_name, old_m, new_m, ch)


def diff(old_snap: dict, new_snap: dict, old: str, new: str) -> Changes:
    ch = Changes(old, new)
    old_methods, new_methods = old_snap["methods"], new_snap["methods"]
    old_only = {n: m for n, m in old_methods.items() if n not in new_methods}
    new_only = {n: m for n, m in new_methods.items() if n not in old_methods}
    moves = detect_moves(old_only, new_only)
    for name in sorted(old_methods):
        if name in new_methods:
            compare_methods(name, None, old_methods[name], new_methods[name], ch)
        elif name in moves:
            ch.moved.append(Moved(name, moves[name]))
            compare_methods(moves[name], name, old_methods[name], new_methods[moves[name]], ch)
        else:
            ch.breaking.append(Breaking(name, "removed method", "no longer exists"))
    moved_to = set(moves.values())
    for name in sorted(new_only):
        if name not in moved_to:
            ch.added.append(Added(name, "new method"))
    for version, snap in ((old, old_snap), (new, new_snap)):
        ch.skipped[version] = [Skipped(name, s["variant"], s["reason"])
                               for name, m in snap["methods"].items() for s in m["skipped"]]
    return ch
