# AI-Powered Multilingual Legal Judgment Explanation System

An evidence-grounded system that explains Indian court judgments in simple
language (English, Tamil, Hindi, Telugu, Malayalam, Kannada), answers questions
using RAG with page-level citations, and flags uncertainty instead of guessing.

> Educational tool only. It is not legal advice.

## Quick start (Windows PowerShell)

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r ..\requirements.txt
pip install -r ..\requirements-ocr.txt      # only needed for scanned PDFs
copy ..\.env.example .env                   # then put your Gemini key in .env
pytest -q
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs.

## Uploading a judgment (Phase 3)

`POST /api/v1/documents` with a PDF. The file is checked immediately (type,
size, readable, not password-protected) and the answer is `202` with status
`processing`. Text extraction then runs in the background. Poll
`GET /api/v1/documents/{id}` until `status` is `ready` or `failed`.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/documents` | Upload a PDF |
| `GET /api/v1/documents/{id}` | Status, progress, warnings |
| `GET /api/v1/documents/{id}/preview` | Opening text with `[Page N]` markers |
| `GET /api/v1/documents/{id}/pages` | Every page and how it was read |
| `GET /api/v1/documents/{id}/pages/{n}` | Full text of one page |
| `DELETE /api/v1/documents/{id}` | Remove the PDF, its text and its record |

Page numbers are the PDF's physical pages (1 = first page of the file), which
can differ from page numbers printed on the judgment itself.

### Settings (in `backend/.env`, all optional)

| Setting | Default | Meaning |
|---|---|---|
| `MAX_UPLOAD_MB` | 25 | Largest accepted file. Scanned judgments are large; raise this if needed |
| `MAX_PAGES` | 2000 | Most pages accepted in one PDF |
| `OCR_ENABLED` | true | Turn OCR off entirely |
| `OCR_DPI` | 200 | Resolution scanned pages are rendered at before OCR |
| `OCR_MIN_CHARS` | 40 | A page with fewer real characters than this, and an image, goes to OCR |

## Search index (Phase 4)

After text extraction, the document is split into overlapping chunks (about
800 characters, 150 overlap; running headers, bare page numbers and margin
letters are removed first), embedded with `all-MiniLM-L6-v2` and stored in a
per-document FAISS index. The document is `ready` as soon as its text is
extracted; `index_status` (`indexing` / `ready` / `failed`) tracks the index.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/documents/{id}/index` | Index status, chunk count, settings, `stale` flag |
| `POST /api/v1/documents/{id}/index` | Rebuild the index (after changing chunk/model settings) |
| `GET /api/v1/documents/{id}/chunks?offset=&limit=` | Browse the chunks that are searchable |
| `POST /api/v1/documents/{id}/search` | `{"query": "...", "top_k": 5}` returns passages with page numbers and scores |

The first run downloads the embedding model (about 90 MB) and needs internet.
Try it from the command line: `python scripts/search_cli.py <document_id> "your question"`.

