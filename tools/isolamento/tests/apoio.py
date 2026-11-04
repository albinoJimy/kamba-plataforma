"""Uma arvore de ensaio com uma superficie de cada tipo.

As verificacoes deste pacote tem de poder dizer «esta mal», e nao so «esta
bem». Para isso precisam de uma arvore que elas nao conhecam: a do repositorio
serve para a regressao (ela esta conforme hoje e tem de continuar), e esta
serve para os canarios — acrescenta-se o defeito de proposito e exige-se que
seja nomeado.
"""

from __future__ import annotations

from pathlib import Path

#: Um serviço em TypeScript com uma app Hono, uma rota literal e uma rota por
#: constante. O `.get("meta_verify_token")` esta aqui de proposito: e um
#: `Map.get`, nao uma rota, e a primeira versao da enumeracao contou-o como uma.
SERVICO_TS = """
import { Hono } from "hono";

export const CAMINHO = "/wa/ensaio";

export function createApp(): Hono {
  const app = new Hono();
  app.get("/healthz", (c) => c.json({}));
  app.post(CAMINHO, (c) => c.json({}));
  const segredos = new Map<string, string>();
  segredos.get("meta_verify_token");
  return app;
}
"""

#: Um servico em Python com uma rota Starlette.
SERVICO_PY = """
from starlette.routing import Route

CAMINHO_DO_ENSAIO = "/internal/ensaio"


def create_app():
    return [
        Route("/healthz", None, methods=["GET"]),
        Route(CAMINHO_DO_ENSAIO, None, methods=["POST"]),
    ]
"""

#: Uma fila com nome literal e uma com nome calculado.
FILAS_TS = """
export const FILA_DE_ENSAIO = "ensaio-inbound";

export function criar(opcoes: { fila?: string }) {
  const fila = opcoes.fila ?? FILA_DE_ENSAIO;
  const trabalhador = new Worker(fila, async () => {});
  // Uma fila com nome calculado: fica indecisa, e exige caso como as outras.
  const outra = new Queue(nomeCalculado(), {});
  return { trabalhador, outra };
}
"""

#: Uma vertical do REG, com uma tool e uma subscricao.
VERTICAL = """
id: ensaio
version: 1.0.0
tools:
  - tool_de_ensaio
subscriptions:
  - tipo: ensaio.ocorreu
    versao: 1
"""

#: As duas listas de politica, vazias e validas.
DISPENSAS = "version: 1\ndispensas: []\n"
SET_SESSAO = "version: 1\nexcepcoes: []\n"

#: O backlog que o leitor de dispensas confronta com o credor.
INDICE = "## 4. Backlog\n\n| KAM-001 | um ticket de ensaio |\n"


def arvore(raiz: Path) -> Path:
    """Escreve a arvore de ensaio em `raiz` e devolve-a."""
    (raiz / "services" / "svc" / "src").mkdir(parents=True)
    (raiz / "services" / "svc" / "src" / "app.ts").write_text(
        SERVICO_TS, encoding="utf-8"
    )
    (raiz / "services" / "pysvc" / "src" / "pacote").mkdir(parents=True)
    (raiz / "services" / "pysvc" / "src" / "pacote" / "api.py").write_text(
        SERVICO_PY, encoding="utf-8"
    )
    (raiz / "packages" / "core" / "src").mkdir(parents=True)
    (raiz / "packages" / "core" / "src" / "filas.ts").write_text(
        FILAS_TS, encoding="utf-8"
    )
    (raiz / "registry").mkdir()
    (raiz / "registry" / "ensaio.yaml").write_text(VERTICAL, encoding="utf-8")
    (raiz / "ci").mkdir()
    (raiz / "ci" / "isolamento-dispensas.yaml").write_text(DISPENSAS, encoding="utf-8")
    (raiz / "ci" / "isolamento-set-sessao.yaml").write_text(
        SET_SESSAO, encoding="utf-8"
    )
    (raiz / "specs").mkdir()
    (raiz / "specs" / "INDICE.md").write_text(INDICE, encoding="utf-8")
    return raiz
