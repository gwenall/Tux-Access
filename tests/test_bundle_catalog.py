import unittest

from tux_access.catalog.applications import expand_catalog
from tux_access.catalog.bundles import bundle_members, is_bundle, member_identities
from tux_access.downloads.catalog import Artifact
from tux_access.protocol.ntk import _product, message_field, varint

K13 = {'upid': 'a3f6622b-00c5-49af-bb0d-2a5ec004e91c', 'title': 'KOMPLETE 13'}
PHASIS = '90f226a1-3cad-4bd7-a047-fc0609afcbab'


class BundleCatalogTests(unittest.TestCase):
    def artifact(self, upid=PHASIS):
        return Artifact(upid, 'Phasis 1.2.1', '1.2.1', 'linux-x86_64', 'any', 5,
                        'Phasis.deb', 'installer', '/private-download-reference')

    def test_reference_ids_distinguish_collection_from_kontrol_application(self):
        self.assertTrue(is_bundle(K13))
        self.assertFalse(is_bundle({'upid': 'cf11c1f6-1d76-432f-aece-52ef5305a14d', 'title': 'Komplete Kontrol'}))
        self.assertFalse(is_bundle({'title': 'KOMPLETE 13'}))
        self.assertTrue(is_bundle({'type': 5, 'title': 'Unknown collection'}))
        self.assertEqual(member_identities({'type': 5}), [])

    def test_exact_reference_members_do_not_substitute_other_owned_products(self):
        rows = bundle_members(K13, [{'upid': 'unrelated', 'title': 'Unrelated owned application'}])
        self.assertEqual(len(rows), 99)
        self.assertNotIn('unrelated', {row['upid'] for row in rows})
        self.assertIn(PHASIS, {row['upid'] for row in rows})
        self.assertFalse(any(row['bundleInstallerAvailable'] for row in rows))

    def test_authorization_and_local_installation_remain_separate_from_membership(self):
        local = {'upid': PHASIS, 'title': 'Phasis', 'source': 'native-install', 'status': 'Installed', 'nativePackage': 'ni-phasis'}
        rows = bundle_members(K13, [local], [self.artifact()])
        phasis = next(row for row in rows if row['upid'] == PHASIS)
        self.assertTrue(phasis['bundleInstallerAvailable'])
        self.assertEqual(phasis['nativePackage'], 'ni-phasis')
        self.assertNotIn('bundleParentUpid', local)
        self.assertNotIn('private-download-reference', repr(rows))
        self.assertFalse(next(row for row in rows if row['title'] == 'Massive')['bundleInstallerAvailable'])

    def test_live_members_override_reference_and_whitelist_public_fields(self):
        bundle = {**K13, 'bundle_members': {'members': [
            {'upid': 'child', 'display_name': 'Child', 'license': 'private'},
            {'upid': 'child', 'title': 'Duplicate'}, {'upid': K13['upid'], 'title': 'Self'},
            {'upid': 'invalid', 'title': 'Bad\nname'}, None]}}
        self.assertEqual(member_identities(bundle), [{'upid': 'child', 'title': 'Child'}])
        self.assertEqual(member_identities({**K13, 'bundleMembers': []}), [])
        self.assertEqual(member_identities({**K13, 'bundleMembers': 'invalid'}), [])

    def test_account_expansion_requires_installer_and_preserves_bundle_identity(self):
        payload = {'products': [K13]}
        rows = expand_catalog(payload, [self.artifact(), self.artifact('unrelated')])['products']
        self.assertEqual({row['upid'] for row in rows}, {K13['upid'], PHASIS})
        self.assertEqual(next(row['title'] for row in rows if row['upid'] == PHASIS), 'Phasis')
        self.assertEqual(payload, {'products': [K13]})

    def test_daemon_decoder_preserves_only_public_bundle_member_fields(self):
        member = message_field(1, b'child') + message_field(2, b'Child') + message_field(4, b'public-snpid')
        encoded = message_field(1, b'bundle') + varint(19 << 3) + varint(5) + message_field(32, message_field(1, member))
        row = _product(encoded)
        self.assertEqual(row['bundleMembers'], [{'upid': 'child', 'title': 'Child'}])


if __name__ == '__main__':
    unittest.main()
