"""PIX trial core: BR create (no promo) -> BR update (free promo) -> PIX QR."""

from __future__ import annotations

import base64
import json
import random
import re
import secrets
import socket
import ssl
import string
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote, urlparse

import requests
from curl_cffi.requests import Session as CurlCffiSession

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
DEFAULT_STRIPE_PK = (
    "pk_live_51HOrSwC6h1nxGoI3lTAgRjYVrz4dU3fVOabyCcKR3pbEJguCVAlqCxdxCUvoRh1XWwRacViovU3kLKvpkjh7IqkW00iXQsjo3n"
)
STRIPE_VERSION_FULL = (
    "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
)
DEFAULT_STRIPE_RUNTIME_VERSION = "52bec4df19"
TIMEOUT = 60

FIRST_M = [
    "Gabriel", "Lucas", "Matheus", "Pedro", "Rafael", "Bruno", "Felipe", "Thiago",
    "Gustavo", "Leonardo", "Joao", "Andre", "Carlos", "Ricardo", "Diego",
]
FIRST_F = [
    "Ana", "Julia", "Mariana", "Beatriz", "Larissa", "Camila", "Fernanda",
    "Patricia", "Amanda", "Bruna", "Leticia", "Carolina", "Isabela", "Gabriela",
]
LAST = [
    "Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira", "Alves", "Pereira",
    "Lima", "Gomes", "Costa", "Ribeiro", "Martins", "Carvalho", "Almeida", "Lopes",
    "Soares", "Fernandes", "Vieira", "Barbosa", "Rocha", "Dias", "Nascimento", "Moreira",
]
BR_ADDRESSES = [
    # Refreshed from OpenStreetMap/Overpass public address tags on 2026-07-17.
    ('Rua Henrique Schaumann 124', 'Sao Paulo', 'SP', '05413-010', 11),
    ('Rua da Consolacao 787', 'Sao Paulo', 'SP', '01301-000', 11),
    ('Rua Doutor Vila Nova 160', 'Sao Paulo', 'SP', '01222-020', 11),
    ('Rua Guaipa 1539', 'Sao Paulo', 'SP', '05089-001', 11),
    ('Rua Maria Antonia 378', 'Sao Paulo', 'SP', '01222-010', 11),
    ('Rua Mateus Grou 15', 'Sao Paulo', 'SP', '05415-040', 11),
    ('Avenida Maria Coelho Aguiar 920', 'Sao Paulo', 'SP', '05805-000', 11),
    ('Rua Antonio da Mata Junior 80', 'Sao Paulo', 'SP', '05812-030', 11),
    ('Rua Alexandre Dumas 1541', 'Sao Paulo', 'SP', '04717-004', 11),
    ('Avenida Valdemar Ferreira 231', 'Sao Paulo', 'SP', '05501-000', 11),
    ('Rua do Catete 153', 'Rio de Janeiro', 'RJ', '22220-000', 21),
    ('Rua do Catete 104', 'Rio de Janeiro', 'RJ', '22220-000', 21),
    ('Rua Pedro Americo 1', 'Rio de Janeiro', 'RJ', '22211-200', 21),
    ('Rua do Catete 265', 'Rio de Janeiro', 'RJ', '22220-001', 21),
    ('Rua do Catete 257', 'Rio de Janeiro', 'RJ', '22220-000', 21),
    ('Rua General Pereira da Silva 184', 'Rio de Janeiro', 'RJ', '24220-031', 21),
    ('Rua General Pereira da Silva 186', 'Rio de Janeiro', 'RJ', '24220-031', 21),
    ('Rua General Pereira da Silva 188', 'Rio de Janeiro', 'RJ', '24220-031', 21),
    ('Rua do Catete 113', 'Rio de Janeiro', 'RJ', '22220-000', 21),
    ('Rua do Catete 115', 'Rio de Janeiro', 'RJ', '22220-000', 21),
    ('Cais do Apolo 739', 'Recife', 'PE', '50030-902', 81),
    ('Rua Pacifico da Luz 104', 'Recife', 'PE', '50721-390', 81),
    ('Rua Tenente Joao Cicero 202', 'Recife', 'PE', '51020-190', 81),
    ('Avenida Fagundes Varela 850', 'Recife', 'PE', '53140-080', 81),
    ('Rua Artur Muniz 122', 'Recife', 'PE', '51111-190', 81),
    ('Rua Francisco da Cunha 47', 'Recife', 'PE', '51020-210', 81),
    ('Estrada do Barbalho 889', 'Recife', 'PE', '50690-900', 81),
    ('Avenida Agamenon Magalhaes 680', 'Recife', 'PE', '53110-710', 81),
    ('R. Arthur Bruno Schwambach 1142', 'Recife', 'PE', '51130-080', 81),
    ('Rua Jose Bonifacio 43', 'Recife', 'PE', '50710-435', 81),
    ('Avenida Manoel Dias da Silva 2031', 'Salvador', 'BA', '41830-000', 71),
    ('Avenida Tancredo Neves 274', 'Salvador', 'BA', '41820-020', 71),
    ('Avenida Oceanica 2717', 'Salvador', 'BA', '40170-010', 71),
    ('Rua Fonte do Boi 215', 'Salvador', 'BA', '41940-360', 71),
    ('Avenida Tancredo Neves 1506', 'Salvador', 'BA', '41820-020', 71),
    ('Avenida Reitor Miguel Calmon - Vale do Canela 1080', 'Salvador', 'BA', '40110-000', 71),
    ('Av. Dorival Caymmi 14', 'Salvador', 'BA', '41635-150', 71),
    ('Rua Machado de Assis 36E', 'Salvador', 'BA', '40285-280', 71),
    ('Rua Monte Conselho 505', 'Salvador', 'BA', '41940-370', 71),
    ('Rua Thomaz Gonzaga 219', 'Salvador', 'BA', '41130-100', 71),
    ('Avenida Republica do Libano 1520', 'Goiania', 'GO', '74115-030', 62),
    ('Avenida Republica do Libano 1440', 'Goiania', 'GO', '74115-030', 62),
    ('Avenida T-7 563', 'Goiania', 'GO', '74210-265', 62),
    ('Avenida Primeira Radial 643', 'Goiania', 'GO', '74820-300', 62),
    ('Avenida T-63 841', 'Goiania', 'GO', '74230-105', 62),
    ('Rua 90 775', 'Goiania', 'GO', '74093-020', 62),
    ('Rua da Saude N. 556', 'Goiania', 'GO', '74425-020', 62),
    ('Rua 54 684', 'Goiania', 'GO', '74810-220', 62),
    ('Avenida 24 de Outubro 311', 'Goiania', 'GO', '74505-011', 62),
    ('Avenida Pires Fernandes 774', 'Goiania', 'GO', '74070-970', 62),
    ('Rua Maria Amalia 273', 'Vitoria', 'ES', '29123-130', 27),
    ('Avenida Hugo Musso 1436', 'Vitoria', 'ES', '29101-280', 27),
    ('Rua Eurico de Aguiar 888', 'Vitoria', 'ES', '29055-280', 27),
    ('Rua Sao Paulo da Cruz 117', 'Vitoria', 'ES', '29115-571', 27),
    ('Rua Visconde de Taunay 20', 'Vitoria', 'ES', '29106-080', 27),
    ('Rua Maria de Fatima da Costa 10', 'Vitoria', 'ES', '29161-828', 27),
    ('Avenida Dante Michelini 791', 'Vitoria', 'ES', '29060-235', 27),
    ('Avenida Henrique Moscoso 256', 'Vitoria', 'ES', '29101-330', 27),
    ('Avenida Vitoria 2551', 'Vitoria', 'ES', '29046-160', 27),
    ('Avenida Marechal Mascarenhas de Moraes 1877', 'Vitoria', 'ES', '29053-245', 27),
    ('Rua Tres Pontas 1888', 'Belo Horizonte', 'MG', '30700-320', 31),
    ('Avenida do Contorno 5771', 'Belo Horizonte', 'MG', '30110-035', 31),
    ('Rua dos Inconfidentes 1068', 'Belo Horizonte', 'MG', '30140-120', 31),
    ('Rua Goncalves Dias 1581', 'Belo Horizonte', 'MG', '30140-092', 31),
    ('Rua Curitiba 1329', 'Belo Horizonte', 'MG', '30170-121', 31),
    ('Avenida Francisco Sa 1369', 'Belo Horizonte', 'MG', '30441-021', 31),
    ('Praca Ruy Barbosa 104', 'Belo Horizonte', 'MG', '30160-000', 31),
    ('R. Rio Grande do Sul, 714', 'Belo Horizonte', 'MG', '30170-110', 31),
    ('Condominio Ville de Montagne Quadra 18 29', 'Brasilia', 'DF', '71680-357', 61),
    ('Condominio Ville de Montagne Quadra 18 60', 'Brasilia', 'DF', '71680-357', 61),
    ('Condominio Ville de Montagne Quadra 18 22', 'Brasilia', 'DF', '71680-357', 61),
    ('Condominio Ville de Montagne Quadra 18 1', 'Brasilia', 'DF', '71680-357', 61),
    ('Terceira Avenida, Bloco 990-1120 1110 B', 'Brasilia', 'DF', '71720-555', 61),
    ('CLN 209 Bloco B Loja 19', 'Brasilia', 'DF', '70854-520', 61),
    ('R1-S5 QI 7', 'Brasilia', 'DF', '71020-216', 61),
    ('R1-S5 QI 7', 'Brasilia', 'DF', '72135-010', 61),
    ('Rua Barao de Cotegipe 415', 'Porto Alegre', 'RS', '90540-020', 51),
    ('Rua Silva So 300', 'Porto Alegre', 'RS', '90610-270', 51),
    ('Rua Professor Alvaro Alvim 400', 'Porto Alegre', 'RS', '90420-020', 51),
    ('Rua Vicente da Fontoura 1804', 'Porto Alegre', 'RS', '90610-000', 51),
    ('Avenida Coronel Lucas de Oliveira 1677', 'Porto Alegre', 'RS', '90460-001', 51),
    ('Avenida Coronel Lucas de Oliveira 1671', 'Porto Alegre', 'RS', '90460-001', 51),
    ('Rua Olavo Barreto Viana 18', 'Porto Alegre', 'RS', '90570-000', 51),
    ('Rua Sarmento Leite 865', 'Porto Alegre', 'RS', '90050-170', 51),
    ('Avenida Santos Dumont 1256', 'Fortaleza', 'CE', '60150-161', 85),
    ('Avenida Antonio Sales 3110', 'Fortaleza', 'CE', '60135-102', 85),
    ('Avenida Washington Soares 85', 'Fortaleza', 'CE', '60811-900', 85),
    ('Avenida Antonio Sales 3700', 'Fortaleza', 'CE', '60192-165', 85),
    ('Rua Gil Amora 1500', 'Fortaleza', 'CE', '60015-180', 85),
    ('Avenida Barao de Studart 855', 'Fortaleza', 'CE', '60120-001', 85),
    ('Avenida Barao de Studart 825', 'Fortaleza', 'CE', '60120-001', 85),
    ('Rua Tenente Benevolo 1785', 'Fortaleza', 'CE', '60160-041', 85),
    ('Avenida Governador Jose Malcher 2927', 'Belem', 'PA', '66060-232', 91),
    ('Avenida Almirante Barroso 3251', 'Belem', 'PA', '66613-710', 91),
    ('Primeira Travessa de Queluz 63', 'Belem', 'PA', '66090-520', 91),
    ('Rua dos Caripunas 1717', 'Belem', 'PA', '66033-442', 91),
    ('Avenida Serzedelo Correa 880', 'Belem', 'PA', '66033-770', 91),
    ('Avenida Presidente Vargas 718', 'Belem', 'PA', '66017-000', 91),
    ('Travessa Padre Eutiquio 2350', 'Belem', 'PA', '66033-726', 91),
    ('Travessa Benjamin Constant 1321', 'Belem', 'PA', '66035-170', 91),
    ('Rua Prefeira Eliane Barros 2000', 'Natal', 'RN', '59014-540', 84),
    ('Rua Jaguarari 1450', 'Natal', 'RN', '59031-500', 84),
    ('Rua Doutor Lauro Pinto 315', 'Natal', 'RN', '59064-250', 84),
    ('Avenida Doutor Mario Negocio 2305', 'Natal', 'RN', '59040-000', 84),
    ('Rua Sao Joao 1349', 'Natal', 'RN', '59022-390', 84),
    ('Avenida Engenheiro Hildebrando de Gois 221', 'Natal', 'RN', '59010-970', 84),
    ('Rua Militao Chaves 2055', 'Natal', 'RN', '59064-440', 84),
    ('Rua Paulo Barros Goes 1584', 'Natal', 'RN', '59064-460', 84),
    ('Avenida Alvaro Otacilio 2991', 'Maceio', 'AL', '57035-900', 82),
    ('Avenida Aristeu Andrade 355', 'Maceio', 'AL', '57051-900', 82),
    ('Avenida Fernandes Lima 781', 'Maceio', 'AL', '57055-970', 82),
    ('Rua Comendador Palmeira 502', 'Maceio', 'AL', '57051-903', 82),
    ('Avenida da Paz 1318', 'Maceio', 'AL', '57020-440', 82),
    ('Avenida Joao Davino 680', 'Maceio', 'AL', '57035-554', 82),
    ('Rua Pedro Paulino 395', 'Maceio', 'AL', '57025-340', 82),
    ('Rua Quintino Bocaiuva 204', 'Maceio', 'AL', '57035-005', 82),
    ('Avenida Hermes Fontes 921', 'Aracaju', 'SE', '49020-550', 79),
    ('Rua Mariano Salmeron 177', 'Aracaju', 'SE', '49075-370', 79),
    ('Avenida Mario Jorge Menezes Vieira 2978', 'Aracaju', 'SE', '49035-660', 79),
    ('Avenida Rio Grande do Sul 446', 'Aracaju', 'SE', '49075-510', 79),
    ('Avenida Coelho Campos 1401', 'Aracaju', 'SE', '49055-180', 79),
    ('Rua Vila Cristina 1051', 'Aracaju', 'SE', '49020-150', 79),
    ('Av. Tancredo Neves 3491', 'Aracaju', 'SE', '49095-000', 79),
    ('Rua Sinezia Barreto Moura 05', 'Aracaju', 'SE', '49097-580', 79),
    ('Avenida Barao de Castelo Branco 2135', 'Teresina', 'PI', '64014-325', 86),
    ('Rua Coelho Rodrigues 1921', 'Teresina', 'PI', '64000-120', 86),
    ('Avenida Odilon Araujo 1296', 'Teresina', 'PI', '64017-280', 86),
    ('Avenida Petronio Portela 2052', 'Teresina', 'PI', '64003-600', 86),
    ('Rua Paissandu 1849', 'Teresina', 'PI', '64001-120', 86),
    ('Rua Lisandro Nogueira 1223', 'Teresina', 'PI', '64000-200', 86),
    ('Rua Lisandro Nogueira 506', 'Teresina', 'PI', '64000-110', 86),
    ('Avenida Sao Raimundo 1438', 'Teresina', 'PI', '64017-090', 86),
]


