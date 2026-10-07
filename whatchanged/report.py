"""Changes -> Markdown."""
from __future__ import annotations

import json
from collections import defaultdict

from .diff import Changes

GLOBAL_THRESHOLD = 8  # a wire change seen on this many methods is reported once, not per method
MAX_VALUE = 200


def _trim(s: str) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= MAX_VALUE else s[:MAX_VALUE] + "..."


def _snippet(changes) -> str:
    lines = []
    for f, before, after in changes:
        lines += [f"{f}", f"- {_trim(before)}", f"+ {_trim(after)}"]
    return "```diff\n" + "\n".join(lines) + "\n```"


def _details(summary: str, body: str) -> str:
    return f"<details>\n<summary>{summary}</summary>\n\n{body}\n\n</details>"


def _wire_section(ch: Changes) -> list:
    sig_methods = defaultdict(set)
    for item in ch.wire:
        for g in item["groups"]:
            sig_methods[json.dumps(g["changes"])].add(item["method"])
    global_sigs = {s for s, ms in sig_methods.items() if len(ms) >= GLOBAL_THRESHOLD}
    out = []
    for item in ch.wire:
        blocks = []
        for g in item["groups"]:
            if json.dumps(g["changes"]) in global_sigs:
                continue
            first, rest = g["variants"][0], g["variants"][1:]
            blk = f"`{item['method']}({first['call']})`\n\n{_snippet(g['changes'])}"
            if rest:
                blk += "\n\nSame change in: " + ", ".join(f"`{v['key']}`" for v in rest)
            blocks.append(blk)
        if blocks:
            moved = f" (was `{item['old_method']}`)" if item["old_method"] else ""
            out.append(f"### `{item['method']}`{moved}\n\n" + "\n\n".join(blocks))
    for sig in sorted(global_sigs):
        methods = sorted(sig_methods[sig])
        changes = json.loads(sig)
        out.append(f"### Across {len(methods)} methods\n\n{_snippet(changes)}\n\n"
                   + _details("methods", ", ".join(f"`{m}`" for m in methods)))
    return out


def render(ch: Changes) -> str:
    n_wire = len({i["method"] for i in ch.wire})
    out = [f"# whatchanged: elevenlabs {ch.old} -> {ch.new}", ""]
    out.append(f"{n_wire} methods with wire changes, {len(ch.breaking)} breaking, "
               f"{len(ch.moved)} moved, {len(ch.types)} type changes, {len(ch.added)} additions.")

    out += ["", f"## Wire behavior changed ({n_wire})", ""]
    out += ["\n\n".join(_wire_section(ch)) or "_None._"]

    out += ["", f"## Breaking ({len(ch.breaking)})", ""]
    if ch.breaking:
        by_kind = defaultdict(list)
        for b in ch.breaking:
            by_kind[b["kind"]].append(b)
        for kind, items in by_kind.items():
            out.append(f"**{kind}**\n")
            out += [f"- `{b['method']}`: {b['detail']}" for b in items]
            out.append("")
    else:
        out.append("_None._")

    out += ["", f"## Moved ({len(ch.moved)})", ""]
    out += [f"- `{m['old']}` -> `{m['new']}`" for m in ch.moved] or ["_None._"]

    out += ["", f"## Type changed ({len(ch.types)})", ""]
    if ch.types:
        out += ["| method | param | before | after |", "|---|---|---|---|"]
        out += [f"| `{t['method']}` | `{t['param']}` | `{_trim(t['before'])}` | `{_trim(t['after'])}` |"
                for t in ch.types]
    else:
        out.append("_None._")

    out += ["", f"## Added ({len(ch.added)})", ""]
    out += [f"- `{a['method']}`: {a['detail']}" for a in ch.added] or ["_None._"]

    total = sum(len(v) for v in ch.skipped.values())
    out += ["", f"## Skipped ({total})", ""]
    body = []
    for ver, items in ch.skipped.items():
        body.append(f"**{ver}** ({len(items)})\n")
        body += [f"- `{s['method']}` `{s['variant']}`: {s['reason']}" for s in items]
        body.append("")
    out.append(_details(f"{total} variants could not be synthesized", "\n".join(body)))
    return "\n".join(out) + "\n"
