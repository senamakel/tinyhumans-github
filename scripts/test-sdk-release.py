"""Pin the privilege boundary and retry behavior of the SDK release workflow."""
from pathlib import Path
import unittest

import yaml


class SdkReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / ".github/workflows/sdk-release.yml"
        self.workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)

    def test_cargo_runs_without_release_write_permission(self):
        jobs = self.workflow["jobs"]
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertNotIn("permissions", jobs["package"])
        self.assertEqual(jobs["publish"]["permissions"], {"contents": "write"})
        package_steps = "\n".join(str(step) for step in jobs["package"]["steps"])
        publish_steps = "\n".join(str(step) for step in jobs["publish"]["steps"])
        self.assertIn("cargo test", package_steps)
        self.assertNotIn("GH_TOKEN", package_steps)
        self.assertNotIn("cargo ", publish_steps)
        self.assertIn("actions/upload-artifact", package_steps)
        self.assertIn("actions/download-artifact", publish_steps)

    def test_existing_release_assets_are_verified_before_retry(self):
        publish_steps = str(self.workflow["jobs"]["publish"]["steps"])
        self.assertIn("gh release view", publish_steps)
        self.assertIn("gh release download", publish_steps)
        self.assertIn("different asset set", publish_steps)
        self.assertIn("different contents", publish_steps)
        self.assertIn("gh release edit", publish_steps)
        self.assertIn("gh release create", publish_steps)


if __name__ == "__main__":
    unittest.main()
