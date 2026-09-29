#!/usr/bin/env bash
# StaticSight engine installer for Linux / macOS (opt-in; nothing is changed without confirmation).
#
#   scripts/install.sh [--check] [--dry-run] [--yes] [--no-global] [--with-semantic] [--python=PATH] [--help]
#
#   --check      only report status (no changes); exit 1 if something required is missing/unusable
#   --dry-run    print the install plan and commands, change nothing
#   --yes        do not ask for confirmation (CI)
#   --no-global  skip GNU Global (optional; StaticSight falls back to ripgrep)
#   --with-semantic  also install the semantic-search Python packages and download the pinned embedding
#                    model (~165 MB, sha256-verified) into the per-user cache
#   --python=PATH    the Python that will run staticsight.py (default: python3), e.g. a venv's python
#
# Engines: ctags (Universal Ctags with JSON, required), rg (required), git (required),
#          cppcheck (recommended), GNU Global gtags/global (optional).
# Python packages (installed with pip for --python, from requirements*.txt): mcp (required),
#          onnxruntime + tokenizers + numpy (semantic search, optional).
# Package managers: apt-get, tdnf, dnf, brew. GNU Global is built from source where no package exists.
# STATICSIGHT_DISABLE_ENGINES=a,b makes the script treat those engines as missing (for testing).
# STATICSIGHT_PREFIX=/path overrides the install prefix of a source-built GNU Global (default /usr/local).
set -euo pipefail

GLOBAL_VERSION="6.6.14"
GLOBAL_SHA256="f6e7fd0b68aed292e85bb686616baf6551d5c9424adcddca11d808ba318cb320"
GLOBAL_URL="https://ftp.gnu.org/pub/gnu/global/global-${GLOBAL_VERSION}.tar.gz"
PREFIX="${STATICSIGHT_PREFIX:-/usr/local}"   # where a source-built GNU Global is installed

CHECK=0 DRY=0 YES=0 NO_GLOBAL=0 SEMANTIC=0 PY=python3
REPO="$(cd "$(dirname "$0")/.." && pwd)"
for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    --no-global) NO_GLOBAL=1 ;;
    --with-semantic) SEMANTIC=1 ;;
    --python=*) PY="${arg#--python=}" ;;
    --help|-h) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

disabled() { [[ ",${STATICSIGHT_DISABLE_ENGINES:-}," == *",$1,"* ]]; }
have() { ! disabled "$1" && command -v "$1" >/dev/null 2>&1; }

ctags_ok() {
  have ctags || return 1
  local v f
  v="$(ctags --version 2>/dev/null | head -n1 || true)"
  f="$(ctags --list-features 2>/dev/null || true)"
  [[ "$v" != *Exuberant* ]] && grep -qi json <<<"$f"
}

status_line() { # name level ok detail
  local mark="OK  "
  if [[ "$3" != 1 ]]; then if [[ "$2" == required ]]; then mark="FAIL"; else mark="WARN"; fi; fi
  printf '  %s %-9s [%s] %s\n' "$mark" "$1" "$2" "$4"
}

report() {
  local fail=0 t
  echo "StaticSight engines:"
  if ctags_ok; then status_line ctags required 1 "$(ctags --version | head -n1)"
  elif have ctags; then status_line ctags required 0 "installed but has no JSON output (Exuberant?) - Universal Ctags needed"; fail=1
  else status_line ctags required 0 "not found"; fail=1; fi
  for t in rg git; do
    if have "$t"; then status_line "$t" required 1 "$("$t" --version 2>/dev/null | head -n1)"
    else status_line "$t" required 0 "not found"; fail=1; fi
  done
  if have cppcheck; then status_line cppcheck recommended 1 "$(cppcheck --version 2>/dev/null | head -n1)"
  else status_line cppcheck recommended 0 "not found"; fi
  for t in global gtags; do
    if have "$t"; then status_line "$t" optional 1 "$("$t" --version 2>/dev/null | head -n1)"
    else status_line "$t" optional 0 "not found (ripgrep fallback will be used)"; fi
  done
  return $fail
}

