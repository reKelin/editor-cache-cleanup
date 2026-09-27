# Editor Cache Cleanup

跨 Windows、macOS、Linux 的 VS Code / VS Code Insiders / Cursor 缓存清理工具。
Python 标准库实现，运行时零第三方依赖，MIT 开源许可。直接运行进入交互向导，确认后才删除。

## 快速开始

安装 Python 3.9 或更高版本后，Windows **双击 `cleanup.cmd`**；macOS / Linux 在项目目录执行 `sh cleanup.sh`。
Windows 启动器会验证解释器能否运行，依次尝试项目 `.venv`、系统 `python` 和 `py -3`。
即使 `py` 已安装但找不到解释器，也不会影响前两个入口。
也可以直接运行：

```sh
python editor_cleanup.py
```

运行后按提示操作，无需记忆参数：

1. 自动查找并列出编辑器数据目录，输入编号选择一个或多个，`a` 选择全部。
2. 扫描所选目录，显示缓存、日志、编辑历史、全局状态的大小，逐项询问是否清理。
3. 选择是否备份；历史或状态数据强制备份。最后确认后检查进程并执行清理。

支持 Windows / macOS / Linux 标准目录、常见 Flatpak / Snap 目录，以及当前目录、脚本附近或 PATH
命令附近的便携版 `data/user-data` 等布局。不会遍历整个硬盘。未发现特殊安装时，输入 `m` 在运行中补充目录。
扫描找到的实际路径会显示出来，由你确认范围。回车可退出或取消最终清理。

安装命令行入口后，也可直接运行 `editor-cleanup` 进入向导。
以下带参数方式保留给预览和自动化使用：

```sh
python editor_cleanup.py --app cursor
python editor_cleanup.py --app vscode --include-logs
```

也可以安装命令行入口：

```sh
python -m pip install .
editor-cleanup --app cursor
```

Windows 可使用 `py`，macOS / Linux 通常使用 `python3` 替代 `python`。

预览清单无误并关闭所有使用该数据目录的编辑器实例后，执行：

```sh
python editor_cleanup.py --app cursor --apply --editor-closed
```

交互输入 `DELETE` 后永久删除清单中的目录，不进入回收站。首次启动编辑器可能需要重建缓存。
程序检查本机 VS Code / Cursor 的常见进程名，发现运行中或检查失败时拒绝清理，不强制结束进程。
`--editor-closed` 是调用者对已关闭编辑器的额外确认；进程名检测无法覆盖自行改名的程序或其他主机。
在自动化环境中，可显式传入 `--yes`，并用 `--json` 获取结果：

```sh
python editor_cleanup.py --app cursor --json
python editor_cleanup.py --app cursor --apply --editor-closed --yes --json
```

退出码：`0` 成功（含无目标），`1` 扫描/清理失败或取消，`2` 参数错误。
发生删除错误立即停止，报告已经删除的目标；不承诺整个操作具有事务性。

## 清理范围

仅匹配用户数据根目录下的以下名称，不按通配符扫描磁盘：

`Cache`、`Code Cache`、`GPUCache`、`CachedData`、`CachedExtensionVSIXs`、
`DawnCache`、`DawnGraphiteCache`、`DawnWebGPUCache`、`ShaderCache`。

`--include-logs` 额外清理 `logs`。缺失的目录直接跳过。
默认保留 `User`（设置、快捷键、会话状态、历史、工作区与扩展存储）、`Backups`、扩展安装目录及项目源码。
工具不修改设备标识，不提供账户或试用重置功能。
本工具不是卸载器，也不进行系统全盘垃圾清理。

## 历史清理、状态重置与备份恢复

`--include-history` 选择 `User/History`；`--reset-state` 选择 `User/globalStorage/state.vscdb`
及其 `.backup`、`-wal`、`-shm` 配套文件。状态重置可能丢失聊天记录、扩展状态、最近记录、
布局或数据库中保存的其他数据，并可能需要重新登录。不要仅凭文件较大就重置。
这两个选项必须明确指定，`--yes` 本身不会启用它们。

```sh
# 先预览深度清理范围
python editor_cleanup.py --app cursor --include-history --reset-state
# 关闭编辑器后执行，必须先成功备份，再删除
python editor_cleanup.py --app cursor --include-history --reset-state --apply --editor-closed
```

