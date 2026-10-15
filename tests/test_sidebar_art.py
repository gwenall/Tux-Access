"""Artwork startup choice and source/installed-layout behavior, without Qt."""
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch
import tux_access.ui.sidebar_art as sidebar_art


class SidebarArtTests(unittest.TestCase):
    def test_bundled_pool_contains_every_named_asset_without_duplicate_image_weighting(self):
        found = sidebar_art.find_artwork()
        self.assertEqual(tuple(path.name for path in found), sidebar_art.ART_NAMES)
        digests = [hashlib.sha256(path.read_bytes()).digest() for path in found]
        self.assertEqual(len(digests), len(set(digests)))

    def test_installed_assets_are_found_without_source_tree_or_working_directory_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = root / 'prefix/share/native-access-linux/assets/tux'
            installed.mkdir(parents=True)
            for name in sidebar_art.ART_NAMES:
                (installed / name).write_bytes(b'fixture')
            found = sidebar_art.find_artwork(root / 'absent-source', root / 'prefix')
            self.assertEqual({path.name for path in found}, set(sidebar_art.ART_NAMES))
            self.assertTrue(all(path.parent == installed for path in found))

    def test_next_startup_avoids_previous_art_and_readonly_cache_is_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artwork = tuple(root / name for name in sidebar_art.ART_NAMES)
            cache = root / 'cache/sidebar-art.txt'
            first = sidebar_art.choose_artwork(artwork, cache, chooser=lambda choices: choices[0])
            second = sidebar_art.choose_artwork(artwork, cache, chooser=lambda choices: choices[0])
            self.assertNotEqual(first, second)
            self.assertEqual(cache.read_text().strip(), second.name)
            with patch('tux_access.ui.sidebar_art.tempfile.mkstemp', side_effect=PermissionError('Read-only cache')):
                third = sidebar_art.choose_artwork(artwork, cache, chooser=lambda choices: choices[0])
            self.assertNotEqual(second, third)
            self.assertEqual(cache.read_text().strip(), second.name)

    def test_process_keeps_one_choice_even_when_windows_or_views_are_recreated(self):
        chosen = Path('/bundled/assets/tux/tux-keyboard-player.png')
        with patch.object(sidebar_art, '_startup_art', sidebar_art._UNSET), \
             patch('tux_access.ui.sidebar_art.find_artwork', return_value=(chosen,)), \
             patch('tux_access.ui.sidebar_art.choose_artwork', return_value=chosen) as choose:
            self.assertEqual(sidebar_art.startup_artwork(), chosen)
            self.assertEqual(sidebar_art.startup_artwork(), chosen)
            choose.assert_called_once()

    def test_renamed_cached_art_is_not_immediately_repeated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artwork = tuple(root / name for name in sidebar_art.ART_NAMES)
            cache = root / 'sidebar-art.txt'
            for old, renamed in sidebar_art.LEGACY_ART_NAMES.items():
                with self.subTest(previous=old):
                    cache.write_text(old + '\n', encoding='ascii')
                    seen = []
                    def choose(choices):
                        seen.extend(path.name for path in choices)
                        return choices[0]
                    chosen = sidebar_art.choose_artwork(artwork, cache, chooser=choose)
                    self.assertNotIn(renamed, seen)
                    self.assertNotEqual(chosen.name, renamed)
                    self.assertEqual(cache.read_text().strip(), chosen.name)


if __name__ == '__main__':
    unittest.main()
