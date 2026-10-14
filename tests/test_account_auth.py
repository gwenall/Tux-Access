import sys,json
import account_auth as auth
import unittest
from urllib.parse import parse_qs,urlsplit
class AuthTests(unittest.TestCase):
 def test_rfc7636_vector(self):
  self.assertEqual(auth.pkce_challenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'),'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')
 def test_roundtrip_mock_provider(self):
  verifier=auth.new_verifier(); state='s'*32
  url=auth.authorize_url(verifier,state)
  query=parse_qs(urlsplit(url).query)
  self.assertEqual(query['code_challenge_method'],['S256'])
  callback=auth.BROWSER_REDIRECT+'?code=mock-code&state='+state
  code=auth.callback_code(callback,state)
  def provider(method,url,headers,body):
   self.assertEqual(method,'POST'); self.assertEqual(url,auth.AUTH_ORIGIN+'/oauth/token')
   request=parse_qs(body.decode())
   self.assertEqual(request['grant_type'],['authorization_code'])
   self.assertEqual(request['code'],['mock-code'])
   self.assertEqual(auth.pkce_challenge(request['code_verifier'][0]),query['code_challenge'][0])
   return {'access_token':'mock-token','token_type':'Bearer'}
  self.assertEqual(auth.exchange_code(code,verifier,provider)['token_type'],'Bearer')
 def test_untrusted_callbacks(self):
  for url in (auth.BROWSER_REDIRECT+'.evil?code=x&state='+'s'*32,auth.BROWSER_REDIRECT+'?code=x&state=wrong',auth.APP_REDIRECT+'?code=x&state='+'s'*32,auth.BROWSER_REDIRECT+'?code=x&code=y&state='+'s'*32):
   with self.assertRaises(ValueError):auth.callback_code(url,'s'*32)
 def test_origin_before_transport(self):
  def transport(*args):self.fail('transport called')
  for origin in ('http://auth.native-instruments.com','https://auth.native-instruments.com.evil','https://auth.native-instruments.com@evil','https://auth.native-instruments.com/evil'):
   with self.assertRaises(ValueError):auth.exchange_code('mock','a'*43,transport,origin=origin)
 def test_provider_errors_redacted(self):
  with self.assertRaisesRegex(RuntimeError,'^Token exchange failed$'):
   auth.exchange_code('mock','a'*43,lambda *args:{'error':'secret error'})
if __name__=='__main__':unittest.main()
