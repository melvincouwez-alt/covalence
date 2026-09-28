# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Melvin Couwez
"""Files with the LocalSend app of the iPhone (LocalSend protocol v2).

LocalSend (https://localsend.org, protocol: https://github.com/localsend/protocol)
is a free app for iOS and the other systems. Two devices on the same network
find each other by UDP multicast (224.0.0.167:53317) and exchange files over
HTTPS with a self-signed certificate; a device is known by the SHA-256 of its
certificate (its fingerprint).

Receiving: a peer asks with POST /api/localsend/v2/prepare-upload (the list of
files). The request waits until the user accepts or refuses in a notification:
nothing is ever accepted silently. The fingerprint in that request is only what
the sender claims (LocalSend clients do not prove it with a client certificate),
anyone on the network can copy the iPhone's: so there is no « always accept »,
every transfer is asked for. Accepted files land in ~/Téléchargements/Covalence,
one POST /api/localsend/v2/upload per file with the token handed out for it,
within MAX_TOTAL bytes and the free space of the disk.

Sending: prepare-upload to the chosen peer (the iPhone asks its user), then one
upload per file. Only HTTPS peers are listed, and every connection checks that
the certificate really has the peer's fingerprint; announcements are unsigned, so
a known peer keeps every address it was seen at and the sender tries them until
one proves the fingerprint (a fake announcement can then only fail, never divert
the files).

Off by default (it listens on the network); [files] localsend=true in
covalenced.conf turns it on. Logs record counts and states only.
"""

import hashlib
import http.client
import http.server
import json
import mimetypes
import os
import secrets
import socket
import ssl
import struct
import subprocess
import threading
import time
import urllib.parse
import uuid

from .util import log

PORT = 53317
GROUP = "224.0.0.167"
API = "/api/localsend/v2"
PROTOCOL_VERSION = "2.1"
PEER_TTL = 180  # seconds a peer stays listed without news
ASK_TIMEOUT = 120  # seconds the user has to accept
MAX_FILES = 500
MAX_TOTAL = 20 * 1024 ** 3  # bytes in one incoming transfer
KEEP_FREE = 1024 ** 3  # never fill the disk: keep this much free after a transfer
MAX_ADDRESSES = 4  # addresses remembered per peer (see the module comment)
CHUNK = 1 << 16


# --- identity ---------------------------------------------------------------------------------

def ensure_certificate(directory):
    """(cert path, key path, fingerprint): a self-signed certificate made once with openssl."""
    os.makedirs(directory, mode=0o700, exist_ok=True)
    cert, key = os.path.join(directory, "cert.pem"), os.path.join(directory, "key.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        old = os.umask(0o077)
        try:
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-keyout", key, "-out", cert, "-days", "3650",
                            "-subj", "/CN=Covalence"],
                           check=True, capture_output=True, timeout=60)
        finally:
            os.umask(old)
    with open(cert, encoding="ascii") as f:
        der = ssl.PEM_cert_to_DER_cert(f.read())
    return cert, key, hashlib.sha256(der).hexdigest()


def device_info(alias, fingerprint, port=PORT, announce=None):
    info = {"alias": alias, "version": PROTOCOL_VERSION, "deviceModel": "elementary OS",
            "deviceType": "desktop", "fingerprint": fingerprint, "port": port,
            "protocol": "https", "download": False}
    if announce is not None:
        info["announce"] = announce
    return info


def peer_from(info, address):
    """A peer from an announcement or a register body, or None when it is not usable."""
    if not isinstance(info, dict):
        return None
    fingerprint = str(info.get("fingerprint") or "")
    if not fingerprint:
        return None
    try:
        port = int(info.get("port") or PORT)
    except (TypeError, ValueError):
        port = PORT
    if info.get("protocol") == "http":
        return None  # no certificate, so nothing proves who it is
    return {"id": fingerprint, "alias": str(info.get("alias") or "LocalSend")[:80],
            "model": str(info.get("deviceModel") or "")[:80],
            "type": str(info.get("deviceType") or ""), "address": address, "port": port,
            "protocol": "https", "addresses": [address], "seen": time.time()}


def merge_peer(known, peer):
    """A new sighting of a peer: the newest address first, the earlier ones kept."""
    if known is None:
        return peer
    addresses = [peer["address"]] + [a for a in known.get("addresses", [known["address"]])
                                     if a != peer["address"]]
    return dict(peer, addresses=addresses[:MAX_ADDRESSES])


