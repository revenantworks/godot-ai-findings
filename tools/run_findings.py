"""Re-run the findings against an official Godot build and rewrite the README status table.

    python tools/run_findings.py latest [--github-output FILE]
    python tools/run_findings.py run --platform linux|windows --findings 1,3 --tag 4.8-stable --out r.json
    python tools/run_findings.py table --results r1.json r2.json [--readme README.md] [--out FILE]
    python tools/run_findings.py local --godot PATH --out FILE
    python tools/run_findings.py guard

findings.csv lists each finding, its repro, the system that runs it (linux, windows or none),
the check that reads the repro's output, and the linked upstream issue and PR numbers.

`run` downloads one build from godotengine/godot-builds, checks it against the release's
SHA512-SUMS.txt, runs each repro headless from a temp copy (user data and editor settings stay in
that temp folder) and writes one JSON file of verdicts. Each check prints `RESULT PASS` (the bug
did not show) or `RESULT FAIL` (the bug showed); anything else is an error.

`table` reads the verdicts and the upstream issue and PR states (read-only `gh`), then rewrites
only the README lines between the status markers, or writes the table to `--out` instead.
`--record-build` also stores the build tag in findings.csv, which `latest` compares against.

`local` is the same run against a Godot binary already on disk, with every finding that has a
repro, and writes the table to `--out`; it never touches the README.

`guard` refuses a change that is more than a status update: tracked files must pass the PII scan,
and the diff may touch only the README status table and the build column of findings.csv.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
FINDINGS_CSV = ROOT / "findings.csv"
README = ROOT / "README.md"
START = "<!-- status:start -->"
END = "<!-- status:end -->"
BUILDS_REPO = "godotengine/godot-builds"
UPSTREAM_REPO = "godotengine/godot"
DOWNLOAD = "https://github.com/" + BUILDS_REPO + "/releases/download/{tag}/{asset}"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TIMEOUT_S = 300
PASS, FAIL, ERROR = "PASS", "FAIL", "ERROR"
CSV_FIELDS = ["finding", "title", "repro", "runner", "check", "issues", "prs", "build"]

GhRunner = Callable[[list[str]], str]


@dataclass
class Finding:
    finding: str
    title: str
    repro: str
    runner: str
    check: str
    issues: list[str]
    prs: list[str]
    build: str


def _split(cell: str) -> list[str]:
    return [part.strip() for part in cell.split(";") if part.strip()]


def load_findings(text: str) -> list[Finding]:
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        rows.append(Finding(row["finding"], row["title"], row["repro"], row["runner"], row["check"],
                            _split(row["issues"]), _split(row["prs"]), row["build"]))
    return rows


def dump_findings(rows: list[Finding]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    for r in rows:
        writer.writerow([r.finding, r.title, r.repro, r.runner, r.check, ";".join(r.issues),
                         ";".join(r.prs), r.build])
    return out.getvalue()


# --- versions --------------------------------------------------------------------------------

STAGES = {"dev": 0, "alpha": 1, "beta": 2, "rc": 3, "stable": 4}


def version_key(tag: str) -> tuple:
    """`4.7.2-stable` -> (4, 7, 2, 4, 0); `4.8-beta3` -> (4, 8, 0, 2, 3)."""
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?-([a-z]+?)(\d*)", tag.strip())
    if not match:
        raise ValueError(f"not a Godot release tag: {tag!r}")
    major, minor, patch, stage, n = match.groups()
    return (int(major), int(minor), int(patch or 0), STAGES.get(stage, -1), int(n or 0))


def recorded_build(rows: list[Finding]) -> str | None:
    builds = [r.build for r in rows if r.build]
    return max(builds, key=version_key) if builds else None


def is_newer(latest: str, recorded: str | None) -> bool:
    return recorded is None or version_key(latest) > version_key(recorded)


def default_gh(args: list[str]) -> str:
    done = subprocess.run(["gh", *args], capture_output=True, text=True, check=True,
                          creationflags=NO_WINDOW)
    return done.stdout


def latest_release(gh: GhRunner = default_gh) -> str:
    """The newest stable release tag of godot-builds (GitHub's "latest" skips pre-releases)."""
    return gh(["api", f"repos/{BUILDS_REPO}/releases/latest", "--jq", ".tag_name"]).strip()


# --- download and SHA-512 --------------------------------------------------------------------

def asset_name(tag: str, platform: str) -> str:
    if platform == "linux":
        return f"Godot_v{tag}_linux.x86_64.zip"
    if platform == "windows":
        return f"Godot_v{tag}_win64.exe.zip"
    raise ValueError(f"unknown platform {platform!r}")


def binary_name(tag: str, platform: str) -> str:
    return f"Godot_v{tag}_linux.x86_64" if platform == "linux" else f"Godot_v{tag}_win64_console.exe"


def parse_sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{128}", parts[0]):
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def verify_sha512(path: Path, expected: str) -> None:
    digest = hashlib.sha512(path.read_bytes()).hexdigest()
    if digest != expected.lower():
        raise RuntimeError(f"SHA-512 mismatch for {path.name}")


def _fetch(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=600) as resp, open(dest, "wb") as out:  # noqa: S310
        shutil.copyfileobj(resp, out)


def download_build(tag: str, platform: str, dest: Path, fetch: Callable[[str, Path], None] = _fetch) -> Path:
    """Download, verify and unzip one build. Returns the path of the console binary."""
    dest.mkdir(parents=True, exist_ok=True)
    asset = asset_name(tag, platform)
    sums_path = dest / "SHA512-SUMS.txt"
    fetch(DOWNLOAD.format(tag=tag, asset="SHA512-SUMS.txt"), sums_path)
    sums = parse_sums(sums_path.read_text(encoding="utf-8"))
    if asset not in sums:
        raise RuntimeError(f"{asset} is not listed in SHA512-SUMS.txt")
    zip_path = dest / asset
    fetch(DOWNLOAD.format(tag=tag, asset=asset), zip_path)
    verify_sha512(zip_path, sums[asset])
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    binary = dest / binary_name(tag, platform)
    if not binary.exists():
        raise RuntimeError(f"{binary.name} not found in {asset}")
    if platform == "linux":
        binary.chmod(0o755)
    return binary


# --- checks: each reads a repro's output and returns (PASS|FAIL|ERROR, detail) ---------------

def result_word(output: str) -> str | None:
    found = [line for line in output.splitlines() if line.startswith("RESULT ")]
    return found[-1].split()[1].rstrip(":") if found else None


def check_float_parse(output: str) -> tuple[str, str]:
    trip = re.search(r"round trip: (\d+) of (\d+)", output)
    dbl = re.search(r"is zero: (true|false)", output)
    if not trip or not dbl:
        return ERROR, "no round-trip or DBL_MIN line"
    off, tried = int(trip.group(1)), int(trip.group(2))
    if off or dbl.group(1) == "true":
        return FAIL, f"{off} of {tried} round trips differ; DBL_MIN reads as zero: {dbl.group(1)}"
    return PASS, f"0 of {tried} round trips differ; DBL_MIN parses"


def check_format_6f(output: str) -> tuple[str, str]:
    total = wrong = 0
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{16}", parts[0]):
            continue
        x = struct.unpack("<d", bytes.fromhex(parts[0]))[0]
        total += 1
        if parts[1] != "%.6f" % x:
            wrong += 1
    if not total:
        return ERROR, "no value lines"
    return (FAIL if wrong else PASS), f"{wrong} of {total} values not correctly rounded"


def check_class_name_cache(output: str) -> tuple[str, str]:
    if "RESULT RESOLVED" in output:
        return PASS, "FreshClass resolved without --import"
    if 'Identifier "FreshClass" not declared' in output:
        return FAIL, "FreshClass unknown until --import"
    return ERROR, "neither RESULT RESOLVED nor the parse error"


def check_crash_runner(output: str) -> tuple[str, str]:
    word = result_word(output)
    if word == "REFUSED":
        return PASS, "the engine refused the derived script"
    if word in ("CRASH", "NO_CRASH"):
        return FAIL, f"RESULT {word}: the derived script was instantiated"
    return ERROR, f"RESULT {word or 'missing'}"


def check_rename(output: str) -> tuple[str, str]:
    word = result_word(output)
    if word == "LOST_TARGET":
        return FAIL, "the failed rename deleted the target"
    if word in ("FAILED_SAFE", "REPLACED"):
        return PASS, f"RESULT {word}"
    return ERROR, f"RESULT {word or 'missing'}"


def check_configfile(output: str) -> tuple[str, str]:
    reported = {int(m.group(1)): int(m.group(2))
                for m in re.finditer(r"configfile_line_(\d+)\.cfg:(\d+):", output)}
    if not reported:
        return ERROR, "no ConfigFile parse error lines"
    off = sorted(line for line, said in reported.items() if said != line)
    if off:
        return FAIL, f"wrong line for {len(off)} of {len(reported)} cases (bad line {off[0]} reported as {reported[off[0]]})"
    return PASS, f"all {len(reported)} cases name the right line"


def check_control_bake(output: str) -> tuple[str, str]:
    word = result_word(output)
    if word == "STUCK":
        return FAIL, "RESULT STUCK: the size stays stretched"
    if word == "SHRINKS":
        return PASS, "RESULT SHRINKS"
    return ERROR, f"RESULT {word or 'missing'}"


CHECKS: dict[str, Callable[[str], tuple[str, str]]] = {
    "float_parse": check_float_parse,
    "format_6f": check_format_6f,
    "class_name_cache": check_class_name_cache,
    "crash_runner": check_crash_runner,
    "rename": check_rename,
    "configfile": check_configfile,
    "control_bake": check_control_bake,
}


# --- running repros --------------------------------------------------------------------------

def _run(cmd: list[str], env: dict, cwd: Path | None = None) -> str:
    try:
        done = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, errors="replace",
                              timeout=TIMEOUT_S, creationflags=NO_WINDOW, check=False)
        return done.stdout + done.stderr
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return out + f"\nTIMEOUT after {TIMEOUT_S} s"


