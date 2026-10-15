"""Choose one bundled, user-supplied Tux illustration per application process."""
import os
from pathlib import Path
import secrets
import sys
import tempfile

LEGACY_ART_NAMES = {
    'tux-01.png': 'tux-flying-v-guitar-headphones.png',
    'tux-02.png': 'tux-dj-turntables-headphones.png',
    'tux-03.png': 'tux-violin-bow-tie.png',
    'tux-04.png': 'tux-keyboard-player.png',
    'tux-05.png': 'tux-saxophone-sunglasses.png',
    'tux-06.png': 'tux-drum-kit.png',
    'tux-07.png': 'tux-flying-v-guitar.png',
    'tux-08.png': 'tux-home-music-studio.png',
}
ART_NAMES = tuple(LEGACY_ART_NAMES.values()) + (
    'tux-acoustic-guitar-headphones.png',
    'tux-flute-headphones.png',
    'tux-clarinet-headphones.png',
    'tux-cello-headphones.png',
    'tux-bass-guitar-headphones.png',
    'tux-singer-microphone.png',
)
_UNSET = object()
_startup_art = _UNSET


def find_artwork(source_directory=None, prefix=None):
    """Work from a source tree or installed data files, independently of cwd."""
    source = Path(source_directory) if source_directory is not None else Path(__file__).resolve().parent
    prefix = Path(prefix) if prefix is not None else Path(sys.prefix)
    for directory in (source / 'assets/tux', prefix / 'share/native-access-linux/assets/tux'):
        available = tuple(directory / name for name in ART_NAMES if (directory / name).is_file())
        if available:
            return available
    return ()


def art_cache_file():
    base = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache')))
    if not base.is_absolute():
        base = Path.home() / '.cache'
    return base / 'native-access-linux/sidebar-art.txt'


def choose_artwork(artwork, cache_file=None, chooser=secrets.choice):
    """Best-effort no-repeat cache; its only content is a bundled image name."""
    artwork = tuple(artwork)
    if not artwork:
        return None
    cache = Path(cache_file) if cache_file is not None else art_cache_file()
    previous = None
    try:
        if not cache.is_symlink() and cache.stat().st_size <= 64:
            previous = cache.read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        pass
    previous = LEGACY_ART_NAMES.get(previous, previous)
    choices = tuple(path for path in artwork if path.name != previous) or artwork
    chosen = chooser(choices)
    temporary = None
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.sidebar-art-', dir=cache.parent)
        temporary = Path(name)
        with os.fdopen(fd, 'w', encoding='ascii') as stream:
            stream.write(chosen.name + '\n')
        os.replace(temporary, cache)
    except OSError:
        # Artwork must never prevent startup on a read-only or full home folder.
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return chosen


def startup_artwork():
    global _startup_art
    if _startup_art is _UNSET:
        _startup_art = choose_artwork(find_artwork())
    return _startup_art
