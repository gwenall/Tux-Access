import sys
import unittest
from tux_access.protocol.ntk import *


class CodecTests(unittest.TestCase):
    def test_observed_request_bytes(self):
        self.assertEqual(encode_request('ping').hex(), '0a080a060808100118043a00')
        self.assertEqual(encode_request('version').hex(), '0a080a06080810011804ba0400')
        self.assertEqual(encode_request('known_products').hex(), '0a080a06080810011804fa0200')

    def test_realistic_response_shapes(self):
        self.assertEqual(decode_response(b'\x1a\x00', 'ping'), {'ok': True})
        version = message_field(72, b'\x08\x01\x10\x20\x22\x01' + b'0')
        self.assertEqual(decode_response(version, 'version'),
                         {'major': 1, 'minor': 32, 'micro': 0, 'build': '0'})
        product = message_field(1, b'ID') + message_field(3, b'Test') + b'\x38\x01'
        reply = message_field(48, message_field(1, product))
        decoded = decode_response(reply, 'known_products')['knownProducts'][0]
        self.assertEqual(decoded['title'], 'Test')
        self.assertTrue(decoded['installed'])
        self.assertFalse(decoded['isOwned'])

    def test_malformed_bounds_and_wire(self):
        for data in (b'\x80', b'\x0a\xff\x01', b'\x00', b'\x0b', b'\xff' * 11):
            with self.assertRaises(ProtocolError):
                fields(data)

    def test_errors_and_version_rejected(self):
        with self.assertRaisesRegex(ProtocolError, 'Daemon error 1: denied'):
            decode_response(message_field(2, b'\x08\x01' + message_field(2, b'denied')), 'ping')
        incompatible = message_field(1, message_field(1, b'\x08\x09')) + b'\x1a\x00'
        with self.assertRaisesRegex(ProtocolError, 'Incompatible'):
            decode_response(incompatible, 'ping')
        with self.assertRaises(ProtocolError):
            decode_response(b'', 'ping')

    def test_unsigned_integer_limits(self):
        for value in (0, 127, 128, 2**64 - 1):
            self.assertEqual(fields(b'\x08' + varint(value))[1], [(0, value)])
        for value in (-1, 2**64):
            with self.assertRaises(ValueError):
                varint(value)


if __name__ == '__main__':
    unittest.main()
