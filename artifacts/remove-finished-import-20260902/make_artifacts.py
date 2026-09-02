from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import difflib, hashlib
root = Path.cwd()
artifact = root / 'artifacts' / 'remove-finished-import-20260902'
files = [
    Path('web/src/api.js'),
    Path('web/src/components/Dashboard.vue'),
    Path('src/autotoken/interfaces/api.py'),
    Path('src/autotoken/api_routes/finished_account_import.py'),
    Path('src/autotoken/services/finished_account_import.py'),
]
patch_parts = []
for rel in files:
    before_path = artifact / 'original' / rel
    after_path = root / rel
    before = before_path.read_text(encoding='utf-8').splitlines(keepends=True) if before_path.exists() else []
    after = after_path.read_text(encoding='utf-8').splitlines(keepends=True) if after_path.exists() else []
    fromfile = f'a/{rel.as_posix()}'
    tofile = f'b/{rel.as_posix()}' if after_path.exists() else '/dev/null'
    patch_parts.extend(difflib.unified_diff(before, after, fromfile=fromfile, tofile=tofile))
(artifact / 'DIFF_FILE.diff').write_text(''.join(patch_parts), encoding='utf-8')
with ZipFile(artifact / 'MODIFIED_FILE', 'w', ZIP_DEFLATED) as z:
    manifest = []
    for rel in files:
        path = root / rel
        if path.exists():
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest().upper()
            manifest.append(f'MODIFIED {digest} {rel.as_posix()}')
            z.write(path, f'modified/{rel.as_posix()}')
        else:
            manifest.append(f'DELETED {rel.as_posix()}')
    z.writestr('MANIFEST.txt', '\n'.join(manifest) + '\n')
print('ARTIFACTS_CREATED')
print((artifact / 'MODIFIED_FILE').resolve())
print((artifact / 'DIFF_FILE.diff').resolve())
print((artifact / 'ROLLBACK.sh').resolve())
