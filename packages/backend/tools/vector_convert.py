"""
Vector ingestion — convert shapefile / GeoPackage / KML / KMZ / GPX / CSV into a
WGS84 (EPSG:4326) GeoJSON FeatureCollection.

Built on DuckDB's `spatial` extension (already a dependency) rather than
geopandas/GDAL, so there is no heavy GDAL binary to bundle in the PyInstaller
build. The extension ships its own GDAL-backed `ST_Read` for vector formats.

Coordinate convention matches the rest of the codebase: output is EPSG:4326
lng/lat. `ST_Transform(..., always_xy := true)` forces x/y (lng/lat) order so
authority-axis-order CRSs (e.g. 4326 = lat/lon) still emit GeoJSON-correct
[lng, lat] coordinates.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

# Formats ST_Read handles directly. CSV is special-cased (lat/lng columns).
VECTOR_EXTS = {".shp", ".gpkg", ".kml", ".kmz", ".gpx", ".geojson", ".json"}
CSV_EXTS = {".csv"}
SUPPORTED_EXTS = VECTOR_EXTS | CSV_EXTS

# Common spellings for coordinate columns in a CSV, longitude first.
_LNG_COLS = ["lng", "lon", "long", "longitude", "x", "lon_dd", "x_coord"]
_LAT_COLS = ["lat", "latitude", "y", "lat_dd", "y_coord"]


class ConversionError(RuntimeError):
    """Raised with a human-readable message when a file can't be converted."""


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    try:
        # LOAD alone works when the extension is already cached/bundled; INSTALL
        # only reaches the network on first use.
        con.execute("LOAD spatial;")
    except duckdb.Error:
        try:
            con.execute("INSTALL spatial; LOAD spatial;")
        except duckdb.Error as e:
            raise ConversionError(
                "The DuckDB 'spatial' extension is unavailable and could not be "
                "downloaded. Vector import needs it; check the network or bundle "
                f"the extension with the app. ({e})"
            ) from e
    return con


def _sql_str(value: str) -> str:
    """Single-quote a value for inline SQL (paths/identifiers from the OS)."""
    return "'" + str(value).replace("'", "''") + "'"


def _detect_source_crs(con: duckdb.DuckDBPyConnection, path: str) -> str | None:
    """Return an 'EPSG:xxxx' string for the file's CRS, or None if unknown.

    None means we skip reprojection and assume the coordinates are already
    lng/lat — the right call for KML/GPX (always WGS84) and for files whose
    CRS metadata is missing.
    """
    try:
        row = con.execute(
            f"SELECT layers FROM ST_Read_Meta({_sql_str(path)})"
        ).fetchone()
    except duckdb.Error:
        return None
    if not row or not row[0]:
        return None
    layers = row[0]
    try:
        geom_fields = layers[0].get("geometry_fields") or []
        crs = (geom_fields[0] or {}).get("crs") if geom_fields else None
        if not crs:
            return None
        auth = crs.get("auth_name")
        code = crs.get("auth_code")
        if auth and code:
            return f"{auth}:{code}"
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    return None


def _features_from_rows(rows: list, columns: list[str], geom_idx: int) -> list[dict]:
    """Assemble GeoJSON features from query rows. `geom_idx` is the column that
    holds the ST_AsGeoJSON string; all other columns become properties."""
    features = []
    for r in rows:
        gj = r[geom_idx]
        if not gj:
            continue
        try:
            geometry = json.loads(gj)
        except (json.JSONDecodeError, TypeError):
            continue
        props = {
            columns[i]: r[i]
            for i in range(len(columns))
            # OGC_FID is a synthetic row id ST_Read adds; not real attribute data.
            if i != geom_idx and columns[i] != "OGC_FID"
        }
        features.append({"type": "Feature", "geometry": geometry, "properties": props})
    return features


def convert_vector_file(path: str) -> dict:
    """Read a vector file via ST_Read, reproject to 4326, return a
    FeatureCollection dict. Raises ConversionError on failure."""
    con = _connect()
    src_crs = _detect_source_crs(con, path)

    # Build the geometry SELECT: reproject only when the source CRS is known and
    # not already 4326. ST_Read exposes the geometry column as `geom`.
    if src_crs and src_crs.upper() != "EPSG:4326":
        geom_select = (
            f"ST_AsGeoJSON(ST_Transform(geom, {_sql_str(src_crs)}, 'EPSG:4326', "
            f"always_xy := true))"
        )
    else:
        geom_select = "ST_AsGeoJSON(geom)"

    try:
        rel = con.execute(
            f"SELECT * EXCLUDE geom, {geom_select} AS __geojson__ "
            f"FROM ST_Read({_sql_str(path)})"
        )
        columns = [d[0] for d in rel.description]
        rows = rel.fetchall()
    except duckdb.Error as e:
        raise ConversionError(f"Could not read vector file: {e}") from e

    geom_idx = columns.index("__geojson__")
    features = _features_from_rows(rows, columns, geom_idx)
    if not features:
        raise ConversionError("File contained no readable features.")

    return {
        "type": "FeatureCollection",
        "features": features,
        "_source_crs": src_crs or "assumed EPSG:4326",
    }


