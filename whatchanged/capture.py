"""Runs inside a version env (python -I capture.py ENV_DIR); prints a JSON snapshot to stdout.

For every public sync client method of the elevenlabs SDK it records the signature (with
resolved types) and the HTTP requests the method sends against an httpx.MockTransport.
"""
from __future__ import annotations

import collections.abc
import datetime
import enum
import inspect
import importlib.metadata
import itertools
import json
import re
import signal
import sys
import types
import typing
import urllib.parse
import warnings

env_dir = sys.argv[1]
sys.path.insert(0, env_dir)
warnings.filterwarnings("ignore")

_real_stdout = sys.stdout
sys.stdout = sys.stderr  # SDK code must not pollute the JSON channel

import httpx  # noqa: E402
import elevenlabs  # noqa: E402
from elevenlabs import ElevenLabs  # noqa: E402

try:
    import pydantic
except Exception:  # pragma: no cover
    pydantic = None

JSONISH = re.compile(r"labels?|metadata|json", re.I)
FILE_VALUE = ("a.mp3", b"\x00\x01", "audio/mpeg")
MAX_VARIANTS_PER_PARAM = 6
IGNORED_HEADERS = {"host", "content-length", "user-agent", "accept-encoding", "connection",
                   "content-type", "xi-api-key"}


class Skip(Exception):
    pass


class CallTimeout(Exception):
    pass


# ---------------------------------------------------------------- type normalisation

def _members(tp):
    """Flattened members of a Union (or [tp]), without None."""
    origin = typing.get_origin(tp)
    if origin is typing.Union or origin is getattr(types, "UnionType", object()):
        out = []
        for a in typing.get_args(tp):
            out.extend(_members(a))
        return [m for m in out if m is not type(None)]
    if tp is type(None):
        return []
    return [tp]


def norm(tp, names=True):
    """Normalised string for a *resolved* type: aliases vanish, unions are sorted."""
    if tp is None or tp is type(None):
        return "None"
    if tp is typing.Any:
        return "Any"
    if isinstance(tp, str):
        return tp
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Annotated:
        return norm(args[0], names)
    if origin is typing.Union or origin is getattr(types, "UnionType", object()):
        flat = []

        def walk(t):
            o = typing.get_origin(t)
            if o is typing.Union or o is getattr(types, "UnionType", object()):
                for a in typing.get_args(t):
                    walk(a)
            else:
                flat.append(t)

        walk(tp)
        return " | ".join(sorted({norm(a, names) for a in flat}))
    if origin is typing.Literal:
        return "Literal[" + ", ".join(sorted(repr(a) for a in args)) + "]"
    if origin is not None:
        oname = getattr(origin, "__name__", str(origin)).lower()
        if oname in ("sequence", "mutablesequence"):
            oname = "list"
        if oname == "mapping":
            oname = "dict"
        inner = ", ".join(norm(a, names) for a in args)
        return f"{oname}[{inner}]"
    if isinstance(tp, type):
        if issubclass(tp, enum.Enum):
            vals = ", ".join(sorted(repr(m.value) for m in tp))
            return f"{tp.__name__}{{{vals}}}" if names else f"enum{{{vals}}}"
        if pydantic is not None and issubclass(tp, pydantic.BaseModel):
            fields = ",".join(sorted(
                f"{n}{'' if f.is_required() else '?'}" for n, f in tp.model_fields.items()))
            return f"{tp.__name__}{{{fields}}}" if names else f"{{{fields}}}"
        if typing.is_typeddict(tp):
            req = getattr(tp, "__required_keys__", set())
            fields = ",".join(sorted(f"{k}{'' if k in req else '?'}" for k in tp.__annotations__))
            return f"{tp.__name__}{{{fields}}}" if names else f"{{{fields}}}"
        return tp.__name__
    return str(tp).replace("typing.", "")


try:
    from elevenlabs.core import File as _File
    FILE_SET = frozenset(norm(m) for m in _members(_File))
except Exception:  # pragma: no cover
    FILE_SET = frozenset()


def is_file(tp):
    ms = _members(tp)
    return bool(FILE_SET) and frozenset(norm(m) for m in ms) == FILE_SET


# ---------------------------------------------------------------- value synthesis

