import io
import json
import unittest
from email.message import Message
from urllib.error import HTTPError
from auth_transport import AuthHttpTransport, AuthTransportError, refresh_token
from account_auth import AUTH_ORIGIN

class Response(io.BytesIO):
    def __init__(self,payload,kind='application/json'):
        super().__init__(payload)
        self.status=200
        self.headers=Message()
        self.headers['Content-Type']=kind

class Opener:
    def __init__(self,result): self.result=result; self.calls=[]
    def open(self,request,timeout):
        self.calls.append(request)
        if isinstance(self.result,Exception): raise self.result
        return self.result

class TransportTests(unittest.TestCase):
    def test_credentials_are_not_sent_to_untrusted_target(self):
        transport=AuthHttpTransport()
        transport.opener=Opener(Response(b'{}'))
        for url in ('https://example.com/oauth/token','http://auth.native-instruments.com/oauth/token','https://auth.native-instruments.com/oauth/token?next=x'):
            with self.assertRaises(AuthTransportError): transport('POST',url,{},b'private')
        self.assertEqual(transport.opener.calls,[])

    def test_response_validation_and_oversize(self):
        for response in (Response(b'{'),Response(b'[]'),Response(b'{}','text/html'),Response(b'x'*(1024*1024+1)),Response(b'{"error":"secret should never be logged"}')):
            transport=AuthHttpTransport(); transport.opener=Opener(response)
            with self.assertRaises(AuthTransportError) as exc:
                transport('POST',AUTH_ORIGIN+'/oauth/token',{},b'grant_type=x')
            self.assertNotIn('secret',str(exc.exception))

    def test_success_and_provider_error_redaction(self):
        transport=AuthHttpTransport(); transport.opener=Opener(Response(b'{"access_token":"test-token"}'))
        self.assertEqual(transport('POST',AUTH_ORIGIN+'/oauth/token',{},b'x=1')['access_token'],'test-token')
        transport.opener=Opener(HTTPError('sensitive-url',401,'sensitive-reason',{},None))
        with self.assertRaisesRegex(AuthTransportError,'HTTP 401') as exc:
            transport('POST',AUTH_ORIGIN+'/oauth/token',{},b'x=1')
        self.assertNotIn('sensitive',str(exc.exception))

    def test_refresh_uses_explicit_transport_and_checks_token(self):
        seen=[]
        def transport(method,url,headers,body):
            seen.append(body)
            return {'access_token':'new-test-token'}
        self.assertEqual(refresh_token('test refresh',transport)['access_token'],'new-test-token')
        self.assertIn(b'grant_type=refresh_token',seen[0])
        with self.assertRaises(AuthTransportError): refresh_token('test',lambda *_:{})

if __name__ == '__main__': unittest.main()
