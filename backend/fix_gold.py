import csv, pathlib
p = pathlib.Path("evaluation/gold/judgment 2.questions.csv")
rows = list(csv.reader(p.open(encoding="utf-8-sig", newline="")))
for r in rows[1:]:
    if r[0] == "q05":
        r[3] = "111;112"
        r[4] = "Para 118: Rule 3(4) read down; summary at para 119."
        r[5] = "Rule 3(4) needs to be read down in the same manner as Section 79(3)(b)"
with p.open("w", encoding="utf-8-sig", newline="") as f:
    csv.writer(f).writerows(rows)
print("patched q05")