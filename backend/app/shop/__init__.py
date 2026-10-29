"""Larkspur Goods: a small storefront with seeded bugs for QAPilot to find.

Two builds share one codebase. ``/shop/`` carries seven seeded defects and
``/shop-fixed/`` is the corrected build, used as a control: a good regression test
fails on the first and passes on the second.

Seeded defects (``/shop/`` only):
    1. Search is case-sensitive ("mug" finds nothing).
    2. The cart subtotal ignores quantities.
    3. The remove-item button has no accessible name.
    4. Re-applying coupon SAVE10 stacks another 10% off.
    5. Checkout accepts an email without a domain ("test.shopper@").
    6. Express shipping makes the order API fail with HTTP 500.
    7. Details for a product without reviews throws a TypeError and never opens.
"""

import itertools
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

STATIC = Path(__file__).parent / "static"
Build = Literal["buggy", "fixed"]

PRODUCTS: list[dict[str, Any]] = [
    {"id": "mug", "name": "Ceramic Mug", "price": 18.00, "emoji": "☕",
     "description": "Stoneware mug with a speckled glaze. Holds 350 ml.", "reviews": [5, 4, 5, 4]},
    {"id": "tote", "name": "Canvas Tote", "price": 24.00, "emoji": "👜",
     "description": "Heavy cotton canvas with an inner pocket.", "reviews": [4, 4, 5]},
    {"id": "plant", "name": "Desk Plant", "price": 32.50, "emoji": "🪴",
     "description": "A low-light pothos in a 12 cm terracotta pot.", "reviews": [5, 5, 4, 5, 5]},
    {"id": "socks", "name": "Wool Socks", "price": 12.00, "emoji": "🧦",
     "description": "Merino blend, ribbed cuff. One size.", "reviews": None},
    {"id": "notebook", "name": "Dot Grid Notebook", "price": 9.50, "emoji": "📓",
     "description": "A5, 160 pages of 100 gsm paper.", "reviews": [4, 5]},
    {"id": "kettle", "name": "Pour-Over Kettle", "price": 54.00, "emoji": "🫖",
     "description": "Gooseneck spout for a steady pour. 1 litre.", "reviews": [5, 4, 4]},
]
_BY_ID = {p["id"]: p for p in PRODUCTS}
COUPONS = {"SAVE10": 0.10}
SHIPPING_RATES: dict[Build, dict[str, float]] = {
    "fixed": {"standard": 0.0, "express": 15.0},
    "buggy": {"standard": 0.0},  # BUG 6: the express rate was never configured on the server
}


class LineItem(BaseModel):
    id: str
    qty: int = Field(ge=1, le=99)


class CheckoutRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=400)
    shipping: str
    coupon: str | None = None
    items: list[LineItem] = Field(min_length=1, max_length=50)


_orders: dict[str, dict[str, Any]] = {}
_order_ids = itertools.count(1001)
_lock = threading.Lock()


def _index_html(build: Build) -> HTMLResponse:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace("<!--BUILD-->", f'<script>window.SHOP_BUILD = "{build}";</script>')
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def _mount(router: APIRouter, prefix: str, build: Build) -> None:
    @router.get(prefix, include_in_schema=False)
    def redirect() -> RedirectResponse:
        return RedirectResponse(f"{prefix}/")

    @router.get(f"{prefix}/", include_in_schema=False)
    def index() -> HTMLResponse:
        return _index_html(build)

    @router.get(f"{prefix}/static/{{name}}", include_in_schema=False)
    def static(name: str) -> FileResponse:
        path = STATIC / name
        if name not in ("app.js", "styles.css") or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @router.get(f"{prefix}/api/products")
    def products() -> list[dict[str, Any]]:
        return PRODUCTS

    @router.post(f"{prefix}/api/checkout", response_model=None)
    def checkout(body: CheckoutRequest) -> dict[str, Any] | JSONResponse:
        lines = []
        for item in body.items:
            product = _BY_ID.get(item.id)
            if product is None:
                raise HTTPException(422, f"Unknown product {item.id}")
            lines.append({"id": item.id, "name": product["name"], "qty": item.qty, "price": product["price"]})
        subtotal = round(sum(line["price"] * line["qty"] for line in lines), 2)
        discount = round(subtotal * COUPONS.get((body.coupon or "").upper(), 0.0), 2)
        try:
            shipping = SHIPPING_RATES[build][body.shipping]
        except KeyError:
            if build == "buggy":
                return JSONResponse({"error": "Internal Server Error"}, status_code=500)
            raise HTTPException(422, "Unknown shipping method") from None
        with _lock:
            order_id = f"LG-{next(_order_ids)}"
            order = {
                "id": order_id, "name": body.name, "email": body.email, "items": lines,
                "subtotal": subtotal, "discount": discount, "shipping": shipping,
                "total": round(subtotal - discount + shipping, 2),
            }
            _orders[order_id] = order
            if len(_orders) > 500:
                _orders.pop(next(iter(_orders)))
        return order

    @router.get(f"{prefix}/api/orders/{{order_id}}")
    def get_order(order_id: str) -> dict[str, Any]:
        order = _orders.get(order_id)
        if order is None:
            raise HTTPException(404, "Order not found")
        return order


def build_shop_router() -> APIRouter:
    router = APIRouter(tags=["demo shop"])
    _mount(router, "/shop", "buggy")
    _mount(router, "/shop-fixed", "fixed")
    return router
