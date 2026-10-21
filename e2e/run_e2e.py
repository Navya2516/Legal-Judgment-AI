r"""Browser test of the whole app (optional dev tool; needs Playwright + Chromium).

1. Terminal A:  cd backend ; python ..\e2e\server.py       (fake model, temp data)
2. Terminal B:  cd frontend ; npm run dev
3. Terminal C:  python e2e\run_e2e.py  <folder for screenshots>
"""
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from make_sample_pdf import PAGES  # noqa: E402
import pymupdf  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:5173/"
problems: list[str] = []


def sample_pdf() -> Path:
    path = Path(tempfile.mkdtemp()) / "Sample-v-State-Housing-Board.pdf"
    doc = pymupdf.open()
    for text in PAGES:
        doc.new_page().insert_textbox(pymupdf.Rect(72, 72, 520, 760), text, fontsize=12)
    doc.save(path)
    return path


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1366, "height": 900})
    page.on("console", lambda m: problems.append(f"console {m.type}: {m.text}") if m.type in ("error", "warning") and "404" not in m.text else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))

    page.goto(URL)
    expect(page.get_by_role("heading", level=1)).to_contain_text("Understand a court judgment")
    page.screenshot(path=OUT / "01-home.png")

    # upload
    page.set_input_files("#pdf-input", str(sample_pdf()))
    page.wait_for_url("**#/doc/*/summary", timeout=30000)
    expect(page.get_by_role("heading", name="No summary yet")).to_be_visible()
    page.screenshot(path=OUT / "02-summary-empty.png")

    # summary
    page.get_by_role("button", name="Write the summary").click()
    expect(page.get_by_role("heading", name="Plain summary")).to_be_visible(timeout=30000)
    expect(page.get_by_text("Quote checked").first).to_be_visible()
    page.screenshot(path=OUT / "03-summary.png", full_page=True)

    # page viewer with highlighted evidence
    page.get_by_role("button", name=lambda n: n.startswith("Open page")).first.click() if False else None
    page.locator("button.pagelink").first.click()
    expect(page.get_by_role("dialog")).to_be_visible()
    expect(page.locator(".viewer-text mark")).to_be_visible()
    page.screenshot(path=OUT / "04-page-viewer.png")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)

    # language: Tamil needs translation
    page.select_option("#language", "ta")
    expect(page.get_by_role("heading", name="The summary is not in Tamil yet")).to_be_visible()
    page.get_by_role("button", name="Translate into Tamil").click()
    expect(page.locator(".point-text").first).to_contain_text("தமிழ்", timeout=30000)
    page.screenshot(path=OUT / "05-summary-tamil.png", full_page=True)
    page.select_option("#language", "en")

    # provisions
    page.get_by_role("link", name="Legal provisions").click()
    expect(page.get_by_role("cell", name="Article 21").or_(page.get_by_role("rowheader", name="Article 21"))).to_be_visible(timeout=15000)
    page.get_by_role("button", name="Explain the provisions").click()
    expect(page.locator("h4.leaf-heading").first).to_be_visible(timeout=30000)
    page.screenshot(path=OUT / "06-provisions.png", full_page=True)

    # next steps
    page.get_by_role("link", name="What happens next").click()
    page.get_by_role("button", name="Find what happens next").click()
    expect(page.get_by_role("heading", name="How the court disposed of the case")).to_be_visible(timeout=30000)
    expect(page.get_by_text("not from this judgment", exact=False).first.or_(page.get_by_text("do not come from this judgment").first)).to_be_visible()
    page.screenshot(path=OUT / "07-next.png", full_page=True)

    # ask
    page.get_by_role("link", name="Ask a question").click()
    page.get_by_label("Your question").fill("Why was the appeal partly allowed?")
    page.get_by_role("button", name="Ask", exact=True).click()
    expect(page.locator(".turn-answer .point-text").first).to_be_visible(timeout=30000)
    page.screenshot(path=OUT / "08-ask.png", full_page=True)

    # mobile
    mobile = browser.new_page(viewport={"width": 390, "height": 800})
    mobile.on("pageerror", lambda e: problems.append(f"mobile pageerror: {e}"))
    mobile.goto(page.url.replace("/ask", "/summary"))
    expect(mobile.get_by_role("heading", name="Plain summary")).to_be_visible(timeout=15000)
    mobile.get_by_role("button", name="Show evidence").first.click()
    mobile.screenshot(path=OUT / "09-mobile-summary.png")
    overflow = mobile.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    if overflow > 0:
        problems.append(f"mobile horizontal overflow: {overflow}px")
    mobile.goto(URL)
    mobile.screenshot(path=OUT / "10-mobile-home.png")
    overflow = mobile.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    if overflow > 0:
        problems.append(f"mobile home horizontal overflow: {overflow}px")

    # delete from the list
    page.goto(URL)
    page.get_by_role("button", name=lambda n: n.startswith("Delete")).first.click() if False else None
    page.locator(".doc-actions button", has_text="Delete").first.click()
    page.get_by_role("button", name="Delete for good").click()
    expect(page.get_by_text("Nothing uploaded yet")).to_be_visible()
    browser.close()

print("PROBLEMS:" if problems else "No console errors or layout problems.")
for line in problems:
    print(" -", line)
