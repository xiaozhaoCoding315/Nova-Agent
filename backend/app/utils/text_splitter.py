import re
import uuid
from dataclasses import dataclass

@dataclass
class Chunk:
    id: str
    content: str
    source: str
    metadata: dict

def clean_markdown(text: str) -> str:
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)
    return text.strip()

def chunk_text(text: str, source: str, max_chunk_size: int = 800, overlap: int = 100) -> list:
    chunks = []
    sections = re.split(r'(?=#{1,3}\s)', text)
    chunk_idx = 0
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= max_chunk_size:
            uid = str(uuid.uuid4())
            chunks.append(Chunk(id=uid, content=section, source=source, metadata={"chunk_index": chunk_idx}))
            chunk_idx += 1
            continue
        parts = section.split('\n\n')
        buffer = ""
        for part in parts:
            if len(buffer) + len(part) > max_chunk_size and buffer:
                uid = str(uuid.uuid4())
                chunks.append(Chunk(id=uid, content=buffer.strip(), source=source, metadata={"chunk_index": chunk_idx}))
                buffer = buffer[-overlap:] + '\n\n' + part
                chunk_idx += 1
            else:
                buffer = buffer + '\n\n' + part if buffer else part
        if buffer.strip():
            uid = str(uuid.uuid4())
            chunks.append(Chunk(id=uid, content=buffer.strip(), source=source, metadata={"chunk_index": chunk_idx}))
            chunk_idx += 1
    return chunks
