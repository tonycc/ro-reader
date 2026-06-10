from __future__ import annotations

from typing import Final


SHIP_TO_HEADER_FIELDS: Final[tuple[str, str, str]] = (
    "ship_to",
    "ship_to_line2",
    "ship_to_line3",
)

MANUFACTURER_ADDRESS_FIELDS: Final[tuple[str, str]] = (
    "manufacturer_address",
    "manufacturer_address_2",
)


def split_header_text(value: str | None, max_lines: int) -> tuple[str, ...]:
    if not value:
        return tuple("" for _ in range(max_lines))

    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return tuple("" for _ in range(max_lines))

    lines = [part.strip() for part in normalized.split("\n") if part.strip()]
    if len(lines) <= 1:
        lines = _split_address_like_text(normalized)

    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [" ".join(lines[max_lines - 1 :]).strip()]

    padded = lines + [""] * (max_lines - len(lines))
    return tuple(padded[:max_lines])


def split_ship_to_lines(value: str | None) -> dict[str, str]:
    parts = split_header_text(value, len(SHIP_TO_HEADER_FIELDS))
    return {
        field_name: part
        for field_name, part in zip(SHIP_TO_HEADER_FIELDS, parts)
        if part
    }


def split_manufacturer_address_lines(value: str | None) -> dict[str, str]:
    parts = split_header_text(value, len(MANUFACTURER_ADDRESS_FIELDS))
    return {
        field_name: part
        for field_name, part in zip(MANUFACTURER_ADDRESS_FIELDS, parts)
        if part
    }


def _split_address_like_text(value: str) -> list[str]:
    segments = [segment.strip() for segment in value.split(",") if segment.strip()]
    if len(segments) <= 1:
        return [value]
    if len(segments) == 2:
        return segments
    if len(segments) == 3:
        return [segments[0], segments[1], segments[2]]
    return [segments[0], ", ".join(segments[1:-1]), segments[-1]]

