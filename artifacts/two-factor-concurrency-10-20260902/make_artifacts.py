from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import difflib, hashlib
root = Path.cwd()
artifact = root / 'artifacts' / 'two-factor-concurrency-10-20260902'
files = [Path('src/autotoken/services/account_two_factor.py'), Path('tests/unit/test_account_two_factor_service.py')]
patch_parts = []
with ZipFile(artifact / 'MODIFIED_FILE', 'w', ZIP_DEFLATED) as z:
    manifest = []
    for rel in files:
        before_path = artifact / 'original' / rel
        after_path = root / rel
        before = before_path.read_text(encoding='utf-8').splitlines(keepends=True)
        after = after_path.read_text(encoding='utf-8').splitlines(keepends=True)
        patch_parts.extend(difflib.unified_diff(before, after, fromfile=f'a/{rel.as_posix()}', tofile=f'b/{rel.as_posix()}'))
        data = after_path.read_bytes()
        manifest.append(f'MODIFIED {hashlib.sha256(data).hexdigest().upper()} {rel.as_posix()}')
        z.write(after_path, f'modified/{rel.as_posix()}')
    z.writestr('MANIFEST.txt', '\n'.join(manifest) + '\n')
(artifact / 'DIFF_FILE.diff').write_text(''.join(patch_parts), encoding='utf-8')
print('ARTIFACTS_CREATED')
print((artifact / 'MODIFIED_FILE').resolve())
print((artifact / 'DIFF_FILE.diff').resolve())
print((artifact / 'ROLLBACK.sh').resolve())
