"""Tests for the UDP discovery answers, which anyone on the network can send."""

from __future__ import annotations

from custom_components.barco_projector.discovery import (
    MAX_ANSWERS,
    MAX_FIELD_LENGTH,
    DiscoveredProjector,
    _DiscoveryProtocol,
    parse_answer,
)


def _answer(**fields: str) -> bytes:
    """Build an answer the way a projector sends it."""
    return b"".join(f"{key}={value}".encode() + b"\x00" for key, value in fields.items())


def test_series_2_answer() -> None:
    """A series 2 answer gives model and hostname; the label shows both."""
    found: dict[str, DiscoveredProjector] = {}
    _DiscoveryProtocol(found).datagram_received(
        _answer(hostname="zaal1", **{"ip-address": "192.0.2.10"}, type="DP2K-6E"),
        ("192.0.2.10", 40961),
    )
    assert found == {
        "192.0.2.10": DiscoveredProjector(host="192.0.2.10", hostname="zaal1", model="DP2K-6E")
    }
    assert found["192.0.2.10"].label == "DP2K-6E - 192.0.2.10 (zaal1)"


def test_sender_address_wins() -> None:
    """An answer cannot point the form at another address than its sender."""
    found: dict[str, DiscoveredProjector] = {}
    _DiscoveryProtocol(found).datagram_received(
        _answer(**{"ip-address": "198.51.100.66"}, type="DP2K-6E"), ("192.0.2.10", 40961)
    )
    assert list(found) == ["192.0.2.10"]


def test_mac_address_is_not_kept() -> None:
    """The MAC address of a series 1 answer is neither stored nor returned."""
    values = parse_answer(
        _answer(hostname="dp100", **{"ip-address": "192.0.2.10", "mac-address": "00:11:22:33"})
    )
    assert values == {"hostname": "dp100", "ip-address": "192.0.2.10"}


def test_fields_are_cleaned_and_capped() -> None:
    """Control characters go, and oversized fields are dropped."""
    values = parse_answer(_answer(hostname="zaal\t1\x7f", type="X" * (MAX_FIELD_LENGTH + 1)))
    assert values == {"hostname": "zaal1"}


def test_number_of_answers_is_capped() -> None:
    """A flood of answers cannot grow the list without limit."""
    found: dict[str, DiscoveredProjector] = {}
    protocol = _DiscoveryProtocol(found)
    for index in range(MAX_ANSWERS + 10):
        protocol.datagram_received(_answer(type="DP2K-6E"), (f"192.0.2.{index + 1}", 40961))
    assert len(found) == MAX_ANSWERS
    # A projector already in the list may still update its answer.
    protocol.datagram_received(_answer(type="DP4K-32B"), ("192.0.2.1", 40961))
    assert found["192.0.2.1"].model == "DP4K-32B"
