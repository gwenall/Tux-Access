"""Independent native desktop launcher for the first Linux compatibility milestone."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def state_path() -> Path:
    """Follow XDG without assuming a distribution or a Windows home layout."""
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'native-access-linux' / 'catalog.json'


def catalog_rows(payload):
    if isinstance(payload, dict):
        for key in ('knownProducts', 'known_products', 'products'):
            if key in payload:
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValueError('Expected a product list or an object with a products/knownProducts field.')
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError('Each product must be a JSON object.')
    return payload


def product_values(p):
    name = p.get('title') or p.get('name') or p.get('displayName') or p.get('display_name') or p.get('upid') or 'Unnamed product'
    version = p.get('installedVersion') or p.get('version') or ''
    if isinstance(version, dict):
        version = '.'.join(str(version.get(k, 0)) for k in ('major', 'minor', 'micro'))
    kind = p.get('type', '')
    kinds = {0: 'Unspecified', 1: 'Application', 2: 'Content', 3: 'Plug-in', 4: 'Utility', 5: 'Bundle', 6: 'Hardware', 7: 'Other'}
    if isinstance(kind, int):
        kind = kinds.get(kind, f'Type {kind}')
    state = p.get('installationState') or p.get('installationStatus') or p.get('status', '')
    if not state and 'installed' in p:
        state = 'Installed' if p['installed'] else 'Not installed'
        if p.get('updateable'):
            state += ' · update available'
    return str(name), str(version), str(kind), str(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', default='tcp://127.0.0.1:5146', help='NTK request endpoint; local by default')
    parser.add_argument('--probe', action='store_true', help='Check the daemon and print catalog counts without opening a window')
    parser.add_argument('--export', type=Path, help='With --probe, save the product catalog as JSON')
    parser.add_argument('--inspect', choices=('preferences', 'deployments', 'catalog'), help='Read a complete descriptor-backed daemon response as JSON')
    parser.add_argument('--inspect-package', type=Path, help='Inspect a Debian package without executing it')
    parser.add_argument('--expected-sha256', help='Expected package digest from a verified Metalink')
    args = parser.parse_args()
    if args.inspect_package:
        if args.inspect or args.probe or args.export:
            parser.error('--inspect-package cannot be combined with daemon query options')
        from package_inspection import inspect_deb, PackageError
        try:
            print(json.dumps(inspect_deb(args.inspect_package, args.expected_sha256), ensure_ascii=False, indent=2))
        except (OSError, PackageError) as exc:
            parser.exit(1, f'Package inspection failed: {exc}\n')
        return
    if args.expected_sha256:
        parser.error('--expected-sha256 requires --inspect-package')
    if args.inspect:
        if args.probe or args.export:
            parser.error('--inspect cannot be combined with --probe or --export')
        from ntk_protocol import NtkClient
        client = None
        try:
            client = NtkClient(endpoint=args.endpoint)
            print(json.dumps(client.inspect(args.inspect), ensure_ascii=False, indent=2))
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            parser.exit(1, f'Backend unavailable: {exc}\n')
        finally:
            if client is not None:
                client.close()
        return
    if args.export and not args.probe:
        parser.error('--export requires --probe')
    if args.probe:
        from ntk_protocol import NtkClient
        client = None
        try:
            client = NtkClient(endpoint=args.endpoint)
            client.ping()
            version = client.version()
            products = catalog_rows(client.known_products())
            if args.export:
                args.export.write_text(json.dumps({'products': products}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'daemonVersion': version, 'products': len(products), 'installed': sum(bool(p.get('installed')) for p in products)}))
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            parser.exit(1, f'Backend unavailable: {exc}\n')
        finally:
            if client is not None:
                client.close()
        return
    try:
        from PySide6 import QtWidgets
        from qt_launcher import Launcher as QtLauncher
    except ImportError:
        parser.exit(1, 'Desktop mode requires the desktop extra: pip install ".[desktop]"\n')
    app = QtWidgets.QApplication([])
    window = QtLauncher(args.endpoint)
    window.show()
    return app.exec()


if __name__ == '__main__':
    main()