def safe_name(name):
    """The last part of a file name, without anything that could leave the folder."""
    name = str(name or "").replace("\\", "/").split("/")[-1].strip()
    name = "".join(c for c in name if c >= " " and c != "\x7f")
    if name in ("", ".", ".."):
        name = "fichier"
    if name.startswith("."):
        name = "_" + name[1:]
    return name[:200]


def free_path(folder, name):
    """folder/name, or folder/name (2).ext… when the name is taken."""
    base, ext = os.path.splitext(name)
    path, n = os.path.join(folder, name), 2
    while os.path.exists(path) or os.path.exists(path + ".part"):
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return path


def parse_prepare(body):
    """(sender info, {file id: {"name", "size", "type"}}) from a prepare-upload body.

    Raises ValueError on anything malformed or too large (see MAX_TOTAL)."""
    data = json.loads(body)
    info, files = data.get("info"), data.get("files")
    if not isinstance(info, dict) or not isinstance(files, dict) or not files:
        raise ValueError("bad prepare-upload")
    if len(files) > MAX_FILES:
        raise ValueError("too many files")
    result = {}
    for file_id, meta in files.items():
        if not isinstance(meta, dict):
            raise ValueError("bad file")
        size = int(meta.get("size", -1))
        if size < 0:
            raise ValueError("bad size")
        result[str(file_id)] = {"name": safe_name(meta.get("fileName")), "size": size,
                                "type": str(meta.get("fileType") or "")}
    if sum(f["size"] for f in result.values()) > MAX_TOTAL:
        raise ValueError("too large")
    return info, result


def room_for(folder, total):
    """Whether the disk holding folder can take total bytes and keep KEEP_FREE free."""
    probe = folder
    while probe and not os.path.exists(probe):
        probe = os.path.dirname(probe)
    try:
        stat = os.statvfs(probe or "/")
    except OSError:
        return False
    return stat.f_bavail * stat.f_frsize - total >= KEEP_FREE


def human_size(size):
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}".replace(".", ",")
        size /= 1024
    return str(size)


# --- receiving -------------------------------------------------------------------------------

class Session:
    def __init__(self, peer, files):
        self.id = uuid.uuid4().hex
        self.peer = peer
        self.files = files  # id -> {"name", "size", "type"}
        self.tokens = {}
        self.done = set()
        self.received = 0
        self.total = sum(f["size"] for f in files.values())
        self.decision = None
        self.event = threading.Event()
        self.cancelled = False
        self.saved = []


