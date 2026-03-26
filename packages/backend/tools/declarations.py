"""
Core tool declarations — provider-agnostic, plain JSON Schema.

These are the tools the AI can invoke to control the map, search, measure,
and create artifacts.  MCP servers add their own on top of these.
"""

from llm.base import ToolDeclaration

CORE_TOOLS: list[ToolDeclaration] = [
    # ── Search ──
    ToolDeclaration(
        name="web_search",
        description="Search the web for urban planning info, regulations, demographics, real estate",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
            },
            "required": ["query"],
        },
    ),
    ToolDeclaration(
        name="geocode",
        description="Convert an address or place name to geographic coordinates",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Address or place name"},
            },
            "required": ["query"],
        },
    ),

    # ── Navigation ──
    ToolDeclaration(
        name="fly_to",
        description="Animate the map to specific coordinates",
        parameters={
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude"},
                "lng": {"type": "number", "description": "Longitude"},
                "zoom": {"type": "number", "description": "Zoom level 1-20, default 15"},
            },
            "required": ["lat", "lng"],
        },
    ),
    ToolDeclaration(
        name="fit_bounds",
        description="Fit the map view to show a bounding box",
        parameters={
            "type": "object",
            "properties": {
                "south": {"type": "number", "description": "South latitude"},
                "west": {"type": "number", "description": "West longitude"},
                "north": {"type": "number", "description": "North latitude"},
                "east": {"type": "number", "description": "East longitude"},
            },
            "required": ["south", "west", "north", "east"],
        },
    ),

    # ── Markers ──
    ToolDeclaration(
        name="add_marker",
        description="Add a labeled marker pin on the map at given coordinates",
        parameters={
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude"},
                "lng": {"type": "number", "description": "Longitude"},
                "label": {"type": "string", "description": "Label text for the marker popup"},
                "color": {"type": "string", "description": "CSS color (default #e6194b)"},
            },
            "required": ["lat", "lng", "label"],
        },
    ),
    ToolDeclaration(
        name="add_markers",
        description="Add multiple markers at once. Use for showing a set of locations.",
        parameters={
            "type": "object",
            "properties": {
                "markers": {
                    "type": "array",
                    "description": "Array of marker objects",
                    "items": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"},
                            "lng": {"type": "number"},
                            "label": {"type": "string"},
                            "color": {"type": "string"},
                        },
                        "required": ["lat", "lng", "label"],
                    },
                },
            },
            "required": ["markers"],
        },
    ),
    ToolDeclaration(
        name="clear_markers",
        description="Remove all AI-placed markers from the map",
        parameters={"type": "object", "properties": {}},
    ),

    # ── Drawing ──
    ToolDeclaration(
        name="draw_line",
        description="Draw a line/polyline on the map between a series of points",
        parameters={
            "type": "object",
            "properties": {
                "coordinates": {
                    "type": "array",
                    "description": "Array of [longitude, latitude] pairs",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "color": {"type": "string", "description": "Line color (default #ef4444)"},
                "width": {"type": "number", "description": "Line width in pixels (default 3)"},
                "label": {"type": "string", "description": "Optional label for this line"},
            },
            "required": ["coordinates"],
        },
    ),
    ToolDeclaration(
        name="draw_polygon",
        description="Draw a filled polygon on the map. Coordinates should form a closed ring.",
        parameters={
            "type": "object",
            "properties": {
                "coordinates": {
                    "type": "array",
                    "description": "Array of [longitude, latitude] pairs forming the polygon boundary",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "color": {"type": "string", "description": "Fill/stroke color (default #3b82f6)"},
                "opacity": {"type": "number", "description": "Fill opacity 0-1 (default 0.3)"},
                "label": {"type": "string", "description": "Optional label for this polygon"},
            },
            "required": ["coordinates"],
        },
    ),
    ToolDeclaration(
        name="draw_circle",
        description="Draw a circle (buffer zone) on the map centered at a point",
        parameters={
            "type": "object",
            "properties": {
                "center_lat": {"type": "number", "description": "Center latitude"},
                "center_lng": {"type": "number", "description": "Center longitude"},
                "radius_km": {"type": "number", "description": "Radius in kilometers"},
                "color": {"type": "string", "description": "Color (default #8b5cf6)"},
                "label": {"type": "string", "description": "Optional label"},
            },
            "required": ["center_lat", "center_lng", "radius_km"],
        },
    ),
    ToolDeclaration(
        name="add_geojson",
        description="Add a GeoJSON FeatureCollection as a new map layer",
        parameters={
            "type": "object",
            "properties": {
                "geojson": {"type": "object", "description": "A GeoJSON FeatureCollection object"},
                "name": {"type": "string", "description": "Display name for the layer"},
                "color": {"type": "string", "description": "Layer color (default auto)"},
            },
            "required": ["geojson", "name"],
        },
    ),

    # ── Layer management ──
    ToolDeclaration(
        name="highlight_features",
        description="Highlight features in a loaded layer by filtering on a property value",
        parameters={
            "type": "object",
            "properties": {
                "layer_name": {"type": "string", "description": "Name of the layer"},
                "property_name": {"type": "string", "description": "Property to filter by"},
                "property_value": {"type": "string", "description": "Value to match"},
            },
            "required": ["layer_name", "property_name", "property_value"],
        },
    ),
    ToolDeclaration(
        name="set_layer_style",
        description="Change the visual style of a loaded map layer",
        parameters={
            "type": "object",
            "properties": {
                "layer_name": {"type": "string", "description": "Name of the layer"},
                "fill_color": {"type": "string", "description": "New fill color"},
                "line_color": {"type": "string", "description": "New line/outline color"},
                "opacity": {"type": "number", "description": "Fill opacity 0-1"},
            },
            "required": ["layer_name"],
        },
    ),
    ToolDeclaration(
        name="toggle_layer",
        description="Show or hide a map layer",
        parameters={
            "type": "object",
            "properties": {
                "layer_name": {"type": "string", "description": "Name of the layer"},
                "visible": {"type": "boolean", "description": "true to show, false to hide"},
            },
            "required": ["layer_name", "visible"],
        },
    ),
    ToolDeclaration(
        name="remove_layer",
        description="Remove a layer from the map entirely",
        parameters={
            "type": "object",
            "properties": {
                "layer_name": {"type": "string", "description": "Name of the layer to remove"},
            },
            "required": ["layer_name"],
        },
    ),

    # ── Measurement ──
    ToolDeclaration(
        name="measure_distance",
        description="Calculate the distance along a series of points (in km and miles)",
        parameters={
            "type": "object",
            "properties": {
                "points": {
                    "type": "array",
                    "description": "Array of [longitude, latitude] pairs",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
            },
            "required": ["points"],
        },
    ),
    ToolDeclaration(
        name="measure_area",
        description="Calculate the area of a polygon (in m², hectares, km²)",
        parameters={
            "type": "object",
            "properties": {
                "polygon": {
                    "type": "array",
                    "description": "Array of [longitude, latitude] pairs forming the polygon",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
            },
            "required": ["polygon"],
        },
    ),

    # ── Artifacts ──
    ToolDeclaration(
        name="save_bookmark",
        description=(
            "Save the current map region as a named bookmark for quick return. "
            "If south/west/north/east are omitted, the app uses the current visible map bounds from context."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Bookmark label, e.g. Chandigarh CBD"},
                "south": {"type": "number"},
                "west": {"type": "number"},
                "north": {"type": "number"},
                "east": {"type": "number"},
                "zoom": {"type": "number", "description": "Optional zoom level to restore"},
            },
            "required": ["name"],
        },
    ),
    ToolDeclaration(
        name="go_to_bookmark",
        description="Fly the map to a previously saved bookmark by name",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact or partial bookmark name"},
            },
            "required": ["name"],
        },
    ),
    ToolDeclaration(
        name="export_region_clip",
        description=(
            "Clip all loaded layers to a bounding box and save a merged GeoJSON into the workspace. "
            "Requires an open workspace folder. If bbox omitted, uses current map bounds from context."
        ),
        parameters={
            "type": "object",
            "properties": {
                "output_base_name": {"type": "string", "description": "Filename base without .geojson"},
                "south": {"type": "number"},
                "west": {"type": "number"},
                "north": {"type": "number"},
                "east": {"type": "number"},
            },
            "required": ["output_base_name"],
        },
    ),
    ToolDeclaration(
        name="create_artifact",
        description="Save a note, analysis, or report as an artifact in the project",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title of the artifact"},
                "content": {"type": "string", "description": "Content text"},
                "artifact_type": {
                    "type": "string",
                    "description": "Type: note, analysis, report, or sketch",
                },
            },
            "required": ["title", "content", "artifact_type"],
        },
    ),
]
