r"""Generate and print a summary or the provisions of an uploaded judgment.

Usage (server must be running):
    python scripts\analysis_cli.py summary    <document_id>
    python scripts\analysis_cli.py provisions <document_id> [how_many]
    python scripts\analysis_cli.py explain    <document_id> [top_n]
    python scripts\analysis_cli.py continuation <document_id> [--court-level supreme_court|high_court|trial_court|tribunal]
    python scripts\analysis_cli.py translate  <document_id> <language> [summary|provisions|continuation]

Add --quotes at the end to also print the word-for-word quote behind each point,
so you can compare the plain-language wording with the evidence.

translate needs the English summary (or explanations, or continuation insights) to exist already. Language
codes: en, ta, hi, te, ml, kn. Extra options for translate:
    --english      show the English sentence under each translated one
    --out FILE     also save the result as a UTF-8 text file (open it in Notepad
                   or a browser; some Windows consoles cannot draw Indian scripts)
"""
import sys
import textwrap

import httpx

BASE = "http://127.0.0.1:8000/api/v1/documents"


def pages(point):
    return ", ".join(str(p) for p in point["pages"])


QUOTES = "--quotes" in sys.argv
if QUOTES:
    sys.argv.remove("--quotes")
ENGLISH = "--english" in sys.argv
if ENGLISH:
    sys.argv.remove("--english")
COURT_LEVEL = None
if "--court-level" in sys.argv:
    position = sys.argv.index("--court-level")
    COURT_LEVEL = sys.argv[position + 1] if position + 1 < len(sys.argv) else None
    del sys.argv[position : position + 2]
OUT = None
if "--out" in sys.argv:
    position = sys.argv.index("--out")
    OUT = sys.argv[position + 1] if position + 1 < len(sys.argv) else None
    del sys.argv[position : position + 2]

# Tamil, Hindi, ... must not crash on a console that uses a legacy code page.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def show_quote(item):
    if QUOTES and item.get("quote"):
        print(textwrap.fill('"' + item["quote"] + '"', 96, initial_indent="      > ", subsequent_indent="        "))


def show_points(title, points):
    if not points:
        return
    print(f"\n== {title} ==")
    for p in points:
        mark = "OK " if p["status"] == "verified" else "?  "
        print(textwrap.fill(f"{mark}{p['text']}  [p. {pages(p)}]", 100, subsequent_indent="    "))
        show_quote(p)


CHECK_MARK = {"ok": "OK ", "numbers_changed": "#? ", "wrong_language": "L? ", "untranslated": "-- "}
SECTIONS = ("plain_summary", "facts", "issues", "holding", "reasoning", "final_order")


