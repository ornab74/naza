import ast
import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
MAIN = ROOT / "main.py"


class ModelIntegrityFailClosedTests(unittest.TestCase):
    def test_no_continue_anyway_bypass_text(self):
        source = MAIN.read_text(encoding="utf-8")
        self.assertNotIn("Continue and encrypt anyway?", source)
        self.assertNotIn("File is kept; you can still encrypt and use it.", source)

    def test_llama_loader_verifies_before_constructor(self):
        source = MAIN.read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_llama_model_blocking")
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        verify = next(i for i, c in enumerate(calls) if isinstance(c.func, ast.Name) and c.func.id == "verify_model_integrity")
        llama = next(i for i, c in enumerate(calls) if isinstance(c.func, ast.Name) and c.func.id == "Llama")
        self.assertLess(verify, llama)

    def test_integrity_helper_rejects_mismatch(self):
        source = MAIN.read_text(encoding="utf-8")
        tree = ast.parse(source)
        wanted = {"sha256_file", "verify_model_integrity", "_is_symlink"}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
        ns = {"Path": Path, "hashlib": hashlib, "hmac": hmac, "os": __import__("os"), "EXPECTED_HASH": "0" * 64}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), ns)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "model.gguf"
            p.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                ns["verify_model_integrity"](p, "0" * 64)


if __name__ == "__main__":
    unittest.main()
