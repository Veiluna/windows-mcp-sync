"""Opt-in Windows integration test: MCP_SYNC_INTEGRATION=1 python -m unittest ..."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == 'nt' and os.getenv('MCP_SYNC_INTEGRATION') == '1', 'opt-in Windows Git integration')
class GitSyncTest(unittest.TestCase):
    def test_two_devices_push_pull_and_local_credentials(self):
        source = Path(__file__).resolve().parents[1]
        # Keep the fixture for inspection; do not recursively remove a venv junction.
        fixture = Path(tempfile.mkdtemp(prefix='mcp-sync-e2e-'))
        a, b, remote = (fixture / name for name in ('pc-a', 'pc-b', 'origin.git'))
        env = os.environ.copy()
        env.pop('GH_TOKEN', None)
        env.pop('GITHUB_PAT_TOKEN', None)
        def run(*args, cwd=None):
            result = subprocess.run(list(map(str, args)), cwd=cwd, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout
        def ps(repo, script, *args):
            env['MCP_TEST_HEADER'] = 'private-device-a' if repo == a else 'private-device-b'
            return run('powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', repo / script, *args)
        def junction(repo):
            command = "New-Item -ItemType Junction -Path '" + str(repo / '.venv') + "' -Target '" + str(source / '.venv') + "' | Out-Null"
            run('powershell.exe', '-NoProfile', '-Command', command)
        run('git', 'init', '--bare', remote)
        a.mkdir()
        for file in source.iterdir():
            if file.is_file():
                shutil.copy2(file, a / file.name)
        for directory in ('scripts', 'tests'):
            shutil.copytree(source / directory, a / directory, ignore=shutil.ignore_patterns('__pycache__'))
        (a / 'settings.json').write_text('{"exclude":["node_repl"],"recipes":{}}', encoding='utf8')
        (a / 'config.toml').write_text('[mcp_servers.initial]\nurl="https://example.com/mcp"\n[mcp_servers.initial.env_http_headers]\nX-Test="MCP_TEST_HEADER"\n', encoding='utf8')
        run('git', 'init', '-b', 'main', a)
        run('git', '-C', a, 'add', '.')
        run('git', '-C', a, 'commit', '-m', 'Test fixture')
        run('git', '-C', a, 'remote', 'add', 'origin', remote)
        run('git', '-C', a, 'push', '-u', 'origin', 'main')
        run('git', '--git-dir', remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        run('git', 'clone', remote, b)
        junction(a)
        junction(b)
        target_a, target_b = fixture / 'device-a.toml', fixture / 'device-b.toml'
        target_a.write_text('model="device-a"\n', encoding='utf8')
        target_b.write_text('model="device-b"\n', encoding='utf8')
        ps(a, 'setup.ps1', '-Target', target_a, '-NonInteractive')
        ps(b, 'setup.ps1', '-Target', target_b, '-NonInteractive')
        with target_a.open('a') as out:
            out.write('\n[mcp_servers.from_a]\nurl="https://a.example/mcp"\n')
        ps(a, 'sync.ps1', 'push', '-Target', target_a)
        ps(b, 'sync.ps1', 'pull', '-Target', target_b, '-NonInteractive')
        self.assertIn('from_a', target_b.read_text())
        self.assertIn('device-b', target_b.read_text())
        with target_b.open('a') as out:
            out.write('\n[mcp_servers.from_b]\nurl="https://b.example/mcp"\n')
        ps(b, 'sync.ps1', 'push', '-Target', target_b)
        ps(a, 'sync.ps1', 'pull', '-Target', target_a, '-NonInteractive')
        self.assertIn('from_b', target_a.read_text())
        self.assertIn('device-a', target_a.read_text())
        self.assertIn('private-device-a', target_a.read_text())
        self.assertIn('private-device-b', target_b.read_text())
        self.assertNotIn('private-device-', (a / 'config.toml').read_text())
        self.assertNotIn('.local', run('git', '-C', a, 'ls-files'))
        self.assertEqual(run('git', '-C', a, 'rev-parse', 'HEAD'), run('git', '-C', b, 'rev-parse', 'HEAD'))
        print('Two-device integration passed:', fixture)
