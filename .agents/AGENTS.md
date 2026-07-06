# Workspace Rules: Cursor for Urban Planners

This file documents rules and guidelines for pair programming on this repository.

## GIS Desktop App Patterns

### 1. Windows Quarantine & Distribution
* **Avoid Installer Deletions:** Unsigned `.exe` installers built with PyInstaller/Electron frequently get quarantined by Windows Defender. Always bundle a `.zip` target in `electron-builder.yml` alongside the installer.
* **Extraction Guide:** Double-clicking the executable inside the `.zip` without extraction runs it in a temp directory, breaking relative backend bindings. Instruct users to select "Extract All..." before running.

### 2. Multi-Runner GitHub Actions Releases
* **Avoid Cleanup Race Conditions:** When building on parallel runners (Mac and Windows), the step to delete prior assets must run sequentially or be restricted to the first runner. Subsequent runners must only upload to the created release to avoid deleting each other's uploaded artifacts.

### 3. Spatial Data Layer Transfers
* **Local Workspace Loading:** Do not send raw GeoJSON collections larger than a few kilobytes directly over the WebSocket. Instead, write the file to the workspace directory on the backend and send an `add_geojson_file` MapAction with the absolute path, allowing the frontend to load it locally using Electron's file API.
* **Size-Gated Context Properties:** For LLM context window efficiency, map layers must truncate properties list to keys-only. However, for layers with <= 100 features, populate a `features_data` field with complete key-value structures to allow tools like attribute table extraction to run locally.
