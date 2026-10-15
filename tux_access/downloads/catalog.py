"""Native account-authorized artifact metadata; no downloading or installation."""
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from tux_access.auth.api import http_downloads, AccountApiError

@dataclass(frozen=True)
class Artifact:
    upid: str
    title: str
    version: str
    platform: str
    hardware_platform: str
    filesize: int
    target_file: str
    file_type: str
    url: str = field(repr=False)
    os_min: str | None = None
    os_max: str | None = None

    def public_metadata(self):
        """Allow display/export of metadata without signed download URLs."""
        return {key:value for key,value in self.__dict__.items() if key != 'url'}

def available_artifacts(token, transport=http_downloads):
    data=transport(token)
    if not isinstance(data,dict) or not isinstance(data.get('artifacts'),list):
        raise AccountApiError('Invalid download metadata envelope')
    result=[]
    for row in data['artifacts']:
        if not isinstance(row,dict):
            raise AccountApiError('Invalid artifact metadata record')
        required=('upid','title','version','platform','hardware_platform','target_file','file_type','url')
        if any(not isinstance(row.get(key),str) for key in required):
            raise AccountApiError('Missing artifact string fields')
        size=row.get('filesize')
        if isinstance(size,bool) or not isinstance(size,int) or size<0:
            raise AccountApiError('Invalid artifact file size')
        url=urlsplit(row['url'])
        relative_path = not url.scheme and not url.netloc and url.path.startswith('/') and not url.path.startswith('//')
        absolute_https = url.scheme == 'https' and bool(url.hostname)
        if not (relative_path or absolute_https) or url.username or url.password or url.fragment:
            raise AccountApiError('Untrusted download URL format')
        result.append(Artifact(**{key:row[key] for key in required},filesize=size,
                               os_min=row.get('os_min'),os_max=row.get('os_max')))
    return result

def select_artifacts(artifacts, *, upid, platform=None, hardware_platform=None):
    """Exact platform matching; never treats Windows or macOS as native Linux."""
    return [a for a in artifacts if a.upid==upid and
            (platform is None or a.platform==platform) and
            (hardware_platform is None or a.hardware_platform==hardware_platform)]
