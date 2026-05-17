"""Exceptions for NetBox Asset Tag."""

from __future__ import annotations


class NetBoxApiError(Exception):
    """Base NetBox API error."""


class NetBoxAuthenticationError(NetBoxApiError):
    """Raised when NetBox rejects the supplied credentials."""

