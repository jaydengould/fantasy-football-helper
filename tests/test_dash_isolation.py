"""dash must never become a draft-night dependency.

The terminal board is the fallback when the web board misbehaves. If importing
`ffhelper.cli` required `dash`, a broken or uninstalled dash would take the
fallback down with it -- which is precisely the moment it is needed.
"""
import importlib
import sys

import pytest


class _BlockDash:
    """A meta_path finder that makes `import dash` raise, as if it were absent."""

    def find_spec(self, name, path=None, target=None):
        if name == "dash" or name.startswith("dash."):
            raise ImportError(f"{name} is blocked for this test")
        return None


@pytest.fixture
def dash_absent(monkeypatch):
    for mod in [m for m in sys.modules if m == "dash" or m.startswith(("dash.", "ffhelper"))]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_BlockDash(), *sys.meta_path])
    yield


def test_cli_imports_with_dash_absent(dash_absent):
    cli = importlib.import_module("ffhelper.cli")
    assert hasattr(cli, "main")


def test_cli_does_not_import_app(dash_absent):
    importlib.import_module("ffhelper.cli")
    assert "ffhelper.app" not in sys.modules, (
        "cli.py imported app.py -- the dependency must run one way only"
    )


def test_the_block_fixture_actually_blocks(dash_absent):
    # Guards the two tests above from passing vacuously: if this import
    # succeeds, the fixture is broken and the other assertions prove nothing.
    with pytest.raises(ImportError):
        importlib.import_module("dash")
