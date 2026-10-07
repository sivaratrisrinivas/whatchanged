"""What an upgrade guide already documents, so the rest can be flagged as possible additions.

Transcribed from https://github.com/elevenlabs/elevenlabs-python/wiki/v3-upgrade-guide
(v3 was a prerelease when this was written; the guide says details may change).
A name ending in "." matches by prefix, anything else must match exactly.
"""
from __future__ import annotations

from dataclasses import dataclass

from .diff import Breaking, Changes, Moved


def _matches(name: str, patterns) -> bool:
    return any(name.startswith(p) if p.endswith(".") else name == p for p in patterns)


@dataclass(frozen=True)
class Guide:
    name: str
    url: str
    moved: tuple          # (old prefix, new prefix) pairs
    removed_methods: tuple
    removed_params: tuple

    def covers_breaking(self, b: Breaking) -> bool:
        if b.kind == "removed method":
            return _matches(b.method, self.removed_methods)
        if b.kind == "removed param":
            return any(f"`{p}`" in b.detail for p in self.removed_params)
        return False

    def covers_move(self, m: Moved) -> bool:
        return any(m.old.startswith(old) and m.new == new + m.old[len(old):]
                   for old, new in self.moved)


@dataclass
class PossibleAdditions:
    breaking: list
    moved: list
    wire: list  # methods with wire changes: a guide never lists these


GUIDES = {
    "v3": Guide(
        name="v3 upgrade guide",
        url="https://github.com/elevenlabs/elevenlabs-python/wiki/v3-upgrade-guide",
        moved=(("conversational_ai.", "agents."),),
        removed_methods=(
            "voices.get_all", "text_to_voice.create_previews", "usage.get",
            "dubbing.resource.", "dubbing.transcript.",
            "conversational_ai.add_to_knowledge_base", "conversational_ai.knowledge_base.",
            "conversational_ai.agents.simulate_conversation",
            "conversational_ai.agents.simulate_conversation_stream",
        ),
        removed_params=("cloud_storage_url",),
    ),
}


def possible_additions(ch: Changes, guide: Guide) -> PossibleAdditions:
    """Changes the guide does not mention."""
    return PossibleAdditions(
        breaking=[b for b in ch.breaking if not guide.covers_breaking(b)],
        moved=[m for m in ch.moved if not guide.covers_move(m)],
        wire=sorted({w.method for w in ch.wire}),
    )