def syn(name, tp, raw=False):
    """Synthesize a value. raw=True builds plain dicts/values for use inside model_construct,
    which (in Fern's UncheckedBaseModel) rebuilds nested models itself."""
    if is_file(tp):
        return FILE_VALUE
    ms = _members(tp)
    if not ms:
        raise Skip("no concrete type")
    if len(ms) > 1:
        return syn(name, ms[0], raw)
    tp = ms[0]
    if tp is typing.Any:
        return "x"
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Annotated:
        return syn(name, args[0], raw)
    if origin is typing.Literal:
        return min(args, key=repr)  # order-independent, so reorders aren't reported as changes
    if origin in (list, set, frozenset, collections.abc.Sequence, collections.abc.Iterable,
                  collections.abc.MutableSequence):
        return [syn(name, args[0], raw) if args else "x"]
    if origin in (dict, collections.abc.Mapping):
        if len(args) > 1:
            v = "v" if args[1] is str else syn(name, args[1], raw)
        else:
            v = "v"
        return {"k": v}
    if origin is tuple:
        return tuple(syn(name, a, raw) for a in args if a is not Ellipsis) or ("x",)
    if origin is not None:
        raise Skip(f"cannot synthesize {norm(tp)}")
    if isinstance(tp, type):
        if issubclass(tp, bool):
            return True
        if issubclass(tp, enum.Enum):
            m = min(tp, key=lambda m: repr(m.value))
            return m.value if raw else m
        if issubclass(tp, int):
            return 1
        if issubclass(tp, float):
            return 1.0
        if issubclass(tp, str):
            return '{"k": "v"}' if JSONISH.search(name) else "x"
        if issubclass(tp, bytes):
            return b"\x00\x01"
        if issubclass(tp, datetime.datetime):
            return datetime.datetime(2024, 1, 1)
        if issubclass(tp, datetime.date):
            return datetime.date(2024, 1, 1)
        if pydantic is not None and issubclass(tp, pydantic.BaseModel):
            try:
                hints = typing.get_type_hints(tp)
                vals = {n: syn(n, hints.get(n, f.annotation), True)
                        for n, f in tp.model_fields.items() if f.is_required()}
                return vals if raw else tp.model_construct(**vals)
            except Skip:
                raise
            except Exception as e:
                raise Skip(f"model {tp.__name__}: {type(e).__name__}")
        if typing.is_typeddict(tp):
            hints = typing.get_type_hints(tp)
            return {k: syn(k, hints[k], raw) for k in getattr(tp, "__required_keys__", ())}
    raise Skip(f"cannot synthesize {norm(tp)}")


def label_of(tp):
    origin = typing.get_origin(tp)
    if origin is not None:
        return getattr(origin, "__name__", str(origin)).lower()
    if isinstance(tp, type):
        return tp.__name__
    return norm(tp)


def variants(name, tp):
    """[(label|None, value|Skip)] — one entry per Union member, else a single entry."""
    ms = _members(tp)
    if is_file(tp) or len(ms) <= 1:
        try:
            return [(None, syn(name, tp))]
        except Skip as e:
            return [(None, e)]
    out = []
    for m in ms[:MAX_VARIANTS_PER_PARAM]:
        try:
            out.append((label_of(m), syn(name, m)))
        except Skip as e:
            out.append((label_of(m), e))
    return out


# ---------------------------------------------------------------- request normalisation

def parse_multipart(body: bytes, boundary: bytes):
    out = []
    for part in body.split(b"--" + boundary)[1:]:
        if part.startswith(b"--"):
            break
        part = part[2:] if part.startswith(b"\r\n") else part
        part = part[:-2] if part.endswith(b"\r\n") else part
        head, _, content = part.partition(b"\r\n\r\n")
        disp = head.decode("utf-8", "replace")
        m = re.search(r'name="([^"]*)"', disp)
        fname = re.search(r'filename="([^"]*)"', disp)
        out.append([m.group(1) if m else "?", "<file>" if fname else content.decode("utf-8", "replace")])
    return out


def norm_request(req: httpx.Request):
    ctype_full = req.headers.get("content-type", "")
    ctype = ctype_full.split(";")[0].strip()
    body = req.content
    nb = None
    if body:
        if ctype == "application/json":
            try:
                nb = json.loads(body)
            except Exception:
                nb = body.decode("utf-8", "replace")[:200]
        elif ctype == "multipart/form-data":
            mb = re.search(r"boundary=([^;]+)", ctype_full)
            nb = parse_multipart(body, mb.group(1).strip('"').encode()) if mb else "<multipart>"
        elif ctype == "application/x-www-form-urlencoded":
            nb = sorted(urllib.parse.parse_qsl(body.decode()))
        else:
            try:
                nb = body.decode("utf-8")[:200]
            except UnicodeDecodeError:
                nb = f"<binary {len(body)} bytes>"
    path = req.url.path
    template = "/".join("{}" if (seg == "x" or seg.isdigit()) else seg for seg in path.split("/"))
    headers = {k.lower(): v for k, v in req.headers.items()
               if k.lower() not in IGNORED_HEADERS and not k.lower().startswith("x-fern")}
    return {
        "method": req.method,
        "path": path,
        "template": template,
        "query": sorted([k, v] for k, v in urllib.parse.parse_qsl(req.url.query.decode())),
        "content_type": ctype,
        "headers": dict(sorted(headers.items())),
        "body": nb,
    }


