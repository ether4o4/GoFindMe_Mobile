"""Tool registry, safe dispatcher, streaming subprocess spawner, and the
install/update manager.

Everything that executes a child process funnels through ``spawn_stream`` with an
argv **list** and ``shell=False``. Targets are validated first; install refs are
validated against tight charsets; managers are an allowlist. No string is ever
handed to a shell.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable

from . import db
from .config import settings
from .util import audit, strip_ansi
from .validators import ValidationError, build_argv, validate

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class ToolSpec:
    name: str
    bin: str
    categories: list[str]
    accepts: list[str]
    run_template: str                 # full command using {bin} and {target}
    timeout_s: int = 180
    auto_runnable: bool = True         # eligible for Search-All / direct run
    interactive: bool = False          # GUI/REPL — never spawned, copy-command only
    install_method: str = "none"       # pip|pipx|go|git|npm|none
    install_ref: str | None = None
    git_entry: str | None = None       # for git tools: python entry script in the clone
    version_cmd: str | None = None     # template, e.g. "{bin} --version"
    stdin_template: str | None = None  # if set, target is piped to stdin, not argv
    notes: str = ""
    source: str = "builtin"

    def public(self) -> dict:
        d = asdict(self)
        d.pop("stdin_template", None)
        return d


# Built-in manifest. Interactive/GUI frameworks are listed for visibility only.
BUILTIN: list[ToolSpec] = [
    # --- username ---
    ToolSpec("sherlock", "sherlock", ["username"], ["username"],
             "{bin} --print-found --timeout 30 --no-color {target}", 240,
             install_method="pip", install_ref="sherlock-project"),
    ToolSpec("maigret", "maigret", ["username"], ["username"],
             "{bin} --timeout 30 --no-color {target}", 300,
             install_method="pip", install_ref="maigret"),
    ToolSpec("blackbird", "blackbird", ["username", "email"], ["username", "email"],
             "{bin} -u {target}", 240, install_method="git",
             install_ref="https://github.com/p1ngul1n0/blackbird",
             git_entry="blackbird.py",
             notes="Cloned to data/tools; run with the system Python entrypoint."),
    ToolSpec("nexfil", "nexfil", ["username"], ["username"],
             "{bin} -u {target}", 240, install_method="git",
             install_ref="https://github.com/thewhiteh4t/nexfil",
             git_entry="nexfil.py",
             notes="Cloned to data/tools; run with the system Python entrypoint."),
    # --- email ---
    ToolSpec("holehe", "holehe", ["email"], ["email"],
             "{bin} --only-used {target}", 180, install_method="pip", install_ref="holehe"),
    ToolSpec("h8mail", "h8mail", ["email"], ["email"],
             "{bin} -t {target}", 180, install_method="pip", install_ref="h8mail"),
    ToolSpec("ghunt", "ghunt", ["email"], ["email"],
             "{bin} email {target}", 180, install_method="pip", install_ref="ghunt",
             notes="Requires a one-time `ghunt login` with Google cookies."),
    # --- phone ---
    ToolSpec("phoneinfoga", "phoneinfoga", ["phone"], ["phone"],
             "{bin} scan -n {target}", 120, install_method="none",
             notes="Install the binary from sundowndev/phoneinfoga releases."),
    # --- domain ---
    ToolSpec("subfinder", "subfinder", ["domain"], ["domain"],
             "{bin} -silent -d {target}", 300, install_method="go",
             install_ref="github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest"),
    ToolSpec("amass", "amass", ["domain"], ["domain"],
             "{bin} enum -passive -d {target}", 600, install_method="go",
             install_ref="github.com/owasp-amass/amass/v4/...@master",
             notes="Heavy; capped to one concurrent run."),
    ToolSpec("findomain", "findomain", ["domain"], ["domain"],
             "{bin} -t {target} -q", 240, install_method="none",
             notes="Install the binary from findomain/findomain releases."),
    ToolSpec("assetfinder", "assetfinder", ["domain"], ["domain"],
             "{bin} --subs-only {target}", 180, install_method="go",
             install_ref="github.com/tomnomnom/assetfinder@latest"),
    ToolSpec("theHarvester", "theHarvester", ["domain"], ["domain"],
             "{bin} -d {target} -b duckduckgo,bing,crtsh,otx", 300,
             install_method="pip", install_ref="theHarvester"),
    ToolSpec("gau", "gau", ["domain"], ["domain"],
             "{bin} {target}", 240, install_method="go",
             install_ref="github.com/lc/gau/v2/cmd/gau@latest"),
    ToolSpec("waybackurls", "waybackurls", ["domain"], ["domain"],
             "{bin} {target}", 180, install_method="go",
             install_ref="github.com/tomnomnom/waybackurls@latest"),
    ToolSpec("katana", "katana", ["domain"], ["domain"],
             "{bin} -silent -u https://{target}", 300, install_method="go",
             install_ref="github.com/projectdiscovery/katana/cmd/katana@latest"),
    ToolSpec("hakrawler", "hakrawler", ["domain"], ["domain"],
             "{bin} -u", 180, install_method="go",
             install_ref="github.com/hakluke/hakrawler@latest",
             stdin_template="https://{target}"),
    ToolSpec("waymore", "waymore", ["domain"], ["domain"],
             "{bin} -i {target} -mode U", 300, install_method="pip", install_ref="waymore"),
    ToolSpec("bbot", "bbot", ["domain"], ["domain"],
             "{bin} -t {target} -f subdomain-enum -y -o {target}", 600,
             install_method="pip", install_ref="bbot",
             notes="Modular recon framework; passive subdomain preset."),
    ToolSpec("whois", "whois", ["domain", "ip"], ["domain", "ip"],
             "{bin} {target}", 30, install_method="none",
             notes="Usually provided by the OS (whois package)."),
    # --- ip / domain (key tools that overlap providers) ---
    ToolSpec("shodan-cli", "shodan", ["ip", "domain"], ["ip", "domain"],
             "{bin} host {target}", 60, install_method="pip", install_ref="shodan",
             notes="Run `shodan init <key>` once; or use the Shodan provider instead."),
    # --- image / metadata (needs an uploaded file; see notes) ---
    ToolSpec("exiftool", "exiftool", ["image"], ["image"],
             "{bin} -json {target}", 60, install_method="none",
             notes="Runs on an uploaded file. Install via your OS package manager."),
    ToolSpec("mat2", "mat2", ["image"], ["image"],
             "{bin} --show {target}", 60, install_method="pip", install_ref="mat2",
             notes="Inspect/strip file metadata on an uploaded file."),
    # --- interactive / GUI frameworks: visibility + copy-command only ---
    ToolSpec("spiderfoot", "sf", ["username", "email", "domain", "ip"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             install_method="pip", install_ref="spiderfoot",
             notes="Runs its own web server; launch separately."),
    ToolSpec("recon-ng", "recon-ng", ["domain", "email"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             install_method="pip", install_ref="recon-ng",
             notes="Interactive console."),
    ToolSpec("maltego", "maltego", ["username", "email", "domain", "ip"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             notes="GUI application."),
    ToolSpec("osmedeus", "osmedeus", ["domain"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             notes="Heavy workflow engine; run separately."),
    ToolSpec("theharvester-foca", "foca", ["domain"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             notes="FOCA is a Windows GUI document-metadata tool."),
    ToolSpec("moriarty", "moriarty", ["phone", "email", "username"], [],
             "{bin}", 0, auto_runnable=False, interactive=True,
             notes="Interactive project; launch separately."),
]


def _custom_specs() -> list[ToolSpec]:
    out: list[ToolSpec] = []
    for r in db.query("SELECT * FROM custom_tools ORDER BY name"):
        out.append(ToolSpec(
            name=r["name"], bin=r["bin"],
            categories=json.loads(r["categories"] or "[]"),
            accepts=json.loads(r["accepts"] or "[]"),
            run_template=r["run_template"], timeout_s=r["timeout_s"],
            auto_runnable=bool(r["auto_runnable"]), interactive=bool(r["interactive"]),
            install_method=r["install_method"], install_ref=r["install_ref"],
            version_cmd=r["version_cmd"], notes=r["notes"] or "", source="custom",
        ))
    return out


def registry() -> dict[str, ToolSpec]:
    """Built-in manifest merged with user-defined custom tools (custom wins)."""
    reg = {s.name: s for s in BUILTIN}
    for s in _custom_specs():
        reg[s.name] = s
    return reg


def get_spec(name: str) -> ToolSpec | None:
    return registry().get(name)


# --- homepage + API-key links shown next to each tool ---
TOOL_URLS = {
    "sherlock": "https://github.com/sherlock-project/sherlock",
    "maigret": "https://github.com/soxoj/maigret",
    "blackbird": "https://github.com/p1ngul1n0/blackbird",
    "nexfil": "https://github.com/thewhiteh4t/nexfil",
    "holehe": "https://github.com/megadose/holehe",
    "h8mail": "https://github.com/khast3x/h8mail",
    "ghunt": "https://github.com/mxrch/GHunt",
    "phoneinfoga": "https://github.com/sundowndev/phoneinfoga",
    "subfinder": "https://github.com/projectdiscovery/subfinder",
    "amass": "https://github.com/owasp-amass/amass",
    "findomain": "https://github.com/Findomain/Findomain",
    "assetfinder": "https://github.com/tomnomnom/assetfinder",
    "theHarvester": "https://github.com/laramies/theHarvester",
    "gau": "https://github.com/lc/gau",
    "waybackurls": "https://github.com/tomnomnom/waybackurls",
    "katana": "https://github.com/projectdiscovery/katana",
    "hakrawler": "https://github.com/hakluke/hakrawler",
    "waymore": "https://github.com/xnl-h4ck3r/waymore",
    "bbot": "https://github.com/blacklanternsecurity/bbot",
    "shodan-cli": "https://github.com/achillean/shodan-python",
    "exiftool": "https://exiftool.org/",
    "mat2": "https://0xacab.org/jvoisin/mat2",
    "spiderfoot": "https://github.com/smicallef/spiderfoot",
    "recon-ng": "https://github.com/lanmaster53/recon-ng",
    "maltego": "https://www.maltego.com/",
    "osmedeus": "https://github.com/j3ssie/osmedeus",
    "theharvester-foca": "https://github.com/ElevenPaths/FOCA",
    "moriarty": "https://github.com/AzizKpln/Moriarty-Project",
}
# Tools that consume an API key → link straight to where that key is obtained.
TOOL_KEY_URLS = {
    "shodan-cli": "https://account.shodan.io",
    "ghunt": "https://github.com/mxrch/GHunt/wiki",          # uses Google auth cookies
    "h8mail": "https://github.com/khast3x/h8mail#-getting-started",  # API keys via config
    "theHarvester": "https://github.com/laramies/theHarvester/wiki/Installation#api-keys",
}

# --- availability (cached briefly) ---
_avail_cache: dict[str, tuple[float, str | None]] = {}
_AVAIL_TTL = 20.0
_extra_dirs_cache: list[str] | None = None

_SCRIPTS_SNIPPET = (
    "import sysconfig, os, json\n"
    "p = set()\n"
    "p.add(sysconfig.get_path('scripts'))\n"
    "try:\n"
    "    p.add(sysconfig.get_path('scripts', os.name + '_user'))\n"
    "except Exception:\n"
    "    pass\n"
    "print(json.dumps([x for x in p if x]))\n"
)


def _system_python() -> str | None:
    if getattr(sys, "frozen", False):
        # `py` is the Windows Python launcher (`py -m pip ...` works); try it last.
        return (shutil.which("python3") or shutil.which("python")
                or shutil.which("py"))
    return sys.executable


def _extra_bin_dirs() -> list[str]:
    """Extra dirs to search for installed tools: Go bin + Python script dirs
    (where pip/`go install` drop console scripts that may not be on PATH)."""
    global _extra_dirs_cache
    if _extra_dirs_cache is not None:
        return _extra_dirs_cache
    dirs: list[str] = []
    home = os.path.expanduser("~")
    for d in (os.environ.get("GOBIN"),
              os.path.join(os.environ.get("GOPATH", os.path.join(home, "go")), "bin"),
              os.path.join(home, "go", "bin")):
        if d and d not in dirs:
            dirs.append(d)
    py = _system_python()
    if py:
        try:
            out = subprocess.run([py, "-c", _SCRIPTS_SNIPPET], capture_output=True,
                                 text=True, timeout=12)
            for d in json.loads(out.stdout or "[]"):
                if d and d not in dirs:
                    dirs.append(d)
        except Exception:
            pass
    _extra_dirs_cache = [d for d in dirs if os.path.isdir(d)]
    return _extra_dirs_cache


def resolve_bin(bin_name: str) -> str | None:
    now = time.time()
    hit = _avail_cache.get(bin_name)
    if hit and now - hit[0] < _AVAIL_TTL:
        return hit[1]
    path = shutil.which(bin_name)
    if not path:
        extra = _extra_bin_dirs()
        if extra:
            search = os.pathsep.join(extra + [os.environ.get("PATH", "")])
            path = shutil.which(bin_name, path=search)
    _avail_cache[bin_name] = (now, path)
    return path


def _git_entry_path(spec: ToolSpec) -> str | None:
    """For a git-cloned tool, the python entry script inside the clone, if present."""
    if spec.install_method != "git" or not spec.git_entry:
        return None
    p = TOOLS_DIR / spec.name / spec.git_entry
    return str(p) if p.is_file() else None


def resolve_spec(spec: ToolSpec) -> str | None:
    """Path used to both detect and run a tool. Git-cloned tools resolve to their
    entry script in TOOLS_DIR; every other tool resolves a binary on PATH."""
    if spec.install_method == "git" and spec.git_entry:
        return _git_entry_path(spec)
    return resolve_bin(spec.bin)


def tool_view(spec: ToolSpec) -> dict:
    path = resolve_spec(spec)
    d = spec.public()
    d["available"] = path is not None
    d["path"] = path
    d["url"] = TOOL_URLS.get(spec.name, "")
    d["key_url"] = TOOL_KEY_URLS.get(spec.name, "")
    return d


def list_tools() -> list[dict]:
    return [tool_view(s) for s in registry().values()]


# ---------------------------------------------------------------------------
# Low-level streaming spawner (the single choke point for child processes)
# ---------------------------------------------------------------------------

OutputCb = Callable[[str], Awaitable[None] | None]

# Child processes inherit the FULL parent environment so they actually work on
# every OS. A stripped allowlist looks safe on Linux but breaks Windows badly:
# pip and every Python-based tool (sherlock/maigret/holehe/...) need SYSTEMROOT,
# TEMP/TMP, APPDATA/LOCALAPPDATA, USERPROFILE and PATHEXT just to start a process
# and open a TLS socket. Without them you get cryptic "could not create temporary
# directory" / download failures on every single install and run.
#
# This is safe: vault secrets live in the SQLite DB and are decrypted on demand
# per provider call — they are NEVER placed in os.environ, so nothing sensitive
# is exposed to a child here.
#
# For tool RUN jobs (third-party OSINT tools) we still drop our own outbound proxy
# and CA overrides, so those tools aren't silently routed through — or made to
# trust — our internal proxy/cert. MANAGE jobs (pip/go/git) KEEP the proxy + CA so
# they can fetch packages through it.
_PROXY_CA_KEYS = (
    "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy",
    "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
    "GOFINDME_CA_BUNDLE",
)


def run_env() -> dict[str, str]:
    env = dict(os.environ)
    for k in _PROXY_CA_KEYS:
        env.pop(k, None)
    return env


async def spawn_stream(
    argv: list[str],
    timeout_s: int,
    on_output: OutputCb | None = None,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> tuple[str, int | None, str]:
    """Run argv (no shell), streaming combined stdout/stderr.

    Returns (status, returncode, full_output) where status is
    done|error|timeout|cancelled-equivalent handled by the caller.
    """
    cap = settings().output_cap_bytes
    buf: list[str] = []
    size = 0
    truncated = False

    async def emit(text: str) -> None:
        nonlocal size, truncated
        if size < cap:
            buf.append(text)
            size += len(text)
            if size >= cap and not truncated:
                truncated = True
                buf.append("\n[output truncated]\n")
            if on_output:
                res = on_output(text)
                if asyncio.iscoroutine(res):
                    await res

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env or run_env(),
            cwd=cwd,
        )
    except FileNotFoundError:
        return "error", None, "executable not found"
    except Exception as exc:  # pragma: no cover - defensive
        return "error", None, f"spawn failed: {exc}"

    if stdin is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
        except Exception:
            pass

    deadline = time.monotonic() + max(1, timeout_s)
    assert proc.stdout is not None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                raise
            if not line:
                break
            await emit(strip_ansi(line.decode("utf-8", "replace")))
        rc = await asyncio.wait_for(proc.wait(), timeout=max(1, deadline - time.monotonic()))
        status = "done" if rc == 0 else "error"
        return status, rc, "".join(buf)
    except asyncio.TimeoutError:
        _kill(proc)
        await emit("\n[timed out]\n")
        return "timeout", None, "".join(buf)
    except asyncio.CancelledError:
        _kill(proc)
        raise


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass


# ---------------------------------------------------------------------------
# Dispatcher — validate, build argv, run a single tool against a target
# ---------------------------------------------------------------------------


def build_tool_argv(spec: ToolSpec, target: str) -> tuple[list[str], str | None]:
    """Validate target for the spec and return (argv, stdin)."""
    exe = resolve_spec(spec)
    if not exe:
        raise FileNotFoundError(f"{spec.bin} is not installed")
    if spec.interactive or not spec.auto_runnable:
        raise PermissionError(f"{spec.name} is interactive/GUI and is not auto-run")
    # Re-validate server-side against an accepted type (never trust client).
    ttype = next((t for t in spec.accepts if _valid_for(target, t)), None)
    if ttype is None:
        raise ValidationError(f"{target!r} is not a valid input for {spec.name}")
    stdin = None
    if spec.stdin_template:
        stdin = spec.stdin_template.replace("{target}", target)
    argv = build_argv(spec.run_template, exe, target)
    if spec.install_method == "git" and spec.git_entry:
        # {bin} resolved to the cloned .py entry script — run it with the system
        # Python (the frozen exe can't import the tool's own deps).
        py = _system_python()
        if not py:
            raise FileNotFoundError("system Python not found to run this tool")
        argv = [py] + argv
    return argv, stdin


def _valid_for(target: str, ttype: str) -> bool:
    try:
        validate(target, ttype)
        return True
    except ValidationError:
        return False


# ---------------------------------------------------------------------------
# Tool manager — install / update / version, via an allowlist of managers
# ---------------------------------------------------------------------------

_SAFE_PKG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,99}$")
_SAFE_GOREF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,200}(@[A-Za-z0-9._/\-]{1,80})?$")
_SAFE_GITURL = re.compile(r"^https://[A-Za-z0-9.\-]{1,255}/[A-Za-z0-9._/\-]{1,200}$")

TOOLS_DIR = settings().db_path.parent / "tools"


class ManageError(ValueError):
    pass


def _pip() -> list[str]:
    exe = sys.executable
    if getattr(sys, "frozen", False):
        # In a packaged build sys.executable is the app itself, not Python — using
        # it would re-launch the app. Fall back to a system Python if one exists.
        py = shutil.which("python3") or shutil.which("python")
        if not py:
            raise ManageError("In-app install needs a system Python; install the tool manually.")
        exe = py
    return [exe, "-m", "pip"]


def install_argv(spec: ToolSpec, update: bool,
                 for_run: bool = False) -> tuple[list[str], str | None]:
    """Return (argv, cwd) for an install/update of a tool. Raises ManageError if
    the method or ref is not allowlisted/valid.

    ``for_run`` must be True only when the command is about to be executed (the
    job runner) — it permits filesystem prep such as clearing a stale partial
    clone. It stays False on the validation path (custom-tool upsert) so no
    directory is ever mutated just by validating a ref.
    """
    m = spec.install_method
    ref = spec.install_ref or ""
    if m == "none":
        raise ManageError(f"{spec.name} has no automated installer; install it manually.")
    if m in ("pip", "pipx", "npm") and not _SAFE_PKG.match(ref):
        raise ManageError(f"Unsafe package ref: {ref!r}")
    if m == "go" and not _SAFE_GOREF.match(ref):
        raise ManageError(f"Unsafe go module ref: {ref!r}")
    if m == "git" and not _SAFE_GITURL.match(ref):
        raise ManageError(f"git ref must be an https repo URL: {ref!r}")

    if m == "pip":
        argv = _pip() + ["install"] + (["--upgrade"] if update else []) + [ref]
        return argv, None
    if m == "pipx":
        argv = ["pipx", "upgrade", spec.bin] if update else ["pipx", "install", ref]
        return argv, None
    if m == "npm":
        return ["npm", "install", "-g", ref], None
    if m == "go":
        return ["go", "install", ref], None
    if m == "git":
        dest = TOOLS_DIR / spec.name
        py = _system_python()
        if for_run and not py:
            raise ManageError("Installing a git-based tool needs a system Python on PATH.")
        # A tiny Python bootstrap does the whole install in one streamed job:
        # clone (or fast-forward), self-heal a partial clone, then pip-install the
        # tool's own requirements.txt so it can actually run. No shell involved —
        # ref is allowlisted above and passed as a discrete argv element.
        return [py or "python", "-c", _GIT_BOOTSTRAP, ref, str(dest)], None
    raise ManageError(f"Unknown install method: {m}")


# Runs under the system Python; clones/updates a tool repo and installs its deps.
_GIT_BOOTSTRAP = (
    "import os, sys, subprocess, shutil\n"
    "ref, dest = sys.argv[1], sys.argv[2]\n"
    "def run(*a):\n"
    "    print('+ ' + ' '.join(a), flush=True)\n"
    "    subprocess.run(list(a), check=True)\n"
    "if os.path.isdir(os.path.join(dest, '.git')):\n"
    "    run('git', '-C', dest, 'pull', '--ff-only')\n"
    "else:\n"
    "    if os.path.exists(dest):\n"
    "        shutil.rmtree(dest, ignore_errors=True)\n"
    "    os.makedirs(os.path.dirname(dest), exist_ok=True)\n"
    "    run('git', 'clone', '--depth', '1', ref, dest)\n"
    "req = os.path.join(dest, 'requirements.txt')\n"
    "if os.path.isfile(req):\n"
    "    run(sys.executable, '-m', 'pip', 'install', '-r', req)\n"
    "print('OK installed to ' + dest, flush=True)\n"
)


def version_argv(spec: ToolSpec) -> list[str] | None:
    exe = resolve_spec(spec)
    if not exe:
        return None
    if spec.install_method == "git" and spec.git_entry:
        # Report the cloned commit rather than run the tool with no args.
        git = shutil.which("git")
        if not git:
            return None
        return [git, "-C", str(TOOLS_DIR / spec.name), "rev-parse", "--short", "HEAD"]
    tmpl = spec.version_cmd or "{bin} --version"
    try:
        return build_argv(tmpl, exe, "")
    except ValidationError:
        return None


def manager_available(method: str) -> bool:
    # pip works via the running interpreter, except in a frozen build where it
    # needs a separate system Python (see _pip()).
    pip_ok = _system_python() is not None if getattr(sys, "frozen", False) else True
    return {
        "pip": pip_ok,
        "pipx": shutil.which("pipx") is not None,
        "npm": shutil.which("npm") is not None,
        "go": shutil.which("go") is not None,
        "git": shutil.which("git") is not None,
        "none": False,
    }.get(method, False)


def mgmt_env() -> dict[str, str]:
    # Full environment so pip/go/git behave exactly as they do in the user's own
    # terminal (TEMP/APPDATA/SYSTEMROOT for Windows, proxy + CA to fetch packages).
    return dict(os.environ)


# ---------------------------------------------------------------------------
# Custom tool CRUD (the "add new software easily" registry)
# ---------------------------------------------------------------------------

_VALID_METHODS = {"pip", "pipx", "go", "git", "npm", "none"}


def upsert_custom_tool(data: dict) -> ToolSpec:
    from .util import now_iso
    name = (data.get("name") or "").strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$", name):
        raise ManageError("Invalid tool name")
    if name in {s.name for s in BUILTIN}:
        raise ManageError("Name collides with a built-in tool")
    bin_name = (data.get("bin") or "").strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$", bin_name):
        raise ManageError("Invalid bin name")
    run_template = (data.get("run_template") or "").strip()
    if "{target}" not in run_template:
        raise ManageError("run_template must contain {target}")
    if "{bin}" not in run_template:
        run_template = "{bin} " + run_template
    # Validate the template compiles to a safe argv (dummy bin/target).
    build_argv(run_template, "/usr/bin/true", "validation-sample")
    method = (data.get("install_method") or "none").strip()
    if method not in _VALID_METHODS:
        raise ManageError("Invalid install_method")
    accepts = data.get("accepts") or []
    cats = data.get("categories") or accepts
    spec_for_install = ToolSpec(
        name=name, bin=bin_name, categories=cats, accepts=accepts,
        run_template=run_template, install_method=method,
        install_ref=(data.get("install_ref") or None),
    )
    if method != "none":
        install_argv(spec_for_install, update=False)  # raises on unsafe ref
    db.execute(
        "INSERT INTO custom_tools (name, categories, accepts, bin, run_template, "
        "install_method, install_ref, version_cmd, timeout_s, auto_runnable, interactive, "
        "notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET categories=excluded.categories, accepts=excluded.accepts, "
        "bin=excluded.bin, run_template=excluded.run_template, install_method=excluded.install_method, "
        "install_ref=excluded.install_ref, version_cmd=excluded.version_cmd, "
        "timeout_s=excluded.timeout_s, auto_runnable=excluded.auto_runnable, "
        "interactive=excluded.interactive, notes=excluded.notes, updated_at=excluded.updated_at",
        (name, json.dumps(cats), json.dumps(accepts), bin_name, run_template, method,
         data.get("install_ref"), data.get("version_cmd"), int(data.get("timeout_s") or 180),
         1 if data.get("auto_runnable", True) else 0, 1 if data.get("interactive") else 0,
         data.get("notes"), now_iso(), now_iso()),
    )
    audit("audit", "mgmt", "custom tool saved", tool=name)
    return get_spec(name)  # type: ignore[return-value]


def delete_custom_tool(name: str) -> bool:
    n = db.write("DELETE FROM custom_tools WHERE name=?", (name,))
    if n:
        audit("audit", "mgmt", "custom tool deleted", tool=name)
    return bool(n)