LogFn = Callable[[str], None]


def short(text: Any, n: int = 220) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[: n - 3] + "..."


def normalize_proxy_url(value: str, default_scheme: str = "http") -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"{default_scheme}://{text}"
    return text


class ProxyChainServer:
    """Local HTTP CONNECT chain: client -> local_proxy -> dynamic_proxy -> target."""

    def __init__(self, local_proxy: str, dynamic_proxy: str, log: LogFn | None = None):
        self.local_proxy = normalize_proxy_url(local_proxy)
        self.dynamic_proxy = normalize_proxy_url(dynamic_proxy)
        self.log = log or (lambda _m: None)
        self.lock = threading.Lock()
        self.active_sockets: set[socket.socket] = set()
        self.server: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.url = ""

    def __enter__(self):
        if not self.local_proxy and not self.dynamic_proxy:
            return self
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(64)
        port = self.server.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self) -> None:
        self.stop_event.set()
        if self.server:
            try:
                self.server.close()
            except Exception:
                pass
        self.server = None

    def _track(self, sock: socket.socket) -> None:
        with self.lock:
            self.active_sockets.add(sock)

    def _untrack(self, sock: socket.socket) -> None:
        with self.lock:
            self.active_sockets.discard(sock)

    def _serve(self) -> None:
        assert self.server is not None
        while not self.stop_event.is_set():
            try:
                client, _addr = self.server.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()

    def _handle_client(self, client: socket.socket) -> None:
        upstream = None
        self._track(client)
        try:
            client.settimeout(30)
            head = self._read_http_head(client)
            if not head:
                return
            first_line = head.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
            parts = first_line.split()
            if len(parts) < 3:
                return
            method, target, version = parts[0].upper(), parts[1], parts[2]
            if method == "CONNECT":
                upstream = self._open_chain_to_target(target)
                self._track(upstream)
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._relay(client, upstream)
                return
            rewritten = self._rewrite_plain_request(head, method, target, version)
            upstream = self._open_chain_to_target(self._target_from_plain_request(method, target, head))
            self._track(upstream)
            upstream.sendall(rewritten)
            self._relay(client, upstream)
        except Exception:
            try:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            except Exception:
                pass
        finally:
            self._untrack(client)
            if upstream:
                self._untrack(upstream)
            try:
                client.close()
            except Exception:
                pass

    def _read_http_head(self, client: socket.socket) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 65536:
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk
        return data

    def _target_from_plain_request(self, method: str, target: str, head: bytes) -> str:
        if target.startswith("http://") or target.startswith("https://"):
            parsed = urlparse(target)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            return f"{parsed.hostname}:{port}"
        host = ""
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"host:"):
                host = line.split(b":", 1)[1].strip().decode("latin1")
                break
        return host

    def _rewrite_plain_request(self, head: bytes, method: str, target: str, version: str) -> bytes:
        if not (target.startswith("http://") or target.startswith("https://")):
            return head
        parsed = urlparse(target)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        lines = head.split(b"\r\n")
        lines[0] = f"{method} {path} {version}".encode("latin1")
        return b"\r\n".join(lines)

    def _open_chain_to_target(self, target: str) -> socket.socket:
        with self.lock:
            local_proxy = self.local_proxy
            dynamic_proxy = self.dynamic_proxy
        if local_proxy:
            sock = self._connect_proxy(local_proxy)
            self._send_connect(sock, self._proxy_connect_target(dynamic_proxy) if dynamic_proxy else target)
            if dynamic_proxy:
                self._send_connect(sock, target, proxy_url=dynamic_proxy)
            return sock
        if dynamic_proxy:
            sock = self._connect_proxy(dynamic_proxy)
            self._send_connect(sock, target, proxy_url=dynamic_proxy)
            return sock
        host, port = self._split_host_port(target, 80)
        return socket.create_connection((host, port), timeout=30)

    def _connect_proxy(self, proxy_url: str) -> socket.socket:
        parsed = urlparse(proxy_url)
        if parsed.scheme not in ("http", "https"):
            raise RuntimeError(f"only http/https proxy supported: {proxy_url}")
        host = parsed.hostname
        if not host:
            raise RuntimeError(f"proxy missing host: {proxy_url}")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        raw = socket.create_connection((host, port), timeout=30)
        if parsed.scheme == "https":
            return ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        return raw

    def _proxy_connect_target(self, proxy_url: str) -> str:
        parsed = urlparse(proxy_url)
        if not parsed.hostname:
            raise RuntimeError(f"dynamic proxy missing host: {proxy_url}")
        return f"{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"

    def _send_connect(self, sock: socket.socket, target: str, proxy_url: str = "") -> None:
        headers = [f"CONNECT {target} HTTP/1.1", f"Host: {target}", "Proxy-Connection: keep-alive"]
        auth = self._proxy_auth(proxy_url)
        if auth:
            headers.append(f"Proxy-Authorization: Basic {auth}")
        sock.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("latin1"))
        response = self._read_http_head(sock)
        status = response.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
        if " 200 " not in f" {status} ":
            raise RuntimeError(f"proxy CONNECT failed: {status}")

    def _proxy_auth(self, proxy_url: str) -> str:
        parsed = urlparse(proxy_url)
        if not parsed.username:
            return ""
        username = unquote(parsed.username)
        password = unquote(parsed.password or "")
        return base64.b64encode(f"{username}:{password}".encode()).decode("ascii")

    def _split_host_port(self, target: str, default_port: int) -> tuple[str, int]:
        if target.startswith("["):
            host, rest = target[1:].split("]", 1)
            port = int(rest[1:]) if rest.startswith(":") else default_port
            return host, port
        if ":" in target:
            host, port_s = target.rsplit(":", 1)
            try:
                return host, int(port_s)
            except Exception:
                return target, default_port
        return target, default_port

    def _relay(self, a: socket.socket, b: socket.socket) -> None:
        stop = threading.Event()

        def pump(src: socket.socket, dst: socket.socket) -> None:
            try:
                while not stop.is_set():
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
            finally:
                stop.set()
                try:
                    dst.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

        t1 = threading.Thread(target=pump, args=(a, b), daemon=True)
        t2 = threading.Thread(target=pump, args=(b, a), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()


def build_kookeey_proxy(username: str, password: str, endpoint: str, region: str = "BR") -> tuple[str, str]:
    username = str(username or "").strip()
    password = str(password or "")
    endpoint = str(endpoint or "").strip()
    region = str(region or "BR").strip().upper() or "BR"
    sid = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
    if "://" not in endpoint:
        endpoint = f"http://{endpoint}"
    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    port = parsed.port or 1000
    host_text = f"[{host}]" if ":" in host and not host.startswith("[") else host
    user = quote(username, safe="")
    pw = quote(password, safe="")
    # kookeey: user:pass-REGION-SID@host:port
    url = f"http://{user}:{pw}-{region}-{sid}@{host_text}:{port}"
    return url, sid


def generate_valid_cpf(formatted: bool = False) -> str:
    while True:
        nums = [random.randint(0, 9) for _ in range(9)]
        if len(set(nums)) == 1:
            continue

        def digit(base, factors):
            s = sum(n * f for n, f in zip(base, factors))
            r = s % 11
            return 0 if r < 2 else 11 - r

        d1 = digit(nums, list(range(10, 1, -1)))
        d2 = digit(nums + [d1], list(range(11, 1, -1)))
        cpf = "".join(map(str, nums + [d1, d2]))
        if cpf in {str(i) * 11 for i in range(10)}:
            continue
        if formatted:
            return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
        return cpf


def br_billing() -> dict:
    first = random.choice(FIRST_M + FIRST_F)
    last1 = random.choice(LAST)
    last2 = random.choice([x for x in LAST if x != last1] or LAST)
    name = f"{first} {last1} {last2}"
    line1, city, state, postal, ddd = random.choice(BR_ADDRESSES)
    if random.random() < 0.35 and "Apto" not in line1:
        line1 = f"{line1} Apto {random.randint(11, 1804)}"
    phone = f"+55{ddd}9{random.randint(10000000, 99999999)}"
    slug = re.sub(r"[^a-z]", "", f"{first}{last1}".lower())
    email = f"{slug}{random.randint(10, 99)}{random.choice(['@gmail.com', '@hotmail.com', '@outlook.com', '@yahoo.com.br'])}"
    cpf = generate_valid_cpf(False)
    return {
        "name": name,
        "email": email,
        "phone": phone,
        "country": "BR",
        "line1": line1,
        "city": city,
        "state": state,
        "postal_code": postal,
        "tax_id": cpf,
        "tax_id_formatted": f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}",
    }


