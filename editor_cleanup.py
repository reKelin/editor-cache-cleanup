"""Conservative, dependency-free VS Code and Cursor cache cleanup."""

import argparse
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile

__version__ = "0.1.0"
APPS = {"vscode": "Code", "vscode-insiders": "Code - Insiders", "cursor": "Cursor"}
# Exact cache names only. User data requires separate explicit options below.
CACHES = ("Cache", "Code Cache", "GPUCache", "CachedData", "CachedExtensionVSIXs",
          "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache", "ShaderCache")
STATE = ("User/globalStorage/state.vscdb", "User/globalStorage/state.vscdb.backup",
         "User/globalStorage/state.vscdb-wal", "User/globalStorage/state.vscdb-shm")
ALLOWED = CACHES + ("logs", "User/History") + STATE


def running_editors():
    """Conservatively block cleanup while a recognized local editor is running."""
    if sys.platform == "win32":
        result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        names = [row[0] for row in csv.reader(io.StringIO(
            result.stdout.decode(errors="replace"))) if row]
    else:
        result = subprocess.run(["ps", "-A", "-o", "comm="], check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        names = result.stdout.decode(errors="replace").splitlines()
    names = [Path(name.strip()).name.lower() for name in names]
    return sorted({name for name in names if name in
                   ("code", "code.exe", "code-insiders", "code - insiders.exe",
                    "cursor", "cursor.exe", "cursor-insiders", "code - insiders")
                   or name.startswith(("code helper", "cursor helper"))})


def data_root(app, system=None, home=None, env=None):
    system = sys.platform if system is None else system
    home = Path.home() if home is None else Path(home)
    env = os.environ if env is None else env
    if system == "win32":
        base = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
    elif system == "darwin":
        base = home / "Library" / "Application Support"
    elif system.startswith("linux"):
        base = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    else:
        raise ValueError("Unsupported OS; specify --user-data-dir explicitly.")
    if not base.is_absolute():
        raise ValueError("The configured application data directory must be absolute.")
    return base / APPS[app]


def is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400  # Windows reparse points/junctions
    )


def check_parents(path):
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if is_link(info):
            raise ValueError("Refusing linked/reparse path: {}".format(part))


def tree_size(path):
    """Reject links and special files anywhere in a target before deletion."""
    info = path.lstat()
    if is_link(info):
        raise ValueError("Refusing linked/reparse path: {}".format(path))
    if stat.S_ISREG(info.st_mode):
        return info.st_size
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("Refusing special file: {}".format(path))
    return sum(tree_size(child) for child in path.iterdir())


def plan(root, include_logs=False, include_history=False, reset_state=False):
    root = Path(os.path.abspath(root))
    check_parents(root)
    if root.exists() and not root.is_dir():
        raise ValueError("User data root is not a directory: {}".format(root))
    items = []
    names = CACHES + (("logs",) if include_logs else ())
    names += ("User/History",) if include_history else ()
    names += STATE if reset_state else ()
    for name in names:
        target = root / name
        check_parents(target)
        if os.path.lexists(target):
            items.append({"path": str(target), "bytes": tree_size(target)})
    return items


def clean(root, items):
    """Only accept exact allowlisted targets; recheck immediately before removal."""
    root = Path(os.path.abspath(root))
    for item in items:
        target = Path(item["path"])
        if target not in [root / name for name in ALLOWED]:
            raise ValueError("Target outside cleanup allowlist: {}".format(target))
    removed = []
    for item in items:
        target = Path(item["path"])
        try:
            check_parents(target)
            tree_size(target)
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed.append(str(target))
        except (OSError, ValueError) as exc:
            return removed, "{}: {}".format(target, exc)
    return removed, None