def _isolated_env(tmp: Path) -> dict:
    env = dict(os.environ)
    for key in ("APPDATA", "LOCALAPPDATA", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        env[key] = str(tmp / "home" / key.lower())
        os.makedirs(env[key], exist_ok=True)
    return env


def run_finding(f: Finding, godot: str) -> dict:
    """Run one finding's repro headless from a temp copy and return its verdict record."""
    check = CHECKS.get(f.check)
    if check is None:
        return {"finding": f.finding, "verdict": ERROR, "detail": f"no check named {f.check!r}"}
    with tempfile.TemporaryDirectory(prefix="findings-") as tmp_name:
        tmp = Path(tmp_name)
        env = _isolated_env(tmp)
        repros = tmp / "repros"
        shutil.copytree(ROOT / "repros", repros, ignore=shutil.ignore_patterns(".godot", "__pycache__"))
        repro = repros / Path(f.repro).relative_to("repros")
        if f.check == "crash_runner":
            output = _run([sys.executable, str(repro), "--project", "project-compile-error", godot], env)
        elif f.check == "class_name_cache":
            output = _run([godot, "--headless", "--path", str(repro), "-s", "res://main.gd"], env)
        else:
            output = _run([godot, "--headless", "--path", str(repros), "-s", repro.name], env)
    verdict, detail = check(output)
    print(f"finding {f.finding}: RESULT {verdict}: {detail}")
    return {"finding": f.finding, "verdict": verdict, "detail": detail}


def godot_version(godot: str) -> str:
    return _run([godot, "--headless", "--version"], dict(os.environ)).strip().splitlines()[-1]


# --- upstream state and the table ------------------------------------------------------------

def upstream_state(kind: str, number: str, gh: GhRunner = default_gh) -> str:
    try:
        data = json.loads(gh([kind, "view", number, "-R", UPSTREAM_REPO, "--json", "state,stateReason"]
                             if kind == "issue" else
                             [kind, "view", number, "-R", UPSTREAM_REPO, "--json", "state"]))
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        return f"{kind} {number} (state unread)"
    state = str(data.get("state", "")).lower()
    reason = str(data.get("stateReason") or "").lower().replace("_", " ")
    if kind == "issue" and state == "closed" and reason:
        return f"issue {number} closed, {reason}"
    return f"{kind} {number} {state}"


def upstream_cell(f: Finding, gh: GhRunner = default_gh) -> str:
    parts = [upstream_state("issue", n, gh) for n in f.issues]
    parts += [upstream_state("pr", n, gh) for n in f.prs]
    return "; ".join(parts) or "None linked"


RESULT_TEXT = {PASS: "Not reproduced", FAIL: "Still reproduces", ERROR: "Run error"}
RUNNER_TEXT = {"linux": "Linux", "windows": "Windows"}


def build_table(rows: list[Finding], results: dict[str, dict], build: str, date: str,
                gh: GhRunner = default_gh, runner_label: dict[str, str] | None = None) -> str:
    labels = runner_label or RUNNER_TEXT
    lines = [f"Last status run: {date}, Godot {build} (official build). "
             "`Not reproduced` means the repro's check passed on that build; it is not a fix claim.",
             "",
             "| # | Finding | Runner | Result | Upstream |",
             "|---|---|---|---|---|"]
    for f in rows:
        if f.check == "not_tracked":
            runner, result, upstream = "None", "Not tracked", "Not tracked"
        elif f.runner == "none":
            runner, result, upstream = "None", "Not run (issue state only)", upstream_cell(f, gh)
        else:
            runner = labels.get(f.runner, f.runner)
            got = results.get(f.finding)
            if got is None:
                result = "Not run"
            else:
                result = f"{RESULT_TEXT[got['verdict']]}: {got['detail']}"
            upstream = upstream_cell(f, gh)
        lines.append(f"| {f.finding} | {f.title.replace('|', '/')} | {runner} | {result} | {upstream} |")
    return "\n".join(lines) + "\n"


def replace_status(readme: str, table: str) -> str:
    start, end = readme.find(START), readme.find(END)
    if start < 0 or end < start:
        raise ValueError("README has no status markers")
    return readme[:start + len(START)] + "\n" + table + readme[end:]


# --- guard: PII scan and diff scope ----------------------------------------------------------

PII_RULES = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@(?![A-Za-z0-9.-]*noreply\.github\.com)[A-Za-z0-9-]+\.[A-Za-z0-9.-]*[A-Za-z]"),
    "windows user folder": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!<user>)[^\\/\s\"'<>]+", re.IGNORECASE),
    "unix home folder": re.compile(r"(?<![\w.])/(?:home|Users)/(?!runner\b)[a-z][\w.-]+", re.IGNORECASE),
    "local drive path": re.compile(r"(?<![\w])[D-Zd-z]:\\[A-Za-z]"),
}


