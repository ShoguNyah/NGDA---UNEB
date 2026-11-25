
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

IGNORED_ARCHIVES = {
    "neogeo.zip",
    "aes.zip",
    "neocdz.zip",
    "kof2002.zip",
    "sega saturn bios.zip",
}

KNOWN_TITLES: dict[str, str] = {
    "galaxyfg": "Galaxy Fight: Universal Warriors",
    "kof2003": "The King of Fighters 2003",
    "wakuwak7": "Waku Waku 7",
    "wakuwaku7": "Waku Waku 7",
    "waku waku 7": "Waku Waku 7",
    "astrasuperstars": "Astra Superstars",
    "astra superstars": "Astra Superstars",
    "astrass": "Astra Superstars",
}

CARTRIDGE_CHIP_PATTERN = re.compile(
    r"([_-]|\b)([pcmvs]\d+[a-z]?)\.(bin|rom|[pcmvs]\d+)$",
    re.IGNORECASE,
)

NEOGEO_CHIP_PATTERN = re.compile(
    r"([_-]|\b)([pcmvs]\d+[a-z]?)\.(bin|rom|[pcmvs]\d+)$",
    re.IGNORECASE,
)


def find_extractor() -> str | None:
    candidates = [
        shutil.which("7z"),
        shutil.which("unrar"),
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        r"C:\Program Files\WinRAR\UnRAR.exe",
        r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def auto_extract_rar_archives(root: Path) -> None:
    extractor = find_extractor()
    if not extractor:
        return

    for rar_path in list(root.rglob("*.rar")):
        stem_lower = rar_path.stem.lower()
        if "kof2002" in stem_lower or "waku" in stem_lower:
            continue

        is_neogeo = any(
            k in stem_lower for k in ("kof", "galaxy", "mslug", "garou", "samsho")
        )

        if is_neogeo:
            target_zip = rar_path.parent / f"{rar_path.stem}.zip"
            if target_zip.is_file():
                continue

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                cmd = (
                    [extractor, "x", "-y", str(rar_path), f"-o{tmp_path}"]
                    if "7z" in extractor.lower()
                    else [extractor, "x", "-y", str(rar_path), f"{tmp_path}\\"]
                )
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                extracted_files = [f for f in tmp_path.rglob("*") if f.is_file()]
                if extracted_files:
                    with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                        for f in extracted_files:
                            zf.write(f, arcname=f.name)
        else:
            extract_dir = root / "saturn" / rar_path.stem
            if extract_dir.is_dir() and any(extract_dir.glob("*.cue")):
                continue
            extract_dir.mkdir(parents=True, exist_ok=True)
            cmd = (
                [extractor, "x", "-y", str(rar_path), f"-o{extract_dir}"]
                if "7z" in extractor.lower()
                else [extractor, "x", "-y", str(rar_path), f"{extract_dir}\\"]
            )
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def is_bios_file(path: Path) -> bool:
    name = path.name.lower()
    if "kof" in name and "kof2002" not in name:
        return False
    if name in IGNORED_ARCHIVES or "bios" in name:
        return True

    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path, "r") as archive:
                inner_names = [
                    Path(item.filename).name.lower()
                    for item in archive.infolist()
                    if not item.is_dir()
                ]
        except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, zlib.error):
            return False

        if not inner_names:
            return False

        has_bios_rom = any(
            n.startswith(("sp-", "uni-bios", "000-lo", "sfix", "sm1", "asia-s3", "vs-bios"))
            for n in inner_names
        )
        has_cartridge_chips = any(CARTRIDGE_CHIP_PATTERN.search(n) for n in inner_names)
        if has_bios_rom and not has_cartridge_chips:
            return True

    return False


def looks_like_neogeo_zip(path: Path) -> bool:
    if path.suffix.lower() != ".zip" or is_bios_file(path):
        return False

    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = [
                Path(item.filename).name
                for item in archive.infolist()
                if not item.is_dir()
            ]
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, zlib.error):
        return False

    if not names:
        return False

    chip_matches = sum(1 for name in names if NEOGEO_CHIP_PATTERN.search(name))
    return chip_matches >= 3


def classify_file(path: Path, root: Path, systems: dict):
    filename = path.stem.lower()

    if "kof" in filename and "arcade" in systems:
        return "arcade", systems["arcade"]

    relative = path.relative_to(root)
    parts = relative.parts


    if len(parts) > 1 and parts[0].lower() in systems:
        system_id = parts[0].lower()
        return system_id, systems[system_id]
    


    for system_id, system in systems.items():
        hints = system.get("filename_hints", [])
        if any(hint.lower() in filename for hint in hints):
            return system_id, system

    if "neogeo" in systems and looks_like_neogeo_zip(path):
        return "neogeo", systems["neogeo"]

    if path.suffix.lower() in {".cue", ".chd", ".iso"} and "saturn" in systems:
        return "saturn", systems["saturn"]

    return "unknown", {
        "name": "Sistema não identificado",
        "emulator": None,
        "core": None,
        "launch_mode": None,
    }


