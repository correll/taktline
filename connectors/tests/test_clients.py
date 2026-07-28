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


def test_shopify_ship_to_and_customer_ride_along_as_attributes():
    """The storefront knows who the goods are for and where they go; the shop
    floor and the shipper need both. They travel as flat attributes — the
    server stamps them on the Kanban card and echoes them back at handoff."""
    o = dict(SHOPIFY_ORDER)
    o["customer"] = {"first_name": "Ada", "last_name": "Lovelace"}
    o["shipping_address"] = {"address1": "12 Analytical Way", "city": "London",
                             "zip": "N1 7EU", "country_code": "GB"}
    rows = orders_from_shopify([o])
    assert all(r["attributes"] == {
        "customer": "Ada Lovelace",
        "shipTo": "12 Analytical Way, London, N1 7EU, GB",
    } for r in rows)


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
    q = {"QuoteID": "abc", "QuoteNumber": "QU-0007", "Status": "ACCEPTED", "LineItems": [
        {"LineItemID": "li-1", "Item": {"Code": "FRAME-M"}, "Description": "Frame", "Quantity": 2.0},
        {"LineItemID": "li-2", "Description": "Assembly labour", "Quantity": 1},   # falls back to Description
    ]}
    rows = orders_from_xero([q])
    assert rows == [
        {"id": "Quote:abc:li-1", "product_ref": "FRAME-M", "qty": 2, "state": "ACCEPTED",
         "lot_code": "QU-0007"},
        {"id": "Quote:abc:li-2", "product_ref": "Assembly labour", "qty": 1, "state": "ACCEPTED",
         "lot_code": "QU-0007"},
    ]


def test_shipstation_order_items():
    o = {"orderId": 9001, "orderNumber": "SS-9001", "orderStatus": "awaiting_shipment", "items": [
        {"orderItemId": 54, "sku": "WHEEL-27", "name": "Wheel 27", "quantity": 4},
        {"sku": None, "orderItemId": 55, "name": "Sticker", "quantity": 1},     # no sku → name
    ]}
    rows = orders_from_shipstation([o])
    assert rows == [
        {"id": "9001:54", "product_ref": "WHEEL-27", "qty": 4, "state": "awaiting_shipment",
         "lot_code": "SS-9001"},
        {"id": "9001:55", "product_ref": "Sticker", "qty": 1, "state": "awaiting_shipment",
         "lot_code": "SS-9001"},
    ]


# --- stable external refs (idempotency keys) -----------------------------

def test_xero_ref_survives_a_line_inserted_above():
    """Keyed on the positional index, inserting a line at the top shifts every
    ref: the new line inherits an already-released ref (so it is never made) and
    the last line gets a fresh one (so it is made twice). LineItemID is stable."""
    a = {"LineItemID": "li-a", "Item": {"Code": "A"}, "Quantity": 1}
    b = {"LineItemID": "li-b", "Item": {"Code": "B"}, "Quantity": 1}
    new = {"LineItemID": "li-c", "Item": {"Code": "C"}, "Quantity": 1}
    before = {r["product_ref"]: r["id"] for r in
              orders_from_xero([{"QuoteID": "q1", "Status": "ACCEPTED", "LineItems": [a, b]}])}
    after = {r["product_ref"]: r["id"] for r in
             orders_from_xero([{"QuoteID": "q1", "Status": "ACCEPTED", "LineItems": [new, a, b]}])}
    assert before["A"] == after["A"] and before["B"] == after["B"]
    assert after["C"] not in before.values()


def test_shipstation_two_lines_of_one_sku_stay_distinct():
    # Keyed on the SKU, the second line collapses onto the first ref and the
    # server's idempotency check swallows it — silent under-production.
    o = {"orderId": 1, "orderStatus": "awaiting_shipment", "items": [
        {"orderItemId": 11, "sku": "BOLT", "quantity": 2},
        {"orderItemId": 12, "sku": "BOLT", "quantity": 3},
    ]}
    assert len({r["id"] for r in orders_from_shipstation([o])}) == 2


def test_generic_accepts_decimal_quantity_strings():
    # Zoho / Cin7 / Business Central serialize quantities as "4.000".
    rows = orders_from_generic([{"id": "1", "product_ref": "X", "qty": "4.000"}], None)
    assert rows[0]["qty"] == 4