历史或状态清理会强制将本次全部清理目标压缩备份到 `~/.editor-cleanup/backups/`，
逐项读回并校验 ZIP CRC 后才允许删除。`--backup-dir PATH` 更换目录，也可为普通缓存清理启用备份。
备份失败不删除任何目标；错误时可能留下不完整 ZIP，不能将其视为可用备份。
备份包含原始数据且不加密，请使用私人本地目录；不要上传含聊天记录或凭据的 ZIP。
备份占用磁盘空间，因此清单大小不等于净释放空间；不承诺固定压缩率。

```sh
# 检验归档并预览；目标目录必须尚不存在
python editor_cleanup.py --restore "backup.zip" --restore-to "recovered-data"
# 解压到新目录，不覆盖编辑器当前数据
python editor_cleanup.py --restore "backup.zip" --restore-to "recovered-data" --apply
```

输入 `RESTORE` 后恢复到新目录。检查恢复结果、关闭编辑器并保存当前同名数据后，
按归档相对目录将需要的文件放回原用户数据根目录。数据库及配套文件应作为同一组处理。
恢复工具拒绝路径穿越、符号链接及清理白名单之外的成员；只使用自己的可信备份。

## 平台与版本兼容性

| 平台 | 默认用户数据根目录 | 支持方式与边界 |
| --- | --- | --- |
| Windows | `%APPDATA%/<应用名>`，缺失时使用用户目录下的 `AppData/Roaming` | 面向 Windows 10 / 11；具体系统必须能运行所选 Python |
| macOS | `~/Library/Application Support/<应用名>` | Intel / Apple Silicon；系统最低版本由 Python 发行版决定 |
| Linux | `$XDG_CONFIG_HOME/<应用名>` 或 `~/.config/<应用名>` | 支持标准 XDG 目录；WSL 在其 Linux 环境中运行 |

应用名为 `Code`、`Code - Insiders`、`Cursor`。按已知数据目录名称适配，不依赖编辑器版本号；
新版本更改布局时，未知目录不会被清理。不能保证所有历史系统和未来编辑器版本均兼容。

便携版、自定义 `--user-data-dir`、沙箱安装或特殊 Linux 打包格式，请明确指定实际用户数据根目录：

```sh
python editor_cleanup.py --user-data-dir "/absolute/path/to/user-data"
```

传入包含 `Cache`、`User` 等目录的根目录，不要传入 `User` 本身。自定义路径优先于 `--app`。
VS Code 便携模式可指定安装目录下的 `data/user-data`；其他布局以实际目录为准。

根路径及祖先路径、目标目录树中的符号链接和 Windows reparse point（包括 junction）会被拒绝，
不会跟随链接清理其他目录。扫描显示逻辑文件大小，实际释放空间可能不同。
请以普通用户运行，在扫描和执行期间保持编辑器关闭，并避免其他程序同时修改目标；
执行前会再次检查路径，但路径检查不能抵御恶意并发替换。本工具不面向不可信共享目录。

## 开发与验证

```sh
python -m unittest discover -s tests -v
```

测试只使用临时目录，覆盖平台路径、预览、删除边界、保留用户数据、链接与失败处理。
首次公开提交的 GitHub Actions 在三种系统与 Python 3.9 / 3.12 / 3.14 的矩阵中
[全部通过](https://github.com/reKelin/editor-cache-cleanup/actions/runs/36313957346)。
本地验证环境与结果见 [VALIDATION.md](VALIDATION.md)。
提交兼容性问题时，请附操作系统、Python / 编辑器版本、安装方式及脱敏错误信息。
新增清理目录必须说明其用途，并增加保留用户数据的测试。不要提交真实用户数据、令牌或日志中的凭据。

## 来源与许可

项目需求参考 [ThendCN/vscode-cursor-cleanup](https://github.com/ThendCN/vscode-cursor-cleanup)。
已参考上游 `master` 分支的脚本与 MIT 许可证。上游的 Bash 脚本使用固定 macOS 用户目录；
本项目以 Python 独立实现跨平台路径、清理预览、ZIP 备份和恢复，并将历史和状态清理改为显式选项。
不沿用上游示例中的压缩率和释放空间数字，不声称所有行为完全一致。

本项目代码采用 [MIT License](LICENSE)。
