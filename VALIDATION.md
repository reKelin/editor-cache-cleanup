# 验证记录

日期：2026-09-27。环境：Windows，Python 3.12.1。

- `python -m unittest discover -s tests -v`：24 项，22 项通过，2 项跳过。
- 新增交互向导测试：自动发现、仅清理选中类别、取消保留文件、深度清理强制备份、无参数入口。
- 跳过项：真实符号链接及链接祖先路径测试，当前账户缺少创建符号链接的权限。
  Windows reparse 属性判断测试通过，但不等同于真实 junction 的完整集成验证。
- Windows、macOS、Linux 默认目录与环境变量路径使用模拟输入验证通过；
  当前只在 Windows 实际执行，未在 macOS、Linux 或旧版 Windows 实机测试。
- `python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist`：构建成功。
- 在独立 `.venv` 中从本地 wheel 离线安装成功；`editor-cleanup --version` 输出 `0.1.0`。
- 本机 Windows 进程枚举调用成功；测试覆盖运行中编辑器拦截和枚举失败时停止清理。
- GitHub Actions 三平台、三个 Python 版本的矩阵已配置，尚未在远端执行。

所有删除与恢复测试均针对自动创建的临时目录，未对真实编辑器数据执行清理。
测试覆盖默认预览、选择性删除、用户数据保留、缺失目录、越界目标、部分失败、
强制备份失败时不删除、状态数据库配套文件备份恢复、拒绝覆盖及恶意 ZIP 路径。

Windows 启动修复：复现 `py -3` 报 `No installed Python found!`，而系统 Python 和项目 `.venv`
均可运行 Python 3.12.1。修复后 `cleanup.cmd --version`、`cleanup.cmd --help` 成功；
新增无 `.venv` 情况下的系统 Python 回退测试，同时验证程序退出码保留及含空格路径。
