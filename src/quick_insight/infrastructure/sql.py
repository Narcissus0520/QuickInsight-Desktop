from __future__ import annotations


def quote_identifier(identifier: str) -> str:
    if not identifier:
        raise ValueError("SQL identifier must not be empty.")
    return '"' + identifier.replace('"', '""') + '"'