def pii_hits(text: str) -> dict[str, int]:
    """Counts per rule; the matched text is never returned."""
    return {name: len(rule.findall(text)) for name, rule in PII_RULES.items() if rule.search(text)}


def scan_tracked(root: Path = ROOT) -> dict[str, dict[str, int]]:
    files = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True,
                           creationflags=NO_WINDOW).stdout.decode().split("\0")
    found = {}
    for name in filter(None, files):
        path = root / name
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        hits = pii_hits(text)
        if hits:
            found[name] = hits
    return found


def outside_markers(readme: str) -> str:
    start, end = readme.find(START), readme.find(END)
    return readme if start < 0 or end < start else readme[:start] + readme[end:]


def without_build(csv_text: str) -> str:
    rows = load_findings(csv_text)
    for r in rows:
        r.build = ""
    return dump_findings(rows)


def scope_problems(changed: list[str], old: dict[str, str], new: dict[str, str]) -> list[str]:
    """Problems with a diff that should touch only the status table and the build column."""
    problems = [f"{name} may not change" for name in changed if name not in ("README.md", "findings.csv")]
    if "README.md" in changed and outside_markers(old["README.md"]) != outside_markers(new["README.md"]):
        problems.append("README.md changed outside the status markers")
    if "findings.csv" in changed and without_build(old["findings.csv"]) != without_build(new["findings.csv"]):
        problems.append("findings.csv changed outside the build column")
    return problems


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True,
                          creationflags=NO_WINDOW).stdout


