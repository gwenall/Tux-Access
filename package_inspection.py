"""Offline Debian/ELF package inspection. Never extracts or runs package code."""
import hashlib
import io
from pathlib import Path
import re
import struct
import tarfile

class PackageError(RuntimeError): pass

def _members(data):
    if data[:8]!=b'!<arch>\n': raise PackageError('Not a Debian ar archive')
    position=8
    result={}
    while position<len(data):
        header=data[position:position+60]
        if len(header)!=60 or header[58:]!=b'`\n':raise PackageError('Malformed ar header')
        try:
            name=header[:16].decode('ascii').strip().rstrip('/')
            size=int(header[48:58].decode('ascii').strip())
        except (ValueError,UnicodeDecodeError):raise PackageError('Invalid ar member') from None
        position+=60
        if size<0 or size>len(data)-position or name in result:raise PackageError('Invalid ar member size or duplicate name')
        result[name]=data[position:position+size]
        position+=size+size%2
    if result.get('debian-binary')!=b'2.0\n':raise PackageError('Unsupported Debian package version')
    return result

def _elf(payload):
    if payload[:4]!=b'\x7fELF':return None
    if len(payload)<64 or payload[4]!=2 or payload[5] not in (1,2):
        return {'format':'ELF','class':payload[4] if len(payload)>4 else None,'inspection':'unsupported layout'}
    endian='<' if payload[5]==1 else '>'
    machine=struct.unpack_from(endian+'H',payload,18)[0]
    offset=struct.unpack_from(endian+'Q',payload,40)[0]
    step,count=struct.unpack_from(endian+'HH',payload,58)
    if count>65535 or step<64 or offset+step*count>len(payload):raise PackageError('Invalid ELF section table')
    sections=[struct.unpack_from(endian+'IIQQQQIIQQ',payload,offset+i*step) for i in range(count)]
    def body(section):
        start,size=section[4],section[5]
        if start+size>len(payload):raise PackageError('Invalid ELF section range')
        return payload[start:start+size]
    needed=[]
    soname=None
    entrypoints=[]
    for section in sections:
        if section[1] not in (6,11):continue
        if section[6]>=len(sections):raise PackageError('Invalid ELF string table link')
        strings=body(sections[section[6]])
        def name(index):
            if index>=len(strings):raise PackageError('Invalid ELF string offset')
            end=strings.find(b'\x00',index)
            if end<0:raise PackageError('Unterminated ELF string')
            return strings[index:end].decode('utf-8','replace')
        raw=body(section)
        if section[1]==6:
            if len(raw)%16:raise PackageError('Malformed ELF dynamic table')
            for i in range(0,len(raw),16):
                tag,value=struct.unpack_from(endian+'qQ',raw,i)
                if tag==1:needed.append(name(value))
                elif tag==14:soname=name(value)
        else:
            stride=section[9] or 24
            if stride<24 or len(raw)%stride:raise PackageError('Malformed ELF symbol table')
            for i in range(0,len(raw),stride):
                index=struct.unpack_from(endian+'I',raw,i)[0]
                exported=struct.unpack_from(endian+'H',raw,i+6)[0]!=0
                symbol=name(index)
                if exported and symbol in ('VSTPluginMain','main','GetPluginFactory','clap_entry'):
                    entrypoints.append(symbol)
    versions=sorted(set(m.group().decode() for m in re.finditer(rb'(?:GLIBC|GLIBCXX|CXXABI)_[0-9]+(?:\.[0-9]+)+',payload)))
    return {'format':'ELF','bits':64,'machine':machine,'soname':soname,'needed_libraries':needed,
            'plugin_entrypoints':entrypoints,'abi_version_strings':versions}

def inspect_deb(path, expected_sha256=None):
    path=Path(path)
    if path.stat().st_size>256*1024*1024:raise PackageError('Package exceeds inspection memory limit')
    data=path.read_bytes()
    digest=hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest!=expected_sha256:raise PackageError('Package SHA-256 mismatch')
    members=_members(data)
    report={'sha256':digest,'integrity_verified':expected_sha256 is not None,'control':{},'maintainer_scripts':[],
            'files':[],'elf_files':[],'package_code_executed':False}
    expanded=0
    for name,raw in members.items():
        if not name.startswith(('control.tar','data.tar')):continue
        try:
            with tarfile.open(fileobj=io.BytesIO(raw),mode='r|*') as archive:
                for entry in archive:
                    expanded+=entry.size
                    if expanded>512*1024*1024 or len(report['files'])>100000:raise PackageError('Expanded package exceeds inspection limit')
                    if not entry.isfile():continue
                    stream=archive.extractfile(entry)
                    if name.startswith('control.tar'):
                        key=entry.name.rsplit('/',1)[-1]
                        if key=='control':
                            text=stream.read(128*1024).decode('utf-8')
                            for line in text.splitlines():
                                if ':' in line and not line.startswith((' ','\t')):
                                    field,value=line.split(':',1)
                                    if field in ('Package','Version','Architecture','Pre-Depends','Depends','Recommends','Description','Section'):
                                        report['control'][field]=value.strip()
                        elif key in ('preinst','postinst','prerm','postrm'):
                            report['maintainer_scripts'].append(key)
                    else:
                        report['files'].append({'path':entry.name,'size':entry.size,'mode':entry.mode})
                        head=stream.read(64)
                        if head[:4]==b'\x7fELF':
                            if entry.size>256*1024*1024:raise PackageError('ELF exceeds inspection memory limit')
                            metadata=_elf(head+stream.read())
                            metadata['path']=entry.name
                            report['elf_files'].append(metadata)
        except (tarfile.TarError,UnicodeDecodeError,OSError):
            raise PackageError('Could not inspect package archive') from None
    return report
