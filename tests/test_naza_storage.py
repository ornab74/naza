import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import naza_storage as store


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.targets = [self.root / 'data', self.root / 'key', self.root / 'mac']
        for p in self.targets[:2]:
            store.atomic_write(p, b'old-' + p.name.encode())

    def tearDown(self):
        self.tmp.cleanup()

    def assert_old(self):
        for p in self.targets[:2]:
            self.assertEqual(p.read_bytes(), b'old-' + p.name.encode())
        self.assertFalse(self.targets[2].exists())

    def test_success_and_permissions(self):
        store.replace_batch(self.root, self.targets, lambda: iter([b'new-data', b'new-key', b'new-mac']))
        for p in self.targets:
            self.assertEqual(p.read_bytes(), b'new-' + p.name.encode())
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertFalse(store.recover(self.root, self.targets))

    def test_preparation_error_preserves_everything(self):
        def prepare():
            yield b'new-data'
            raise ValueError('failed verification')
        with self.assertRaises(ValueError):
            store.replace_batch(self.root, self.targets, prepare)
        self.assert_old()
        self.assertFalse((self.root / '.naza-rotation').exists())

    def test_write_failure_rolls_back(self):
        original = store.atomic_write
        def failing(path, data):
            if path == self.targets[1] and data == b'new-key':
                raise OSError('simulated disk error')
            original(path, data)
        with patch.object(store, 'atomic_write', failing), self.assertRaises(OSError):
            store.replace_batch(self.root, self.targets, lambda: iter([b'new-data', b'new-key', b'new-mac']))
        self.assert_old()

    def test_error_after_commit_marker_keeps_new_set(self):
        original = store.atomic_write
        def failing(path, data):
            original(path, data)
            if path.name == 'manifest.json' and json.loads(data)['committed']:
                raise OSError('failure after commit replacement')
        with patch.object(store, 'atomic_write', failing):
            store.replace_batch(self.root, self.targets, lambda: iter([b'new-data', b'new-key', b'new-mac']))
        for p in self.targets:
            self.assertEqual(p.read_bytes(), b'new-' + p.name.encode())

    def crash(self, committed=False):
        code = '''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import naza_storage as s
root = Path(sys.argv[2])
targets = [root / x for x in ('data','key','mac')]
write = s.atomic_write
def crash_write(path, data):
    write(path, data)
    if sys.argv[3] == 'yes':
        stop = path.name == 'manifest.json' and json.loads(data)['committed']
    else:
        stop = path == targets[0]
    if stop:
        os._exit(73)
s.atomic_write = crash_write
s.replace_batch(root, targets, lambda: iter([b'new-data', b'new-key', b'new-mac']))
'''
        result = subprocess.run([sys.executable, '-c', code, str(Path(store.__file__).parent), str(self.root), 'yes' if committed else 'no'])
        self.assertEqual(result.returncode, 73)

    def test_process_crash_recovery_and_idempotence(self):
        self.crash()
        self.assertEqual(self.targets[0].read_bytes(), b'new-data')
        self.assertTrue(store.recover(self.root, self.targets))
        self.assert_old()
        self.assertFalse(store.recover(self.root, self.targets))

    def test_committed_crash_preserves_new_set(self):
        self.crash(committed=True)
        self.assertFalse(store.recover(self.root, self.targets))
        for p in self.targets:
            self.assertEqual(p.read_bytes(), b'new-' + p.name.encode())

    def test_journal_cannot_redirect_recovery(self):
        self.crash()
        manifest = self.root / '.naza-rotation' / 'manifest.json'
        rec = json.loads(manifest.read_bytes())
        rec['targets'][0] = '/tmp/unrelated-file'
        manifest.write_text(json.dumps(rec))
        with self.assertRaises(ValueError):
            store.recover(self.root, self.targets)
        self.assertEqual(self.targets[0].read_bytes(), b'new-data')

    def test_symlink_rejected_and_old_file_untouched(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.targets[0])
        with self.assertRaises(ValueError):
            store.atomic_write(alias, b'bad')
        self.assert_old()


if __name__ == '__main__':
    unittest.main()
