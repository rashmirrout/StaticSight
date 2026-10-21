#!/usr/bin/env python3
"""Evaluate StaticSight on planted-bug tasks: does the evidence reach the answer, at what token cost?

    python3 scripts/eval_agent.py                          # static mode on the test repository (no agent needed)
    python3 scripts/eval_agent.py --json eval.json         # also write the raw results
    python3 scripts/eval_agent.py \\
        --agent-cmd    'copilot -p {prompt} --allow-all-tools' \\
        --baseline-cmd 'copilot -p {prompt} --allow-all-tools --disable-mcp-server staticsight'

Static mode (always): for every task in shared/eval/tasks.json it runs the StaticSight calls a well-behaved agent
would make, and checks that the output contains the evidence a correct answer needs (the file, the line within ±3,
and a keyword such as "leak" or "deadlock"). It compares the tokens of that output with the tokens of the files an
assistant without StaticSight would have to read to find the same thing.

Agent mode (optional): `--agent-cmd` and `--baseline-cmd` are shell command templates for any coding agent CLI.
`{prompt}` is replaced by the (shell-quoted) question and `{repo}` by the repository folder; the command runs inside
the repository. Each answer is graded with the same rule. Run your agent with StaticSight configured for
`--agent-cmd` and without it for `--baseline-cmd`. Agent answers vary between runs: use `--repeat N`.

`--repo` and `--tasks` evaluate your own repository with your own tasks (same JSON format). Without them, a fresh
copy of the test repository is built in a temporary folder.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "staticsight-py" / "src"))
sys.path.insert(0, str(HERE / "shared" / "fixtures"))
sys.path.insert(0, str(HERE / "scripts"))

from benchmark import counter, logging_off, pct  # noqa: E402

WINDOW = 6


def found(text: str, expect: dict) -> bool:
    """True when some window of lines names the file, a line within ±3 of the expected one, and a keyword."""
    path = expect["file"]
    base = path.rsplit("/", 1)[-1]
    want = int(expect.get("line", 0))
    words = [w.lower() for w in expect.get("any", [])]
    lines = text.splitlines()
    for i in range(len(lines)):
        win = "\n".join(lines[i:i + WINDOW])
        low = win.lower()
        if base not in win or (words and not any(w in low for w in words)):
            continue
        if not want:
            return True
        nums = [int(n) for n in re.findall(rf"{re.escape(base)}`?\s*(?::|\(|,)?\s*(?:L|line\s+)?(\d+)", win)]
        nums += [int(n) for n in re.findall(r"\*\*L(\d+)\*\*|\[L(\d+)\]|\bL(\d+)\b|\bline\s+(\d+)", win) for n in n if n]
        if any(abs(n - want) <= 3 for n in nums):
            return True
    return False


async def static_eval(repo: Path, tasks: list[dict], count) -> list[dict]:
    from staticsight.server import TOOLS, safe_tool
    from staticsight.toolrun import _prepare

    fns = {f.__name__: safe_tool(f) for f in TOOLS}
    results = []
    for t in tasks:
        outs, t0 = [], time.perf_counter()
        for name, args in t["calls"]:
            await _prepare(name)
            outs.append(await fns[name](**args))
        text = "\n\n".join(outs)
        read = ""
        for rel in t.get("read", []):
            try:
                read += (repo / rel).read_text(encoding="utf-8", errors="replace") + "\n"
            except OSError:
                pass
        results.append({"id": t["id"], "question": t["question"], "evidence": found(text, t["expect"]),
                        "tokens": count(text), "read_tokens": count(read), "calls": len(t["calls"]),
                        "seconds": round(time.perf_counter() - t0, 2)})
    return results


def agent_eval(template: str, repo: Path, tasks: list[dict], repeat: int, timeout: int) -> dict[str, float]:
    scores: dict[str, float] = {}
    for t in tasks:
        ok = 0
        for _ in range(repeat):
            cmd = template.replace("{prompt}", shlex.quote(t["question"])).replace("{repo}", shlex.quote(str(repo)))
            try:
                out = subprocess.run(cmd, shell=True, cwd=repo, capture_output=True, text=True, errors="replace",
                                     timeout=timeout).stdout
            except subprocess.TimeoutExpired:
                out = ""
            ok += found(out, t["expect"])
        scores[t["id"]] = ok / repeat
        say(f"{t['id']}: {ok}/{repeat}")
    return scores


def render(static: list[dict], agent: dict | None, baseline: dict | None, tokenizer: str) -> str:
    head = "| Task | Evidence in StaticSight output | StaticSight tokens | Tokens to read the files | Change |"
    sep = "|---|---|---|---|---|"
    if agent is not None:
        head += " Agent + StaticSight |"
        sep += "---|"
    if baseline is not None:
        head += " Agent alone |"
        sep += "---|"
    rows = [head, sep]
    for r in static:
        row = (f"| `{r['id']}` | {'✅' if r['evidence'] else '❌'} | {r['tokens']:,} | {r['read_tokens']:,} | "
               f"{pct(r['tokens'], r['read_tokens'])} |")
        if agent is not None:
            row += f" {agent.get(r['id'], 0):.0%} |"
        if baseline is not None:
            row += f" {baseline.get(r['id'], 0):.0%} |"
        rows.append(row)
    hits = sum(r["evidence"] for r in static)
    tot, rd = sum(r["tokens"] for r in static), sum(r["read_tokens"] for r in static)
    rows.append("")
    rows.append(f"**Evidence found:** {hits} of {len(static)} tasks · **tokens:** {tot:,} with StaticSight vs {rd:,} "
                f"to read the files ({pct(tot, rd)}) · tokenizer: {tokenizer}.")
    if agent is not None:
        rows.append(f"**Agent + StaticSight:** {sum(agent.values()) / max(len(agent), 1):.0%} of answers correct.")
    if baseline is not None:
        rows.append(f"**Agent alone:** {sum(baseline.values()) / max(len(baseline), 1):.0%} of answers correct.")
    rows.append("\n_\"Tokens to read the files\" is a lower bound for an assistant without StaticSight: it must also find "
                "those files, and on a large repository it rarely reads all of them._")
    return "\n".join(rows)


def say(msg: str) -> None:
    print(f"  … {msg}", file=sys.stderr, flush=True)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default="", help="repository to evaluate (default: a fresh copy of the test repository)")
    ap.add_argument("--tasks", default=str(HERE / "shared" / "eval" / "tasks.json"), help="tasks JSON file")
    ap.add_argument("--only", default="", help="comma-separated task ids to run")
    ap.add_argument("--agent-cmd", default="", help="agent command template with StaticSight ({prompt}, {repo})")
    ap.add_argument("--baseline-cmd", default="", help="the same agent without StaticSight")
    ap.add_argument("--repeat", type=int, default=1, help="agent runs per task (answers vary; default 1)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per agent run (default 600)")
    ap.add_argument("--json", default="", help="also write the raw results to this file")
    args = ap.parse_args()

    tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))["tasks"]
    if args.only:
        keep = {x.strip() for x in args.only.split(",")}
        tasks = [t for t in tasks if t["id"] in keep]
    tmp = None
    if args.repo:
        repo = Path(args.repo).resolve()
        os.environ["STATICSIGHT_DATA_DIR"] = "cache"  # read-only for the evaluated repository
    else:
        import make_fixture

        tmp = tempfile.TemporaryDirectory(prefix="staticsight-eval-")
        repo = make_fixture.build(Path(tmp.name) / "cpp-sample")
        say(f"test repository built in {repo}")
    os.environ["WORKSPACE_ROOT"] = str(repo)
    logging_off()
    count, tokenizer = counter()
    try:
        static = await static_eval(repo, tasks, count)
        agent = agent_eval(args.agent_cmd, repo, tasks, args.repeat, args.timeout) if args.agent_cmd else None
        base = agent_eval(args.baseline_cmd, repo, tasks, args.repeat, args.timeout) if args.baseline_cmd else None
    finally:
        if tmp is not None:
            tmp.cleanup()
    print(render(static, agent, base, tokenizer))
    if args.json:
        Path(args.json).write_text(json.dumps({"tokenizer": tokenizer, "static": static, "agent": agent,
                                               "baseline": base}, indent=2), encoding="utf-8")
    return 0 if all(r["evidence"] for r in static) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
