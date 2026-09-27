import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import editor_cleanup as cleanup


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "编辑器 data"
        self.root.mkdir()

    def write(self, name, content=b"sample"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = cleanup.main(["--user-data-dir", str(self.root), "--json", *args])
        return code, json.loads(output.getvalue())

    def test_platform_paths(self):
        home = self.base
        cases = [("win32", {}, home / "AppData/Roaming/Cursor"),
                 ("win32", {"APPDATA": str(home / "roaming")}, home / "roaming/Cursor"),
                 ("darwin", {}, home / "Library/Application Support/Cursor"),
                 ("linux", {}, home / ".config/Cursor"),
                 ("linux", {"XDG_CONFIG_HOME": str(home / "xdg")}, home / "xdg/Cursor")]
        for system, env, expected in cases:
            with self.subTest(system=system, env=env):
                self.assertEqual(cleanup.data_root("cursor", system, home, env), expected)
        with self.assertRaises(ValueError):
            cleanup.data_root("vscode", "linux", home, {"XDG_CONFIG_HOME": "relative"})
        with self.assertRaises(ValueError):
            cleanup.data_root("vscode", "unknown", home, {})

    def test_discovery_standard_and_portable(self):
        standard = self.base / "config"
        (standard / "Code").mkdir(parents=True)
        portable = self.base / "install/data/user-data"
        portable.mkdir(parents=True)
        with patch.object(cleanup, "data_root", side_effect=lambda app: standard / cleanup.APPS[app]), \
                patch.object(cleanup.Path, "cwd", return_value=portable.parent.parent), \
                patch.object(cleanup.shutil, "which", return_value=None), \
                patch.object(cleanup.Path, "home", return_value=self.base):
            roots = [path for _, path in cleanup.discover_roots()]
        self.assertIn(standard / "Code", roots)
        self.assertIn(portable, roots)
        self.assertEqual(len(roots), len(set(roots)))

    def wizard(self, answers):
        with patch.object(cleanup, "discover_roots", return_value=[("Cursor", self.root)]), \
                patch("builtins.input", side_effect=answers), \
                patch.object(cleanup, "running_editors", return_value=[]), \
                contextlib.redirect_stdout(io.StringIO()):
            return cleanup.interactive()

    def test_wizard_only_cleans_selected_category(self):
        cache = self.write("Cache/file")
        log = self.write("logs/file")
        history = self.write("User/History/file")
        state = self.write("User/globalStorage/state.vscdb")
        # Root, caches yes, logs/history/state no, no backup, confirm.
        self.assertEqual(self.wizard(["1", "y", "n", "n", "n", "n", "y"]), 0)
        self.assertFalse(cache.exists())
        self.assertTrue(all(path.exists() for path in (log, history, state)))

    def test_wizard_cancel_preserves_files(self):
        cache = self.write("Cache/file")
        self.assertEqual(self.wizard(["1", "y", "n", "n"]), 0)
        self.assertTrue(cache.exists())

    def test_wizard_deep_cleanup_forces_backup(self):
        history = self.write("User/History/file")
        with patch.object(cleanup, "backup", return_value="test.zip") as backup:
            self.assertEqual(self.wizard(["1", "y", "y"]), 0)
        backup.assert_called_once()
        self.assertFalse(history.exists())

    def test_no_args_enters_wizard(self):
        with patch.object(cleanup.sys.stdin, "isatty", return_value=True), \
                patch.object(cleanup, "interactive", return_value=0) as wizard:
            self.assertEqual(cleanup.main([]), 0)
            wizard.assert_called_once_with(None)

    def test_preview_preserves_all_data(self):
        cache = self.write("Cache/data", b"12345")
        user = self.write("User/settings.json")
        self.write("logs/test.log")
        code, report = self.cli()
        self.assertEqual(code, 0)
        self.assertEqual(report["total_bytes"], 5)
        self.assertTrue(cache.exists())
        self.assertTrue(user.exists())
        self.assertEqual(report["removed"], [])

    @patch.object(cleanup, "running_editors", return_value=[])
    def test_apply_preserves_user_data_and_extensions(self, _):
        self.write("Code Cache/nested/cache")
        self.write("logs/test.log")
        preserved = [self.write(name) for name in (
            "User/settings.json", "User/History/edit", "User/globalStorage/state.vscdb",
            "Backups/unsaved", "extensions/plugin/file", "UnknownCache/file")]
        code, report = self.cli("--apply", "--editor-closed", "--yes", "--include-logs")
        self.assertEqual(code, 0)
        self.assertEqual(len(report["removed"]), 2)
        self.assertFalse((self.root / "Code Cache").exists())
        self.assertTrue(all(path.exists() for path in preserved))

    def test_missing_directory_is_noop(self):
        self.assertEqual(cleanup.plan(self.base / "missing"), [])

    def test_root_file_rejected(self):
        with self.assertRaises(ValueError):
            cleanup.plan(self.write("file"))

    def test_apply_requires_closed_acknowledgment(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            cleanup.main(["--apply", "--yes"])
        self.assertEqual(exc.exception.code, 2)

    @patch.object(cleanup, "running_editors", return_value=["cursor.exe"])
    def test_running_editor_blocks_deletion(self, _):
        cache = self.write("Cache/file")
        code, report = self.cli("--apply", "--editor-closed", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("running editors", report["error"])
        self.assertTrue(cache.exists())

    @patch.object(cleanup, "running_editors", side_effect=FileNotFoundError("ps missing"))
    def test_process_detection_failure_blocks_deletion(self, _):
        cache = self.write("Cache/file")
        code, _ = self.cli("--apply", "--editor-closed", "--yes")
        self.assertEqual(code, 1)
        self.assertTrue(cache.exists())

    def test_process_names(self):
        samples = [("win32", b'"Code.exe","1"\n"other.exe","2"\n', ["code.exe"]),
                   ("darwin", b'/Applications/Cursor.app/Contents/MacOS/Cursor\n/bin/sh\n', ["cursor"]),
                   ("linux", b'code-insiders\npython\n', ["code-insiders"])]
        for platform, output, expected in samples:
            with patch.object(cleanup.sys, "platform", platform), patch.object(
                    cleanup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output)):
                self.assertEqual(cleanup.running_editors(), expected)

    def test_outside_target_rejected_before_any_deletion(self):
        cache = self.write("Cache/file")
        outside = self.base / "keep"
        outside.write_text("keep")
        items = cleanup.plan(self.root) + [{"path": str(outside), "bytes": 4}]
        with self.assertRaises(ValueError):
            cleanup.clean(self.root, items)
        self.assertTrue(cache.exists())
        self.assertTrue(outside.exists())

    def test_partial_failure_report(self):
        self.write("Cache/file")
        self.write("GPUCache/file")
        items = cleanup.plan(self.root)
        original = cleanup.shutil.rmtree
        def remove(path):
            if path.name == "GPUCache":
                raise PermissionError("locked")
            original(path)
        with patch.object(cleanup.shutil, "rmtree", side_effect=remove):
            removed, error = cleanup.clean(self.root, items)
        self.assertEqual(removed, [str(self.root / "Cache")])
        self.assertIn("locked", error)
        self.assertTrue((self.root / "GPUCache/file").exists())

    def link(self, target, link):
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except OSError:
            self.skipTest("OS does not grant symlink creation")

    def test_nested_link_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "keep").write_text("keep")
        self.write("Cache/normal")
        self.link(outside, self.root / "Cache/link")
        with self.assertRaises(ValueError):
            cleanup.plan(self.root)
        self.assertTrue((outside / "keep").exists())

    def test_linked_ancestor_rejected(self):
        linked = self.base / "linked"
        self.link(self.root, linked)
        with self.assertRaises(ValueError):
            cleanup.plan(linked / "nested")

    def test_reparse_detection(self):
        info = type("Info", (), {"st_mode": stat.S_IFDIR, "st_file_attributes": 0x400})()
        self.assertTrue(cleanup.is_link(info))

    @patch.object(cleanup, "running_editors", return_value=[])
    def test_deep_cleanup_backup_restore_roundtrip(self, _):
        originals = {name: self.write(name).read_bytes() for name in (
            "User/History/local", "User/globalStorage/state.vscdb",
            "User/globalStorage/state.vscdb-wal", "User/globalStorage/state.vscdb-shm",
            "User/globalStorage/state.vscdb.backup", "Cache/data")}
        settings = self.write("User/settings.json")
        code, report = self.cli("--apply", "--editor-closed", "--yes", "--reset-state",
                                "--include-history", "--backup-dir", str(self.base / "backups"))
        self.assertEqual(code, 0, report)
        self.assertTrue(settings.exists())
        self.assertFalse((self.root / "User/History").exists())
        destination = self.base / "recovered"
        cleanup.restore(Path(report["backup"]), destination)
        self.assertFalse(destination.exists())
        cleanup.restore(Path(report["backup"]), destination, apply=True)
        for name, content in originals.items():
            self.assertEqual((destination / name).read_bytes(), content)
        with self.assertRaises(ValueError):
            cleanup.restore(Path(report["backup"]), destination, apply=True)

    @patch.object(cleanup, "running_editors", return_value=[])
    @patch.object(cleanup, "backup", side_effect=OSError("disk full"))
    def test_backup_failure_prevents_deletion(self, *_):
        state = self.write("User/globalStorage/state.vscdb")
        code, report = self.cli("--apply", "--editor-closed", "--yes", "--reset-state")
        self.assertEqual(code, 1)
        self.assertEqual(report["removed"], [])
        self.assertTrue(state.exists())

    def test_backup_inside_target_rejected(self):
        self.write("Cache/file")
        with self.assertRaises(ValueError):
            cleanup.backup(self.root, cleanup.plan(self.root), self.root / "Cache/backups")

    def test_restore_rejects_traversal_and_unlisted_members(self):
        for index, name in enumerate(("../escape", "/absolute", "Cache/../../escape",
                                      "Cache\\escape", "User/settings.json", "Cache/C:stream")):
            archive = self.base / (str(index) + ".zip")
            with zipfile.ZipFile(archive, "w") as output:
                member = zipfile.ZipInfo("placeholder")
                member.filename = name  # Prevent Windows writer from normalizing separators.
                output.writestr(member, b"bad")
            with self.assertRaises(ValueError):
                cleanup.restore(archive, self.base / "restored", apply=True)
            self.assertFalse((self.base / "restored").exists())


if __name__ == "__main__":
    unittest.main()
