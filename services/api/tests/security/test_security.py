import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.errors import Problem
from app.core.security import TokenVault, validate_destination


async def public_resolver(hostname: str) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "https://169.254.169.254/",
        "https://10.0.0.1/",
        "https://chatgpt.com:8080/share/x",
        "file:///etc/passwd",
        "https://chatgpt.com.evil.com/share/x",
        "https://user:secret@chatgpt.com/share/x",
        "https://chatgpt.com\\@evil.com/",
        "https://chatgpt.com/\nfoo",
    ],
)
async def test_unsafe_url_rejected_before_resolution(url: str) -> None:
    async def forbidden_resolution(hostname: str) -> list[str]:
        pytest.fail("Unsafe URL should never be resolved")

    with pytest.raises(Problem) as error:
        await validate_destination(
            url, allowed_hosts=frozenset({"chatgpt.com"}), resolver=forbidden_resolution
        )
    assert error.value.code == "UNSAFE_URL"


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.0.0.2"],
        ["169.254.169.254"],
        ["::1"],
        ["fc00::1"],
        ["::ffff:127.0.0.1"],
        ["93.184.216.34", "192.168.1.1"],
        [],
        ["224.0.0.1"],
    ],
)
async def test_private_or_mixed_dns_is_rejected(addresses: list[str]) -> None:
    async def resolver(hostname: str) -> list[str]:
        return addresses

    with pytest.raises(Problem, match="UNSAFE_URL"):
        await validate_destination(
            "https://chatgpt.com/share/123",
            allowed_hosts=frozenset({"chatgpt.com"}),
            resolver=resolver,
        )


async def test_resolved_addresses_are_returned_for_connection_pinning() -> None:
    result = await validate_destination(
        "https://chatgpt.com/share/123#frag",
        allowed_hosts=frozenset({"chatgpt.com"}),
        resolver=public_resolver,
    )
    assert result.url == "https://chatgpt.com/share/123"
    assert result.addresses == ("93.184.216.34",)


def test_vault_round_trip_wrong_key_and_missing_key() -> None:
    vault = TokenVault(SecretStr(Fernet.generate_key().decode()))
    token = SecretStr("github-test-secret")
    ciphertext = vault.encrypt(token)
    assert "github-test-secret" not in ciphertext
    assert vault.decrypt(ciphertext) == token
    other = TokenVault(SecretStr(Fernet.generate_key().decode()))
    with pytest.raises(Problem, match="CREDENTIAL_UNAVAILABLE"):
        other.decrypt(ciphertext)
    with pytest.raises(Problem, match="KEY_NOT_CONFIGURED"):
        TokenVault(None)