def resolve_metadata(stem: str) -> tuple[str, str]:
    key = stem.lower().strip()
    if "kof" in key and key not in KNOWN_TITLES:
        title = f"The King of Fighters ({stem})"
    else:
        title = KNOWN_TITLES.get(key, stem)

    if "waku" in key:
        cover_key = "wakuwaku7"
    elif "astra" in key:
        cover_key = "astrasuperstars"
    elif "kof" in key:
        cover_key = "kof2003"
    else:
        cover_key = key.replace(" ", "")
    return title, f"/api/cover/{cover_key}"


def inspect_archive(path: Path, system_id: str, system: dict, root: Path) -> dict:
    title, cover_url = resolve_metadata(path.stem)
    ext = path.suffix.lower()

    entry = {
        "id": f"{system_id}:{path.relative_to(root).as_posix()}",
        "title": title,
        "rom_stem": path.stem,
        "cover": cover_url,
        "system_id": system_id,
        "system_name": system["name"],
        "archive": path.relative_to(root).as_posix(),
        "format": ext.lstrip("."),
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

    if ext in {".cue", ".chd", ".iso"}:
        entry["launch_mode"] = "disc_direct"
        entry["status"] = "candidate"
        return entry

    if ext == ".rar":
        entry["status"] = "needs_extraction"
        entry["error"] = "Extraia o arquivo .rar para .zip ou .cue/.bin."
        return entry

    try:
        with zipfile.ZipFile(path, "r") as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]

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
            

            entry["status"] = "candidate"

    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, zlib.error) as exc:
        entry["status"] = "invalid_archive"
        entry["error"] = str(exc)

    return entry


def scan_catalog(roms_dir: Path, systems_file: Path) -> dict:
    root = roms_dir.resolve()

    if not root.is_dir():
        raise FileNotFoundError(f"Pasta de ROMs não encontrada: {root}")

    auto_extract_rar_archives(root)

    config = json.loads(systems_file.read_text(encoding="utf-8-sig"))
    systems = config["systems"]
    games = []

    all_files = sorted(root.rglob("*"))
    extracted_stems = {
        p.stem.lower().replace(" ", "")
        for p in all_files
        if p.is_file() and p.suffix.lower() in {".zip", ".cue", ".chd"}
    }

    seen_keys: set[str] = set()

    for path in all_files:
        if not path.is_file() or path.stem.lower() in {"stvbios", "segabill"}:
            continue
            continue

        if path.suffix.lower() == ".bin":
            continue

        if is_bios_file(path):
            continue

        stem_lower = path.stem.lower().strip()
        if "kof2002" in stem_lower:
            continue

        norm_stem = re.sub(r"[^a-z0-9]", "", stem_lower)
        if path.suffix.lower() == ".rar" and norm_stem in extracted_stems:
            continue

        if "waku" in norm_stem:
            dedup_key = f"{path.suffix.lower()}:wakuwaku7"
        elif "astra" in norm_stem:
            dedup_key = f"{path.suffix.lower()}:astrasuperstars"
        elif "kof" in norm_stem:
            dedup_key = f"{path.suffix.lower()}:kof2003"
        else:
            dedup_key = f"{path.suffix.lower()}:{norm_stem}"

        if dedup_key in seen_keys:
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

        seen_keys.add(dedup_key)
        games.append(inspect_archive(path, system_id, system, root))

    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roms_directory": str(root),
        "total_games": len(games),
        "candidate_games": sum(game["status"] == "candidate" for game in games),
        "games": games,
    }


def save_catalog(
    roms_dir: Path,
    systems_file: Path,
    output_file: Path,
) -> dict:
    catalog = scan_catalog(roms_dir, systems_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="NGDA - catálogo multissistema")
    parser.add_argument("--roms", default="roms")
    parser.add_argument("--systems", default="config/systems.json")
    parser.add_argument("--output", default="data/catalog.json")
    args = parser.parse_args()

    catalog = save_catalog(Path(args.roms), Path(args.systems), Path(args.output))
    print(f"Total: {catalog['total_games']} | Prontos: {catalog['candidate_games']}")


if __name__ == "__main__":
    main()
    
