import sys
import os
import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mcp_servers.network_server import NetworkServer

@pytest.mark.asyncio
async def test_fetch_street_network_success(tmp_path):
    server = NetworkServer()
    
    mock_overpass_response = {
        "elements": [
            {"type": "node", "id": 1, "lat": 40.7128, "lon": -74.0060},
            {"type": "node", "id": 2, "lat": 40.7138, "lon": -74.0070},
            {
                "type": "way",
                "id": 100,
                "nodes": [1, 2],
                "tags": {
                    "highway": "residential",
                    "name": "Broadway"
                }
            }
        ]
    }
    
    with patch("mcp_servers.network_server._overpass_post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_overpass_response
        
        args = {
            "workspace": str(tmp_path),
            "lat": 40.7128,
            "lng": -74.0060,
            "radius_meters": 500,
            "title": "Test Streets"
        }
        
        res = await server.execute("fetch_street_network", args)
        
        assert res["status"] == "success"
        assert res["features_count"] == 1
        output_layer = Path(res["output_layer"])
        assert output_layer.exists()
        
        # Verify geojson contents
        with open(output_layer) as f:
            geojson = json.load(f)
            
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 1
        feat = geojson["features"][0]
        assert feat["geometry"]["type"] == "LineString"
        assert feat["geometry"]["coordinates"] == [[-74.0060, 40.7128], [-74.0070, 40.7138]]
        assert feat["properties"]["name"] == "Broadway"
        assert feat["properties"]["highway"] == "residential"

@pytest.mark.asyncio
async def test_analyze_street_network_with_geojson_path(tmp_path):
    server = NetworkServer()
    
    # Save a dummy road network to disk
    geojson_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-74.0060, 40.7128], [-74.0070, 40.7138]]
                },
                "properties": {
                    "highway": "residential",
                    "name": "Broadway"
                }
            }
        ]
    }
    
    geojson_file = tmp_path / "streets.geojson"
    with open(geojson_file, "w") as f:
        json.dump(geojson_data, f)
        
    args = {
        "geojson_path": str(geojson_file),
        "workspace": str(tmp_path),
        "title": "Analysis Test"
    }
    
    res = await server.execute("analyze_street_network", args)
    assert "error" not in res
    assert res["status"] == "success"
    assert res["summary"]["total_nodes"] == 2
