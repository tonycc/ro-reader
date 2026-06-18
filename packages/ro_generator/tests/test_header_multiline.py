"""Header multiline field splitting tests."""

from __future__ import annotations

from ro_generator.header_multiline import split_manufacturer_address_lines, split_ship_to_lines


def test_manufacturer_split_handles_large_space_separators() -> None:
    raw = (
        "WEIHAI E-MAX SPORT APPARATUS CO.LTD"
        "                                                       "
        "NO. 93 GRAPE BEACH ROAD"
        "                                                                        "
        "SUNJIATUAN TOWN, WEIHAI，SHANGDONG, CHINA"
    )

    assert split_manufacturer_address_lines(raw) == {
        "manufacturer": "WEIHAI E-MAX SPORT APPARATUS CO.LTD",
        "manufacturer_address": "NO. 93 GRAPE BEACH ROAD",
        "manufacturer_address_2": "SUNJIATUAN TOWN, WEIHAI，SHANGDONG, CHINA",
    }


def test_ship_to_split_drops_repeated_combined_address_line() -> None:
    raw = (
        "Rather Outdoors Corporation,\n"
        "40 Industrial Road,Dauphin, MB R7N 2V2\n"
        "Rather Outdoors Corporation, 40 Industrial Road,Dauphin, MB R7N 2V2"
    )

    assert split_ship_to_lines(raw) == {
        "ship_to": "Rather Outdoors Corporation,",
        "ship_to_line2": "40 Industrial Road,Dauphin, MB R7N 2V2",
    }
