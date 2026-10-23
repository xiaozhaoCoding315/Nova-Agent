"""Tiny MCP stdio server used by the MCP client tests."""
import json
import sys


def respond(payload, request_id):
    print(json.dumps({"jsonrpc": "2.0", "id": request_id, **payload}, ensure_ascii=False), flush=True)


for line in sys.stdin:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        continue
    if method == "initialize":
        respond({
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "1.0.0"},
            }
        }, request_id)
    elif method == "tools/list":
        respond({
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo the input text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    },
                    {
                        "name": "write_secret",
                        "description": "Not allowlisted",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]
            }
        }, request_id)
    elif method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") == "echo":
            text = str((params.get("arguments") or {}).get("text") or "")
            respond({
                "result": {
                    "content": [{"type": "text", "text": f"echo: {text}"}],
                }
            }, request_id)
        else:
            respond({
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "tool not allowed"}],
                }
            }, request_id)
    else:
        respond({"error": {"code": -32601, "message": "method not found"}}, request_id)
