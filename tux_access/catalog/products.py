"""Normalize product payloads for library, install, and removal workflows."""

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
