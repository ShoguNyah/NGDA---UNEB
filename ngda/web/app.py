from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from ngda.catalog.scanner import save_catalog
from ngda.distributed.coordinator import (
    query_agents,
    launch_on_agent,
)


def get_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = get_project_root()
CATALOG_PATH = PROJECT_ROOT / "data" / "catalog.json"
SYSTEMS_PATH = PROJECT_ROOT / "config" / "systems.json"
ROM_ROOT = (PROJECT_ROOT / "roms").resolve()

if getattr(sys, "frozen", False):
    STATIC_DIR = Path(sys._MEIPASS) / "ngda" / "static"
else:
    STATIC_DIR = Path(__file__).resolve().parent / "static"

INDEX_PATH = STATIC_DIR / "index.html"

COVER_SEARCH_DIRS = [
    PROJECT_ROOT / "covers",
    PROJECT_ROOT / "assets" / "covers",
    PROJECT_ROOT / "data" / "covers",
    PROJECT_ROOT / "static" / "covers",
    STATIC_DIR / "covers",
    Path(__file__).resolve().parent / "covers",
    Path(__file__).resolve().parents[2] / "covers",
    Path(__file__).resolve().parents[2] / "static" / "covers",
]

ALLOWED_LAUNCH_MODES = {"zip_direct", "disc_direct"}
ALLOWED_CORES = {"fbneo", "beetle_saturn", "pcsx_rearmed", "mame"}

app = FastAPI(
    title="NGDA API",
    description="API local do Neo Geo Distributed Arcade",
    version="0.2.0",
)

if STATIC_DIR.is_dir():
    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )


def open_folder_in_explorer(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(folder))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def find_existing_covers_dir() -> Path:
    for folder in COVER_SEARCH_DIRS:
        if folder.is_dir() and any(folder.iterdir()):
            return folder
    default_dir = PROJECT_ROOT / "covers"
    default_dir.mkdir(parents=True, exist_ok=True)
    return default_dir


@app.get("/api/cover/{cover_key}")
def get_cover_image(cover_key: str) -> Response:
    target = cover_key.lower().replace(" ", "").replace("_", "").replace("-", "")
    valid_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

    for folder in COVER_SEARCH_DIRS:
        if not folder.is_dir():
            continue
        for file in folder.iterdir():
            if not file.is_file() or file.suffix.lower() not in valid_exts:
                continue
            stem_norm = file.stem.lower().replace(" ", "").replace("_", "").replace("-", "")
            if stem_norm == target or target in stem_norm or stem_norm in target:
                return FileResponse(file)

    raise HTTPException(status_code=404, detail="Capa não encontrada.")


@app.post("/api/open-roms")
def open_roms_folder() -> dict[str, str]:
    open_folder_in_explorer(ROM_ROOT)
    return {"status": "ok", "path": str(ROM_ROOT)}


@app.post("/api/open-covers")
def open_covers_folder() -> dict[str, str]:
    covers_dir = find_existing_covers_dir()
    open_folder_in_explorer(covers_dir)
    return {"status": "ok", "path": str(covers_dir)}


def load_catalog(rescan: bool = True) -> dict[str, Any]:
    if rescan or not CATALOG_PATH.is_file():
        try:
            return save_catalog(ROM_ROOT, SYSTEMS_PATH, CATALOG_PATH)
        except Exception:
            if CATALOG_PATH.is_file():
                try:
                    with CATALOG_PATH.open("r", encoding="utf-8-sig") as file:
                        cached = json.load(file)
                    if isinstance(cached, dict) and isinstance(cached.get("games"), list):
                        return cached
                except Exception:
                    pass
            return {
                "schema_version": 2,
                "generated_at": "",
                "total_games": 0,
                "candidate_games": 0,
                "games": [],
            }

    try:
        with CATALOG_PATH.open("r", encoding="utf-8-sig") as file:
            catalog = json.load(file)
    except Exception:
        return {
            "schema_version": 2,
            "generated_at": "",
            "total_games": 0,
            "candidate_games": 0,
            "games": [],
        }

    if not isinstance(catalog, dict) or not isinstance(catalog.get("games"), list):
        return {
            "schema_version": 2,
            "generated_at": "",
            "total_games": 0,
            "candidate_games": 0,
            "games": [],
        }

    return catalog


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "application": "NGDA"}


@app.get("/api/nodes")
def list_nodes() -> dict[str, Any]:
    try:
        agents = query_agents()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível consultar os agentes. Verifique se o Name Server Pyro5 está ativo.",
        ) from exc

    return {
        "total_nodes": len(agents),
        "online_nodes": sum(1 for agent in agents if agent.get("reachable") is True),
        "nodes": agents,
    }


@app.get("/api/games")
def list_games(
    system_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
) -> dict[str, Any]:
    catalog = load_catalog(rescan=True)
    games = catalog["games"]

    if system_id:
        games = [
            game for game in games
            if game.get("system_id", "").casefold() == system_id.casefold()
        ]

    if status:
        games = [
            game for game in games
            if game.get("status", "").casefold() == status.casefold()
        ]

    if q:
        term = q.casefold()
        games = [
            game for game in games
            if term in str(game.get("title", "")).casefold()
            or term in str(game.get("system_name", "")).casefold()
        ]

    return {
        "schema_version": catalog.get("schema_version"),
        "generated_at": catalog.get("generated_at"),
        "total_games": len(games),
        "candidate_games": sum(1 for game in games if game.get("status") == "candidate"),
        "games": games,
    }


@app.post("/api/games/{game_id:path}/launch")
def launch_game(game_id: str) -> dict[str, Any]:
    catalog = load_catalog(rescan=False)

    game = next(
        (item for item in catalog["games"] if item.get("id") == game_id),
        None,
    )

    if game is None:
        raise HTTPException(status_code=404, detail="Jogo não encontrado no catálogo.")

    if game.get("status") != "candidate":
        raise HTTPException(
            status_code=409,
            detail=game.get("error") or "Este jogo ainda não está pronto para execução.",
        )

    if game.get("emulator") != "retroarch":
        raise HTTPException(status_code=400, detail="O jogo não está configurado para o RetroArch.")

    if game.get("launch_mode") not in ALLOWED_LAUNCH_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Modo de execução '{game.get('launch_mode')}' não suportado.",
        )

    if game.get("core") not in ALLOWED_CORES:
        raise HTTPException(
            status_code=400,
            detail=f"Core '{game.get('core')}' não habilitado neste agente.",
        )

    archive = game.get("archive")
    if not isinstance(archive, str) or not archive:
        raise HTTPException(status_code=400, detail="Arquivo do jogo inválido no catálogo.")

    content_path = (ROM_ROOT / archive).resolve()

    try:
        content_path.relative_to(ROM_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="Caminho do jogo inválido.")

    if not content_path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo do jogo não encontrado na pasta roms.")

    try:
        result = launch_on_agent(game["core"], str(content_path))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Falha na comunicação com o Pyro5: {exc}") from exc

    if not result.get("success"):
        raise HTTPException(
            status_code=503,
            detail=result.get("error", "Não foi possível iniciar o jogo."),
        )

    return {
        "game_id": game_id,
        "title": game["title"],
        **result,
    }


@app.get("/")
def home() -> FileResponse:
    if not INDEX_PATH.is_file():
        raise HTTPException(status_code=404, detail="Interface ainda não criada.")
    return FileResponse(INDEX_PATH)
