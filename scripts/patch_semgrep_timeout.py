"""Apply the narrow OAuth discovery timeout fix for Semgrep 1.178.0.

Run with the Python interpreter belonging to the Semgrep installation.
Only the OAuth metadata connect timeout changes; TLS verification and auth remain.
"""
from pathlib import Path
import shutil

import semgrep


OLD = 'response = requests.get(oauth_url, timeout=(2, 30))'
NEW = 'response = requests.get(oauth_url, timeout=(15, 30))'


def patch_source(text):
    if NEW in text and OLD not in text:
        return text
    if text.count(OLD) != 1:
        raise RuntimeError('Unexpected Semgrep source; timeout patch was not applied.')
    return text.replace(OLD, NEW, 1)


def main():
    if semgrep.__VERSION__ != '1.178.0':
        raise RuntimeError('Review this patch before applying to another Semgrep version.')
    target = Path(semgrep.__file__).parent / 'mcp/utilities/utils.py'
    original = target.read_text(encoding='utf-8')
    patched = patch_source(original)
    if patched == original:
        print('Semgrep OAuth connect timeout is already 15 seconds.')
        return
    compile(patched, str(target), 'exec')
    backup = target.with_name('utils.py.before-mcp-timeout-fix.bak')
    if not backup.exists():
        shutil.copy2(target, backup)
    with target.open('w', encoding='utf-8', newline='\n') as out:
        out.write(patched)
    print('Semgrep OAuth connect timeout: 2 -> 15 seconds. Original source backed up.')


if __name__ == '__main__':
    main()
