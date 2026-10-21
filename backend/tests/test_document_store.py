from app.schemas.documents import DocumentStatus
from app.services.document_store import DocumentStore


def test_records_survive_a_restart(tmp_path):
    path = tmp_path / "documents.json"
    created = DocumentStore(path).add("judgment.pdf")
    reopened = DocumentStore(path)  # simulates restarting the server
    assert reopened.get(created.id).filename == "judgment.pdf"


def test_update_changes_status_and_page_count(store):
    record = store.add("judgment.pdf")
    updated = store.update(record.id, status="ready", page_count=412)
    assert updated.status == DocumentStatus.ready
    assert store.get(record.id).page_count == 412


def test_update_unknown_id_returns_none(store):
    assert store.update("f" * 32, status="ready") is None


def test_delete_removes_record(store):
    record = store.add("judgment.pdf")
    assert store.delete(record.id) is True
    assert store.get(record.id) is None
    assert store.delete(record.id) is False


def test_no_temp_files_left_behind(tmp_path):
    store = DocumentStore(tmp_path / "documents.json")
    store.add("a.pdf")
    store.add("b.pdf")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["documents.json"]


def test_non_ascii_filenames_round_trip(store):
    record = store.add("தீர்ப்பு.pdf")
    assert store.get(record.id).filename == "தீர்ப்பு.pdf"