def extract_pk(data) -> str:
    if isinstance(data, dict):
        for _k, v in data.items():
            if isinstance(v, str) and v.startswith("pk_"):
                return v
            found = extract_pk(v)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = extract_pk(item)
            if found:
                return found
    return ""


def amount_info(payload) -> str:
    if not isinstance(payload, dict):
        return "?"
    total = payload.get("total_summary")
    if isinstance(total, dict) and total.get("due") is not None:
        return str(total.get("due"))
    invoice = payload.get("invoice")
    if isinstance(invoice, dict) and invoice.get("amount_due") is not None:
        return str(invoice.get("amount_due"))
    return "?"


def pmt_info(payload) -> tuple[list, list, bool]:
    pmt = payload.get("payment_method_types") or []
    ordered = payload.get("ordered_payment_method_types") or []
    has = "pix" in [str(x).lower() for x in list(pmt) + list(ordered)]
    return pmt, ordered, has


def to_openai_pay_url(stripe_hosted_url: str) -> str:
    url = str(stripe_hosted_url or "").strip()
    if url.startswith("https://checkout.stripe.com"):
        return "https://pay.openai.com" + url[len("https://checkout.stripe.com") :]
    return url


def extract_qr(payload, cs_id: str = "") -> dict:
    text = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload
    out = {
        "pix_copy_paste": "",
        "hosted_instructions_url": "",
        "image_url_png": "",
        "image_url_svg": "",
        "hooks_url": "",
        "ebanx_url": "",
        "cs_id": cs_id,
        "submission_state": "",
        "next_action_type": "",
        "setup_intent": "",
        "payment_intent": "",
    }
    m = re.search(r"000201[\w\./\-\*\s]+", text)
    if m:
        out["pix_copy_paste"] = m.group(0).strip()
    m = re.search(r"https://payments\.stripe\.com/qr/instructions/[A-Za-z0-9_\-]+", text)
    if m:
        out["hosted_instructions_url"] = m.group(0)
    m = re.search(r"https://hooks\.stripe\.com/[^\s\"']+", text)
    if m:
        out["hooks_url"] = m.group(0)
    m = re.search(r"https://pix\.ebanx\.com/[^\s\"']+", text)
    if m:
        out["ebanx_url"] = m.group(0)
    m = re.search(r"seti_[A-Za-z0-9]+", text)
    if m:
        out["setup_intent"] = m.group(0)
    m = re.search(r"pi_[A-Za-z0-9]+", text)
    if m and "hcaptcha" not in m.group(0):
        out["payment_intent"] = m.group(0)

    if isinstance(payload, dict):
        sub = find_submission_attempt(payload)
        out["submission_state"] = str(sub.get("state") or "")

        def walk(obj):
            if isinstance(obj, dict):
                na = obj.get("next_action")
                if isinstance(na, dict):
                    if na.get("type"):
                        out["next_action_type"] = str(na.get("type"))
                    box = na.get("pix_display_qr_code") or {}
                    if isinstance(box, dict):
                        for k, dest in (
                            ("data", "pix_copy_paste"),
                            ("hosted_instructions_url", "hosted_instructions_url"),
                            ("image_url_png", "image_url_png"),
                            ("image_url_svg", "image_url_svg"),
                        ):
                            v = box.get(k)
                            if isinstance(v, str) and v and "intent_path" not in v:
                                if not out[dest] or (dest == "pix_copy_paste" and len(v) > len(out[dest])):
                                    out[dest] = v
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(payload)
    return out


