import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.shop import build_shop_router


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(build_shop_router())
    with TestClient(app) as c:
        yield c


ORDER = {"name": "Test Shopper", "email": "shopper@example.com", "address": "1 Test Street",
         "items": [{"id": "mug", "qty": 2}, {"id": "notebook", "qty": 1}]}


def test_both_builds_serve_the_app(client):
    for prefix, build in (("/shop", "buggy"), ("/shop-fixed", "fixed")):
        assert client.get(prefix, follow_redirects=False).headers["location"] == f"{prefix}/"
        page = client.get(f"{prefix}/")
        assert page.status_code == 200 and f'window.SHOP_BUILD = "{build}"' in page.text
        assert client.get(f"{prefix}/static/app.js").status_code == 200
        assert client.get(f"{prefix}/static/index.html").status_code == 404
        assert len(client.get(f"{prefix}/api/products").json()) == 6


def test_checkout_totals(client):
    order = client.post("/shop-fixed/api/checkout", json={**ORDER, "shipping": "express", "coupon": "save10"}).json()
    assert (order["subtotal"], order["discount"], order["shipping"], order["total"]) == (45.5, 4.55, 15.0, 55.95)
    assert client.get(f"/shop-fixed/api/orders/{order['id']}").json() == order
    assert client.get("/shop-fixed/api/orders/LG-0").status_code == 404


def test_seeded_express_shipping_bug(client):
    assert client.post("/shop/api/checkout", json={**ORDER, "shipping": "express"}).status_code == 500
    assert client.post("/shop/api/checkout", json={**ORDER, "shipping": "standard"}).status_code == 200
    assert client.post("/shop-fixed/api/checkout", json={**ORDER, "shipping": "drone"}).status_code == 422


def test_checkout_validation(client):
    no_items = {**ORDER, "shipping": "standard", "items": []}
    assert client.post("/shop-fixed/api/checkout", json=no_items).status_code == 422
    bad_item = {**ORDER, "shipping": "standard", "items": [{"id": "unicorn", "qty": 1}]}
    assert client.post("/shop-fixed/api/checkout", json=bad_item).status_code == 422
