import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from package_inspection import inspect_deb, PackageError

def member(name, data):
    header = f'{name+"/":<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(data):<10}`\n'.encode()
    return header+data+(b'\n' if len(data)%2 else b'')

def archive(files):
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w:xz') as tar:
        for name,data in files.items():
            entry=tarfile.TarInfo(name);entry.size=len(data)
            tar.addfile(entry,io.BytesIO(data))
    return output.getvalue()

class PackageInspectionTests(unittest.TestCase):
    def test_inspection_never_runs_maintainer_script_or_extracts_payload(self):
        control=archive({'control':b'Package: independent-test\nVersion: 1.0\nArchitecture: amd64\n',
                         'postinst':b'#!/bin/sh\nexit 99\n'})
        payload=archive({'usr/share/test.txt':b'fixture data'})
        data=b'!<arch>\n'+member('debian-binary',b'2.0\n')+member('control.tar.xz',control)+member('data.tar.xz',payload)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.deb';path.write_bytes(data)
            with patch('subprocess.run',side_effect=AssertionError('Package code must not run')):
                result=inspect_deb(path,hashlib.sha256(data).hexdigest())
            self.assertEqual(result['control']['Package'],'independent-test')
            self.assertEqual(result['maintainer_scripts'],['postinst'])
            self.assertTrue(result['integrity_verified'])
            self.assertEqual(list(Path(directory).iterdir()),[path])

    def test_hash_mismatch_and_truncated_archive_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.deb';path.write_bytes(b'!<arch>\ntruncated')
            with self.assertRaisesRegex(PackageError,'SHA-256'):inspect_deb(path,'0'*64)
            with self.assertRaises(PackageError):inspect_deb(path)

if __name__ == '__main__':unittest.main()
