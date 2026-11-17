# Godot engine findings (AI-assisted)

Everything in this repo was found with AI help. Not all of it has been checked by a human.
Each finding says how far it was checked: **Human-checked**, **AI-run** (an AI session ran the
repro and read the result) or **Unverified** (read from source or seen in a game, not run).

Upstream issue states were read on the dates given and may have changed since. "None found"
means a search found nothing, not that no report exists.

## Summary

| # | Finding | Godot | Status | Godot issue |
|---|---|---|---|---|
| 1 | Float parsing is not correctly rounded | 4.7.2 | AI-run, Windows and Linux | 123700, 124516 |
| 2 | `"%.6f" % x` misrounds on Windows | 4.7.2 | AI-run, Windows and Linux | 125468 (closed, not planned) |
| 3 | A new `class_name` is unknown to `-s` until `--import` | 4.7.2 | AI-run, Linux | None open (editor case: 92054, closed) |
| 4 | A script whose base failed to compile still runs, then crashes | 4.7.2 | AI-run, Linux | 124160 |
| 5 | Windows `DirAccess.rename` deletes the target before the move | 4.7.2 | Unverified on Windows | 118858 |
| 6 | ConfigFile parse errors name the line before the bad one | 4.7.2 | AI-run, Linux | None found |
| 7 | A Control stops shrinking to its minimum once `position` is set | 4.7.2 | AI-run, Linux | None found |
| 8 | TileSet tile inspector is blank on the 4.6 branch | 4.6 tip `3b853ac6f` | Human-checked | 125035 |
| 9 | Configure Snap resets Primary Line Every on Tab | 4.8-beta2, 4.8-beta3 | AI-run, Windows | 125030 |
| 10 | `sin`, `cos`, `atan2` differ in the last bit, Windows vs Linux | 4.7.2 | Unverified, no repro | None found |

## Status

A weekly workflow re-runs the repros on each new stable Godot build from godot-builds
(findings 1, 3, 4, 6 and 7 on Linux, 2 and 5 on Windows) and reads the linked issue and PR
states. It rewrites only the table between the markers below. `findings.csv` lists what it runs.

<!-- status:start -->
No status run yet. The weekly workflow fills this table.
<!-- status:end -->

## How to run

Single-script repros, headless, from the repo root:

```bash
godot --headless --path repros -s float_parse.gd
```

Project repros live in `repros/projects/<name>/`. Editor probes (8, 9) and the crash runner (4)
copy the project to a temp folder first, so nothing in the repo changes:

```bash
python repros/projects/125035-tile-inspector-blank/probe/run_probe.py godot
python repros/projects/124160-failed-base-still-instantiated/probe/run_repro.py --project project-compile-error godot
```

List more Godot binaries after the first to compare builds. Helper tests: `python -m pytest tools repros -q`.

## Findings

### 1. Float parsing is not correctly rounded

- **Godot / OS:** 4.7.2 official, Windows and Linux (same output on both).
- **Repro:** [`repros/float_parse.gd`](repros/float_parse.gd); pipe its output to [`repros/check_mismatches.py`](repros/check_mismatches.py).
- **Expected:** `"00000000000000000001.5".to_float()` is `1.5`; `"2.2250738585072014e-308".to_float()` is that number; text from `String.num_scientific()` parses back to the same double.
- **Actual:** both give `0.0`; 9,873 of 20,000 random doubles parse back to a different double, from 1 ulp up to whole values. Python reads the same text back exactly, so the parse is wrong, not the print.
- **Affects:** `float()`, `String.to_float()`, `str_to_var()`, `JSON.parse_string()`, GDScript literals.
- **Status:** AI-run 2026-10-18. Not checked by a human.
- **Godot issue:** 123700 (leading zeros; PR 123839 open), 124516 (rounding).

### 2. `"%.6f" % x` and `String.num(x, 6)` misround on Windows

- **Godot / OS:** 4.7.2 official. Windows 11 wrong; Linux x86_64 right.
- **Repro:** [`repros/format_6f.gd`](repros/format_6f.gd), run on both systems; compare with [`repros/check_format.py`](repros/check_format.py).
- **Expected:** correctly rounded output, as Python's `"%.6f"` gives (exact value, ties to even).
- **Actual (Windows):** about 1 in 17 values wrong at the 6th decimal. One run counted 11,729 of 199,694 distinct values; 3,297 are exact ties rounded away from even, the rest sit just below the halfway point and round up.

| Double (little-endian hex) | Exact value | Expected | Windows |
|---|---|---|---|
| `00000000b5a4c240` | 9545.4140625 | 9545.414062 | 9545.414063 |
| `e751f17fc7075fc0` | -124.12155149999999537... | -124.121551 | -124.121552 |
| `e7a8a3e36ac028c0` | -12.37581549999999985... | -12.375815 | -12.375816 |

- **Status:** AI-run 2026-10-18. Expected values re-checked with Python 2026-11-14. Windows output not re-run since. Cause not found.
- **Godot issue:** 125468 (closed as not planned, 2026-11-14).

### 3. A new `class_name` is unknown to a headless `-s` run until `--import`

