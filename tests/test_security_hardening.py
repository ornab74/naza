import ast
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


def load_security_helpers(filename="main.py"):
    source = Path(__file__).parents[1].joinpath(filename).read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"write_private_file", "private_temp_path", "download_model_httpx"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=functions, type_ignores=[])
    namespace = {
        "Path": Path,
        "Optional": __import__("typing").Optional,
        "hashlib": hashlib,
        "hmac": __import__("hmac"),
        "os": os,
        "sys": __import__("sys"),
        "tempfile": tempfile,
        "color": lambda text, **_kwargs: text,
    }
    exec(compile(module, "main.py", "exec"), namespace)
    return namespace


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self, chunk_size=8192):
        yield self.payload[:chunk_size]
        yield self.payload[chunk_size:]


class SecurityHardeningTests(unittest.TestCase):
    def test_private_write_replaces_symlink_and_uses_owner_only_mode(self):
        for filename in ("main.py", "main_foodwater.py"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                helpers = load_security_helpers(filename)
                root = Path(directory)
                victim = root / "victim"
                victim.write_bytes(b"unchanged")
                target = root / "secret"
                target.symlink_to(victim)

                helpers["write_private_file"](target, b"secret")

                self.assertEqual(target.read_bytes(), b"secret")
                self.assertFalse(target.is_symlink())
                self.assertEqual(victim.read_bytes(), b"unchanged")
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_hash_mismatch_preserves_existing_model_and_removes_partial(self):
        for filename in ("main.py", "main_foodwater.py"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                helpers = load_security_helpers(filename)
                destination = Path(directory) / "model.gguf"
                destination.write_bytes(b"trusted-old-model")
                helpers["httpx"] = SimpleNamespace(stream=lambda *_args, **_kwargs: FakeResponse(b"tampered"))

                with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                    helpers["download_model_httpx"](
                        "https://example.invalid/model", destination, show_progress=False, expected_sha="0" * 64
                    )

                self.assertEqual(destination.read_bytes(), b"trusted-old-model")
                self.assertEqual(set(destination.parent.iterdir()), {destination})

    def test_matching_hash_atomically_installs_download(self):
        payload = b"verified-model"
        for filename in ("main.py", "main_foodwater.py"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                helpers = load_security_helpers(filename)
                destination = Path(directory) / "model.gguf"
                helpers["httpx"] = SimpleNamespace(stream=lambda *_args, **_kwargs: FakeResponse(payload))

                digest = helpers["download_model_httpx"](
                    "https://example.invalid/model",
                    destination,
                    show_progress=False,
                    expected_sha=hashlib.sha256(payload).hexdigest(),
                )

                self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
                self.assertEqual(destination.read_bytes(), payload)
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
