from app.locators import candidates, described, render_py, render_ts, scope_variants, ts_str


def test_candidates_follow_playwright_priority():
    info = {"role": "textbox", "name": "Email", "label": "Email", "placeholder": "you@example.com", "test_id": "email"}
    assert [c[0]["op"] for c in candidates(info)] == ["test_id", "role", "label", "placeholder"]


def test_candidates_skip_clipped_names_and_non_field_labels():
    assert candidates({"role": "button", "name": "Add the very long product name…"}) == []
    assert candidates({"role": "heading", "name": "Cart", "label": "Cart"}) == [
        [{"op": "role", "role": "heading", "name": "Cart", "exact": True}]
    ]
    assert candidates({"role": "text", "name": "Free shipping"}) == [
        [{"op": "text", "value": "Free shipping", "exact": True}]
    ]
    assert candidates({"role": "generic"}) == []


def test_scope_variants():
    assert scope_variants(None) == []
    scope = {"test_id": "card-mug", "css": "article.card", "has_text": "Ceramic Mug"}
    assert scope_variants(scope) == [
        [{"op": "test_id", "value": "card-mug"}],
        [{"op": "css", "value": "article.card"}, {"op": "filter", "has_text": "Ceramic Mug"}],
    ]


def test_described():
    assert described(text="Order placed") == [{"op": "text", "value": "Order placed"}]
    assert described(role="alert") == [{"op": "role", "role": "alert"}]
    assert described(role="dialog", name="Details") == [{"op": "role", "role": "dialog", "name": "Details"}]


def test_render_scoped_locator():
    spec = [
        {"op": "css", "value": "article.card"},
        {"op": "filter", "has_text": "Ceramic Mug"},
        {"op": "role", "role": "button", "name": "Add to cart", "exact": True},
        {"op": "nth", "index": 1},
    ]
    assert render_py(spec) == (
        'page.locator("article.card").filter(has_text="Ceramic Mug")'
        '.get_by_role("button", name="Add to cart", exact=True).nth(1)'
    )
    assert render_ts(spec) == (
        "page.locator('article.card').filter({ hasText: 'Ceramic Mug' })"
        ".getByRole('button', { name: 'Add to cart', exact: true }).nth(1)"
    )


def test_render_text_like_ops():
    for op, py, ts in [
        ("label", "get_by_label", "getByLabel"),
        ("placeholder", "get_by_placeholder", "getByPlaceholder"),
        ("text", "get_by_text", "getByText"),
    ]:
        assert render_py([{"op": op, "value": "Qty", "exact": True}]) == f'page.{py}("Qty", exact=True)'
        assert render_ts([{"op": op, "value": "Qty"}]) == f"page.{ts}('Qty')"
    assert render_py([{"op": "test_id", "value": "subtotal"}, {"op": "first"}]) == (
        'page.get_by_test_id("subtotal").first'
    )
    assert render_ts([{"op": "test_id", "value": "subtotal"}, {"op": "first"}]) == (
        "page.getByTestId('subtotal').first()"
    )


def test_strings_are_escaped_for_both_languages():
    tricky = "It's a \"quote\" \\ \n line\u2028"
    assert ts_str(tricky) == "'It\\'s a \"quote\" \\\\ \\n line\\u2028'"
    # Python literals are JSON strings, which keep U+2028 as is (it is not a line break in Python source).
    assert render_py([{"op": "text", "value": tricky}]) == 'page.get_by_text("It\'s a \\"quote\\" \\\\ \\n line\u2028")'