- **Godot / OS:** 4.7.2 official, Linux x86_64, headless.
- **Repro:** [`repros/projects/92054-class-name-cache-headless/project/`](repros/projects/92054-class-name-cache-headless/project/). Delete its `.godot/`, then run `godot --headless --path <that folder> -s res://main.gd`.
- **Expected:** `main.gd` resolves `FreshClass` and prints `RESULT RESOLVED`.
- **Actual:** `Parse Error: Identifier "FreshClass" not declared in the current scope` on every `-s` run until one `godot --headless --import`. Each new `class_name` needs another import. May be by design: `-s` never scans the file system.
- **Status:** AI-run 2026-11-10. Windows not run.
- **Godot issue:** none open. The editor version (92054, also 72989 and 75684) was closed as fixed.

### 4. A script whose base failed to compile still runs, then crashes

- **Godot / OS:** 4.7.2 official, Linux x86_64, headless.
- **Repro:** [`repros/projects/124160-failed-base-still-instantiated/`](repros/projects/124160-failed-base-still-instantiated/), runner `probe/run_repro.py`. `project-compile-error/` crashes; `project/` (a parse-stage failure) is the control.
- **Expected:** the engine refuses to instantiate a script whose base failed to compile.
- **Actual:** `main.gd` runs anyway, `new()` returns an object with its base members never set up, and the first read of the typed array crashes with signal 11. The parse-stage control is refused cleanly.
- **Status:** AI-run 2026-11-10. Windows, 4.8 and `master` not run.
- **Godot issue:** 124160.

### 5. On Windows, `DirAccess.rename` deletes an existing target before it moves the file

- **Godot / OS:** 4.7.2, Windows (by source); Linux control.
- **Repro:** [`repros/rename_replace.gd`](repros/rename_replace.gd). It holds the source file open so the move fails.
- **Expected:** when the rename fails, the old target file is still there.
- **Actual (from source, not run):** `drivers/windows/dir_access_windows.cpp` removes the target, then calls `MoveFileW`; if the move fails, the target is gone. The repro should print `RESULT LOST_TARGET` on Windows. Linux prints `RESULT REPLACED`.
- **Status:** Unverified on Windows. Linux control AI-run 2026-11-10.
- **Godot issue:** 118858 (PR 118933 open).

### 6. ConfigFile parse errors name the line before the bad one

- **Godot / OS:** 4.7.2 official, Linux x86_64, headless.
- **Repro:** [`repros/configfile_line.gd`](repros/configfile_line.gd).
- **Expected:** a bad line on line 4 is reported as line 4, as a `.tres` with the same line is.
- **Actual:** bad lines on 1, 2, 4 and 6 are reported as `:0:`, `:1:`, `:3:` and `:5:`. The counter in `core/io/config_file.cpp` starts at 0.
- **Status:** AI-run 2026-11-10. Windows not run.
- **Godot issue:** none found.

### 7. A Control stops shrinking to its minimum once `position` is set

- **Godot / OS:** 4.7.2 official, Linux x86_64, headless.
- **Repro:** [`repros/control_position_bake.gd`](repros/control_position_bake.gd). Case A is the control.
- **Expected:** a Control outside any Container shrinks back when its minimum size drops, as it does when `position` is never written (case A).
- **Actual:** after `position` is set while stretched, the stretched size sticks: 200 px tall with a 50 px minimum (`RESULT STUCK`). May be intended.
- **Status:** AI-run 2026-11-10. Windows not run.
- **Godot issue:** none exact found (nearest: 96932, closed).

### 8. TileSet tile inspector is blank on the 4.6 branch

- **Godot / OS:** 4.6 branch tip `3b853ac6f`, built from source on Windows. Controls: 4.6.3 and 4.7.2 official.
- **Repro:** [`repros/projects/125035-tile-inspector-blank/`](repros/projects/125035-tile-inspector-blank/), probe `probe/run_probe.py`. By hand: open `tileset.tres`, pick the atlas source, Select tab, click a tile.
- **Expected:** the tile inspector lists the tile's properties (4.6.3 and 4.7.2 show 15).
- **Actual:** the inspector stays blank (`RESULT BLANK`).
- **Status:** Human-checked by hand in the editor, 2026-11-02; probe AI-run the same day. Cause not proven.
- **Godot issue:** 125035.

### 9. Configure Snap resets Primary Line Every on Tab or focus loss

- **Godot / OS:** 4.8-beta2 and 4.8-beta3 official, Windows, headless editor. Controls: 4.6.3 and 4.7.2.
- **Repro:** [`repros/projects/125030-snap-primary-line-reset/`](repros/projects/125030-snap-primary-line-reset/), probe `probe/run_probe.py`.
- **Expected:** a typed value is kept on Tab or focus loss, as Grid Offset and Grid Step keep theirs.
- **Actual:** both Primary Line Every fields go back to 1 (`RESULT RESET`, 4 of 12 fields). Enter keeps the value. 4.6.3 and 4.7.2 keep all of them.
- **Status:** AI-run 2026-11-09, headless only. Not checked by hand. Cause not proven.
- **Godot issue:** 125030.

### 10. Trig differs in the last bit between Windows and Linux

- **Godot / OS:** 4.7.2, Windows vs Linux.
- **Repro:** none in this repo.
- **Expected:** the same `sin`, `cos`, `atan2` result on both systems.
- **Actual:** seen in a deterministic game simulation: the last bit differs, also in `Vector2.from_angle`, `angle` and `rotated`. Likely the platform math library, not a Godot bug.
- **Status:** Unverified.
- **Godot issue:** none found.
