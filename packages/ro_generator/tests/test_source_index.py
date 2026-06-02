"""Source index 测试：双向溯源数据结构 + builder。"""

from __future__ import annotations

from ro_generator.source_index import (
    COMPUTED_SHEET,
    SourceIndex,
    SourceIndexBuilder,
    SourceLocation,
)


class TestSourceLocation:
    def test_basic(self) -> None:
        loc = SourceLocation(sheet="PO record", row=18, field="SAP Number")
        assert loc.sheet == "PO record"
        assert loc.row == 18
        assert loc.field == "SAP Number"
        assert not loc.is_computed

    def test_computed(self) -> None:
        loc = SourceLocation(sheet=COMPUTED_SHEET, row=None, field="amount")
        assert loc.is_computed

    def test_equality(self) -> None:
        a = SourceLocation("PO record", 18, "SAP Number")
        b = SourceLocation("PO record", 18, "SAP Number")
        c = SourceLocation("PO record", 19, "SAP Number")
        assert a == b
        assert a != c


class TestSourceIndexBuilder:
    def test_empty(self) -> None:
        idx = SourceIndexBuilder().build()
        assert len(idx) == 0
        assert idx.lookup_source("D18") is None
        assert idx.lookup_doc_cells(SourceLocation("x", 1, "f")) == ()

    def test_add_and_lookup(self) -> None:
        b = SourceIndexBuilder()
        loc1 = SourceLocation("PO record", 18, "SAP Number")
        loc2 = SourceLocation("PO record", 19, "SAP Number")
        b.add("D18", loc1)
        b.add("D19", loc2)
        idx = b.build()
        assert idx.lookup_source("D18") == loc1
        assert idx.lookup_source("D19") == loc2
        assert idx.lookup_source("D99") is None

    def test_reverse_lookup(self) -> None:
        b = SourceIndexBuilder()
        loc = SourceLocation("PO record", 18, "FINALQTY")
        # 多个文档单元格都来自同一个源
        b.add("F18", loc)
        b.add("F28", loc)  # 比如月度切片后的另一处
        idx = b.build()
        cells = idx.lookup_doc_cells(loc)
        assert set(cells) == {"F18", "F28"}

    def test_add_computed(self) -> None:
        b = SourceIndexBuilder()
        b.add_computed("H18", "amount")
        idx = b.build()
        loc = idx.lookup_source("H18")
        assert loc is not None
        assert loc.is_computed
        assert loc.field == "amount"

    def test_iter_preserves_order(self) -> None:
        b = SourceIndexBuilder()
        loc1 = SourceLocation("PO record", 18, "SAP Number")
        loc2 = SourceLocation("PO record", 19, "SAP Number")
        b.add("D18", loc1)
        b.add("D19", loc2)
        idx = b.build()
        cells = [cell for cell, _ in idx]
        assert cells == ["D18", "D19"]


class TestSourceIndexImmutable:
    def test_entries_is_tuple(self) -> None:
        idx = SourceIndex(entries=())
        assert isinstance(idx.entries, tuple)

    def test_builder_changes_dont_affect_built(self) -> None:
        b = SourceIndexBuilder()
        b.add("D18", SourceLocation("PO record", 18, "SAP Number"))
        idx = b.build()
        # build 后再加，原 idx 不受影响
        b.add("D19", SourceLocation("PO record", 19, "SAP Number"))
        assert len(idx) == 1
