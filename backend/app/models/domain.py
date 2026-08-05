from pydantic import BaseModel


class RetrievedChunk(BaseModel):
    id: str
    content: str
    source: str
    score_type: str  # "dense" | "keyword" | "graph"
    score: float = 0.0
    metadata: dict = {}
