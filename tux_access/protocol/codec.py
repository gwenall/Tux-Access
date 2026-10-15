"""Bounded protobuf codec for the types present in the recovered NTK interface.

No message is sent by this module. Unknown fields are skipped, as protobuf
requires. Decoded values use descriptor field names and preserve enum numbers.
"""
import struct
from tux_access.protocol.ntk import fields, varint, message_field, ProtocolError, _read_varint
from tux_access.protocol.schema import SCHEMA

PREFIX = '.ni.ntk.daemon.proto.'
VARINT_TYPES = {'bool', 'enum', 'uint32', 'uint64', 'int64'}

def _schema(name):
    key = name if name.startswith('.') else PREFIX + name
    try:
        return SCHEMA[key]
    except KeyError as exc:
        raise ProtocolError(f'Unknown message schema: {name}') from exc

def _scalar(field, value):
    kind = field['type']
    if kind == 'bool':
        if not isinstance(value, bool):
            raise ValueError(f"{field['name']} must be boolean")
        return 0, varint(int(value))
    if kind in VARINT_TYPES:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field['name']} must be integer")
        lower, upper = {'uint32': (0, 2**32), 'uint64': (0, 2**64),
                        'int64': (-2**63, 2**63), 'enum': (-2**31, 2**31)}[kind]
        if not lower <= value < upper:
            raise ValueError(f"{field['name']} is out of range")
        return 0, varint(value & (2**64 - 1))
    if kind == 'float':
        return 5, struct.pack('<f', value)
    if kind == 'string':
        if not isinstance(value, str):
            raise ValueError(f"{field['name']} must be text")
        return 2, value.encode('utf-8')
    if kind == 'message':
        return 2, encode(field['type_name'], value)
    raise ProtocolError(f'Unsupported schema type: {kind}')

def encode(name, values, *, _depth=0):
    if _depth > 64:
        raise ProtocolError('Message nesting exceeds limit')
    if not isinstance(values, dict):
        raise ValueError('Message values must be a dictionary')
    schema = _schema(name)
    by_name = {field['name']: field for field in schema}
    unknown = set(values) - set(by_name)
    if unknown:
        raise ValueError('Unknown message fields: ' + ', '.join(sorted(unknown)))
    oneofs = set()
    result = bytearray()
    for field in schema:
        key = field['name']
        if key not in values:
            continue
        if 'oneof_index' in field:
            group = field['oneof_index']
            if group in oneofs:
                raise ValueError('Multiple values for oneof group')
            oneofs.add(group)
        repeated = field['label'] == 'repeated'
        items = values[key] if repeated else [values[key]]
        if repeated and not isinstance(items, (tuple, list)):
            raise ValueError(f'{key} must be a list')
        for item in items:
            if field['type'] == 'message':
                wire, payload = 2, encode(field['type_name'], item, _depth=_depth + 1)
            else:
                wire, payload = _scalar(field, item)
            if wire == 2:
                result.extend(message_field(field['number'], payload))
            else:
                result.extend(varint(field['number'] << 3 | wire) + payload)
            if len(result) > 32 * 1024 * 1024:
                raise ProtocolError('Message exceeds size limit')
    return bytes(result)

def _decode_scalar(field, wire, value, depth):
    kind = field['type']
    expected = 0 if kind in VARINT_TYPES else 5 if kind == 'float' else 2
    if wire != expected:
        raise ProtocolError(f"Unexpected wire type for {field['name']}")
    if kind == 'message':
        return decode(field['type_name'], value, _depth=depth + 1)
    if kind == 'string':
        try:
            return value.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ProtocolError('Invalid UTF-8') from exc
    if kind == 'bool':
        return bool(value)
    if kind == 'float':
        return struct.unpack('<f', value)[0]
    if kind == 'int64':
        return value - 2**64 if value >= 2**63 else value
    if kind == 'enum':
        value &= 0xffffffff
        return value - 2**32 if value >= 2**31 else value
    if kind == 'uint32' and value >= 2**32:
        raise ProtocolError('uint32 overflow')
    return value

def decode(name, data, *, _depth=0):
    if _depth > 64:
        raise ProtocolError('Message nesting exceeds limit')
    schema = _schema(name)
    parsed = fields(data)
    result = {}
    for field in schema:
        entries = parsed.get(field['number'], [])
        if field['label'] == 'repeated':
            items = []
            for wire, value in entries:
                if wire == 2 and field['type'] in VARINT_TYPES:
                    position = 0
                    while position < len(value):
                        scalar, position = _read_varint(value, position)
                        items.append(_decode_scalar(field, 0, scalar, _depth))
                elif wire == 2 and field['type'] == 'float':
                    if len(value) % 4:
                        raise ProtocolError('Malformed packed float field')
                    items.extend(struct.unpack('<' + 'f' * (len(value) // 4), value))
                else:
                    items.append(_decode_scalar(field, wire, value, _depth))
            result[field['name']] = items
        elif entries:
            wire, value = entries[-1]
            result[field['name']] = _decode_scalar(field, wire, value, _depth)
    return result
