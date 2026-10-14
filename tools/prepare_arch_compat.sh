#!/bin/bash
# Prepare the exact legacy ABIs used by the two inspected NI Linux VST packages.
set -eu
[ -f /etc/arch-release ] || { echo 'This preparation script currently targets Arch Linux.' >&2; exit 1; }
sudo pacman -S --needed python cmake ninja gcc make patchelf
stage="${XDG_CACHE_HOME:-$HOME/.cache}/native-access-linux/compat-build"
prefix="$HOME/.local/lib/native-access-linux/compat-legacy"
mkdir -p "$stage/downloads" "$prefix/lib"
cd "$stage/downloads"
python -u - <<'PY'
import hashlib,re
from pathlib import Path
import urllib.request
files={
 'openssl-1.1-1.1.1.w-2-x86_64.pkg.tar.zst':'https://archive.archlinux.org/packages/o/openssl-1.1/openssl-1.1-1.1.1.w-2-x86_64.pkg.tar.zst',
 'openssl-1.1-1.1.1.w-2-x86_64.pkg.tar.zst.sig':'https://archive.archlinux.org/packages/o/openssl-1.1/openssl-1.1-1.1.1.w-2-x86_64.pkg.tar.zst.sig',
 'xerces-c-3.2.5.tar.gz':'https://archive.apache.org/dist/xerces/c/3/sources/xerces-c-3.2.5.tar.gz',
 'xerces-c-3.2.5.tar.gz.sha256':'https://archive.apache.org/dist/xerces/c/3/sources/xerces-c-3.2.5.tar.gz.sha256',
}
for name,url in files.items():
 with urllib.request.urlopen(url, timeout=30) as response:
  payload=response.read(32*1024*1024+1)
  if len(payload)>32*1024*1024:raise RuntimeError('Source download exceeds limit')
 Path(name).write_bytes(payload)
 print('Fetched '+name)
expected=re.search(r'\b[0-9a-fA-F]{64}\b',Path('xerces-c-3.2.5.tar.gz.sha256').read_text()).group().lower()
if hashlib.sha256(Path('xerces-c-3.2.5.tar.gz').read_bytes()).hexdigest()!=expected:
 raise RuntimeError('Apache source checksum mismatch')
print('Apache source checksum verified.')
PY
sudo pacman-key --verify openssl-1.1-1.1.1.w-2-x86_64.pkg.tar.zst.sig openssl-1.1-1.1.1.w-2-x86_64.pkg.tar.zst
mkdir -p "$stage/openssl" "$stage/source"
bsdtar -xf openssl-1.1-1.1.1.w-2-x86_64.pkg.tar.zst -C "$stage/openssl"
bsdtar -xf xerces-c-3.2.5.tar.gz -C "$stage/source"
cp "$stage/openssl/usr/lib/libssl.so.1.1" "$stage/openssl/usr/lib/libcrypto.so.1.1" "$prefix/lib/"
cmake -S "$stage/source/xerces-c-3.2.5" -B "$stage/build" -G Ninja -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_INSTALL_LIBDIR=lib -DBUILD_SHARED_LIBS=ON -DBUILD_TESTING=OFF -Dtranscoder=gnuiconv -Dnetwork-accessor=socket
cmake --build "$stage/build" -j "$(nproc)"
cmake --install "$stage/build"
echo 'Compatibility libraries prepared for local plug-in installation.'
