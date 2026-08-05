import re
from typing import Optional

ENTITY_PATTERNS = {
    "framework": re.compile(r'\b(FastAPI|Django|Flask|React|Vue|Spring|Next\.js|Express|Angular|Svelte|PyTorch|TensorFlow|Redis|Kafka|Nginx|Docker|Kubernetes|Git|PostgreSQL|Qdrant|Neo4j|Elasticsearch|Pydantic|SQLAlchemy|Celery|RabbitMQ|GraphQL|REST|gRPC|WebSocket|OAuth|JWT|HTTPS|TCP|UDP|HTTP|gRPC)\b', re.IGNORECASE),
    "function": re.compile(r'(?:function|def |class |装饰器|中间件|方法|API|路由|端点|装饰器)\s+([a-zA-Z_][\w.]{1,80})'),
    "error": re.compile(r'((?:Error|Exception|报错|错误|失败|Warning|Traceback)[:\s]*([^\n.,]{5,100}))', re.IGNORECASE),
    "api": re.compile(r'(?:GET|POST|PUT|DELETE|PATCH)\s+(/\S+)'),
    "concept": re.compile(r'(?:依赖注入|中间件|路由|序列化|异步|并发|缓存|认证|授权|ORM|迁移|蓝图|生命周期|钩子|事件|信号|管道|代理|负载均衡|微服务|容器化|CI/CD|DevOps|敏捷|测试驱动|领域驱动|设计模式|架构模式|重构|性能优化|安全防护|数据验证|错误处理|日志记录|配置管理|部署|监控|告警)'),
}

# Co-occurrence window: entities appearing in same paragraph are "related"
def extract_entities(text: str, source: str) -> list:
    """Return [{name, type, source}]."""
    entities = []
    seen = set()
    for etype, pattern in ENTITY_PATTERNS.items():
        for match in pattern.finditer(text):
            name = next((g for g in match.groups() if g), match.group(0))
            name = name.strip()[:200]
            key = f"{name.lower()}:{etype}"
            if key not in seen and len(name) > 1:
                seen.add(key)
                entities.append({"name": name, "type": etype, "source": source})
    return entities


def extract_relationships(text: str, source: str) -> list:
    """Extract SIMILAR_TO and FOLLOWS relationships from text structure."""
    relationships = []
    paragraphs = text.split('\n\n')

    for para in paragraphs:
        para_entities = extract_entities(para, source)
        if len(para_entities) < 2:
            continue

        # SIMILAR_TO: entities co-occurring in same paragraph
        for i in range(len(para_entities)):
            for j in range(i + 1, min(i + 5, len(para_entities))):
                a, b = para_entities[i], para_entities[j]
                if a["name"].lower() != b["name"].lower():
                    relationships.append({
                        "from": a["name"],
                        "to": b["name"],
                        "type": "SIMILAR_TO",
                        "source": source,
                    })

        # FOLLOWS: sequential entities in ordered context (e.g. tutorial steps)
        if any(kw in para for kw in ['首先', '然后', '接着', '最后', '第一步', '第二步', '首先', '其次', 'next', 'then', 'step']):
            for i in range(len(para_entities) - 1):
                relationships.append({
                    "from": para_entities[i]["name"],
                    "to": para_entities[i + 1]["name"],
                    "type": "FOLLOWS",
                    "source": source,
                })

    return relationships
