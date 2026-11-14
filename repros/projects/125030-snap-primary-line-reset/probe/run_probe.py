"""Run the 125030 probe headlessly against one or more Godot binaries.

Usage: python run_probe.py [path-to-godot ...]   (default: `godot` on PATH)

Copies ../project and the probe addon to a temp folder, so the project stays clean, and points
APPDATA there, so the editor's settings and project list stay untouched. Opens no window.
With two or more binaries it also prints a version table.
Set PROBE_DUMP=1 to print the Configure Snap dialog's control tree as well.
The work is done by tools/probe_harness.py at the repo root.
"""
import sys
from pathlib import Path

DRAFT = Path(__file__).resolve().parents[1]


def main():
    sys.path.insert(0, str(DRAFT.parents[2] / "tools"))
    import probe_harness

    return probe_harness.main([str(DRAFT), *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
