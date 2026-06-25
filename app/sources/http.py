"""Cliente HTTP minimo (stdlib) que respeta el proxy de salida y su CA."""

import json
import os
import ssl
import urllib.request
import urllib.error

# El proxy de salida re-termina TLS; hay que confiar en su CA si esta presente.
_CA_CANDIDATES = [
    os.environ.get("SSL_CERT_FILE"),
    os.environ.get("REQUESTS_CA_BUNDLE"),
    "/root/.ccr/ca-bundle.crt",
]
_CA = next((p for p in _CA_CANDIDATES if p and os.path.exists(p)), None)
_CTX = ssl.create_default_context(cafile=_CA) if _CA else ssl.create_default_context()

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PatrimonioApp/1.0)",
    "Accept": "application/json,text/plain,*/*",
}


def request(url, method="GET", data=None, headers=None, timeout=25):
    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    # urllib toma el proxy de las variables de entorno (HTTPS_PROXY) automaticamente.
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return resp.status if hasattr(resp, "status") else 200, raw


def get_json(url, headers=None, timeout=25):
    status, raw = request(url, headers=headers, timeout=timeout)
    return status, json.loads(raw) if raw else None


def post_json(url, data, headers=None, timeout=25):
    status, raw = request(url, method="POST", data=data, headers=headers, timeout=timeout)
    return status, json.loads(raw) if raw else None
