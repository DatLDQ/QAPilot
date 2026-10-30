import ast
import json
from collections.abc import Callable

import pytest

from app.codegen import PY_FILE, TS_FILE, app_base, plan_tests, relative_url, slugify, write_suite
from app.recorder import Recorder


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
    # Each check carries its step index, and a failure reports it, so verify can match it to its bug.
    check_step = next(s.index for s in recorder.scenarios[1].steps if s.bug_ids)
    assert f"soft.check({check_step}, " in py.split("def test_02")[1]
    namespace: dict = {}
    soft_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SoftAssertions")
    exec(compile(ast.Module([soft_class], []), PY_FILE, "exec"), {"Callable": Callable}, namespace)
    soft = namespace["SoftAssertions"]()
    soft.check(7, "Subtotal is $36.00", lambda: None)
    soft.check(9, "Badge shows 2", lambda: (_ for _ in ()).throw(AssertionError("expected 2\nmore")))
    with pytest.raises(AssertionError, match=r"1 check\(s\) failed:\n- #9 Badge shows 2: expected 2$"):
        soft.assert_all()
    assert 'page.get_by_test_id("card-mug").get_by_role("button", name="Add to cart", exact=True).click()' in py
    assert 'page.on("pageerror"' in py

    ts = (tests_dir / TS_FILE).read_text(encoding="utf-8")
    assert "test('02 · Cart subtotal multiplies price by quantity'" in ts
    assert "page.getByTestId('card-mug').getByRole('button', { name: 'Add to cart', exact: true })" in ts
    assert "process.env.BASE_URL" in ts or "baseURL" in (tests_dir / "playwright.config.ts").read_text()


def test_steps_that_navigated_wait_for_the_new_page(tmp_path):
    rec = Recorder("https://shop.example/")
    rec.begin("Details link opens the product", "https://shop.example/inventory.html", 0)
    button = [{"op": "role", "role": "button", "name": "View details", "exact": True}]
    rec.add_step(0, kind="click", description="Add to cart", locator=button, url="https://shop.example/inventory.html")
    rec.add_step(0, kind="click", description="Open details", locator=button, url="https://shop.example/item?id=4")
    rec.add_step(0, kind="expect", description="Title is Bolt", assertion="text_equals", expected="Bolt",
                 passed=True, locator=[{"op": "role", "role": "heading", "name": "Bolt"}])
    write_suite(rec, tmp_path, "run1", "story")
    py = (tmp_path / "tests" / PY_FILE).read_text(encoding="utf-8")
    ast.parse(py)
    click = 'page.get_by_role("button", name="View details", exact=True).click()'
    # Only the click that changed the URL waits; the one that stayed on the page runs as is.
    assert f"    navigates(page, lambda: {click})" in py and f"\n    {click}\n" in py
    ts = (tmp_path / "tests" / TS_FILE).read_text(encoding="utf-8")
    assert "await navigates(page, () => page.getByRole('button', { name: 'View details', exact: true }).click());" in ts
