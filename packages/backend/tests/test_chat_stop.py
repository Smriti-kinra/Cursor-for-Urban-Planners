import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import app


def test_stop_message_is_acknowledged_by_websocket():
    with TestClient(app) as client:
        with client.websocket_connect("/api/chat/ws") as websocket:
            websocket.send_json({"type": "stop"})
            message = websocket.receive_json()
            assert message["type"] == "stopped"
