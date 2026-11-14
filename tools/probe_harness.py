"""Run one draft's headless editor probe against one or more Godot binaries.

    python tools/probe_harness.py <draft-folder> [godot ...]

A draft folder holds `project/` (the minimal project) and `probe/addons/<name>/plugin.cfg` (an
EditorPlugin that prints `PROBE ...` lines and one `RESULT <WORD>: <detail>` line). For each
binary the harness copies the project and the probe addon to a temp folder, enables every probe
plugin there, points APPDATA at the temp folder (so the editor's settings and project list stay
untouched), runs `--import` then `--editor`, all with `--headless`, and keeps the probe's lines.

With no binary it runs `godot` on PATH . With one binary it prints the probe's
lines, as each draft's own `run_probe.py` always has. With two or more it also prints a Markdown
table (build, commit, result) ready for a version table.

Exit code: 0 when every binary printed a RESULT line, 2 when any did not, 1 on a usage error.
Environment variables such as PROBE_DUMP pass through to the editor.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KEPT_PREFIXES = ("PROBE", "RESULT", "ERROR", "SCRIPT ERROR")
RESULT_RE = re.compile(r"^RESULT (\S+?):?(?:\s+(.*))?$")
VERSION_RE = re.compile(r"^(\d+\.\d+(?:\.\d+)?)\.([A-Za-z0-9]+)\.([A-Za-z0-9_]+)\.([0-9a-f]{6,40})$")
TIMEOUT_S = 240


class HarnessError(Exception):
    """A draft folder or binary the harness cannot use."""


@dataclass
class ProbeRun:
    godot: str
    version: str
    lines: list[str] = field(default_factory=list)
    tail: list[str] = field(default_factory=list)

    @property
    def result_line(self) -> str | None:
        found = [line for line in self.lines if line.startswith("RESULT")]
        return found[-1] if found else None

    @property
    def result(self) -> str:
        """The word after RESULT (KEPT, RESET, BLANK, ...), or NO_RESULT."""
        line = self.result_line
        if line is None:
            return "NO_RESULT"
        match = RESULT_RE.match(line)
        return match.group(1) if match else "NO_RESULT"


def find_plugins(draft: Path) -> list[str]:
    """Return the res:// path of every probe plugin.cfg under probe/addons, sorted."""
    addons = draft / "probe" / "addons"
    cfgs = sorted(addons.glob("*/plugin.cfg"))
    if not cfgs:
        raise HarnessError(f"no probe plugin under {addons}")
    return [f"res://addons/{cfg.parent.name}/plugin.cfg" for cfg in cfgs]


def stage_project(draft: Path, dest: Path) -> Path:
    """Copy the draft's project and probe addons to dest/project and enable the probe plugins."""
    source = draft / "project"
    if not (source / "project.godot").is_file():
        raise HarnessError(f"no project.godot in {source}")
    plugins = find_plugins(draft)
    project = dest / "project"
    shutil.copytree(source, project)
    shutil.copytree(draft / "probe" / "addons", project / "addons", dirs_exist_ok=True)
    settings = project / "project.godot"
    text = settings.read_text(encoding="utf-8")
    if re.search(r"^\[editor_plugins\]", text, re.MULTILINE):
        raise HarnessError(f"{source / 'project.godot'} already has an [editor_plugins] section")
    listed = ", ".join(f'"{p}"' for p in plugins)
    with open(settings, "a", encoding="utf-8", newline="\n") as f:
        f.write(f"\n[editor_plugins]\n\nenabled=PackedStringArray({listed})\n")
    return project


def run_godot(godot: str, project: Path | None, env: dict, *args: str) -> str:
    cmd = [godot, "--headless"]
    if project is not None:
        cmd += ["--path", str(project)]
    done = subprocess.run(
        [*cmd, *args], env=env, capture_output=True, text=True, errors="replace",
        timeout=TIMEOUT_S, creationflags=NO_WINDOW, check=False,
    )
    return done.stdout + done.stderr


def keep_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith(KEPT_PREFIXES)]


def resolve_godot(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise HarnessError(f"Godot binary not found: {name}")
    return found


def godot_version(godot: str, env: dict) -> str:
    out = run_godot(godot, None, env, "--version")
    for line in reversed(out.splitlines()):
        line = line.strip()
        if VERSION_RE.match(line):
            return line
    return "unknown"


def run_probe(draft: Path, godot: str) -> ProbeRun:
    """Stage the draft in a temp folder and run its probe once against one binary."""
    with tempfile.TemporaryDirectory(prefix=f"probe-{draft.name[:20]}-") as tmp:
        project = stage_project(draft, Path(tmp))
        env = dict(os.environ, APPDATA=str(Path(tmp) / "appdata"))
        os.makedirs(env["APPDATA"])
        version = godot_version(godot, env)
        run_godot(godot, project, env, "--import")
        output = run_godot(godot, project, env, "--editor")
    return ProbeRun(godot=godot, version=version, lines=keep_lines(output),
                    tail=output.splitlines()[-40:])


def split_version(version: str) -> tuple[str, str]:
    """'4.8.beta3.official.c51ff06e8' -> ('4.8-beta3', 'c51ff06e8'). Unknown text passes through."""
    match = VERSION_RE.match(version)
    if not match:
        return version, "unknown"
    number, status, _build, commit = match.groups()
    return f"{number}-{status}", commit[:9]


def table(runs: list[ProbeRun]) -> str:
    rows = ["| Build | Commit | Probe result |", "|---|---|---|"]
    for run in runs:
        build, commit = split_version(run.version)
        rows.append(f"| {build} | `{commit}` | `RESULT {run.result}` |")
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 1 if not argv else 0
    draft = Path(argv[0]).resolve()
    binaries = argv[1:] or ["godot"]
    try:
        godots = [resolve_godot(name) for name in binaries]
        find_plugins(draft)
        runs = []
        for godot in godots:
            run = run_probe(draft, godot)
            runs.append(run)
            if len(godots) > 1:
                print(f"== {run.version} ({godot})")
            print("\n".join(run.lines))
            if run.result_line is None:
                print("NO RESULT LINE. Full output tail:")
                print("\n".join(run.tail))
    except HarnessError as err:
        print(f"probe_harness: {err}", file=sys.stderr)
        return 1
    if len(runs) > 1:
        print()
        print(table(runs))
    return 0 if all(run.result_line for run in runs) else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
