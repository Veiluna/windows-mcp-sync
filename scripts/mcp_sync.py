"""Export portable MCP declarations and merge them into a device's Codex config."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

import tomlkit

ROOT = Path(__file__).resolve().parents[1]
SECRET_KEY = re.compile(r"token|secret|password|api.?key|authorization|credential", re.I)
SECRET_VALUE = re.compile(r"(?:gh[pousr]_|github_pat_|sk-[A-Za-z0-9]|ctx7sk-|Bearer\s+)[A-Za-z0-9_./+=-]+")
TOKEN = re.compile(r"\$\{([^}]+)\}")


def read_toml(path):
    return tomlkit.parse(path.read_text(encoding="utf-8-sig")) if path.exists() else tomlkit.document()


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def state_path(root, target):
    identity = os.path.normcase(str(target.resolve()))
    return root / '.local' / ('state-' + hashlib.sha256(identity.encode()).hexdigest()[:16] + '.json')


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.write(text)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path, data):
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def plain(value):
    return value.unwrap() if hasattr(value, "unwrap") else copy.deepcopy(value)


def walk(value, fn):
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [walk(x, fn) for x in value]
    if isinstance(value, dict):
        return {k: walk(v, fn) for k, v in value.items()}
    return value


def expand(value, root, target):
    values = {"ROOT": str(root).replace("\\", "/"), "USERPROFILE": str(Path.home()).replace("\\", "/"),
              "CODEX_HOME": str(target.parent).replace("\\", "/"), "PYTHON": sys.executable,
              "UV": str(Path(sys.executable).with_name("uv.exe" if os.name == "nt" else "uv"))}

    def sub(text):
        def replace(match):
            key = match[1]
            if key in ('PIPX_BIN', 'PIPX_VENVS'):
                setting = 'PIPX_BIN_DIR' if key == 'PIPX_BIN' else 'PIPX_LOCAL_VENVS'
                if key not in values:
                    values[key] = str(pipx_path(setting)).replace('\\', '/')
            if key in values:
                return values[key]
            if key.startswith("ENV:") and os.getenv(key[4:]):
                return os.environ[key[4:]]
            raise ValueError(f"Missing device variable: {key}")
        return TOKEN.sub(replace, text)
    return walk(value, sub)


def portable(value, root, target):
    # Only replace complete path prefixes, never arbitrary substrings.
    prefixes = [(str(root), "${ROOT}"), (str(target.parent), "${CODEX_HOME}"), (str(Path.home()), "${USERPROFILE}")]
    def convert(text):
        normalized = text.replace("\\", "/")
        for prefix, label in prefixes:
            prefix = prefix.replace("\\", "/").rstrip("/")
            if normalized.lower() == prefix.lower() or normalized.lower().startswith(prefix.lower() + "/"):
                return label + normalized[len(prefix):]
        return text
    return walk(value, convert)


def env_name(server, key):
    return "MCP_" + re.sub(r"[^A-Za-z0-9]", "_", server + "_" + key).upper()


def sanitize(name, server, secrets, reference=None):
    server = copy.deepcopy(server)
    reference = reference or {}
    forwarded = [v if isinstance(v, str) else v['name'] for v in server.get('env_vars', [])]
    for key, value in list(server.get("env", {}).items()):
        if key in forwarded or SECRET_KEY.search(key) or SECRET_VALUE.search(str(value)):
            secrets[key] = value
            server["env"].pop(key)
            entries = server.setdefault("env_vars", [])
            if key not in entries:
                entries.append(key)
    if server.get("env") == {}:
        server.pop("env")
    for key, value in server.pop("http_headers", {}).items():
        if key.lower() == 'authorization' and reference.get('bearer_token_env_var') and value.startswith('Bearer '):
            variable = reference['bearer_token_env_var']
            secrets[variable] = value[7:]
            server['bearer_token_env_var'] = variable
            continue
        variable = reference.get('env_http_headers', {}).get(key, env_name(name, key))
        secrets[variable] = value
        server.setdefault("env_http_headers", {})[key] = variable
    return server


def validate(shared):
    if set(shared) - {"mcp_servers"}:
        raise ValueError("Shared config.toml may contain only mcp_servers.")
    for name, server in shared.get("mcp_servers", {}).items():
        if ("command" in server) == ("url" in server):
            raise ValueError(f"{name}: specify exactly one of command or url")
        if server.get("http_headers"):
            raise ValueError(f"{name}: use env_http_headers instead of literal headers")
        for key in server.get("env", {}):
            if SECRET_KEY.search(key):
                raise ValueError(f"{name}: move {key} to env_vars")
        def inspect(text):
            if SECRET_VALUE.search(text):
                raise ValueError(f"{name}: possible literal credential; replace with an environment reference")
            if re.search(r"(?:^|[=\s])[A-Za-z]:[\\/]", text) or text.startswith("\\\\"):
                raise ValueError(f"{name}: absolute Windows path must use a device placeholder")
            if text.startswith(("http://", "https://")):
                url = urlsplit(text)
                if url.username or url.password or url.query:
                    raise ValueError(f"{name}: URL credentials/query must be reviewed and parameterized")
            return text
        walk(server, inspect)


def export_config(root, target):
    settings = read_json(root / "settings.json", {})
    local = plain(read_toml(target)).get("mcp_servers", {})
    path = root / "config.toml"
    existing = plain(read_toml(path)).get("mcp_servers", {})
    state = read_json(state_path(root, target), {})
    secrets = read_json(root / ".local/secrets.json", {})
    merged = copy.deepcopy(existing)
    baseline = state.get("shared", {})
    for name, current in local.items():
        if name in settings.get("exclude", []):
            continue
        clean = sanitize(name, current, secrets, baseline.get(name, existing.get(name)))
        recipe = settings.get("recipes", {}).get(name, {})
        # Preserve an unchanged managed command as a portable recipe reference.
        old = state.get("applied", {}).get(name)
        if recipe and (old is None or all(current.get(k) == old.get(k) for k in ("command", "args"))):
            for key in ("command", "args"):
                if key in recipe:
                    clean[key] = recipe[key]
        clean = portable(clean, root, target)
        if name in baseline and existing.get(name) != baseline[name] and clean != baseline[name] and clean != existing.get(name):
            raise ValueError(f"{name}: both local and shared configuration changed; resolve explicitly before exporting")
        if name in baseline and clean == baseline[name] and existing.get(name) != baseline[name]:
            continue  # Shared edit (including explicit deletion) wins over unchanged device state.
        merged[name] = clean
    result = {"mcp_servers": merged}
    validate(result)
    # Secrets never enter the tracked template. Device storage is gitignored.
    write_json(root / ".local/secrets.json", secrets)
    atomic_write(path, tomlkit.dumps(result))
    print("Exported: " + ", ".join(sorted(merged)))
    print("Device-only exclusions: " + ", ".join(settings.get("exclude", [])))


def run(argv, cwd):
    subprocess.run(argv, cwd=cwd, check=True)


def pipx_path(setting):
    result = subprocess.check_output(
        [sys.executable, '-m', 'pipx', 'environment', '--value', setting], text=True)
    return Path(result.strip())


def install_pipx(name, recipe, root):
    package = recipe['package']
    # A fixed version is needed because the Semgrep source patch is version-specific.
    package_name, separator, version = package.partition('==')
    if not separator or package_name != name or not version:
        raise ValueError(f'{name}: pipx recipe requires package=name==version')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name):
        raise ValueError('Invalid pipx environment name')
    required_python = recipe.get('python', '3.14.7')
    venvs = pipx_path('PIPX_LOCAL_VENVS').resolve()
    folder = venvs / name
    if folder.resolve() != folder:
        raise ValueError(f'{name}: pipx environment is a link outside its expected location')
    python = folder / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    metadata_path = folder / 'pipx_metadata.json'
    prefix = [sys.executable, '-m', 'pipx']
    metadata = {}
    actual_python = None
    try:
        metadata = read_json(metadata_path, {})
        if metadata.get('main_package', {}).get('package_version') and (folder / 'pyvenv.cfg').is_file() and python.is_file():
            actual_python = subprocess.check_output(
                [str(python), '-c', 'import sys; print(chr(46).join(map(str, sys.version_info[:3])))'],
                text=True, stderr=subprocess.PIPE, timeout=20).strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        actual_python = None
    if actual_python is None and folder.exists() and any(folder.iterdir()):
        backup_root = venvs.parent / 'mcp-sync-backups'
        if not backup_root.resolve().is_relative_to(venvs.parent):
            raise ValueError('Backup directory must remain inside pipx home')
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / (name + '-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        if backup.resolve().parent != backup_root.resolve():
            raise ValueError('Invalid pipx backup destination')
        folder.rename(backup)
        print(f'{name}: incomplete/broken pipx environment preserved at {backup}; installing Python {required_python}.')
    if actual_python is not None:
        if actual_python != required_python:
            print(f'{name}: recreating pipx environment with Python {required_python}; '
                  're-run install-semgrep-pro afterwards if you use the Pro engine.')
            run(prefix + ['reinstall', '--python', required_python,
                          '--fetch-python=missing', name], root)
        metadata = read_json(metadata_path, {})
        if metadata.get('main_package', {}).get('package_version') != version:
            run(prefix + ['install', '--force', package], root)
    else:
        run(prefix + ['install', '--python', required_python,
                      '--fetch-python=missing', package], root)
    actual_python = subprocess.check_output(
        [str(python), '-c', 'import sys; print(chr(46).join(map(str, sys.version_info[:3])))'],
        text=True).strip()
    metadata = read_json(metadata_path, {})
    if actual_python != required_python or metadata.get('main_package', {}).get('package_version') != version:
        raise ValueError(f'{name}: pipx installation does not match the requested Python/package version')
    run(prefix + ['ensurepath'], root)
    print(f'{name}: pipx Python {actual_python}; executable: {pipx_path("PIPX_BIN_DIR") / (name + ".exe")}')


def install_recipes(root, target, shared):
    settings = read_json(root / "settings.json", {})
    uv = expand("${UV}", root, target)
    for name, recipe in settings.get("recipes", {}).items():
        if name not in shared or shared[name].get("enabled", True) is False:
            continue
        installer = recipe.get('installer', 'venv')
        if installer not in ('venv', 'pipx'):
            raise ValueError(f'{name}: unknown installer {installer}')
        if installer == 'pipx':
            install_pipx(name, recipe, root)
        elif recipe.get("packages"):
            folder = root / ".local/servers" / name
            python = folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            required_python = recipe.get("python", "3.14.7")
            version_command = [str(python), "-c", "import platform; print(platform.python_version())"]
            actual_python = None
            if python.exists():
                try:
                    actual_python = subprocess.check_output(version_command, text=True, stderr=subprocess.PIPE, timeout=20).strip()
                except (OSError, subprocess.SubprocessError):
                    pass
            if actual_python != required_python:
                if folder.exists():
                    if folder.resolve().parent != (root / ".local/servers").resolve():
                        raise ValueError("Server environment must remain inside .local/servers")
                    backup = folder.with_name(folder.name + "-backup-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
                    folder.rename(backup)
                    print(f"{name}: old environment preserved at {backup}")
                run([uv, "venv", "--python", required_python, str(folder)], root)
            run([uv, "pip", "install", "--python", str(python), *recipe["packages"]], root)
            actual_python = subprocess.check_output(version_command, text=True).strip()
            if actual_python != required_python:
                raise ValueError(f"{name}: expected Python {required_python}, got {actual_python}")
            print(f"{name}: Python {actual_python}; executable: {python}")
        for command in recipe.get("install", []):
            run(expand(command, root, target), root)


def apply_config(root, target, install=False, interactive=False, force=False):
    shared = plain(read_toml(root / "config.toml"))
    validate(shared)
    declarations = shared.get("mcp_servers", {})
    before = target.read_text(encoding="utf-8-sig") if target.exists() else ""
    document = tomlkit.parse(before)
    current = plain(document).get("mcp_servers", {})
    state = read_json(state_path(root, target), {})
    secrets = read_json(root / ".local/secrets.json", {})
    desired = expand(declarations, root, target)
    for name, server in desired.items():
        if not force and name in state.get("applied", {}) and current.get(name) != state["applied"][name]:
            raise ValueError(f"{name}: local changes detected; run sync.ps1 push first (or setup.ps1 -Force to discard)")
        if not server.get("enabled", True):
            continue
        def secret(key):
            value = os.getenv(key) or secrets.get(key)
            if not value and interactive:
                value = getpass.getpass(f"{name}: enter {key} (stored only on this device): ")
            if not value:
                raise ValueError(f"{name}: missing {key}; set it in your environment or run setup interactively")
            secrets[key] = value
            return value
        for key in server.get("env_vars", []):
            if isinstance(key, dict) and key.get("source") == "remote":
                continue
            key = key["name"] if isinstance(key, dict) else key
            server.setdefault("env", {})[key] = secret(key)
        for header, variable in server.pop("env_http_headers", {}).items():
            server.setdefault("http_headers", {})[header] = secret(variable)
        if variable := server.pop("bearer_token_env_var", None):
            server.setdefault("http_headers", {})["Authorization"] = "Bearer " + secret(variable)
    if install:
        install_recipes(root, target, declarations)
    for name, server in desired.items():
        if server.get("enabled", True) and "command" in server:
            command = server["command"]
            if not Path(command).is_file() and not shutil.which(command):
                raise ValueError(f"{name}: command not found; add an installation recipe or install {command}")
    document.setdefault("mcp_servers", tomlkit.table())
    for name, server in desired.items():
        document["mcp_servers"][name] = server
    # Removed shared declarations remain local; use enabled=false to propagate a disable.
    rendered = tomlkit.dumps(document)
    tomlkit.parse(rendered)
    if target.exists() and target.read_text(encoding="utf-8-sig") != before:
        raise ValueError("Codex config changed during setup; retry after the other writer finishes")
    if rendered != before:
        if target.exists():
            backup = target.with_name(target.name + ".mcp-sync-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".bak")
            shutil.copy2(target, backup)
        atomic_write(target, rendered)
    write_json(root / ".local/secrets.json", secrets)
    write_json(state_path(root, target), {"shared": declarations, "applied": desired})
    print(f"Applied {len(desired)} servers to {target}; restart Codex to load them.")


def check_local(root, target):
    state = read_json(state_path(root, target), {})
    current = plain(read_toml(target)).get('mcp_servers', {})
    for name, previous in state.get('applied', {}).items():
        if current.get(name) != previous:
            raise ValueError(f'{name}: unpublished local changes; run sync.ps1 push before pull')
    settings = read_json(root / 'settings.json', {})
    if state:
        added = set(current) - set(state.get('applied', {})) - set(settings.get('exclude', []))
        if added:
            raise ValueError('New local servers need exporting first: ' + ', '.join(sorted(added)))


def record(root, target):
    shared = plain(read_toml(root / 'config.toml')).get('mcp_servers', {})
    current = plain(read_toml(target)).get('mcp_servers', {})
    write_json(state_path(root, target), {'shared': shared, 'applied': {k: v for k, v in current.items() if k in shared}})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "apply", "check", "plan", "check-local", "record", "needs-node"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--target", type=Path, default=Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    root, target = args.root.resolve(), args.target.resolve()
    os.environ["PIPX_HOME"] = str(root / ".local/servers/pipx")
    os.environ["PIPX_BIN_DIR"] = str(root / ".local/bin")
    os.environ["PIPX_MAN_DIR"] = str(root / ".local/share/man")
    if args.action != 'export' and not (root / 'config.toml').exists():
        raise ValueError('Shared config.toml does not exist; export it first')
    if args.action == "export":
        export_config(root, target)
    elif args.action == "apply":
        apply_config(root, target, args.install, args.interactive, args.force)
    elif args.action == 'check-local':
        check_local(root, target)
    elif args.action == 'record':
        record(root, target)
    elif args.action == 'needs-node':
        servers = plain(read_toml(root / 'config.toml')).get('mcp_servers', {})
        print(int(any(s.get('command', '').lower() in ('npx', 'npx.cmd', 'node', 'node.exe', 'npm', 'npm.cmd') for s in servers.values() if s.get('enabled', True))))
    else:
        shared = plain(read_toml(root / "config.toml"))
        validate(shared)
        print("Valid shared configuration: " + ", ".join(shared.get("mcp_servers", {})))
        if args.action == "plan":
            for name, spec in shared.get("mcp_servers", {}).items():
                print(f"  {name}: {'enabled' if spec.get('enabled', True) else 'disabled'}; {spec.get('command', spec.get('url'))}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
