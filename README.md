# 🧹 Editor Cache Cleanup

跨 Windows、macOS、Linux 清理 VS Code、VS Code Insiders 和 Cursor。自动查找数据目录，运行时选择清理范围；只需 Python 3.9+，无额外依赖。

## 🚀 快速开始

从 [GitHub 下载 ZIP](https://github.com/reKelin/editor-cache-cleanup/archive/refs/heads/main.zip) 并解压，或克隆仓库：

```sh
git clone https://github.com/reKelin/editor-cache-cleanup.git
cd editor-cache-cleanup
```

| 系统 | 启动方式 |
| --- | --- |
| Windows | 双击 `cleanup.cmd` |
| macOS / Linux | 在项目目录运行 `sh cleanup.sh` |

安装 [Python 3.9+](https://www.python.org/downloads/) 后启动。按提示选择编辑器目录（可多选）、清理项目和备份选项，最后确认执行。输入 `m` 可补充未找到的目录；直接回车退出。

## 🎯 清理范围

| 项目 | 默认选择 | 影响 |
| --- | --- | --- |
| 🟢 缓存 | 是 | 重启后由编辑器重建 |
| 🟢 日志 | 是 | 丢失旧日志 |
| 🟡 本地编辑历史 | 否 | 丢失本地历史版本 |
| 🔴 全局状态 | 否 | **重置整个状态数据库**，可能丢失聊天记录、扩展状态与登录状态 |

每项都会先显示大小，再单独确认。历史和全局状态必须先完成 ZIP 备份；其他项目可选备份。工具会检查编辑器进程，运行中不会清理。项目源码、设置和已安装扩展不在清理范围内。

⚠️ 备份保存在 `~/.editor-cleanup/backups/`，包含原始数据且**未加密**，也会占用磁盘空间。全局状态文件大不代表能无损清理；只想清缓存时，对这一项选 `n`。

## 🔄 恢复与进阶用法

恢复到**尚不存在的新目录**，检查后再手动放回编辑器数据目录，不会覆盖现有文件：

```sh
python editor_cleanup.py --restore "backup.zip" --restore-to "recovered-data" --apply
```

只预览 Cursor 缓存，或查看全部参数：

```sh
python editor_cleanup.py --app cursor
python editor_cleanup.py --help
```

Windows 可使用 `py -3`，macOS / Linux 通常使用 `python3` 替代上述 `python`。自动发现覆盖标准目录、常见 Flatpak / Snap 目录和附近的便携版安装；特殊安装可在运行时输入 `m`。测试记录见 [VALIDATION.md](VALIDATION.md)。

## 📄 许可证

采用 [MIT 许可证](LICENSE)。
