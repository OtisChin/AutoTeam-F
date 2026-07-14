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
    # Sao Paulo / SP
    ("Avenida Paulista 1578", "Sao Paulo", "SP", "01310-200", 11),
    ("Rua Augusta 2690", "Sao Paulo", "SP", "01412-100", 11),
    ("Rua da Consolacao 3126", "Sao Paulo", "SP", "01416-000", 11),
    ("Avenida Brigadeiro Faria Lima 3477", "Sao Paulo", "SP", "04538-133", 11),
    ("Rua Oscar Freire 379", "Sao Paulo", "SP", "01426-001", 11),
    ("Rua Haddock Lobo 595", "Sao Paulo", "SP", "01414-001", 11),
    ("Avenida Reboucas 3970", "Sao Paulo", "SP", "05402-600", 11),
    ("Rua Bela Cintra 1225", "Sao Paulo", "SP", "01415-001", 11),
    ("Avenida Ibirapuera 3103", "Sao Paulo", "SP", "04029-200", 11),
    ("Rua Vergueiro 3185", "Sao Paulo", "SP", "04101-300", 11),
    ("Avenida Santo Amaro 3487", "Sao Paulo", "SP", "04505-000", 11),
    ("Rua Teodoro Sampaio 2550", "Sao Paulo", "SP", "05406-200", 11),
    ("Avenida Angelica 2345", "Sao Paulo", "SP", "01228-200", 11),
    ("Rua da Consolacao 222", "Sao Paulo", "SP", "01302-000", 11),
    ("Avenida 9 de Julho 3180", "Sao Paulo", "SP", "01406-000", 11),
    ("Rua Pamplona 145", "Sao Paulo", "SP", "01405-000", 11),
    ("Avenida Europa 158", "Sao Paulo", "SP", "01449-000", 11),
    ("Rua Estados Unidos 1456", "Sao Paulo", "SP", "01427-002", 11),
    ("Avenida Brasil 1376", "Sao Paulo", "SP", "01430-001", 11),
    ("Rua Joaquim Floriano 466", "Sao Paulo", "SP", "04534-002", 11),
    ("Avenida Engenheiro Luis Carlos Berrini 105", "Sao Paulo", "SP", "04571-010", 11),
    ("Rua Gomes de Carvalho 1507", "Sao Paulo", "SP", "04547-005", 11),
    ("Avenida das Nacoes Unidas 12901", "Sao Paulo", "SP", "04578-910", 11),
    ("Rua Funchal 418", "Sao Paulo", "SP", "04551-060", 11),
    ("Avenida Magalhaes de Castro 12000", "Sao Paulo", "SP", "05502-001", 11),
    ("Rua dos Pinheiros 498", "Sao Paulo", "SP", "05422-000", 11),
    ("Avenida Europa 655", "Sao Paulo", "SP", "01449-001", 11),
    ("Rua Cincinato Braga 340", "Sao Paulo", "SP", "01333-010", 11),
    ("Avenida Paulista 1000", "Sao Paulo", "SP", "01310-100", 11),
    ("Rua Augusta 1508", "Sao Paulo", "SP", "01304-001", 11),
    # Campinas / SP
    ("Avenida Francisco Glicerio 1239", "Campinas", "SP", "13012-000", 19),
    ("Rua Barreto Leme 1985", "Campinas", "SP", "13010-200", 19),
    ("Avenida Norte Sul 777", "Campinas", "SP", "13025-320", 19),
    ("Rua Coronel Quirino 1632", "Campinas", "SP", "13025-001", 19),
    # Santos / SP
    ("Avenida Ana Costa 555", "Santos", "SP", "11060-003", 13),
    ("Rua Conselheiro Nebias 444", "Santos", "SP", "11045-002", 13),
    # Sao Jose dos Campos / SP
    ("Avenida Sao Joao 2400", "Sao Jose dos Campos", "SP", "12242-000", 12),
    ("Rua Euclides Miragaia 400", "Sao Jose dos Campos", "SP", "12245-820", 12),
    # Rio de Janeiro / RJ
    ("Avenida Atlantica 1702", "Rio de Janeiro", "RJ", "22021-001", 21),
    ("Rua Visconde de Piraja 550", "Rio de Janeiro", "RJ", "22410-003", 21),
    ("Avenida Nossa Senhora de Copacabana 540", "Rio de Janeiro", "RJ", "22020-001", 21),
    ("Rua Barata Ribeiro 502", "Rio de Janeiro", "RJ", "22040-001", 21),
    ("Avenida Vieira Souto 460", "Rio de Janeiro", "RJ", "22420-002", 21),
    ("Rua Prudente de Morais 1145", "Rio de Janeiro", "RJ", "22420-043", 21),
    ("Avenida Epitacio Pessoa 3000", "Rio de Janeiro", "RJ", "22471-003", 21),
    ("Rua Voluntarios da Patria 445", "Rio de Janeiro", "RJ", "22270-000", 21),
    ("Avenida Rio Branco 156", "Rio de Janeiro", "RJ", "20040-003", 21),
    ("Rua da Assembleia 10", "Rio de Janeiro", "RJ", "20011-000", 21),
    ("Avenida Presidente Vargas 3131", "Rio de Janeiro", "RJ", "20210-030", 21),
    ("Rua do Catete 311", "Rio de Janeiro", "RJ", "22220-000", 21),
    ("Avenida das Americas 7000", "Rio de Janeiro", "RJ", "22640-100", 21),
    ("Rua Dias Ferreira 190", "Rio de Janeiro", "RJ", "22431-050", 21),
    ("Avenida Ataulfo de Paiva 1079", "Rio de Janeiro", "RJ", "22440-034", 21),
    ("Rua Jardim Botanico 674", "Rio de Janeiro", "RJ", "22461-000", 21),
    ("Avenida Borges de Medeiros 3407", "Rio de Janeiro", "RJ", "22470-001", 21),
    ("Rua Sao Clemente 298", "Rio de Janeiro", "RJ", "22260-000", 21),
    # Niteroi / RJ
    ("Rua da Conceicao 188", "Niteroi", "RJ", "24020-086", 21),
    ("Avenida Ernani do Amaral Peixoto 500", "Niteroi", "RJ", "24020-070", 21),
    # Belo Horizonte / MG
    ("Avenida Afonso Pena 1500", "Belo Horizonte", "MG", "30130-007", 31),
    ("Rua da Bahia 1148", "Belo Horizonte", "MG", "30160-011", 31),
    ("Avenida do Contorno 6480", "Belo Horizonte", "MG", "30110-044", 31),
    ("Rua dos Timbiras 1697", "Belo Horizonte", "MG", "30140-061", 31),
    ("Avenida Getulio Vargas 1420", "Belo Horizonte", "MG", "30112-021", 31),
    ("Rua da Paisagem 220", "Nova Lima", "MG", "34006-059", 31),
    ("Avenida Raja Gabaglia 2000", "Belo Horizonte", "MG", "30350-563", 31),
    ("Rua Claudio Manoel 1162", "Belo Horizonte", "MG", "30140-100", 31),
    ("Avenida Bias Fortes 382", "Belo Horizonte", "MG", "30170-010", 31),
    ("Rua Sao Paulo 1401", "Belo Horizonte", "MG", "30170-131", 31),
    # Uberlandia / MG
    ("Avenida Joao Naves de Avila 1331", "Uberlandia", "MG", "38400-042", 34),
    ("Rua Santos Dumont 500", "Uberlandia", "MG", "38400-062", 34),
    # Curitiba / PR
    ("Rua XV de Novembro 1299", "Curitiba", "PR", "80060-000", 41),
    ("Avenida Sete de Setembro 2775", "Curitiba", "PR", "80230-010", 41),
    ("Rua Marechal Deodoro 630", "Curitiba", "PR", "80010-010", 41),
    ("Avenida Batel 1750", "Curitiba", "PR", "80420-090", 41),
    ("Rua Comendador Araujo 731", "Curitiba", "PR", "80420-000", 41),
    ("Avenida Candido de Abreu 526", "Curitiba", "PR", "80530-000", 41),
    ("Rua Visconde do Rio Branco 1480", "Curitiba", "PR", "80420-210", 41),
    ("Avenida Iguacu 2820", "Curitiba", "PR", "80240-030", 41),
    # Londrina / PR
    ("Avenida Higienopolis 1000", "Londrina", "PR", "86020-080", 43),
    ("Rua Sergipe 800", "Londrina", "PR", "86010-380", 43),
    # Brasilia / DF
    ("Setor Comercial Sul Quadra 2 Bloco C", "Brasilia", "DF", "70302-000", 61),
    ("SHS Quadra 6 Bloco A", "Brasilia", "DF", "70316-000", 61),
    ("SCLS 210 Bloco B", "Brasilia", "DF", "70273-520", 61),
    ("SQN 308 Bloco A", "Brasilia", "DF", "70747-010", 61),
    ("SHIN QL 10 Conjunto 4", "Brasilia", "DF", "71525-045", 61),
    ("SBN Quadra 1 Bloco A", "Brasilia", "DF", "70040-010", 61),
    ("CLN 202 Bloco B", "Brasilia", "DF", "70832-525", 61),
    ("SEPS 705/905 Bloco C", "Brasilia", "DF", "70390-055", 61),
    # Goiania / GO
    ("Avenida Goias 200", "Goiania", "GO", "74010-010", 62),
    ("Rua 18 500", "Goiania", "GO", "74120-080", 62),
    ("Avenida T-63 1500", "Goiania", "GO", "74230-100", 62),
    ("Rua 87 500", "Goiania", "GO", "74093-300", 62),
    # Recife / PE
    ("Avenida Boa Viagem 5200", "Recife", "PE", "51030-000", 81),
    ("Rua da Aurora 1253", "Recife", "PE", "50050-000", 81),
    ("Avenida Conselheiro Aguiar 2333", "Recife", "PE", "51111-010", 81),
    ("Rua Sete de Setembro 235", "Recife", "PE", "50050-030", 81),
    ("Avenida Governador Agamenon Magalhaes 2655", "Recife", "PE", "52020-000", 81),
    ("Rua do Hospicio 371", "Recife", "PE", "50050-050", 81),
    # Salvador / BA
    ("Rua Chile 21", "Salvador", "BA", "40026-032", 71),
    ("Avenida Tancredo Neves 2539", "Salvador", "BA", "41820-021", 71),
    ("Rua da Graca 300", "Salvador", "BA", "40150-055", 71),
    ("Rua Alagoinhas 400", "Salvador", "BA", "41940-620", 71),
    ("Avenida Orlando Gomes 1000", "Salvador", "BA", "41650-010", 71),
    ("Avenida Anita Garibaldi 1800", "Salvador", "BA", "41940-450", 71),
    # Fortaleza / CE
    ("Avenida Beira Mar 4060", "Fortaleza", "CE", "60165-121", 85),
    ("Rua Barao do Rio Branco 1071", "Fortaleza", "CE", "60025-061", 85),
    ("Avenida Dom Luis 1200", "Fortaleza", "CE", "60160-230", 85),
    ("Rua Monsenhor Tabosa 1100", "Fortaleza", "CE", "60165-010", 85),
    ("Avenida Santos Dumont 3131", "Fortaleza", "CE", "60175-172", 85),
    ("Rua Dragao do Mar 81", "Fortaleza", "CE", "60060-390", 85),
    # Porto Alegre / RS
    ("Avenida Borges de Medeiros 1501", "Porto Alegre", "RS", "90110-150", 51),
    ("Rua dos Andradas 1234", "Porto Alegre", "RS", "90020-008", 51),
    ("Avenida Ipiranga 6681", "Porto Alegre", "RS", "90619-900", 51),
    ("Rua Mostardeiro 322", "Porto Alegre", "RS", "90430-000", 51),
    ("Avenida Independencia 1205", "Porto Alegre", "RS", "90035-075", 51),
    ("Rua Padre Chagas 66", "Porto Alegre", "RS", "90570-080", 51),
    # Florianopolis / SC
    ("Avenida Beira Mar Norte 1426", "Florianopolis", "SC", "88015-700", 48),
    ("Rua Felipe Schmidt 415", "Florianopolis", "SC", "88010-001", 48),
    ("Avenida Mauro Ramos 1501", "Florianopolis", "SC", "88020-301", 48),
    ("Rua Bocaiuva 2125", "Florianopolis", "SC", "88015-530", 48),
    # Joinville / SC
    ("Rua do Principe 123", "Joinville", "SC", "89201-000", 47),
    ("Avenida Getulio Vargas 500", "Joinville", "SC", "89202-000", 47),
    # Manaus / AM
    ("Avenida Eduardo Ribeiro 520", "Manaus", "AM", "69010-001", 92),
    ("Rua 10 de Julho 500", "Manaus", "AM", "69010-060", 92),
    ("Avenida Djalma Batista 1661", "Manaus", "AM", "69050-010", 92),
    ("Rua Ramos Ferreira 1200", "Manaus", "AM", "69010-120", 92),
    # Belem / PA
    ("Avenida Presidente Vargas 800", "Belem", "PA", "66017-000", 91),
    ("Rua Santo Antonio 300", "Belem", "PA", "66010-095", 91),
    ("Avenida Magalhaes Barata 1000", "Belem", "PA", "66630-040", 91),
    # Natal / RN
    ("Avenida Engenheiro Roberto Freire 3100", "Natal", "RN", "59090-000", 84),
    ("Rua Joao Pessoa 300", "Natal", "RN", "59025-500", 84),
    # Joao Pessoa / PB
    ("Avenida Epitacio Pessoa 1251", "Joao Pessoa", "PB", "58030-001", 83),
    ("Rua Duque de Caxias 500", "Joao Pessoa", "PB", "58010-820", 83),
    # Maceio / AL
    ("Avenida Fernandes Lima 2500", "Maceio", "AL", "57050-000", 82),
    ("Rua do Comercio 300", "Maceio", "AL", "57020-000", 82),
    # Aracaju / SE
    ("Avenida Beira Mar 1000", "Aracaju", "SE", "49025-040", 79),
    ("Rua Laranjeiras 500", "Aracaju", "SE", "49010-000", 79),
    # Vitoria / ES
    ("Avenida Nossa Senhora da Penha 1495", "Vitoria", "ES", "29045-402", 27),
    ("Rua Sete de Setembro 50", "Vitoria", "ES", "29015-000", 27),
    # Campo Grande / MS
    ("Avenida Afonso Pena 4000", "Campo Grande", "MS", "79002-075", 67),
    ("Rua 14 de Julho 1800", "Campo Grande", "MS", "79002-330", 67),
    # Cuiaba / MT
    ("Avenida Historiador Rubens de Mendonca 2000", "Cuiaba", "MT", "78050-000", 65),
    ("Rua Barao de Melgaco 3000", "Cuiaba", "MT", "78005-300", 65),
    # Teresina / PI
    ("Avenida Frei Serafim 2000", "Teresina", "PI", "64001-020", 86),
    ("Rua Coelho Rodrigues 500", "Teresina", "PI", "64000-080", 86),
    # Sao Luis / MA
    ("Avenida dos Holandeses 1", "Sao Luis", "MA", "65075-650", 98),
    ("Rua Grande 500", "Sao Luis", "MA", "65070-260", 98),
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
    direct = [normalize_pix_proxy_url(item) for item in (cfg.direct_proxies or []) if str(item or "").strip()]
    if direct:
        idx = stage_index % len(direct)
        return direct[idx], f"direct-{idx + 1}"
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
