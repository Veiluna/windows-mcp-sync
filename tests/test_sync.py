import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import tomlkit

spec = importlib.util.spec_from_file_location('sync', Path(__file__).resolve().parents[1] / 'scripts/mcp_sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.target = Path(self.temp.name) / 'device/config.toml'
        self.target.parent.mkdir()
        sync.write_json(self.root / 'settings.json', {'exclude': ['node_repl']})

    def write_shared(self, servers):
        (self.root / 'config.toml').write_text(tomlkit.dumps({'mcp_servers': servers}), encoding='utf8')

    def test_export_redacts_credentials_and_excludes_runtime(self):
        self.target.write_text('''model = "keep"
[mcp_servers.node_repl]
command = "device-runtime"
[mcp_servers.remote]
url = "https://example.com/mcp"
[mcp_servers.remote.http_headers]
Authorization = "Bearer very-private-value"
[mcp_servers.local]
command = "npx"
[mcp_servers.local.env]
API_KEY = "very-private-value"
REGION = "china"
''', encoding='utf8')
        sync.export_config(self.root, self.target)
        text = (self.root / 'config.toml').read_text()
        self.assertNotIn('very-private-value', text)
        self.assertNotIn('node_repl', text)
        self.assertNotIn('model', text)
        self.assertIn('REGION', text)
        self.assertIn('MCP_REMOTE_AUTHORIZATION', text)

    def test_apply_preserves_other_settings_is_idempotent_and_backs_up(self):
        self.target.write_text('# retained comment\nmodel = "keep"\n[mcp_servers.device]\nurl = "https://local.example/mcp"\n', encoding='utf8')
        self.write_shared({'new': {'url': 'https://example.com/mcp'}})
        sync.apply_config(self.root, self.target)
        once = self.target.read_text()
        sync.apply_config(self.root, self.target)
        self.assertEqual(once, self.target.read_text())
        self.assertIn('# retained comment', once)
        self.assertEqual(sync.read_toml(self.target)['model'], 'keep')
        self.assertIn('device', sync.read_toml(self.target)['mcp_servers'])
        self.assertEqual(len(list(self.target.parent.glob('*.bak'))), 1)

    def test_bearer_and_header_roundtrip(self):
        original = {'github': {'url': 'https://example.com/mcp', 'bearer_token_env_var': 'GITHUB_PAT_TOKEN'},
                    'other': {'url': 'https://example.org/mcp', 'env_http_headers': {'X-Key': 'MY_HEADER'}}}
        self.write_shared(original)
        with patch.dict(os.environ, {'GITHUB_PAT_TOKEN': 'test-value', 'MY_HEADER': 'private-header'}):
            sync.apply_config(self.root, self.target)
        sync.export_config(self.root, self.target)
        self.assertEqual(sync.plain(sync.read_toml(self.root / 'config.toml'))['mcp_servers'], original)
        self.assertNotIn('private-header', (self.root / 'config.toml').read_text())

    def test_missing_credential_does_not_write_target(self):
        self.write_shared({'r': {'url': 'https://example.com', 'bearer_token_env_var': 'UNSET_TEST_KEY'}})
        with patch.dict(os.environ, {'UNSET_TEST_KEY': ''}), self.assertRaisesRegex(ValueError, 'missing'):
            sync.apply_config(self.root, self.target)
        self.assertFalse(self.target.exists())

    def test_local_edits_block_pull_and_apply(self):
        self.write_shared({'r': {'url': 'https://example.com'}})
        sync.apply_config(self.root, self.target)
        self.target.write_text(self.target.read_text().replace('example.com', 'changed.com'), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'unpublished'):
            sync.check_local(self.root, self.target)
        with self.assertRaisesRegex(ValueError, 'local changes'):
            sync.apply_config(self.root, self.target)
        sync.export_config(self.root, self.target)
        sync.record(self.root, self.target)
        sync.check_local(self.root, self.target)

    def test_shared_edits_not_overwritten_by_unchanged_device(self):
        self.write_shared({'r': {'url': 'https://old.example'}})
        sync.apply_config(self.root, self.target)
        self.write_shared({'r': {'url': 'https://new.example'}})
        sync.export_config(self.root, self.target)
        self.assertEqual(sync.read_toml(self.root / 'config.toml')['mcp_servers']['r']['url'], 'https://new.example')

    def test_conflicting_device_and_shared_edits_fail(self):
        self.write_shared({'r': {'url': 'https://old.example'}})
        sync.apply_config(self.root, self.target)
        self.write_shared({'r': {'url': 'https://new.example'}})
        self.target.write_text(self.target.read_text().replace('old.example', 'device.example'), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'both local and shared'):
            sync.export_config(self.root, self.target)

    def test_disabled_service_does_not_need_credential_or_executable(self):
        self.write_shared({'r': {'enabled': False, 'command': 'nonexistent-program', 'env_vars': ['MISSING']}})
        sync.apply_config(self.root, self.target)

    def test_paths_expand_without_corrupting_toml(self):
        value = {'command': '${ROOT}/with spaces/a.exe', 'args': ['${USERPROFILE}/data']}
        rendered = sync.expand(value, self.root, self.target)
        self.assertEqual(rendered['command'], str(self.root).replace('\\', '/') + '/with spaces/a.exe')
        self.assertEqual(sync.portable(rendered, self.root, self.target), value)

    def test_new_local_mcp_detected_before_pull(self):
        self.write_shared({'r': {'url': 'https://example.com'}})
        sync.apply_config(self.root, self.target)
        with self.target.open('a') as f:
            f.write('\n[mcp_servers.new]\nurl = "https://new.example"\n')
        with self.assertRaisesRegex(ValueError, 'New local'):
            sync.check_local(self.root, self.target)

    def test_reject_secret_and_unportable_path(self):
        for server in [{'command': 'C:/Users/old/python.exe'}, {'url': 'https://example.com?token=secret'},
                       {'command': 'npx', 'args': ['--token', 'ghp_privatevalue']}]:
            with self.assertRaises(ValueError):
                sync.validate({'mcp_servers': {'bad': server}})

    def test_shared_removal_preserves_device_server(self):
        self.write_shared({'r': {'url': 'https://example.com'}})
        sync.apply_config(self.root, self.target)
        self.write_shared({})
        sync.apply_config(self.root, self.target)
        self.assertIn('r', sync.read_toml(self.target)['mcp_servers'])

    def test_target_state_is_separate(self):
        self.write_shared({'r': {'url': 'https://example.com'}})
        sync.apply_config(self.root, self.target)
        other = self.target.with_name('other.toml')
        sync.apply_config(self.root, other)
        self.assertNotEqual(sync.state_path(self.root, self.target), sync.state_path(self.root, other))


if __name__ == '__main__':
    unittest.main()
