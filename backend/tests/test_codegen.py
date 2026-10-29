import ast
import json

import pytest

from app.codegen import PY_FILE, TS_FILE, app_base, plan_tests, relative_url, slugify, write_suite


@pytest.mark.parametrize(
    ("target", "base"),
    [
        ("http://localhost:8100/shop/", "http://localhost:8100/shop/"),
        ("http://localhost:8100/shop", "http://localhost:8100/shop/"),
        ("http://localhost:8100/shop/index.html?x=1#cart", "http://localhost:8100/shop/"),
        ("https://example.com", "https://example.com/"),
    ],
)
def test_app_base(target, base):
    assert app_base(target) == base


def test_relative_url():
    base = "http://localhost:8100/shop/"
    assert relative_url("http://localhost:8100/shop/#/cart", base) == "#/cart"
    assert relative_url("http://localhost:8100/shop", base) == ""
    assert relative_url("http://localhost:8100/docs", base) == "/docs"
    assert relative_url("https://other.example/", base) == "https://other.example/"


def test_slugify():
    assert slugify("Coupon SAVE10 applies 10% once!") == "coupon_save10_applies_10_once"
    assert slugify("Thanh toán bằng thẻ") == "thanh_toan_bang_the"
    assert slugify("Đặt hàng với địa chỉ trống") == "dat_hang_voi_dia_chi_trong"
    assert slugify("???") == "scenario"
    assert len(slugify("word " * 40)) <= 60 and not slugify("word " * 40).endswith("_")
    long = "Details dialog opens for a product without reviews or ratings"
    assert slugify(long) == "details_dialog_opens_for_a_product_without_reviews_or"  # whole words only
    assert slugify("x" * 70) == "x" * 60  # no boundary to cut at


def test_plan_tests(recorder):
    tests = plan_tests(recorder)
    assert [(t.name, t.expected_outcome, t.bug_ids) for t in tests] == [
        ("test_01_search_finds_products_regardless_of_case", "pass", []),
        ("test_02_cart_subtotal_multiplies_price_by_quantity", "fail", ["BUG-1"]),
    ]
    assert tests[1].title == "02 · Cart subtotal multiplies price by quantity"


def test_write_suite(recorder, tmp_path):
    manifest = write_suite(recorder, tmp_path, "run123", 'As a shopper I can "check out" """quickly"""')
    tests_dir = tmp_path / "tests"
    assert sorted(p.name for p in tests_dir.iterdir()) == sorted(
        [PY_FILE, TS_FILE, "pytest.ini", "playwright.config.ts", "README.md", "manifest.json"]
    )
    assert manifest["base_url"] == "http://localhost:8100/shop/"
    assert json.loads((tests_dir / "manifest.json").read_text(encoding="utf-8")) == manifest

    py = (tests_dir / PY_FILE).read_text(encoding="utf-8")
    tree = ast.parse(py)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {"test_01_search_finds_products_regardless_of_case",
            "test_02_cart_subtotal_multiplies_price_by_quantity"} <= set(functions)
    failing = functions["test_02_cart_subtotal_multiplies_price_by_quantity"]
    assert "Known bug BUG-1: Cart subtotal ignores quantities" in (ast.get_docstring(failing) or "")
    assert '@pytest.mark.bug("BUG-1")' in py
    # URLs hang off BASE_URL, so the same suite runs against the control build.
    assert 'BASE_URL = os.environ.get("BASE_URL", "http://localhost:8100/shop/")' in py
    assert 'page.goto(url("#/cart"))' in py
    # The soft assertion states the correct behaviour, never the buggy value that was observed.
    assert 'expect(page.get_by_test_id("subtotal")).to_contain_text("$36.00")' in py
    assert "$18.00" not in py.split("def test_02")[1]
    assert 'page.get_by_test_id("card-mug").get_by_role("button", name="Add to cart", exact=True).click()' in py
    assert 'page.on("pageerror"' in py

    ts = (tests_dir / TS_FILE).read_text(encoding="utf-8")
    assert "test('02 · Cart subtotal multiplies price by quantity'" in ts
    assert "page.getByTestId('card-mug').getByRole('button', { name: 'Add to cart', exact: true })" in ts
    assert "process.env.BASE_URL" in ts or "baseURL" in (tests_dir / "playwright.config.ts").read_text()
