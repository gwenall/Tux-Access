import struct
import unittest
from schema_codec import encode, decode
from ntk_protocol import encode_request, message_field, ProtocolError

class SchemaCodecTests(unittest.TestCase):
    def test_reference_requests_match_observed_subset(self):
        header = {'version': {'major':8,'minor':1,'micro':4}}
        for operation,field in [('ping','daemon_ping_request'), ('version','daemon_version_request'), ('known_products','known_products_request')]:
            self.assertEqual(encode('NtkMessage', {'header':header,field:{}}), encode_request(operation))

    def test_known_component_fixture_and_unknown_field(self):
        wire = bytes.fromhex('0802120d2f746573742f636f6e74656e741801') + message_field(100,b'unknown')
        self.assertEqual(decode('Component',wire), {'name':2,'current_path':'/test/content','is_broken':True})

    def test_nested_catalog_fixture(self):
        product = message_field(3,b'Sample') + message_field(16,b'\x08\x01')
        response = message_field(48,message_field(1,product))
        result=decode('NtkMessage',response)['known_products_response']['known_products'][0]
        self.assertEqual(result['title'],'Sample')
        self.assertEqual(result['components'],[{'name':1}])

    def test_float_and_signed_enum(self):
        wire = b'\x25' + struct.pack('<f',0.5) + b'\x28' + b'\xff'*9+b'\x01'
        decoded=decode('Deployment',wire)
        self.assertEqual(decoded['progress'],0.5)
        self.assertEqual(decoded['state'],-1)

    def test_bounds_unknown_inputs_and_nested_type(self):
        for wire in (b'\x12\xff',b'\x08\xff',b'\x0a\x01x'):
            with self.assertRaises(ProtocolError): decode('Component',wire)
        with self.assertRaises(ValueError): encode('Component',{'current_path':123})
        with self.assertRaises(ValueError): encode('Component',{'extra':'x'})
        with self.assertRaises(ValueError): encode('Component',{'name':2**32})

    def test_readonly_query_encoding(self):
        header={'version':{'major':8,'minor':1,'micro':4}}
        self.assertEqual(encode('NtkMessage',{'header':header,'get_preferences_request':{}}).hex(),'0a080a060808100118048a0300')
        with self.assertRaises(ValueError): encode('NtkMessage',{'known_products_request':{},'daemon_ping_request':{}})

if __name__ == '__main__': unittest.main()
