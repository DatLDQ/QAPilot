from app.prompts import VIETNAMESE_NOTICE, initial_message


def test_vietnamese_story_restates_language_rule():
    vi = initial_message("http://shop.test/", "Là khách hàng, tôi muốn thanh toán giỏ hàng.")
    assert VIETNAMESE_NOTICE in vi
    assert VIETNAMESE_NOTICE in initial_message("http://shop.test/", "Checkout works", focus="Kiểm tra mã giảm giá")
    for story in ("As a shopper I want to check out.", "En tant que client, je veux payer à l'étape finale."):
        assert VIETNAMESE_NOTICE not in initial_message("http://shop.test/", story)
