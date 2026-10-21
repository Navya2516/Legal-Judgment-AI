r"""End-to-end smoke test against a RUNNING server with the REAL model.

Start the backend first (uvicorn app.main:app), then, from the backend folder:

    python smoke_real.py "C:\path\to\judgment.pdf"
    python smoke_real.py "C:\path\to\judgment.pdf" --lang hi --gap 13

It prints PASS / FAIL / INFO for each step and exits 1 if anything failed.
Model calls made on a normal run: summary 1, provisions explain 1,
continuation 1, translations 3, ask 2 = about 8. --gap pauses between calls to
stay under the free-tier limit of 5 requests a minute. Nothing here is mocked.
The test deletes the document it uploaded when it finishes (use --keep to skip).
Standard library only.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

results = []


def call(base, method, path, *, json_body=None, file=None, timeout=300):
    url = base.rstrip("/") + path
    headers, data = {}, None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    if file is not None:
        name, content, ctype = file
        boundary = uuid.uuid4().hex
        data = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.status
    except urllib.error.HTTPError as exc:
        raw, code = exc.read(), exc.code
    except Exception as exc:  # server down, timeout
        return 0, {"_exception": repr(exc)}, time.time() - started
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = {"_raw": raw[:200].decode("utf-8", "replace")}
    return code, body, time.time() - started


def record(status, name, detail=""):
    results.append(status)
    print(f"{status:4} {name}" + (f"  -- {detail}" if detail else ""), flush=True)


def check(ok, name, detail=""):
    record("PASS" if ok else "FAIL", name, detail)
    return ok


def err_text(body):
    e = (body or {}).get("error") if isinstance(body, dict) else None
    return f"{e.get('code')}: {e.get('message')}" if e else str(body)[:160]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--lang", default="hi", help="language for the translation checks")
    ap.add_argument("--gap", type=float, default=13.0, help="seconds to pause before each model call")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--question", default="What did the Court finally decide?")
    ap.add_argument("--unanswerable", default="What is the name of the Chief Minister's pet dog?")
    a = ap.parse_args()
    base = a.base

    def model_call(*args, **kw):
        time.sleep(a.gap)
        return call(base, *args, **kw)

    # ---- server basics (no model)
    code, body, _ = call(base, "GET", "/health")
    if not check(code == 200, "GET /health", f"HTTP {code} {body}"):
        print("Server not reachable. Start it with: uvicorn app.main:app"); sys.exit(1)
    code, body, _ = call(base, "GET", "/api/v1/languages")
    check(code == 200 and body, "GET /api/v1/languages", str(body)[:100])
    code, body, _ = call(base, "GET", "/api/v1/disclaimer")
    check(code == 200 and body, "GET /api/v1/disclaimer")

    # ---- bad input (no model)
    code, body, _ = call(base, "POST", "/api/v1/documents", file=("fake.pdf", b"this is not a pdf", "application/pdf"))
    check(400 <= code < 500, "reject a text file named .pdf", f"HTTP {code}: {err_text(body)}")
    code, body, _ = call(base, "GET", "/api/v1/documents/" + "0" * 32)
    check(code in (404, 422), "unknown document id", f"HTTP {code}: {err_text(body)}")

    # ---- upload
    path = Path(a.pdf)
    if not path.is_file():
        print(f"PDF not found: {path}"); sys.exit(2)
    code, body, secs = call(base, "POST", "/api/v1/documents", file=(path.name, path.read_bytes(), "application/pdf"))
    if not check(code in (200, 201, 202) and isinstance(body, dict), "upload PDF", f"HTTP {code} in {secs:.1f}s; keys {sorted(body)[:8] if isinstance(body, dict) else body}"):
        sys.exit(1)
    doc_id = body.get("id") or body.get("doc_id")
    if not check(bool(doc_id), "upload response carries an id"):
        sys.exit(1)

    try:
        # ---- wait for text extraction and index
        t0, doc = time.time(), {}
        while time.time() - t0 < 600:
            code, doc, _ = call(base, "GET", f"/api/v1/documents/{doc_id}")
            if code != 200 or doc.get("status") in ("ready", "failed") and doc.get("index_status") in ("ready", "failed", None):
                break
            time.sleep(3)
        check(doc.get("status") == "ready", "document status ready", f"status={doc.get('status')} index={doc.get('index_status')} after {time.time()-t0:.0f}s; pages={doc.get('page_count', doc.get('pages'))}")
        check(doc.get("index_status") == "ready", "search index ready")
        if doc.get("warnings"):
            record("INFO", "upload warnings", str(doc["warnings"])[:200])

        code, body, _ = call(base, "GET", f"/api/v1/documents/{doc_id}/pages/1")
        check(code == 200, "read page 1", f"HTTP {code}")
        code, body, _ = call(base, "GET", f"/api/v1/documents/{doc_id}/pages/999999")
        check(code in (404, 422), "page number out of range", f"HTTP {code}: {err_text(body)}")
        code, body, _ = call(base, "POST", f"/api/v1/documents/{doc_id}/search", json_body={"query": "fundamental right", "top_k": 3})
        check(code == 200, "search (embedding, no model call)", f"HTTP {code}")
        code, body, _ = call(base, "GET", f"/api/v1/documents/{doc_id}/provisions")
        check(code == 200, "list provisions (no model)", f"HTTP {code}")

        # ---- before any generation, reading saved items should say "not yet"
        code, body, _ = call(base, "GET", f"/api/v1/documents/{doc_id}/summary")
        record("INFO", "GET summary before generating", f"HTTP {code}: {err_text(body)}")

        # ---- real model calls
        code, body, secs = model_call("POST", f"/api/v1/documents/{doc_id}/summary")
        if check(code == 200 and isinstance(body, dict), "POST summary (real model)", f"HTTP {code} in {secs:.0f}s" + ("" if code == 200 else f": {err_text(body)}")):
            record("INFO", "summary fields", ", ".join(sorted(body))[:200])
            if "grounding" in body:
                record("INFO", "summary grounding", json.dumps(body["grounding"])[:200])
        code, body, secs = call(base, "GET", f"/api/v1/documents/{doc_id}/summary")
        check(code == 200, "GET saved summary after generating", f"HTTP {code}")

        code, body, secs = model_call("POST", f"/api/v1/documents/{doc_id}/provisions/explain", json_body={"top_n": 5})
        check(code == 200, "POST provisions/explain (real model)", f"HTTP {code} in {secs:.0f}s" + ("" if code == 200 else f": {err_text(body)}"))

        code, body, secs = model_call("POST", f"/api/v1/documents/{doc_id}/continuation")
        check(code == 200, "POST continuation (real model)", f"HTTP {code} in {secs:.0f}s" + ("" if code == 200 else f": {err_text(body)}"))

        for what in ("summary", "provisions/explain", "continuation"):
            code, body, secs = model_call("POST", f"/api/v1/documents/{doc_id}/{what}/{a.lang}")
            ok = check(code == 200, f"POST {what}/{a.lang} (translation)", f"HTTP {code} in {secs:.0f}s" + ("" if code == 200 else f": {err_text(body)}"))
            if ok:
                text = json.dumps(body, ensure_ascii=False)
                record("INFO", f"{what}/{a.lang} automatic checks", f"ok={text.count(chr(34)+'ok'+chr(34))} numbers_changed={text.count('numbers_changed')} wrong_language={text.count('wrong_language')} untranslated={text.count('untranslated')}")
        code, body, _ = call(base, "POST", f"/api/v1/documents/{doc_id}/summary/xx")
        check(400 <= code < 500, "unsupported language code is refused", f"HTTP {code}: {err_text(body)}")

        # ---- ask
        code, body, secs = model_call("POST", f"/api/v1/documents/{doc_id}/ask", json_body={"question": a.question, "lang": "en"})
        if check(code == 200 and isinstance(body, dict), "ask an answerable question (real model)", f"HTTP {code} in {secs:.0f}s" + ("" if code == 200 else f": {err_text(body)}")):
            check(body.get("answered") is True, "answerable question was answered", f"answered={body.get('answered')}")
            record("INFO", "answer", json.dumps(body, ensure_ascii=False)[:300])
        code, body, secs = model_call("POST", f"/api/v1/documents/{doc_id}/ask", json_body={"question": a.unanswerable, "lang": "en"})
        if check(code == 200 and isinstance(body, dict), "ask an unanswerable question (real model)", f"HTTP {code}" + ("" if code == 200 else f": {err_text(body)}")):
            check(body.get("answered") is False, "unanswerable question was declined", f"answered={body.get('answered')}")
        code, body, _ = call(base, "POST", f"/api/v1/documents/{doc_id}/ask", json_body={"question": "  ", "lang": "en"})
        check(code == 422, "empty question is refused", f"HTTP {code}")
        code, body, _ = call(base, "POST", f"/api/v1/documents/{doc_id}/ask", json_body={"question": "x" * 600, "lang": "en"})
        check(code == 422, "over-long question is refused", f"HTTP {code}")
    finally:
        if not a.keep:
            code, body, _ = call(base, "DELETE", f"/api/v1/documents/{doc_id}")
            check(code in (200, 204), "delete the test document", f"HTTP {code}")
            code, body, _ = call(base, "GET", f"/api/v1/documents/{doc_id}")
            check(code == 404, "deleted document is gone", f"HTTP {code}")

    n_fail = results.count("FAIL")
    print(f"\n{results.count('PASS')} passed, {n_fail} failed.")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()