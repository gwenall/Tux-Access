"""Non-secret user preferences shared by the desktop and installer backends."""
from dataclasses import dataclass, fields, replace
import json
import os
from pathlib import Path
import stat
import tempfile
from urllib.parse import urlsplit


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class AppSettings:
    download_directory: Path
    installation_directory: Path
    content_directory: Path
    wine_prefix_directory: Path
    wine_executable: str = 'wine'
    yabridge_directory: Path | None = None
    prefer_native: bool = True
    manage_wine: bool = True
    manual_mode: bool = False
    reference_endpoint: str = 'tcp://127.0.0.1:5146'


def default_settings():
    home = Path.home()
    data = Path(os.environ.get('XDG_DATA_HOME', str(home / '.local/share')))
    application = data / 'native-access-linux'
    return AppSettings(home / 'Downloads/Native Access', application,
                       home / 'Native Instruments', application / 'wine-prefixes')


def _path(value):
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise SettingsError('Choose an absolute directory path.')
    if any(ord(c) < 32 for c in str(value)):
        raise SettingsError('Directory paths cannot contain control characters.')
    path = Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts:
        raise SettingsError('Choose an absolute directory without parent traversal.')
    return path


def validate_settings(settings):
    if not isinstance(settings, AppSettings):
        raise SettingsError('Invalid settings record.')
    names = ('download_directory', 'installation_directory', 'content_directory', 'wine_prefix_directory')
    normalized = {name: _path(getattr(settings, name)) for name in names}
    normalized['yabridge_directory'] = (_path(settings.yabridge_directory)
                                       if settings.yabridge_directory is not None else None)
    for name in ('prefer_native', 'manage_wine', 'manual_mode'):
        if type(getattr(settings, name)) is not bool:
            raise SettingsError('Invalid settings toggle.')
    wine = settings.wine_executable
    if not isinstance(wine, str) or (wine != 'wine' and not Path(wine).is_absolute()):
        raise SettingsError('Wine must be the system command or an absolute executable path.')
    if not wine or any(ord(c) < 32 for c in wine):
        raise SettingsError('Invalid Wine executable path.')
    try:
        endpoint = urlsplit(settings.reference_endpoint)
        valid = (endpoint.scheme == 'tcp' and endpoint.hostname in ('127.0.0.1', 'localhost', '::1')
                 and endpoint.port is not None and 1 <= endpoint.port <= 65535
                 and not endpoint.username and not endpoint.password
                 and not endpoint.path and not endpoint.query and not endpoint.fragment)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise SettingsError('The reference bridge must be a loopback TCP endpoint.')
    return replace(settings, **normalized)


def _location(path):
    if path is not None:
        return _path(path)
    return _path(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
                 / 'native-access-linux/settings.json')


def load_settings(path=None):
    path = _location(path)
    if path.is_symlink():
        raise SettingsError('The settings file cannot be a symbolic link.')
    if not path.exists():
        return validate_settings(default_settings())
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
            raise SettingsError('Invalid settings file type or size.')
        data = json.loads(path.read_text(encoding='utf-8'))
        allowed = {field.name for field in fields(AppSettings)}
        if not isinstance(data, dict) or set(data) - allowed:
            raise SettingsError('Unrecognized settings fields.')
        defaults = default_settings()
        return validate_settings(replace(defaults, **data))
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError) as error:
        raise SettingsError('Could not read valid launcher settings.') from None


def save_settings(settings, path=None):
    settings = validate_settings(settings)
    path = _location(path)
    if path.is_symlink():
        raise SettingsError('The settings file cannot be a symbolic link.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = {field.name: getattr(settings, field.name) for field in fields(settings)}
    for name, value in data.items():
        if isinstance(value, Path):
            data[name] = str(value)
    fd, temporary_name = tempfile.mkstemp(prefix='.settings-', dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return settings
