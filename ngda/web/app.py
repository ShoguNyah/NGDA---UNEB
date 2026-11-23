
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ngda.distributed.coordinator import (
    query_agents,
    launch_on_agent,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PROJECT_ROOT / "data" / "catalog.json"
ROM_ROOT = (PROJECT_ROOT / "roms").resolve()

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_PATH = STATIC_DIR / "index.html"

app = FastAPI(
    title="NGDA API",
    description="API local do Neo Geo Distributed Arcade",
    version="0.2.0",
)

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)


def load_catalog() -> dict[str, Any]:
    """Carrega o catálogo de jogos gerado pelo scanner."""

    if not CATALOG_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail="Catálogo não encontrado. Execute o scanner do NGDA.",
        )

    try:
        with CATALOG_PATH.open("r", encoding="utf-8-sig") as file:
            catalog = json.load(file)

    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Não foi possível ler data/catalog.json.",
        ) from exc

    if not isinstance(catalog, dict) or not isinstance(
        catalog.get("games"), list
    ):
        raise HTTPException(
            status_code=500,
            detail="O formato do catálogo é inválido.",
        )

    return catalog


@app.get("/api/health")
def health() -> dict[str, str]:
    """Verifica se a API está respondendo."""

    return {
        "status": "ok",
        "application": "NGDA",
    }


@app.get("/api/nodes")
def list_nodes() -> dict[str, Any]:
    """Retorna o estado dos agentes distribuídos do NGDA."""

    try:
        agents = query_agents()

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Não foi possível consultar os agentes. "
                "Verifique se o Name Server Pyro5 está ativo."
            ),
        ) from exc

    return {
        "total_nodes": len(agents),
        "online_nodes": sum(
            1 for agent in agents
            if agent.get("reachable") is True
        ),
        "nodes": agents,
    }


@app.get("/api/games")
def list_games(
    system_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
) -> dict[str, Any]:
    """Lista os jogos do catálogo, com filtros opcionais."""

    catalog = load_catalog()
    games = catalog["games"]

    if system_id:
        games = [
            game for game in games
            if game.get("system_id", "").casefold()
            == system_id.casefold()
        ]

    if status:
        games = [
            game for game in games
            if game.get("status", "").casefold()
            == status.casefold()
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
        "candidate_games": sum(
            1 for game in games
            if game.get("status") == "candidate"
        ),
        "games": games,
    }


@app.post("/api/games/{game_id}/launch")
def launch_game(game_id: str) -> dict[str, Any]:
    """Solicita ao agente Pyro5 a execução de um jogo."""

    catalog = load_catalog()

    game = next(
        (
            item for item in catalog["games"]
            if item.get("id") == game_id
        ),
        None,
    )

    if game is None:
        raise HTTPException(
            status_code=404,
            detail="Jogo não encontrado no catálogo.",
        )

    if game.get("status") != "candidate":
        raise HTTPException(
            status_code=409,
            detail="Este jogo ainda não está pronto para execução.",
        )

    if game.get("emulator") != "retroarch":
        raise HTTPException(
            status_code=400,
            detail="O jogo não está configurado para o RetroArch.",
        )

    if game.get("launch_mode") != "zip_direct":
        raise HTTPException(
            status_code=400,
            detail="Modo de execução ainda não implementado.",
        )

    if game.get("core") != "fbneo":
        raise HTTPException(
            status_code=400,
            detail="Nesta etapa, somente o core FBNeo está habilitado.",
        )

    archive = game.get("archive")

    if not isinstance(archive, str) or not archive:
        raise HTTPException(
            status_code=400,
            detail="O catálogo não possui um arquivo válido para este jogo.",
        )

    content_path = (ROM_ROOT / archive).resolve()

    try:
        content_path.relative_to(ROM_ROOT)

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Caminho do jogo inválido.",
        )

    if not content_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Arquivo do jogo não encontrado na pasta roms.",
        )

    try:
        result = launch_on_agent(
            game["core"],
            str(content_path),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Falha na comunicação com o Pyro5: {exc}",
        ) from exc

    if not result.get("success"):
        raise HTTPException(
            status_code=503,
            detail=result.get(
                "error",
                "Não foi possível iniciar o jogo.",
            ),
        )

    return {
        "game_id": game_id,
        "title": game["title"],
        **result,
    }


@app.get("/")
def home() -> FileResponse:
    """Entrega a página inicial do NGDA."""

    if not INDEX_PATH.is_file():
        raise HTTPException(
            status_code=404,
            detail="Interface ainda não criada.",
        )

    return FileResponse(INDEX_PATH)
