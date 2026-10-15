"""Public NI standalone identities observed in the original application's catalog.

These are product identities, not license grants. An application is added only
when the signed-in account's full-products API supplies its installer metadata.
The Applications view excludes libraries and expansions. Other confirmed bundle
members can appear in the full catalog when an authorized installer is available.
"""

APPLICATIONS = {
    '00b224af-b357-4dfe-9929-414bbdf97d6f': ('Absynth 5', 1),
    '5e508a8c-9fd2-4fcd-a4b6-747569cd7eac': ('Audiolens', 1),
    'c6b8ce64-9c20-49bb-96a7-4a13e3b2edfd': ('Battery 4', 1),
    'f2ce397b-a6f5-4680-90a2-2b567517fa61': ('Controller Editor', 4),
    'd4eabebb-c95b-4d71-bb1f-c8cd98d9e64a': ('Creator Tools', 1),
    'f1e4c3f3-300a-413f-983e-cb8fb758397e': ('FM8', 1),
    'e390057f-14b9-4e78-b033-3d7cc7e7767b': ('Guitar Rig 6', 1),
    'f819ab0d-6180-44cf-b2f6-56f6d0c70f25': ('Guitar Rig 7', 1),
    'cf11c1f6-1d76-432f-aece-52ef5305a14d': ('Komplete Kontrol', 1),
    '68cffbb8-7b20-4e9a-bee5-1dab962049ff': ('Kontakt', 1),
    '9259876f-e616-4e21-bc27-0b506868e1d0': ('Kontakt 7', 1),
    '0e504595-40d8-4982-978e-a242f036912d': ('Kontakt 8', 1),
    'fccc863c-324f-4d79-af7e-b38c1f7488fe': ('Maschine 2', 1),
    '02cf2683-8802-4ccc-b7c4-78c89f7d3fad': ('Massive', 1),
    '39232cc5-01ba-4404-b5aa-00af0c82b92e': ('Reaktor 6', 1),
    '0f2ff284-7aed-4f67-8d54-9d8ec1547e34': ('Traktor DJ 2', 1),
}


def is_application(product):
    return product.get('upid') in APPLICATIONS or product.get('isApplication') is True


def expand_catalog(payload, artifacts):
    """Expand account bundle entitlements using their authorized app installers.

    Preserve the original account rows and titles as metadata. Do not infer any
    installed state, activation, edition or standalone runtime compatibility.
    """
    from tux_access.catalog.products import catalog_rows
    from tux_access.catalog.bundles import member_identities
    rows = [dict(row) for row in catalog_rows(payload)]
    members = {member['upid']: member for row in rows for member in member_identities(row)}
    eligible = {artifact.upid for artifact in artifacts
                if artifact.file_type == 'installer' and (artifact.upid in APPLICATIONS or artifact.upid in members)}
    by_id = {row.get('upid'): row for row in rows if row.get('upid')}
    for upid in sorted(eligible):
        name, kind = APPLICATIONS.get(upid, (members.get(upid, {}).get('title', ''), None))
        row = by_id.get(upid)
        if row is None:
            row = {'upid': upid, 'title': name, 'source': 'account-downloads', 'status': 'Account record'}
            rows.append(row)
        elif row.get('title') != name:
            row.setdefault('entitlementTitle', row.get('title', ''))
            row['title'] = name
        if kind is not None:
            row.update(type=kind, isApplication=True)
    return {'products': rows}
