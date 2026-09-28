"""Install the pinned upstream Google Scholar MCP source without Smithery."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".local" / "sources" / "google-scholar"
UPSTREAM = "https://github.com/JackKuo666/Google-Scholar-MCP-Server.git"
REVISION = "738d60a4d69464731e7c5b3a61767c06ff2cec0d"
GIT = ["git", "-c", "http.sslBackend=openssl"]


def git(*args):
    return subprocess.check_output([*GIT, *args], text=True).strip()


def main():
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists():
        subprocess.run([*GIT, "clone", UPSTREAM, str(SOURCE)], check=True)
    if not (SOURCE / ".git").is_dir():
        raise RuntimeError(f"Incomplete Google Scholar source checkout: {SOURCE}")
    if git("-C", str(SOURCE), "rev-parse", "HEAD") != REVISION:
        subprocess.run([*GIT, "-C", str(SOURCE), "fetch", "origin", REVISION], check=True)
        subprocess.run([*GIT, "-C", str(SOURCE), "checkout", "--detach", REVISION], check=True)
    if git("-C", str(SOURCE), "rev-parse", "HEAD") != REVISION:
        raise RuntimeError("Google Scholar source is not at the configured revision")
    entrypoint = SOURCE / "google_scholar_server.py"
    if not entrypoint.is_file():
        raise RuntimeError("Google Scholar MCP entrypoint is missing")
    original_import = "from mcp.server.fastmcp import FastMCP"
    compatible_import = "from mcp.server.mcpserver import MCPServer as FastMCP"
    source = entrypoint.read_text(encoding="utf-8")
    if original_import in source:
        entrypoint.write_text(source.replace(original_import, compatible_import, 1), encoding="utf-8")
    elif compatible_import not in source:
        raise RuntimeError("Google Scholar MCP entrypoint has changed; review the SDK compatibility patch")
    print(f"Google Scholar MCP source: {SOURCE} ({REVISION[:12]})")


if __name__ == "__main__":
    main()
