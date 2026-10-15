"""Independent, read-only NTK protobuf subset. No NI source or dependencies.

Field mapping observed in Native Access 3.26.0 Windows package. Linux daemon
compatibility is unverified. Transport requires optional package pyzmq.
"""
from urllib.parse import urlsplit

PROTOCOL_VERSION = (8, 1, 4)


class ProtocolError(RuntimeError):
    pass


def varint(value):
    if not isinstance(value, int) or not 0 <= value < 2**64:
        raise ValueError("Expected unsigned 64-bit integer")
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _read_varint(data, position):
    value = 0
    for shift in range(0, 70, 7):
        if position >= len(data):
            raise ProtocolError("Truncated varint")
        byte = data[position]
        position += 1
        value |= (byte & 127) << shift
        if byte < 128:
            if value >= 2**64:
                raise ProtocolError("Varint overflow")
            return value, position
    raise ProtocolError("Varint overflow")


def message_field(number, payload):
    return varint((number << 3) | 2) + varint(len(payload)) + payload


def fields(data):
    """Parse ordinary protobuf wire fields with strict bounds checking."""
    if len(data) > 32 * 1024 * 1024:
        raise ProtocolError("Message exceeds 32 MiB limit")
    position = 0
    result = {}
    while position < len(data):
        tag, position = _read_varint(data, position)
        number, wire = tag >> 3, tag & 7
        if not 1 <= number < 2**29:
            raise ProtocolError("Invalid field number")
        if wire == 0:
            value, position = _read_varint(data, position)
        elif wire in (1, 2, 5):
            if wire == 2:
                size, position = _read_varint(data, position)
            else:
                size = 8 if wire == 1 else 4
            if size > len(data) - position:
                raise ProtocolError("Truncated field")
            value = data[position:position + size]
            position += size
        else:
            raise ProtocolError("Unsupported protobuf wire type")
        result.setdefault(number, []).append((wire, value))
    return result


def _get(parsed, number, wire, default):
    entries = parsed.get(number)
    if not entries:
        return default
    actual, value = entries[-1]
    if actual != wire:
        raise ProtocolError("Unexpected field wire type")
    return value


def _text(parsed, number, default=""):
    try:
        return _get(parsed, number, 2, default.encode()).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProtocolError("Invalid UTF-8") from error


def _version(data, build=False):
    parsed = fields(data)
    result = {name: _get(parsed, n, 0, 0)
              for n, name in enumerate(("major", "minor", "micro"), 1)}
    if build:
        result["build"] = _text(parsed, 4)
    return result


def encode_request(name):
    request_fields = {"ping": 7, "version": 71, "known_products": 47}
    if name not in request_fields:
        raise ValueError("Only ping, version and known_products are supported")
    version = b"".join(varint(n << 3) + varint(v)
                       for n, v in enumerate(PROTOCOL_VERSION, 1))
    return message_field(1, message_field(1, version)) + message_field(request_fields[name], b"")


def _product(data):
    parsed = fields(data)
    product = {"upid": _text(parsed, 1), "title": _text(parsed, 3),
               "company": _text(parsed, 25), "vendor": _text(parsed, 26)}
    for number, name in ((2, "isPlayer"), (7, "installed"), (8, "updateable"),
                         (12, "isOwned"), (14, "isLocatable"), (15, "isInstallable"),
                         (20, "isUninstallable")):
        product[name] = bool(_get(parsed, number, 0, 0))
    for number, name in ((6, "installedSize"), (11, "activationState"),
                         (13, "targetSize"), (17, "installationSource"), (19, "type")):
        product[name] = _get(parsed, number, 0, 0)
    for number, name in ((4, "installedVersion"), (5, "targetVersion")):
        if number in parsed:
            product[name] = _version(_get(parsed, number, 2, b""))
    if 22 in parsed:
        product['binaryPath'] = _text(parsed, 22)
    product['components'] = []
    for wire, value in parsed.get(16, []):
        if wire != 2:
            raise ProtocolError('Invalid component field')
        component = fields(value)
        product['components'].append({
            'name': _get(component, 1, 0, 0),
            'currentPath': _text(component, 2),
            'isBroken': bool(_get(component, 3, 0, 0)),
        })
    product["platforms"] = []
    for wire, value in parsed.get(28, []):
        if wire != 2:
            raise ProtocolError("Invalid platform field")
        product["platforms"].append(value.decode("utf-8"))
    if 32 in parsed:
        members = fields(_get(parsed, 32, 2, b''))
        product['bundleMembers'] = []
        for wire, value in members.get(1, []):
            if wire != 2:
                raise ProtocolError('Invalid bundle member field')
            member = fields(value)
            product['bundleMembers'].append({'upid': _text(member, 1), 'title': _text(member, 2)})
    return product