# ---------------------------------------------------------------------------------------------- Python
py_ok() { command -v "$PY" >/dev/null 2>&1 && "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }
py_has() { "$PY" -c "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in sys.argv[1:]) else 1)" "$@" 2>/dev/null; }
# pip can install for $PY: pip present, and a venv or no PEP 668 "externally managed" marker
py_pip_ok() {
  "$PY" - <<'PY' 2>/dev/null
import importlib.util, os, sys, sysconfig
managed = os.path.exists(os.path.join(sysconfig.get_path("stdlib"), "EXTERNALLY-MANAGED"))
sys.exit(0 if importlib.util.find_spec("pip") and (sys.prefix != sys.base_prefix or not managed) else 1)
PY
}

report_python() {
  local fail=0
  echo "Python packages (for $PY):"
  if ! py_ok; then
    status_line python required 0 "Python >= 3.10 not found as '$PY' (or use the TypeScript implementation with Node >= 22.13)"
    return 1
  fi
  status_line python required 1 "$("$PY" -c 'import sys; print("Python", sys.version.split()[0], "(" + sys.executable + ")")')"
  if py_has mcp; then status_line mcp required 1 "$("$PY" -c 'from importlib.metadata import version; print("mcp", version("mcp"))')"
  else status_line mcp required 0 "not installed (runs the MCP server and the command line)"; fail=1; fi
  if py_has onnxruntime tokenizers numpy; then status_line semantic optional 1 "onnxruntime, tokenizers, numpy"
  else status_line semantic optional 0 "onnxruntime/tokenizers/numpy not installed (only needed for semantic search)"; fi
  return $fail
}

detect_pm() {
  local pm
  for pm in apt-get tdnf dnf brew; do
    if command -v "$pm" >/dev/null 2>&1; then echo "$pm"; return; fi
  done
  echo none
}

# package name for an engine under a package manager ("" = not packaged -> special handling)
pkg_for() { # pm engine
  case "$1:$2" in
    apt-get:ctags) echo universal-ctags ;;  apt-get:rg) echo ripgrep ;;  apt-get:cppcheck) echo cppcheck ;;
    apt-get:global) echo global ;;          apt-get:git) echo git ;;
    brew:ctags) echo universal-ctags ;;     brew:rg) echo ripgrep ;;     brew:cppcheck) echo cppcheck ;;
    brew:global) echo global ;;             brew:git) echo git ;;
    tdnf:ctags|dnf:ctags) echo ctags ;;     tdnf:rg|dnf:rg) echo ripgrep ;;
    tdnf:cppcheck|dnf:cppcheck) echo cppcheck ;;  tdnf:git|dnf:git) echo git ;;
    dnf:global) echo global ;;
    *) echo "" ;;
  esac
}

SUDO=""
if [[ $(id -u) -ne 0 ]] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

if [[ $CHECK == 1 ]]; then
  rc=0
  report || rc=1
  echo
  report_python || rc=1
  if [[ $rc == 0 ]]; then echo "Result: all required engines and packages OK"; exit 0; fi
  echo "Result: something required is missing or unusable (FAIL)"; exit 1
fi

report || true
echo
report_python || true
echo

PM="$(detect_pm)"
missing=()
ctags_ok || missing+=(ctags)
have rg || missing+=(rg)
have git || missing+=(git)
have cppcheck || missing+=(cppcheck)
if [[ $NO_GLOBAL == 0 ]] && { ! have global || ! have gtags; }; then missing+=(global); fi

# Python packages: pip through staticsight.py --install (reads requirements*.txt), for $PY
py_step=""
py_note=""
if py_ok; then
  if ! py_has mcp || { [[ $SEMANTIC == 1 ]] && ! py_has onnxruntime tokenizers numpy; }; then
    if py_pip_ok; then
      py_step="$PY staticsight.py --install"
      if [[ $SEMANTIC == 1 ]]; then py_step+=" --semantic"; fi
      py_step+=" --yes"
    else
      py_note="Python packages: pip cannot install for $PY (no pip, or an OS-managed Python, PEP 668). Run
    $PY $REPO/staticsight.py --install
  to see the options (a private venv is recommended), then re-run this script with --python=/path/to/venv/bin/python."
    fi
  fi
else
  py_note="Python packages: no Python >= 3.10 found as '$PY'; install Python 3.10+ (or use the TypeScript implementation)."
fi

# Semantic model download (after the packages)
model_step=""
if [[ $SEMANTIC == 1 ]]; then
  if [[ -n "$py_step" ]] || { py_ok && py_has onnxruntime tokenizers numpy mcp; }; then
    model_step="$PY staticsight.py model download"
  elif command -v node >/dev/null 2>&1 && [[ -f "$REPO/staticsight-ts/package.json" ]]; then
    model_step="cd staticsight-ts && npm install && npm run build && node dist/server.js model download"
  fi
fi

run_python_steps() {
  local c
  for c in "$py_step" "$model_step"; do
    [[ -z "$c" ]] && continue
    echo "> $c"
    ( cd "$REPO" && bash -c "$c" ) || return 1
  done
}

