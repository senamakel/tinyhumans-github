"""Prove additional source packages cannot change verified module assets."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("source_assets", Path(__file__).with_name("merge-source-assets.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
reviewed_spec = importlib.util.spec_from_file_location(
    "reviewed_source_assets",
    Path(__file__).with_name("merge-reviewed-source-assets.py"),
)
reviewed_module = None
if reviewed_spec is not None and reviewed_spec.loader is not None and Path(reviewed_spec.origin).is_file():
    reviewed_module = importlib.util.module_from_spec(reviewed_spec)
    reviewed_spec.loader.exec_module(reviewed_module)

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

    def test_reviewed_tinydocs_bundle_merges_the_exact_package_and_pinned_bus_archive(self):
        self.assertIsNotNone(reviewed_module, "reviewed source asset merger is missing")
        with tempfile.TemporaryDirectory() as root:
            source, dest = Path(root)/"source", Path(root)/"release"
            source.mkdir(); dest.mkdir()
            (source/"tinydocs-bus-0.2.4.crate").write_bytes(b"crate")
            (source/"tinybus-source-0123456789ab.tar.gz").write_bytes(b"bus source")
            reviewed_module.merge("tinydocs", "0.2.4", source, dest)
            self.assertEqual(
                sorted(path.name for path in dest.iterdir()),
                ["tinydocs-bus-0.2.4.crate", "tinybus-source-0123456789ab.tar.gz"],
            )
            self.assertEqual((dest/"tinydocs-bus-0.2.4.crate").read_bytes(), b"crate")
            self.assertEqual((dest/"tinybus-source-0123456789ab.tar.gz").read_bytes(), b"bus source")

    def test_reviewed_source_merger_rejects_unknown_profiles_and_unexpected_files(self):
        self.assertIsNotNone(reviewed_module, "reviewed source asset merger is missing")
        with tempfile.TemporaryDirectory() as root:
            source, dest = Path(root)/"source", Path(root)/"release"
            source.mkdir(); dest.mkdir()
            (source/"tinydocs-bus-0.2.4.crate").write_bytes(b"crate")
            (source/"tinybus-source-0123456789ab.tar.gz").write_bytes(b"bus source")
            with self.assertRaisesRegex(ValueError, "unsupported reviewed source bundle"):
                reviewed_module.merge("caller-selected", "0.2.4", source, dest)
            (source/"extra.zip").write_bytes(b"unlisted")
            with self.assertRaisesRegex(ValueError, "exact source asset set"):
                reviewed_module.merge("tinydocs", "0.2.4", source, dest)
            self.assertEqual(list(dest.iterdir()), [])

    def test_reviewed_source_merger_rejects_symlinks_collisions_and_bad_versions_before_copy(self):
        self.assertIsNotNone(reviewed_module, "reviewed source asset merger is missing")
        with tempfile.TemporaryDirectory() as root:
            source, dest = Path(root)/"source", Path(root)/"release"
            source.mkdir(); dest.mkdir()
            (source/"tinydocs-bus-0.2.4.crate").write_bytes(b"crate")
            (source/"tinybus-source-0123456789ab.tar.gz").symlink_to(source/"tinydocs-bus-0.2.4.crate")
            with self.assertRaisesRegex(ValueError, "regular files"):
                reviewed_module.merge("tinydocs", "0.2.4", source, dest)
            (source/"tinybus-source-0123456789ab.tar.gz").unlink()
            (source/"tinybus-source-0123456789ab.tar.gz").write_bytes(b"bus source")
            with self.assertRaisesRegex(ValueError, "version"):
                reviewed_module.merge("tinydocs", "../0.2.4", source, dest)
            (dest/"tinydocs-bus-0.2.4.crate").write_bytes(b"verified")
            with self.assertRaisesRegex(ValueError, "collides"):
                reviewed_module.merge("tinydocs", "0.2.4", source, dest)
            self.assertEqual((dest/"tinydocs-bus-0.2.4.crate").read_bytes(), b"verified")
            self.assertEqual(len(list(dest.iterdir())), 1)

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
