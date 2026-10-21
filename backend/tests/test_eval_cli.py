"""The command line must never report success when it checked nothing."""
from evaluation import gold as gold_mod
from evaluation.run import main
from tests import pdf_factory


def test_gold_check_says_nothing_was_checked_for_blank_files(tmp_path, capsys):
    pdfs, gold = tmp_path / "pdfs", tmp_path / "gold"
    pdfs.mkdir()
    pdf_factory.make_text_pdf(pdfs / "case.pdf", ["The court dismissed the appeal with costs of five thousand rupees."] * 3)
    gold_mod.write_template(gold / "case.questions.csv")
    code = main(["gold-check", "--pdfs", str(pdfs), "--gold", str(gold)])
    out = capsys.readouterr().out
    assert code == 1 and "Nothing was checked" in out and "All checked quotes" not in out


def test_find_needs_a_real_phrase(tmp_path):
    import pytest

    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    pdf_factory.make_text_pdf(pdfs / "case.pdf", ["x"] * 1)
    with pytest.raises(SystemExit):
        main(["find", "phrase", "--pdfs", str(pdfs)])
