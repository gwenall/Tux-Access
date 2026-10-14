import unittest
from download_catalog import available_artifacts, select_artifacts
from account_api import AccountApiError

class DownloadCatalogTests(unittest.TestCase):
    def fixture(self):
        return {'artifacts':[{'upid':'test','title':'Sample','version':'1.2.3',
            'platform':'win','hardware_platform':'x64','filesize':123,
            'target_file':'sample.exe','file_type':'exe','url':'https://example.com/sample?signature=private'}]}

    def test_platform_selection_and_sensitive_url_exclusion(self):
        artifacts=available_artifacts('token',lambda _:self.fixture())
        self.assertEqual(select_artifacts(artifacts,upid='test',platform='linux'),[])
        self.assertEqual(len(select_artifacts(artifacts,upid='test',platform='win')),1)
        self.assertNotIn('signature',repr(artifacts))
        self.assertNotIn('url',artifacts[0].public_metadata())

    def test_bad_artifacts_fail_without_returning_partial_catalog(self):
        for key,value in [('filesize',-1),('filesize',True),('url','http://example.com/file'),('url','https://user:secret@example.com/file'),('version',None)]:
            response=self.fixture(); response['artifacts'][0][key]=value
            with self.assertRaises(AccountApiError): available_artifacts('token',lambda _:response)

    def test_relative_download_reference_preserved_without_guessing_host(self):
        response=self.fixture(); response['artifacts'][0]['url']='/artifacts/test/file'
        artifact=available_artifacts('token',lambda _:response)[0]
        self.assertEqual(artifact.url,'/artifacts/test/file')

if __name__ == '__main__': unittest.main()