class Receiver:
    """The HTTPS side of LocalSend. ask(session, answer) is called (through dispatch) when a
    peer wants to send; answer(True/False) settles it. Everything else reaches the owner
    through on_event(kind, data), also through dispatch."""

    def __init__(self, identity, folder, ask, on_event, dispatch, host="0.0.0.0", port=PORT):
        self.cert, self.key, self.fingerprint = identity["cert"], identity["key"], identity["fingerprint"]
        self.alias = identity["alias"]
        self.folder = folder
        self.ask = ask
        self.on_event = on_event
        self.dispatch = dispatch
        self.lock = threading.Lock()
        self.session = None
        self.server = self._make_server(host, port)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, name="covalence-localsend",
                                       daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        with self.lock:
            if self.session:
                self.session.cancelled = True
                self.session.event.set()

    def info(self):
        return device_info(self.alias, self.fingerprint, self.port)

    def _make_server(self, host, port):
        receiver = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass  # no addresses, names or paths in the logs

            def _reply(self, code, payload=None):
                data = b"" if payload is None else json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if data:
                    self.wfile.write(data)

            def _body(self, limit=1 << 20):
                length = int(self.headers.get("Content-Length") or 0)
                if length > limit:
                    raise ValueError("body too large")
                return self.rfile.read(length) if length else b""

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                if url.path in (API + "/info", "/api/localsend/v1/info"):
                    self._reply(200, receiver.info())
                else:
                    self._reply(404)

            def do_POST(self):
                url = urllib.parse.urlparse(self.path)
                query = dict(urllib.parse.parse_qsl(url.query))
                try:
                    if url.path == API + "/register":
                        receiver._register(self._body(), self.client_address[0])
                        self._reply(200, receiver.info())
                    elif url.path == API + "/prepare-upload":
                        code, payload = receiver._prepare(self._body(), self.client_address[0])
                        self._reply(code, payload)
                    elif url.path == API + "/upload":
                        self._reply(receiver._upload(query, self))
                    elif url.path == API + "/cancel":
                        receiver._cancel(query.get("sessionId", ""))
                        self._reply(200)
                    else:
                        self._reply(404)
                except (ValueError, json.JSONDecodeError):
                    self._reply(400)
                except OSError:
                    self._reply(500)

        class Server(http.server.ThreadingHTTPServer):
            def handle_error(self, _request, _address):
                pass  # a peer that hangs up (or fails TLS) is not worth a traceback

        server = Server((host, port), Handler)
        server.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        return server

    def _register(self, body, address):
        peer = peer_from(json.loads(body or b"{}"), address)
        if peer and peer["id"] != self.fingerprint:
            self.dispatch(self.on_event, "peer", peer)

    def _prepare(self, body, address):
        info, files = parse_prepare(body)
        peer = peer_from(info, address) or {"id": "", "alias": "LocalSend", "model": "",
                                           "address": address}
        session = Session(peer, files)
        if not room_for(self.folder, session.total):
            self.dispatch(self.on_event, "refused", session)
            return 413, {"message": "Not enough space"}
        with self.lock:
            if self.session is not None and not self.session.cancelled:
                return 409, {"message": "Blocked by another session"}
            self.session = session

        def answer(accepted):
            session.decision = bool(accepted)
            session.event.set()

        self.dispatch(self.ask, session, answer)
        session.event.wait(ASK_TIMEOUT)
        if not session.decision or session.cancelled:
            with self.lock:
                if self.session is session:
                    self.session = None
            self.dispatch(self.on_event, "refused", session)
            return 403, {"message": "Rejected"}
        session.tokens = {file_id: secrets.token_hex(16) for file_id in files}
        os.makedirs(self.folder, exist_ok=True)
        self.dispatch(self.on_event, "started", session)
        return 200, {"sessionId": session.id, "files": session.tokens}

    def _upload(self, query, handler):
        with self.lock:
            session = self.session
        file_id = query.get("fileId", "")
        if session is None or session.cancelled or query.get("sessionId") != session.id \
                or file_id not in session.tokens or query.get("token") != session.tokens[file_id] \
                or file_id in session.done:
            return 403
        meta = session.files[file_id]
        length = int(handler.headers.get("Content-Length") or -1)
        if length != meta["size"]:
            return 400
        path = free_path(self.folder, meta["name"])
        part = path + ".part"
        remaining = length
        try:
            with open(part, "wb") as out:
                while remaining > 0:
                    chunk = handler.rfile.read(min(CHUNK, remaining))
                    if not chunk:
                        raise OSError("connection closed")
                    out.write(chunk)
                    remaining -= len(chunk)
                    session.received += len(chunk)
                    if session.cancelled:
                        raise OSError("cancelled")
                    self.dispatch(self.on_event, "progress", session)
            os.replace(part, path)
        except OSError:
            if os.path.exists(part):
                os.unlink(part)
            raise
        session.done.add(file_id)
        session.saved.append(path)
        if len(session.done) == len(session.files):
            with self.lock:
                if self.session is session:
                    self.session = None
            self.dispatch(self.on_event, "finished", session)
        return 200

    def _cancel(self, session_id):
        with self.lock:
            session = self.session
            if session is None or session.id != session_id:
                return
            session.cancelled = True
            session.event.set()
            self.session = None
        self.dispatch(self.on_event, "cancelled", session)

    def cancel_current(self):
        with self.lock:
            session = self.session
        if session:
            self._cancel(session.id)


# --- discovery -------------------------------------------------------------------------------

class Discovery:
    """Multicast announcements: ours at start (and on request), theirs as they come."""

    def __init__(self, info, on_peer, dispatch, register):
        self.info = info
        self.on_peer = on_peer
        self.dispatch = dispatch
        self.register = register
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", PORT))
        membership = struct.pack("4sl", socket.inet_aton(GROUP), socket.INADDR_ANY)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        self.sock.settimeout(1.0)
        self.running = True
        self.thread = threading.Thread(target=self._listen, name="covalence-localsend-udp",
                                       daemon=True)

    def start(self):
        self.thread.start()
        self.announce()

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass

    def announce(self):
        data = json.dumps(dict(self.info, announce=True)).encode("utf-8")
        try:
            self.sock.sendto(data, (GROUP, PORT))
        except OSError as error:
            log(f"fichiers : annonce impossible ({error.strerror or error})")

    def _listen(self):
        while self.running:
            try:
                data, (address, _port) = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                info = json.loads(data)
            except (ValueError, UnicodeDecodeError):
                continue
            peer = peer_from(info, address)
            if peer is None or peer["id"] == self.info["fingerprint"]:
                continue
            self.dispatch(self.on_peer, peer)
            if info.get("announce") or info.get("announcement"):
                # Answer by HTTP register, or by an unannounced UDP message as a fallback.
                if not self.register(peer):
                    try:
                        self.sock.sendto(json.dumps(dict(self.info, announce=False)).encode("utf-8"),
                                         (GROUP, PORT))
                    except OSError:
                        pass


