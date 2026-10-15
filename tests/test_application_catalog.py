from dataclasses import replace
import unittest

from application_catalog import APPLICATIONS, expand_catalog, is_application
from download_catalog import Artifact


class ApplicationCatalogTests(unittest.TestCase):
    def test_bundle_children_require_authorized_installer_and_skip_libraries(self):
        upid = next(iter(APPLICATIONS))
        installer = Artifact(upid, 'Absynth 5.3.4', '5.3.4', 'pc', 'any', 5, 'Absynth.zip', 'installer', '/private-reference')
        source = {'products': [{'upid': 'bundle', 'title': 'KOMPLETE 13'}]}
        self.assertEqual(expand_catalog(source, [])['products'], source['products'])
        rows = expand_catalog(source, [installer, replace(installer, upid='library')])['products']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['title'], 'Absynth 5')
        self.assertTrue(is_application(rows[1]))
        self.assertNotIn('private-reference', repr(rows))
        self.assertNotIn('installed', rows[1])
        self.assertNotIn('isApplication', source['products'][0])

    def test_application_alias_merges_by_public_identity_without_duplicate_rows(self):
        upid = 'fccc863c-324f-4d79-af7e-b38c1f7488fe'
        installer = Artifact(upid, 'Maschine 2.18.4', '2.18.4', 'pc', 'any', 5, 'Maschine.zip', 'installer', '/reference')
        source = {'products': [{'upid': upid, 'title': 'Maschine 2 Essentials Application for M32'}]}
        rows = expand_catalog(source, [installer, installer])['products']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], 'Maschine 2')
        self.assertEqual(rows[0]['entitlementTitle'], source['products'][0]['title'])
        self.assertEqual(rows[0]['type'], 1)


if __name__ == '__main__':
    unittest.main()
