"""
A sample application for the Kuberns storage bucket API.

It exists to answer one question: what does it actually take to use a bucket
from your own code? Every endpoint the API offers has a button on the page,
and every call shows the request that went out and the response that came
back, so the page doubles as documentation you can run.

The credential lives here and never reaches the browser. That is not a detail
of this demo - it is how an application should hold it. Anything you put in
page JavaScript is readable by whoever opens the page.

    export KB_ACCESS_KEY_ID=...
    export KB_SECRET=...

    python3 app.py
"""

import base64
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=None)

# The one address every bucket is reached through. It is the same for
# everybody and it is not a secret, so it belongs here rather than in each
# application's configuration - the two things that differ per customer are
# the credential below. Overridable all the same, for pointing at a staging
# gateway.
DEFAULT_GATEWAY = 'https://storage-staging.kuberns.site'

GATEWAY = os.environ.get('KB_GATEWAY_URL', DEFAULT_GATEWAY).rstrip('/')
ACCESS_KEY_ID = os.environ.get('KB_ACCESS_KEY_ID', '')
SECRET = os.environ.get('KB_SECRET', '')

# Long enough for a real upload, short enough that a wrong host does not hang
# the page for a minute.
TIMEOUT_SECONDS = 120

# Responses are shown in full in the page, so a download of any size would
# freeze the browser. Enough to see what came back.
MAX_SHOWN_BYTES = 64 * 1024

# Where a system keeps its CA bundle, when Python's own store is empty.
CA_BUNDLES = (
    '/etc/ssl/cert.pem',                   # macOS, FreeBSD
    '/etc/ssl/certs/ca-certificates.crt',  # Debian, Ubuntu, Alpine
    '/etc/pki/tls/certs/ca-bundle.crt',    # RHEL, Fedora
)


def build_ssl_context():
    """A context that can actually verify the gateway's certificate.

    A Python installed from python.org on macOS ships with an empty trust
    store until someone runs `Install Certificates.command`, and every HTTPS
    call fails with CERTIFICATE_VERIFY_FAILED. Finding a bundle in that one
    case keeps this working without anyone having to know that.

    Verification is never turned off. A sample is read as a recommendation,
    and `verify=False` in one is how it ends up in production.
    """
    context = ssl.create_default_context()

    if context.cert_store_stats().get('x509_ca', 0) > 0:
        return context

    try:
        import certifi
        context.load_verify_locations(certifi.where())
        return context
    except ImportError:
        pass

    for bundle in CA_BUNDLES:
        if os.path.exists(bundle):
            context.load_verify_locations(bundle)
            return context

    app.logger.warning(
        'No trusted CA certificates found, so every HTTPS call will fail. '
        'Run the Python installer\'s "Install Certificates.command", '
        'or pip install certifi.'
    )
    return context


SSL_CONTEXT = build_ssl_context()


def quote_key(key):
    """Path-escape an object key, leaving the slashes that make up folders."""
    return urllib.parse.quote(key, safe='/')


