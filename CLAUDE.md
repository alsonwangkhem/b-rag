# RAG System — Behavior Strategist Tools

## Project Overview

Building a RAG-powered internal tool that replicates the CEO's (Bizzie's) GPT tools for all behavior strategists. Strategists currently copy-paste into ChatGPT — this brings that capability inside the existing client website with consistent, reliable outputs.

The source material is Bizzie's exported GPT conversation history — multiple markdown files averaging 4,500–12,000 lines each. These are not clean datasets. They are raw teaching conversations in `**You:** ... **ChatGPT:** ...` format (with `* * *` horizontal rule dividers between turns) containing a mixture of content types.

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Next.js | Existing client website |
| Backend | Django | Existing — add Django auth layer later |
| RAG Service | FastAPI | New standalone service — build this first |
| Vector DB | pgvector on Supabase | Free tier — sufficient for this scale |
| Embeddings | OpenAI text-embedding-3-small | Cheap, runs once at ingestion |
| LLM | OpenAI API | Per strategist request |
| Hosting | Railway | Free $5 credits/month — no cold starts |

---

## Source Data Format

All source files are markdown exports of Bizzie's ChatGPT conversations. Actual format is:

```
**You:**

[Bizzie's message]

* * *

**ChatGPT:**

[GPT's response]

* * *

**You:**

[next message]
```

Each file corresponds to one tool (e.g. pattern presentation, red to green cones, ELI questions). Files are NOT clean — they contain a mixture of:
- Teaching moments (Bizzie explaining frameworks to GPT)
- Corrections (Bizzie fixing wrong GPT answers mid-conversation)
- Real client work (Bizzie actually using the tool for a real client)
- Possibly other types — do not assume, let classification discover them

---

## Build Order

1. Classification script
2. Ingestion script
3. FastAPI RAG service
4. Frontend UI (tool selector + chat interface)
5. Django auth layer (later — not now)

---

## Step 1 — Classification Script

**Purpose:** Read raw markdown files and discover chunk types. Do NOT hardcode types — let AI discover them from the content.

**How it works:**
- Read 1000 lines at a time from each markdown file
- Send each batch to OpenAI (gpt-4o)
- Ask it to identify what type of exchange each chunk is — let it name the types itself
- Output a JSON classification map per file

**Output format:**
```json
[
  {
    "position": 1,
    "chunk_text": "You: ...\nChatGPT: ...",
    "discovered_type": "teaching",
    "notes": "Bizzie explaining dominant brain pattern framework"
  },
  {
    "position": 2,
    "chunk_text": "You: ...\nChatGPT: ...",
    "discovered_type": "correction",
    "notes": "Bizzie correcting a wrong answer from position 1"
  }
]
```

**Important:** The markdown files are never modified. The JSON is only a map used by the ingestion script. The markdown is always the source of truth.

**After running:** Review the discovered types with Bizzie. Decide how each type should be treated in ingestion (ingest / skip / ingest with caution).

---

## Step 2 — Ingestion Script

**Purpose:** Use the markdown files + JSON classification map to populate pgvector.

**Chunking strategy:**
- Split on `**You:**` boundaries — every `**You:**` block starts a new chunk
- Keep the `**You:**` message and the following `**ChatGPT:**` response together as one chunk — never split them
- If a ChatGPT response spans multiple paragraphs before the next `You:`, keep it all in the same chunk
- Track position (resets to 1 per file/tool)

**Handling corrections:**
- When a chunk is classified as a correction, find the chunk it corrects (usually the previous chunk on the same topic)
- Store the correction chunk with a flag
- At query time, if both the original and correction are retrieved, the system prompt instructs the LLM to prefer the correction

**pgvector schema:**
```sql
CREATE TABLE chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tool_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  chunk_type TEXT NOT NULL,
  chunk_text TEXT NOT NULL,
  embedding VECTOR(1536),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops);
```

**Cost:** ~$0.50 total for all files using text-embedding-3-small. Runs once.

---

## Step 3 — FastAPI RAG Service

**Purpose:** Standalone service that handles all RAG logic. Django and Next.js call this — they don't know anything about embeddings or retrieval.

**Endpoints:**
```
POST /query
Body: { tool_id, question, client_context (optional) }
Returns: { answer, chunks_used }

GET /health
Returns: { status: "ok" }
```

**Query pipeline per request:**
1. Embed the strategist's question
2. Similarity search in pgvector filtered by `tool_id`
3. Retrieve top 8-12 chunks
4. Assemble prompt: system prompt + retrieved chunks + client context + question
5. Call LLM API
6. Return response

**Auth for now:** None — direct call from frontend during testing phase. Add Django auth middleware later.

**Deployment:** Railway. Set these env vars:
```
OPENAI_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
```

---

## Step 4 — System Prompts (one per tool)

Keep these LEAN. The heavy knowledge lives in RAG — the system prompt only handles behavior.

**Template:**
```
You are the [Tool Name] assistant for a behavior strategy practice.
You have been trained on [framework name] frameworks and examples.

Rules:
- Only answer based on the retrieved context provided
- If the context contains a correction to an earlier answer, always use the corrected version
- If you don't have enough information to answer confidently, say so — never guess
- Keep answers practical and directly usable by a behavior strategist
- Do not reference the source conversation or mention that you were trained on examples
```

---

## Step 5 — Frontend UI

**Location:** Inside existing Next.js website — not a separate app.

**UI per tool:**
- Tool selector (dropdown or sidebar — one per tool e.g. "Pattern Presentation", "Red to Green Cones")
- Chat interface (strategist types question, sees response)
- Optional: paste client document context before asking

**For now:** Frontend calls FastAPI directly (no Django in between). Later: route through Django for auth.

---

## Step 6 — Django Auth Layer (later)

When ready to open to all strategists:
- Django receives the request, validates the user session
- Forwards `{ tool_id, question, client_context }` to FastAPI internal URL
- FastAPI stays unchanged — Django is just a proxy + auth gate

---

## Key Decisions and Why

| Decision | Reason |
|---|---|
| RAG not fine-tuning | Source material is too large for system prompt, RAG is more maintainable |
| pgvector not Pinecone | No new infrastructure, Postgres already in stack, free tier sufficient |
| FastAPI separate service | Decoupled from Django — can iterate chunking/retrieval without touching main app |
| Railway not Render | No cold starts on free tier for 4-5 testers |
| Classification before ingestion | Prevents garbage entering the vector DB — most common cause of RAG hallucination |
| Let OpenAI (gpt-4o) discover chunk types | Don't hardcode types that might not match the actual content |
| Lean system prompts | Heavy knowledge lives in RAG — system prompt only handles behavior rules |
| Never split You+ChatGPT pairs | Each exchange is a complete unit of knowledge — splitting loses context |

---

## What We Are NOT Doing

- No fine-tuning (unnecessary complexity)
- No Pinecone/Weaviate (overkill for this scale)
- No manual reformatting of markdown files (script handles it)
- No hardcoded chunk type labels (let classification discover them)
- No heavy system prompts (RAG carries the knowledge)
- No modifying source markdown files (they are read-only source of truth)

---

Start with one tool's markdown file as a test run before processing all.