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
    # ELI group
    "___ specific strategy ELI": "eli",
    "Generate ELI questions": "eli",
    "___ ACB to ELI Q": "eli",
    # ACB group
    "__ ACB diagnostic session editing tool": "acb",
    # Cones group
    "___Green Cones Tool": "cones",
    "___Red to Green Cone Strategy": "cones",
    # Timeline group
    "___Timeline Dysregulated behavior summary": "timeline",
    "___Timeline Pattern Opposition - Prompt": "timeline",
    # Source Belief group
    "___ Fill ins- Review Source Belief Structure": "source_belief",
    "__Rebellon Zones for FS Doc __": "source_belief",
    # Simplified Steps
    "___Simplified client steps": "simplified_steps",
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

    # Wipe each tool_id once upfront so grouped files don't overwrite each other
    seen_tool_ids: set = set()
    for json_path in json_files:
        tool_id = TOOL_IDS.get(json_path.stem)
        if tool_id and tool_id not in seen_tool_ids:
            supabase.table("chunks").delete().eq("tool_id", tool_id).execute()
            print(f"Cleared existing rows for '{tool_id}'")
            seen_tool_ids.add(tool_id)

    for json_path in json_files:
        tool_id = TOOL_IDS.get(json_path.stem)
        if not tool_id:
            print(f"WARNING: no tool_id mapping for {json_path.name} — skipping")
            continue
        ingest_file(json_path, tool_id)

    print("\nDone — all files ingested.")


if __name__ == "__main__":
    main()
