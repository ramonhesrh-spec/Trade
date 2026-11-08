import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import bevriezing_check as bc  # noqa: E402


def _git(repo, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


class BevriezingCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _git(self.repo, "init", "-q")
        (self.repo / "app").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self, name, text, date):
        (self.repo / name).write_text(text)
        _git(self.repo, "add", name)
        _git(self.repo, "commit", "-q", "-m", f"wijzig {name}", date=date)

    def test_only_watched_files_after_date(self):
        self._commit("app/model.py", "a", "2026-11-01T10:00:00+00:00")  # voor de datum
        self._commit("app/model.py", "b", "2026-11-04T10:00:00+00:00")  # telt
        self._commit("app/htf_zones.py", "c", "2026-11-05T10:00:00+00:00")  # telt
        self._commit("app/repo.py", "d", "2026-11-06T10:00:00+00:00")  # niet bewaakt
        got = bc.commits_since(self.repo, "2026-11-03")
        self.assertEqual([c["files"] for c in got], [["app/htf_zones.py"], ["app/model.py"]])

    def test_bare_date_includes_earlier_time_that_day(self):
        self._commit("app/model.py", "a", "2026-11-03T00:30:00+00:00")
        self.assertEqual(len(bc.commits_since(self.repo, "2026-11-03")), 1)

    def test_empty_and_exit_code(self):
        self._commit("app/repo.py", "x", "2026-11-04T10:00:00+00:00")
        self.assertEqual(bc.commits_since(self.repo, "2026-11-03"), [])
        self.assertIn("Geen commits.", bc.render([], "2026-11-03"))
        self.assertEqual(bc.main(["--repo", str(self.repo)]), 0)
        self._commit("app/model_live.py", "y", "2026-11-04T11:00:00+00:00")
        self.assertEqual(bc.main(["--repo", str(self.repo)]), 1)

    def test_read_only(self):
        self._commit("app/model.py", "a", "2026-11-04T10:00:00+00:00")
        before = _status(self.repo)
        bc.main(["--repo", str(self.repo)])
        self.assertEqual(_status(self.repo), before)


def _status(repo):
    return subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout


if __name__ == "__main__":
    unittest.main()
