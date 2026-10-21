"""The languages the system can explain judgments in."""
from typing import Optional

from app.schemas.meta import Language

SUPPORTED_LANGUAGES: tuple[Language, ...] = (
    Language(code="en", name="English", native_name="English"),
    Language(code="ta", name="Tamil", native_name="தமிழ்"),
    Language(code="hi", name="Hindi", native_name="हिन्दी"),
    Language(code="te", name="Telugu", native_name="తెలుగు"),
    Language(code="ml", name="Malayalam", native_name="മലയാളം"),
    Language(code="kn", name="Kannada", native_name="ಕನ್ನಡ"),
)


def get_language(code: str) -> Optional[Language]:
    code = code.strip().lower()
    for language in SUPPORTED_LANGUAGES:
        if language.code == code:
            return language
    return None


def is_supported(code: str) -> bool:
    return get_language(code) is not None


# Standard legal terms, so the same English word is always translated the same
# way (a model left alone mixed "Constitution" and its translation, and used two
# different words for "Article"). This is a STARTER list. Have a reader who
# knows the language and legal usage review it before you rely on it.
GLOSSARY: dict[str, dict[str, str]] = {
    "hi": {"Constitution": "संविधान", "Supreme Court": "सर्वोच्च न्यायालय", "High Court": "उच्च न्यायालय",
           "Article": "अनुच्छेद", "Section": "धारा", "fundamental right": "मौलिक अधिकार", "Bench": "पीठ"},
    "ta": {"Constitution": "அரசியலமைப்பு", "Supreme Court": "உச்ச நீதிமன்றம்", "High Court": "உயர் நீதிமன்றம்",
           "Article": "உறுப்பு", "Section": "பிரிவு", "fundamental right": "அடிப்படை உரிமை", "Bench": "அமர்வு"},
    "te": {"Constitution": "రాజ్యాంగం", "Supreme Court": "సుప్రీంకోర్టు", "High Court": "హైకోర్టు",
           "Article": "అధికరణం", "Section": "సెక్షన్", "fundamental right": "ప్రాథమిక హక్కు", "Bench": "ధర్మాసనం"},
    "ml": {"Constitution": "ഭരണഘടന", "Supreme Court": "സുപ്രീം കോടതി", "High Court": "ഹൈക്കോടതി",
           "Article": "അനുച്ഛേദം", "Section": "വകുപ്പ്", "fundamental right": "മൗലികാവകാശം", "Bench": "ബെഞ്ച്"},
    "kn": {"Constitution": "ಸಂವಿಧಾನ", "Supreme Court": "ಸರ್ವೋಚ್ಚ ನ್ಯಾಯಾಲಯ", "High Court": "ಉಚ್ಚ ನ್ಯಾಯಾಲಯ",
           "Article": "ಅನುಚ್ಛೇದ", "Section": "ಕಲಂ", "fundamental right": "ಮೂಲಭೂತ ಹಕ್ಕು", "Bench": "ಪೀಠ"},
}
