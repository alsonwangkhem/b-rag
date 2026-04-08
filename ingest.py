"""
Ingestion script — Step 2
Reads classification JSONs, generates embeddings via OpenAI,
and inserts everything into Supabase pgvector.
"""

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client

load_dotenv()

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# Ingest everything — all chunk types go into the vector DB
SKIP_TYPES: set = set()

# Classification JSON filename stem → tool_id used in the database
TOOL_IDS = {
    "___ specific strategy ELI": "eli",
    "__ ACB diagnostic session editing tool": "acb",
    "___ Fill ins- Review Source Belief Structure": "fill_ins",
    "___Simplified client steps": "simplified_steps",
    "___Timeline Dysregulated behavior summary": "timeline",
}

EMBEDDING_BATCH_SIZE = 50


def get_embeddings(texts: list[str]) -> list[list[float]]:
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return [item.embedding for item in response.data]


def ingest_file(json_path: Path, tool_id: str):
    chunks = json.loads(json_path.read_text(encoding="utf-8"))

    to_ingest = [c for c in chunks if c["discovered_type"] not in SKIP_TYPES]
    skipped = len(chunks) - len(to_ingest)

    print(f"\n{json_path.name}")
    print(f"  tool_id : {tool_id}")
    print(f"  chunks  : {len(chunks)} total, {len(to_ingest)} to ingest, {skipped} skipped")

    # Wipe any previous run for this tool so re-running is safe
    supabase.table("chunks").delete().eq("tool_id", tool_id).execute()
    print(f"  Cleared existing rows for '{tool_id}'")

    inserted = 0
    for start in range(0, len(to_ingest), EMBEDDING_BATCH_SIZE):
        batch = to_ingest[start : start + EMBEDDING_BATCH_SIZE]
        end = start + len(batch)
        print(f"  Embedding {start + 1}–{end}...")

        texts = [c["chunk_text"] for c in batch]
        embeddings = get_embeddings(texts)

        rows = [
            {
                "tool_id": tool_id,
                "position": chunk["position"],
                "chunk_type": chunk["discovered_type"],
                "chunk_text": chunk["chunk_text"],
                "embedding": embedding,
            }
            for chunk, embedding in zip(batch, embeddings)
        ]

        supabase.table("chunks").insert(rows).execute()
        inserted += len(rows)

        # Avoid hitting OpenAI rate limits between batches
        if end < len(to_ingest):
            time.sleep(0.5)

    print(f"  Inserted {inserted} rows ✓")


def main():
    json_files = sorted(Path("classifications").glob("*.json"))

    if not json_files:
        print("No JSON files found in classifications/")
        return

    for json_path in json_files:
        tool_id = TOOL_IDS.get(json_path.stem)
        if not tool_id:
            print(f"WARNING: no tool_id mapping for {json_path.name} — skipping")
            continue
        ingest_file(json_path, tool_id)

    print("\nDone — all files ingested.")


if __name__ == "__main__":
    main()