def translate_main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 1
    doc_id, lang = sys.argv[2], sys.argv[3]
    what = sys.argv[4] if len(sys.argv) > 4 else "summary"
    if what not in ("summary", "provisions", "continuation"):
        print(__doc__)
        return 1
    path = {"summary": "summary", "provisions": "provisions/explain", "continuation": "continuation"}[what]
    try:
        response = httpx.post(f"{BASE}/{doc_id}/{path}/{lang}", timeout=300)
    except httpx.HTTPError as exc:
        print("Could not reach the server:", exc)
        return 1
    if response.status_code != 200:
        print(response.status_code, response.json().get("error", response.text))
        return 1
    body = response.json()
    labels = body["labels"]
    lines: list[str] = []

    def add(text: str = "", width: int = 100, indent: str = "", more: str = "") -> None:
        lines.extend(textwrap.wrap(text, width, initial_indent=indent, subsequent_indent=more) or [""])

    def show(item: dict, text: str) -> None:
        pages = ", ".join(str(p) for p in item["pages"])
        add(f"{CHECK_MARK[item['check']]}{text}  [{labels.get('pages', 'p.')} {pages}]", more="    ")
        if ENGLISH:
            add(item["source_text"], 96, "      EN: ", "          ")
        if QUOTES and item.get("quote"):
            add('"' + item["quote"] + '"', 96, "      > ", "        ")

    if what == "summary":
        add(f"{body.get('case_title') or '-'} | {body.get('court') or '-'} | {body.get('date') or '-'}")
        for name in SECTIONS:
            if body[name]:
                lines.append("")
                add(f"== {labels.get(name, name)} ==")
                for point in body[name]:
                    show(point, point["text"])
        if body.get("coverage_note"):
            lines.append("")
            add("NOTE: " + body["coverage_note"])
    elif what == "continuation":
        add(f"{labels['court_level']}: {body['court_level_name']}  ({body['court_level_basis']})")
        if body.get("disposition"):
            d = body["disposition"]
            lines.append("")
            add(f"== {labels['disposition']} ==")
            show(d, f"[{d['label_name']}] {d['text']}")
        for name in ("directions", "deadlines", "further_proceedings"):
            lines.append("")
            add(f"== {labels[name]} ==")
            if not body[name]:
                lines.append("   -")
            for point in body[name]:
                show(point, point["text"])
        lines.append("")
        add(f"== {labels['avenues']} ==")
        add(body["avenues_intro"])
        for a in body["avenues"]:
            add(f"{CHECK_MARK[a['check']]}{a['title']}: {a['description']}" + (f" [{a['basis']}]" if a.get("basis") else ""), more="    ")
            if ENGLISH:
                add(a["source_title"] + ": " + a["source_description"], 96, "      EN: ", "          ")
        add(body["avenues_notice"])
        if body.get("coverage_note"):
            lines.append("")
            add("NOTE: " + body["coverage_note"])
    else:
        add(f"== {labels.get('provisions', 'Provisions')} ==")
        for item in body["items"]:
            show(item, f"{item['key']}: {item['role_in_case']}")
    lines.append("")
    add(body["disclaimer"])
    if body.get("translation_notice"):
        lines.append("")
        add(body["translation_notice"])
    q = body["quality"]
    lines.append("")
    add(
        f"Language: {body['language_name']} ({body['language']}), model {body['model']}. "
        f"Translation checks: {q['ok']} ok, {q['flagged']} flagged, {q['untranslated']} left in English, of {q['items_total']}. "
        f"English grounding: {body['grounding']}"
    )
    add("OK = passed checks, #? = a number differs from the English, L? = not mostly in the target script, -- = English shown")
    if body.get("stale"):
        add("WARNING: the English was regenerated after this translation; translate again.")

    text = "\n".join(lines)
    print(text)
    if OUT:
        with open(OUT, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(f"\nSaved to {OUT} (UTF-8).")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "translate":
        return translate_main()
    if len(sys.argv) < 3 or sys.argv[1] not in ("summary", "provisions", "explain", "continuation"):
        print(__doc__)
        return 1
    action, doc_id = sys.argv[1], sys.argv[2]
    arg = int(sys.argv[3]) if len(sys.argv) > 3 else None
    try:
        if action == "summary":
            response = httpx.post(f"{BASE}/{doc_id}/summary", timeout=300)
        elif action == "continuation":
            params = {"court_level": COURT_LEVEL} if COURT_LEVEL else None
            response = httpx.post(f"{BASE}/{doc_id}/continuation", params=params, timeout=300)
        elif action == "provisions":
            response = httpx.get(f"{BASE}/{doc_id}/provisions", params={"limit": arg or 25}, timeout=60)
        else:
            response = httpx.post(f"{BASE}/{doc_id}/provisions/explain", json={"top_n": arg or 8}, timeout=300)
    except httpx.HTTPError as exc:
        print("Could not reach the server:", exc)
        return 1
    if response.status_code != 200:
        print(response.status_code, response.json().get("error", response.text))
        return 1
    body = response.json()
    if action == "summary":
        print(f"{body.get('case_title') or '-'} | {body.get('court') or '-'} | {body.get('date') or '-'}")
        print(f"Mode: {body['mode']} ({body['pages_in_context']} of {body['total_pages']} pages used)")
        if body.get("coverage_note"):
            print(textwrap.fill("NOTE: " + body["coverage_note"], 100))
        for name in ("plain_summary", "facts", "issues", "holding", "reasoning", "final_order"):
            show_points(name.replace("_", " ").title(), body[name])
        print("\nGrounding:", body["grounding"], "  (OK = quote found on the page, ? = page valid but quote not matched)")
    elif action == "continuation":
        print(f"Court: {body['court_level']}  ({body['court_level_basis']})")
        print(f"Mode: {body['mode']} ({body['pages_in_context']} of {body['total_pages']} pages used)")
        if body.get("coverage_note"):
            print(textwrap.fill("NOTE: " + body["coverage_note"], 100))
        if body.get("disposition"):
            d = body["disposition"]
            print("\n== How the court disposed of the case ==")
            mark = "OK " if d["status"] == "verified" else "?  "
            print(textwrap.fill(f"{mark}[{d['label']}] {d['text']}  [p. {', '.join(map(str, d['pages']))}]", 100, subsequent_indent="    "))
            show_quote(d)
        for title, key in (
            ("What the court ordered", "directions"),
            ("Time limits and dates stated in the judgment", "deadlines"),
            ("What happens next in this case", "further_proceedings"),
        ):
            if body[key]:
                show_points(title, body[key])
            else:
                print(f"\n== {title} ==\n   (none stated in the passages reviewed)")
        print("\n== General information (NOT from this judgment) ==")
        print(textwrap.fill(body["avenues_intro"], 100))
        for a in body["avenues"]:
            basis = f"  [{a['basis']}]" if a.get("basis") else ""
            print(textwrap.fill(f"- {a['title']}: {a['description']}{basis}", 100, subsequent_indent="    "))
        print(textwrap.fill(body["avenues_notice"], 100))
        print("\nGrounding:", body["grounding"], "  (OK = quote found on the page, ? = page valid but quote not matched)")
    elif action == "provisions":
        print(f"{body['returned']} of {body['total']} provisions\n")
        for p in body["provisions"]:
            basis = "" if p["act_basis"] != "assumed" else "  (act assumed)"
            print(f"{p['mentions']:4d}x  {p['key']}{basis}  on {p['page_count']} pages, first p. {p['first_mention']['page']}")
    else:
        for item in body["items"]:
            mark = "OK " if item["status"] == "verified" else "?  "
            print(textwrap.fill(f"{mark}{item['key']}: {item['role_in_case']}  [p. {', '.join(map(str, item['pages']))}]", 100, subsequent_indent="    "))
            show_quote(item)
        print("\nGrounding:", body["grounding"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
