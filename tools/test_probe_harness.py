"""Tests for probe_harness.py. They run fake Godot binaries, so no engine is needed.

    python -m pytest tools
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import probe_harness as ph
import pytest

REPO = Path(__file__).resolve().parents[1]
DRAFTS = REPO / "repros" / "projects"

FAKE = r'''
import json, os, sys
from pathlib import Path
VERSION, RESULT, LOG = {version!r}, {result!r}, {log!r}
args = sys.argv[1:]
with open(LOG, "a", encoding="utf-8") as f:
    f.write(json.dumps({{"args": args, "appdata": os.environ.get("APPDATA", "")}}) + "\n")
if "--version" in args:
    print("Godot Engine banner line")
    print(VERSION)
    sys.exit(0)
project = Path(args[args.index("--path") + 1])
if "--import" in args:
    (project / ".godot").mkdir(exist_ok=True)
    (project / ".godot" / "imported").write_text("yes")
    sys.exit(0)
text = (project / "project.godot").read_text(encoding="utf-8")
enabled = [line for line in text.splitlines() if line.startswith("enabled=")]
print("Godot Engine v" + VERSION)
print("noise line the harness must drop")
if not (project / ".godot" / "imported").exists():
    print("RESULT NOT_DRIVEN: editor ran before import")
    sys.exit(0)
print("PROBE plugins " + (enabled[0] if enabled else "none"))
if RESULT:
    print("RESULT " + RESULT + ": detail (engine " + VERSION + ")")
'''


def make_fake(tmp_path: Path, name: str, version: str, result: str | None) -> tuple[str, Path]:
    log = tmp_path / f"{name}.log"
    script = tmp_path / f"{name}.py"
    script.write_text(FAKE.format(version=version, result=result, log=str(log)), encoding="utf-8")
    if os.name == "nt":
        launcher = tmp_path / f"{name}.bat"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = tmp_path / name
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    return str(launcher), log


def calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def make_draft(tmp_path: Path, plugins=("probe_x",), extra_settings: str = "") -> Path:
    draft = tmp_path / "draft"
    (draft / "project").mkdir(parents=True)
    (draft / "project" / "project.godot").write_text(
        "config_version=5\n" + extra_settings, encoding="utf-8")
    for name in plugins:
        addon = draft / "probe" / "addons" / name
        addon.mkdir(parents=True)
        (addon / "plugin.cfg").write_text('[plugin]\nscript="plugin.gd"\n', encoding="utf-8")
    return draft


def test_both_real_drafts_are_found():
    assert ph.find_plugins(DRAFTS / "125030-snap-primary-line-reset") == [
        "res://addons/probe_125030/plugin.cfg"]
    assert ph.find_plugins(DRAFTS / "125035-tile-inspector-blank") == [
        "res://addons/probe_125035/plugin.cfg"]


def test_stage_enables_every_plugin_and_leaves_source_clean(tmp_path):
    draft = make_draft(tmp_path, plugins=("probe_b", "probe_a"))
    before = (draft / "project" / "project.godot").read_text(encoding="utf-8")
    project = ph.stage_project(draft, tmp_path / "stage")
    text = (project / "project.godot").read_text(encoding="utf-8")
    assert text.startswith(before)
    assert ('enabled=PackedStringArray("res://addons/probe_a/plugin.cfg", '
            '"res://addons/probe_b/plugin.cfg")') in text
    assert (project / "addons" / "probe_a" / "plugin.cfg").is_file()
    assert (draft / "project" / "project.godot").read_text(encoding="utf-8") == before
    assert not (draft / "project" / "addons").exists()


def test_stage_refuses_a_project_that_already_lists_plugins(tmp_path):
    draft = make_draft(tmp_path, extra_settings='\n[editor_plugins]\n\nenabled=PackedStringArray()\n')
    with pytest.raises(ph.HarnessError, match="editor_plugins"):
        ph.stage_project(draft, tmp_path / "stage")


def test_draft_without_probe_is_a_usage_error(tmp_path, capsys):
    draft = make_draft(tmp_path, plugins=())
    godot, _ = make_fake(tmp_path, "godot", "4.7.2.stable.official.ed1daf0bf", "KEPT")
    assert ph.main([str(draft), godot]) == 1
    assert "no probe plugin" in capsys.readouterr().err


def test_missing_binary_is_a_usage_error(tmp_path, capsys):
    draft = make_draft(tmp_path)
    assert ph.main([str(draft), str(tmp_path / "no-such-godot")]) == 1
    assert "not found" in capsys.readouterr().err


def test_one_binary_runs_headless_import_then_editor_in_a_temp_appdata(tmp_path, capsys):
    draft = make_draft(tmp_path)
    godot, log = make_fake(tmp_path, "godot", "4.8.beta3.official.c51ff06e8", "RESET")
    assert ph.main([str(draft), godot]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        'PROBE plugins enabled=PackedStringArray("res://addons/probe_x/plugin.cfg")',
        "RESULT RESET: detail (engine 4.8.beta3.official.c51ff06e8)",
    ]
    seen = calls(log)
    assert [c["args"][-1] for c in seen] == ["--version", "--import", "--editor"]
    assert all(c["args"][0] == "--headless" for c in seen)
    appdata = {c["appdata"] for c in seen}
    assert len(appdata) == 1 and appdata != {os.environ.get("APPDATA", "")}
    assert not Path(appdata.pop()).exists()  # the temp folder is gone afterwards


def test_no_result_line_prints_the_tail_and_exits_2(tmp_path, capsys):
    draft = make_draft(tmp_path)
    godot, _ = make_fake(tmp_path, "godot", "4.7.2.stable.official.ed1daf0bf", None)
    assert ph.main([str(draft), godot]) == 2
    out = capsys.readouterr().out
    assert "NO RESULT LINE" in out
    assert "noise line the harness must drop" in out


def test_several_binaries_print_a_findings_table(tmp_path, capsys):
    draft = make_draft(tmp_path)
    old, _ = make_fake(tmp_path, "old", "4.7.2.stable.official.ed1daf0bf", "KEPT")
    new, _ = make_fake(tmp_path, "new", "4.8.beta3.official.c51ff06e8", "RESET")
    assert ph.main([str(draft), old, new]) == 0
    out = capsys.readouterr().out
    assert out.rstrip().endswith(
        "| Build | Commit | Probe result |\n"
        "|---|---|---|\n"
        "| 4.7.2-stable | `ed1daf0bf` | `RESULT KEPT` |\n"
        "| 4.8-beta3 | `c51ff06e8` | `RESULT RESET` |")


@pytest.mark.parametrize("version, expected", [
    ("4.7.2.stable.official.ed1daf0bf", ("4.7.2-stable", "ed1daf0bf")),
    ("4.8.beta3.official.c51ff06e8", ("4.8-beta3", "c51ff06e8")),
    ("4.6.4.rc.custom_build.3b853ac6f", ("4.6.4-rc", "3b853ac6f")),
    ("unknown", ("unknown", "unknown")),
])
def test_split_version(version, expected):
    assert ph.split_version(version) == expected


@pytest.mark.parametrize("line, word", [
    ("RESULT BLANK: inspector edits nothing (engine x)", "BLANK"),
    ("RESULT KEPT", "KEPT"),
    ("RESULT NOT_DRIVEN: dialog not found", "NOT_DRIVEN"),
])
def test_result_word(line, word):
    assert ph.ProbeRun(godot="g", version="v", lines=["PROBE a", line]).result == word


def test_draft_wrapper_still_takes_a_binary_argument(tmp_path):
    godot, log = make_fake(tmp_path, "godot", "4.6.3.stable.official.7d41c59c4", "FILLED")
    wrapper = DRAFTS / "125035-tile-inspector-blank" / "probe" / "run_probe.py"
    done = subprocess.run([sys.executable, str(wrapper), godot], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().splitlines()[-1].startswith("RESULT FILLED")
    assert "res://addons/probe_125035/plugin.cfg" in done.stdout
    assert len(calls(log)) == 3
