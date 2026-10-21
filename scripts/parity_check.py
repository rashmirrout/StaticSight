#!/usr/bin/env python3
"""Parity check on a real repository: run the same tool calls through the Python and the TypeScript implementation
and compare the Markdown byte for byte. The goldens cover the test repository; this covers yours.

    python3 scripts/parity_check.py /path/to/cpp/repo [N_SYMBOLS]

Read-only for the repository (indexes go to a temporary cache). Symbols, types, enums and files are sampled with a
fixed seed. Differences are written to ./parity_out/<hash>.{py,ts}.md; the exit code is 1 when any output differs.
Needs the Python environment (staticsight-py/.venv, or `staticsight` on PATH) and a built TypeScript server.
"""
import glob, hashlib, os, random, shutil, sqlite3, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if len(sys.argv) < 2:
    sys.exit(__doc__)
repo = os.path.abspath(sys.argv[1]); n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
F = tempfile.mkdtemp(prefix="staticsight-parity-")
out = os.path.abspath("parity_out")
env=dict(os.environ, STATICSIGHT_DATA_DIR="cache", STATICSIGHT_EMBED_MODEL="test-hash")
venv=os.path.join(HERE, "staticsight-py", ".venv", "Scripts" if os.name == "nt" else "bin", "staticsight")
PY=[venv] if os.path.exists(venv) or os.path.exists(venv + ".exe") else [shutil.which("staticsight") or "staticsight"]; TS=["node", f"{HERE}/staticsight-ts/dist/server.js"]
def run(cmd, cache, args):
    e=dict(env, STATICSIGHT_CACHE_DIR=os.path.join(F, cache))
    return subprocess.run(cmd+["--repo", repo, "tool", *args], env=e, capture_output=True, text=True, encoding="utf-8", cwd=F).stdout
# warm both graphs
run(PY,"dt_py",["get_index_status"]); run(TS,"dt_ts",["get_index_status"])
run(PY,"dt_py",["get_impact","main"]); run(TS,"dt_ts",["get_impact","main"])
db=sqlite3.connect(glob.glob(os.path.join(F,"dt_py","*","graph.db"))[0])
rnd=random.Random(7)
fns=[r[0] for r in db.execute("select distinct callee from calls where how in ('call','member','qualified') and callee in (select name from defs where kind='function') order by callee")]
types=[r[0] for r in db.execute("select distinct name from defs where kind in ('class','struct') and inherits<>'' order by name")]
enums=[r[0] for r in db.execute("select distinct name from defs where kind='enum' order by name")]
files=[r[0] for r in db.execute("select path from files where path like '%.cpp' order by path")]
S=rnd.sample(fns, min(n,len(fns))); cases=[]
for s in S:
    cases += [["get_impact",s],["get_impact",s,"--direction","callees","--depth","2"],["find_entry_paths",s],["find_related_tests",s],
              ["find_counterparts",s],["get_context_pack",s],["plan_change",s,"--change","add a parameter"],["get_upstream_callers",s]]
for a,b in zip(S,S[1:]): cases.append(["get_call_paths",a,b])
for t in rnd.sample(types,min(n,len(types))): cases += [["get_type_hierarchy",t],["query_graph",f"derived*2 of {t}"],["query_graph",f"members of {t}"]]
for e in rnd.sample(enums,min(n,len(enums))): cases.append(["find_switch_coverage",e])
for f in rnd.sample(files,min(n,len(files))): cases += [["get_line_history",f,"10","--end-line","40"],["get_branch_skeleton",f,"--start-line","30"]]
cases += [["get_change_hotspots"],["get_change_hotspots","--path-glob","src/*"],["query_graph","entry-points"],["get_lock_graph"],
          ["find_log_origin","Failed to open handle 0x1234 for adapter {ABC} error 5"]]
bad=0
for c in cases:
    a=run(PY,"dt_py",c); b=run(TS,"dt_ts",c)
    if a!=b:
        bad+=1; os.makedirs(out, exist_ok=True); h=hashlib.sha1(" ".join(c).encode()).hexdigest()[:8]
        open(os.path.join(out,h+".py.md"),"w").write(a); open(os.path.join(out,h+".ts.md"),"w").write(b)
        print("DIFF", h, " ".join(c))
print(f"{len(cases)-bad}/{len(cases)} identical" + (f"; differences in {out}" if bad else ""))
shutil.rmtree(F, ignore_errors=True)
sys.exit(1 if bad else 0)
