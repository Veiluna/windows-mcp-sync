# Windows MCP Sync

在多台 Windows 电脑之间同步 **Codex 用户级 MCP 配置**，并自动准备本地服务器运行环境。

项目通过 Git 管理可共享的配置和安装步骤，将凭证、虚拟环境与设备状态保留在本机。适合需要在多台设备复用 MCP 配置，同时保留设备独立设置的用户。

仓库里的 `config.toml` 只保存 `mcp_servers`。`setup.ps1` 按服务器名称合并到 `$CODEX_HOME/config.toml`（默认 `%USERPROFILE%/.codex/config.toml`），保留模型、插件、项目、注释以及本机独有的 MCP，写入前自动备份。

## 快速开始

需要安装 Codex，并拥有目标 GitHub 仓库的访问权限。支持 Windows PowerShell 5.1 和 PowerShell 7，首次安装需联网；自动安装系统依赖时需要 winget。

建议将个人配置放在自己控制的私有仓库中。将以下 `YOUR_ACCOUNT/YOUR_REPOSITORY` 替换为自己的仓库，或其他已授权访问的实例。

```powershell
winget install --id Git.Git --exact
winget install --id GitHub.cli --exact
# 安装完成后重新打开终端
gh auth login
gh auth setup-git
gh repo clone YOUR_ACCOUNT/YOUR_REPOSITORY windows-mcp-sync
cd windows-mcp-sync
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

脚本自身需要 Python 3.11+；缺失时通过 winget 安装 Python 3.12。这是安装工具的引导环境，与固定使用 Python 3.14.7 的 MCP 环境分开。需要 npx 的配置会检查并安装 Node.js LTS。脚本自己的 `tomlkit`、`uv`、`pipx` 放在 `.venv`。MarkItDown 使用独立 Python 3.14.7 环境；Semgrep 改用官方 pipx 安装，指定 Python 3.14.7，缺失时由 pipx 下载。首次安装需联网。pipx 按官方默认规则选择安装后端；本脚本自带 uv，可用于加快依赖安装，环境与命令入口仍由 pipx 管理。

首次运行前，可在 `config.toml` 将不需要的服务设置为 `enabled = false`。

首次配置会提示输入缺失的凭证（输入隐藏）。Context7 的 `MCP_CONTEXT7_AUTHORIZATION` 要输入完整的 `Bearer <token>`；`GITHUB_PAT_TOKEN` 输入 token 本身。也可提前设置当前进程或用户环境变量。凭证保存在本机 `.local/secrets.json` 和生成的 Codex 配置中，不通过 Git 同步。这些文件不是加密凭证库，应限制本机访问权限。OAuth 服务须在每台电脑分别执行 `codex mcp login <名称>`。

完成后重启 Codex，在 MCP 列表检查连接状态。脚本负责安装依赖和合并配置；各服务的账号登录与在线连接仍需按服务要求完成。

## 日常同步

在任意电脑通过 Codex 或编辑用户配置新增/修改 MCP 后：

```powershell
powershell -ExecutionPolicy Bypass -File .\sync.ps1 push -Message "Add a new MCP"
```

它会导出 MCP、移除字面量凭证、检查便携路径、提交并上传。**仅修改配置不会自动上传，必须执行 push。** 若还编辑了仓库配置，执行 `setup.ps1` 将其应用到本机。

其他电脑更新：

```powershell
powershell -ExecutionPolicy Bypass -File .\sync.ps1 pull
```

它会 `git pull --ff-only`，准备依赖并合并配置。存在未上传的本机修改时先停止，请先 push。本机和远端都已提交而分叉时，执行 `git fetch`、`git merge origin/master`，解决 `config.toml/settings.json` 冲突后 `git push`，再运行 `setup.ps1`。脚本不会强推或自动选择冲突一方。

### 辅助命令

单独导出、检查和查看服务清单：

```powershell
.\sync.ps1 export
.\sync.ps1 check
.\setup.ps1 -Plan
.\setup.ps1 -Target "$PWD\.local\trial\config.toml"
```

`-Plan` 不改 Codex 配置，但仍会准备脚本的 Python 环境。`-NonInteractive` 禁止交互输入，缺少凭证时报错。`-SkipInstall` 只合并配置，命令仍必须已存在。`-Force` 明确放弃对本机未导出修改的保护，以仓库同名配置覆盖。

## 内置 MCP

| MCP | 部署方式 |
|---|---|
| Context7 | 远程 HTTP；设备本地 Authorization |
| GitHub | 远程 HTTP；设备本地 PAT |
| EdgeOne Pages/Makers | Node.js + npx；首次启动下载 npm 包，服务登录单独完成 |
| shadcn | Node.js + npx；首次启动下载 npm 包 |
| MarkItDown | 独立 Python 3.14.7 + markitdown-mcp==0.0.1a7 |
| Semgrep | 仓库内 pipx 环境 + Python 3.14.7 + semgrep==1.178.0 |

`node_repl` 被 `settings.json` 的 exclude 排除，因为它是 Codex 桌面生成的本机运行时配置。插件附带的 MCP、Skills、Codex 登录态不属于此仓库的同步范围；各电脑通过 Codex 安装/登录对应插件。

Semgrep 1.178.0 的 OAuth 元数据请求使用 2 秒连接超时，代理/TLS 握手较慢时会使 `semgrep mcp` 启动失败。安装 recipe 会执行 `scripts/patch_semgrep_timeout.py`，将这一处连接超时改为 15 秒（读取超时保持 30 秒），保留认证和 TLS 校验；Codex 的启动等待设置为 60 秒。补丁检查版本和原始源码，首次修改旁存 `utils.py.before-mcp-timeout-fix.bak`，重复执行不重复修改。升级 Semgrep 后需重新评估此补丁。

## Semgrep 登录与 Pro 引擎

运行 `powershell -ExecutionPolicy Bypass -File .\setup.ps1`，然后重新打开终端：

```powershell
semgrep --version
semgrep login
semgrep install-semgrep-pro
```

Semgrep CLI 支持登录和安装 Pro 引擎；Pro 功能取决于账号权限。setup 不自动登录或下载 Pro 引擎，登录信息不随 Git 同步。

Codex 和终端使用同一个仓库内 pipx 安装。脚本按仓库位置设置 `PIPX_HOME`、`PIPX_BIN_DIR` 和 `PIPX_MAN_DIR`，不依赖全局 pipx 的默认安装目录。`${PIPX_BIN}` 和 `${PIPX_VENVS}` 由脚本展开。

如果 pipx 只残留目录、缺少 `pyvenv.cfg` / 元数据，或解释器无法启动，setup 会先将该目录移动到 pipx 主目录下的 `mcp-sync-backups` 保存，再重新安装；不会仅凭目录存在判断安装成功。

已是 Python 3.14.7 + Semgrep 1.178.0 时不会重装，保留环境里的 Pro 引擎。Python 版本不同时执行 pipx reinstall；包版本不同时安装仓库指定版本。重建环境后需重新执行 `semgrep install-semgrep-pro`。环境被运行中的 MCP 占用时，重建可能失败；先退出相关进程再重试。

脚本自带的 pipx 可这样管理：

```powershell
. .\scripts\common.ps1
.\.venv\Scripts\python.exe -m pipx list
.\.venv\Scripts\python.exe -m pipx environment
```

所有 Python MCP（MarkItDown、Semgrep）均锁定 Python 3.14.7，检查包含补丁号。MarkItDown 旧环境会先备份再重建；EdgeOne 和 shadcn 是 Node.js 程序，继续使用 Node.js。升级 Semgrep 时需一起更新 `settings.json` 和版本相关的超时补丁。

参考：[Semgrep Windows 安装](https://semgrep.dev/docs/getting-started/quickstart)、[pipx 命令参考](https://pipx.pypa.io/stable/reference/cli.html)。

## 目录与运行环境

```text
windows-mcp-sync/
├── config.toml              # 可共享的 MCP 声明
├── settings.json            # 安装步骤和排除项
├── setup.ps1                # 安装并应用配置
├── sync.ps1                 # 导出、检查、上传、下载
├── publish.ps1              # 首次创建 GitHub 私有仓库
├── scripts/                 # 同步和安装逻辑
├── tests/                   # 回归测试
├── .venv/                   # 同步工具：tomlkit、uv、pipx
└── .local/                  # 本机数据，不提交到 Git
    ├── bin/                 # Semgrep 命令入口
    ├── secrets.json         # 本机凭证
    └── servers/
        ├── markitdown/      # MarkItDown 虚拟环境
        └── pipx/venvs/
            └── semgrep/     # Semgrep 虚拟环境
