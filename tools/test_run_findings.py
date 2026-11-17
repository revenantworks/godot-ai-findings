"""Tests for run_findings.py. No network and no Godot: every gh call, download and repro output
is a recorded fixture."""
import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_findings as rf  # noqa: E402

CSV = (
    "finding,title,repro,runner,check,issues,prs,build\n"
    "1,Float parsing,repros/float_parse.gd,linux,float_parse,123700;124516,123839,4.7.2-stable\n"
    "5,Rename,repros/rename_replace.gd,windows,rename,118858,,4.7.2-stable\n"
    "8,Tile inspector,repros/projects/x,none,issue_only,125035,,\n"
    "10,Trig,,none,not_tracked,,,\n"
)

# Recorded `gh ... --json` answers, keyed by the command's first three words.
GH_FIXTURES = {
    ("api", "repos/godotengine/godot-builds/releases/latest", "--jq"): "4.8-stable\n",
    ("issue", "view", "123700"): '{"state":"OPEN","stateReason":""}',
    ("issue", "view", "124516"): '{"state":"CLOSED","stateReason":"COMPLETED"}',
    ("issue", "view", "118858"): '{"state":"OPEN","stateReason":""}',
    ("issue", "view", "125035"): '{"state":"CLOSED","stateReason":"NOT_PLANNED"}',
    ("pr", "view", "123839"): '{"state":"MERGED"}',
}


def fake_gh(args):
    key = tuple(args[:3])
    if key not in GH_FIXTURES:
        raise AssertionError(f"unexpected gh call {args}")
    return GH_FIXTURES[key]


class CsvTests(unittest.TestCase):
    def test_round_trip(self):
        rows = rf.load_findings(CSV)
        self.assertEqual(rows[0].issues, ["123700", "124516"])
        self.assertEqual(rows[0].prs, ["123839"])
        self.assertEqual(rf.dump_findings(rows), CSV)

    def test_repo_csv_loads(self):
        rows = rf.load_findings(rf.FINDINGS_CSV.read_text(encoding="utf-8"))
        self.assertEqual([r.finding for r in rows], [str(n) for n in range(1, 11)])
        by_runner = {k: [r.finding for r in rows if r.runner == k] for k in ("linux", "windows")}
        self.assertEqual(by_runner, {"linux": ["1", "3", "4", "6", "7"], "windows": ["2", "5"]})
        for r in rows:
            if r.runner != "none":
                self.assertIn(r.check, rf.CHECKS)
                self.assertTrue((rf.ROOT / r.repro).exists(), r.repro)


class VersionTests(unittest.TestCase):
    def test_order(self):
        tags = ["4.8-stable", "4.7.2-stable", "4.8-beta3", "4.8-rc1", "4.7-stable", "4.10-stable"]
        self.assertEqual(sorted(tags, key=rf.version_key),
                         ["4.7-stable", "4.7.2-stable", "4.8-beta3", "4.8-rc1", "4.8-stable", "4.10-stable"])

    def test_newer(self):
        rows = rf.load_findings(CSV)
        self.assertEqual(rf.recorded_build(rows), "4.7.2-stable")
        self.assertTrue(rf.is_newer(rf.latest_release(fake_gh), "4.7.2-stable"))
        self.assertFalse(rf.is_newer("4.7.2-stable", "4.7.2-stable"))
        self.assertTrue(rf.is_newer("4.7.2-stable", None))

    def test_bad_tag(self):
        with self.assertRaises(ValueError):
            rf.version_key("latest")


class DownloadTests(unittest.TestCase):
    def _fixture_zip(self, name, data):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(name, data)
        return buf.getvalue()

    def test_download_verifies_sha512(self):
        tag = "4.8-stable"
        zip_bytes = self._fixture_zip(rf.binary_name(tag, "windows"), b"fake godot")
        good = hashlib.sha512(zip_bytes).hexdigest()
        for sums_hash, ok in ((good, True), ("0" * 128, False)):
            served = {"SHA512-SUMS.txt": f"{sums_hash}  {rf.asset_name(tag, 'windows')}\n".encode(),
                      rf.asset_name(tag, "windows"): zip_bytes}

            def fetch(url, dest):
                dest.write_bytes(served[url.rsplit("/", 1)[1]])

            with tempfile.TemporaryDirectory() as tmp:
                if ok:
                    binary = rf.download_build(tag, "windows", Path(tmp), fetch)
                    self.assertEqual(binary.read_bytes(), b"fake godot")
                else:
                    with self.assertRaises(RuntimeError):
                        rf.download_build(tag, "windows", Path(tmp), fetch)

    def test_parse_sums(self):
        h = "a" * 128
        sums = rf.parse_sums(f"{h}  Godot_v4.8-stable_linux.x86_64.zip\nnot a line\n")
        self.assertEqual(sums, {"Godot_v4.8-stable_linux.x86_64.zip": h})


def _hex(x):
    return struct.pack("<d", x).hex()


