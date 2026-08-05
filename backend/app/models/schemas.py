from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


class ChatResponse(BaseModel):
    session_id: str
    tokens: int
    retrieval_time_ms: float


class RetrievedItem(BaseModel):
    id: str
    content: str
    source: str
    score_type: str
    score: float


class SSERetrieval(BaseModel):
    type: str = "retrieval"
    data: list[RetrievedItem]


class SSEToken(BaseModel):
    type: str = "token"
    content: str


class SSEResponseInfo(BaseModel):
    type: str = "done"
    session_id: str
    retrieval_time_ms: float
    tokens: int
