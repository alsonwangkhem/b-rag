from dotenv import load_dotenv

load_dotenv()  # must run before anything that reads env vars

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.rag import query as rag_query

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://admin.therewirelab.com",
]


class Message(BaseModel):
    role: str   # "user" or "assistant"
    content: str


class QueryRequest(BaseModel):
    tool_id: str = "auto"
    question: str
    client_context: str = ""
    messages: list[Message] = []  # conversation history from the frontend


class QueryResponse(BaseModel):
    answer: str
    chunks_used: list[dict]


app = FastAPI(title="Break RAG API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query_endpoint(request: QueryRequest):
    try:
        result = rag_query(
            tool_id=request.tool_id,
            question=request.question,
            client_context=request.client_context,
            messages=[m.model_dump() for m in request.messages],
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