def backup(root, items, directory):
    """Write a fresh ZIP, then read every member to verify CRC before deletion."""
    directory = Path(os.path.abspath(directory.expanduser()))
    check_parents(directory)
    # A backup must never be placed inside a target it is about to archive/delete.
    for item in items:
        target = Path(item["path"])
        if directory == target or target in directory.parents:
            raise ValueError("Backup directory is inside a cleanup target.")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / ("cleanup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                               + "-" + uuid.uuid4().hex[:12] + ".zip")
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for item in items:
            target = Path(item["path"])
            check_parents(target)
            tree_size(target)
            archive.write(target, target.relative_to(root).as_posix())
            if target.is_dir():
                for child in target.rglob("*"):
                    check_parents(child)
                    archive.write(child, child.relative_to(root).as_posix())
    with zipfile.ZipFile(destination) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError("Backup verification failed: " + bad)
    return str(destination)


def restore(archive_path, destination, apply=False):
    """Restore into a NEW directory only, never overwrite current editor data."""
    destination = Path(os.path.abspath(destination.expanduser()))
    check_parents(destination)
    if os.path.lexists(destination):
        raise ValueError("Restore destination must not exist: {}".format(destination))
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if not names:
            raise ValueError("Empty backup.")
        for member in archive.infolist():
            name = member.filename.rstrip("/")
            parts = name.split("/")
            if (any(part in ("", ".", "..") for part in parts)
                    or "\\" in member.orig_filename or ":" in name
                    or not any(name == allowed or name.startswith(allowed + "/")
                               for allowed in ALLOWED)
                    or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError("Unsafe backup member: " + member.filename)
        if archive.testzip():
            raise ValueError("Backup CRC verification failed.")
        if apply:
            destination.mkdir(parents=True, exist_ok=False)
            archive.extractall(destination)
        return names


def discover_roots():
    """Probe known layouts and nearby/PATH portable installs, never crawl disks."""
    candidates = [(label, data_root(app)) for app, label in APPS.items()]
    home = Path.home()
    if sys.platform.startswith("linux"):
        for package, label in (("com.visualstudio.code", "Code"), ("com.cursor.Cursor", "Cursor")):
            candidates.append((label, home / ".var/app" / package / "config" / label))
        for package, label in (("code", "Code"), ("cursor", "Cursor")):
            for revision in ("current", "common"):
                candidates.append((label, home / "snap" / package / revision / ".config" / label))
    locations = {Path.cwd(), Path(__file__).resolve().parent}
    for command in ("code", "code-insiders", "cursor"):
        executable = shutil.which(command)
        if executable:
            locations.add(Path(executable).resolve().parent)
    for location in list(locations):
        locations.add(location.parent)
    for location in locations:
        for relative in ("data/user-data", "code-portable-data/user-data", "cursor-portable-data/user-data"):
            candidates.append(("便携版", location / relative))
    found, seen = [], set()
    for label, root in candidates:
        try:
            # Resolve installation aliases during discovery, then show the actual path.
            root = root.resolve()
            if root not in seen and root.is_dir():
                check_parents(root)
                found.append((label, root))
                seen.add(root)
        except (OSError, ValueError):
            continue
    return found


def ask_yes(prompt, default=False):
    while True:
        answer = input(prompt + (" [Y/n]: " if default else " [y/N]: ")).strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "是"):
            return True
        if answer in ("n", "no", "否"):
            return False
        print("请输入 y 或 n。")


def interactive(root=None):
    print("VS Code / Cursor 清理工具\n正在查找当前用户的数据目录……")
    try:
        found = [("指定目录", root.expanduser().resolve())] if root else discover_roots()
        for index, (label, path) in enumerate(found, 1):
            print("  {}) {}  {}".format(index, label, path))
        if not found:
            print("未发现标准安装或附近的便携版数据。")
        print("输入编号（多个用空格分隔），a 全部，m 补充目录，直接回车退出。")
        while True:
            answer = input("清理范围: ").strip().lower()
            if not answer:
                return 0
            if answer == "m":
                path = Path(input("用户数据根目录（包含 User/Cache 的目录）: ").strip().strip('"')).expanduser().resolve()
                check_parents(path)
                if not path.is_dir() or not (path / "User").is_dir():
                    print("未识别到编辑器数据目录，请重新选择。")
                    continue
                existing = next((i for i, (_, known) in enumerate(found, 1) if known == path), None)
                if existing is None:
                    found.append(("自定义目录", path))
                print("  {}) {}".format(existing or len(found), path))
                continue
            try:
                indices = list(range(len(found))) if answer == "a" else list(dict.fromkeys(int(v) - 1 for v in answer.replace(",", " ").split()))
                if not indices or any(i < 0 or i >= len(found) for i in indices):
                    raise ValueError()
                selected = [found[i] for i in indices]
                break
            except ValueError:
                print("请输入列表中的编号。")
        jobs = []
        groups = (("缓存（可重建）", CACHES, True), ("日志（会丢失历史日志）", ("logs",), True),
                  ("本地编辑历史（会丢失历史版本）", ("User/History",), False),
                  ("全局状态（会丢失聊天、扩展状态等，可能需要重新登录）", STATE, False))
        for label, path in selected:
            print("\n扫描 {}: {}".format(label, path))
            items = plan(path, True, True, True)
            chosen = []
            for title, names, default in groups:
                group = [item for item in items if Path(item["path"]) in [path / name for name in names]]
                if group:
                    size = sum(item["bytes"] for item in group) / (1024 * 1024)
                    if ask_yes("清理 {}（{:.2f} MiB）？".format(title, size), default):
                        chosen.extend(group)
            if chosen:
                deep = any(Path(item["path"]) in [path / name for name in ("User/History",) + STATE] for item in chosen)
                if deep:
                    print("所选历史/状态数据将强制备份。")
                with_backup = deep or ask_yes("清理前创建 ZIP 备份？", True)
                jobs.append((path, chosen, with_backup))
        if not jobs:
            print("没有选择可清理的数据，未修改文件。")
            return 0
        print("\n即将永久删除以下目标：")
        for path, items, _ in jobs:
            for item in items:
                print("  {} ({:,} bytes)".format(item["path"], item["bytes"]))
        if not ask_yes("请关闭编辑器。确认执行以上清理？"):
            print("已取消，未修改文件。")
            return 0
        while True:
            running = running_editors()
            if not running:
                break
            print("编辑器仍在运行：" + ", ".join(running))
            if not ask_yes("关闭后重新检查？"):
                return 0
        # Back up every selected root before starting any deletion.
        for path, items, with_backup in jobs:
            if with_backup:
                archive = backup(path, items, Path.home() / ".editor-cleanup/backups")
                print("已校验备份：{} -> {}".format(path, archive))
        if running_editors():
            raise ValueError("编辑器重新启动，清理已停止。")
        for path, items, _ in jobs:
            removed, error = clean(path, items)
            print("{}：已清理 {} 项。".format(path, len(removed)))
            if error:
                raise ValueError(error)
        print("清理完成。")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\n已中止；已完成的操作不会回滚。")
        return 1
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        print("清理停止：{}".format(exc), file=sys.stderr)
        return 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interactive", action="store_true", help="启动交互式扫描与清理")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--app", choices=APPS, default="vscode")
    parser.add_argument("--user-data-dir", type=Path,
                        help="Actual user-data root (not User/), for portable/custom installs")
    parser.add_argument("--include-logs", action="store_true")
    parser.add_argument("--include-history", action="store_true", help="Remove local edit history; backed up before deletion")
    parser.add_argument("--reset-state", action="store_true", help="Reset global state, including chat/extension state; backed up first")
    parser.add_argument("--backup-dir", type=Path, help="ZIP backup destination; automatic for history/state cleanup")
    parser.add_argument("--restore", type=Path, help="ZIP backup to validate or extract")
    parser.add_argument("--restore-to", type=Path, help="New directory for recovered data (never overwrites existing data)")
    parser.add_argument("--apply", action="store_true", help="Execute cleanup or restore (default: preview)")
    parser.add_argument("--editor-closed", action="store_true",
                        help="Confirm all instances using this directory have been closed")
    parser.add_argument("--yes", action="store_true", help="Skip interactive deletion confirmation")
    parser.add_argument("--json", action="store_true", help="Machine-readable output; apply requires --yes")
    args = parser.parse_args(argv)
    if not argv or args.interactive:
        if args.interactive and any(v not in ("--interactive", "--user-data-dir") for v in argv if v.startswith("--")):
            parser.error("交互模式仅支持 --user-data-dir；请在运行时选择清理范围。")
        if not sys.stdin.isatty():
            parser.error("交互模式需要终端。自动化预览请使用 --json。")
        return interactive(args.user_data_dir)
    if args.restore and (not args.restore_to or args.user_data_dir or args.include_logs
                         or args.include_history or args.reset_state or args.backup_dir):
        parser.error("--restore requires --restore-to and cannot be combined with cleanup options.")
    if args.restore_to and not args.restore:
        parser.error("--restore-to requires --restore.")
    if args.apply and not args.restore and not args.editor_closed:
        parser.error("Close the editor, then pass --editor-closed to allow cleanup.")
    if args.apply and args.json and not args.yes:
        parser.error("--json --apply requires --yes.")
    report = {"version": __version__, "mode": "apply" if args.apply else "preview",
              "targets": [], "removed": [], "error": None}
    try:
        if args.restore:
            if args.apply and not args.yes:
                if not sys.stdin.isatty() or input("Extract backup into a new directory? Type RESTORE: ") != "RESTORE":
                    raise ValueError("Restore cancelled.")
            report["mode"] = "restore" if args.apply else "restore-preview"
            report["members"] = restore(args.restore, args.restore_to, args.apply)
            report["destination"] = str(args.restore_to.absolute())
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print("{}: {} members -> {}".format(report["mode"], len(report["members"]), args.restore_to))
            return 0
        root = args.user_data_dir if args.user_data_dir is not None else data_root(args.app)
        root = Path(os.path.abspath(root.expanduser()))
        report["root"] = str(root)
        report["targets"] = plan(root, args.include_logs, args.include_history, args.reset_state)
        report["total_bytes"] = sum(item["bytes"] for item in report["targets"])
        if not args.json:
            print("{}: {}".format(report["mode"].upper(), root))
            for item in report["targets"]:
                print("  {:>12,} bytes  {}".format(item["bytes"], item["path"]))
            print("{} target(s), {:,} bytes (logical size).".format(
                len(report["targets"]), report["total_bytes"]))
        if args.apply and report["targets"]:
            running = running_editors()
            if running:
                raise ValueError("Close running editors before cleanup: " + ", ".join(running))
            confirmed = args.yes
            if not confirmed and sys.stdin.isatty():
                confirmed = input("Permanently delete these targets? Type DELETE: ") == "DELETE"
            if not confirmed:
                raise ValueError("Cleanup cancelled. For unattended use, explicitly pass --yes.")
            if args.backup_dir or args.include_history or args.reset_state:
                report["backup"] = backup(root, report["targets"], args.backup_dir or
                                          Path.home() / ".editor-cleanup" / "backups")
                if not args.json:
                    print("Verified backup: " + report["backup"])
            report["removed"], report["error"] = clean(root, report["targets"])
    except (OSError, ValueError, EOFError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        report["error"] = str(exc)
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    elif report["error"]:
        print("ERROR: {}".format(report["error"]), file=sys.stderr)
        print("Removed {} target(s) before stopping.".format(len(report["removed"])), file=sys.stderr)
    elif args.apply:
        print("Removed {} target(s).".format(len(report["removed"])))
    else:
        print("Preview only. No files changed.")
    return 1 if report["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
