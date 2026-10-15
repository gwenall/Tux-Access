"""Run via ``python -m tux_access`` or an absolute browser callback path."""
from pathlib import Path
import sys

# Desktop URI handlers must also work from an arbitrary working directory when
# running an uninstalled source checkout. Normal module execution needs no setup.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tux_access.cli import main

if __name__ == '__main__':
    sys.exit(main())
