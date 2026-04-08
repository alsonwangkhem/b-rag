"""
Classification script — Step 1
Reads a markdown file of Bizzie's GPT conversations, parses it into
complete You+ChatGPT exchange pairs, sends batches to OpenAI for
classification, and writes a JSON map.
"""

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BATCH_SIZE = 10  # exchange pairs per OpenAI call


def parse_exchanges(filepath: str) -> list[dict]:
    """Parse markdown file into a list of complete You+ChatGPT exchange dicts."""
    text = Path(filepath).read_text(encoding="utf-8")

    # Find every speaker turn by scanning for **You:** and **ChatGPT:** headers.
    # We do NOT split on * * * because ChatGPT responses contain * * * internally.
    turn_pattern = re.compile(r"(\*\*(?:You|ChatGPT):\*\*)", re.MULTILINE)
    matches = list(turn_pattern.finditer(text))

    # Slice text between consecutive speaker markers to get full turn content
    turns = []
    for idx, match in enumerate(matches):
        speaker = "You" if "You" in match.group() else "ChatGPT"
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        # Strip trailing * * * divider that separates this turn from the next
        content = re.sub(r"\s*\*\s*\*\s*\*\s*$", "", content).strip()
        turns.append({"speaker": speaker, "content": content})

    # Group into You+ChatGPT pairs
    exchanges = []
    position = 1
    i = 0
    while i < len(turns):
        if turns[i]["speaker"] == "You":
            if i + 1 < len(turns) and turns[i + 1]["speaker"] == "ChatGPT":
                chunk_text = turns[i]["content"] + "\n\n* * *\n\n" + turns[i + 1]["content"]
                exchanges.append({"position": position, "chunk_text": chunk_text})
                position += 1
                i += 2
            else:
                i += 1
        else:
            i += 1

    return exchanges


def classify_batch(batch: list[dict], tool_name: str) -> list[dict]:
    """Send a batch of exchange pairs to OpenAI and get classification back."""

    numbered_chunks = ""
    for item in batch:
        numbered_chunks += f"=== CHUNK {item['position']} ===\n{item['chunk_text']}\n\n"

    prompt = f"""You are analyzing conversation chunks from a behavior strategy coaching tool called "{tool_name}".

Each chunk is one complete exchange between Bizzie (the CEO/expert) and ChatGPT.

For each chunk, identify what TYPE of exchange it is. Do NOT use predefined categories — discover the types yourself based on what you actually see in the content. Use descriptive names like "teaching", "real_client_work", "correction", "framework_explanation", "quality_check", etc. — whatever fits best.

Return a JSON object with a single key "chunks" whose value is an array. Each item in the array must have:
- "discovered_type": your type label (snake_case)
- "notes": one sentence explaining what is happening in this chunk

Return one item per chunk, in the same order they were given. Do not skip any chunks.

Chunks to classify:
{numbered_chunks}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    parsed = json.loads(raw)
    chunks = parsed["chunks"]

    # Log first batch only so we can verify the shape
    if batch[0]["position"] == 1:
        print("\n  [DEBUG] First batch response sample (first 2 items):")
        for item in chunks[:2]:
            print(f"    {item}")
        print()

    return chunks


def classify_file(filepath: str, output_path: str):
    tool_name = Path(filepath).stem.lstrip("_ ")
    print(f"\nTool: {tool_name}")

    exchanges = parse_exchanges(filepath)
    print(f"Found {len(exchanges)} exchange pairs")

    all_results = []

    for start in range(0, len(exchanges), BATCH_SIZE):
        batch = exchanges[start : start + BATCH_SIZE]
        end = start + len(batch)
        print(f"  Classifying chunks {start + 1}–{end}...")

        classifications = classify_batch(batch, tool_name)

        # Merge by order — classifications come back in the same order we sent them
        for i, item in enumerate(batch):
            classification = classifications[i] if i < len(classifications) else {}
            all_results.append(
                {
                    "position": item["position"],
                    "chunk_text": item["chunk_text"],
                    "discovered_type": classification.get("discovered_type", "unknown") if isinstance(classification, dict) else "unknown",
                    "notes": classification.get("notes", "") if isinstance(classification, dict) else "",
                }
            )

    Path(output_path).write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Saved {len(all_results)} classified chunks → {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default to ELI file for the first test run
        target = "gpt-tools/___ specific strategy ELI.md"
    else:
        target = sys.argv[1]

    if not Path(target).exists():
        print(f"File not found: {target}")
        sys.exit(1)

    output = "classifications/" + Path(target).stem + ".json"
    Path("classifications").mkdir(exist_ok=True)

    classify_file(target, output)