if [[ ${#missing[@]} -eq 0 && -z "$py_step" && -z "$model_step" ]]; then
  echo "Nothing to install."
  if [[ -n "$py_note" ]]; then echo "$py_note"; fi
  exit 0
fi
if [[ ${#missing[@]} -gt 0 && "$PM" == none ]]; then
  echo "No supported package manager found (apt-get, tdnf, dnf, brew). Install manually: ${missing[*]}" >&2
  exit 1
fi
pkgs=()
build_global=0
for e in ${missing[@]+"${missing[@]}"}; do  # bash 3.2 (macOS) + set -u: an empty array is "unbound"
  p="$(pkg_for "$PM" "$e")"
  if [[ -n "$p" ]]; then pkgs+=("$p")
  elif [[ "$e" == global ]]; then build_global=1
  else echo "warning: no $PM package known for $e; install it manually" >&2; fi
done

plan=()
if [[ ${#pkgs[@]} -gt 0 ]]; then
  case "$PM" in
    apt-get) plan+=("${SUDO:+$SUDO }apt-get update" "${SUDO:+$SUDO }apt-get install -y ${pkgs[*]}") ;;
    tdnf) plan+=("${SUDO:+$SUDO }tdnf install -y ${pkgs[*]}") ;;
    dnf) plan+=("${SUDO:+$SUDO }dnf install -y ${pkgs[*]}") ;;
    brew) plan+=("brew install ${pkgs[*]}") ;;
  esac
fi
if [[ $build_global == 1 ]]; then
  plan+=("build GNU Global ${GLOBAL_VERSION} from source (${GLOBAL_URL}, sha256-verified) into ${PREFIX}")
fi
if [[ -n "$py_step" ]]; then plan+=("Python packages (pip): $py_step"); fi
if [[ -n "$model_step" ]]; then plan+=("embedding model: $model_step"); fi

echo "Install plan${PM:+ ($PM)}:"
for c in ${plan[@]+"${plan[@]}"}; do echo "  - $c"; done
if [[ -n "$py_note" ]]; then echo "$py_note"; fi
if [[ $DRY == 1 ]]; then echo "(dry run: nothing changed)"; exit 0; fi

if [[ $YES == 0 ]]; then
  if [[ ! -t 0 ]]; then echo "Refusing to install without confirmation on a non-interactive shell; re-run with --yes." >&2; exit 1; fi
  read -r -p "Proceed? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted; nothing changed."; exit 1; }
fi

tdnf_install() {
  # Some images lack the distroverpkg package that tdnf uses to infer $releasever; pass it explicitly then.
  $SUDO tdnf install -y "$@" && return 0
  local rel=""
  if [[ -r /etc/os-release ]]; then rel="$(. /etc/os-release && echo "${VERSION_ID%.*}")"; fi
  [[ -n "$rel" ]] && $SUDO tdnf --releasever="$rel" install -y "$@"
}

if [[ ${#pkgs[@]} -gt 0 ]]; then
  case "$PM" in
    apt-get) $SUDO apt-get update && $SUDO apt-get install -y "${pkgs[@]}" ;;
    tdnf) tdnf_install "${pkgs[@]}" ;;
    dnf) $SUDO dnf install -y "${pkgs[@]}" ;;
    brew) brew install "${pkgs[@]}" ;;
  esac
fi

if [[ $build_global == 1 ]]; then
  for t in curl tar make cc sha256sum; do
    command -v "$t" >/dev/null || { echo "GNU Global build needs '$t'; install it and re-run." >&2; exit 1; }
  done
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  curl -fsSL "$GLOBAL_URL" -o "$work/global.tgz"
  echo "${GLOBAL_SHA256}  $work/global.tgz" | sha256sum -c - >/dev/null || { echo "checksum mismatch for $GLOBAL_URL" >&2; exit 1; }
  tar xzf "$work/global.tgz" -C "$work"
  # Cross-compile SDK environments (CC/CFLAGS pointing at another target) break a native build: clear them.
  ( cd "$work/global-${GLOBAL_VERSION}" && env -u CC -u CXX -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS -u LD -u AR -u RANLIB \
      -u CONFIG_SITE -u PKG_CONFIG_SYSROOT_DIR -u PKG_CONFIG_PATH \
      sh -c './configure --prefix="$0" --disable-gtagscscope >/dev/null && make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)" >/dev/null' "$PREFIX" )
  if [[ -w "$PREFIX" || ( ! -e "$PREFIX" && -w "$(dirname "$PREFIX")" ) ]]; then inst=""; else inst="$SUDO"; fi
  ( cd "$work/global-${GLOBAL_VERSION}" && $inst make install >/dev/null )
  case ":$PATH:" in *":$PREFIX/bin:"*) ;; *) echo "note: add $PREFIX/bin to PATH to use GNU Global." ;; esac
fi

run_python_steps || { echo "Python package installation failed (see above)." >&2; exit 1; }

echo
rc=0
report || rc=1
echo
report_python || rc=1
if [[ $rc == 0 ]]; then echo "Result: all required engines and packages OK"; else echo "Result: something required is still missing"; exit 1; fi
