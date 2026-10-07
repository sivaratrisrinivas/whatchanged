"""Acceptance test: whatchanged 2.54.0 2.59.0 must surface the voices.update `labels` wire change."""
import re

import pytest

from whatchanged.cli import main


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    out = tmp_path_factory.mktemp("rep") / "r.md"
    assert main(["2.54.0", "2.59.0", "-o", str(out)]) == 0
    return out.read_text()


def section(report: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}.*?$(.*?)(?=^## |\Z)", report, re.S | re.M)
    assert m, f"no section {title!r}"
    return m.group(1)


def test_wire_section_comes_first(report):
    assert re.findall(r"^## (.+)$", report, re.M)[0].startswith("Wire behavior changed")


def test_voices_update_labels_before_after_bytes(report):
    wire = section(report, "Wire behavior changed")
    assert "voices.update" in wire
    assert "labels" in wire
    assert '{"k": "v"}' in wire  # 2.54.0: sent as-is
    assert '"{\\"k\\": \\"v\\"}"' in wire  # 2.59.0: JSON-encoded again


def test_alias_rename_is_not_a_type_change(report):
    types = section(report, "Type changed")
    assert "voices.update" not in types
    assert "EditVoiceRequestLabels" not in report.split("## Added")[0].split("## Type changed")[-1]
