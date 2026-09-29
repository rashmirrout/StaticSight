#!/usr/bin/env python3
"""Measure what StaticSight changes on YOUR repository: tokens, precision and depth, versus plain text search.

    python3 scripts/benchmark.py                        # the repository around the current folder
    python3 scripts/benchmark.py --repo /path/to/repo --base HEAD~3 --samples 20 --json results.json

Read-only for the measured repository: indexes go to the per-user cache (STATICSIGHT_DATA_DIR=cache) unless
--in-repo is given. Sampling uses a fixed seed, so two runs on the same commit give the same table.

Tokens are counted with tiktoken's o200k_base encoding when `tiktoken` is installed (pip install tiktoken), otherwise
estimated as characters / 4; the output says which. "Text search" means `rg -w NAME` over C/C++ files, the kind of
search an assistant (or a human) does without StaticSight.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "staticsight-py" / "src"))

CPP_GLOB = "*.{c,cc,cpp,cxx,h,hh,hpp,hxx}"


def counter():
    try:
        import tiktoken

        enc = tiktoken.get_encoding("o200k_base")
        return (lambda s: len(enc.encode(s, disallowed_special=()))), "tiktoken o200k_base"
    except Exception:  # not installed, or no network to fetch the encoding
        return (lambda s: (len(s) + 3) // 4), "estimate (characters / 4; pip install tiktoken for exact counts)"


def med(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0


def pct(part: float, whole: float) -> str:
    """'−92%' when StaticSight's answer is smaller, '+329%' when it is larger (tiny diffs: the bundle adds context)."""
    if not whole:
        return "n/a"
    change = 100 * (part / whole - 1)
    return f"−{-change:.0f}%" if change < 0 else f"+{change:.0f}%"