class CheckTests(unittest.TestCase):
    def test_float_parse(self):
        bad = "DBL_MIN: \"2.2e-308\".to_float() = 0, is zero: true\nround trip: 9873 of 20000 random\n"
        good = "DBL_MIN: ... is zero: false\nround trip: 0 of 20000 random\n"
        self.assertEqual(rf.check_float_parse(bad)[0], rf.FAIL)
        self.assertEqual(rf.check_float_parse(good)[0], rf.PASS)
        self.assertEqual(rf.check_float_parse("crashed")[0], rf.ERROR)

    def test_format_6f(self):
        right = f"{_hex(1.25)} 1.250000\n{_hex(9545.4140625)} 9545.414062\n"
        wrong = right + f"{_hex(9545.4140625)} 9545.414063\n"
        self.assertEqual(rf.check_format_6f(right), (rf.PASS, "0 of 2 values not correctly rounded"))
        self.assertEqual(rf.check_format_6f(wrong)[0], rf.FAIL)
        self.assertEqual(rf.check_format_6f("Godot Engine v4\n")[0], rf.ERROR)

    def test_class_name_cache(self):
        self.assertEqual(rf.check_class_name_cache("RESULT RESOLVED: 42")[0], rf.PASS)
        err = 'Parse Error: Identifier "FreshClass" not declared in the current scope.'
        self.assertEqual(rf.check_class_name_cache(err)[0], rf.FAIL)

    def test_result_words(self):
        self.assertEqual(rf.check_crash_runner("RESULT CRASH: signal 11")[0], rf.FAIL)
        self.assertEqual(rf.check_crash_runner("RESULT REFUSED: load")[0], rf.PASS)
        self.assertEqual(rf.check_crash_runner("RESULT NO_RESULT: timeout")[0], rf.ERROR)
        self.assertEqual(rf.check_rename("RESULT LOST_TARGET: x")[0], rf.FAIL)
        self.assertEqual(rf.check_rename("RESULT FAILED_SAFE: x")[0], rf.PASS)
        self.assertEqual(rf.check_control_bake("RESULT STUCK: x")[0], rf.FAIL)
        self.assertEqual(rf.check_control_bake("RESULT SHRINKS: x")[0], rf.PASS)

    def test_configfile(self):
        bad = "".join(f"ERROR: ConfigFile parse error at user://configfile_line_{n}.cfg:{n - 1}: x\n"
                      for n in (1, 2, 4, 6))
        good = "".join(f"ERROR: ConfigFile parse error at user://configfile_line_{n}.cfg:{n}: x\n"
                       for n in (1, 2, 4, 6))
        self.assertEqual(rf.check_configfile(bad)[0], rf.FAIL)
        self.assertEqual(rf.check_configfile(good)[0], rf.PASS)
        self.assertEqual(rf.check_configfile("")[0], rf.ERROR)


class TableTests(unittest.TestCase):
    def test_table_and_markers(self):
        rows = rf.load_findings(CSV)
        results = {"1": {"finding": "1", "verdict": rf.FAIL, "detail": "9873 of 20000 differ"}}
        table = rf.build_table(rows, results, "4.8-stable", "2026-11-16", gh=fake_gh)
        self.assertIn("| 1 | Float parsing | Linux | Still reproduces: 9873 of 20000 differ | "
                      "issue 123700 open; issue 124516 closed, completed; pr 123839 merged |", table)
        self.assertIn("| 5 | Rename | Windows | Not run | issue 118858 open |", table)
        self.assertIn("| 8 | Tile inspector | None | Not run (issue state only) | "
                      "issue 125035 closed, not planned |", table)
        self.assertIn("| 10 | Trig | None | Not tracked | Not tracked |", table)
        readme = f"# Title\n\nintro\n\n{rf.START}\nold\n{rf.END}\n\n## After\n"
        new = rf.replace_status(readme, table)
        self.assertEqual(rf.outside_markers(new), rf.outside_markers(readme))
        self.assertNotIn("\nold\n", new)
        with self.assertRaises(ValueError):
            rf.replace_status("# no markers\n", table)

    def test_unreadable_state(self):
        def broken(args):
            raise OSError("gh missing")
        self.assertEqual(rf.upstream_state("issue", "1", broken), "issue 1 (state unread)")


class GuardTests(unittest.TestCase):
    def test_pii_rules(self):
        at = "@"
        self.assertEqual(rf.pii_hits("mail someone" + at + "example.com"), {"email": 1})
        self.assertEqual(rf.pii_hits("bot 41898282+github-actions[bot]" + at + "users.noreply.github.com"), {})
        self.assertEqual(rf.pii_hits("C:" + "\\Users\\someone\\x"), {"windows user folder": 1})
        self.assertEqual(rf.pii_hits("C:" + "\\Users\\<user>\\x"), {})
        self.assertEqual(rf.pii_hits("/" + "home/someone/x"), {"unix home folder": 1})
        self.assertEqual(rf.pii_hits("V:" + "\\Tools\\x"), {"local drive path": 1})
        self.assertEqual(rf.pii_hits('func f() -> void:\n\t@warning_ignore("x")\n'), {})

    def test_scope(self):
        readme_old = f"a\n{rf.START}\nold\n{rf.END}\nb\n"
        readme_new = f"a\n{rf.START}\nnew\n{rf.END}\nb\n"
        csv_new = CSV.replace("4.7.2-stable", "4.8-stable")
        old = {"README.md": readme_old, "findings.csv": CSV}
        ok = {"README.md": readme_new, "findings.csv": csv_new}
        self.assertEqual(rf.scope_problems(["README.md", "findings.csv"], old, ok), [])
        bad = {"README.md": readme_new.replace("b\n", "c\n"), "findings.csv": csv_new.replace("118858", "1")}
        self.assertEqual(len(rf.scope_problems(["README.md", "findings.csv", "x.gd"], old, bad)), 3)

    def test_results_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.json", Path(tmp) / "b.json"
            a.write_text(json.dumps({"build": "4.8-stable", "results": [{"finding": "1", "verdict": "PASS"}]}))
            b.write_text(json.dumps({"build": "4.8-stable", "results": [{"finding": "5", "verdict": "FAIL"}]}))
            merged, build = rf._load_results([str(a), str(b)])
        self.assertEqual((sorted(merged), build), (["1", "5"], "4.8-stable"))


if __name__ == "__main__":
    unittest.main()
