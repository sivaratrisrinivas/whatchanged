from whatchanged.diff import Breaking, Changes, Moved
from whatchanged.guides import GUIDES, possible_additions


def test_only_changes_the_guide_does_not_mention_are_possible_additions():
    ch = Changes("1", "2")
    ch.breaking = [
        Breaking("voices.get_all", "removed method", ""),        # documented
        Breaking("dubbing.resource.get", "removed method", ""),  # documented (prefix)
        Breaking("flows.templates.get", "removed method", ""),   # not documented
        Breaking("x.y", "removed param", "`cloud_storage_url` was removed"),
        Breaking("x.y", "removed param", "`limit` was removed"),
    ]
    ch.moved = [Moved("conversational_ai.tools.create", "agents.tools.create"),
                Moved("foo.bar", "baz.bar")]
    pa = possible_additions(ch, GUIDES["v3"])
    assert [b.method for b in pa.breaking] == ["flows.templates.get", "x.y"]
    assert [m.old for m in pa.moved] == ["foo.bar"]
