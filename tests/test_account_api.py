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

    def test_invalid_tokens_rejected_before_http(self):
        for token in ('','x\r\nInjected: y',None):
            with self.assertRaises(ValueError): http_catalog(token)

if __name__ == '__main__': unittest.main()
