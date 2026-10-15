"""Native Metalink resolution and verified retrieval. Does not run installers."""
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

API_ORIGIN = 'https://api.native-instruments.com'
CDN_HOSTS = frozenset({'artifacts-cdn.native-instruments.com'})
MAX_METALINK = 1024 * 1024
NAMESPACE = '{urn:ietf:params:xml:ns:metalink}'

class DownloadError(RuntimeError): pass
class DownloadCancelled(DownloadError): pass

@dataclass(frozen=True)
class DownloadSpec:
    name: str
    size: int
    sha256: str
    urls: tuple[str, ...] = field(repr=False)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DownloadError('Unexpected download redirect')

def _https(url, hosts):
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == 'https' and parsed.hostname in hosts and
                 parsed.port in (None,443) and not parsed.username and
                 not parsed.password and not parsed.fragment)
    except ValueError:
        valid=False
    if not valid: raise DownloadError('Untrusted download origin')
    return url

def parse_metalink(xml, artifact):
    if len(xml)>MAX_METALINK or b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
        raise DownloadError('Invalid Metalink document')
    try:
        root=ET.fromstring(xml)
        if root.tag != NAMESPACE+'metalink': raise DownloadError('Unexpected Metalink namespace')
        files=root.findall(NAMESPACE+'file')
        if len(files)!=1: raise DownloadError('Expected exactly one artifact file')
        element=files[0]
        name=element.get('name','')
        # Both separators are rejected even when inspecting another OS's payload.
        if not name or name in ('.','..') or any(c in name for c in ('/','\\',':','\x00')):
            raise DownloadError('Invalid artifact filename')
        if name!=artifact.target_file: raise DownloadError('Artifact filename mismatch')
        size=int(element.findtext(NAMESPACE+'size','-1'))
        if size<0 or size!=artifact.filesize: raise DownloadError('Artifact size mismatch')
        hashes=[(h.text or '').strip().lower() for h in element.findall(NAMESPACE+'hash') if h.get('type')=='sha-256']
        if len(hashes)!=1 or not re.fullmatch('[0-9a-f]{64}',hashes[0]):
            raise DownloadError('Metalink requires one SHA-256 digest')
        urls=tuple(_https((node.text or '').strip(),CDN_HOSTS) for node in element.findall(NAMESPACE+'url'))
        if not urls: raise DownloadError('Metalink has no trusted download source')
        return DownloadSpec(name,size,hashes[0],urls)
    except (ET.ParseError,ValueError,TypeError):
        raise DownloadError('Malformed Metalink document') from None

def resolve_artifact(artifact, token, *, opener=None):
    if not isinstance(token,str) or not token or '\r' in token or '\n' in token or len(token)>32768:
        raise ValueError('Invalid access token')
    reference=urlsplit(artifact.url)
    if reference.scheme or reference.netloc or reference.query or reference.fragment or not reference.path.startswith('/') or '..' in reference.path.split('/'):
        raise DownloadError('Expected a root-relative NI artifact reference')
    request=urllib.request.Request(API_ORIGIN+'/v2/download'+artifact.url,
        headers={'Authorization':'Bearer '+token,'Accept':'application/metalink4+xml'},method='GET')
    opener=opener or urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request,timeout=20) as response:
            if response.status!=200 or response.headers.get_content_type()!='application/metalink4+xml':
                raise DownloadError('Unexpected artifact resolution response')
            return parse_metalink(response.read(MAX_METALINK+1),artifact)
    except urllib.error.HTTPError as exc:
        raise DownloadError(f'Artifact resolution rejected (HTTP {exc.code})') from None
    except (urllib.error.URLError,OSError):
        raise DownloadError('Artifact resolution failed') from None

def download(spec, directory, *, opener=None, cancelled=None, progress=None):
    """Stream to a private temp file; publish only after size and SHA-256 match.

    The account bearer token is never passed to this CDN request. Existing
    destination files are preserved. Cancellation discards the partial file.
    """
    directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    if not spec.name or Path(spec.name).name!=spec.name or any(c in spec.name for c in ('/','\\',':','\x00')) or spec.name in ('.','..'):
        raise DownloadError('Invalid destination filename')
    if not isinstance(spec.size,int) or spec.size<0 or not re.fullmatch('[0-9a-f]{64}',spec.sha256):
        raise DownloadError('Invalid download specification')
    target=directory/spec.name
    if target.exists(): raise DownloadError('Destination already exists')
    opener=opener or urllib.request.build_opener(NoRedirect())
    if not spec.urls: raise DownloadError('No payload source')
    request=urllib.request.Request(_https(spec.urls[0],CDN_HOSTS),headers={'Accept':'application/octet-stream'},method='GET')
    fd,temp_name=tempfile.mkstemp(prefix='.ni-download-',suffix='.part',dir=directory)
    temporary=Path(temp_name)
    try:
        digest=hashlib.sha256()
        written=0
        with os.fdopen(fd,'wb') as output, opener.open(request,timeout=20) as response:
            if response.status!=200: raise DownloadError('Unexpected payload response')
            length=response.headers.get('Content-Length')
            if length is not None and int(length)!=spec.size: raise DownloadError('Payload length mismatch')
            while True:
                if cancelled is not None and cancelled(): raise DownloadCancelled('Download cancelled')
                chunk=response.read(min(256*1024,spec.size-written+1))
                if not chunk: break
                written+=len(chunk)
                if written>spec.size: raise DownloadError('Payload exceeded expected size')
                digest.update(chunk)
                output.write(chunk)
                if progress is not None: progress(written,spec.size)
            output.flush()
            os.fsync(output.fileno())
        if written!=spec.size: raise DownloadError('Payload size mismatch')
        if digest.hexdigest()!=spec.sha256: raise DownloadError('Payload SHA-256 mismatch')
        if cancelled is not None and cancelled(): raise DownloadCancelled('Download cancelled')
        # Exclusive publication on POSIX and Windows; never replace an existing file.
        os.link(temporary,target)
        return target
    except urllib.error.HTTPError as exc:
        raise DownloadError(f'Payload request rejected (HTTP {exc.code})') from None
    except (urllib.error.URLError,OSError,ValueError):
        raise DownloadError('Payload retrieval or publication failed') from None
    finally:
        try: temporary.unlink()
        except FileNotFoundError: pass
