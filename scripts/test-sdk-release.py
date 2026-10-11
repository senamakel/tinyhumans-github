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


class ModuleAssetWorkflowTests(unittest.TestCase):
    def test_public_asset_name_flows_to_verification_and_uploads(self):
        path = Path(__file__).parents[1] / ".github/workflows/module-release.yml"
        text = path.read_text()
        workflow = yaml.load(text, Loader=yaml.BaseLoader)
        self.assertEqual(workflow["on"]["workflow_call"]["inputs"]["asset-name"]["default"], "")
        self.assertIn('[[ "$MODULE_ASSET" =~ ^[A-Za-z0-9_-]+$ ]]', text)
        for job in ("native", "distro"):
            uploads = [step for step in workflow["jobs"][job]["steps"]
                       if step.get("uses", "").startswith("actions/upload-artifact@")]
            self.assertTrue(uploads)
            for step in uploads:
                self.assertIn("inputs.asset-name || inputs.module-crate", step["with"]["path"])
        native = workflow["jobs"]["native"]["steps"]
        for step in native:
            if step.get("name", "").startswith("Verify"):
                self.assertIn("MODULE_ASSET", step["run"])


if __name__ == "__main__":
    unittest.main()
