"""Install pinned paper MCP sources into the local sync directory."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REVISIONS = {
    'scansci-pdf': 'b588f2c21e10fbf056b355e0f46c1016d624cd9c',
    'instsci': '7a233a4df767c7fe64f03491ef1b6abe84d08c34',
}

def main(name):
    revision = REVISIONS[name]
    source = ROOT / '.local/sources' / name
    source.parent.mkdir(parents=True, exist_ok=True)
    def run(*args):
        subprocess.run(list(map(str, args)), check=True, cwd=ROOT)
    if not source.exists():
        run('git', 'clone', '--depth', '1', f'https://github.com/Rimagination/{name}.git', source)
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != revision:
        if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
            raise RuntimeError(f'Preserve local source changes before changing revision: {source}')
        run('git', '-C', source, 'fetch', 'origin', revision)
        run('git', '-C', source, 'checkout', '--detach', revision)
    uv = ROOT / '.venv/Scripts/uv.exe'
    env = ROOT / '.local/servers' / name
    python = env / 'Scripts/python.exe'
    if not python.exists():
        run(uv, 'venv', '--python', '3.14.7', env)
    package = str(source) + ('[vpnsci,cloakbrowser]' if name == 'scansci-pdf' else '')
    run(uv, 'pip', 'install', '--python', python, '-e', package, *(['mcp>=1.12,<2'] if name == 'instsci' else []))

if __name__ == '__main__':
    main(sys.argv[1])