## Summaries and provisions (Phase 5)

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/documents/{id}/summary` | Generate and save a plain-language summary (calls Gemini, up to a minute) |
| `GET /api/v1/documents/{id}/summary` | Read the saved summary (no model call) |
| `GET /api/v1/documents/{id}/provisions` | Articles, Sections and Rules mentioned, with pages and counts (no model) |
| `POST /api/v1/documents/{id}/provisions/explain` | What role the most-mentioned provisions play in this judgment (saved) |
| `GET /api/v1/documents/{id}/provisions/explain` | Read the saved explanations |

**How answers stay grounded.** The model must cite pages and give a short
word-for-word quote for each point. The server then checks every quote against
the judgment itself: a point is `verified` when its quote is found (and the page
is corrected to where it was found), `cited` when the page is valid but the
quote was not matched, and removed when no valid page backs it (counted in
`grounding.dropped_unsupported`). Set `LLM_DROP_UNVERIFIED=true` to keep only
verified points. Law reports print a column of margin letters (A to H) beside the text, and text
extraction can leave them inside sentences; when a quote does not match exactly, the check tries
again ignoring those stray letters on both sides, so an extraction quirk does not downgrade a
correct quote.

**Long judgments.** Up to `LLM_MAX_CONTEXT_CHARS` (60,000 characters, about
15,000 tokens) the whole judgment is sent. Longer ones are summarised from
passages chosen by retrieval (opening, ending and the best matches for facts,
issues, reasoning and final order), and the response says so in `mode` and
`coverage_note`. Provisions are found by pattern search over every page, with
no model, so none is invented.

Try it: `python scripts\analysis_cli.py summary <document_id>` (see the file for
the other commands).

### More settings (all optional)

| Setting | Default | Meaning |
|---|---|---|
| `GEMINI_MODEL` | gemini-3.8-flash | Google retires models over time; if you get `llm_model_not_found`, run `python scripts\list_gemini_models.py` and update `.env` |
| `LLM_RETRIES` | 2 | Extra tries (with pauses) when Gemini says "high demand" (503) or cannot be reached |
| `EMBEDDING_PRELOAD` | false | Set `true` to load the embedding model when the server starts, so the first search or summary is not slow |
| `LLM_MAX_CONTEXT_CHARS` | 60000 | Largest text sent whole to the model |
| `LLM_MAX_OUTPUT_TOKENS` | 8192 | Largest reply allowed. Gemini's hidden "thinking" counts toward it, so a reply can be cut off mid-sentence (log: `Model reply was not valid`). Raise to 16384 if you see that |
| `LLM_TIMEOUT_SECONDS` | 120 | Time allowed for one model call |
| `LLM_TEMPERATURE` | 0.2 | Lower is more literal |
| `LLM_DROP_UNVERIFIED` | false | Keep only word-for-word verified points |

## Multilingual explanations (Phase 6)

Languages: English (`en`), Tamil (`ta`), Hindi (`hi`), Telugu (`te`), Malayalam (`ml`), Kannada (`kn`).
`GET /api/v1/languages` lists them.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/documents/{id}/summary/{lang}` | Translate the saved English summary and save the translation (calls Gemini) |
| `GET /api/v1/documents/{id}/summary/{lang}` | Read the saved translation (no model call); `stale` is true if the English was regenerated after it |
| `POST /api/v1/documents/{id}/provisions/explain/{lang}` | Translate the saved provision explanations |
| `GET /api/v1/documents/{id}/provisions/explain/{lang}` | Read the saved translation |

**Design.** English is the single source of truth. The English summary must exist
first (`POST /summary`). Only the plain sentences, headings and the disclaimer are
translated. Page numbers, evidence status and the word-for-word quotes are copied
unchanged, so a Tamil sentence still points to the same pages and the same English
evidence. `en` needs no model call.

**Checks on every translated sentence** (`check` field):

| `check` | Meaning |
|---|---|
| `ok` | Passed: the numbers match the English and the text is mostly in the right script |
| `numbers_changed` | A number (year, Article, amount) differs from the English: read with care |
| `wrong_language` | Mostly not in the target script |
| `untranslated` | The model gave nothing usable, so the English sentence is shown |

Failed items are retried once with feedback; what still fails is kept but flagged,
never hidden. The response includes `quality` counts and the English `source_text`
of each sentence so a reader (or a bilingual reviewer) can compare them.

**Limits to be honest about.** The checks catch lost numbers and the wrong language,
not a wrong or awkward meaning. Legal terms in Dravidian languages are the weakest
point. Machine translation needs review by a bilingual person before you rely on it
for anything important. The response carries a translated notice saying so.

Try it: `python scripts\analysis_cli.py translate <document_id> ta --english --out tamil.txt`
(`--out` saves UTF-8 text because some Windows consoles cannot draw Indian scripts).

| Setting | Default | Meaning |
|---|---|---|
| `TRANSLATION_BATCH_SIZE` | 12 | Sentences translated per model call; lower it if replies get cut off |

**Standard terms.** `GLOSSARY` in `app/services/languages.py` fixes how words such as Constitution, Supreme Court, Article and Section are translated, so they come out the same every time. It is a starter list: have someone who knows the language and legal usage review it. Case names, party names and Act names stay in English.

**Slow internet tip.** After the embedding model has downloaded once, add `HF_HUB_OFFLINE=1` to `backend\.env` to stop it contacting Hugging Face on every start.

## Case continuation insights (Phase 7)

