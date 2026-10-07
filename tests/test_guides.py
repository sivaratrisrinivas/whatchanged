from whatchanged.diff import Changes
from whatchanged.guides import GUIDES, possible_additions


def test_only_changes_the_guide_does_not_mention_are_possible_additions():
    ch = Changes("1", "2")
    ch.breaking = [
        {"method": "voices.get_all", "kind": "removed method", "detail": ""},        # documented
        {"method": "dubbing.resource.get", "kind": "removed method", "detail": ""},  # documented (prefix)
        {"method": "flows.templates.get", "kind": "removed method", "detail": ""},   # not documented
        {"method": "x.y", "kind": "removed param", "detail": "`cloud_storage_url` was removed"},
        {"method": "x.y", "kind": "removed param", "detail": "`limit` was removed"},
    ]
    ch.moved = [{"old": "conversational_ai.tools.create", "new": "agents.tools.create"},
                {"old": "foo.bar", "new": "baz.bar"}]
    pa = possible_additions(ch, GUIDES["v3"])
    assert [b["method"] for b in pa["breaking"]] == ["flows.templates.get", "x.y"]
    assert [m["old"] for m in pa["moved"]] == ["foo.bar"]
