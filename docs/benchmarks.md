<!-- nav:top -->
📚 [Documentation](README.md) › **Benchmarks**
<!-- /nav:top -->

# Benchmarks you can reproduce

Every number in the README's "Why StaticSight" section comes from `scripts/benchmark.py`. This page explains what it
measures, how, and what the results on two repositories were. Run it on your own code: that is the real test.

<!-- nav:toc -->
**On this page:** [Run it](#run-it) · [What it measures](#what-it-measures) · [Results](#results) · [Evaluate an agent on planted bugs](#evaluate-an-agent-on-planted-bugs) · [Honest reading of these numbers](#honest-reading-of-these-numbers)
<!-- /nav:toc -->

## Run it

🐧 Linux · macOS:

```text
cd /path/to/your/cpp/repo
python3 $SS_HOME/scripts/benchmark.py                       # review measurement against HEAD~1
python3 $SS_HOME/scripts/benchmark.py --base HEAD~3 --samples 20 --json results.json
```

🪟 Windows:

```powershell
cd C:\path\to\your\cpp\repo
py -3 "$env:SS_HOME\scripts\benchmark.py" --base HEAD~3 --samples 20
```

| Option | Meaning |
|---|---|
| `--repo PATH` | Repository to measure (default: the one around the current folder). |
| `--base REF` | Diff base for the review measurement (default `HEAD~1`). |
| `--samples N` | Functions, symbols and headers sampled per measurement (default 20). |
| `--seed N` | Sampling seed (default 7), so two runs on the same commit give the same table. |
| `--json FILE` | Also write the raw numbers, including the flagged examples to check by hand. |
| `--in-repo` | Keep indexes in `<repo>/.staticsight/` instead of the per-user cache. |

> ✅ **Read-only by default.** The benchmark stores its indexes in the per-user cache, so the measured repository is
> not written to. For exact token counts install `tiktoken` (`pip install tiktoken`); otherwise it estimates
> characters ÷ 4 and says so.

## What it measures

| Measurement | "Without StaticSight" means | "With StaticSight" means |
|---|---|---|
| **Review** | the tokens to read every changed C/C++ file (and, for reference, the raw diff) | the tokens of one `review_changes` bundle, and its time |
| **Logic of one function** | the tokens of the function body, and of its whole file | the tokens of `get_branch_skeleton` (random functions of 40+ lines) |
| **Who calls it?** | the lines `rg -w NAME` returns over C/C++ files | the call sites `get_upstream_callers` returns, and how many ignore the result |
| **Header change reach** | the direct `#include` lines a text search finds | the extra files reached through other headers (`get_include_blast_radius`, depth 3); headers whose bare name matches several files are skipped |
| **Struct layout change** | every whole-word reference to the struct | the sites where its bytes matter (`track_struct_risks`), and how many were found on a neighbouring line |
| **Locking** | text search cannot answer | `track_lock_order` over the repository, and `track_state_mutations` on sampled members of classes that take locks |

"Without StaticSight" is a fair stand-in for what an assistant reads when it has only text search and file reads:
to answer "who calls this?" it must look at every matching line; to review a change it must read the changed files.

## Results

### SomeCPPRepo: a 1.1-million-line production C++ service

2,004 C/C++ files (Windows-heavy C++: SRW locks, critical sections, COM), never compiled for these runs.
`--base HEAD~3 --samples 20`, tokens counted with tiktoken `o200k_base`, Linux, 32 vCPU AMD EPYC 7763.

| Measurement | Without StaticSight | With StaticSight |
|---|---|---|
| Review `HEAD~3` (6 C/C++ files) | 55,502 tokens to read the changed files (26,689 for the raw diff) | **5,202-token review bundle** (−91%), 5.0 s |
| Logic of one function (20 functions ≥ 40 lines) | median 514 tokens (body), 20,364 (file) | **median 258-token skeleton** (−50% vs body, −99% vs file), 148 ms |
| Who calls it? (20 functions) | 365 text-search lines, **70% not calls** | **109 call sites** with caller; 35 flagged as ignoring the result; median 73 ms |
| Header change reach (20 headers) | median 4 direct `#include` lines | **median +54 more files through other headers**; 20 of 20 reach further than a text search shows |
| Struct layout change (10 structs) | 384 references to read | **20 sites where the bytes matter** (1 with the operation on a neighbouring line) |
| Locking (865 functions take 195 locks) | no answer from text search | **16 lock-order pairs, 0 potential deadlock cycles, 1 same-lock-twice, 9 held across blocking calls**; 9 of 20 sampled members accessed both with and without a lock (candidates to review); 11.9 s |

What we checked by hand:
- **Callers:** for all 20 functions, every call line that a line-by-line cross-check found was also in StaticSight's
  answer. The 70% "not calls" were declarations, definitions, comments and logging strings that contain the name.
- **Same lock taken twice:** the one finding is genuine: a function holds an SRW lock in shared mode and calls a method
  that acquires the same lock again. Windows SRW locks must not be acquired recursively, even shared.
- **Locks held across blocking calls:** `Sleep`, `WaitForSingleObject`, `WriteFile` and `CreateFile` while a lock is
  held. Each is worth a look for latency or deadlock risk; some are deliberate.
- **Members accessed with and without a lock:** these are *candidates*. The two we inspected were a pointer written
  once under a lock during initialisation and read afterwards (usually benign), and a queue accessed without a lock in
  methods whose callers may hold it. The tool's own note says locks held by callers are not visible.

### The test repository (`shared/fixtures`)

27 C/C++ files with planted review bugs; `--base origin/main --samples 5`.

| Measurement | Without StaticSight | With StaticSight |
|---|---|---|
| Review `origin/main` (8 C/C++ files) | 1,072 tokens to read the changed files (1,009 for the raw diff) | **3,862-token review bundle** (+260%), 0.8 s |
| Header change reach (1 header) | median 8 direct `#include` lines | **median +3 more files through other headers** |
| Struct layout change (1 struct) | 18 references to read | **4 sites where the bytes matter** (1 with the operation on a neighbouring line) |
| Locking (5 functions take 3 locks) | no answer from text search | **1 potential deadlock cycle, 1 lock held across a blocking call** |

On a toy diff the bundle is *larger* than the changed files. That is expected: it adds the evidence that lives in
other files (callers, the `memcpy` sites, the lock taken by `drain()`), which is exactly what the diff does not show.
The token savings appear on real changes to real files.

## Evaluate an agent on planted bugs

Tokens and precision measure the tools. `scripts/eval_agent.py` measures whether the evidence reaches the **answer**.

```bash
python3 scripts/eval_agent.py                        # static mode: builds the test repository in a temp folder
python3 scripts/eval_agent.py --only switch_gap,log_origin --json eval.json
```

Each task in [`shared/eval/tasks.json`](../shared/eval/tasks.json) is a question a developer asks about a planted bug
("Can ConnPool deadlock?", "MsgType gained a Ping value. Is every switch updated?", "A log says … Which code printed
it?"), the StaticSight calls that answer it, and the evidence a correct answer must name: the file, the line within ±3,
and one keyword ("deadlock", "Ping", …). **Static mode** runs the calls and checks their output; it also counts the tokens
of the files an assistant without StaticSight would have to read to find the same thing.

Result on the test repository:

| Task | Evidence in StaticSight output | StaticSight tokens | Tokens to read the files | Change |
|---|---|---|---|---|
| `leak_early_return` | ✅ | 3,870 | 355 | +990% |
| `leak_project_allocator` | ✅ | 107 | 461 | −77% |
| `lock_order_cycle` | ✅ | 314 | 191 | +64% |
| `lock_across_send` | ✅ | 314 | 191 | +64% |
| `switch_gap` | ✅ | 93 | 395 | −76% |
| `platform_twin` | ✅ | 124 | 51 | +143% |
| `unlocked_write` | ✅ | 255 | 355 | −28% |
| `struct_layout` | ✅ | 352 | 324 | +9% |
| `ignored_result` | ✅ | 283 | 444 | −36% |
| `entry_exposure` | ✅ | 250 | 300 | −17% |
| `log_origin` | ✅ | 119 | 365 | −67% |
| `virtual_override` | ✅ | 189 | 228 | −17% |

**Evidence found:** 12 of 12 tasks · **tokens:** 6,270 with StaticSight vs 3,660 to read the files (+71%) · tokenizer: estimate (characters / 4; pip install tiktoken for exact counts).

_"Tokens to read the files" is a lower bound for an assistant without StaticSight: it must also find those files, and on a large repository it rarely reads all of them._

On this toy repository the source files are tiny, so reading them is cheap; the point of the table is the first
column. On real code the files are thousands of lines long and the token picture is the one in the SomeCPPRepo results.

**Agent mode** grades real agents with the same rule. Pass any agent CLI as a command template; `{prompt}` becomes the
question (shell-quoted) and the command runs inside the repository:

```text
python3 scripts/eval_agent.py \
    --agent-cmd    'copilot -p {prompt} --allow-all-tools' \
    --baseline-cmd 'copilot -p {prompt} --allow-all-tools --disable-mcp-server staticsight' \
    --repeat 3
```

Two more columns appear: the share of correct answers with StaticSight and without it. Answers vary between runs, so
use `--repeat`. With `--repo` and `--tasks` it evaluates your own repository with your own planted or historical bugs.

## Honest reading of these numbers

- **Tokens are a proxy.** They show how much an assistant must read to have the same evidence. They do not measure
  answer quality directly; the precision rows (callers, struct sites, lock order) and the planted bugs do that.
- **"Without StaticSight" is deliberately simple.** A skilled assistant can search more cleverly than `rg -w`. It still
  has to read and judge every line, which is the cost StaticSight removes.
- **Samples are small and seeded.** Run with more samples on your own repository; the JSON output lists the flagged
  items so you can check them.
- **Heuristic findings are leads.** Lock-order and lock-consistency results name file and line so you can confirm them;
  they are not proofs.

---

<!-- nav:bottom -->
| ⬅️ [Raw commands](COMMANDS.md) | 📚 [Documentation](README.md) | [Developer guide](developer-guide.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
