import csv, pathlib
src = pathlib.Path("evaluation/gold")
dst = pathlib.Path("evaluation/gold_subset")
dst.mkdir(exist_ok=True)
keep = {"q01", "q03", "q04", "q09", "q11", "q15", "q16", "q19", "q21", "q23"}
for f in sorted(src.glob("*.questions.csv")):
    rows = list(csv.reader(f.open(encoding="utf-8-sig", newline="")))
    out = [rows[0]] + [r for r in rows[1:] if r[0] in keep]
    with (dst / f.name).open("w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerows(out)
    print(f.name, len(out) - 1, "rows")