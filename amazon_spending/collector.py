"""Backward-compatibility shim.

The Amazon collector has moved to amazon_spending.retailers.amazon.
Import from there directly, or use the retailer registry:

    from amazon_spending.retailers import REGISTRY
    result = REGISTRY["amazon"].collect(conn, output_dir, order_limit=50)
"""
from __future__ import annotations

from .retailers.amazon import AmazonCollector, collect_amazon
from .retailers.base import (
    CollectResult,
    ParsedItem,
    ParsedOrder,
    ParsedRetailerTransaction,
    ParsedRetailerTransaction as ParsedAmazonTransaction,  # legacy alias
)

__all__ = [
    "collect_amazon",
    "AmazonCollector",
    "CollectResult",
    "ParsedOrder",
    "ParsedItem",
    "ParsedAmazonTransaction",
    "ParsedRetailerTransaction",
]
