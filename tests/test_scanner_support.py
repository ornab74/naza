import ast
import hashlib
import hmac
from pathlib import Path
import re
import unittest
from typing import Callable, Dict, List, Optional, Tuple


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def support_scope():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    names = {"seal_scan", "_simple_tokenize", "punkd_analyze", "punkd_apply", "chunked_generate"}
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    scope = dict(re=re, hashlib=hashlib, hmac=hmac, List=List, Dict=Dict,
                 Tuple=Tuple, Optional=Optional, Callable=Callable, Llama=object,
                 _mac_key=lambda key: key)
    exec(compile(ast.Module(body=body, type_ignores=[]), "main.py", "exec"), scope)
    return scope


class FakeLlama:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.budgets = []

    def __call__(self, _prompt, max_tokens, temperature):
        self.budgets.append(max_tokens)
        return {"choices": [{"text": next(self.replies)}]}


class ScannerSupportTests(unittest.TestCase):
    def test_numeric_circuit_lock_seals_without_changing_label(self):
        receipt = support_scope()["seal_scan"](
            "High", "unchanged prompt",
            {"lock": 0.625, "wobble": {"word": "surge", "leader": "temp"}},
            b"k" * 32,
        )
        self.assertIn("High|0.625|surge:temp|", receipt)

    def test_non_divisible_chunk_budget_is_capped(self):
        llm = FakeLlama(["one two three four five six seven eight", "more words continue here"])
        support_scope()["chunked_generate"](
            llm, "prompt", max_total_tokens=10, chunk_tokens=8, base_temperature=0.2,
        )
        self.assertEqual(llm.budgets, [8, 2])

    def test_scanner_operating_contract_stays_frozen(self):
        source = MAIN.read_text(encoding="utf-8")
        self.assertIn("Analyze the environmental and triple check cor accurate intelligent replu", source)
        self.assertIn("candidate = text.split()", source)
        self.assertIn("max_total_tokens=256, chunk_tokens=64, base_temperature=0.18", source)
        self.assertGreaterEqual(source.count("persist_scan_receipt(label, prompt"), 2)


if __name__ == "__main__":
    unittest.main()
