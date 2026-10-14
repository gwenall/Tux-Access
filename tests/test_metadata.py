import unittest
from ntk_protocol import decode_response, message_field, ProtocolError
from launcher import product_values

class MetadataTests(unittest.TestCase):
    def test_components_and_binary_path(self):
        component = b'\x08\x02' + message_field(2, b'/test/content') + b'\x18\x01'
        product = message_field(3, b'Test') + message_field(16, component) + message_field(22, b'/test/app')
        result = decode_response(message_field(48, message_field(1, product)), 'known_products')['knownProducts'][0]
        self.assertEqual(result['binaryPath'], '/test/app')
        self.assertEqual(result['components'], [{'name': 2, 'currentPath': '/test/content', 'isBroken': True}])

    def test_invalid_component_wire_type(self):
        with self.assertRaises(ProtocolError):
            decode_response(message_field(48, message_field(1, b'\x80\x01\x01')), 'known_products')

    def test_product_types_from_descriptor(self):
        self.assertEqual(product_values({'type': 2})[2], 'Content')
        self.assertEqual(product_values({'type': 3})[2], 'Plug-in')
        self.assertEqual(product_values({'type': 99})[2], 'Type 99')

if __name__ == '__main__':
    unittest.main()
