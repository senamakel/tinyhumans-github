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

    def test_registry_jobs_install_native_dependencies_before_publish(self):
        path = Path(__file__).parents[1] / ".github/workflows/module-release.yml"
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        for job in ("crates_io_check", "crates_io"):
            steps = workflow["jobs"][job]["steps"]
            installs = [i for i,s in enumerate(steps) if "sudo apt-get install" in s.get("run", "")]
            publishes = [i for i,s in enumerate(steps) if "cargo publish" in s.get("run", "")]
            self.assertEqual(len(installs), 1)
            self.assertEqual(len(publishes), 1)
            self.assertLess(installs[0], publishes[0])

    def test_build_metadata_hyphens_do_not_mark_prereleases(self):
        import os
        import re
        import subprocess
        for file,var,flags in [("sdk-release.yml","VERSION","release_type"),("module-release.yml","MODULE_VERSION","release_type")]:
            path = Path(__file__).parents[1] / ".github/workflows" / file
            line = re.search(r"^ +if .*--prerelease.*fi$", path.read_text(), re.M).group().strip()
            for version,expected in [("1.2.3",0),("1.2.3+linux-x86",0),("1.2.3-beta+linux-x86",1)]:
                script = flags+"=(); "+line+"; printf '%s' "+chr(34)+"$"+"{#"+flags+"[@]}"+chr(34)
                result = subprocess.run(["bash","-c",script], env=dict(os.environ,**{var:version}),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout,str(expected))


if __name__ == "__main__":
    unittest.main()
