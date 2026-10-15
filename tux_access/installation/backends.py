"""Fixed qualified Wine product dispatch shared by install, launch and removal."""
from dataclasses import dataclass

from tux_access.catalog.products import product_values


@dataclass(frozen=True)
class WineSpec:
    version: str
    filename: str
    size: int
    sha256: str
    manager: object
    install_method: str
    receipt_name: str
    load_hashes: object = None


def title_key(product):
    return ''.join(letter for letter in product_values(product)[0].casefold() if letter.isalnum())


def wine_spec(product):
    key = title_key(product)
    if key in ('kontakt8', 'kontakt8player'):
        from tux_access.installation.wine.kontakt import WineManager, ZIP_SIZE, ZIP_SHA256, RECEIPT
        return WineSpec('8.9.0', 'Kontakt_8_Installer.zip', ZIP_SIZE, ZIP_SHA256,
                        WineManager, 'install_kontakt_890', RECEIPT)
    if key == 'maschine2':
        from tux_access.installation.wine.maschine import MaschineManager, ZIP_SIZE, ZIP_SHA256, RECEIPT, load_hashes
        return WineSpec('2.18.4', 'Maschine_2_Installer.zip', ZIP_SIZE, ZIP_SHA256,
                        MaschineManager, 'install_maschine_2184', RECEIPT, load_hashes)
    if key == 'massive':
        from tux_access.installation.wine.massive import MassiveManager, ZIP_SIZE, ZIP_SHA256, PROFILE
        return WineSpec(PROFILE.version, 'Massive_Installer.zip', ZIP_SIZE, ZIP_SHA256,
                        MassiveManager, 'install_massive_170', '.native-access-linux-massive.json', PROFILE.load_hashes)
    return None
