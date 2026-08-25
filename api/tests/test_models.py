from __future__ import annotations

from sqlalchemy import BigInteger, Float, Numeric

from app.db.models import Base


def test_money_columns_are_bigint_and_direct_metadata_has_no_float_or_numeric() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.name.endswith("_paise"):
                assert isinstance(column.type, BigInteger), (
                    f"{table.name}.{column.name} must be BigInteger"
                )
            assert not isinstance(column.type, (Float, Numeric)), (
                f"{table.name}.{column.name} must not use Float or Numeric"
            )
