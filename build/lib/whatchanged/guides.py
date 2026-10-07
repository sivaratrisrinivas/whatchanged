"""What an upgrade guide already documents, so the rest can be flagged as possible additions.

Transcribed from https://github.com/elevenlabs/elevenlabs-python/wiki/v3-upgrade-guide
(v3 was a prerelease when this was written; the guide says details may change).
A name ending in "." matches by prefix, anything else must match exactly.
"""
from __future__ import annotations

from .diff import Changes

GUIDES = {
    "v3": {
        "name": "v3 upgrade guide",
        "url": "https://github.com/elevenlabs/elevenlabs-python/wiki/v3-upgrade-guide",
        "moved": [("conversational_ai.", "agents.")],
        "removed_methods": [
            "voices.get_all", "text_to_voice.create_previews", "usage.get",
            "dubbing.resource.", "dubbing.transcript.",
            "conversational_ai.add_to_knowledge_base", "conversational_ai.knowledge_base.",
            "conversational_ai.agents.simulate_conversation",
            "conversational_ai.agents.simulate_conversation_stream",
        ],
        "removed_params": ["cloud_storage_url"],
    },
}


def _match(name: str, patterns) -> bool:
    return any(name.startswith(p) if p.endswith(".") else name == p for p in patterns)


def possible_additions(ch: Changes, guide: dict) -> dict:
    """Changes the guide does not mention: {"breaking": [...], "moved": [...], "wire": [methods]}."""
    breaking = []
    for b in ch.breaking:
        if b["kind"] == "removed method" and _match(b["method"], guide["removed_methods"]):
            continue
        if b["kind"] == "removed param" and any(f"`{p}`" in b["detail"] for p in guide["removed_params"]):
            continue
        breaking.append(b)
    moved = [m for m in ch.moved
             if not any(m["old"].startswith(o) and m["new"] == n + m["old"][len(o):]
                        for o, n in guide["moved"])]
    return {"breaking": breaking, "moved": moved, "wire": sorted({w["method"] for w in ch.wire})}
