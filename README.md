# Windows MCP Sync

用 GitHub 私有仓库同步 **Codex 用户级 MCP 配置**，并在各 Windows 电脑准备本地服务器运行环境。

仓库里的 `config.toml` 只保存 `mcp_servers`。`setup.ps1` 按服务器名称合并到 `$CODEX_HOME/config.toml`（默认 `%USERPROFILE%/.codex/config.toml`），保留模型、插件、项目、注释以及本机独有的 MCP，写入前自动备份。

## 新电脑：首次配置

需要安装 Codex，并能登录 GitHub。Windows PowerShell 5.1 或 PowerShell 7 均可。

```powershell
winget install --id Git.Git --exact
winget install --id GitHub.cli --exact
# 安装完成后重新打开终端
gh auth login
gh auth setup-git
gh repo clone Veiluna/windows-mcp-sync
cd windows-mcp-sync
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

脚本会检查 Python 3.11+；缺失时通过 winget 安装 Python 3.12。需要 npx 的配置会检查并安装 Node.js LTS。脚本自己的 `tomlkit`、`uv` 放在 `.venv`，MarkItDown/Semgrep 使用各自的 Python 3.12 环境。uv 会在需要时下载 Python；首次安装需联网。无需复制原电脑的 Python 目录。

首次配置会提示输入缺失的凭证（输入隐藏）。Context7 的 `MCP_CONTEXT7_AUTHORIZATION` 要输入完整的 `Bearer <token>`；`GITHUB_PAT_TOKEN` 输入 token 本身。也可提前设置当前进程或用户环境变量。凭证只保存在本机 `.local/secrets.json` 和生成的 Codex 配置中，不上传。OAuth 服务须在每台电脑分别执行 `codex mcp login <名称>`。

完成后重启 Codex，在 MCP 列表检查连接状态。安装成功、配置成功和 MCP 握手成功是不同层次；本脚本不宣称自动完成所有服务的登录/在线健康验证。

## 日常双向同步

在任意电脑通过 Codex 或编辑用户配置新增/修改 MCP 后：

```powershell
powershell -ExecutionPolicy Bypass -File .\sync.ps1 push -Message "Add a new MCP"
```

它会导出 MCP、移除字面量凭证、检查便携路径、提交并上传。**仅修改配置不会自动上传，必须执行 push。** 若还编辑了仓库配置，执行 `setup.ps1` 将其应用到本机。

其他电脑更新：

```powershell
powershell -ExecutionPolicy Bypass -File .\sync.ps1 pull
```

它会 `git pull --ff-only`，准备依赖并合并配置。存在未上传的本机修改时先停止，请先 push。本机和远端都已提交而分叉时，执行 `git fetch`、`git merge origin/main`，解决 `config.toml/settings.json` 冲突后 `git push`，再运行 `setup.ps1`。脚本不会强推或自动选择冲突一方。

单独导出、检查和查看方案：

```powershell
.\sync.ps1 export
.\sync.ps1 check
.\setup.ps1 -Plan
.\setup.ps1 -Target "$PWD\.local\trial\config.toml"
```

`-Plan` 不改 Codex 配置，但仍会准备脚本的 Python 环境。`-NonInteractive` 禁止交互输入，缺少凭证时报错。`-SkipInstall` 只合并配置，命令仍必须已存在。`-Force` 明确放弃对本机未导出修改的保护，以仓库同名配置覆盖。

## 当前纳入的 MCP

| MCP | 部署方式 |
|---|---|
| Context7 | 远程 HTTP；设备本地 Authorization |
| GitHub | 远程 HTTP；设备本地 PAT |
| EdgeOne Pages/Makers | Node.js + npx；首次启动下载 npm 包，服务登录单独完成 |
| shadcn | Node.js + npx；首次启动下载 npm 包 |
| MarkItDown | 独立 Python 3.12 + markitdown-mcp==0.0.1a7 |
| Semgrep | 独立 Python 3.12 + semgrep==1.178.0 |

`node_repl` 被 `settings.json` 的 exclude 排除，因为它是 Codex 桌面生成的本机运行时配置。插件附带的 MCP、Skills、Codex 登录态不属于此仓库的同步范围；各电脑通过 Codex 安装/登录对应插件。

初始检查发现原电脑的 Semgrep 运行时报 `CertOpenSystemStore returned NULL`。独立安装不会保证修复操作系统证书访问问题，需要在正常用户终端验证 `semgrep mcp`。此问题不应误认为 Git 同步故障。

## 新增本地服务器

远程 HTTP/npx 服务一般直接导出即可。**自定义本地源码不会因一个 command 路径而自动被复制**；要把源码及依赖清单纳入本仓库，或在 `settings.json` 增加安装步骤。路径使用 `${ROOT}`（仓库）、`${USERPROFILE}`、`${CODEX_HOME}`、`${ENV:变量名}`。这些是本脚本展开的占位符，不是 Codex 自身的 TOML 插值功能。

例如把自有 Python MCP 源码放在 `servers/demo/server.py`，配置：

```toml
[mcp_servers.demo]
command = "${ROOT}/.local/servers/demo/Scripts/python.exe"
args = ["${ROOT}/servers/demo/server.py"]
```

在 `settings.json` 的 recipes 中添加：

```json
"demo": {
  "python": "3.12",
  "packages": ["mcp>=1,<2"],
  "command": "${ROOT}/.local/servers/demo/Scripts/python.exe",
  "args": ["${ROOT}/servers/demo/server.py"]
}
```

需要 clone/build 的项目，可以使用 recipe 的 `install` 数组，每个子数组是一个命令及参数，以仓库为工作目录运行。步骤应支持重复执行。例如源码已纳入仓库时：`"install": [["npm.cmd", "ci", "--prefix", "${ROOT}/servers/example"]]`。其他运行时（Docker、WSL）、localhost 后台服务、数据库和桌面应用需要针对该 MCP 补充安装/启动 recipe；脚本不会猜测这些依赖。源码目录需手动 `git add servers` 后提交，push 脚本只自动暂存已知配置及脚本目录。

常规 python/node 绝对路径会被转换为设备占位符，但该文件仍须在目标设备存在；更推荐独立安装 recipe。无法便携化的盘符路径会阻止导出，先将它改成占位符并提供文件/安装方式。凭证如果藏在自定义参数中，应手动改成 `${ENV:变量名}`；导出的敏感字段/常见 token 检查不能代替审阅任意新配置。

## 删除、备份与凭证

- 想在所有电脑停用服务，在仓库对应段设置 `enabled = false`，提交并同步。
- 从仓库删除某段不会删除另一电脑上的本地 MCP，避免误删设备独有服务。彻底删除时在各电脑手动删除该段。
- 备份位于原配置旁的 `config.toml.mcp-sync-*.bak`；恢复时关闭 Codex 并将选定备份覆盖回配置。
- `.local` 包含凭证和同步状态，不应复制/上传；`.venv` 和本地服务器环境都不进 Git。
- 私有仓库也不保存 token。脚本会把共享凭证引用展开到本机 Codex 配置，因此无需依赖 Codex 桌面是否继承当前终端环境。

## 从文件夹首次发布

本仓库若尚未上传，可运行 `powershell -ExecutionPolicy Bypass -File .\publish.ps1` 创建 **private** 仓库。已存在远端时不再运行 publish，用 sync push/pull。支持现有 gh 登录或当前进程 `GITHUB_PAT_TOKEN`（仅临时映射为 GH_TOKEN）；Git remote 不含 token。

## 本地测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

参考：[Codex MCP 配置](https://developers.openai.com/codex/mcp)、[GitHub CLI 私有仓库创建](https://cli.github.com/manual/gh_repo_create)。