def decode_response(data, name):
    parsed = fields(data)
    if 2 in parsed:
        error = fields(_get(parsed, 2, 2, b""))
        raise ProtocolError("Daemon error %s: %s" % (_get(error, 1, 0, 0), _text(error, 2)))
    if 1 in parsed:
        header = fields(_get(parsed, 1, 2, b""))
        if 1 in header:
            version = _version(_get(header, 1, 2, b""))
            if version["major"] != PROTOCOL_VERSION[0]:
                raise ProtocolError("Incompatible daemon protocol major version")
    expected = {"ping": 3, "version": 72, "known_products": 48}[name]
    if expected not in parsed:
        raise ProtocolError("Expected response field is absent")
    payload = _get(parsed, expected, 2, b"")
    if name == "ping":
        return {"ok": True}
    if name == "version":
        return _version(payload, build=True)
    products = fields(payload)
    result = []
    for wire, value in products.get(1, []):
        if wire != 2:
            raise ProtocolError("Invalid product field")
        result.append(_product(value))
    return {"knownProducts": result}


class NtkClient:
    """Read-only client for a loopback NTK daemon; sockets live per request."""
    def __init__(self, endpoint="tcp://127.0.0.1:5146", timeout_ms=1500):
        address = urlsplit(endpoint)
        if address.scheme != "tcp" or address.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Only loopback TCP endpoints are allowed")
        if not address.port or address.path or address.query or address.fragment or address.username:
            raise ValueError("Invalid daemon endpoint")
        if not isinstance(timeout_ms, int) or not 1 <= timeout_ms <= 60000:
            raise ValueError("Timeout must be 1..60000 milliseconds")
        try:
            import zmq
        except ImportError as error:
            raise RuntimeError("Daemon probes require optional dependency pyzmq") from error
        self._zmq = zmq
        self._context = zmq.Context()
        self.endpoint, self.timeout_ms = endpoint, timeout_ms

    def _exchange(self, payload):
        if self._context is None:
            raise RuntimeError("Client is closed")
        socket = self._context.socket(self._zmq.REQ)
        try:
            socket.setsockopt(self._zmq.LINGER, 0)
            socket.setsockopt(self._zmq.SNDTIMEO, self.timeout_ms)
            socket.setsockopt(self._zmq.RCVTIMEO, self.timeout_ms)
            socket.setsockopt(self._zmq.MAXMSGSIZE, 32 * 1024 * 1024)
            socket.connect(self.endpoint)
            socket.send(payload)
            frames = socket.recv_multipart()
            if len(frames) != 1:
                raise ProtocolError("Unexpected multipart daemon reply")
            return frames[0]
        except self._zmq.Again as error:
            raise TimeoutError("NTK daemon did not respond before timeout") from error
        finally:
            socket.close()

    def _request(self, name):
        return decode_response(self._exchange(encode_request(name)), name)

    def inspect(self, operation):
        """Read complete descriptor-backed messages for three allowlisted queries."""
        from tux_access.protocol.codec import encode, decode
        queries = {
            'preferences': ('get_preferences_request', 'get_preferences_response'),
            'deployments': ('active_deployments_request', 'active_deployments_response'),
            'catalog': ('known_products_request', 'known_products_response'),
        }
        if operation not in queries:
            raise ValueError('Only preferences, deployments and catalog can be inspected')
        request, response = queries[operation]
        envelope = {'header': {'version': dict(zip(('major', 'minor', 'micro'), PROTOCOL_VERSION))}, request: {}}
        decoded = decode('NtkMessage', self._exchange(encode('NtkMessage', envelope)))
        if 'error_response' in decoded:
            error = decoded['error_response']
            raise ProtocolError(f"Daemon error {error.get('type', 0)}: {error.get('message', '')}")
        if response not in decoded:
            raise ProtocolError('Expected response field is absent')
        version = decoded.get('header', {}).get('version', {})
        if version and version.get('major', 0) != PROTOCOL_VERSION[0]:
            raise ProtocolError('Incompatible daemon protocol major version')
        return decoded[response]

    def ping(self):
        return self._request("ping")

    def version(self):
        return self._request("version")

    def known_products(self):
        return self._request("known_products")

    def close(self):
        if self._context is not None:
            self._context.term()
            self._context = None