def guard() -> int:
    status = 0
    found = scan_tracked()
    for name, hits in sorted(found.items()):
        print(f"PII scan: {name}: " + ", ".join(f"{rule} x{n}" for rule, n in hits.items()))
        status = 1
    changed = [line for line in _git("diff", "--name-only", "HEAD").splitlines() if line]
    changed += [line for line in _git("ls-files", "--others", "--exclude-standard").splitlines() if line]
    in_head = set(_git("ls-tree", "--name-only", "HEAD").splitlines())
    problems = [f"{n} is new, so this is not a status update" for n in changed if n not in in_head]
    kept = [n for n in changed if n in in_head]
    old = {n: _git("show", f"HEAD:{n}") for n in ("README.md", "findings.csv") if n in kept}
    new = {n: (ROOT / n).read_text(encoding="utf-8") for n in old}
    for problem in problems + scope_problems(kept, old, new):
        print(f"diff scope: {problem}")
        status = 1
    print("guard: " + ("FAIL" if status else "PASS"))
    return status


# --- commands --------------------------------------------------------------------------------

def _select(rows: list[Finding], ids: str | None, runnable_only: bool = True) -> list[Finding]:
    wanted = set(ids.split(",")) if ids else None
    return [r for r in rows if (wanted is None or r.finding in wanted)
            and (not runnable_only or r.check in CHECKS)]


