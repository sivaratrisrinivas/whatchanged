from whatchanged.diff import Changes, Incomparable, Skipped
from whatchanged.report import render


def test_skipped_count_covers_synthesis_skips_only_and_lists_uncompared_separately():
    ch = Changes("1", "2")
    ch.skipped = {"1": [Skipped("m", "*", "cannot synthesize")], "2": []}
    ch.incomparable = [Incomparable("n", "s", "s='a'", "s='b'"), Incomparable("n", "t", "t=1", "t=2")]
    md = render(ch)
    assert "## Skipped (1)" in md
    assert "1 variants skipped, 2 not compared" in md
    assert "Inputs differ between versions" in md


def test_sections_come_in_the_briefs_order():
    headings = [h[3:].split(" (")[0] for h in render(Changes("1", "2")).splitlines() if h.startswith("## ")]
    assert headings == ["Wire behavior changed", "Breaking", "Moved", "Type changed", "Added", "Skipped"]