def is_success(fields: dict) -> bool:
    data = fields.get("pix_copy_paste") or ""
    if data.startswith("000201"):
        return True
    url = fields.get("hosted_instructions_url") or ""
    if url.startswith("https://payments.stripe.com/qr/instructions/"):
        return True
    if "hooks.stripe.com" in str(fields.get("hooks_url") or ""):
        return True
    return False


def find_submission_attempt(payload) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("submission_attempt", "latest_attempt", "submission"):
        val = payload.get(key)
        if isinstance(val, dict) and val:
            return val
    return {}


def new_http_session(proxy_url: str = "") -> requests.Session:
    try:
        session = CurlCffiSession(impersonate="chrome142")
    except Exception:
        session = requests.Session()
    if hasattr(session, "trust_env"):
        session.trust_env = False
    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    return session


def build_chatgpt_session(access_token: str, proxy_url: str = "", device_id: str = "") -> requests.Session:
    device_id = str(device_id or uuid.uuid4())
    session = new_http_session(proxy_url)
    session.headers.update({
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Authorization": f"Bearer {access_token}",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "Content-Type": "application/json",
        "oai-device-id": device_id,
        "oai-language": "pt-BR",
        "sec-ch-ua": '"Google Chrome";v="146", "Chromium";v="146", "Not.A/Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "Cookie": f"oai-did={device_id}",
    })
    return session


