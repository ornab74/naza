"""Durable private writes and recoverable encrypted-file replacement (POSIX).

Call recovery before opening the key or data. The caller supplies the fixed
allowed target list; recovery never follows paths supplied by a journal.
"""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import stat


def sync_dir(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def regular(path):
    if path.is_symlink() or (path.exists() and not stat.S_ISREG(path.stat().st_mode)):
        raise ValueError(f'Refusing non-regular file: {path}')


def atomic_write(path, data):
    path = Path(path)
    regular(path)
    tmp = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        sync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


@contextlib.contextmanager
def _locked(root):
    root = Path(root)
    fd = os.open(str(root / '.naza-rotation.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield root / '.naza-rotation'
    finally:
        os.close(fd)


def _cleanup(journal):
    shutil.rmtree(journal)
    sync_dir(journal.parent)


def _recover(journal, targets):
    if journal.is_symlink():
        raise ValueError('Refusing symlink rotation journal')
    if not journal.exists():
        return False
    manifest = journal / 'manifest.json'
    regular(manifest)
    if not manifest.exists():
        # Preparation did not finish; no live files were replaced.
        _cleanup(journal)
        return False
    record = json.loads(manifest.read_bytes())
    expected = [str(Path(p).absolute()) for p in targets]
    if (record.get('version') != 1 or record.get('targets') != expected
            or type(record.get('committed')) is not bool
            or not isinstance(record.get('existed'), list)
            or len(record['existed']) != len(targets)
            or any(type(v) is not bool for v in record['existed'])):
        raise ValueError('Invalid rotation journal; recovery stopped')
    if not record['committed']:
        # Check all backups before restoring any target.
        for i, existed in enumerate(record['existed']):
            regular(Path(targets[i]))
            if existed:
                backup = journal / f'{i}.old'
                regular(backup)
                if not backup.is_file():
                    raise ValueError('Incomplete rotation backup')
        for i, existed in enumerate(record['existed']):
            path = Path(targets[i])
            if existed:
                atomic_write(path, (journal / f'{i}.old').read_bytes())
            elif path.exists():
                path.unlink()
                sync_dir(path.parent)
    rolled_back = not record['committed']
    if rolled_back:
        record['committed'] = True
        atomic_write(manifest, json.dumps(record).encode())
    _cleanup(journal)
    return rolled_back


def recover(root, targets):
    with _locked(root) as journal:
        return _recover(journal, targets)


def replace_batch(root, targets, prepare):
    """Stage prepare()'s bytes in target order, then replace as a recoverable batch.

    prepare must authenticate/verify every new encrypted artifact before yielding.
    Backups and staged files contain encrypted data only. An unfinished commit is
    rolled back on error or by recover() after process interruption.
    """
    targets = [Path(p) for p in targets]
    if len(set(p.absolute() for p in targets)) != len(targets):
        raise ValueError('Duplicate rotation targets')
    with _locked(root) as journal:
        _recover(journal, targets)
        journal.mkdir(mode=0o700)
        sync_dir(journal.parent)
        try:
            existed = []
            for i, path in enumerate(targets):
                regular(path)
                existed.append(path.exists())
                if path.exists():
                    atomic_write(journal / f'{i}.old', path.read_bytes())
            count = 0
            for i, blob in enumerate(prepare()):
                if i >= len(targets):
                    raise ValueError('Too many staged files')
                if blob is not None:
                    atomic_write(journal / f'{i}.new', blob)
                count += 1
            if count != len(targets):
                raise ValueError('Missing staged files')
            record = dict(version=1, targets=[str(p.absolute()) for p in targets], existed=existed, committed=False)
            atomic_write(journal / 'manifest.json', json.dumps(record).encode())
            for i, path in enumerate(targets):
                staged = journal / f'{i}.new'
                if staged.exists():
                    atomic_write(path, staged.read_bytes())
                elif path.exists():
                    path.unlink()
                    sync_dir(path.parent)
            record['committed'] = True
            atomic_write(journal / 'manifest.json', json.dumps(record).encode())
        except BaseException:
            # A write may raise after replacement (for example directory fsync).
            # If the commit marker is already visible, keep the complete new set
            # and report success so the caller switches to its new in-memory key.
            manifest = journal / 'manifest.json'
            committed = manifest.exists() and json.loads(manifest.read_bytes()).get('committed') is True
            _recover(journal, targets)
            if not committed:
                raise
        # Cleanup is recoverable too; a committed marker preserves the new set.
        try:
            _cleanup(journal)
        except OSError:
            pass
