"""Compatibility entrypoint for existing source-checkout launch commands."""
from tux_access.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