```

两个 Python MCP 固定使用 Python 3.14.7，但各自隔离依赖。Node.js MCP 继续使用 Node.js。虚拟环境不应跨设备复制；新设备或新目录应重新克隆仓库并运行安装脚本。

## 添加自定义 MCP

远程 HTTP/npx 服务一般直接导出即可。**自定义本地源码不会因一个 command 路径而自动被复制**；要把源码及依赖清单纳入本仓库，或在 `settings.json` 增加安装步骤。路径使用 `${ROOT}`（仓库）、`${USERPROFILE}`、`${CODEX_HOME}`、`${ENV:变量名}`。这些是本脚本展开的占位符，不是 Codex 自身的 TOML 插值功能。

例如把自有 Python MCP 源码放在 `servers/demo/server.py`，配置：

```toml
[mcp_servers.demo]
command = "${ROOT}/.local/servers/demo/Scripts/python.exe"
args = ["${ROOT}/servers/demo/server.py"]
```

在 `settings.json` 的 `recipes` 对象中添加以下成员，并按实际需要调整依赖：

```json
{
  "demo": {
  "python": "3.14.7",
  "packages": ["mcp>=1,<2"],
  "command": "${ROOT}/.local/servers/demo/Scripts/python.exe",
  "args": ["${ROOT}/servers/demo/server.py"]
  }
}
```

需要 clone/build 的项目，可以使用 recipe 的 `install` 数组，每个子数组是一个命令及参数，以仓库为工作目录运行。步骤应支持重复执行。例如源码已纳入仓库时：`"install": [["npm.cmd", "ci", "--prefix", "${ROOT}/servers/example"]]`。其他运行时（Docker、WSL）、localhost 后台服务、数据库和桌面应用需要针对该 MCP 补充安装/启动 recipe；脚本不会猜测这些依赖。源码目录需手动 `git add servers` 后提交，push 脚本只自动暂存已知配置及脚本目录。

常规 python/node 绝对路径会被转换为设备占位符，但该文件仍须在目标设备存在；更推荐独立安装 recipe。无法便携化的盘符路径会阻止导出，先将它改成占位符并提供文件/安装方式。凭证如果藏在自定义参数中，应手动改成 `${ENV:变量名}`；导出的敏感字段/常见 token 检查不能代替审阅任意新配置。

## 凭证、删除与备份

- 想在所有电脑停用服务，在仓库对应段设置 `enabled = false`，提交并同步。
- 从仓库删除某段不会删除另一电脑上的本地 MCP，避免误删设备独有服务。彻底删除时在各电脑手动删除该段。
- 备份位于原配置旁的 `config.toml.mcp-sync-*.bak`，可能包含凭证，应同样限制访问。恢复时关闭 Codex，并将选定备份覆盖回配置。
- `.local` 包含凭证和同步状态，不应复制/上传；`.venv` 和本地服务器环境都不进 Git。
- 私有仓库也不保存 token。脚本会把共享凭证引用展开到本机 Codex 配置，因此无需依赖 Codex 桌面是否继承当前终端环境。

## 发布自己的同步仓库

对于尚未设置远端的项目副本，可运行 `powershell -ExecutionPolicy Bypass -File .\publish.ps1` 创建 **private** 仓库。已有远端时，先确认 `origin` 指向自己有写入权限的仓库，再使用 sync push/pull，无需重复运行 publish。支持现有 gh 登录或当前进程 `GITHUB_PAT_TOKEN`（仅临时映射为 GH_TOKEN）；Git remote 不含 token。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

提交修改时，请说明配置或安装行为的变化及验证结果，避免提交凭证、虚拟环境和本机状态文件。

参考：[Codex MCP 配置](https://developers.openai.com/codex/mcp)、[GitHub CLI 私有仓库创建](https://cli.github.com/manual/gh_repo_create)。