def build_call(op, params):
    """Which request an operation turns into.

    Returns (method, path, query, body, content_type). Grouped the way the API
    is: everything under /buckets manages buckets, everything else is the
    objects inside one.
    """
    bucket = params.get('bucket', '')
    key = params.get('key', '')

    # --- Managing buckets -------------------------------------------------
    if op == 'buckets.list':
        return 'GET', '/buckets', {}, None, None

    if op == 'buckets.create':
        return 'POST', '/buckets', {}, {'name': params.get('name', '')}, 'application/json'

    if op == 'buckets.detail':
        return 'GET', f'/buckets/{bucket}', {}, None, None

    if op == 'buckets.delete':
        return 'DELETE', f'/buckets/{bucket}', {}, None, None

    if op == 'folders.create':
        return ('POST', f'/buckets/{bucket}/folders', {},
                {'folder_path': params.get('folder_path', '')}, 'application/json')

    # --- Sharing one object ----------------------------------------------
    if op == 'visibility.get':
        return 'GET', f'/buckets/{bucket}/visibility', {'key': key}, None, None

    if op == 'visibility.set':
        return ('PUT', f'/buckets/{bucket}/visibility', {},
                {'object_key': key, 'visibility': params.get('visibility', 'private')},
                'application/json')

    if op == 'url.get':
        return ('POST', f'/buckets/{bucket}/url', {},
                {'object_key': key}, 'application/json')

    # --- The objects themselves -------------------------------------------
    if op == 'objects.list':
        query = {}
        if params.get('prefix'):
            query['prefix'] = params['prefix']
        if params.get('token'):
            query['token'] = params['token']
        return 'GET', f'/{bucket}', query, None, None

    if op == 'objects.put':
        if params.get('content_b64'):
            body = base64.b64decode(params['content_b64'])
        else:
            body = params.get('content', '').encode('utf-8')
        return ('PUT', f'/{bucket}/{quote_key(key)}', {}, body,
                params.get('content_type') or 'application/octet-stream')

    if op == 'objects.get':
        return 'GET', f'/{bucket}/{quote_key(key)}', {}, None, None

    if op == 'objects.head':
        return 'HEAD', f'/{bucket}/{quote_key(key)}', {}, None, None

    if op == 'objects.delete':
        return 'DELETE', f'/{bucket}/{quote_key(key)}', {}, None, None

    raise ValueError(f'Unknown operation: {op}')


def call_gateway(op, params):
    """Make the call and report everything about it."""
    method, path, query, body, content_type = build_call(op, params)

    url = GATEWAY + path
    if query:
        url += '?' + urllib.parse.urlencode(query)

    payload = json.dumps(body).encode('utf-8') if isinstance(body, dict) else body
    outgoing = urllib.request.Request(url, data=payload, method=method)

    # The credential travels as HTTP Basic auth: the key id is the username
    # and the secret is the password. Any HTTP client can do this, which is
    # the point - there is no SDK to install.
    token = base64.b64encode(f'{ACCESS_KEY_ID}:{SECRET}'.encode()).decode()
    outgoing.add_header('Authorization', f'Basic {token}')

    if content_type:
        outgoing.add_header('Content-Type', content_type)

    shown = {
        'method': method,
        'url': url,
        'body': body if isinstance(body, dict) else (
            f'<{len(payload)} bytes>' if payload else None
        ),
    }

    try:
        with urllib.request.urlopen(
            outgoing, timeout=TIMEOUT_SECONDS, context=SSL_CONTEXT
        ) as response:
            return {
                'request': shown,
                'status': response.status,
                'headers': dict(response.headers),
                'body': decode(response.read(MAX_SHOWN_BYTES)),
            }

    except urllib.error.HTTPError as e:
        # Not an exception as far as this page is concerned. A 403 or a 404 is
        # an answer, and seeing it is the whole point.
        return {
            'request': shown,
            'status': e.code,
            'headers': dict(e.headers),
            'body': decode(e.read(MAX_SHOWN_BYTES)),
        }

    except Exception as e:
        return {
            'request': shown,
            'status': 0,
            'headers': {},
            'body': f'Could not reach the gateway: {e}',
        }


def decode(raw):
    if not raw:
        return ''
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return f'<{len(raw)} bytes of binary>'


@app.get('/')
def page():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'index.html')


@app.get('/healthz')
def healthz():
    """Enough for a platform health check to see the app is up, and to say
    whether it has been given what it needs to be useful."""
    return jsonify({
        'status': 'ok',
        'gateway': GATEWAY or None,
        'credential_configured': bool(ACCESS_KEY_ID and SECRET),
    })


@app.post('/call')
def call():
    if not (ACCESS_KEY_ID and SECRET):
        return jsonify({
            'request': {'method': '-', 'url': '-', 'body': None},
            'status': 0,
            'headers': {},
            'body': 'Set KB_ACCESS_KEY_ID and KB_SECRET, then restart.',
        })

    payload = request.get_json(silent=True) or {}
    return jsonify(call_gateway(payload.get('op', ''), payload.get('params', {})))


if __name__ == '__main__':
    # Local use only. On a server this is started by gunicorn, which is what
    # the Procfile says.
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '8000')))
