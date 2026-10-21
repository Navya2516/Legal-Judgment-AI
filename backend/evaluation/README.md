# Evaluation (Phase 9)

This folder measures how well the system works, in a way you can repeat and
report. It follows one rule: **a number appears in a report only if it was
measured by running the real code, or written into a CSV by a person.** Nothing
here invents a score, and a blank cell is never filled in.

Run every command from the `backend` folder with the virtual environment on:

```powershell
cd "C:\Users\Navya Saravanan\OneDrive\Desktop\legal-judgment-ai\backend"
.\venv\Scripts\Activate.ps1
```

## What is measured, and who does the work

| Question | Command | Needs a person? | Uses Gemini quota? |
|---|---|---|---|
| What do the PDFs look like (pages, OCR, chunks)? | `corpus` | no | no |
| Does search find the pages that answer a question? Better than keyword search? | `retrieval` | **yes, to write the gold questions** | no |
| Does the quote checker accept real quotes and reject altered ones? | `verifier` | no | no |
| What share of saved summaries, provisions and translations is quote-checked, removed, or flagged? | `collect` | no | no (reads saved results) |
| Does question answering answer, cite the right pages, and decline when it should? | `ask-run`, `ask-score` | **yes, gold questions** | **yes** |
| Does the page really support each sentence? | `audit-sample`, `audit-score` | **yes, a reader of English** | no |
| Is each translation faithful? | `audit-sample`, `audit-score` | **yes, a reader of that language** | no |
| Everything in one document | `report` | no | no |

The automatic "Quote checked" label only proves that the quoted words are on
the page. Whether the sentence is a fair statement of the page is a human
judgment, which is why the audit exists. Report both.

## Step 1. Collect judgments

