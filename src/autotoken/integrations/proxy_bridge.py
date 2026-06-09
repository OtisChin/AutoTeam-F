"""Small local HTTP proxy that forwards browser traffic through SOCKS5.

Playwright Chromium can be fickle with direct SOCKS routing on some targets.
This bridge gives Chromium a local HTTP proxy and performs SOCKS5 upstream
connection itself.
"""

from __future__ import annotations

import logging
import select
import socket
import socketserver
import struct
import threading
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from autotoken.settings.config import normalize_proxy_url

logger = logging.getLogger(__name__)


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise OSError("unexpected EOF from SOCKS proxy")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _connect_socks5(upstream: str, target_host: str, target_port: int) -> socket.socket:
    parsed = urlsplit(upstream)
    if parsed.scheme not in {"socks5", "socks5h"} or not parsed.hostname or not parsed.port:
        raise ValueError("SOCKS bridge requires socks5/socks5h upstream with host and port")
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    sock = socket.create_connection((parsed.hostname, parsed.port), timeout=20)
    sock.settimeout(20)
    try:
        methods = b"\x00\x02" if username or password else b"\x00"
        sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
        version, method = _read_exact(sock, 2)
        if version != 5:
            raise OSError("invalid SOCKS proxy greeting")
        if method == 0x02:
            user_bytes = username.encode("utf-8")
            pass_bytes = password.encode("utf-8")
            if len(user_bytes) > 255 or len(pass_bytes) > 255:
                raise OSError("SOCKS credentials are too long")
            sock.sendall(b"\x01" + bytes([len(user_bytes)]) + user_bytes + bytes([len(pass_bytes)]) + pass_bytes)
            auth_version, status = _read_exact(sock, 2)
            if auth_version != 1 or status != 0:
                raise OSError("SOCKS proxy authentication failed")
        elif method != 0x00:
            raise OSError("SOCKS proxy did not accept authentication method")

        host_bytes = target_host.encode("idna")
        if len(host_bytes) > 255:
            raise OSError("target hostname is too long for SOCKS5")
        request = b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + struct.pack("!H", int(target_port))
        sock.sendall(request)
        reply = _read_exact(sock, 4)
        if reply[0] != 5 or reply[1] != 0:
            raise OSError(f"SOCKS proxy connect failed: code={reply[1] if len(reply) > 1 else 'unknown'}")
        atyp = reply[3]
        if atyp == 1:
            _read_exact(sock, 4)
        elif atyp == 3:
            _read_exact(sock, _read_exact(sock, 1)[0])
        elif atyp == 4:
            _read_exact(sock, 16)
        else:
            raise OSError("invalid SOCKS proxy bind address type")
        _read_exact(sock, 2)
        sock.settimeout(None)
        return sock
    except Exception:
        sock.close()
        raise


def _relay(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    try:
        while True:
            readable, _, _ = select.select(sockets, [], [], 60)
            if not readable:
                return
            for src in readable:
                data = src.recv(65536)
                if not data:
                    return
                dst = right if src is left else left
                dst.sendall(data)
    finally:
        for sock in sockets:
            try:
                sock.close()
            except Exception:
                pass


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: _ProxyServer = self.server  # type: ignore[assignment]
        try:
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 65536:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                data += chunk
            header, _, body = data.partition(b"\r\n\r\n")
            lines = header.split(b"\r\n")
            if not lines:
                return
            first = lines[0].decode("iso-8859-1", errors="replace")
            parts = first.split()
            if len(parts) < 3:
                return
            method, target, version = parts[0].upper(), parts[1], parts[2]
            if method == "CONNECT":
                host, _, port_text = target.rpartition(":")
                port = int(port_text or "443")
                upstream = _connect_socks5(server.upstream_url, host, port)
                self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                _relay(self.request, upstream)
                return

            parsed = urlsplit(target)
            if parsed.scheme.lower() != "http" or not parsed.hostname:
                self.request.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                return
            port = parsed.port or 80
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            upstream = _connect_socks5(server.upstream_url, parsed.hostname, port)
            lines[0] = f"{method} {path} {version}".encode("iso-8859-1")
            upstream.sendall(b"\r\n".join(lines) + b"\r\n\r\n" + body)
            _relay(self.request, upstream)
        except Exception as exc:
            logger.debug("[proxy_bridge] proxy request failed: %s", exc)
            try:
                self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            except Exception:
                pass


class _ProxyServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler_cls, upstream_url: str):
        self.upstream_url = upstream_url
        super().__init__(server_address, handler_cls)


@dataclass
class SocksHttpBridge:
    upstream_url: str
    server: _ProxyServer
    thread: threading.Thread

    @property
    def proxy_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def stop(self) -> None:
        try:
            self.server.shutdown()
        except Exception:
            pass
        try:
            self.server.server_close()
        except Exception:
            pass


def start_playwright_socks_bridge(proxy_url: str | None) -> SocksHttpBridge | None:
    raw = str(proxy_url or "").strip()
    if not raw:
        return None
    try:
        upstream = normalize_proxy_url(raw)
    except Exception:
        return None
    parsed = urlsplit(upstream)
    if parsed.scheme not in {"socks5", "socks5h"}:
        return None
    server = _ProxyServer(("127.0.0.1", 0), _ProxyHandler, upstream)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="playwright-socks-http-bridge")
    thread.start()
    bridge = SocksHttpBridge(upstream_url=upstream, server=server, thread=thread)
    logger.info("[proxy_bridge] started local HTTP bridge for SOCKS proxy at %s", bridge.proxy_url)
    return bridge
