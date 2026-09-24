import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import os
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('sync_pipx', Path(__file__).resolve().parents[1] / 'scripts/mcp_sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

class PipxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.venvs = self.root / 'custom-venvs'
        self.folder = self.venvs / 'semgrep'
        self.folder.mkdir(parents=True)
        self.metadata = self.folder / 'pipx_metadata.json'
        self.recipe = {'package': 'semgrep==1.178.0', 'python': '3.14.7'}

    def put_metadata(self, version='1.178.0'):
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / 'pyvenv.cfg').write_text('home = test')
        executable = self.folder / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        executable.parent.mkdir(exist_ok=True)
        executable.touch()
        self.metadata.write_text(json.dumps({'main_package': {'package_version': version}}))

    def test_repeated_setup_does_not_reinstall(self):
        self.put_metadata()
        with patch.object(sync, 'pipx_path', return_value=self.venvs), patch.object(sync.subprocess, 'check_output', return_value='3.14.7'), patch.object(sync, 'run') as run:
            sync.install_pipx('semgrep', self.recipe, self.root)
        self.assertEqual([c.args[0][3:] for c in run.call_args_list], [['ensurepath']])

    def test_new_install_requests_python_314(self):
        def install(argv, cwd):
            if 'install' in argv:
                self.put_metadata()
        with patch.object(sync, 'pipx_path', return_value=self.venvs), patch.object(sync.subprocess, 'check_output', return_value='3.14.7'), patch.object(sync, 'run', side_effect=install) as run:
            sync.install_pipx('semgrep', self.recipe, self.root)
        self.assertEqual(run.call_args_list[0].args[0][3:], ['install', '--python', '3.14.7', '--fetch-python=missing', 'semgrep==1.178.0'])

    def test_python_migration_uses_reinstall(self):
        self.put_metadata()
        with patch.object(sync, 'pipx_path', return_value=self.venvs), patch.object(sync.subprocess, 'check_output', side_effect=['3.14.6', '3.14.7']), patch.object(sync, 'run') as run:
            sync.install_pipx('semgrep', self.recipe, self.root)
        self.assertEqual(run.call_args_list[0].args[0][3:], ['reinstall', '--python', '3.14.7', '--fetch-python=missing', 'semgrep'])

    def test_custom_pipx_paths_resolve(self):
        with patch.object(sync, 'pipx_path', return_value=self.venvs):
            actual = sync.expand('${PIPX_BIN}/semgrep.exe', self.root, self.root / 'config.toml')
        self.assertEqual(actual, self.venvs.as_posix() + '/semgrep.exe')

    def test_wrong_python_after_install_is_rejected(self):
        self.put_metadata()
        with patch.object(sync, 'pipx_path', return_value=self.venvs), patch.object(sync.subprocess, 'check_output', return_value='3.14.6'), patch.object(sync, 'run'), self.assertRaisesRegex(ValueError, 'does not match'):
            sync.install_pipx('semgrep', self.recipe, self.root)

    def test_package_version_update_keeps_python_selection(self):
        self.put_metadata('1.177.0')
        def update(argv, cwd):
            if 'install' in argv:
                self.put_metadata()
        with patch.object(sync, 'pipx_path', return_value=self.venvs), patch.object(sync.subprocess, 'check_output', return_value='3.14.7'), patch.object(sync, 'run', side_effect=update) as run:
            sync.install_pipx('semgrep', self.recipe, self.root)
        self.assertEqual(run.call_args_list[0].args[0][3:], ['install', '--force', 'semgrep==1.178.0'])

    def test_pipx_command_survives_apply_export_roundtrip(self):
        command = self.root / 'bin/semgrep.exe'
        command.parent.mkdir()
        command.touch()
        server = {'command': '${PIPX_BIN}/semgrep.exe', 'args': ['mcp']}
        sync.atomic_write(self.root / 'config.toml', sync.tomlkit.dumps({'mcp_servers': {'semgrep': server}}))
        sync.write_json(self.root / 'settings.json', {'recipes': {'semgrep': dict(self.recipe, **server)}})
        target = self.root / 'device/config.toml'
        with patch.object(sync, 'pipx_path', return_value=command.parent):
            sync.apply_config(self.root, target)
            sync.export_config(self.root, target)
        actual = sync.plain(sync.read_toml(self.root / 'config.toml'))['mcp_servers']['semgrep']
        self.assertEqual(actual, server)

    def test_partial_folder_without_metadata_is_backed_up_and_reinstalled(self):
        marker = self.folder / 'old-files.txt'
        marker.write_text('preserve')
        def install(argv, cwd):
            if 'install' in argv:
                self.put_metadata()
        with patch.object(sync, 'pipx_path', return_value=self.venvs), patch.object(sync.subprocess, 'check_output', return_value='3.14.7'), patch.object(sync, 'run', side_effect=install) as run:
            sync.install_pipx('semgrep', self.recipe, self.root)
        backups = list((self.root / 'mcp-sync-backups').glob('semgrep-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'old-files.txt').read_text(), 'preserve')
        self.assertFalse(marker.exists())
        self.assertIn('install', run.call_args_list[0].args[0])

    def test_existing_metadata_but_broken_interpreter_is_recovered(self):
        self.put_metadata()
        def install(argv, cwd):
            if 'install' in argv:
                self.put_metadata()
        failure = subprocess.CalledProcessError(106, ['python.exe'])
        with patch.object(sync, 'pipx_path', return_value=self.venvs), patch.object(sync.subprocess, 'check_output', side_effect=[failure, '3.14.7']), patch.object(sync, 'run', side_effect=install) as run:
            sync.install_pipx('semgrep', self.recipe, self.root)
        self.assertIn('install', run.call_args_list[0].args[0])
        self.assertNotIn('reinstall', run.call_args_list[0].args[0])
        self.assertEqual(len(list((self.root / 'mcp-sync-backups').glob('semgrep-*'))), 1)
