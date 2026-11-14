"""Run the 124160 repro headlessly against one or more Godot binaries and classify the outcome.

Usage: python run_repro.py [--project NAME] [path-to-godot ...]
       (default build: `godot` on PATH; default project: `project`)

Two projects sit beside this folder:

  project                the base fails at the PARSE stage (an undeclared class). Read by load()
                         only, so main.gd itself compiles.
  project-compile-error  the issue reporter's shorter variant: the base fails at the COMPILE stage
                         (it names an autoload a `-s` run does not know yet), and main.gd names
                         the derived class directly.

Copies the chosen project to a temp folder, points APPDATA there (editor settings stay
untouched), runs one `--import` pass so the class_name cache knows every script, then
`-s res://main.gd`, all `--headless`. Prints the repro's own lines and the engine's errors, then
one verdict line:

  RESULT CRASH       the process died (a signal, a Windows access violation, or Godot's crash
                     handler banner) before main.gd printed its RESULT line
  RESULT NO_CRASH    main.gd instantiated the derived script and used it
  RESULT REFUSED     the engine refused the derived script cleanly (load, can_instantiate or new)
  RESULT NO_RESULT   none of the above, a timeout included: the output tail follows

Exit code: 0 when a verdict was reached, 2 for NO_RESULT, 1 when no binary or project was found.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECTS = ("project", "project-compile-error")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KEPT = ("REPRO", "RESULT", "ERROR", "SCRIPT ERROR", "Parse Error", "  at:", "handle_crash",
        "CrashHandlerException", "Program crashed")
CRASH_MARKERS = ("Program crashed with signal", "CrashHandlerException", "handle_crash:")
# 0xC0000005 access violation and 0xC0000409 stack buffer overrun, as unsigned and signed exit codes.
WINDOWS_CRASH_CODES = {0xC0000005, 0xC0000409, 0xC0000005 - 2**32, 0xC0000409 - 2**32}
TIMEOUT_S = 120
# A script error under `-s` leaves the engine running (quit() is never reached), so a refusal
# that raises a script error ends as a timeout. This exit code marks it for classify().
TIMED_OUT = 124


def _text(data: str | bytes | None) -> str:
    if isinstance(data, bytes):
        return data.decode(errors="replace")
    return data or ""


def run(godot: str, project: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    cmd = [godot, "--headless", "--path", str(project), *args]
    try:
        return subprocess.run(
            cmd, env=env, capture_output=True, text=True, errors="replace",
            timeout=TIMEOUT_S, creationflags=NO_WINDOW, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(cmd, TIMED_OUT, _text(exc.stdout), _text(exc.stderr))


def classify(returncode: int, output: str) -> tuple[str, str]:
    """Return (verdict, detail) from the -s run's exit code and combined output."""
    results = [line for line in output.splitlines() if line.startswith("RESULT ")]
    if results:
        word = results[-1].split()[1].rstrip(":")
        if word in ("NO_CRASH", "REFUSED"):
            return word, results[-1]
    if returncode in WINDOWS_CRASH_CODES:
        return "CRASH", f"exit code 0x{returncode & 0xFFFFFFFF:08X}"
    if returncode < 0:
        return "CRASH", f"killed by signal {-returncode}"
    if any(marker in output for marker in CRASH_MARKERS):
        return "CRASH", f"crash handler output, exit code {returncode}"
    if returncode == TIMED_OUT:
        return "NO_RESULT", f"no exit within {TIMEOUT_S} s (a -s script error leaves the engine running)"
    return "NO_RESULT", f"exit code {returncode}, no RESULT line"


def probe(godot: str, project_name: str = "project") -> tuple[str, str, list[str], list[str]]:
    with tempfile.TemporaryDirectory(prefix="repro124160-") as tmp:
        project = Path(tmp) / "project"
        shutil.copytree(HERE.parent / project_name, project)
        env = dict(os.environ, APPDATA=str(Path(tmp) / "appdata"))
        os.makedirs(env["APPDATA"])
        run(godot, project, env, "--import")
        done = run(godot, project, env, "-s", "res://main.gd")
    output = done.stdout + done.stderr
    verdict, detail = classify(done.returncode, output)
    kept = [line for line in output.splitlines() if line.startswith(KEPT)]
    return verdict, detail, kept, output.splitlines()[-40:]


def parse_args(argv: list[str]) -> tuple[str, list[str]]:
    """Return (project name, build names). `--project NAME` may appear once, anywhere."""
    args = list(argv)
    project_name = "project"
    if "--project" in args:
        i = args.index("--project")
        if i + 1 >= len(args):
            raise ValueError("--project needs a name, one of: " + ", ".join(PROJECTS))
        project_name = args[i + 1]
        del args[i:i + 2]
    if project_name not in PROJECTS:
        raise ValueError(f"unknown project {project_name!r}, one of: " + ", ".join(PROJECTS))
    return project_name, args or ["godot"]


def main(argv: list[str]) -> int:
    try:
        project_name, names = parse_args(argv)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    godots = [shutil.which(name) for name in names]
    missing = [name for name, found in zip(names, godots) if found is None]
    if missing:
        print(f"Godot binary not found: {', '.join(missing)}", file=sys.stderr)
        return 1
    status = 0
    for godot in godots:
        verdict, detail, kept, tail = probe(godot, project_name)
        if len(godots) > 1:
            print(f"== {godot}")
        print("\n".join(line for line in kept if not line.startswith("RESULT")))
        if verdict == "NO_RESULT":
            print("\n".join(tail))
            status = 2
        print(f"RESULT {verdict}: {detail}")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
