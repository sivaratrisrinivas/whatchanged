"""Properties of real capture snapshots (cached after the first run; needs network once)."""
import json
from pathlib import Path

import pytest

from whatchanged.envs import DEFAULT_CACHE, snapshot


@pytest.fixture(scope="module")
def snap():
    return snapshot("2.59.0", Path(DEFAULT_CACHE))


def test_json_bodies_are_stored_key_sorted(snap):
    bodies = [w["request"]["body"] for m in snap["methods"].values() for w in m["wire"].values()
              if w.get("request") and w["request"]["content_type"] == "application/json"]
    assert bodies
    assert all(json.dumps(b) == json.dumps(b, sort_keys=True) for b in bodies)


def test_dict_of_any_is_synthesized_as_k_v(snap):
    call = snap["methods"]["conversational_ai.agents.branches.create"]["wire"]["conversation_config"]["call"]
    assert "conversation_config={'k': 'v'}" in call


def test_every_union_member_gets_a_call_or_a_recorded_skip(snap):
    # the labels param is Union[Dict[str, str], str]: one call per member, none dropped silently
    wire = snap["methods"]["voices.update"]["wire"]
    assert {"labels=dict", "labels=str"} <= set(wire)
