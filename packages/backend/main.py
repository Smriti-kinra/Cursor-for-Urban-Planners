from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routers import files, chat, artifacts, reports, geocode, streetview
from tools import http as http_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    await http_client.aclose()


app = FastAPI(title="Cursor Urban Planners API", lifespan=lifespan)

# Allow only loopback origins. The renderer runs as a file:// or
# http://localhost:* and the Electron preload bridges all other channels.
# Wide-open CORS would let any browser tab on the user's machine hit the
# backend.
_LOOPBACK_RE = re.compile(r"^(file://|app://|https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?)$")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_LOOPBACK_RE.pattern,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(artifacts.router, prefix="/api/artifacts", tags=["artifacts"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(geocode.router, prefix="/api/geocode", tags=["geocode"])
app.include_router(streetview.router, prefix="/api/streetview", tags=["streetview"])


@app.get("/health")
async def health():
    return {"status": "ok"}
