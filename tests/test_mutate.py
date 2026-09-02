"""The mutation runner's own restore step.

`mutate.py` rewrites source in place and restores it, and the whole tool is
worthless if the interpreter goes on running the mutant afterwards. Python
validates a `.pyc` on the source's mtime-in-SECONDS plus its size, so a
mutation the same length as the original, written and restored inside one
second, leaves cached bytecode that looks valid and is not. That happened on
2026-09-02: the tree was byte-identical to HEAD, `git status` was clean, and a
guard-clause test failed because the loaded module was still mutated. The
dangerous direction is the opposite one -- a restored file running mutant
bytecode reports `killed` for a check that never ran.
"""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from mutate import _write


def test_write_drops_the_cached_bytecode(tmp_path):
    src = tmp_path / "victim.py"
    src.write_text("X = 1\n")
    cached = Path(importlib.util.cache_from_source(str(src)))
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"stale bytecode from a mutant")

    _write(src, "X = 2\n")

    assert src.read_text() == "X = 2\n"
    assert not cached.exists()


def test_write_is_fine_when_there_is_no_cached_bytecode(tmp_path):
    src = tmp_path / "victim.py"
    _write(src, "X = 1\n")
    assert src.read_text() == "X = 1\n"
