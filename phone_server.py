"""CardCrop's phone console, the network side: a small HTTPS and WebSocket server, run on background
threads with nothing but the standard library, and the certificates that let an iPhone trust it.

Why HTTPS on a home network: iOS gives a web page the phone's motion sensors (the 3D card's gyro)
only on a secure page, and a secure page needs a certificate the phone trusts. So CardCrop makes its
own small certificate authority, once, kept in its data folder; the phone installs that authority
once (a profile download from the plain-HTTP setup page, then a switch in Settings), and every
certificate CardCrop signs after that is trusted, including new ones when the Mac's address changes.

Two ports: HTTPS on 8743 for the console, its pictures and its WebSocket (/ws), and plain HTTP on
8744 only for the setup page and the certificate download, since the phone cannot reach HTTPS
before it trusts the authority. Nothing here touches the window: requests that need the app are
handed to it through the callbacks the app gives (see phone_link.py), which run on the UI thread."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import http.server
import ipaddress
import json
import os
import queue
import socket
import ssl
import struct
import threading
import urllib.parse

HTTPS_PORT, HTTP_PORT = 8743, 8744
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ------------------------------------------------------------------ addresses and certificates
def lan_addresses() -> list[str]:
    """The Mac's addresses on the local network, the one with the default route first."""
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))              # no packet is sent; it only picks the interface
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    except OSError:
        pass
    return out or ["127.0.0.1"]


def host_name() -> str:
    """The Mac's Bonjour name (what iPhones resolve on the local network), e.g. anthonys-mbp.local."""
    import subprocess
    import sys
    if sys.platform == "darwin":
        try:
            r = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip() + ".local"
        except (OSError, subprocess.SubprocessError):
            pass
    h = socket.gethostname().split(".")[0]
    return f"{h}.local"


TAILSCALE_CLI = ("/Applications/Tailscale.app/Contents/MacOS/Tailscale", "tailscale")


def tailscale() -> dict:
    """{ip, name} of this Mac on your Tailscale network, or {} without Tailscale. The name is the
    MagicDNS one (mac.tailnet-1234.ts.net), which keeps working wherever the phone and the Mac are."""
    import shutil
    import subprocess
    out = {}
    try:                                        # the route to Tailscale's own resolver picks its address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("100.100.100.100", 53))
        ip = s.getsockname()[0]
        s.close()
        if ipaddress.ip_address(ip) in ipaddress.ip_network("100.64.0.0/10"):
            out["ip"] = ip
    except OSError:
        pass
    for cli in TAILSCALE_CLI:
        path = cli if os.path.isabs(cli) and os.path.exists(cli) else shutil.which(cli)
        if not path:
            continue
        try:
            r = subprocess.run([path, "status", "--json"], capture_output=True, text=True, timeout=4)
            me = json.loads(r.stdout or "{}").get("Self") or {}
            name = (me.get("DNSName") or "").rstrip(".")
            ips = [i for i in me.get("TailscaleIPs") or [] if ":" not in i]
            if name:
                out["name"] = name
            if ips:
                out["ip"] = ips[0]
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        break
    return out


