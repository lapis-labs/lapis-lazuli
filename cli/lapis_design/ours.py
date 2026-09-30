"""Decide which source hosts belong to the local render under test."""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


_IPV4_BLOCKS = tuple(ipaddress.ip_network(block) for block in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "0.0.0.0/32",
))
_IPV6_BLOCKS = tuple(ipaddress.ip_network(block) for block in ("::1/128", "fc00::/7"))


def _private_address(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in block for block in (_IPV4_BLOCKS if address.version == 4 else _IPV6_BLOCKS))


def literal_ours(host: str) -> bool:
    """Only literal local names and the specifically allowed private IP ranges are ours."""
    return host == "localhost" or host.endswith(".localhost") or _private_address(host)


def source_is_ours(host: str, addresses: list[str] | None) -> bool:
    """A pinned .test source is ours only if every resolved address is private."""
    return literal_ours(host) or (host.endswith(".test") and bool(addresses) and
                                  all(_private_address(address) for address in addresses))


def canonical_start_url(url: str) -> str:
    """Use the one canonical .test name for both the browser target and recorded source."""
    parts = urlsplit(url)
    host = (parts.hostname or "").rstrip(".").lower()
    if not host.endswith(".test"):
        return url
    if parts.username or parts.password:
        raise ValueError("a .test source URL cannot contain credentials")
    netloc = host + (f":{parts.port}" if parts.port is not None else "")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


@dataclass(frozen=True)
class SourcePin:
    host: str
    addresses: tuple[str, ...]
    address: str


def resolve_addresses(host: str) -> list[str]:
    """Resolve once; retain all unique addresses in resolver order for the source record."""
    return list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)))


def pin_source(url: str, *, resolved: list[str] | None = None, pinned_address: str | None = None) -> SourcePin | None:
    """Pin a starting .test URL; optionally reuse the same run's resolution and address."""
    parts = urlsplit(url)
    host = (parts.hostname or "").rstrip(".").lower()
    if not host.endswith(".test") or parts.scheme not in ("http", "https"):
        return None
    try:
        addresses = resolved if resolved is not None else resolve_addresses(host)
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
    except (OSError, ValueError):
        return None
    if not source_is_ours(host, addresses):
        return None
    for address in addresses:
        if pinned_address is not None and address != pinned_address:
            continue
        try:
            connection = socket.create_connection((address, port), timeout=1)
        except OSError:
            continue
        connection.close()
        return SourcePin(host, tuple(addresses), address)
    return None


def chromium_args(pins: list[SourcePin], args: list[str] | None = None) -> list[str]:
    """Merge caller and run rules into one switch; pinned mappings take precedence."""
    args = list(args or [])
    rules = [f"MAP {pin.host} {'[' + pin.address + ']' if ':' in pin.address else pin.address}"
             for pin in pins]
    bypass = [pin.host for pin in pins]
    other = []
    for arg in args:
        if arg.startswith("--host-resolver-rules="):
            rules.append(arg.partition("=")[2])
        elif arg.startswith("--proxy-bypass-list="):
            bypass.extend(arg.partition("=")[2].split(","))
        else:
            other.append(arg)
    if rules:
        other.append("--host-resolver-rules=" + ", ".join(rules))
    if bypass:
        other.append("--proxy-bypass-list=" + ",".join(dict.fromkeys(bypass)))
    return other