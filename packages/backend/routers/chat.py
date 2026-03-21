from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
import json
import os
import httpx

router = APIRouter()

SYSTEM_PROMPT = (
    "You are an expert urban planning assistant embedded in a desktop GIS application. "
    "You help with zoning analysis, land use planning, transportation networks, "
    "environmental impact, building codes, community development, and spatial analysis. "
    "Keep answers concise and actionable. "
    "You have tools: web_search (search the internet), geocode (find coordinates), "
    "fly_to (move the map), highlight_features (highlight map features), "
    "and create_artifact (save notes/analyses). "
    "Use fly_to when the user mentions a specific location they want to see on the map. "
    "Use highlight_features when discussing specific features in their loaded layers. "
    "Use create_artifact to save important findings as project artifacts."
)

TOOL_DECLARATIONS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="web_search",
                description="Search the web for information about urban planning, regulations, demographics, real estate, etc.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "query": {"type": "STRING", "description": "The search query"},
                    },
                    "required": ["query"],
                },
            ),
            types.FunctionDeclaration(
                name="geocode",
                description="Convert an address or place name to geographic coordinates (latitude, longitude)",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "query": {"type": "STRING", "description": "Address or place name to geocode"},
                    },
                    "required": ["query"],
                },
            ),
            types.FunctionDeclaration(
                name="fly_to",
                description="Move the map view to specific coordinates. Use when user mentions a location.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "lat": {"type": "NUMBER", "description": "Latitude"},
                        "lng": {"type": "NUMBER", "description": "Longitude"},
                        "zoom": {"type": "NUMBER", "description": "Zoom level 1-20, default 15"},
                    },
                    "required": ["lat", "lng"],
                },
            ),
            types.FunctionDeclaration(
                name="highlight_features",
                description="Highlight specific features on a loaded map layer by filtering on a property value",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "layer_name": {"type": "STRING", "description": "Name of the layer"},
                        "property_name": {"type": "STRING", "description": "Property to filter by"},
                        "property_value": {"type": "STRING", "description": "Value to match"},
                    },
                    "required": ["layer_name", "property_name", "property_value"],
                },
            ),
            types.FunctionDeclaration(
                name="create_artifact",
                description="Save a note, analysis, or report as an artifact in the project",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING", "description": "Title of the artifact"},
                        "content": {"type": "STRING", "description": "Content text"},
                        "artifact_type": {
                            "type": "STRING",
                            "description": "Type: note, analysis, report, or sketch",
                        },
                    },
                    "required": ["title", "content", "artifact_type"],
                },
            ),
        ]
    )
]


def get_client():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


async def execute_web_search(query: str) -> dict:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        return {
            "results": [
                {"title": r.get("title", ""), "body": r.get("body", ""), "href": r.get("href", "")}
                for r in results
            ]
        }
    except Exception as e:
        return {"error": str(e)}


async def execute_geocode(query: str) -> dict:
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 5},
                headers={"User-Agent": "CursorUrbanPlanners/1.0"},
            )
            results = resp.json()
            return {
                "results": [
                    {"display_name": r.get("display_name", ""), "lat": r.get("lat"), "lon": r.get("lon")}
                    for r in results
                ]
            }
    except Exception as e:
        return {"error": str(e)}


def create_artifact_in_db(args: dict) -> dict:
    try:
        from database import get_connection
        conn = get_connection()
        cursor = conn.execute(
            "INSERT INTO artifacts (title, content, artifact_type) VALUES (?, ?, ?)",
            (args.get("title", "Untitled"), args.get("content", ""), args.get("artifact_type", "note")),
        )
        conn.commit()
        artifact_id = cursor.lastrowid
        conn.close()
        return {"status": "created", "id": artifact_id}
    except Exception as e:
        return {"error": str(e)}


@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    client = get_client()
    history: list = []

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            user_content = message.get("content", "")
            map_context = message.get("map_context")

            if not client:
                await websocket.send_text(json.dumps({
                    "type": "stream",
                    "content": "GEMINI_API_KEY is not set. Add it to packages/backend/.env",
                }))
                await websocket.send_text(json.dumps({"type": "end"}))
                continue

            system = SYSTEM_PROMPT
            if map_context:
                system += f"\n\nCurrent map state:\n{json.dumps(map_context, indent=2)}"

            history.append({"role": "user", "parts": [{"text": user_content}]})

            config = types.GenerateContentConfig(
                system_instruction=system,
                tools=TOOL_DECLARATIONS,
            )

            try:
                for _round in range(5):
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=history,
                        config=config,
                    )

                    if not response.candidates:
                        await websocket.send_text(json.dumps({
                            "type": "stream", "content": "No response generated.",
                        }))
                        break

                    candidate = response.candidates[0]
                    parts = candidate.content.parts

                    func_calls = [p for p in parts if getattr(p, "function_call", None)]

                    if not func_calls:
                        text = "".join(p.text for p in parts if getattr(p, "text", None))
                        if text:
                            await websocket.send_text(json.dumps({"type": "stream", "content": text}))
                            history.append({"role": "model", "parts": [{"text": text}]})
                        break

                    history.append(candidate.content)
                    func_response_parts = []

                    for part in func_calls:
                        fc = part.function_call
                        func_name = fc.name
                        func_args = dict(fc.args) if fc.args else {}

                        await websocket.send_text(json.dumps({
                            "type": "tool_use", "tool": func_name, "args": func_args,
                        }))

                        if func_name in ("fly_to", "highlight_features"):
                            await websocket.send_text(json.dumps({
                                "type": "action", "action": func_name, "payload": func_args,
                            }))
                            result = {"status": "success", "message": f"Map action {func_name} executed."}
                        elif func_name == "create_artifact":
                            result = create_artifact_in_db(func_args)
                            await websocket.send_text(json.dumps({
                                "type": "action", "action": "refresh_artifacts", "payload": {},
                            }))
                        elif func_name == "web_search":
                            result = await execute_web_search(func_args.get("query", ""))
                        elif func_name == "geocode":
                            result = await execute_geocode(func_args.get("query", ""))
                        else:
                            result = {"error": f"Unknown function: {func_name}"}

                        func_response_parts.append(
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=func_name, response=result,
                                )
                            )
                        )

                    history.append(types.Content(role="user", parts=func_response_parts))

            except Exception as e:
                await websocket.send_text(json.dumps({
                    "type": "stream", "content": f"\n\n[Error from Gemini: {e}]",
                }))

            await websocket.send_text(json.dumps({"type": "end"}))
    except WebSocketDisconnect:
        pass
