"""Suite-wide safety: no test may reach the real `season.db`.

Found by running `lineup` for real and reading the rows back -- not by any
test. A fully green suite had written two rows into the PRODUCTION database
under real league names, because several `_lineup` tests stub `/state/nfl` to
the same week they request, which is exactly the condition the snapshot writes
on. One of those rows was `yahoo-main` week 1: it shares a primary key with the
real week-1 record, and `INSERT OR REPLACE` would have overwritten a genuine
decision with a fixture.

That is the worst failure this table can have. Its entire value is being
trustworthy months later, and the corruption is invisible -- the row is still
there, still well-formed, just fabricated.

The redirect is **autouse and suite-wide** rather than remembered per test,
because the per-test version is a rule the next `_lineup` test forgets, and it
fails silently in the only direction that matters. A test may still point
`store.DB_PATH` somewhere of its own; this only guarantees it is never the
real file.
"""
import pytest

from ffhelper import data, store


@pytest.fixture(autouse=True)
def _never_the_real_season_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test-season.db")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test may reach the network. Autouse, for the same reason as above.

    The suite's value is being sub-second and offline, and a test that quietly
    starts fetching keeps passing -- it just gets slower, which nobody reads.
    Found exactly that way: wiring nflverse's injury report into `lineup` sent
    the whole suite to the network and the only symptom was 0.68s -> 4.78s.

    Loaders that take a `fetcher` argument are unaffected; this closes the
    default path, which is the one a new call site picks up by accident.
    """
    def refuse(url):
        raise AssertionError(f"test reached the network: {url}")
    monkeypatch.setattr(data, "_requests_get", refuse)
