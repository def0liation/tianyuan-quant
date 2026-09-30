from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.core import portfolio_store


def _zip(*entries):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


@pytest.mark.parametrize("limit,raw", [
    ("MAX_XLSX_EXPANDED_BYTES", _zip(("xl/sharedStrings.xml", b"x" * 300))),
    ("MAX_XLSX_ZIP_ENTRIES", _zip(("a.xml", b"a"), ("b.xml", b"b"))),
], ids=["expanded_bytes", "entry_count"])
def test_xlsx_resource_limits_reject_before_workbook_reader(monkeypatch, limit, raw):
    monkeypatch.setattr(portfolio_store, limit, 1, raising=False)
    called = []

    def reader(*args, **kwargs):
        called.append(True)
        raise AssertionError("Workbook reader must not receive an oversized archive")

    monkeypatch.setattr("openpyxl.load_workbook", reader)
    with pytest.raises(ValueError, match="XLSX archive exceeds"):
        portfolio_store.decode_table(raw, "holdings.xlsx")
    assert called == []


def test_malformed_xlsx_is_a_controlled_validation_error():
    with pytest.raises(ValueError, match="Invalid XLSX archive"):
        portfolio_store.decode_table(b"not a zip workbook", "holdings.xlsx")
