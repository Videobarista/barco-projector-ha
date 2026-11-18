"""Tests for the address check in the configuration forms."""

from __future__ import annotations

import pytest

from custom_components.barco_projector.validation import is_valid_host


@pytest.mark.parametrize(
    "host",
    [
        "192.0.2.10",
        "2001:db8::10",
        "fe80::1%eth0",
        "projector",
        "dp2k-6e.local",
        "screen1.cinema.example.",
    ],
)
def test_valid_hosts(host: str) -> None:
    """Bare IP addresses and hostnames are accepted."""
    assert is_valid_host(host)


@pytest.mark.parametrize(
    "host",
    [
        "",
        "http://192.0.2.10",
        "192.0.2.10:43728",
        "192.0.2.10/index.html",
        "192.0.2.300",
        "projector name",
        "-projector",
        "projector-",
        "a" * 64,
        ".".join(["a" * 63] * 4) + ".com",
        "[2001:db8::10]",
    ],
)
def test_invalid_hosts(host: str) -> None:
    """URLs, ports, paths, typos and oversized names are refused."""
    assert not is_valid_host(host)
