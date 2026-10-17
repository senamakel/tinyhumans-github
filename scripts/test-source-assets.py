"""Prove additional source packages cannot change verified module assets."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("source_assets", Path(__file__).with_name("merge-source-assets.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class SourceAssetsTests(unittest.TestCase):
    def test_valid_flat_artifact_is_copied(self):
        """Flat source packages are appended to the release."""
        with tempfile.TemporaryDirectory() as root:
            source, dest = Path(root)/"source", Path(root)/"dest"
            source.mkdir(); dest.mkdir()
            (source/"sdk.crate").write_bytes(b"source")
            module.merge(source, dest)
            self.assertEqual((dest/"sdk.crate").read_bytes(), b"source")

    def test_collision_preserves_every_original_asset(self):
        """A source checksum or archive cannot replace a verified module asset."""
        with tempfile.TemporaryDirectory() as root:
            source, dest = Path(root)/"source", Path(root)/"dest"
            source.mkdir(); dest.mkdir()
            (source/"sdk.crate").write_bytes(b"source")
            (source/"checksum.toml").write_bytes(b"replacement")
            (dest/"checksum.toml").write_bytes(b"verified")
            with self.assertRaises(ValueError): module.merge(source, dest)
            self.assertEqual((dest/"checksum.toml").read_bytes(), b"verified")
            self.assertFalse((dest/"sdk.crate").exists())

    def test_nested_artifact_is_rejected(self):
        """Directories are rejected before any asset is copied."""
        with tempfile.TemporaryDirectory() as root:
            source, dest = Path(root)/"source", Path(root)/"dest"
            source.mkdir(); dest.mkdir(); (source/"nested").mkdir()
            with self.assertRaises(ValueError): module.merge(source, dest)

    def test_workflow_embeds_the_validated_merger(self):
        """Caller checkouts do not contain the shared repository's scripts."""
        script = Path(__file__).with_name("merge-source-assets.py").read_text()
        workflow = (Path(__file__).parents[1]/".github/workflows/module-release.yml").read_text()
        self.assertIn("".join("          "+line+"\n" for line in script.splitlines()), workflow)

if __name__ == "__main__": unittest.main()
