import asyncio
import hashlib
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.core.errors import Problem

MAX_INPUT_BYTES = 1_000_000
MAX_BATCH_BYTES = 10_000_000
MAX_BATCH_FILES = 200


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenVault:
    def __init__(self, key: SecretStr | None) -> None:
        if key is None or not key.get_secret_value():
            raise Problem(503, "KEY_NOT_CONFIGURED", "请先在服务端配置凭据加密密钥。")
        try:
            self._fernet = Fernet(key.get_secret_value().encode())
        except (ValueError, TypeError):
            raise Problem(503, "INVALID_KEY", "服务端凭据密钥配置无效。") from None

    def encrypt(self, token: SecretStr) -> str:
        return self._fernet.encrypt(token.get_secret_value().encode()).decode()

    def decrypt(self, ciphertext: str) -> SecretStr:
        try:
            return SecretStr(self._fernet.decrypt(ciphertext.encode()).decode())
        except (InvalidToken, ValueError):
            raise Problem(403, "CREDENTIAL_UNAVAILABLE", "凭据已不可用，请重新授权。") from None


@dataclass(frozen=True)
class SafeTarget:
    """A checked destination. Fetchers MUST pin connections to these addresses."""

    url: str
    hostname: str
    addresses: tuple[str, ...]


Resolver = Callable[[str], Awaitable[list[str]]]


async def resolve_addresses(hostname: str) -> list[str]:
    records = await asyncio.get_running_loop().getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    return list({str(record[4][0]) for record in records})


async def validate_destination(
    url: str, *, allowed_hosts: frozenset[str], resolver: Resolver = resolve_addresses
) -> SafeTarget:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if (
            len(url) > 2048
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)
            or "\\" in url
            or parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or host not in allowed_hosts
            or not re.fullmatch(r"[a-z0-9.-]+", host)
        ):
            raise ValueError
        async with asyncio.timeout(3):
            addresses = await resolver(host)
        if not addresses or len(addresses) > 32:
            raise ValueError
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global or ip.is_multicast or ip.is_unspecified:
                raise ValueError
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
                if not ip.ipv4_mapped.is_global:
                    raise ValueError
    except (ValueError, OSError, TimeoutError):
        raise Problem(400, "UNSAFE_URL", "网址或网络目标不受支持，请使用公开允许的来源。") from None
    normalized = urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    return SafeTarget(normalized, host, tuple(sorted(set(addresses))))
