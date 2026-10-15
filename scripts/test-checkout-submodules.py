"""Offline regressions for actions/checkout/checkout-submodules.sh.

Builds a superproject with nested submodules (and wiki submodules at several
depths) from local repositories, then checks which ones the script clones.
"""
import os
import pathlib
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).parents[1] / "actions/checkout/checkout-submodules.sh"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_ALLOW_PROTOCOL": "file",
}


def git(cwd, *args):
    subprocess.run(["git", "-c", "protocol.file.allow=always", "-c", "init.defaultBranch=main", *args],
                   cwd=cwd, env=ENV, check=True, capture_output=True)


class CheckoutSubmodulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        ENV["HOME"] = str(self.home)
        self.origin = base / "origin"

        def repo(name, subs=()):
            path = self.origin / name
            path.mkdir(parents=True)
            git(path, "init", "-q")
            (path / "README").write_text(name)
            for sub, dest in subs:
                git(path, "submodule", "add", "-q", (self.origin / sub).as_uri(), dest)
            git(path, "add", "-A")
            git(path, "commit", "-q", "-m", name)

        repo("leaf")
        repo("wiki")
        repo("lib", [("leaf", "vendor/leaf"), ("wiki", "wiki")])
        repo("top", [("lib", "vendor/lib"), ("wiki", "wiki"), ("leaf", "docs/wiki-tools")])
        self.work = base / "work"
        git(base, "clone", "-q", (self.origin / "top").as_uri(), str(self.work))

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, **env):
        result = subprocess.run([str(SCRIPT), str(self.work)], env={**ENV, **env}, text=True,
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def cloned(self, rel):
        return (self.work / rel / "README").is_file()

    def test_bare_name_skips_wikis_at_every_depth(self):
        out = self.run_script(EXCLUDE="wiki\n")
        self.assertTrue(self.cloned("vendor/lib"))
        self.assertTrue(self.cloned("vendor/lib/vendor/leaf"))
        self.assertTrue(self.cloned("docs/wiki-tools"))
        self.assertFalse(self.cloned("wiki"))
        self.assertFalse(self.cloned("vendor/lib/wiki"))
        self.assertIn("checked out 3 submodules, skipped 2", out)

    def test_path_pattern_matches_from_the_root(self):
        self.run_script(EXCLUDE="vendor/*/wiki")
        self.assertTrue(self.cloned("wiki"))
        self.assertFalse(self.cloned("vendor/lib/wiki"))

    def test_excluding_a_parent_skips_everything_beneath_it(self):
        out = self.run_script(EXCLUDE="vendor/lib")
        self.assertFalse(self.cloned("vendor/lib"))
        self.assertTrue(self.cloned("wiki"))
        self.assertNotIn("vendor/lib/", out)

    def test_non_recursive_stops_at_the_first_level(self):
        self.run_script(RECURSIVE="false")
        self.assertTrue(self.cloned("vendor/lib"))
        self.assertFalse(self.cloned("vendor/lib/vendor/leaf"))

    def test_no_exclusions_clones_everything(self):
        out = self.run_script()
        self.assertIn("checked out 5 submodules, skipped 0", out)

    def test_clones_are_shallow(self):
        self.run_script(DEPTH="1")
        shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=self.work / "vendor/lib",
                                 env=ENV, text=True, capture_output=True, check=True).stdout.strip()
        self.assertEqual(shallow, "true")

    def test_token_never_reaches_git_config(self):
        self.run_script(TOKEN="secret-token")
        for config in [self.work / ".git/config", *self.work.glob(".git/modules/**/config")]:
            self.assertNotIn("extraheader", config.read_text())

    def test_a_checkout_owned_by_another_user_still_gets_its_submodules(self):
        # A container job runs as root over a workspace the runner's user owns.
        # git's test hook makes every repository look foreign, as it does there.
        out = self.run_script(TOKEN="secret-token", GIT_TEST_ASSUME_DIFFERENT_OWNER="1")
        self.assertTrue(self.cloned("vendor/lib/vendor/leaf"))
        self.assertIn("checked out 5 submodules", out)
        self.assertNotIn("safe.directory", (self.home / ".gitconfig").read_text()
                         if (self.home / ".gitconfig").exists() else "")

    def test_a_failed_clone_fails_the_script(self):
        (self.origin / "leaf").rename(self.origin / "gone")
        result = subprocess.run([str(SCRIPT), str(self.work)], env=ENV, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