def build_stripe_session(proxy_url: str = "") -> requests.Session:
    session = new_http_session(proxy_url)
    session.headers.update({
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Origin": "https://pay.openai.com",
        "Referer": "https://pay.openai.com/",
        "sec-fetch-site": "cross-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    })
    return session


def stripe_init(stripe: requests.Session, cs_id: str, stripe_pk: str, ctx: dict) -> dict:
    resp = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data={
            "browser_locale": "pt-BR",
            "browser_timezone": "America/Sao_Paulo",
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
            "elements_session_client[locale]": "pt-BR",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"stripe init failed: HTTP {resp.status_code} {short(resp.text)}")
    data = resp.json() or {}
    ctx["config_id"] = str(data.get("config_id") or ctx.get("config_id") or "")
    ctx["init_checksum"] = str(data.get("init_checksum") or "")
    ctx["elements_session_config_id"] = str(data.get("config_id") or ctx.get("elements_session_config_id") or uuid.uuid4())
    return data


def page_get(stripe: requests.Session, cs_id: str, stripe_pk: str, ctx: dict) -> dict:
    resp = stripe.get(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}",
        params={
            "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
            "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[session_id]": ctx["elements_session_id"],
            "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
            "elements_session_client[locale]": "pt-BR",
            "elements_session_client[is_aggregation_expected]": "false",
            "elements_options_client[saved_payment_method][enable_save]": "never",
            "elements_options_client[saved_payment_method][enable_redisplay]": "never",
            "key": stripe_pk,
            "_stripe_version": STRIPE_VERSION_FULL,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"payment_pages get failed: HTTP {resp.status_code} {short(resp.text)}")
    return resp.json() or {}


def chatgpt_approve(access_token: str, cs_id: str, processor: str, proxy_url: str, device_id: str, log: LogFn) -> None:
    cg = build_chatgpt_session(access_token, proxy_url, device_id)
    # lightweight ping
    try:
        cg.post(
            "https://chatgpt.com/backend-api/sentinel/ping",
            json={},
            headers={
                "Referer": "https://chatgpt.com/",
                "x-openai-target-path": "/backend-api/sentinel/ping",
                "x-openai-target-route": "/backend-api/sentinel/ping",
            },
            timeout=TIMEOUT,
        )
    except Exception:
        pass
    last_err = ""
    for attempt in range(1, 4):
        try:
            resp = cg.post(
                "https://chatgpt.com/backend-api/payments/checkout/approve",
                json={"checkout_session_id": cs_id, "processor_entity": processor},
                headers={
                    "Referer": f"https://chatgpt.com/checkout/{processor}/{cs_id}",
                    "x-openai-target-path": "/backend-api/payments/checkout/approve",
                    "x-openai-target-route": "/backend-api/payments/checkout/approve",
                },
                timeout=TIMEOUT,
            )
            log(f"approve attempt {attempt}: HTTP {resp.status_code} {short(resp.text, 120)}")
            if resp.status_code < 400:
                return
            last_err = short(resp.text)
        except Exception as exc:
            last_err = short(exc)
            log(f"approve attempt {attempt} error: {last_err}")
        time.sleep(1.0)
    raise RuntimeError(f"approve failed: {last_err}")


@dataclass
class PixJobConfig:
    access_token: str
    local_proxy: str = "http://127.0.0.1:7897"
    kookeey_user: str = ""
    kookeey_pass: str = ""
    kookeey_endpoint: str = "gate.kookeey.info:1000"
    region: str = "BR"
    direct_proxies: list[str] = field(default_factory=list)
    preflighted_checkout_proxy_url: str = ""




def normalize_pix_proxy_url(value: str) -> str:
    """Accept a URL or host:port:user:pass; default raw arxlabs format to socks5h."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        return raw
    parts = raw.split(":", 3)
    if len(parts) == 4 and parts[1].isdigit():
        host, port, user, password = parts
        return f"socks5h://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    return normalize_proxy_url(raw)


def pix_proxy_with_fresh_sid(proxy_url: str, region: str = "BR") -> tuple[str, str]:
    """Return a proxy URL with a fresh session id when the provider format exposes one.

    Supported common formats:
    - credentials containing ``sid-<old>-t-``
    - URL query parameters named sid/session/session_id/sessionid
    - Kookeey-style password suffix ``-REGION-SID`` before ``@``
    """
    proxy = str(proxy_url or "").strip()
    if not proxy:
        return "", ""
    sid = uuid.uuid4().hex[:8]

    refreshed, count = re.subn(r"(sid-)[^-:@/?#]+(-t-)", rf"\g<1>{sid}\g<2>", proxy, count=1)
    if count:
        return refreshed, sid

    refreshed, count = re.subn(
        r"([?&](?:sid|session|session_id|sessionid)=)[^&#]+",
        rf"\g<1>{sid}",
        proxy,
        count=1,
        flags=re.IGNORECASE,
    )
    if count:
        return refreshed, sid

    normalized_region = re.escape(str(region or "BR").strip().upper() or "BR")
    refreshed, count = re.subn(
        rf"(:[^:@/?#]*-{normalized_region}-)[A-Za-z0-9]{{4,32}}(@)",
        lambda m: f"{m.group(1)}{sid}{m.group(2)}",
        proxy,
        count=1,
        flags=re.IGNORECASE,
    )
    if count:
        return refreshed, sid

    return proxy, "static"


class DirectProxyContext:
    def __init__(self, proxy_url: str):
        self.url = proxy_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def pix_proxy_context(local_proxy: str, dynamic_proxy: str, log: LogFn | None = None):
    dynamic = normalize_pix_proxy_url(dynamic_proxy)
    local = normalize_proxy_url(local_proxy) if local_proxy else ""
    if dynamic.startswith(("socks4://", "socks4a://", "socks5://", "socks5h://")) and not local:
        return DirectProxyContext(dynamic)
    return ProxyChainServer(local, dynamic, log)


def build_pix_dynamic_proxy(cfg: PixJobConfig, stage_index: int) -> tuple[str, str]:
    preflighted = normalize_pix_proxy_url(getattr(cfg, "preflighted_checkout_proxy_url", ""))
    if stage_index == 0 and preflighted:
        return preflighted, "preflighted"
    direct = [normalize_pix_proxy_url(item) for item in (cfg.direct_proxies or []) if str(item or "").strip()]
    if direct:
        idx = stage_index % len(direct)
        proxy, sid = pix_proxy_with_fresh_sid(direct[idx], cfg.region)
        sid_label = f"sid={sid}" if sid and sid != "static" else "static"
        return proxy, f"direct-{idx + 1} {sid_label}"
    return build_kookeey_proxy(cfg.kookeey_user, cfg.kookeey_pass, cfg.kookeey_endpoint, cfg.region)


def generate_pix_trial(cfg: PixJobConfig, log: LogFn | None = None) -> dict:
    log = log or (lambda m: None)
    token = str(cfg.access_token or "").strip()
    if not token:
        raise RuntimeError("缺少 Access Token")
    if not cfg.direct_proxies and (not cfg.kookeey_user or not cfg.kookeey_pass):
        raise RuntimeError("缺少代理配置：direct_proxies 或 kookeey 用户名/密码")

    device_id = str(uuid.uuid4())
    billing = br_billing()
    log(f"账单: {billing['name']} / {billing['city']}-{billing['state']} / CPF {billing['tax_id_formatted']}")
    log(f"手机: {billing['phone']}  邮箱: {billing['email']}")

    # Stage 1: BR create no promo
    dyn1, sid1 = build_pix_dynamic_proxy(cfg, 0)
    log(f"[1/6] BR 创建 checkout（无 promo） sid={sid1}")
    with pix_proxy_context(cfg.local_proxy, dyn1, log) as chain1:
        p1 = chain1.url
        cg = build_chatgpt_session(token, p1, device_id)
        r = cg.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            json={
                "entry_point": "all_plans_pricing_modal",
                "plan_name": "chatgptplusplan",
                "billing_details": {"country": "BR", "currency": "BRL"},
                "checkout_ui_mode": "custom",
            },
            headers={
                "x-openai-target-path": "/backend-api/payments/checkout",
                "x-openai-target-route": "/backend-api/payments/checkout",
            },
            timeout=TIMEOUT,
        )
        log(f"checkout HTTP {r.status_code}")
        if r.status_code >= 400:
            raise RuntimeError(f"checkout failed: {short(r.text)}")
        data = r.json() or {}
        cs_id = str(data.get("checkout_session_id") or data.get("session_id") or data.get("id") or "")
        if not cs_id.startswith("cs_"):
            raise RuntimeError(f"checkout missing cs_id: {short(data)}")
        pk = extract_pk(data) or DEFAULT_STRIPE_PK
        processor = str(data.get("processor_entity") or "openai_llc")
        log(f"cs_id={cs_id} processor={processor}")

        time.sleep(0.8)
        stripe = build_stripe_session(p1)
        ctx = {
            "stripe_js_id": str(uuid.uuid4()),
            "elements_session_id": f"elements_session_{uuid.uuid4().hex[:11]}",
            "elements_session_config_id": str(uuid.uuid4()),
            "config_id": "",
            "init_checksum": "",
        }
        init0 = stripe_init(stripe, cs_id, pk, ctx)
        amt0 = amount_info(init0)
        pmt0, ordered0, has_pix0 = pmt_info(init0)
        log(f"创建后金额={amt0} 支付方式={pmt0} ordered={ordered0} has_pix={has_pix0}")
        if not has_pix0:
            raise RuntimeError(f"创建后未出现 PIX，pmt={pmt0}")

    # Stage 2: BR update free promo (new SID)
    dyn2, sid2 = build_pix_dynamic_proxy(cfg, 1)
    log(f"[2/6] BR update 套试用 promo sid={sid2}")
    with pix_proxy_context(cfg.local_proxy, dyn2, log) as chain2:
        p2 = chain2.url
        cg2 = build_chatgpt_session(token, p2, device_id)
        ur = cg2.post(
            "https://chatgpt.com/backend-api/payments/checkout/update",
            json={
                "checkout_session_id": cs_id,
                "processor_entity": processor,
                "plan_name": "chatgptplusplan",
                "price_interval": "month",
                "seat_quantity": 1,
                "billing_details": {"country": "BR", "currency": "BRL"},
                "promo_campaign": {
                    "promo_campaign_id": "plus-1-month-free",
                    "is_coupon_from_query_param": False,
                },
            },
            headers={
                "x-openai-target-path": "/backend-api/payments/checkout/update",
                "x-openai-target-route": "/backend-api/payments/checkout/update",
            },
            timeout=TIMEOUT,
        )
        log(f"update HTTP {ur.status_code} {short(ur.text, 120)}")
        if ur.status_code >= 400:
            raise RuntimeError(f"update failed: {short(ur.text)}")

    # Stage 3+: stripe with new SID
    dyn3, sid3 = build_pix_dynamic_proxy(cfg, 2)
    log(f"[3/6] Stripe init（套 promo 后） sid={sid3}")
    with pix_proxy_context(cfg.local_proxy, dyn3, log) as chain3:
        p3 = chain3.url
        time.sleep(0.8)
        stripe = build_stripe_session(p3)
        ctx = {
            "stripe_js_id": str(uuid.uuid4()),
            "elements_session_id": f"elements_session_{uuid.uuid4().hex[:11]}",
            "elements_session_config_id": str(uuid.uuid4()),
            "config_id": "",
            "init_checksum": "",
        }
        init_payload = stripe_init(stripe, cs_id, pk, ctx)
        amount = amount_info(init_payload)
        pmt, ordered, has_pix = pmt_info(init_payload)
        log(f"套 promo 后金额={amount} 支付方式={pmt} ordered={ordered} has_pix={has_pix}")
        if not has_pix:
            raise RuntimeError(f"套 promo 后 PIX 丢失，pmt={pmt}")
        if amount not in ("0", "0.0"):
            raise RuntimeError(f"套 promo 后金额不是 0: {amount}")

        hosted = str(init_payload.get("stripe_hosted_url") or "")
        config_id = str(init_payload.get("config_id") or ctx.get("config_id") or "")
        init_checksum = str(init_payload.get("init_checksum") or ctx.get("init_checksum") or "")
        runtime = DEFAULT_STRIPE_RUNTIME_VERSION

        log("[4/6] 创建 PIX payment_method")
        time.sleep(0.6)
        pm = stripe.post(
            "https://api.stripe.com/v1/payment_methods",
            data={
                "billing_details[name]": billing["name"],
                "billing_details[email]": billing["email"],
                "billing_details[phone]": billing["phone"],
                "billing_details[address][country]": "BR",
                "billing_details[address][line1]": billing["line1"],
                "billing_details[address][city]": billing["city"],
                "billing_details[address][postal_code]": billing["postal_code"],
                "billing_details[address][state]": billing["state"],
                "billing_details[tax_id]": billing["tax_id"],
                "type": "pix",
                "guid": uuid.uuid4().hex,
                "muid": uuid.uuid4().hex,
                "sid": uuid.uuid4().hex,
                "payment_user_agent": f"stripe.js/{runtime}; stripe-js-v3/{runtime}; payment-element; deferred-intent",
                "referrer": "https://chatgpt.com",
                "time_on_page": str(random.randint(28000, 65000)),
                "client_attribution_metadata[checkout_session_id]": cs_id,
                "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
                "client_attribution_metadata[checkout_config_id]": config_id,
                "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
                "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
                "client_attribution_metadata[merchant_integration_source]": "elements",
                "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
                "client_attribution_metadata[merchant_integration_version]": "2021",
                "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
                "client_attribution_metadata[payment_method_selection_flow]": "automatic",
                "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
                "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
                "key": pk,
                "_stripe_version": STRIPE_VERSION_FULL,
            },
            timeout=TIMEOUT,
        )
        log(f"pm HTTP {pm.status_code}")
        if pm.status_code >= 400:
            raise RuntimeError(f"create pm failed: {short(pm.text)}")
        pm_id = str((pm.json() or {}).get("id") or "")
        if not pm_id.startswith("pm_"):
            raise RuntimeError(f"bad pm id: {short(pm.text)}")
        log(f"pm_id={pm_id}")

        log("[5/6] confirm PIX")
        time.sleep(0.7)
        return_url = to_openai_pay_url(hosted) or hosted
        conf = stripe.post(
            f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm",
            data={
                "guid": uuid.uuid4().hex,
                "muid": uuid.uuid4().hex,
                "sid": uuid.uuid4().hex,
                "payment_method": pm_id,
                "init_checksum": init_checksum,
                "version": runtime,
                "expected_amount": amount,
                "expected_payment_method_type": "pix",
                "return_url": return_url,
                "elements_session_client[session_id]": ctx["elements_session_id"],
                "elements_session_client[locale]": "pt-BR",
                "elements_session_client[referrer_host]": "chatgpt.com",
                "elements_session_client[is_aggregation_expected]": "false",
                "elements_session_client[elements_init_source]": "custom_checkout",
                "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
                "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
                "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
                "elements_options_client[saved_payment_method][enable_save]": "never",
                "elements_options_client[saved_payment_method][enable_redisplay]": "never",
                "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
                "client_attribution_metadata[checkout_session_id]": cs_id,
                "client_attribution_metadata[checkout_config_id]": config_id,
                "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
                "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
                "client_attribution_metadata[merchant_integration_source]": "checkout",
                "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
                "client_attribution_metadata[merchant_integration_version]": "custom",
                "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
                "client_attribution_metadata[payment_method_selection_flow]": "automatic",
                "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
                "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
                "consent[terms_of_service]": "accepted",
                "key": pk,
                "_stripe_version": STRIPE_VERSION_FULL,
            },
            timeout=TIMEOUT,
        )
        log(f"confirm HTTP {conf.status_code}")
        if conf.status_code >= 400:
            raise RuntimeError(f"confirm failed: {short(conf.text)}")
        conf_data = conf.json() or {}
        fields = extract_qr(conf_data, cs_id)
        sub = find_submission_attempt(conf_data)
        log(f"confirm submission={sub.get('state')}")
        if is_success(fields):
            fields["amount"] = amount
            fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
            fields["billing"] = billing
            log("confirm 后已拿到二维码")
            return {"ok": True, "amount": amount, "fields": fields, "billing": billing}

        log("[6/6] approve + poll QR")
        chatgpt_approve(token, cs_id, processor, p3, device_id, log)

        last_err: dict = {}
        for i in range(1, 16):
            page_data = page_get(stripe, cs_id, pk, ctx)
            fields = extract_qr(page_data, cs_id)
            sub = find_submission_attempt(page_data)
            err = sub.get("error") if isinstance(sub.get("error"), dict) else {}
            log(
                f"poll {i}/15 sub={sub.get('state')} "
                f"err={err.get('code') if err else '-'} success={is_success(fields)}"
            )
            if is_success(fields):
                fields["amount"] = amount
                fields["chatgpt_checkout_url"] = f"https://chatgpt.com/checkout/{processor}/{cs_id}"
                fields["billing"] = billing
                log("成功拿到 PIX 二维码")
                return {"ok": True, "amount": amount, "fields": fields, "billing": billing}
            if sub.get("state") == "failed":
                last_err = err or {}
                pe = last_err.get("payment_error") if isinstance(last_err.get("payment_error"), dict) else {}
                raise RuntimeError(
                    f"approve 后失败: {last_err.get('code')} "
                    f"payment_error={pe.get('code')}/{pe.get('decline_code')}"
                )
            time.sleep(1.0)

        raise RuntimeError("轮询超时，未拿到二维码")
