from app.services.languages import get_language, is_supported


def test_languages_lists_all_six(client):
    body = client.get("/api/v1/languages").json()
    codes = [language["code"] for language in body["languages"]]
    assert codes == ["en", "ta", "hi", "te", "ml", "kn"]
    assert body["default"] == "en"


def test_languages_include_native_names(client):
    body = client.get("/api/v1/languages").json()
    tamil = next(lang for lang in body["languages"] if lang["code"] == "ta")
    assert tamil["name"] == "Tamil"
    assert tamil["native_name"] == "தமிழ்"


def test_disclaimer_says_not_legal_advice(client):
    text = client.get("/api/v1/disclaimer").json()["disclaimer"]
    assert "not legal advice" in text.lower()


def test_language_helpers():
    assert is_supported("TA")
    assert is_supported(" hi ")
    assert not is_supported("fr")
    assert get_language("fr") is None
