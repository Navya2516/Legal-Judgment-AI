from app.services.provisions import extract_provisions


def keys(text):
    return {p["key"]: p for p in extract_provisions({1: text})}


def test_article_list_is_split_and_subclauses_recorded():
    found = keys("Articles 14, 19(1)(a) and 21 of the Constitution apply. Art.20(3) too.")
    assert "Article 14 (Constitution of India)" in found
    assert found["Article 19 (Constitution of India)"]["variants"] == ["19(1)(a)"]
    assert "Article 20 (Constitution of India)" in found
    assert "Article 21 (Constitution of India)" in found


def test_act_names_and_abbreviations():
    found = keys("Charged under Section 302 IPC and Section 498-A of the Indian Penal Code, 1860.")
    assert found["Section 302 (Indian Penal Code, 1860)"]["act_basis"] == "stated"
    assert "Section 498A (Indian Penal Code, 1860)" in found


def test_act_with_brackets_in_its_title():
    found = keys("Section 3 of the Aadhaar (Targeted Delivery of Financial and other Subsidies) Act, 2016 applies.")
    assert any(k.startswith("Section 3 (Aadhaar") for k in found)


def test_order_and_rule():
    found = keys("Order VII Rule 11 CPC was invoked.")
    assert "Order VII Rule 11 (Code of Civil Procedure, 1908)" in found


def test_bare_article_is_marked_assumed_and_treaty_is_not_confused():
    found = keys("Article 21 applies. Article 8 of the European Convention on Human Rights also.")
    assert found["Article 21 (Constitution of India)"]["act_basis"] == "assumed"
    treaty = [k for k in found if k.startswith("Article 8 (")]
    assert treaty and "Convention" in treaty[0]
    assert "Article 8 (Constitution of India)" not in found


def test_act_is_not_borrowed_from_the_next_provision():
    found = keys("Section 113 (1973) 4 SCC 225 and Section 9(iii) of the Limitation Act.")
    assert found["Section 113"]["act"] is None
    assert found["Section 113"]["variants"] == []  # '(1973)' is a case year, not a sub-clause
    assert "Section 9 (Limitation Act)" in found


def test_names_and_money_are_not_provisions():
    assert extract_provisions({1: "Rs. 5,000 was paid. S. A. Bobde, J. and R. K. Agrawal agreed."}) == []


def test_counts_pages_and_first_mention():
    pages = {1: "Article 21 here.", 2: "nothing", 3: "Article 21 again and Article 21 once more."}
    prov = extract_provisions(pages)[0]
    assert prov["mentions"] == 3 and prov["pages"] == [1, 3]
    assert prov["first_mention"]["page"] == 1


def test_sorted_by_mentions():
    found = extract_provisions({1: "Article 14. Article 21. Article 21. Article 21."})
    assert [p["number"] for p in found] == ["21", "14"]


def test_bare_article_near_a_treaty_name_is_not_called_the_constitution():
    pages = {1: "In the European Convention cases, when the courts identify an infringement of a person's Article 8 rights, relief follows."}
    (item,) = extract_provisions(pages)
    assert item["act"] == "European Convention on Human Rights" and item["act_basis"] == "assumed"


def test_bare_article_without_treaty_words_still_assumed_constitution():
    (item,) = extract_provisions({1: "The petitioner relies on Article 21 for this."})
    assert item["act"] == "Constitution of India" and item["act_basis"] == "assumed"
