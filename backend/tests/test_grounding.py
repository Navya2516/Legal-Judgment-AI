from app.services.grounding import CITED, UNSUPPORTED, VERIFIED, PageTexts, check_claim, normalize

PAGES = {
    1: "The petitioner purchased land in Madurai. The seller later disputed the sale deed.",
    2: "The High Court held that registration is mandatory under the Registration Act, so the unregistered deed",
    3: "could not transfer title. The appeal is dismissed with costs.",
}
TEXTS = PageTexts(PAGES)
ALLOWED = {1, 2, 3}


def test_normalize_ignores_case_punctuation_and_spacing():
    assert normalize("Dr. B.R.  Ambedkar’s “heart”") == normalize("dr b r ambedkar s heart")


def test_quote_found_gives_verified_and_real_page():
    result = check_claim([1], "registration is mandatory under the Registration Act", TEXTS, ALLOWED)
    assert result.status == VERIFIED and result.pages == [2]  # model said 1, words are on 2


def test_quote_matching_ignores_formatting_differences():
    result = check_claim([2], "REGISTRATION IS MANDATORY, under the registration act", TEXTS, ALLOWED)
    assert result.status == VERIFIED and result.pages == [2]


def test_quote_across_page_break():
    result = check_claim([2], "so the unregistered deed could not transfer title", TEXTS, ALLOWED)
    assert result.status == VERIFIED and result.pages == [2, 3]


def test_quote_not_found_but_page_valid_is_cited():
    result = check_claim([1], "the court ordered the land to be returned to the seller", TEXTS, ALLOWED)
    assert result.status == CITED and result.pages == [1]


def test_no_quote_but_valid_page_is_cited():
    assert check_claim([3], None, TEXTS, ALLOWED).status == CITED
    assert check_claim([3], "   ", TEXTS, ALLOWED).status == CITED


def test_page_outside_context_is_unsupported():
    result = check_claim([99], "invented words that are not anywhere", TEXTS, ALLOWED)
    assert result.status == UNSUPPORTED and result.pages == []


def test_no_pages_and_no_quote_is_unsupported():
    assert check_claim([], None, TEXTS, ALLOWED).status == UNSUPPORTED


def test_very_short_quote_is_not_accepted_as_proof():
    result = check_claim([1], "the", TEXTS, ALLOWED)
    assert result.status == CITED


def test_quote_only_searched_in_allowed_pages():
    result = check_claim([], "appeal is dismissed with costs", TEXTS, {1, 2})
    assert result.status == UNSUPPORTED


# ---- margin letters (A-H) left inside sentences by text extraction ----

ORDER_PAGES = {
    430: "2. The reference is disposed of in the following terms:\n(i) The decision in M P Sharma which holds that the right to\nC privacy is not protected by the Constitution stands over-ruled;\n(ii) The decision in Kharak Singh to the extent that it holds that\nD the right to privacy is not protected by the Constitution stands",
    431: "over-ruled;\n(iii) The right to privacy is protected as an intrinsic part of the right\nE to life and personal liberty under Article 21",
}
ORDER = PageTexts(ORDER_PAGES)


def test_stray_margin_letters_do_not_stop_a_correct_quote_from_verifying():
    quote = "The reference is disposed of in the following terms: (i) The decision in M P Sharma which holds that the right to privacy"
    result = check_claim([430], quote, ORDER, {430, 431})
    assert result.status == VERIFIED and result.pages == [430]


def test_quote_that_includes_the_margin_letter_also_verifies():
    result = check_claim([430], "the right to C privacy is not protected by the Constitution", ORDER, {430, 431})
    assert result.status == VERIFIED


def test_margin_letters_inside_a_quote_that_crosses_a_page_break():
    quote = "Kharak Singh to the extent that it holds that the right to privacy is not protected by the Constitution stands over-ruled"
    result = check_claim([430], quote, ORDER, {430, 431})
    assert result.status == VERIFIED and result.pages == [430, 431]


def test_margin_tolerance_does_not_make_wrong_quotes_match():
    quote = "The reference is disposed of by awarding costs of fifty thousand rupees to the petitioner"
    assert check_claim([430], quote, ORDER, {430, 431}).status == CITED
    assert check_claim([430], "the right to D privacy is absolutely unlimited and cannot be restricted", ORDER, {430, 431}).status == CITED


def test_a_real_word_a_is_not_treated_as_a_margin_letter_when_matching_exactly():
    texts = PageTexts({1: "A party may appeal to the High Court within the time allowed by law."})
    assert check_claim([1], "A party may appeal to the High Court", texts, {1}).status == VERIFIED
