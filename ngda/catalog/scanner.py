
from __future__ import annotations

import argparse
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def classify_file(path: Path, root: Path, systems: dict):
    """Classifica por subpasta ou por nome do arquivo."""

    relative = path.relative_to(root)
    parts = relative.parts

    # Se estiver em roms/neogeo/, roms/saturn/ etc.
    if len(parts) > 1 and parts[0].lower() in systems:
        system_id = parts[0].lower()
        return system_id, systems[system_id]

    # Se estiver diretamente em roms/, usa as pistas de nome.
    filename = path.stem.lower()

    for system_id, system in systems.items():
        hints = system.get("filename_hints", [])
        if any(hint.lower() in filename for hint in hints):
            return system_id, system

    return "unknown", {
        "name": "Sistema não identificado",
        "emulator": None,
        "core": None,
        "launch_mode": None,
    }


def inspect_archive(path: Path, system_id: str,
                    system: dict, root: Path) -> dict:
    entry = {
        "id": f"{system_id}:{path.relative_to(root).as_posix()}",
        "title": path.stem,
        "system_id": system_id,
        "system_name": system["name"],
        "archive": path.relative_to(root).as_posix(),
        "format": path.suffix.lower().lstrip("."),
        "size_bytes": path.stat().st_size,
        "emulator": system.get("emulator"),
        "core": system.get("core"),
        "launch_mode": system.get("launch_mode"),
        "status": "pending_inspection",
        "contents": [],
        "error": None,
    }

    if system_id == "unknown":
        entry["status"] = "unknown_system"
        entry["error"] = "Configure o sistema antes de executar o jogo."
        return entry

    if path.suffix.lower() == ".rar":
        entry["status"] = "needs_rar_inspection"
        entry["error"] = (
            "Arquivo RAR catalogado, mas seu conteúdo ainda "
            "precisa ser inspecionado."
        )
        return entry

    try:
        with zipfile.ZipFile(path, "r") as archive:
            files = [
                item for item in archive.infolist()
                if not item.is_dir()
            ]

            if not files:
                entry["status"] = "empty"
                return entry

            entry["contents"] = [
                {
                    "name": item.filename,
                    "size_bytes": item.file_size,
                    "encrypted": bool(item.flag_bits & 1),
                }
                for item in files
            ]

            if any(item.flag_bits & 1 for item in files):
                entry["status"] = "encrypted"
                entry["error"] = "O ZIP contém arquivos criptografados."
                return entry

            bad_file = archive.testzip()
            if bad_file is not None:
                entry["status"] = "corrupt"
                entry["error"] = f"Falha de CRC: {bad_file}"
                return entry

            entry["status"] = "candidate"

    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
        entry["status"] = "invalid_archive"
        entry["error"] = str(exc)

    return entry


def scan_catalog(roms_dir: Path, systems_file: Path) -> dict:
    root = roms_dir.resolve()

    if not root.is_dir():
        raise FileNotFoundError(f"Pasta de ROMs não encontrada: {root}")

    config = json.loads(systems_file.read_text(encoding="utf-8"))
    systems = config["systems"]
    games = []

    # Percorre a raiz de roms e todas as subpastas.
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        system_id, system = classify_file(path, root, systems)

        if system_id == "unknown":
            allowed = {
                ext.lower()
                for item in systems.values()
                for ext in item.get("accepted_extensions", [])
            }
        else:
            allowed = {
                ext.lower()
                for ext in system.get("accepted_extensions", [])
            }

        if path.suffix.lower() not in allowed:
            continue

        games.append(
            inspect_archive(path, system_id, system, root)
        )

    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roms_directory": str(root),
        "total_games": len(games),
        "candidate_games": sum(
            game["status"] == "candidate" for game in games
        ),
        "games": games,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NGDA - catálogo multissistema"
    )
    parser.add_argument("--roms", default="roms")
    parser.add_argument("--systems", default="config/systems.json")
    parser.add_argument("--output", default="data/catalog.json")
    args = parser.parse_args()

    try:
        catalog = scan_catalog(
            Path(args.roms),
            Path(args.systems),
        )
    except (OSError, KeyError, ValueError) as exc:
        parser.error(str(exc))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=== NGDA | Catálogo multissistema ===")
    print(f"Arquivos catalogados: {catalog['total_games']}")
    print(f"Candidatos: {catalog['candidate_games']}")
    print(f"Catálogo: {output.resolve()}")

    for game in catalog["games"]:
        print(
            f"[{game['status']}] {game['system_id']} | "
            f"{game['title']} | {game['format']} | "
            f"Core: {game['core'] or 'não definido'}"
        )


if __name__ == "__main__":
    main()
