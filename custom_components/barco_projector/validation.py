"""Validation of the addresses entered in the configuration forms."""

from __future__ import annotations

import ipaddress
import re

# One DNS label: letters, digits and hyphens, not starting or ending with a hyphen.
_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
MAX_HOSTNAME_LENGTH = 253


def _is_ip_address(value: str) -> bool:
    """Return whether ``value`` is an IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def is_valid_host(value: str) -> bool:
    """Return whether ``value`` is a bare IP address or hostname.

    Anything else, such as a URL, a path or an address with a port, can only
    fail to connect, so the form says so straight away.
    """
    if _is_ip_address(value):
        return True
    hostname = value[:-1] if value.endswith(".") else value
    if not hostname or len(hostname) > MAX_HOSTNAME_LENGTH:
        return False
    labels = hostname.split(".")
    # An all-numeric last label is a mistyped IP address, not a hostname.
    if labels[-1].isdigit():
        return False
    return all(_LABEL.match(label) for label in labels)