Copy the PDFs into `backend\evaluation\pdfs\`. They stay on your computer (the folder is
ignored by git). Use **several judgments of different kinds** (for example a Supreme Court
constitutional case, a High Court civil case, and a shorter order). Results from one
judgment cannot support a general claim, and the paper must not depend on one document.

## Step 2. Write the gold questions (a person, once per judgment)

```powershell
python -m evaluation.run gold-template
```

This creates `evaluation\gold\<pdf name>.questions.csv` with eight generic starter
questions. Open it in Excel and:

* add questions that are specific to the case (a provision, a party, a date, a direction);
* fill `answerable` with `yes` or `no`;
* for every `yes`, fill `relevant_pages` with the PDF page numbers the viewer shows, for
  example `78` or `78;279-280`. Write down every page that answers the question, not just the first;
* copy a short exact quote (8 to 25 words) from one of those pages into `evidence_quote`. Then run
  `python -m evaluation.run gold-check`, which searches every quote and tells you if a page number is
  wrong or a quote is mistyped. To find the page of a phrase yourself:
  `python -m evaluation.run find "right to privacy is protected as an intrinsic part"`;
* include some `no` questions, which the judgment really does not answer. They test
  whether the system declines instead of guessing;
* aim for at least 20 answerable and 5 unanswerable questions per judgment. With fewer,
  the intervals in the report will be wide. That is honest, not a defect.

Rows that are blank or inconsistent are listed and skipped; they are never guessed. The
command never overwrites a CSV that already exists, so labels cannot be lost.

If possible have a second person label a sample of the same questions independently and
report how often you agreed.

## Step 3. Measurements that need no Gemini quota

```powershell
python -m evaluation.run corpus
python -m evaluation.run retrieval
python -m evaluation.run retrieval --chunk-sizes 400 800 1200   # optional: compares chunk sizes
python -m evaluation.run verifier --samples 200
```

`retrieval` compares three ways of ranking the same chunks: the application's embedding
search (MiniLM), a BM25 keyword baseline, and random order. It reports hit@k, recall@k and
MRR with 95% bootstrap intervals. The first run may download the embedding model.

`verifier` cuts real spans out of each judgment and checks them (and altered copies)
with the application's quote checker. It tests the checker, not the language model.
One control is informational on purpose: the checker ignores punctuation, so `3(1)`
and `31` match. The report shows how often such numbers occur in each judgment.

## Step 4. Count what the app already produced (no quota)

Generate summaries, provisions, continuation insights and translations in the app as usual,
then:

```powershell
python -m evaluation.run collect
```

This reads the saved results and reports, with intervals, how many points are quote-checked,
how many claims the model made that were removed as unsupported, how much of a long
judgment the model actually saw, and how the automatic translation checks came out.
Translations are counted separately so the same evidence is never counted twice.

## Step 5. Question answering with the real model (uses quota)

The free Gemini tier allows about **20 requests per day per model**, and failed and
retried requests also count. So the run is resumable and capped:

```powershell
python -m evaluation.run ask-run --dry-run                 # shows how many calls it would need
python -m evaluation.run ask-run --max-calls 15            # English, stops at 15 calls
python -m evaluation.run ask-score
```

Each answer is saved the moment it arrives. Running the same command the next day
asks only the questions that are not yet answered. Use the same `GEMINI_MODEL` for
the whole run: the report warns if answers came from more than one model, and they
must not be pooled. Other languages: `--lang ta` (and the same for `ask-score`);
each translated answer costs at least one extra call.

Reported per judgment: answered rate on answerable questions; whether a cited page is a
gold page; whether each sentence's pages include a gold page; how many sentences are
quote-checked; and how often the system correctly declined an unanswerable question.

## Step 6. Human audit

```powershell
python -m evaluation.run audit-sample --kind evidence --out evaluation\runs\main\evidence.csv
python -m evaluation.run audit-sample --kind translation --language ta --out evaluation\runs\main\translation_ta.csv
```

Open the CSV in Excel. Fill the `label` column only.

**Evidence sheet** (reader of English). Read `quote` and `page_context`, then write one of:

* `supported`: the page says what the sentence says;
* `partly`: the page supports part of the sentence, or says it less strongly;
* `not_supported`: the page does not say this, or says something different.

**Translation sheet** (reader of that language). Compare `translation` with `english`:

* `adequate`: same meaning, correct legal terms;
* `minor_error`: meaning kept, but a wrong or awkward word, or a small omission;
* `major_error`: the meaning changed, or something important was added or lost.

Sampling is stratified (by automatic status or check) and seeded, so the same command gives the
same sheet. For a second reviewer, copy the sheet *before* anyone fills it in, and let each
reviewer label their own copy. Then:

```powershell
python -m evaluation.run audit-score --kind evidence --sheet evaluation\runs\main\evidence.csv --second evaluation\runs\main\evidence_B.csv
python -m evaluation.run audit-score --kind translation --sheet evaluation\runs\main\translation_ta.csv
```

Unlabelled rows are counted and left out; invalid labels are listed. With two reviewers the
score includes agreement and Cohen's kappa.

## Step 7. The report

```powershell
python -m evaluation.run report
```

writes `evaluation\runs\main\report.md`: Markdown tables you can paste into Word. It starts
with a record of the exact settings, package versions, seed and document hashes that
produced the numbers, and ends with a list of what the numbers do not show. Use `--run NAME`
on every command to keep separate runs (for example one per model).

## Reproducibility

* Every random choice uses a seed (`--seed`, default 0) and is recorded in the output.
* Each JSON output carries a manifest: Python, platform, package versions, models, chunk sizes,
  temperature, the command line, and the SHA-256 of every PDF. The API key is never recorded.
* Model replies are not deterministic. Report the model name and date, and say so.
* Everything in `runs\` and `pdfs\` stays local: it can contain judgment text.

## What not to claim

* Do not report a number from a run that used the stand-in test embedder; the report marks those runs.
* Do not call "Quote checked" "accuracy". Report it as the share of sentences whose quote was found
  on the page, next to the audit's supported rate.
* Report negative and weak results as they are, including wide intervals and small samples.
* Do not generalise beyond the judgments, languages, model and settings you actually ran.
