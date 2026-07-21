import json

from fastapi import WebSocket


async def send_action(ws: WebSocket, action: str, payload: dict) -> None:
    await ws.send_text(json.dumps({"type": "action", "action": action, "payload": payload}))
