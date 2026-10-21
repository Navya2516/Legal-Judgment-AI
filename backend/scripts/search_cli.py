"""Try a search against a running server and print the passages with page numbers.

Usage (server must be running):
    python scripts/search_cli.py <document_id> "your question" [top_k]
"""
import sys
import textwrap

import httpx

BASE = "http://127.0.0.1:8000/api/v1/documents"


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    doc_id, query = sys.argv[1], sys.argv[2]
    top_k = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    response = httpx.post(f"{BASE}/{doc_id}/search", json={"query": query, "top_k": top_k}, timeout=120)
    if response.status_code != 200:
        print(response.status_code, response.json().get("error", response.text))
        return 1
    body = response.json()
    print(f"Query: {body['query']}  (model: {body['embedding_model']})\n")
    for hit in body["hits"]:
        chunk = hit["chunk"]
        pages = chunk["page_start"] if chunk["page_start"] == chunk["page_end"] else f"{chunk['page_start']}-{chunk['page_end']}"
        print(f"#{hit['rank']}  score {hit['score']:.3f}  PDF page {pages}  (chunk {chunk['chunk_id']})")
        print(textwrap.indent(textwrap.fill(chunk["text"], 100), "    "), "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