def detect_csv_lat_lng(path: str) -> tuple[str | None, str | None]:
    """Guess the latitude/longitude column names in a CSV (case-insensitive)."""
    con = _connect()
    try:
        rel = con.execute(
            f"SELECT * FROM read_csv_auto({_sql_str(path)}) LIMIT 0"
        )
        cols = [d[0] for d in rel.description]
    except duckdb.Error as e:
        raise ConversionError(f"Could not read CSV header: {e}") from e

    lower = {c.lower(): c for c in cols}
    lng = next((lower[c] for c in _LNG_COLS if c in lower), None)
    lat = next((lower[c] for c in _LAT_COLS if c in lower), None)
    return lat, lng


def convert_csv_file(
    path: str, lat_col: str | None = None, lng_col: str | None = None
) -> dict:
    """Convert a CSV with point coordinates into a FeatureCollection of points.
    Auto-detects lat/lng columns when not given. Assumes WGS84 lng/lat."""
    if not lat_col or not lng_col:
        det_lat, det_lng = detect_csv_lat_lng(path)
        lat_col = lat_col or det_lat
        lng_col = lng_col or det_lng
    if not lat_col or not lng_col:
        raise ConversionError(
            "Could not find latitude/longitude columns in the CSV. "
            "Expected headers like lat/latitude and lng/lon/longitude."
        )

    con = _connect()
    try:
        rel = con.execute(
            f"SELECT *, "
            f"ST_AsGeoJSON(ST_Point(CAST({_sql_ident(lng_col)} AS DOUBLE), "
            f"CAST({_sql_ident(lat_col)} AS DOUBLE))) AS __geojson__ "
            f"FROM read_csv_auto({_sql_str(path)}) "
            f"WHERE {_sql_ident(lng_col)} IS NOT NULL AND {_sql_ident(lat_col)} IS NOT NULL"
        )
        columns = [d[0] for d in rel.description]
        rows = rel.fetchall()
    except duckdb.Error as e:
        raise ConversionError(f"Could not build points from CSV: {e}") from e

    geom_idx = columns.index("__geojson__")
    features = _features_from_rows(rows, columns, geom_idx)
    if not features:
        raise ConversionError("No rows with valid coordinates were found.")

    return {"type": "FeatureCollection", "features": features, "_source_crs": "EPSG:4326"}


def _sql_ident(name: str) -> str:
    """Double-quote a column identifier for SQL."""
    return '"' + str(name).replace('"', '""') + '"'


def convert_file(
    path: str, lat_col: str | None = None, lng_col: str | None = None
) -> dict:
    """Dispatch on extension. Returns a FeatureCollection dict (with a
    `_source_crs` hint) or raises ConversionError."""
    ext = Path(path).suffix.lower()
    if ext in CSV_EXTS:
        return convert_csv_file(path, lat_col, lng_col)
    if ext in VECTOR_EXTS:
        return convert_vector_file(path)
    raise ConversionError(f"Unsupported file type: {ext or '(none)'}")


def extract_table(path: str) -> dict:
    """Read a vector file via ST_Read, exclude geometry, return columns and rows.
    
    Raises ConversionError on failure.
    """
    con = _connect()
    try:
        desc_rel = con.execute(f"SELECT * FROM ST_Read({_sql_str(path)}) LIMIT 0")
        all_cols = [d[0] for d in desc_rel.description]
    except duckdb.Error as e:
        raise ConversionError(f"Could not read vector metadata: {e}") from e

    geom_cols = {"geom", "geometry", "wkb_geometry"}
    cols_to_select = [c for c in all_cols if c.lower() not in geom_cols]
    
    if not cols_to_select:
        raise ConversionError("File contains only geometry columns or no readable columns.")

    select_list = ", ".join([_sql_ident(c) for c in cols_to_select])
    try:
        rel = con.execute(f"SELECT {select_list} FROM ST_Read({_sql_str(path)})")
        columns = [d[0] for d in rel.description]
        rows = rel.fetchall()
    except duckdb.Error as e:
        raise ConversionError(f"Could not read vector attributes: {e}") from e

    # convert any non-serializable objects (like datetime) to string
    serializable_rows = []
    for r in rows:
        row_data = []
        for val in r:
            if val is not None and not isinstance(val, (int, float, str, bool)):
                row_data.append(str(val))
            else:
                row_data.append(val)
        serializable_rows.append(row_data)

    return {"columns": columns, "rows": serializable_rows}
