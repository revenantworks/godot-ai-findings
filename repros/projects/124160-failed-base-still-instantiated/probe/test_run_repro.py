"""Tests for run_repro.py. They run fake Godot binaries, so no engine is needed.

    python -m pytest contributions -q
"""
from __future__ import annotations

import json
import os
import signal
import stat
import sys
from pathlib import Path

import pytest
import run_repro

FAKE = r'''
import json, os, signal, sys
from pathlib import Path
MODE, LOG = {mode!r}, {log!r}
args = sys.argv[1:]
with open(LOG, "a", encoding="utf-8") as f:
    f.write(json.dumps({{"args": args, "appdata": os.environ.get("APPDATA", "")}}) + "\n")
project = Path(args[args.index("--path") + 1])
if "--import" in args:
    (project / ".godot").mkdir(exist_ok=True)
    sys.exit(0)
print("Godot Engine v4.7.2.stable.official")
print("SCRIPT ERROR: Parse Error: Identifier \"NoSuchClass\" not declared in the current scope.")
print("noise line the runner must drop")
if not (project / ".godot").exists() or not (project / "main.gd").exists():
    sys.exit(0)
print("REPRO loaded derived=true")
if MODE == "signal":
    sys.stdout.flush()
    os.kill(os.getpid(), signal.SIGSEGV)
if MODE == "banner":
    print("handle_crash: Program crashed with signal 11")
    sys.exit(1)
if MODE == "no_crash":
    print("RESULT NO_CRASH: instantiated and called both methods (engine 4.7.2)")
if MODE == "refused":
    print("RESULT REFUSED: can_instantiate() is false (engine 4.7.2)")
'''


def make_fake(tmp_path: Path, mode: str) -> tuple[str, Path]:
    log = tmp_path / f"{mode}.log"
    script = tmp_path / f"fake_godot_{mode}.py"
    script.write_text(FAKE.format(mode=mode, log=str(log)), encoding="utf-8")
    if os.name == "nt":
        launcher = tmp_path / f"{mode}.bat"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = tmp_path / f"godot-{mode}"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    return str(launcher), log


def last_line(out: str) -> str:
    return out.strip().splitlines()[-1]


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="POSIX signals only")
def test_a_segfault_is_a_crash(tmp_path, capsys):
    godot, _ = make_fake(tmp_path, "signal")
    assert run_repro.main([godot]) == 0
    assert last_line(capsys.readouterr().out) == f"RESULT CRASH: killed by signal {int(signal.SIGSEGV)}"


def test_godot_crash_banner_is_a_crash(tmp_path, capsys):
    godot, _ = make_fake(tmp_path, "banner")
    assert run_repro.main([godot]) == 0
    out = capsys.readouterr().out
    assert "handle_crash: Program crashed with signal 11" in out
    assert last_line(out) == "RESULT CRASH: crash handler output, exit code 1"


def test_no_crash_keeps_the_repro_and_error_lines(tmp_path, capsys):
    godot, log = make_fake(tmp_path, "no_crash")
    assert run_repro.main([godot]) == 0
    out = capsys.readouterr().out
    assert "noise line" not in out
    assert "REPRO loaded derived=true" in out
    assert "Parse Error" in out
    assert last_line(out).startswith("RESULT NO_CRASH: RESULT NO_CRASH: instantiated")
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [c["args"][3:] for c in calls] == [["--import"], ["-s", "res://main.gd"]]
    assert all(c["args"][0] == "--headless" for c in calls)
    appdata = {c["appdata"] for c in calls}
    assert len(appdata) == 1 and not Path(appdata.pop()).exists()


def test_clean_refusal(tmp_path, capsys):
    godot, _ = make_fake(tmp_path, "refused")
    assert run_repro.main([godot]) == 0
    assert last_line(capsys.readouterr().out).startswith("RESULT REFUSED")


def test_silence_is_no_result_with_tail(tmp_path, capsys):
    godot, _ = make_fake(tmp_path, "silent")
    assert run_repro.main([godot]) == 2
    out = capsys.readouterr().out
    assert "noise line the runner must drop" in out  # the tail is printed for diagnosis
    assert last_line(out) == "RESULT NO_RESULT: exit code 0, no RESULT line"


def test_missing_binary(tmp_path, capsys):
    assert run_repro.main([str(tmp_path / "nope")]) == 1
    assert "not found" in capsys.readouterr().err


@pytest.mark.parametrize("code, detail", [
    (0xC0000005, "exit code 0xC0000005"),
    (-1073741819, "exit code 0xC0000005"),
    (0xC0000409, "exit code 0xC0000409"),
])
def test_windows_crash_codes(code, detail):
    assert run_repro.classify(code, "") == ("CRASH", detail)


def test_a_result_line_wins_over_a_nonzero_exit():
    assert run_repro.classify(1, "RESULT REFUSED: new() returned null (engine x)")[0] == "REFUSED"


def test_the_shipped_project_matches_the_story():
    project = Path(run_repro.HERE).parent / "project"
    base = (project / "broken_base.gd").read_text(encoding="utf-8")
    derived = (project / "derived.gd").read_text(encoding="utf-8")
    main = (project / "main.gd").read_text(encoding="utf-8")
    assert "class_name BrokenBase" in base and "NoSuchClass.new()" in base
    assert "extends BrokenBase" in derived
    # main.gd must reach derived.gd by path only, or main.gd itself would fail to compile.
    assert 'load("res://derived.gd")' in main
    assert "DerivedFromBroken" not in main and "BrokenBase" not in main


def test_the_compile_error_project_matches_the_story():
    project = Path(run_repro.HERE).parent / "project-compile-error"
    settings = (project / "project.godot").read_text(encoding="utf-8")
    base = (project / "base.gd").read_text(encoding="utf-8")
    derived = (project / "derived.gd").read_text(encoding="utf-8")
    main = (project / "main.gd").read_text(encoding="utf-8")
    # The base parses but fails to compile: it names the autoload, unknown to a `-s` run.
    assert 'Auto="*res://auto.gd"' in settings
    assert "class_name Base124" in base and "Auto.name" in base and "Array[int]" in base
    assert "extends Base124" in derived
    # The reporter's shorter variant names the derived class directly and iterates the array.
    assert "Derived124.new()" in main and "for x in d.list" in main


def test_parse_args_defaults_and_project():
    assert run_repro.parse_args([]) == ("project", ["godot"])
    name = "project-compile-error"
    assert run_repro.parse_args(["--project", name]) == (name, ["godot"])
    assert run_repro.parse_args(["a", "--project", "project", "b"]) == ("project", ["a", "b"])


@pytest.mark.parametrize("argv", [["--project"], ["--project", "nope"]])
def test_parse_args_refuses_a_bad_project(argv, capsys):
    assert run_repro.main(argv) == 1
    assert "one of: project, project-compile-error" in capsys.readouterr().err


def test_a_timeout_is_no_result():
    verdict, detail = run_repro.classify(run_repro.TIMED_OUT, "SCRIPT ERROR: Invalid call.")
    assert verdict == "NO_RESULT" and "no exit within" in detail
