"""Simulates action.yml and examples/whatchanged.yml locally, without GitHub.

The shell and JavaScript are extracted from the YAML files and run for real; only the
`${{ }}` expressions and the GitHub API (a recording stub) are faked.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
ACTION = yaml.safe_load((ROOT / "action.yml").read_text())
STEPS = {s["name"]: s for s in ACTION["runs"]["steps"] if "name" in s}


def expand(text: str, ctx: dict) -> str:
    return re.sub(r"\$\{\{\s*([\w.\-]+)\s*\}\}", lambda m: ctx[m.group(1)], text)


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    """Run the action's install and report steps in a clean venv, as a runner would."""
    tmp = tmp_path_factory.mktemp("runner")
    venv = tmp / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    env = {**os.environ, "PATH": f"{venv / 'bin'}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp),
           "GITHUB_OUTPUT": str(tmp / "output"), "GITHUB_STEP_SUMMARY": str(tmp / "summary")}
    ctx = {"github.action_path": str(ROOT), "inputs.from": "2.54.0", "inputs.to": "2.59.0",
           "inputs.guide": "", "steps.run.outputs.report": ""}

    install = expand(STEPS["Install whatchanged"]["run"], ctx)
    subprocess.run(["bash", "-e", "-c", install], env=env, check=True, capture_output=True, cwd=tmp)

    step = STEPS["Generate report"]
    env.update({k: expand(v, ctx) for k, v in step["env"].items()})
    done = subprocess.run(["bash", "-e", "-c", step["run"]], env=env, capture_output=True, text=True, cwd=tmp)
    assert done.returncode == 0, done.stderr
    return tmp


def test_report_step_writes_report_output_and_job_summary(generated):
    out = dict(line.split("=", 1) for line in (generated / "output").read_text().split("\n") if line)
    report = Path(out["report"]).read_text()
    assert "voices.update" in report and "## Wire behavior changed" in report
    assert (generated / "summary").read_text() == report
    assert (generated / "whatchanged-cache" / "env" / "2.59.0").is_dir()  # cache stays out of the repo


def test_report_step_passes_guide_flag_when_set(tmp_path):
    script = STEPS["Generate report"]["run"]
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "whatchanged").write_text('#!/bin/sh\necho "$@" > "$RUNNER_TEMP/args"\necho x > "$4"\n')
    (fake / "whatchanged").chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path),
           "GITHUB_OUTPUT": str(tmp_path / "o"), "GITHUB_STEP_SUMMARY": str(tmp_path / "s"),
           "FROM": "2.71.0", "TO": "3.0.0a1", "GUIDE": "v3"}
    subprocess.run(["bash", "-e", "-c", script], env=env, check=True)
    assert (tmp_path / "args").read_text().split()[:2] == ["2.71.0", "3.0.0a1"]
    assert "--guide v3" in (tmp_path / "args").read_text()


HARNESS = """
const fs = require('fs');
const calls = [];
const existing = JSON.parse(process.env.EXISTING);
const github = {
  paginate: async () => existing,
  rest: {issues: {
    listComments: {},
    createComment: async (a) => calls.push(['create', a]),
    updateComment: async (a) => calls.push(['update', a]),
  }},
};
const context = {repo: {owner: 'o', repo: 'r'}, issue: {number: 7}};
(async () => {
%s
fs.writeFileSync(process.env.CALLS, JSON.stringify(calls));
})();
"""


def run_comment_step(tmp_path, report: str, existing: list):
    step = STEPS["Comment on PR"]
    (tmp_path / "report.md").write_text(report)
    (tmp_path / "h.js").write_text(HARNESS % step["with"]["script"])
    env = {**os.environ, "REPORT": str(tmp_path / "report.md"), "EXISTING": json.dumps(existing),
           "CALLS": str(tmp_path / "calls.json")}
    done = subprocess.run(["node", str(tmp_path / "h.js")], env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads((tmp_path / "calls.json").read_text())


def test_first_run_creates_one_marked_comment(tmp_path):
    (kind, args), = run_comment_step(tmp_path, "# report\n", [{"id": 1, "body": "unrelated"}])
    assert kind == "create"
    assert (args["owner"], args["repo"], args["issue_number"]) == ("o", "r", 7)
    assert args["body"].startswith("<!-- whatchanged -->\n# report")


def test_rerun_updates_the_existing_comment_instead_of_adding_another(tmp_path):
    (kind, args), = run_comment_step(
        tmp_path, "# new\n", [{"id": 1, "body": "x"}, {"id": 42, "body": "<!-- whatchanged -->\nold"}])
    assert kind == "update" and args["comment_id"] == 42 and "# new" in args["body"]


def test_oversized_report_is_truncated_under_githubs_comment_limit(tmp_path):
    (kind, args), = run_comment_step(tmp_path, "x" * 100_000, [])
    assert len(args["body"]) < 65536 and "truncated" in args["body"]


def test_comment_step_only_runs_for_pull_requests_when_enabled():
    cond = STEPS["Comment on PR"]["if"]
    assert "inputs.comment == 'true'" in cond and "pull_request" in cond


def test_example_workflow_reads_base_and_pr_versions(tmp_path):
    wf = yaml.safe_load((ROOT / "examples" / "whatchanged.yml").read_text())
    step = next(s for s in wf["jobs"]["report"]["steps"] if s.get("id") == "v")
    git = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)  # noqa: E731
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (tmp_path / "requirements.txt").write_text("httpx\nelevenlabs==2.54.0\n")
    git("add", ".")
    git("commit", "-qm", "base")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    (tmp_path / "requirements.txt").write_text("httpx\nelevenlabs>=2.59.0\n")
    env = {**os.environ, "GITHUB_OUTPUT": str(tmp_path / "out")}
    run = expand(step["run"], {"github.base_ref": "main"})
    subprocess.run(["bash", "-e", "-c", run], cwd=tmp_path, env=env, check=True)
    assert (tmp_path / "out").read_text().split() == ["from=2.54.0", "to=2.59.0"]
