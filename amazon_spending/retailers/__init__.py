"""Retailer adapter registry.

Each retailer is represented by a RetailerCollector subclass. Add new retailers
by implementing RetailerCollector in a new module and registering it here.

Usage:
    from amazon_spending.retailers import REGISTRY
    result = REGISTRY["amazon"].collect(conn, output_dir, order_limit=50)
"""

from .amazon import AmazonCollector
from .base import CollectResult, ParsedItem, ParsedOrder, ParsedRetailerTransaction, RetailerCollector
from .target import TargetCollector

REGISTRY: dict[str, RetailerCollector] = {
    "amazon": AmazonCollector(),
    "target": TargetCollector(),
}

__all__ = [
    "REGISTRY",
    "RetailerCollector",
    "CollectResult",
    "ParsedOrder",
    "ParsedItem",
    "ParsedRetailerTransaction",
    "AmazonCollector",
    "TargetCollector",
]