def pl(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def run(cmd: list[str], cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace").stdout


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default="", help="repository to measure (default: the one around the current folder)")
    ap.add_argument("--base", default="HEAD~1", help="diff base for the review measurement (default HEAD~1)")
    ap.add_argument("--samples", type=int, default=20, help="functions/symbols sampled per measurement (default 20)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", default="", help="also write the raw numbers to this file")
    ap.add_argument("--in-repo", action="store_true", help="keep indexes in <repo>/.staticsight instead of the cache")
    args = ap.parse_args()

    from staticsight.config import find_repo_root

    repo = Path(args.repo).resolve() if args.repo else find_repo_root(Path.cwd())
    os.environ["WORKSPACE_ROOT"] = str(repo)
    if not args.in_repo:
        os.environ["STATICSIGHT_DATA_DIR"] = "cache"
    os.environ.setdefault("STATICSIGHT_MAX_RESULTS", "15")
    logging_off()

    from staticsight.config import load_config
    from staticsight.indexer import get_indexer
    from staticsight.server import safe_tool
    from staticsight.tools.graph_gtags import get_upstream_callers
    from staticsight.tools.lock_order import analyse, find_cycles
    from staticsight.tools.review import review_changes
    from staticsight.tools.ripgrep_mem import get_include_blast_radius, track_struct_risks
    from staticsight.tools.state_mutation import track_state_mutations
    from staticsight.tools.syntax_ctags import get_branch_skeleton

    T, tokenizer = counter()
    rnd = random.Random(args.seed)
    cfg = load_config()
    res: dict = {"repo_files": 0, "tokenizer": tokenizer}
    files = [f for f in run(["git", "ls-files", "*.c", "*.cc", "*.cpp", "*.cxx", "*.h", "*.hh", "*.hpp", "*.hxx"], repo).split("\n") if f]
    res["repo_files"] = len(files)
    say(f"StaticSight benchmark: {len(files)} C/C++ files; tokens: {tokenizer}")
    t = time.time()
    await get_indexer(cfg).start()
    res["index_seconds"] = round(time.time() - t, 1)

    # 1. review bundle versus reading the changed files
    say("1/6 review bundle …")
    changed = [f for f in run(["git", "diff", "--name-only", args.base, "--", *[f"*{e}" for e in (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx")]], repo).split("\n") if f and (repo / f).is_file()]
    if changed:
        t = time.time()
        bundle = await safe_tool(review_changes)(base_ref=args.base)
        secs = time.time() - t
        full = sum(T((repo / f).read_text(errors="replace")) for f in changed)
        diff = T(run(["git", "diff", args.base, "--", *changed], repo))
        res["review"] = {"base": args.base, "files": len(changed), "bundle_tokens": T(bundle), "changed_files_tokens": full,
                         "diff_tokens": diff, "seconds": round(secs, 1)}
    # 2. skeletons versus bodies and files
    say("2/6 function skeletons …")
    funcs = []
    srcs = [f for f in files if f.endswith((".c", ".cc", ".cpp", ".cxx"))]
    for i in range(0, len(srcs), 200):
        out = run(["ctags", "--output-format=json", "--fields=+ne", "--kinds-C++=f", "--language-force=C++", "-f", "-", *srcs[i:i + 200]], repo)
        for line in out.splitlines():
            try:
                tg = json.loads(line)
            except ValueError:
                continue
            if tg.get("kind") == "function" and tg.get("end") and tg["end"] - tg["line"] >= 40:
                funcs.append((tg["path"], tg["line"], tg["end"], tg["name"]))
    sk = safe_tool(get_branch_skeleton)
    rows = []
    for path, a, b, _ in rnd.sample(funcs, min(args.samples, len(funcs))):
        text = (repo / path).read_text(errors="replace")
        lines = text.splitlines()
        t = time.time()
        out = await sk(file_path=path, start_line=a)
        rows.append({"body": T("\n".join(lines[a - 1:b])), "file": T(text), "skeleton": T(out), "ms": (time.time() - t) * 1000})
    if rows:
        res["skeleton"] = {"n": len(rows), **{k: med([r[k] for r in rows]) for k in ("body", "file", "skeleton", "ms")}}
    # 3. callers versus text search
    say("3/6 callers …")
    names = sorted({n for _, _, _, n in funcs if len(n) > 5 and not n.startswith("~") and "::" not in n})
    rnd.shuffle(names)
    cal = safe_tool(get_upstream_callers)
    crow = []
    for n in names:
        grep = run(["rg", "-n", "-w", "--no-heading", "-g", CPP_GLOB, n], repo)
        hits = grep.count("\n")
        if not 5 <= hits <= 150:
            continue
        t = time.time()
        out = await cal(symbol=n)
        m = re.search(r"Found (\d+) call site", out)
        crow.append({"grep_lines": hits, "grep_tokens": T(grep), "sites": int(m.group(1)) if m else 0, "tool_tokens": T(out),
                     "ignored": out.count("result ignored"), "ms": (time.time() - t) * 1000})
        if len(crow) >= args.samples:
            break
    if crow:
        res["callers"] = {"n": len(crow), "grep_lines": sum(r["grep_lines"] for r in crow), "call_sites": sum(r["sites"] for r in crow),
                          "ignored_results": sum(r["ignored"] for r in crow), "grep_tokens": med([r["grep_tokens"] for r in crow]),
                          "tool_tokens": med([r["tool_tokens"] for r in crow]), "ms": med([r["ms"] for r in crow])}
    # 4. header blast radius: direct (what a text search finds) versus transitive
    say("4/6 header blast radius …")
    headers = [f for f in files if f.endswith((".h", ".hh", ".hpp", ".hxx"))]
    rnd.shuffle(headers)
    br = safe_tool(get_include_blast_radius)
    brow = []
    for h in headers:
        out = await br(header_filename=h, transitive_depth=3)
        m = re.search(r"\*\*Direct includers:\*\* (\d+) files?; \*\*transitive:\*\* (\d+) more", out)
        if not m or int(m.group(1)) == 0 or "matches several headers" in out:
            continue  # skip bare names shared by several headers (e.g. every project's stdafx.h): counts would mix them
        tu = re.search(r"Translation units affected:\*\* (\d+) of (\d+)", out)
        brow.append({"header": h, "direct": int(m.group(1)), "transitive": int(m.group(2)), "tus": int(tu.group(1)) if tu else 0})
        if len(brow) >= args.samples:
            break
    if brow:
        res["blast"] = {"n": len(brow), "direct": med([r["direct"] for r in brow]), "transitive": med([r["transitive"] for r in brow]),
                        "headers_with_hidden_reach": sum(1 for r in brow if r["transitive"] > 0), "rows": brow}
    # 5. struct layout risks versus every mention
    say("5/6 struct layout risks …")
    out = run(["ctags", "--output-format=json", "--kinds-C++=s", "--language-force=C++", "-f", "-", *headers[:1500]], repo)
    structs = sorted({json.loads(l)["name"] for l in out.splitlines() if l.startswith("{") and '"name"' in l} - {""})
    structs = [s for s in structs if not s.startswith("__anon")]
    rnd.shuffle(structs)
    tr = safe_tool(track_struct_risks)
    srow = []
    for s in structs:
        grep = run(["rg", "-n", "-w", "--no-heading", "-g", CPP_GLOB, s], repo)
        hits = grep.count("\n")
        if not 10 <= hits <= 400:
            continue
        out = await tr(struct_name=s)
        m = re.search(r"may break (\d+) sites", out)
        srow.append({"refs": hits, "risky": int(m.group(1)) if m else 0, "nearby": out.count("(operation within ±2 lines)")})
        if len(srow) >= max(5, args.samples // 2):
            break
    if srow:
        res["structs"] = {"n": len(srow), "references": sum(r["refs"] for r in srow), "risky_sites": sum(r["risky"] for r in srow),
                          "found_on_neighbouring_line": sum(r["nearby"] for r in srow)}
    # 6. locking: lock order + inconsistent locking of members of classes that lock
    say("6/6 locking …")
    t = time.time()
    fns, edges, blocking, selfre = await analyse(cfg)
    res["locks"] = {"functions_taking_locks": sum(1 for f in fns if f.acquired), "locks": len({k for f in fns for k in f.acquired}),
                    "order_pairs": len({(e.first, e.second) for e in edges}), "cycles": len(find_cycles(edges)),
                    "same_lock_twice": len(set(selfre)), "held_across_blocking": len({(p, n) for p, _, n, _, _ in blocking}),
                    "seconds": round(time.time() - t, 1)}
    members = sorted({k.rsplit("::", 1)[-1] for f in fns for k in f.acquired if "::" in k})
    locking_classes = sorted({f.cls for f in fns if f.acquired and f.cls})
    tm = safe_tool(track_state_mutations)
    cands = []
    for p in sorted({f.path for f in fns if f.acquired})[:200]:
        out = run(["ctags", "--output-format=json", "--kinds-C++=m", "--language-force=C++", "-f", "-", p], repo)
        for l in out.splitlines():
            try:
                tg = json.loads(l)
            except ValueError:
                continue
            if tg.get("scope", "").rsplit("::", 1)[-1] in locking_classes and tg["name"] not in members:
                cands.append(tg["name"])
    cands = sorted(set(cands))
    rnd.shuffle(cands)
    flagged: list[str] = []
    checked = 0
    for name in cands[: args.samples]:
        checked += 1
        if "Inconsistent locking" in await tm(symbol=name):
            flagged.append(name)
    res["locks"].update({"members_checked": checked, "members_inconsistently_locked": len(flagged),
                         "examples": {"inconsistently_locked": flagged,
                                      "same_lock_twice": sorted({f"{p}:{n}" for p, _, n, _, _ in selfre}),
                                      "held_across_blocking": sorted({f"{p}:{n} {c}()" for p, _, n, c, _ in blocking})}})

    report = render(res)
    print(report)
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    return 0


def render(r: dict) -> str:
    out = [f"## StaticSight benchmark ({r['repo_files']} C/C++ files)", "", f"_Tokens: {r['tokenizer']}. GNU Global index: {r['index_seconds']} s._", "",
           "| Measurement | Without StaticSight | With StaticSight |", "|---|---|---|"]
    if "review" in r:
        v = r["review"]
        out.append(f"| Review `{v['base']}` ({v['files']} C/C++ files) | {v['changed_files_tokens']:,} tokens to read the changed files "
                   f"({v['diff_tokens']:,} for the raw diff) | **{v['bundle_tokens']:,}-token review bundle** "
                   f"({pct(v['bundle_tokens'], v['changed_files_tokens'])}), {v['seconds']} s |")
    if "skeleton" in r:
        v = r["skeleton"]
        out.append(f"| Logic of one function ({v['n']} functions ≥ 40 lines) | median {v['body']:,.0f} tokens (body), {v['file']:,.0f} (file) | "
                   f"**median {v['skeleton']:,.0f}-token skeleton** ({pct(v['skeleton'], v['body'])} vs body, "
                   f"{pct(v['skeleton'], v['file'])} vs file), {v['ms']:.0f} ms |")
    if "callers" in r:
        v = r["callers"]
        noise = 100 * (1 - v["call_sites"] / v["grep_lines"]) if v["grep_lines"] else 0
        out.append(f"| Who calls it? ({v['n']} functions) | {v['grep_lines']} text-search lines, **{noise:.0f}% not calls** | "
                   f"**{v['call_sites']} call sites** with caller; {v['ignored_results']} flagged as ignoring the result; median {v['ms']:.0f} ms |")
    if "blast" in r:
        v = r["blast"]
        out.append(f"| Header change reach ({pl(v['n'], 'header')}) | median {v['direct']:.0f} direct `#include` lines | **median +{v['transitive']:.0f} "
                   f"more files through other headers**; {v['headers_with_hidden_reach']} of {v['n']} reach further than a text search shows |")
    if "structs" in r:
        v = r["structs"]
        out.append(f"| Struct layout change ({pl(v['n'], 'struct')}) | {v['references']} references to read | **{v['risky_sites']} sites where the "
                   f"bytes matter** ({v['found_on_neighbouring_line']} with the operation on a neighbouring line) |")
    v = r["locks"]
    out.append(f"| Locking ({v['functions_taking_locks']} functions take {v['locks']} locks) | no answer from text search | "
               f"**{pl(v['order_pairs'], 'lock-order pair')}, {pl(v['cycles'], 'potential deadlock cycle')}, "
               f"{v['same_lock_twice']} same-lock-twice, {v['held_across_blocking']} held across blocking calls**; {v['members_inconsistently_locked']} of "
               f"{v['members_checked']} sampled members accessed both with and without a lock (candidates to review); {v['seconds']} s |")
    out += ["", "_Findings are leads with `file:line`: verify them before asserting. Heuristic analyses say so in their output._"]
    return "\n".join(out)


def say(msg: str) -> None:
    print(f"  … {msg}", file=sys.stderr, flush=True)


def logging_off() -> None:
    import logging

    logging.getLogger("staticsight").setLevel(logging.WARNING)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
