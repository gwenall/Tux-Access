import unittest
from account_api import catalog, AccountApiError, http_catalog

class AccountApiTests(unittest.TestCase):
    def test_observed_envelope_and_private_field_exclusion(self):
        fixture={'response_head':{'status':'OK'},'response_body':{'products':[
            {'upid':'test','licensedproduct_title':'Sample','serialnumber':'private-serial',
             'manufacturer_title':'Vendor','locked':False,'subscribed':False,'type':'product'}]}}
        result=catalog('test-token',lambda _:fixture)
        self.assertEqual(result['products'][0]['title'],'Sample')
        self.assertNotIn('serialnumber',repr(result))
        self.assertNotIn('installed',result['products'][0])
        self.assertNotIn('test-token',repr(result))

    def test_reject_unexpected_or_failed_envelopes(self):
        for response in ({},{'response_head':{'status':'FAILED'},'response_body':{'products':[]}},
                         {'response_head':{'status':'OK'},'response_body':{'products':[1]}}):
            with self.assertRaises(AccountApiError): catalog('token',lambda _:response)

    def test_m32_maschine_entitlement_uses_its_shared_installer_identity(self):
        response = {'response_head': {'status': 'OK'}, 'response_body': {'products': [
            {'upid': 'fccc863c-324f-4d79-af7e-b38c1f7488fe',
             'licensedproduct_title': 'Maschine 2 Essentials Application for M32'},
            {'upid': 'unrelated', 'licensedproduct_title': 'Maschine 2 Factory Selection'}]}}
        products = catalog('token', lambda _: response)['products']
        self.assertEqual(products[0]['title'], 'Maschine 2')
        self.assertEqual(products[0]['entitlementTitle'], 'Maschine 2 Essentials Application for M32')
        self.assertEqual(products[1]['title'], 'Maschine 2 Factory Selection')

    def test_invalid_tokens_rejected_before_http(self):
        for token in ('','x\r\nInjected: y',None):
            with self.assertRaises(ValueError): http_catalog(token)

if __name__ == '__main__': unittest.main()
