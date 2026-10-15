import hashlib
import io
from email.message import Message
from pathlib import Path
import tempfile
import unittest
from tux_access.downloads.catalog import Artifact
from tux_access.downloads.manager import parse_metalink, resolve_artifact, download, DownloadSpec, DownloadError, DownloadCancelled

CONTENT=b'independent verified payload fixture'
DIGEST=hashlib.sha256(CONTENT).hexdigest()
URL='https://artifacts-cdn.native-instruments.com/test/file?signature=private'

class Response(io.BytesIO):
    def __init__(self,payload,kind='application/octet-stream',length=None):
        super().__init__(payload)
        self.status=200; self.headers=Message()
        self.headers['Content-Type']=kind
        if length is not None:self.headers['Content-Length']=str(length)

class Opener:
    def __init__(self,payload,kind='application/octet-stream'): self.payload=payload; self.kind=kind; self.requests=[]
    def open(self,request,timeout):
        self.requests.append(request)
        return Response(self.payload,self.kind)

class DownloadTests(unittest.TestCase):
    def artifact(self):return Artifact('test','Sample','1','linux-x86_64','any',len(CONTENT),'sample.deb','installer','/test/path/file')
    def metalink(self):return f'<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file name="sample.deb"><size>{len(CONTENT)}</size><hash type="sha-256">{DIGEST}</hash><url>{URL.replace("&","&amp;")}</url></file></metalink>'.encode()
    def spec(self):return DownloadSpec('sample.deb',len(CONTENT),DIGEST,(URL,))

    def test_authorized_resolution_and_no_bearer_on_payload(self):
        opener=Opener(self.metalink(),'application/metalink4+xml')
        spec=resolve_artifact(self.artifact(),'test-token',opener=opener)
        self.assertEqual(opener.requests[0].full_url,'https://api.native-instruments.com/v2/download/test/path/file')
        self.assertEqual(opener.requests[0].get_header('Authorization'),'Bearer test-token')
        payload=Opener(CONTENT)
        with tempfile.TemporaryDirectory() as directory:
            target=download(spec,directory,opener=payload)
            self.assertEqual(target.read_bytes(),CONTENT)
            self.assertIsNone(payload.requests[0].get_header('Authorization'))
        self.assertNotIn('signature',repr(spec))

    def test_size_hash_and_cancellation_never_publish_invalid_file(self):
        for body,spec,cancelled,error in ((CONTENT+b'x',self.spec(),None,DownloadError),
            (CONTENT[:-1],self.spec(),None,DownloadError),
            (CONTENT,DownloadSpec('sample.deb',len(CONTENT),'0'*64,(URL,)),None,DownloadError),
            (CONTENT,self.spec(),lambda:True,DownloadCancelled)):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(error): download(spec,directory,opener=Opener(body),cancelled=cancelled)
                self.assertEqual(list(Path(directory).iterdir()),[])

    def test_existing_destination_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'sample.deb'; target.write_bytes(b'existing')
            with self.assertRaises(DownloadError):download(self.spec(),directory,opener=Opener(CONTENT))
            self.assertEqual(target.read_bytes(),b'existing')

    def test_untrusted_metalink_and_filename_rejected(self):
        for xml in (self.metalink().replace(b'sample.deb',b'../sample.deb'),
                    self.metalink().replace(DIGEST.encode(),b'invalid'),
                    self.metalink().replace(b'artifacts-cdn.native-instruments.com',b'example.com'),
                    b'<!DOCTYPE x><metalink/>',b'<broken',self.metalink().replace(b'<size>',b'<size>99')):
            with self.assertRaises(DownloadError):parse_metalink(xml,self.artifact())

if __name__ == '__main__':unittest.main()
