"""Native NI account catalog HTTP adapter, verified against an existing session.

Account records are not the daemon's expanded installed-product catalog.
Tokens are provided by the caller, used transiently and never persisted here.
"""
import json
import urllib.request
import urllib.error

ORIGIN = 'https://api.native-instruments.com'
PRODUCTS_PATH = '/v1/users/me/products?include_subscriptions=true'
# NI uses the same public installer identity for this keyboard entitlement
# and the Maschine standalone. Display the application name so its validated
# installation merges with the account row instead of becoming a duplicate.
APPLICATION_TITLES = {'fccc863c-324f-4d79-af7e-b38c1f7488fe': 'Maschine 2'}

class AccountApiError(RuntimeError):
    pass

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AccountApiError('Account API redirect rejected')

def _get_json(token, path):
    if not isinstance(token,str) or not token or len(token)>32768 or '\n' in token or '\r' in token:
        raise ValueError('Invalid access token')
    opener=urllib.request.build_opener(_NoRedirect())
    if path not in (PRODUCTS_PATH, '/v2/download/me/full-products'):
        raise AccountApiError('Unrecognized account API path')
    request=urllib.request.Request(ORIGIN+path,
        headers={'Authorization':'Bearer '+token,'Accept':'application/json'},method='GET')
    try:
        with opener.open(request,timeout=20) as response:
            if response.status!=200 or response.headers.get_content_type()!='application/json':
                raise AccountApiError('Unexpected account API response')
            payload=response.read(8*1024*1024+1)
            if len(payload)>8*1024*1024:
                raise AccountApiError('Account response exceeded limit')
            return json.loads(payload.decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise AccountApiError(f'Account API rejected request (HTTP {exc.code})') from None
    except (urllib.error.URLError,OSError,UnicodeDecodeError,ValueError):
        raise AccountApiError('Could not read a valid account response') from None

def http_catalog(token):
    return _get_json(token, PRODUCTS_PATH)

def http_downloads(token):
    return _get_json(token, '/v2/download/me/full-products')

def catalog(token, transport=http_catalog):
    """Return account product metadata without serial numbers or session tokens."""
    payload=transport(token)
    if not isinstance(payload,dict) or not isinstance(payload.get('response_head'),dict):
        raise AccountApiError('Invalid account response envelope')
    if payload['response_head'].get('status')!='OK':
        raise AccountApiError('Account API returned an unsuccessful result')
    body=payload.get('response_body')
    if not isinstance(body,dict) or not isinstance(body.get('products'),list):
        raise AccountApiError('Account response contains no product list')
    products=[]
    for row in body['products']:
        if not isinstance(row,dict):
            raise AccountApiError('Invalid account product record')
        product={'source':'account-api','status':'Account record'}
        for source,target in (('upid','upid'),('licensedproduct_title','title'),
                              ('manufacturer_title','vendor'),('licensedproduct_id','accountProductId'),
                              ('locked','locked'),('subscribed','subscribed'),('type','accountType')):
            if source in row:
                product[target]=row[source]
        if product.get('upid') in APPLICATION_TITLES:
            product['entitlementTitle'] = product.get('title', '')
            product['title'] = APPLICATION_TITLES[product['upid']]
        products.append(product)
    return {'products':products}
