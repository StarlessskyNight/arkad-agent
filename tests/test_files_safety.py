"""File tools safety: non-UTF-8 refusal, atomic writes, skip-dir relativity."""
import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from arkad import constants
from arkad.constants import set_cwd
from arkad.tools.files import (
    _atomic_write,
    _in_skip_dir,
    edit_file,
    multi_edit,
    read_file,
    write_file,
)


class FilesSafetyTests(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = constants.CWD
        self._project = TemporaryDirectory()
        set_cwd(Path(self._project.name))
        self.root = Path(self._project.name)

    def tearDown(self):
        set_cwd(self._orig_cwd)
        self._project.cleanup()

    # --- non-UTF-8 handling: lossy round-trips are refused, bytes preserved ---

    def _latin1_file(self) -> Path:
        p = self.root / "latin1.txt"
        p.write_bytes(b"caf\xe9 na\xefve\n")  # valid latin-1, invalid UTF-8
        return p

    def test_read_file_refuses_non_utf8(self):
        p = self._latin1_file()
        out = read_file("latin1.txt")
        self.assertIn("not valid UTF-8", out)
        self.assertEqual(p.read_bytes(), b"caf\xe9 na\xefve\n")

    def test_read_file_force_shows_replacement(self):
        self._latin1_file()
        out = read_file("latin1.txt", force=True)
        self.assertNotIn("ERROR", out)
        self.assertIn("\ufffd", out)

    def test_edit_file_refuses_non_utf8_and_preserves_bytes(self):
        p = self._latin1_file()
        out = edit_file("latin1.txt", "caf", "tea")
        self.assertIn("not valid UTF-8", out)
        self.assertEqual(p.read_bytes(), b"caf\xe9 na\xefve\n")

    def test_multi_edit_refuses_non_utf8(self):
        p = self._latin1_file()
        out = multi_edit(edits=[{"path": "latin1.txt", "old_str": "caf", "new_str": "tea"}])
        self.assertIn("not valid UTF-8", out)
        self.assertEqual(p.read_bytes(), b"caf\xe9 na\xefve\n")

    def test_write_file_bad_content_leaves_original(self):
        p = self.root / "ok.txt"
        p.write_text("original")
        out = write_file("ok.txt", "bad \ud800 surrogate")
        self.assertIn("ERROR", out)
        self.assertEqual(p.read_text(), "original")

    # --- atomic writes preserve content and mode ---

    def test_atomic_write_preserves_mode(self):
        p = self.root / "conf.txt"
        p.write_text("v1")
        os.chmod(p, 0o640)
        out = write_file("conf.txt", "v2")
        self.assertTrue(out.startswith("WROTE"))
        self.assertEqual(p.read_text(), "v2")
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o640)

    def test_atomic_write_no_temp_litter_on_success(self):
        self.root / "a.txt"
        write_file("a.txt", "hello")
        leftovers = [f for f in os.listdir(self.root) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_atomic_write_failure_leaves_original_intact(self):
        p = self.root / "b.txt"
        p.write_text("original")
        real_replace = os.replace

        def boom(src, dst):
            raise OSError("disk full")

        with patch("arkad.tools.files.os.replace", side_effect=boom):
            out = write_file("b.txt", "new content")
        self.assertIn("ERROR", out)
        self.assertEqual(p.read_text(), "original")
        leftovers = [f for f in os.listdir(self.root) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_atomic_write_new_file_gets_default_mode(self):
        write_file("fresh.txt", "x")
        mode = stat.S_IMODE((self.root / "fresh.txt").stat().st_mode)
        self.assertNotEqual(mode & 0o077, 0o077)  # never world-writable-by-accident

    def test_edit_still_works_end_to_end(self):
        p = self.root / "code.py"
        p.write_text("def f():\n    return 1\n")
        out = edit_file("code.py", "return 1", "return 2")
        self.assertIn("EDITED", out)
        self.assertEqual(p.read_text(), "def f():\n    return 2\n")

    # --- skip-dir relativity: project under a dir named like a skip dir ---

    def test_project_under_build_dir_is_readable(self):
        with TemporaryDirectory() as outer:
            proj = Path(outer) / "build" / "myproj"
            proj.mkdir(parents=True)
            (proj / "main.py").write_text("print('hi')\n")
            set_cwd(proj)
            out = read_file(str(proj / "main.py"))
            self.assertNotIn("inside", out)
            self.assertIn("print", out)

    def test_real_skip_dir_inside_project_still_blocked(self):
        d = self.root / "node_modules"
        d.mkdir()
        (d / "x.js").write_text("module.exports = 1\n")
        out = read_file("node_modules/x.js")
        self.assertIn("inside", out)

    def test_in_skip_dir_relative_logic(self):
        inside = self.root / "dist" / "app.js"
        self.assertEqual(_in_skip_dir(inside), "dist")
        plain = self.root / "src" / "app.js"
        self.assertIsNone(_in_skip_dir(plain))
