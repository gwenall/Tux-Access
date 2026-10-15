"""Collection membership is distinct from account installer authorization."""
import re

from bundle_catalog_data import BUNDLES

SOURCE_LABEL = 'NI catalog reference, 14 October 2026'


def is_bundle(product):
    if not isinstance(product, dict):
        return False
    kind = product.get('type')
    return (product.get('upid') in BUNDLES or kind == 5 or
            isinstance(kind, str) and kind.casefold() == 'bundle' or
            'bundleMembers' in product or 'bundle_members' in product)


def member_identities(product):
    """Return whitelisted public metadata; an explicit live list takes precedence."""
    if not is_bundle(product):
        return []
    if 'bundleMembers' in product:
        source = product['bundleMembers']
    elif 'bundle_members' in product:
        source = product['bundle_members']
    else:
        source = BUNDLES.get(product.get('upid'), {}).get('members', [])
    if isinstance(source, dict):
        source = source.get('members', [])
    if not isinstance(source, list):
        return []
    seen, result = set(), []
    for member in source[:4096]:
        if not isinstance(member, dict):
            continue
        upid = member.get('upid')
        title = member.get('title', member.get('display_name', member.get('displayName')))
        if (not isinstance(upid, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', upid)
                or upid == product.get('upid') or upid in seen or
                not isinstance(title, str) or not title.strip() or len(title) > 500 or
                any(ord(c) < 32 for c in title)):
            continue
        result.append({'upid': upid, 'title': title.strip()})
        seen.add(upid)
    return result


def bundle_members(product, products, artifacts=None):
    """List only confirmed members, preserving real local/account state by ID.

    Membership alone never grants download access. An Install action also needs
    an exact member ID in the account's current installer metadata.
    """
    rows = {row['upid']: row for row in products
            if isinstance(row, dict) and isinstance(row.get('upid'), str)}
    eligible = {a.upid for a in (artifacts or []) if a.file_type == 'installer'}
    result = []
    for identity in member_identities(product):
        row = dict(rows.get(identity['upid'], identity))
        row.setdefault('source', 'bundle-membership')
        row.setdefault('status', 'Account installer available' if identity['upid'] in eligible else 'Installer unavailable')
        row.update(bundleParentUpid=product.get('upid'),
                   bundleInstallerAvailable=identity['upid'] in eligible)
        result.append(row)
    return sorted(result, key=lambda row: str(row.get('title', '')).casefold())