def cmd_latest(args: argparse.Namespace) -> int:
    rows = load_findings(FINDINGS_CSV.read_text(encoding="utf-8"))
    tag, recorded = latest_release(), recorded_build(rows)
    newer = is_newer(tag, recorded)
    print(f"latest {tag}; recorded {recorded}; newer: {str(newer).lower()}")
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as out:
            out.write(f"tag={tag}\nnewer={str(newer).lower()}\n")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rows = _select(load_findings(FINDINGS_CSV.read_text(encoding="utf-8")), args.findings)
    with tempfile.TemporaryDirectory(prefix="godot-build-") as tmp:
        godot = args.godot or str(download_build(args.tag, args.platform, Path(tmp)))
        results = [run_finding(f, godot) for f in rows]
    Path(args.out).write_text(json.dumps({"build": args.tag, "platform": args.platform,
                                          "results": results}, indent=2) + "\n", encoding="utf-8")
    return 0


def _load_results(paths: list[str]) -> tuple[dict[str, dict], str]:
    merged, build = {}, ""
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        build = data.get("build", build)
        for r in data["results"]:
            merged[r["finding"]] = r
    return merged, build


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def cmd_table(args: argparse.Namespace) -> int:
    rows = load_findings(FINDINGS_CSV.read_text(encoding="utf-8"))
    results, build = _load_results(args.results)
    table = build_table(rows, results, build, _today())
    if args.out:
        Path(args.out).write_text(table, encoding="utf-8")
    else:
        readme = Path(args.readme)
        readme.write_text(replace_status(readme.read_text(encoding="utf-8"), table), encoding="utf-8")
    if args.record_build:
        for r in rows:
            if r.check in CHECKS:
                r.build = build
        FINDINGS_CSV.write_text(dump_findings(rows), encoding="utf-8")
    return 0


def cmd_local(args: argparse.Namespace) -> int:
    rows = load_findings(FINDINGS_CSV.read_text(encoding="utf-8"))
    host = "windows" if os.name == "nt" else "linux"
    results = {f.finding: run_finding(f, args.godot) for f in _select(rows, args.findings)}
    label = {k: f"{RUNNER_TEXT[host]} (local; CI runs it on {v})" if k != host else f"{v} (local)"
             for k, v in RUNNER_TEXT.items()}
    table = build_table(rows, results, godot_version(args.godot), _today(), runner_label=label)
    Path(args.out).write_text(table, encoding="utf-8")
    print(f"table written to {args.out}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("latest")
    p.add_argument("--github-output")
    p.set_defaults(func=cmd_latest)
    p = sub.add_parser("run")
    p.add_argument("--platform", choices=["linux", "windows"], required=True)
    p.add_argument("--findings")
    p.add_argument("--tag", required=True)
    p.add_argument("--godot", help="use this binary instead of downloading")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("table")
    p.add_argument("--results", nargs="+", required=True)
    p.add_argument("--readme", default=str(README))
    p.add_argument("--out")
    p.add_argument("--record-build", action="store_true")
    p.set_defaults(func=cmd_table)
    p = sub.add_parser("local")
    p.add_argument("--godot", required=True)
    p.add_argument("--findings")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_local)
    p = sub.add_parser("guard")
    p.set_defaults(func=lambda _args: guard())
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
