import os

from openai import OpenAI
from supabase import create_client

from api.prompts import SYSTEM_PROMPTS

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

RETRIEVE_COUNT = 10
RETRIEVE_COUNT_AUTO = 12  # pull more when searching across all tools


def embed(text: str) -> list[float]:
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding


def retrieve_chunks(tool_id: str, query_embedding: list[float]) -> list[dict]:
    if tool_id == "auto":
        result = supabase.rpc(
            "match_chunks_all",
            {
                "query_embedding": query_embedding,
                "match_count": RETRIEVE_COUNT_AUTO,
            },
        ).execute()
    else:
        result = supabase.rpc(
            "match_chunks",
            {
                "query_embedding": query_embedding,
                "match_tool_id": tool_id,
                "match_count": RETRIEVE_COUNT,
            },
        ).execute()
    return result.data


def build_user_message(chunks: list[dict], client_context: str, question: str) -> str:
    parts = []

    corrections = [c for c in chunks if "correction" in c["chunk_type"]]
    examples = [c for c in chunks if "correction" not in c["chunk_type"]]

    if examples:
        parts.append("Relevant examples from Bizzie's work:\n")
        for i, chunk in enumerate(examples, 1):
            source = f" [{chunk['tool_id']}]" if chunk.get("tool_id") else ""
            parts.append(f"--- Example {i}{source} ---\n{chunk['chunk_text']}")

    if corrections:
        parts.append(
            "\nCorrections and refinements (these override any conflicting examples above):\n"
        )
        for chunk in corrections:
            parts.append(f"--- Correction ---\n{chunk['chunk_text']}")

    if client_context:
        parts.append(f"\nClient details:\n{client_context}")

    parts.append(f"\nRequest: {question}")

    return "\n\n".join(parts)


def query(
    tool_id: str,
    question: str,
    client_context: str = "",
    messages: list[dict] = [],
) -> dict:
    system_prompt = SYSTEM_PROMPTS.get(tool_id)
    if not system_prompt:
        raise ValueError(f"Unknown tool_id: '{tool_id}'")

    # Embed question + client context for retrieval
    query_text = f"{question}\n\n{client_context}" if client_context else question
    query_embedding = embed(query_text)

    chunks = retrieve_chunks(tool_id, query_embedding)
    user_message = build_user_message(chunks, client_context, question)

    # Build message list: system + conversation history + current turn
    openai_messages = [{"role": "system", "content": system_prompt}]
    openai_messages.extend(messages)  # prior turns from the frontend
    openai_messages.append({"role": "user", "content": user_message})

    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=openai_messages,
        temperature=0.3,
    )

    return {
        "answer": response.choices[0].message.content,
        "chunks_used": [
            {
                "position": c["position"],
                "chunk_type": c["chunk_type"],
                "tool_id": c.get("tool_id"),
                "similarity": round(c.get("similarity") or 0, 4),
            }
            for c in chunks
        ],
    }
