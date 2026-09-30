#!/usr/bin/env python3
"""Run the skill on a fixture with any agent, then grade the result.

    python evals/run.py --case type2 --agent oracle
    python evals/run.py --case type2 --agent 'claude -p --permission-mode bypassPermissions {prompt}'
    python evals/run.py --case type2 --agent 'codex exec --full-auto {prompt}'
    python evals/run.py --case type2 --agent 'gemini --yolo -p {prompt}'

`{prompt}` is replaced by the task prompt as a single argument. The agent runs
with the run folder as its working directory and never sees truth.json.
`--agent oracle` fills workpapers from the known answers: a fast, model-free
regression test for the scripts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "soc2-audit"
sys.path.insert(0, str(HERE))

from graders import grade, print_grade  # noqa: E402

PROMPT = """You are the engagement team for a SOC 2 Type {type} examination.
The engagement folder is {engagement}. Read {skill}/SKILL.md first and follow it.
Use `{python}` to run the skill's scripts; its dependencies are installed.
Work until `soc2.py status` reports that the draft report and review packet are ready for partner review.
The engagement partner will review later; do not ask questions, and never run signoff."""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--case", default="type2", help="fixture name under evals/fixtures")
    p.add_argument("--agent", required=True, help="'oracle' or a command template containing {prompt}")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--timeout", type=int, default=4 * 3600, help="seconds per run")
    a = p.parse_args()

    fixture = HERE / "fixtures" / a.case
    if not fixture.exists():
        sys.exit(f"No fixture {fixture}. Run: python evals/make_fixture.py")
    truth = json.loads((fixture / "truth.json").read_text())
    scores = []
    for i in range(a.runs):
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        run = HERE / "runs" / f"{stamp}-{a.case}-{i + 1}"
        shutil.copytree(fixture, run, ignore=shutil.ignore_patterns("truth.json"))
        print(f"run {i + 1}: {run}")
        if a.agent == "oracle":
            _oracle(run, fixture / "truth.json")
        else:
            prompt = PROMPT.format(type=truth["report_type"], engagement=run, skill=SKILL, python=sys.executable)
            cmd = [prompt if tok == "{prompt}" else tok for tok in shlex.split(a.agent)]
            if prompt not in cmd:
                sys.exit("--agent must contain {prompt} as a separate argument")
            with open(run / "agent.log", "w") as log:
                subprocess.run(cmd, cwd=run, stdout=log, stderr=subprocess.STDOUT, timeout=a.timeout)
        g = grade(run, truth)
        (run / "grade.json").write_text(json.dumps(g, indent=2) + "\n")
        print_grade(g)
        scores.append(g["score"])
    if len(scores) > 1:
        print(f"mean score {sum(scores) / len(scores):.3f} over {len(scores)} runs")
    return 0


def _oracle(run: Path, truth_path: Path) -> None:
    soc2 = [sys.executable, str(SKILL / "scripts" / "soc2.py")]
    for step in ("ingest", "check", "plan", "sample"):
        subprocess.run(soc2 + [step, str(run)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, str(HERE / "oracle.py"), str(run), str(truth_path)], check=True, stdout=subprocess.DEVNULL)
    for step in ("render", "packet"):
        subprocess.run(soc2 + [step, str(run)], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    sys.exit(main())
