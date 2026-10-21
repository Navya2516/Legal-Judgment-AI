r"""List the Gemini models your API key can use for text generation.

Usage (from the backend folder, venv active):
    python scripts\list_gemini_models.py

Then put one of the names in backend\.env as GEMINI_MODEL=... and restart the server.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so `app` can be imported

from app.config import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    if not settings.gemini_api_key.strip():
        print("No GEMINI_API_KEY found in backend\\.env")
        return 1
    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)
    names = []
    try:
        for model in client.models.list():
            actions = model.supported_actions or []
            if "generateContent" in actions:
                names.append(model.name.replace("models/", ""))
    except Exception as exc:  # network or key problems
        print("Could not list models:", exc)
        return 1
    print(f"Current setting: GEMINI_MODEL={settings.gemini_model}\n")
    print("Models your key can use with generateContent:")
    for name in sorted(names):
        if "flash" in name or "pro" in name:
            print("  ", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
