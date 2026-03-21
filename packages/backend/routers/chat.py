from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google import genai
import json
import os

router = APIRouter()

SYSTEM_PROMPT = (
    "You are an expert urban planning assistant embedded in a desktop GIS application. "
    "You help with zoning analysis, land use planning, transportation networks, "
    "environmental impact, building codes, community development, and spatial analysis. "
    "Keep answers concise and actionable. When relevant, suggest how the user could "
    "visualize data on the map or save findings as artifacts."
)


def get_client():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    client = get_client()
    history: list[dict] = []

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            user_content = message.get("content", "")

            if not client:
                await websocket.send_text(json.dumps({
                    "type": "stream",
                    "content": "GEMINI_API_KEY is not set. Add it to packages/backend/.env",
                }))
                await websocket.send_text(json.dumps({"type": "end", "content": ""}))
                continue

            history.append({"role": "user", "parts": [{"text": user_content}]})

            try:
                response = client.models.generate_content_stream(
                    model="gemini-2.5-flash",
                    contents=history,
                    config=genai.types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                    ),
                )
                full_reply = ""
                for chunk in response:
                    if chunk.text:
                        full_reply += chunk.text
                        await websocket.send_text(json.dumps({
                            "type": "stream",
                            "content": chunk.text,
                        }))

                history.append({"role": "model", "parts": [{"text": full_reply}]})
            except Exception as e:
                await websocket.send_text(json.dumps({
                    "type": "stream",
                    "content": f"\n\n[Error from Gemini: {e}]",
                }))

            await websocket.send_text(json.dumps({"type": "end", "content": ""}))
    except WebSocketDisconnect:
        pass
