
from __future__ import annotations

import json
from typing import Any

import Pyro5.api


def query_agents() -> list[dict[str, Any]]:
    """Consulta o estado dos agentes registrados no Name Server."""

    nameserver = Pyro5.api.locate_ns()
    registered = nameserver.list(prefix="ngda.agent.")
    results: list[dict[str, Any]] = []

    for service_name, uri in sorted(registered.items()):
        proxy = Pyro5.api.Proxy(uri)
        proxy._pyroTimeout = 3.0

        try:
            info = proxy.status()
            info["service_name"] = service_name
            info["reachable"] = True
            results.append(info)

        except Exception as exc:
            results.append({
                "name": service_name.removeprefix("ngda.agent."),
                "service_name": service_name,
                "status": "unreachable",
                "reachable": False,
                "error": str(exc),
            })

        finally:
            proxy._pyroRelease()

    return results


def launch_on_agent(
    core_id: str,
    content_path: str,
) -> dict[str, Any]:
    """Encaminha a execução para o primeiro agente alcançável."""

    nameserver = Pyro5.api.locate_ns()
    registered = nameserver.list(prefix="ngda.agent.")

    for service_name, uri in sorted(registered.items()):
        proxy = Pyro5.api.Proxy(uri)
        proxy._pyroTimeout = 10.0

        try:
            # Confirma que o agente responde antes de solicitar a execução.
            proxy.status()

            result = proxy.launch_game(core_id, content_path)

            if result.get("success"):
                result["service_name"] = service_name

            return result

        except Exception:
            # Se um agente falhar na comunicação, tenta o próximo.
            continue

        finally:
            proxy._pyroRelease()

    return {
        "success": False,
        "error": "Nenhum agente NGDA está disponível para executar o jogo.",
    }


def main() -> None:
    """Permite consultar os agentes pelo terminal."""

    try:
        print(json.dumps(
            query_agents(),
            indent=2,
            ensure_ascii=False,
        ))

    except Exception as exc:
        print(f"Falha ao consultar os agentes: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
