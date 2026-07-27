"""Odoo connector — Manufacturing Orders (``mrp.production``) via XML-RPC.

Odoo MO  ──(confirmed/progress)──►  Taktline pull order
Taktline order.completed  ──────►  Odoo MO marked done (assembly built)
Taktline order.cancelled  ──────►  Odoo MO cancelled
"""
from __future__ import annotations

import xmlrpc.client

from .config import Config
from .core import Connector, Mapping
from .taktline import TaktlineClient

DEFAULT_STATES = ("confirmed", "progress")


class OdooClient:
    def __init__(self, cfg: Config):
        base = cfg.odoo_url.rstrip("/")
        self.db = cfg.odoo_db
        self.password = cfg.odoo_password
        common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common")
        self.uid = common.authenticate(cfg.odoo_db, cfg.odoo_username, cfg.odoo_password, {})
        if not self.uid:
            raise RuntimeError("Odoo authentication failed — check ODOO_DB / ODOO_USERNAME / ODOO_PASSWORD.")
        self.models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object")

    def _exec(self, model: str, method: str, *args, **kwargs):
        return self.models.execute_kw(self.db, self.uid, self.password, model, method, list(args), kwargs or {})

    def list_orders(self, states) -> list[dict]:
        states = tuple(states) or DEFAULT_STATES
        mos = self._exec("mrp.production", "search_read",
                         [["state", "in", list(states)]],
                         {"fields": ["id", "name", "product_id", "product_qty", "state"]})
        # Resolve product refs (SKU / default_code) in one batched read.
        pids = list({m["product_id"][0] for m in mos if m.get("product_id")})
        refs: dict[int, str] = {}
        if pids:
            for p in self._exec("product.product", "read", pids, {"fields": ["default_code", "name"]}):
                refs[p["id"]] = p.get("default_code") or p.get("name")
        return [{
            "id": m["id"],
            "product_ref": refs.get(m["product_id"][0]) if m.get("product_id") else None,
            "qty": int(m.get("product_qty") or 0),
            "state": m["state"],
            "lot_code": m.get("name"),   # the MO reference, e.g. "MO/00042"
        } for m in mos]

    def mark_done(self, external_ref: str) -> None:
        mo_id = int(external_ref)
        qty = self._exec("mrp.production", "read", [mo_id], {"fields": ["product_qty"]})[0]["product_qty"]
        self._exec("mrp.production", "write", [[mo_id], {"qty_producing": qty}])
        self._exec("mrp.production", "button_mark_done", [[mo_id]],
                   context={"skip_backorder": True, "skip_immediate": True})

    def cancel(self, external_ref: str) -> None:
        self._exec("mrp.production", "action_cancel", [[int(external_ref)]])


def build(cfg: Config) -> Connector:
    return Connector(
        erp=OdooClient(cfg),
        taktline=TaktlineClient(cfg.taktline_url, cfg.taktline_api_key),
        mapping=Mapping(cfg.product_mapping),
        source="odoo",
        order_states=cfg.order_states,
    )
