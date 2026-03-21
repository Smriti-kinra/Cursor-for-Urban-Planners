# Cursor for Urban Planners

A desktop application for urban planners featuring an interactive map, file workspace, AI chat assistant, and artifact management.

## Prerequisites

- Node.js >= 18
- pnpm >= 8
- Python >= 3.11

## Setup

### 1. Install frontend dependencies

```bash
pnpm install
```

### 2. Create a Python virtual environment and install backend dependencies

```bash
cd packages/backend
python -m venv .buildenv
source .buildenv/bin/activate   # Windows: .buildenv\Scripts\activate
pip install -r requirements.txt
```

## Development

Start both the backend and the Electron app in parallel:

```bash
pnpm dev
```

Or start them separately:

```bash
# Terminal 1 — backend
cd packages/backend
source .buildenv/bin/activate
python -m uvicorn main:app --reload --port 8765

# Terminal 2 — desktop
cd apps/desktop
npx electron-vite dev
```

## Build for distribution

### 1. Build the Python backend binary (PyInstaller)

```bash
cd packages/backend
source .buildenv/bin/activate
pip install pyinstaller
pyinstaller backend.spec --noconfirm
```

### 2. Package the Electron app

```bash
cd apps/desktop
npx electron-vite build
npx electron-builder
```

Output is written to `apps/desktop/release/`.

## Project Structure

```
.
├── apps/desktop/              Electron + React frontend
│   ├── src/main/              Electron main process
│   ├── src/preload/           Preload (IPC bridge)
│   └── src/renderer/          React UI (map, panels)
├── packages/backend/          Python FastAPI backend
│   ├── main.py                App entry & routes
│   ├── routers/               API routers (files, chat, artifacts)
│   └── database.py            SQLite setup
├── package.json               Workspace root scripts
└── pnpm-workspace.yaml        Monorepo config
```