# --- sending ---------------------------------------------------------------------------------

class SendError(Exception):
    pass


def _connection(peer, timeout):
    if peer.get("protocol") != "https":
        raise SendError("fingerprint")  # never in clear: nothing would prove the peer
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # self-signed: the fingerprint is checked instead
    return http.client.HTTPSConnection(peer["address"], peer["port"], timeout=timeout,
                                       context=context)


def _request(peer, method, path, body=b"", timeout=15, headers=None, stream=None, progress=None):
    conn = _connection(peer, timeout)
    try:
        conn.connect()
        der = conn.sock.getpeercert(binary_form=True)
        if not der or hashlib.sha256(der).hexdigest() != peer["id"]:
            raise SendError("fingerprint")
        head = {"Content-Type": "application/json"}
        head.update(headers or {})
        if stream is None:
            conn.request(method, path, body=body, headers=head)
        else:
            conn.putrequest(method, path)
            for key, value in head.items():
                conn.putheader(key, value)
            conn.endheaders()
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                conn.send(chunk)
                if progress:
                    progress(len(chunk))
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def register(own_info, peer):
    """Tell a peer we exist (answer to its announcement). True when it answered."""
    try:
        status, _ = _request(peer, "POST", API + "/register",
                             json.dumps(own_info).encode("utf-8"), timeout=5)
        return status == 200
    except (OSError, SendError, http.client.HTTPException):
        return False


def verified_peer(peer, timeout=5):
    """The peer at the first of its addresses whose certificate has its fingerprint.
    Raises SendError("fingerprint") when none does, SendError("unreachable") when none
    answers at all."""
    reached = False
    for address in peer.get("addresses") or [peer["address"]]:
        candidate = dict(peer, address=address)
        try:
            _request(candidate, "GET", API + "/info", timeout=timeout)
            return candidate
        except SendError:
            reached = True
        except (OSError, http.client.HTTPException):
            continue
    raise SendError("fingerprint" if reached else "unreachable")


def send_files(own_info, peer, paths, progress=lambda sent, total: None, cancelled=lambda: False):
    """Send files to a peer; returns the number of files it took. Raises SendError."""
    peer = verified_peer(peer)
    files, sizes = {}, {}
    for path in paths:
        size = os.path.getsize(path)
        file_id = uuid.uuid4().hex
        files[file_id] = {"id": file_id, "fileName": os.path.basename(path), "size": size,
                          "fileType": mimetypes.guess_type(path)[0] or "application/octet-stream"}
        sizes[file_id] = (path, size)
    total = sum(size for _path, size in sizes.values())
    body = json.dumps({"info": own_info, "files": files}).encode("utf-8")
    try:
        status, data = _request(peer, "POST", API + "/prepare-upload", body, timeout=ASK_TIMEOUT + 30)
    except (OSError, http.client.HTTPException) as error:
        raise SendError("unreachable") from error
    if status == 204:
        return 0
    if status == 403:
        raise SendError("refused")
    if status == 409:
        raise SendError("busy")
    if status != 200:
        raise SendError(f"http {status}")
    answer = json.loads(data)
    session, tokens = answer.get("sessionId", ""), answer.get("files") or {}
    sent = [0]

    def step(count):
        sent[0] += count
        progress(sent[0], total)

    taken = 0
    for file_id, token in tokens.items():
        if file_id not in sizes:
            continue
        if cancelled():
            _request(peer, "POST", f"{API}/cancel?sessionId={urllib.parse.quote(session)}")
            raise SendError("cancelled")
        path, size = sizes[file_id]
        query = urllib.parse.urlencode({"sessionId": session, "fileId": file_id, "token": token})
        with open(path, "rb") as stream:
            try:
                status, _ = _request(peer, "POST", f"{API}/upload?{query}", timeout=60,
                                     headers={"Content-Type": "application/octet-stream",
                                              "Content-Length": str(size)},
                                     stream=stream, progress=step)
            except (OSError, http.client.HTTPException) as error:
                raise SendError("interrupted") from error
        if status != 200:
            raise SendError(f"http {status}")
        taken += 1
    return taken
