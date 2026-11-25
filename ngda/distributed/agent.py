
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import Pyro5.api


def get_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = get_project_root()
RETROARCH_DIR = PROJECT_ROOT / "runtime" / "retroarch"
RETROARCH_EXE = RETROARCH_DIR / "retroarch.exe"
RETROARCH_CFG = RETROARCH_DIR / "retroarch.cfg"
ROM_ROOT = (PROJECT_ROOT / "roms").resolve()


AVAILABLE_CORES = {
    "fbneo": "fbneo_libretro.dll",
    "beetle_saturn": "mednafen_saturn_libretro.dll",
    "mame": "mame_libretro.dll",
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


        if core_id not in AVAILABLE_CORES:
            return {"success": False, "error": f"Core não permitido: {core_id}"}

        content = Path(content_path).resolve()

        try:
            content.relative_to(ROM_ROOT)
        except ValueError:
            return {"success": False, "error": "O conteúdo precisa estar dentro da pasta roms."}

        if not content.is_file():
            return {"success": False, "error": f"Arquivo do jogo não encontrado: {content.name}"}

        if not RETROARCH_EXE.is_file():
            return {"success": False, "error": "runtime/retroarch/retroarch.exe não encontrado."}

        core_path = (RETROARCH_DIR / "cores" / AVAILABLE_CORES[core_id]).resolve()

        if not core_path.is_file():
            return {"success": False, "error": f"Arquivo do core não encontrado: {core_path.name}"}

        command = [str(RETROARCH_EXE), "-L", str(core_path), str(content)]

        if RETROARCH_CFG.is_file():
            command.extend(["--config", str(RETROARCH_CFG)])

        try:
            process = subprocess.Popen(command, cwd=str(RETROARCH_DIR), shell=False)
        except OSError as exc:
            return {"success": False, "error": f"Não foi possível iniciar o RetroArch: {exc}"}

        return {
            "success": True,
            "agent": self.name,
            "pid": process.pid,
            "message": "Processo do RetroArch iniciado.",
        }


def run_agent_loop(name: str, host: str = "127.0.0.1", stop_event=None) -> None:
    service_name = f"ngda.agent.{name}"
    daemon = Pyro5.api.Daemon(host=host)
    nameserver = None

    try:
        nameserver = Pyro5.api.locate_ns()
        agent = NGDAAgent(name)
        uri = daemon.register(agent)
        nameserver.register(service_name, uri, safe=True)

        print(f"[NGDA Agent] {service_name} online em {uri}")

        if stop_event is not None:
            daemon.requestLoop(loopCondition=lambda: not stop_event.is_set())
        else:
            daemon.requestLoop()
    finally:
        if nameserver is not None:
            try:
                nameserver.remove(service_name)
            except Exception:
                pass
        daemon.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente distribuído NGDA")
    parser.add_argument("--name", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    try:
        run_agent_loop(args.name, args.host)
    except KeyboardInterrupt:
        print(f"\nEncerrando ngda.agent.{args.name}...")


if __name__ == "__main__":
    main()
