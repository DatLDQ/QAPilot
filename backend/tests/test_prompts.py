from app.prompts import SYSTEM_PROMPT, initial_message, language_notice, step_limit_notice, story_language


def test_story_language_detection():
    assert story_language("Là khách hàng, tôi muốn thanh toán giỏ hàng.") == "Vietnamese"
    assert story_language("Checkout works", focus="Kiểm tra mã giảm giá") == "Vietnamese"
    assert story_language("As a shopper I want to check out.") == "English"
    assert story_language("En tant que client, je veux payer à l'étape finale.") is None


def test_initial_message_restates_language_rule():
    assert language_notice("Vietnamese") in initial_message("http://shop.test/", "Tôi muốn thanh toán giỏ hàng.")
    assert language_notice("English") in initial_message("http://shop.test/", "As a shopper I want to check out.")
    french = initial_message("http://shop.test/", "En tant que client, je veux payer à l'étape finale.")
    assert "The user story is in" not in french


def test_step_limit_notice_names_the_language():
    assert "written in English" in step_limit_notice("As a shopper I want to check out.")
    assert "written in Vietnamese" in step_limit_notice("Tôi muốn thanh toán giỏ hàng.")
    assert "same language as the user story" in step_limit_notice("Je veux payer à l'étape finale.")


def test_system_prompt_does_not_suggest_a_language():
    assert "Vietnamese" not in SYSTEM_PROMPT