def ensure_certificates(folder: str, ips: list[str], names: list[str] | None = None) -> tuple[str, str, str]:
    """(ca.pem, server.pem, server.key) in folder: the authority made once, the server certificate
    made again whenever the Mac's addresses change or it nears expiry."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    os.makedirs(folder, exist_ok=True)
    ca_pem, ca_key_p = os.path.join(folder, "ca.pem"), os.path.join(folder, "ca.key")
    srv_pem, srv_key_p = os.path.join(folder, "server.pem"), os.path.join(folder, "server.key")
    now = dt.datetime.now(dt.timezone.utc)

    def save_key(k, p):
        with open(p, "wb") as f:
            f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
        os.chmod(p, 0o600)

    if not (os.path.exists(ca_pem) and os.path.exists(ca_key_p)):
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"CardCrop on {host_name()}"),
                          x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CardCrop")])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
                .not_valid_after(now + dt.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                             content_commitment=False, key_encipherment=False,
                                             data_encipherment=False, key_agreement=False,
                                             encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .sign(key, hashes.SHA256()))
        save_key(key, ca_key_p)
        with open(ca_pem, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        for p in (srv_pem, srv_key_p):                # a new authority: the old server cert goes too
            if os.path.exists(p):
                os.remove(p)
    with open(ca_pem, "rb") as f:
        ca = x509.load_pem_x509_certificate(f.read())
    with open(ca_key_p, "rb") as f:
        ca_key = serialization.load_pem_private_key(f.read(), None)

    want = sorted(set(ips) | {"127.0.0.1"})
    want_names = sorted({host_name(), "localhost"} | set(names or []))
    fresh = False
    if os.path.exists(srv_pem) and os.path.exists(srv_key_p):
        with open(srv_pem, "rb") as f:
            cur = x509.load_pem_x509_certificate(f.read())
        try:
            san = cur.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            have = sorted(str(a) for a in san.get_values_for_type(x509.IPAddress))
            have_names = sorted(san.get_values_for_type(x509.DNSName))
        except x509.ExtensionNotFound:
            have, have_names = [], []
        fresh = have == want and have_names == want_names and cur.not_valid_after_utc - now > dt.timedelta(days=30)
    if not fresh:
        key = ec.generate_private_key(ec.SECP256R1())
        names = [x509.DNSName(n) for n in want_names] + \
                [x509.IPAddress(ipaddress.ip_address(i)) for i in want]
        cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host_name())]))
                .issuer_name(ca.subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
                .not_valid_after(now + dt.timedelta(days=397))       # Apple's limit for server certificates
                .add_extension(x509.SubjectAlternativeName(names), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, key_cert_sign=False,
                                             crl_sign=False, content_commitment=False, data_encipherment=False,
                                             key_agreement=True, encipher_only=False, decipher_only=False),
                               critical=True)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .sign(ca_key, hashes.SHA256()))
        save_key(key, srv_key_p)
        with open(srv_pem, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
    return ca_pem, srv_pem, srv_key_p


def ca_der(ca_pem: str) -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    with open(ca_pem, "rb") as f:
        return x509.load_pem_x509_certificate(f.read()).public_bytes(serialization.Encoding.DER)


def ca_profile(ca_pem: str) -> bytes:
    """The authority wrapped as an unsigned iOS configuration profile (a root certificate payload).
    Its identifiers derive from the certificate, so installing it again replaces it rather than
    adding a second copy."""
    import plistlib
    import uuid
    der = ca_der(ca_pem)
    h = hashlib.sha256(der).hexdigest()
    profile = {
        "PayloadType": "Configuration", "PayloadVersion": 1,
        "PayloadIdentifier": f"app.cardcrop.ca.{h[:12]}", "PayloadUUID": str(uuid.UUID(h[:32])),
        "PayloadDisplayName": "CardCrop", "PayloadOrganization": "CardCrop",
        "PayloadDescription": "Lets this iPhone trust CardCrop on your Mac, so its phone console can use the "
                              "motion sensors and notifications. It trusts nothing else.",
        "PayloadContent": [{
            "PayloadType": "com.apple.security.root", "PayloadVersion": 1,
            "PayloadIdentifier": f"app.cardcrop.ca.{h[:12]}.cert", "PayloadUUID": str(uuid.UUID(h[32:64])),
            "PayloadDisplayName": "CardCrop certificate authority", "PayloadCertificateFileName": "CardCrop.cer",
            "PayloadContent": der}],
    }
    return plistlib.dumps(profile)


# ------------------------------------------------------------------ WebSocket connections
class WsConn:
    """One phone's live connection: frames read on its handler thread, writes from a queue on a writer
    thread, so the app can send from anywhere without waiting on the network."""

    def __init__(self, sock, peer):
        self.sock, self.peer = sock, peer
        self.q = queue.Queue(maxsize=64)
        self.alive = True
        self.token = None
        self.wants_frames = False
        self.w = threading.Thread(target=self._writer, daemon=True)
        self.w.start()

    def _frame(self, op, data: bytes) -> bytes:
        n = len(data)
        head = bytes([0x80 | op])
        if n < 126:
            head += bytes([n])
        elif n < 65536:
            head += bytes([126]) + struct.pack("!H", n)
        else:
            head += bytes([127]) + struct.pack("!Q", n)
        return head + data

    def send_json(self, obj):
        self._put(self._frame(1, json.dumps(obj, separators=(",", ":")).encode()))

    def send_binary(self, data: bytes, droppable=True):
        if droppable and self.q.qsize() > 4:        # a slow phone skips frames rather than falling behind
            return
        self._put(self._frame(2, data))

    def _put(self, b):
        if not self.alive:
            return
        try:
            self.q.put_nowait(b)
        except queue.Full:
            pass

    def _writer(self):
        while self.alive:
            try:
                b = self.q.get(timeout=1.0)
            except queue.Empty:
                continue
            if b is None:
                break
            try:
                self.sock.sendall(b)
            except OSError:
                self.alive = False

    def close(self):
        self.alive = False
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def read_message(self):
        """The next text or binary message (str or bytes), or None when the phone has gone."""
        def exact(n):
            buf = b""
            while len(buf) < n:
                chunk = self.sock.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError
                buf += chunk
            return buf
        parts, kind = [], None
        while True:
            b1, b2 = exact(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", exact(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", exact(8))[0]
            if n > 8 * 1024 * 1024:
                raise ConnectionError
            mask = exact(4) if b2 & 0x80 else None
            data = exact(n)
            if mask:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if op == 8:
                return None
            if op == 9:
                self._put(self._frame(10, data))
                continue
            if op == 10:
                continue
            if op in (1, 2):
                kind = op
            parts.append(data)
            if fin:
                msg = b"".join(parts)
                return msg.decode("utf-8", "replace") if kind == 1 else msg


# ------------------------------------------------------------------ the server
class PhoneServer:
    """HTTPS (console, pictures, /ws) and plain HTTP (setup, certificate). `app` gives the callbacks:
    app.http(method, path, query, body, token) -> (status, content_type, bytes) for /api/ requests,
    app.ws_open(conn), app.ws_message(conn, obj), app.ws_close(conn), app.valid_token(token),
    app.static_dir, app.setup_page(query) -> str."""

    def __init__(self, app, cert_folder):
        self.app = app
        self.cert_folder = cert_folder
        self.conns: list[WsConn] = []
        self.lock = threading.Lock()
        self.httpd = self.plain = None
        self.ips = []
        self.ts = {}
        self.error = ""

    # -------------------------------------------------------- lifecycle
    def start(self) -> bool:
        self.stop()
        self.ips = lan_addresses()
        self.ts = tailscale()
        if self.ts.get("ip") and self.ts["ip"] not in self.ips:
            self.ips.append(self.ts["ip"])
        try:
            ca, cert, key = ensure_certificates(self.cert_folder, self.ips,
                                                [self.ts["name"]] if self.ts.get("name") else [])
            self.ca_pem = ca
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(cert, key)
            self.httpd = _Server(("0.0.0.0", HTTPS_PORT), self._handler(secure=True))
            self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True, do_handshake_on_connect=False)
            self.plain = _Server(("0.0.0.0", HTTP_PORT), self._handler(secure=False))
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            self.stop()
            return False
        for srv in (self.httpd, self.plain):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.error = ""
        return True

    def stop(self):
        for srv in (self.httpd, self.plain):
            if srv is not None:
                try:
                    srv.shutdown()
                    srv.server_close()
                except Exception:  # noqa: BLE001
                    pass
        self.httpd = self.plain = None
        with self.lock:
            conns, self.conns = self.conns, []
        for c in conns:
            c.close()

    @property
    def running(self):
        return self.httpd is not None

    def clients(self) -> list[WsConn]:
        with self.lock:
            return [c for c in self.conns if c.alive and c.token]

    def broadcast(self, obj):
        for c in self.clients():
            c.send_json(obj)

    # -------------------------------------------------------- requests
    def _handler(self, secure):
        server = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def setup(self):
                if secure:
                    try:
                        self.request.do_handshake()
                    except (ssl.SSLError, OSError):
                        self.close_connection = True
                        raise
                super().setup()

            def _send(self, status, ctype, body: bytes, extra=None):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                # the console's own files are checked every time (a new CardCrop build shows at once);
                # pictures and three.js may be kept a while
                self.send_header("Cache-Control", "no-store" if status != 200 or ctype.startswith(("application/json", "text/html"))
                                 else "no-cache" if ctype.startswith(("text/javascript", "text/css",
                                                                       "application/manifest"))
                                 else "max-age=600")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _token(self, q):
                a = self.headers.get("Authorization", "")
                if a.startswith("Bearer "):
                    return a[7:].strip()
                return (q.get("k") or [""])[0]

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def _route(self, method):
                u = urllib.parse.urlsplit(self.path)
                path, q = u.path, urllib.parse.parse_qs(u.query)
                try:
                    if not secure:
                        return self._plain(path, q)
                    if path == "/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
                        return self._websocket()
                    if path.startswith("/api/"):
                        n = int(self.headers.get("Content-Length") or 0)
                        body = self.rfile.read(n) if n else b""
                        status, ctype, data = server.app.http(method, path, q, body, self._token(q))
                        return self._send(status, ctype, data)
                    return self._static(path)
                except (BrokenPipeError, ConnectionError, ssl.SSLError):
                    self.close_connection = True

            def _plain(self, path, q):
                if path in ("/cardcrop.mobileconfig", "/profile"):
                    # an iOS configuration profile: Safari hands it to Settings to install, where a bare
                    # certificate sent as a download only lands in Files
                    return self._send(200, "application/x-apple-aspen-config", ca_profile(server.ca_pem))
                if path in ("/cardcrop.cer", "/ca.cer"):
                    return self._send(200, "application/x-x509-ca-cert", ca_der(server.ca_pem))
                if path in ("/", "/setup"):
                    return self._send(200, "text/html; charset=utf-8", server.app.setup_page(q).encode())
                self._send(404, "text/plain", b"not here")

            def _static(self, path):
                root = server.app.static_dir
                rel = "index.html" if path in ("/", "") else path.lstrip("/")
                full = os.path.normpath(os.path.join(root, rel))
                if not full.startswith(os.path.normpath(root)) or not os.path.isfile(full):
                    if rel.startswith("fonts/"):
                        f2 = os.path.join(server.app.font_dir, os.path.basename(rel))
                        if os.path.isfile(f2):
                            full = f2
                        else:
                            return self._send(404, "text/plain", b"not here")
                    else:
                        return self._send(404, "text/plain", b"not here")
                ext = os.path.splitext(full)[1].lower()
                ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                         ".css": "text/css; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml",
                         ".json": "application/json", ".webmanifest": "application/manifest+json",
                         ".ttf": "font/ttf", ".woff2": "font/woff2"}.get(ext, "application/octet-stream")
                with open(full, "rb") as f:
                    self._send(200, ctype, f.read())

            def _websocket(self):
                key = self.headers.get("Sec-WebSocket-Key", "")
                acc = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
                self.send_response(101, "Switching Protocols")
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", acc)
                self.end_headers()
                self.wfile.flush()
                conn = WsConn(self.request, self.client_address[0])
                with server.lock:
                    server.conns.append(conn)
                try:
                    while conn.alive:
                        msg = conn.read_message()
                        if msg is None:
                            break
                        if isinstance(msg, bytes):
                            continue
                        try:
                            obj = json.loads(msg)
                        except ValueError:
                            continue
                        if conn.token is None:          # the first message proves the phone is paired
                            if server.app.valid_token(obj.get("auth", "")):
                                conn.token = obj["auth"]
                                server.app.ws_open(conn)
                            else:
                                conn.send_json({"t": "unpaired"})
                            continue
                        server.app.ws_message(conn, obj)
                except (ConnectionError, OSError, ssl.SSLError):
                    pass
                finally:
                    conn.close()
                    with server.lock:
                        if conn in server.conns:
                            server.conns.remove(conn)
                    if conn.token:
                        server.app.ws_close(conn)
                    self.close_connection = True

        return H


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # a phone that has not trusted the certificate yet, or walked out of Wi-Fi, is not an error
        import sys
        e = sys.exc_info()[1]
        if isinstance(e, (ssl.SSLError, ConnectionError, OSError, TimeoutError)):
            return
        super().handle_error(request, client_address)
