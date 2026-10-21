r"""Compare two reviewers' audit sheets and list the items they labelled differently.

Run from the backend folder, for example:

    python audit_compare.py evaluation\audit_translation_ta.csv evaluation\audit_translation_ta_B.csv --kind translation --out evaluation\disagreements_ta.csv
    python audit_compare.py evaluation\audit_evidence.csv evaluation\audit_evidence_B.csv --kind evidence --out evaluation\disagreements_evidence.csv

After the two reviewers have discussed the differences and filled the agreed_label column of the
disagreements file, run it again with --adjudicated to get the final counts:

    python audit_compare.py evaluation\audit_translation_ta.csv evaluation\audit_translation_ta_B.csv --kind translation --adjudicated evaluation\disagreements_ta.csv

It reads the sheets only. It makes no model calls and changes no sheet.
The console shows item ids and labels (plain ASCII). The CSV written by --out holds the full
text, saved as UTF-8 with a byte-order mark so Excel opens Indian-language text correctly.
"""
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from evaluation.stats import proportion

LABELS = {
    "evidence": ["supported", "partly", "not_supported"],
    "translation": ["adequate", "minor_error", "major_error"],
}
TEXT_COLUMNS = {
    "evidence": ["claim", "quote"],
    "translation": ["english", "translation"],
}


def clean(label: str) -> str:
    return (label or "").strip().lower().replace(" ", "_").replace("-", "_")


def read(path: Path) -> list:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sheet_a", type=Path, help="first reviewer's filled sheet")
    ap.add_argument("sheet_b", type=Path, help="second reviewer's filled sheet")
    ap.add_argument("--kind", choices=["evidence", "translation"], required=True)
    ap.add_argument("--out", type=Path, default=None, help="CSV to write the disagreements to (never overwrites)")
    ap.add_argument("--adjudicated", type=Path, default=None,
                    help="the disagreements CSV after the reviewers filled agreed_label: prints the final counts")
    args = ap.parse_args()

    labels = LABELS[args.kind]
    a_rows, b_rows = read(args.sheet_a), read(args.sheet_b)
    a = {r["item_id"]: r for r in a_rows}
    b = {r["item_id"]: r for r in b_rows}
    both = [i for i in a if i in b]
    print(f"Sheet A: {len(a_rows)} rows. Sheet B: {len(b_rows)} rows. Item ids in both: {len(both)}.")
    if set(a) != set(b):
        print("WARNING: the two sheets do not have the same item ids. Only shared ids are compared.")
    text_cols = TEXT_COLUMNS[args.kind]
    changed = [i for i in both if any((a[i].get(c) or "") != (b[i].get(c) or "") for c in text_cols)]
    if changed:
        print(f"WARNING: {len(changed)} item(s) have different {'/'.join(text_cols)} text in the two sheets "
              f"(for example {changed[0]}). The sheets may come from different sample runs.")

    def labelled(rows):
        return Counter(clean(r.get("label")) for r in rows if clean(r.get("label")))

    for name, rows in (("A", [a[i] for i in both]), ("B", [b[i] for i in both])):
        c = labelled(rows)
        total = sum(c.values())
        bad = {k: v for k, v in c.items() if k not in labels}
        parts = ", ".join(f"{k} {c.get(k, 0)}" for k in labels)
        top = c.get(labels[0], 0)
        share = f"{100 * top / total:.1f}%" if total else "n/a"
        print(f"Reviewer {name}: {total} labelled ({parts}); {labels[0]} share {share}.")
        if bad:
            print(f"  Invalid labels in {name}: {bad}")

    pairs = [(clean(a[i].get("label")), clean(b[i].get("label")), i) for i in both]
    pairs = [p for p in pairs if p[0] in labels and p[1] in labels]
    same = sum(1 for x, y, _ in pairs if x == y)
    print(f"Both labelled and valid: {len(pairs)}. Same label: {same} ({100 * same / len(pairs):.1f}%)." if pairs else "No items labelled by both.")
    if pairs and same == len(pairs) and len(pairs) >= 10:
        print("NOTE: the reviewers agree on every item. That can be genuine, but check that sheet B was labelled "
              "independently and was not a copy of sheet A.")

    matrix = Counter((x, y) for x, y, _ in pairs)
    print("\nReviewer A (rows) against reviewer B (columns):")
    print("  " + "".join(f"{l:>14}" for l in labels))
    for x in labels:
        print(f"{x:>14}" + "".join(f"{matrix.get((x, y), 0):>14}" for y in labels))

    diff = [(x, y, i) for x, y, i in pairs if x != y]
    print(f"\nDisagreements: {len(diff)}")
    for x, y, i in diff:
        print(f"  {i}: A={x}, B={y}")


    if args.adjudicated:
        agreed = {}
        for row in read(args.adjudicated):
            agreed[row["item_id"]] = clean(row.get("agreed_label"))
        final, unresolved, invalid = Counter(), [], []
        for x, y, i in pairs:
            if x == y:
                final[x] += 1
                continue
            label = agreed.get(i, "")
            if not label:
                unresolved.append(i)
            elif label not in labels:
                invalid.append((i, label))
            else:
                final[label] += 1
        n_final = sum(final.values())
        print("\nAfter discussion (items the reviewers agreed on at first, plus the labels they settled together):")
        print("  " + ", ".join(f"{k} {final.get(k, 0)}" for k in labels) + f"; {n_final} items counted.")
        if n_final:
            from evaluation.stats import fmt_rate
            print(f"  {labels[0]}: {fmt_rate(proportion(final.get(labels[0], 0), n_final))}")
        if unresolved:
            print(f"  NOT YET SETTLED (agreed_label blank, left out): {', '.join(unresolved)}")
        if invalid:
            print(f"  INVALID agreed_label (left out): {invalid}")

    if args.out:
        if args.out.exists():
            print(f"\n{args.out} already exists, so it was not overwritten. Choose another name.")
            return 1
        fields = ["item_id", "reviewer_A", "notes_A", "reviewer_B", "notes_B"] + text_cols + ["agreed_label", "discussion"]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="", encoding="utf-8-sig") as handle:
            w = csv.DictWriter(handle, fieldnames=fields)
            w.writeheader()
            for x, y, i in diff:
                row = {"item_id": i, "reviewer_A": x, "notes_A": a[i].get("notes", ""), "reviewer_B": y,
                       "notes_B": b[i].get("notes", ""), "agreed_label": "", "discussion": ""}
                for c in text_cols:
                    row[c] = a[i].get(c, "")
                w.writerow(row)
        print(f"\nWrote {len(diff)} disagreement(s) to {args.out}. The reviewers can fill agreed_label together.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
