"""Web Push from the Mac to the phone, with nothing but `cryptography` and urllib.

A home-screen web app on iOS 16.4 or later can receive push notifications. The phone subscribes with
Apple's push service and hands CardCrop the subscription (an endpoint URL and two keys); CardCrop
encrypts each message for that phone (RFC 8291, aes128gcm) and signs the request with its own
VAPID key (RFC 8292), so Apple knows the sender and only the phone can read the message. The Mac is
the sender, so notifications only come while CardCrop is running."""
from __future__ import annotations

import base64
import json
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

SUBJECT = "mailto:push@cardcrop.app"       # VAPID asks for a contact; Apple refuses a request without one


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _hmac(key, data):
    from cryptography.hazmat.primitives import hashes, hmac
    h = hmac.HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize()


class Vapid:
    """CardCrop's push identity: one P-256 key kept beside its certificates."""

    def __init__(self, folder):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, "vapid.key")
        if os.path.exists(p):
            with open(p, "rb") as f:
                self.key = serialization.load_pem_private_key(f.read(), None)
        else:
            self.key = ec.generate_private_key(ec.SECP256R1())
            with open(p, "wb") as f:
                f.write(self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
            os.chmod(p, 0o600)
        self.public = self.key.public_key().public_bytes(serialization.Encoding.X962,
                                                         serialization.PublicFormat.UncompressedPoint)

    @property
    def public_b64(self):
        return b64u(self.public)

    def header(self, endpoint: str) -> str:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        u = urllib.parse.urlsplit(endpoint)
        claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": SUBJECT}
        signing = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "." + \
            b64u(json.dumps(claims, separators=(",", ":")).encode())
        r, s = decode_dss_signature(self.key.sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
        jwt = signing + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        return f"vapid t={jwt}, k={self.public_b64}"


def encrypt(payload: bytes, p256dh: str, auth: str, salt: bytes | None = None) -> bytes:
    """The aes128gcm body for one subscription (one record, as every push message fits in 4 KB)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ua_pub = unb64u(p256dh)
    secret = unb64u(auth)
    salt = salt or os.urandom(16)
    as_key = ec.generate_private_key(ec.SECP256R1())
    as_pub = as_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = as_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    prk_key = _hmac(secret, shared)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_pub + as_pub + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(as_pub)) + as_pub + body


def decrypt(body: bytes, ua_key, auth: str) -> bytes:
    """The phone's side, for the tests: proves a message encrypted here opens with the phone's keys."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, (_, n) = body[:16], struct.unpack("!IB", body[16:21])
    as_pub, ct = body[21:21 + n], body[21 + n:]
    ua_pub = ua_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = _hmac(_hmac(unb64u(auth), shared), b"WebPush: info\x00" + ua_pub + as_pub + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    return AESGCM(cek).decrypt(nonce, ct, None).rstrip(b"\x00")[:-1]


def send(vapid: Vapid, sub: dict, message: dict, ttl=86400, opener=urllib.request.urlopen) -> int:
    """Sends one notification; returns the push service's HTTP status (201 delivered,
    404 or 410 when the phone has unsubscribed, so the subscription should be forgotten)."""
    endpoint = sub["endpoint"]
    keys = sub.get("keys") or {}
    body = encrypt(json.dumps(message, separators=(",", ":")).encode(), keys["p256dh"], keys["auth"])
    req = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "TTL": str(ttl), "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
        "Urgency": "high", "Authorization": vapid.header(endpoint)})
    try:
        with opener(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError):
        return 0