"What happens next?" in two clearly separate parts.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/documents/{id}/continuation` | Generate and save the insights (calls Gemini). Optional `?court_level=supreme_court\|high_court\|trial_court\|tribunal` if the court was detected wrongly |
| `GET /api/v1/documents/{id}/continuation` | Read the saved insights (no model call) |
| `POST /api/v1/documents/{id}/continuation/{lang}` | Translate them (en, ta, hi, te, ml, kn) and save the translation |
| `GET /api/v1/documents/{id}/continuation/{lang}` | Read a saved translation (`stale` if the English was regenerated) |

**Part 1: from the judgment.** `disposition` (allowed, partly allowed, dismissed, disposed of,
remanded, reference answered, other), `directions` (what the court ordered, including costs),
`deadlines` (time limits or dates the judgment itself sets) and `further_proceedings` (matters
sent back, listed before another bench, liberty to approach, questions left open). Each point has
pages and a word-for-word quote and is checked against the judgment exactly like the summary.
One extra check applies here: if a point mentions a figure (for example "Rs 5,000" or "45 days")
that is not on the page it cites, it is downgraded from `verified` to `cited`.

**Part 2: general information (`avenues`).** Routes people commonly consider after a judgment,
such as review, curative petition, special leave to appeal, appeal to a higher court or a writ
petition. **These are not generated by the model and do not come from the judgment.** They are a
fixed hand-written table in `app/services/continuation.py`, chosen by the court level, and the
response labels them as general information, not advice. They deliberately contain **no time
limits**, because those depend on the type of case and change with the law. The notice says so and
tells the reader to speak to an advocate promptly. Nothing in this feature predicts what a court
would do.

**Court level** is found by simple rules on the first two pages (for example "IN THE SUPREME
COURT", a `[2017] 10 S.C.R.` report marker, "CJI", "High Court" near the top). The response gives
`court_level_basis` (what was found, and where) so you can check it. If it is wrong or `unknown`,
repeat the request with `?court_level=`.

**Limits to be honest about.** Judgments with several opinions can have an operative order that is
easy to miss when the judgment is long; the response says when it was built from selected passages.
The general-information table is a short starter list for educational use: have an advocate review
it before the system is used by anyone for real decisions.

Try it:
`python scripts\analysis_cli.py continuation <document_id> --quotes`
`python scripts\analysis_cli.py translate <document_id> ta continuation --english --out next_ta.txt`

## Asking questions (Phase 8, backend)
`POST /api/v1/documents/{id}/ask` with `{"question": "...", "lang": "en", "top_k": 6}`. The server
searches the judgment's index, gives only those passages to the model, and requires every sentence of
the answer to cite pages and quote the judgment word for word. Quotes are checked exactly as for
summaries; a sentence with no valid page is removed. If nothing supported remains, `answered` is
`false` with a plain message instead of a guess. Non-English answers are translated with the same
checks as Phase 6; quotes stay in English. Answers are not stored. The question is passed to the model
as data, not as instructions.

## Frontend (Phase 8)
React + Vite in `frontend/`. Start the backend first, then:

    cd frontend
    npm install
    npm run dev          # http://localhost:5173
    npm test             # 41 unit and component tests

It talks to `http://127.0.0.1:8000`. If the backend is elsewhere, copy `frontend/.env.example` to
`frontend/.env.local` and change `VITE_API_BASE_URL`. No secret ever belongs in the frontend; the
Gemini key stays in `backend/.env`.

Screens: upload with live processing steps; your judgments (open, delete); and per judgment four
sections (Summary, Legal provisions, What happens next, Ask a question) with a language selector.
Each point shows its evidence in a ruled margin: the page (click to read it, quote highlighted),
whether the quote was found on that page ("Quote checked") or only the page is real ("Page only"),
and the judgment's own words. On narrow screens the evidence folds under each point. Translated
sentences carry their automatic check result and a link to the English sentence.

Interface labels (buttons, menus) are English only for now; the explanations, headings and
disclaimers follow the selected language.

Optional browser test with a scripted fake model (testing only, says nothing about real model
quality): see `e2e/`.

## Evaluation (Phase 9)

`backend/evaluation/` measures retrieval, the quote checker, saved results, question answering and
human-audited quality, with seeds, confidence intervals and a recorded manifest. Gold questions and audit
labels are written by people; the code never fills them in. See `backend/evaluation/README.md`.

## Status
Phases 1 to 8 are complete and confirmed (setup, backend foundation, PDF extraction, retrieval, summaries and
provisions, multilingual explanations, case continuation insights, grounded Q&A and the React frontend).
Phase 9 (evaluation framework) is built and tested with fake data; it is confirmed once a first real run has been done on your machine.
Next: Phase 10, end-to-end testing and debugging.
