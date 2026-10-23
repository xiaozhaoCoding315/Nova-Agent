from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    """A retrieval hit. For repo chunks, path/line_start/line_end point into
    the indexed file so the UI can render an accurate file:line citation."""

    id: str
    content: str
    path: str = ""
    line_start: int = 0
    line_end: int = 0
    lang: str = ""
    kind: str = "code"          # code | doc
    score_type: str = ""        # dense | keyword
    score: float = 0.0
    metadata: dict = Field(default_factory=dict)