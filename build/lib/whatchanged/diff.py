"""Two capture snapshots -> structured changes."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

ABSENT = "(absent)"


@dataclass
class Changes:
    old: str
    new: str
    wire: list = field(default_factory=list)      # {method, old_method, groups:[{changes, variants}]}
    breaking: list = field(default_factory=list)  # {method, kind, detail}
    moved: list = field(default_factory=list)     # {old, new}
    types: list = field(default_factory=list)     # {method, param, before, after}
    added: list = field(default_factory=list)     # {method, detail}
    skipped: dict = field(default_factory=dict)   # {version: [{method, variant, reason}]}
    incomparable: list = field(default_factory=list)  # {method, variant, before, after}


# ---------------------------------------------------------------- wire comparison

def _kv(pairs):
    out: dict = {}
    for k, v in pairs:
        if k in out:
            out[k] = (out[k] if isinstance(out[k], list) else [out[k]]) + [v]
        else:
            out[k] = v
    return out


def _walk(label, a, b, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            _walk(f"{label}.{k}" if label else k, a.get(k, ABSENT), b.get(k, ABSENT), out)
    elif a != b:
        out.append((label, a, b))


def _fmt(v):
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True)


def request_changes(a: dict, b: dict) -> list:
    """[(field, before, after)] between two normalised requests."""
    out: list = []
    for key, label in (("method", "http method"), ("path", "path"), ("content_type", "content-type")):
        if a[key] != b[key]:
            out.append((label, a[key], b[key]))
    for key, label in (("query", "query"), ("headers", "header")):
        da = _kv(a[key]) if key == "query" else a[key]
        db = _kv(b[key]) if key == "query" else b[key]
        for k in sorted(set(da) | set(db)):
            if da.get(k, ABSENT) != db.get(k, ABSENT):
                out.append((f"{label} `{k}`", da.get(k, ABSENT), db.get(k, ABSENT)))
    ba, bb = a["body"], b["body"]
    if a["content_type"] == b["content_type"] and ba is not None and bb is not None:
        if a["content_type"] == "multipart/form-data" and isinstance(ba, list) and isinstance(bb, list):
            # field order is not semantic, so it is compared as a mapping
            sub: list = []
            _walk("", _kv(ba), _kv(bb), sub)
            out += [(f"multipart field `{k}`", x, y) for k, x, y in sub]
        elif a["content_type"] == "application/json":
            sub = []
            _walk("", ba, bb, sub)
            out += [(f"json `{k}`" if k else "json body", x, y) for k, x, y in sub]
        elif ba != bb:
            out.append(("body", ba, bb))
    elif ba != bb:
        out.append(("body", ba if ba is not None else ABSENT, bb if bb is not None else ABSENT))
    return [(f, _fmt(x), _fmt(y)) for f, x, y in out]


def _req_summary(r):
    return f"{r['method']} {r['template']}"


def compare_wire(key, wa, wb):
    """-> ('breaking', detail) | ('wire', [(field,before,after)]) | None for one variant."""
    ea, eb = wa.get("client_error"), wb.get("client_error")
    if ea and eb:
        return ("wire", [("client error", ea, eb)]) if ea != eb else None
    if eb and not ea:
        return ("breaking", f"`{eb}` is raised before any request is sent (previously "
                            f"`{_req_summary(wa['request'])}`)")
    if ea and not eb:
        return ("wire", [("result", f"raises {ea}", f"sends {_req_summary(wb['request'])}")])
    ch = request_changes(wa["request"], wb["request"])
    return ("wire", ch) if ch else None


# ---------------------------------------------------------------- method matching

def _endpoint_key(m):
    return frozenset((w["request"]["method"], w["request"]["template"])
                     for w in m["wire"].values() if w.get("request"))


def detect_moves(old_only: dict, new_only: dict) -> dict:
    """{old_name: new_name} for removed+added methods that hit the same endpoint(s)."""
    by_old: dict = {}
    by_new: dict = {}
    for n, m in old_only.items():
        k = _endpoint_key(m)
        if k:
            by_old.setdefault(k, []).append(n)
    for n, m in new_only.items():
        k = _endpoint_key(m)
        if k:
            by_new.setdefault(k, []).append(n)
    moves = {}
    for k, olds in by_old.items():
        news = by_new.get(k, [])
        if len(olds) == 1 and len(news) == 1:
            moves[olds[0]] = news[0]
        elif news:
            for o in olds:
                same = [n for n in news if n.rsplit(".", 1)[-1] == o.rsplit(".", 1)[-1]]
                if len(same) == 1:
                    moves[o] = same[0]
    # never map two old methods onto one new method
    seen: dict = {}
    for o, n in list(moves.items()):
        if n in seen:
            del moves[o]
            del moves[seen[n]]
        else:
            seen[n] = o
    return moves


# ---------------------------------------------------------------- the diff

def compare_methods(name, old_name, ma, mb, ch: Changes):
    pa = {p["name"]: p for p in ma["params"]}
    pb = {p["name"]: p for p in mb["params"]}
    for n in pa:
        if n not in pb:
            ch.breaking.append({"method": name, "kind": "removed param",
                                "detail": f"`{n}` was removed"})
    for n, p in pb.items():
        if n not in pa:
            if p["required"]:
                ch.breaking.append({"method": name, "kind": "new required param",
                                    "detail": f"`{n}: {p['type']}`"})
            else:
                ch.added.append({"method": name, "detail": f"new optional param `{n}: {p['type']}`"})
            continue
        q = pa[n]
        if q["type_key"] != p["type_key"]:
            ch.types.append({"method": name, "param": n, "before": q["type"], "after": p["type"]})
        if p["required"] and not q["required"]:
            ch.breaking.append({"method": name, "kind": "param became required", "detail": f"`{n}`"})
        elif q["required"] and not p["required"]:
            ch.types.append({"method": name, "param": n, "before": "required", "after": "optional"})
    pos_a = [p["name"] for p in ma["params"] if p["kind"] == "POSITIONAL_OR_KEYWORD" and p["name"] in pb]
    pos_b = [p["name"] for p in mb["params"] if p["kind"] == "POSITIONAL_OR_KEYWORD" and p["name"] in pa]
    if pos_a != pos_b:
        ch.breaking.append({"method": name, "kind": "positional order changed",
                            "detail": f"`{', '.join(pos_a)}` -> `{', '.join(pos_b)}`"})

    groups: dict = {}
    for key, wa in ma["wire"].items():
        wb = mb["wire"].get(key)
        if wb is None:
            continue
        if wa["call"] != wb["call"]:
            # the synthesized inputs differ (e.g. an enum gained a member), so the wire
            # difference says nothing about SDK behavior
            ch.incomparable.append({"method": name, "variant": key,
                                    "before": wa["call"], "after": wb["call"]})
            continue
        res = compare_wire(key, wa, wb)
        if res is None:
            continue
        kind, payload = res
        if kind == "breaking":
            ch.breaking.append({"method": name, "kind": "client_error appeared",
                                "detail": f"`{key}`: {payload}"})
        else:
            sig = json.dumps(payload)
            groups.setdefault(sig, {"changes": payload, "variants": []})["variants"].append(
                {"key": key, "call": wb["call"]})
    if groups:
        ch.wire.append({"method": name, "old_method": old_name, "groups": list(groups.values())})


def diff(old_snap: dict, new_snap: dict, old: str, new: str) -> Changes:
    ch = Changes(old, new)
    A, B = old_snap["methods"], new_snap["methods"]
    old_only = {n: m for n, m in A.items() if n not in B}
    new_only = {n: m for n, m in B.items() if n not in A}
    moves = detect_moves(old_only, new_only)
    for n in sorted(A):
        if n in B:
            compare_methods(n, None, A[n], B[n], ch)
        elif n in moves:
            ch.moved.append({"old": n, "new": moves[n]})
            compare_methods(moves[n], n, A[n], B[moves[n]], ch)
        else:
            ch.breaking.append({"method": n, "kind": "removed method", "detail": "no longer exists"})
    moved_new = set(moves.values())
    for n in sorted(new_only):
        if n not in moved_new:
            ch.added.append({"method": n, "detail": "new method"})
    for ver, snap in ((old, old_snap), (new, new_snap)):
        ch.skipped[ver] = [{"method": n, "variant": s["variant"], "reason": s["reason"]}
                           for n, m in snap["methods"].items() for s in m["skipped"]]
    return ch