# ---------------------------------------------------------------- client walk

captured: list = []


def handler(request: httpx.Request) -> httpx.Response:
    request.read()
    captured.append(norm_request(request))
    return httpx.Response(200, json={})


def make_client():
    return ElevenLabs(api_key="x", base_url="https://api.test",
                      httpx_client=httpx.Client(transport=httpx.MockTransport(handler)))


def client_like(obj):
    cls = type(obj)
    if not cls.__name__.endswith("Client") or cls.__name__.startswith(("Raw", "Async")):
        return False
    mod = cls.__module__
    if not mod.startswith("elevenlabs"):
        return False
    return not any(p == "conversation" or p.startswith("realtime") or "websocket" in p
                   for p in mod.split("."))


def walk(obj, path, seen, out, depth=0):
    if depth > 6 or id(obj) in seen:
        return
    seen.add(id(obj))
    for name in sorted(dir(obj)):
        if name.startswith("_") or name in ("with_raw_response",):
            continue
        try:
            attr = getattr(obj, name)
        except Exception:
            continue
        dotted = f"{path}.{name}" if path else name
        if inspect.ismethod(attr) and attr.__self__ is obj:
            out[dotted] = attr
        elif client_like(attr):
            walk(attr, dotted, seen, out, depth + 1)


def describe_params(fn):
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}
    params = []
    for p in inspect.signature(fn).parameters.values():
        if p.name == "request_options":
            continue
        tp = hints.get(p.name, p.annotation if p.annotation is not p.empty else typing.Any)
        params.append({
            "name": p.name,
            "kind": p.kind.name,
            "required": p.default is p.empty and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD),
            "type": norm(tp),
            "type_key": norm(tp, names=False),
            "tp": tp,
        })
    return params, hints


def short_repr(v):
    if isinstance(v, tuple) and v == FILE_VALUE:
        return "<file>"
    if isinstance(v, enum.Enum):
        return f"{type(v).__name__}.{v.name}"
    if pydantic is not None and isinstance(v, pydantic.BaseModel):
        return "<model>"
    return repr(v)[:80]


def _alarm(signum, frame):
    raise CallTimeout()


def do_call(fn, kwargs):
    captured.clear()
    err = None
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, 5)
    try:
        result = fn(**kwargs)
        if inspect.isgenerator(result) or isinstance(result, collections.abc.Iterator):
            for _ in itertools.islice(result, 10):
                pass
    except BaseException as e:  # noqa: BLE001 - every exception is data
        err = type(e).__name__
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    reqs = list(captured)
    entry = {
        "call": ", ".join(f"{k}={short_repr(v)}" for k, v in kwargs.items()),
        "request": reqs[0] if reqs else None,
        "n_requests": len(reqs),
    }
    if not reqs:
        entry["client_error"] = err or "NoRequest"
    return entry


def capture_method(fn):
    params, _ = describe_params(fn)
    info = {"params": [{k: v for k, v in p.items() if k != "tp"} for p in params],
            "wire": {}, "skipped": []}
    plan = {}
    base = {}
    for p in params:
        if p["kind"] in ("VAR_POSITIONAL", "VAR_KEYWORD"):
            continue
        plan[p["name"]] = variants(p["name"], p["tp"])
    for p in params:
        if p["required"]:
            v = plan[p["name"]][0][1]
            if isinstance(v, Skip):
                info["skipped"].append({"variant": "*", "reason": f"required {p['name']}: {v}"})
                return info
            base[p["name"]] = v
    info["wire"]["base"] = do_call(fn, dict(base))
    for p in params:
        n = p["name"]
        if n not in plan:
            continue
        vs = plan[n]
        for i, (label, val) in enumerate(vs):
            if p["required"] and (len(vs) == 1 or i == 0):
                continue
            key = n if label is None else f"{n}={label}"
            if isinstance(val, Skip):
                info["skipped"].append({"variant": key, "reason": str(val)})
                continue
            info["wire"][key] = do_call(fn, {**base, n: val})
    return info


def main():
    client = make_client()
    methods = {}
    walk(client, "", set(), methods)
    out = {"sdk_version": importlib.metadata.version("elevenlabs"),
           "methods": {}}
    for dotted in sorted(methods):
        out["methods"][dotted] = capture_method(methods[dotted])
    _real_stdout.write(json.dumps(out))


main()
