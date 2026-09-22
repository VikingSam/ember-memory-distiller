"""Recoverable writes with optimistic concurrency checks and append-only backups."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def safe_path(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:
        raise ValueError('Unsafe workspace path')
    path = root / rel
    if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
        raise ValueError('Symlink paths are not supported')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path leaves workspace')
    return path


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.ember-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextlib.contextmanager
def locked(root):
    # Lock the existing directory inode: dry-runs create no lock or state files.
    fd = os.open(root, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


class Plan:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.before = {}
        self.after = {}

    def read(self, rel):
        if rel not in self.before:
            path = safe_path(self.root, rel)
            self.before[rel] = path.read_bytes() if path.exists() else None
        data = self.after.get(rel, self.before[rel])
        return data.decode('utf-8') if data is not None else ''

    def write(self, rel, text):
        self.read(rel)
        self.after[rel] = text.encode('utf-8')

    def changes(self):
        return {p: b for p, b in self.after.items() if b != self.before[p]}

    def commit(self):
        changes = self.changes()
        if not changes:
            return None
        for rel, original in self.before.items():
            path = safe_path(self.root, rel)
            current = path.read_bytes() if path.exists() else None
            if current != original:
                raise RuntimeError(f'Concurrent edit detected: {rel}')
        ident = uuid.uuid4().hex
        backup = safe_path(self.root, f'.ember-distiller/backups/{ident}')
        backup.mkdir(parents=True, mode=0o700)
        manifest = {'id': ident, 'status': 'prepared', 'files': {}}
        for i, (rel, data) in enumerate(changes.items()):
            old = self.before[rel]
            name = str(i)
            if old is not None:
                atomic(backup / name, old)
            manifest['files'][rel] = {'backup': name if old is not None else None,
                                      'before': digest(old), 'after': digest(data)}
        atomic(backup / 'manifest.json', json.dumps(manifest, indent=2).encode())
        # Backups and manifest are durable before the first target write.
        for rel, data in changes.items():
            path = safe_path(self.root, rel)
            current = path.read_bytes() if path.exists() else None
            if current != self.before[rel]:
                raise RuntimeError(f'Concurrent edit; restore backup {ident}: {rel}')
            atomic(path, data)
        manifest['status'] = 'committed'
        atomic(backup / 'manifest.json', json.dumps(manifest, indent=2).encode())
        return ident


def restore(root, ident):
    if not ident.isalnum():
        raise ValueError('Invalid backup ID')
    root = Path(root).resolve()
    backup = safe_path(root, f'.ember-distiller/backups/{ident}')
    manifest = json.loads((backup / 'manifest.json').read_text())
    todo = []
    for rel, info in manifest['files'].items():
        path = safe_path(root, rel)
        current = path.read_bytes() if path.exists() else None
        if digest(current) == info['before']:
            continue
        if digest(current) != info['after']:
            raise RuntimeError(f'Restore would overwrite later edits: {rel}')
        old = (backup / info['backup']).read_bytes() if info['backup'] else None
        if digest(old) != info['before']:
            raise RuntimeError('Corrupt backup')
        todo.append((rel, current, old))
    recovery = safe_path(root, f'.ember-distiller/restore-archives/{uuid.uuid4().hex}')
    for rel, current, old in todo:
        path = safe_path(root, rel)
        atomic(recovery / rel, current)
        if old is None:
            # Preserve newly-created files by moving them out of the live tree.
            destination = recovery / ('new-files/' + rel)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, destination)
        else:
            atomic(path, old)

    manifest['status'] = 'restored'
    atomic(backup / 'manifest.json', json.dumps(manifest, indent=2).encode())
