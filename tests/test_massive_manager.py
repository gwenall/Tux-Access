import unittest
from dataclasses import replace
from tux_access.installation.wine.massive import PROFILE, EXE_TARGET
from tux_access.installation.wine.application import validate_payload
from tux_access.installation.wine.kontakt import WineError


class MassiveProfileTests(unittest.TestCase):
    def test_all_original_files_and_primary_fingerprints_are_pinned(self):
        rows, hashes = validate_payload(PROFILE)
        self.assertEqual(len(rows), 3384)
        self.assertEqual(sum(row['size'] for row in rows), 531518498)
        self.assertEqual(hashes[EXE_TARGET], 'a85dc23b4424bd50892a9de82a2ff6a21478600654ad316dfa5dde0bbb4c023e')
        self.assertEqual(PROFILE.artifact.zip_sha256, '764f39a99dfd9e7e02216791523cfd096f7889b968d54463d65756e8991cb663')
        self.assertEqual({item.name for item in PROFILE.registry_values}, {'InstallDir', 'InstallVST64Dir', 'ContentDir'})
        self.assertTrue(all(item.view == 64 for item in PROFILE.registry_values))

    def test_original_shared_resource_scope_is_fixed_and_not_global(self):
        rows, hashes = validate_payload(PROFILE)
        self.assertEqual(sum(row['target'].startswith('Program Files (x86)/') for row in rows), 3353)
        changed = [dict(row) for row in rows]
        row = next(row for row in changed if '/Shared Content/' in row['target'])
        row['target'] = row['target'].replace('/Sounds/Massive/', '/Sounds/Other Product/')
        with self.assertRaises(WineError): validate_payload(replace(PROFILE, load_plan=lambda: {'files': changed}))


if __name__ == '__main__': unittest.main()
