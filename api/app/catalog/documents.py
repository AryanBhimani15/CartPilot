from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def product_document(product: Mapping[str, object]) -> str:
    """Compose the category-aware text shared by lexical and semantic retrieval.

    Footwear facts are included only when the product actually has the nested footwear
    attribute block. This preserves the taxonomy boundary established in T-003b.
    """
    attrs = product["attrs"]
    if not isinstance(attrs, Mapping):
        raise ValueError("Product attrs must be a mapping")

    fields: list[object] = [
        product["title"],
        product["brand"],
        product["category"],
        product["subcategory"],
        attrs.get("use_case", ""),
        attrs.get("gender", ""),
        product["description"],
    ]
    footwear = attrs.get("footwear")
    if isinstance(footwear, Mapping):
        fields.extend(footwear.values())
    return " ".join(str(value) for value in fields if value not in (None, ""))


def product_document_from_values(
    *,
    title: str,
    brand: str,
    category: str,
    subcategory: str,
    description: str,
    attrs: Mapping[str, Any],
) -> str:
    """Adapter for ORM values without making the pure composer depend on SQLAlchemy."""
    return product_document(
        {
            "title": title,
            "brand": brand,
            "category": category,
            "subcategory": subcategory,
            "description": description,
            "attrs": dict(attrs),
        }
    )
