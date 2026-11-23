
from __future__ import annotations

import argparse
import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import Pyro5.api


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RETROARCH_DIR = PROJECT_ROOT / "runtime" / "retroarch"
RETROARCH_EXE = RETROARCH_DIR / "retroarch.exe"
ROM_ROOT = (PROJECT_ROOT / "roms").resolve()

# O cliente não escolhe caminhos arbitrários para cores.
AVAILABLE_CORES = {
    "fbneo": "fbneo_libretro.dll",
    "beetle_saturn": "mednafen_saturn_libretro.dll",
}


class NGDAAgent:
    """Representa um nó de execução do NGDA."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.started_at = datetime.now(timezone.utc).isoformat()

    @Pyro5.api.expose
    def status(self) -> dict:
        return {
            "name": self.name,
            "status": "online",
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "started_at": self.started_at,
            "service": "NGDAAgent",
        }

    @Pyro5.api.expose
    def ping(self) -> str:
        return f"pong:{self.name}"

    @Pyro5.api.expose
    def launch_game(self, core_id: str, content_path: str) -> dict:
        """Inicia um conteúdo no RetroArch instalado junto ao NGDA."""

        if core_id not in AVAILABLE_CORES:
            return {
                "success": False,
                "error": f"Core não permitido: {core_id}",
            }

        content = Path(content_path).resolve()

        try:
            content.relative_to(ROM_ROOT)
        except ValueError:
            return {
                "success": False,
                "error": "O conteúdo precisa estar dentro da pasta roms.",
            }

        if not content.is_file():
            return {
                "success": False,
                "error": "Arquivo do jogo não encontrado.",
            }

        if not RETROARCH_EXE.is_file():
            return {
                "success": False,
                "error": "runtime/retroarch/retroarch.exe não encontrado.",
            }

        core_path = (
            RETROARCH_DIR / "cores" / AVAILABLE_CORES[core_id]
        ).resolve()

        if not core_path.is_file():
            return {
                "success": False,
                "error": f"Arquivo do core não encontrado: {core_path.name}",
            }

        command = [
            str(RETROARCH_EXE),
            "-L",
            str(core_path),
            str(content),
        ]

        try:
            process = subprocess.Popen(
                command,
                cwd=str(RETROARCH_DIR),
                shell=False,
            )
        except OSError as exc:
            return {
                "success": False,
                "error": f"Não foi possível iniciar o RetroArch: {exc}",
            }

        return {
            "success": True,
            "agent": self.name,
            "pid": process.pid,
            "message": "Processo do RetroArch iniciado.",
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agente distribuído NGDA"
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    service_name = f"ngda.agent.{args.name}"
    daemon = Pyro5.api.Daemon(host=args.host)
    nameserver = None

    try:
        nameserver = Pyro5.api.locate_ns()
        agent = NGDAAgent(args.name)
        uri = daemon.register(agent)
        nameserver.register(service_name, uri, safe=True)

        print(f"Agente: {service_name}")
        print(f"URI: {uri}")
        print("Estado: online")
        print("Pressione Ctrl+C para encerrar.")

        daemon.requestLoop()

    except KeyboardInterrupt:
        print(f"\nEncerrando {service_name}...")

    finally:
        if nameserver is not None:
            try:
                nameserver.remove(service_name)
            except Exception:
                pass
        daemon.close()


if __name__ == "__main__":
    main()
