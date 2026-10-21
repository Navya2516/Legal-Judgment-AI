"""Makes a synthetic multi-page PDF (invented case, invented text) for the browser test."""
import sys
from pathlib import Path

import pymupdf

PAGES = [
    "IN THE SUPREME COURT OF SAMPLELAND. Civil Appeal No. 1234 of 2020. Ramesh Kumar (Appellant) versus State Housing Board (Respondent). "
    "This is an invented judgment used only to test software. Judgment delivered on 14 March 2021. The appellant purchased agricultural land in 1998 and "
    "the seller delivered possession, but the sale deed was later disputed on the ground that the registration fee had not been paid.",
    "The trial court held that the sale deed was invalid under Section 17 of the Registration Act, 1908. The High Court affirmed that view. "
    "The appellant contends that Article 300A protects his property and that Article 21 requires fair procedure before he is deprived of possession.",
    "Issue. Whether a sale deed is valid when the registration fee was not paid at the time of presentation. Whether Article 300A protects a purchaser who has been in possession for more than twenty years.",
    "Reasoning. The Court finds that registration is mandatory under the Registration Act and that a document which is not registered does not convey title. "
    "However, Article 300A requires that no person be deprived of property save by authority of law, and the Board identified no such law. Article 21 was also considered.",
    "Order. The appeal is partly allowed. The Board shall not disturb the possession of the appellant. The appellant shall present the sale deed for registration within eight weeks, "
    "and the Board shall pay costs of Rs 5,000 to the appellant within four weeks of this judgment.",
]

if __name__ == "__main__":
    out = Path(sys.argv[1])
    doc = pymupdf.open()
    for text in PAGES:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 520, 760), text, fontsize=12)
    doc.save(out)
