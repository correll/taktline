"""Pure parsing/mapping for the storefront + generic clients — no network.
The HTTP plumbing is thin; the mapping is where mistakes hide, so we pin it."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from taktline_connect.generic import _unwrap, orders_from_generic          # noqa: E402
from taktline_connect.qbo import orders_from_qbo                            # noqa: E402
from taktline_connect.shipstation import orders_from_shipstation           # noqa: E402
from taktline_connect.shopify import cancel_refs_from_shopify, orders_from_shopify  # noqa: E402
from taktline_connect.woocommerce import cancel_refs_from_woo, orders_from_woo      # noqa: E402
from taktline_connect.xero import orders_from_xero                          # noqa: E402


SHOPIFY_ORDER = {
    "id": 1001, "name": "#1001", "financial_status": "paid",
    "line_items": [
        {"id": 11, "sku": "BIKE-750", "title": "E-Bike 750W", "quantity": 2},
        {"id": 12, "sku": None, "title": "Spare Wheel", "quantity": 1},   # SKU falls back to title
    ],
}


def test_shopify_orders_one_per_line_item():
    rows = orders_from_shopify([SHOPIFY_ORDER])
    # lot_code = the human order name "#1001"; externalRef stays the composite line id.
    assert rows == [
        {"id": "1001:11", "product_ref": "BIKE-750", "qty": 2, "state": "paid", "lot_code": "#1001"},
        {"id": "1001:12", "product_ref": "Spare Wheel", "qty": 1, "state": "paid", "lot_code": "#1001"},
    ]


def test_shopify_cancel_refs():
    assert cancel_refs_from_shopify([SHOPIFY_ORDER]) == ["1001:11", "1001:12"]


WOO_ORDER = {
    "id": 55, "number": "55", "status": "processing",
    "line_items": [{"id": 7, "sku": "FRAME-M", "name": "Frame M", "quantity": 3}],
}


def test_woo_orders_and_cancels():
    assert orders_from_woo([WOO_ORDER]) == [
        {"id": "55:7", "product_ref": "FRAME-M", "qty": 3, "state": "processing", "lot_code": "#55"},
    ]
    assert cancel_refs_from_woo([WOO_ORDER]) == ["55:7"]


def test_generic_field_remap_and_unwrap():
    payload = {"data": [{"orderNo": "A-1", "item": "WIDGET", "count": "4", "name": "PO-9"}]}
    items = _unwrap(payload)
    rows = orders_from_generic(items, {"id": "orderNo", "product_ref": "item",
                                       "qty": "count", "lot_code": "name"})
    assert rows == [{"id": "A-1", "product_ref": "WIDGET", "qty": 4, "state": None, "lot_code": "PO-9"}]


def test_generic_unwrap_shapes():
    assert _unwrap([{"a": 1}]) == [{"a": 1}]
    assert _unwrap({"orders": [{"a": 1}]}) == [{"a": 1}]
    assert _unwrap({"results": [{"a": 1}]}) == [{"a": 1}]
    assert _unwrap({"nope": 1}) == []


def test_qbo_estimate_line_items():
    est = {"Id": "148", "TxnStatus": "Accepted", "Line": [
        {"Id": "1", "SalesItemLineDetail": {"ItemRef": {"name": "BIKE-750", "value": "5"}, "Qty": 3}},
        {"Id": "2", "DetailType": "SubTotalLineDetail"},                        # skipped (no SalesItemLineDetail)
    ]}
    rows = orders_from_qbo([est], "Estimate")
    assert rows == [{"id": "Estimate:148:1", "product_ref": "BIKE-750", "qty": 3, "state": "Accepted"}]


def test_xero_quote_line_items():
    q = {"QuoteID": "abc", "Status": "ACCEPTED", "LineItems": [
        {"Item": {"Code": "FRAME-M"}, "Description": "Frame", "Quantity": 2.0},
        {"Description": "Assembly labour", "Quantity": 1},                      # falls back to Description
    ]}
    rows = orders_from_xero([q])
    assert rows == [
        {"id": "Quote:abc:0", "product_ref": "FRAME-M", "qty": 2, "state": "ACCEPTED"},
        {"id": "Quote:abc:1", "product_ref": "Assembly labour", "qty": 1, "state": "ACCEPTED"},
    ]


def test_shipstation_order_items():
    o = {"orderId": 9001, "orderStatus": "awaiting_shipment", "items": [
        {"sku": "WHEEL-27", "name": "Wheel 27", "quantity": 4},
        {"sku": None, "orderItemId": 55, "name": "Sticker", "quantity": 1},     # sku falls back to orderItemId
    ]}
    rows = orders_from_shipstation([o])
    assert rows == [
        {"id": "9001:WHEEL-27", "product_ref": "WHEEL-27", "qty": 4, "state": "awaiting_shipment"},
        {"id": "9001:55", "product_ref": "Sticker", "qty": 1, "state": "awaiting_shipment"},
    ]
