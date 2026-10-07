"""Changes -> Markdown."""
from __future__ import annotations

from collections import defaultdict

from .diff import Changes, FieldChange, signature
from .guides import Guide, possible_additions

GLOBAL_THRESHOLD = 8  # a wire change seen on this many methods is reported once, not per method
MAX_VALUE = 200
NONE = "_None._"


def _trim(s: str) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= MAX_VALUE else s[:MAX_VALUE] + "..."


def _snippet(changes: list[FieldChange]) -> str:
    lines = []
    for c in changes:
        lines += [c.field, f"- {_trim(c.before)}", f"+ {_trim(c.after)}"]
    return "```diff\n" + "\n".join(lines) + "\n```"


def _details(summary: str, body: str) -> str:
    return f"<details>\n<summary>{summary}</summary>\n\n{body}\n\n</details>"


def _section(heading: str, lines: list[str]) -> list[str]:
    return ["", f"## {heading}", "", *(lines or [NONE])]


def _wire_blocks(ch: Changes) -> list[str]:
    methods_by_sig = defaultdict(set)
    changes_by_sig = {}
    for item in ch.wire:
        for g in item.groups:
            methods_by_sig[g.signature].add(item.method)
            changes_by_sig[g.signature] = g.changes
    global_sigs = sorted(s for s, ms in methods_by_sig.items() if len(ms) >= GLOBAL_THRESHOLD)

    blocks = []
    for item in ch.wire:
        parts = []
        for g in item.groups:
            if g.signature in global_sigs:
                continue
            first, rest = g.variants[0], g.variants[1:]
            part = f"`{item.method}({first.call})`\n\n{_snippet(g.changes)}"
            if rest:
                part += "\n\nSame change in: " + ", ".join(f"`{v.key}`" for v in rest)
            parts.append(part)
        if parts:
            was = f" (was `{item.old_method}`)" if item.old_method else ""
            blocks.append(f"### `{item.method}`{was}\n\n" + "\n\n".join(parts))
    for sig in global_sigs:
        methods = sorted(methods_by_sig[sig])
        blocks.append(f"### Across {len(methods)} methods\n\n{_snippet(changes_by_sig[sig])}\n\n"
                      + _details("methods", ", ".join(f"`{m}`" for m in methods)))
    return blocks


def _breaking_lines(ch: Changes) -> list[str]:
    by_kind = defaultdict(list)
    for b in ch.breaking:
        by_kind[b.kind].append(b)
    lines = []
    for kind, items in by_kind.items():
        lines += [f"**{kind}**", ""]
        lines += [f"- `{b.method}`: {b.detail}" for b in items]
        lines.append("")
    return lines


def _type_lines(ch: Changes) -> list[str]:
    if not ch.types:
        return []
    return ["| method | param | before | after |", "|---|---|---|---|"] + [
        f"| `{t.method}` | `{t.param}` | `{_trim(t.before)}` | `{_trim(t.after)}` |" for t in ch.types]


def _additions_lines(ch: Changes, guide: Guide) -> list[str]:
    pa = possible_additions(ch, guide)
    lines = [f"Changes found here that [the guide]({guide.url}) does not mention. These are "
             "candidates for documentation, not errors: the guide may simply be incomplete.", ""]
    lines += [f"- `{b.method}` ({b.kind}): {b.detail}" for b in pa.breaking]
    lines += [f"- `{m.old}` -> `{m.new}` (moved)" for m in pa.moved]
    if pa.wire:
        lines.append("- wire behavior changed (see above): " + ", ".join(f"`{m}`" for m in pa.wire))
    return lines if len(lines) > 2 else lines + [NONE]


def _skipped_details(ch: Changes, n_skipped: int) -> str:
    body = []
    if ch.incomparable:
        body += [f"**Inputs differ between versions, wire not compared** ({len(ch.incomparable)})", ""]
        body += [f"- `{s.method}` `{s.variant}`: `{_trim(s.before)}` vs `{_trim(s.after)}`"
                 for s in ch.incomparable]
        body.append("")
    for version, items in ch.skipped.items():
        body += [f"**Could not be synthesized in {version}** ({len(items)})", ""]
        body += [f"- `{s.method}` `{s.variant}`: {s.reason}" for s in items]
        body.append("")
    return _details(f"{n_skipped} variants skipped, {len(ch.incomparable)} not compared",
                    "\n".join(body))


def render(ch: Changes, guide: Guide | None = None) -> str:
    n_wire = len(ch.wire)
    n_skipped = sum(len(v) for v in ch.skipped.values())
    out = [f"# whatchanged: elevenlabs {ch.old} -> {ch.new}", "",
           f"{n_wire} methods with wire changes, {len(ch.breaking)} breaking, "
           f"{len(ch.moved)} moved, {len(ch.types)} type changes, {len(ch.added)} additions."]
    out += _section(f"Wire behavior changed ({n_wire})", ["\n\n".join(_wire_blocks(ch))] if ch.wire else [])
    out += _section(f"Breaking ({len(ch.breaking)})", _breaking_lines(ch))
    out += _section(f"Moved ({len(ch.moved)})", [f"- `{m.old}` -> `{m.new}`" for m in ch.moved])
    out += _section(f"Type changed ({len(ch.types)})", _type_lines(ch))
    out += _section(f"Added ({len(ch.added)})", [f"- `{a.method}`: {a.detail}" for a in ch.added])
    if guide:
        pa = possible_additions(ch, guide)
        n = len(pa.breaking) + len(pa.moved) + len(pa.wire)
        out += _section(f"Possible additions to the {guide.name} ({n})", _additions_lines(ch, guide))
    out += _section(f"Skipped ({n_skipped})", [_skipped_details(ch, n_skipped)])
    return "\n".join(out) + "\n"
