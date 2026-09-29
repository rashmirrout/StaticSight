<!-- nav:top -->
📚 [Documentation](README.md) › **Benchmarks**
<!-- /nav:top -->

# Benchmarks you can reproduce

Every number in the README's "Why StaticSight" section comes from `scripts/benchmark.py`. This page explains what it
measures, how, and what the results on two repositories were. Run it on your own code: that is the real test.

<!-- nav:toc -->
**On this page:** [Run it](#run-it) · [What it measures](#what-it-measures) · [Results](#results) · [Honest reading of these numbers](#honest-reading-of-these-numbers)
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

17 C/C++ files with planted review bugs; `--base origin/main --samples 5`.

| Measurement | Without StaticSight | With StaticSight |
|---|---|---|
| Review `origin/main` (5 C/C++ files) | 699 tokens to read the changed files (724 for the raw diff) | **3,489-token review bundle** (+399%), 0.4 s |
| Header change reach (1 header) | median 7 direct `#include` lines | **median +3 more files through other headers** |
| Struct layout change (1 struct) | 17 references to read | **4 sites where the bytes matter** (1 with the operation on a neighbouring line) |
| Locking (5 functions take 3 locks) | no answer from text search | **1 potential deadlock cycle, 1 lock held across a blocking call** |

On a toy diff the bundle is *larger* than the changed files. That is expected: it adds the evidence that lives in
other files (callers, the `memcpy` sites, the lock taken by `drain()`), which is exactly what the diff does not show.
The token savings appear on real changes to real files.

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
| ⬅️ [Raw commands](COMMANDS.md) | 📚 [Documentation](README.md) |   |
|:---|:---:|---:|
<!-- /nav:bottom -->
