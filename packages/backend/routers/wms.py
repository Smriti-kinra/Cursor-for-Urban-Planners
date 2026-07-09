"""WMS proxy routes — avoids CORS when the renderer calls GetFeatureInfo
or GetCapabilities against external WMS servers that don't set
Access-Control-Allow-Origin headers.

All routes proxy through the backend so requests arrive with a proper
server-side User-Agent and no browser CORS restrictions.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

_WMS_TIMEOUT = 12.0  # seconds


def _build_sep(url: str) -> str:
    return "&" if "?" in url else "?"


# ── GetFeatureInfo proxy ──────────────────────────────────────────────────────

@router.get("/featureinfo")
async def wms_featureinfo(
    url: str = Query(..., description="Base WMS URL"),
    layer_name: str = Query(..., description="Layer name (query_layers)"),
    bbox: str = Query(..., description="Bounding box as west,south,east,north"),
    width: int = Query(800),
    height: int = Query(600),
    x: int = Query(..., description="Click pixel X"),
    y: int = Query(..., description="Click pixel Y"),
    version: str = Query("1.1.1", description="WMS version (1.1.1 or 1.3.0)"),
    feature_count: int = Query(5),
):
    """
    Proxy a WMS GetFeatureInfo request to avoid CORS restrictions in the
    Electron renderer. Tries application/json first; falls back to
    text/xml (GML). Returns a normalised JSON payload.
    """
    sep = _build_sep(url)
    # WMS 1.3.0 uses 'i'/'j' instead of 'x'/'y', and 'CRS' instead of 'SRS'.
    if version == "1.3.0":
        pixel_params = f"&i={x}&j={y}"
        srs_param = "CRS=EPSG:4326"
    else:
        pixel_params = f"&x={x}&y={y}"
        srs_param = "SRS=EPSG:4326"

    base_params = (
        f"{sep}service=WMS&version={version}&request=GetFeatureInfo"
        f"&layers={layer_name}&query_layers={layer_name}&styles="
        f"&{srs_param}&bbox={bbox}&width={width}&height={height}"
        f"&feature_count={feature_count}"
    )

    errors: list[str] = []

    async with httpx.AsyncClient(timeout=_WMS_TIMEOUT, follow_redirects=True) as client:
        # 1. Try JSON format
        try:
            json_url = url + base_params + pixel_params + "&info_format=application/json"
            res = await client.get(json_url)
            ct = res.headers.get("content-type", "")
            if res.status_code == 200 and "json" in ct:
                return res.json()
        except Exception as exc:
            errors.append(f"JSON attempt: {exc}")

        # 2. Try GML/XML and convert to a minimal GeoJSON-like dict
        try:
            xml_url = url + base_params + pixel_params + "&info_format=text/xml"
            res = await client.get(xml_url)
            if res.status_code == 200:
                text = res.text.strip()
                if not text or "no features" in text.lower():
                    return {"type": "FeatureCollection", "features": []}
                props = _parse_gml_props(text)
                if props:
                    return {
                        "type": "FeatureCollection",
                        "features": [{"type": "Feature", "geometry": None, "properties": props}],
                    }
                # Return raw text as a single property so the UI can still show it.
                plain = " ".join(text.replace("<", " <").split())
                # Strip XML tags
                import re
                plain = re.sub(r"<[^>]+>", " ", plain).strip()
                plain = re.sub(r"\s+", " ", plain)[:600]
                if plain:
                    return {
                        "type": "FeatureCollection",
                        "features": [
                            {"type": "Feature", "geometry": None, "properties": {"info": plain}}
                        ],
                    }
        except Exception as exc:
            errors.append(f"XML attempt: {exc}")

    # Nothing worked — return empty rather than crashing the UI
    return {"type": "FeatureCollection", "features": [], "_errors": errors}


def _parse_gml_props(xml_text: str) -> dict | None:
    """
    Best-effort extraction of key/value pairs from a WMS GetFeatureInfo
    XML response. Handles both GML FeatureCollection and plain text/xml
    key-value formats.
    """
    try:
        root = ET.fromstring(xml_text)
        props: dict[str, str] = {}
        # Strip namespace from tag for comparison
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            text = (elem.text or "").strip()
            if text and tag not in {"FeatureCollection", "featureMember", "Feature", "GML_RESPONSE"}:
                # Avoid duplicating the tag if it appears many times;
                # only keep the first non-empty value.
                if tag not in props:
                    props[tag] = text
        return props if props else None
    except ET.ParseError:
        return None


# ── GetCapabilities proxy / layer list ───────────────────────────────────────

@router.get("/capabilities")
async def wms_capabilities(
    url: str = Query(..., description="Base WMS URL"),
):
    """
    Proxy a GetCapabilities request and return the list of available layer
    names and titles. Used by the frontend for re-validation and layer
    discovery without hitting CORS.
    """
    sep = _build_sep(url)
    caps_url = f"{url}{sep}service=WMS&request=GetCapabilities"

    async with httpx.AsyncClient(timeout=_WMS_TIMEOUT, follow_redirects=True) as client:
        try:
            res = await client.get(caps_url)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not reach WMS server: {exc}")

        if res.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"WMS server returned HTTP {res.status_code}",
            )

        layers = _parse_capabilities_layers(res.text)
        return {"layers": layers}


def _parse_capabilities_layers(xml_text: str) -> list[dict]:
    """Extract all queryable layer entries from a GetCapabilities XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Strip namespaces
    def strip_ns(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    layers: list[dict] = []
    seen: set[str] = set()

    for elem in root.iter():
        if strip_ns(elem.tag) != "Layer":
            continue
        name_el = next(
            (c for c in elem if strip_ns(c.tag) == "Name"), None
        )
        title_el = next(
            (c for c in elem if strip_ns(c.tag) == "Title"), None
        )
        if name_el is not None and name_el.text:
            name = name_el.text.strip()
            if name and name not in seen:
                seen.add(name)
                layers.append({
                    "name": name,
                    "title": (title_el.text or name).strip() if title_el is not None else name,
                    "queryable": elem.attrib.get("queryable", "0") == "1",
                })

    return layers
