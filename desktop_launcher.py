from __future__ import annotations

import os
import socket
import threading
import time

import Pyro5.api
import Pyro5.nameserver
import uvicorn
import webview

from ngda.distributed.agent import run_agent_loop

try:
    from ngda.web.app import app
except ImportError:
    try:
        from ngda.server.app import app
    except ImportError:
        try:
            from ngda.api.app import app
        except ImportError:
            from ngda.app import app


def find_free_port() -> int:
    """Aloca uma porta TCP livre no localhost para permitir múltiplas instâncias."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ensure_nameserver(host: str = "127.0.0.1") -> None:
    """Garante que exista um Name Server Pyro5 ativo; se não houver, inicia um."""
    try:
        Pyro5.api.locate_ns()
        print("[NGDA] Name Server Pyro5 já está ativo na rede.")
    except Exception:
        print("[NGDA] Iniciando Name Server Pyro5 local...")
        ns_thread = threading.Thread(
            target=Pyro5.nameserver.start_ns_loop,
            kwargs={"host": host},
            daemon=True,
        )
        ns_thread.start()
        for _ in range(20):
            try:
                Pyro5.api.locate_ns()
                break
            except Exception:
                time.sleep(0.2)


def main() -> None:
    host = "127.0.0.1"
    pid = os.getpid()
    hostname = socket.gethostname()
    agent_name = f"{hostname}-{pid}"

    ensure_nameserver(host=host)

    stop_event = threading.Event()
    agent_thread = threading.Thread(
        target=run_agent_loop,
        args=(agent_name, host, stop_event),
        daemon=True,
    )
    agent_thread.start()

    api_port = find_free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=api_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    api_thread = threading.Thread(target=server.run, daemon=True)
    api_thread.start()

    time.sleep(0.8)

    webview.create_window(
        title=f"NGDA — Games Explorer [{agent_name}]",
        url=f"http://127.0.0.1:{api_port}/",
        width=1120,
        height=720,
        min_size=(820, 540),
    )

    try:
        webview.start()
    finally:
        stop_event.set()
        server.should_exit = True
        agent_thread.join(timeout=2.0)


if __name__ == "__main__":
    main()