"""O `release.lock`: a lista de *digests* que um deploy implanta (KAM-078).

O deploy e por *digest*, e o *rollback* e «reimplantar o `release.lock`
anterior» (`docs/tecnica/09` §7). Por isso o lock e gerado **antes** do deploy,
e a *tag* SemVer so depois da verificacao pos-deploy (`tag.py`): e a resolucao
que o Contexto do bloco escreve para a divergencia entre o doc 09 e o §4.

## Forma

JSON e nao YAML, por duas razoes: le-se e escreve-se com a biblioteca padrao (os
tres leitores de YAML deste repositorio sao subconjuntos, e nenhum escreve), e a
serializacao com chaves ordenadas e deterministica — dois locks com o mesmo
conteudo sao o mesmo ficheiro, byte a byte::

    {
      "commit": "<sha de 40>",
      "formato": 1,
      "servicos": {
        "gwy": {"imagem": "<registo>/<nome>@sha256:<64>", "origem": "build"},
        "postgres": {"imagem": "pgvector/pgvector:...@sha256:<64>", "origem": "terceiros"}
      }
    }

Nao ha data no ficheiro, de proposito: uma data tornava dois locks iguais em
ficheiros diferentes, e o *diff* entre a release N e a N-1 deixava de dizer so
o que mudou.

## De onde vem cada *digest*

* **`origem: terceiros`** — o `image:` do compose de producao, que o gate 11
  (`supply_chain`) ja exige por `@sha256:`. Le-se do ficheiro e nao se repete.
* **`origem: build`** — os servicos nossos, que o compose constroi (`build:`).
  O *digest* so existe depois do *build*, e chega por um ficheiro JSON
  `{servico: referencia@sha256:...}` que o passo de *build* escreve. **Um
  servico `build:` sem *digest* nesse ficheiro falha**: um lock com um buraco e
  um deploy que implanta o que estiver em cache.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

#: `<nome>@sha256:<64 hexadecimais>`. A etiqueta entre o nome e o `@` e
#: permitida (e informativa), mas o que se implanta e o *digest*.
REFERENCIA_POR_DIGEST = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")

#: Um SHA de *commit* completo. O curto colide, e o lock e o registo do que foi.
COMMIT = re.compile(r"^[0-9a-f]{40}$")

FORMATO = 1
ORIGENS = ("build", "terceiros")


class LockInvalido(ValueError):
    """O lock, ou o que se quis meter nele, nao serve para implantar."""


@dataclasses.dataclass(frozen=True)
class Entrada:
    imagem: str
    origem: str


@dataclasses.dataclass(frozen=True)
class Lock:
    commit: str
    servicos: dict[str, Entrada]

    def como_json(self) -> str:
        corpo = {
            "commit": self.commit,
            "formato": FORMATO,
            "servicos": {
                nome: {"imagem": e.imagem, "origem": e.origem}
                for nome, e in sorted(self.servicos.items())
            },
        }
        return json.dumps(corpo, indent=2, sort_keys=True, ensure_ascii=True) + "\n"

    def construidos(self) -> dict[str, Entrada]:
        """Os servicos nossos: os que o gate 14 tem de verificar."""
        return {n: e for n, e in self.servicos.items() if e.origem == "build"}

    def diferencas(self, anterior: "Lock") -> dict[str, tuple[str | None, str | None]]:
        """`servico -> (antes, depois)`, so para o que mudou."""
        nomes = set(self.servicos) | set(anterior.servicos)
        saida: dict[str, tuple[str | None, str | None]] = {}
        for nome in sorted(nomes):
            antes = anterior.servicos.get(nome)
            depois = self.servicos.get(nome)
            a = antes.imagem if antes else None
            d = depois.imagem if depois else None
            if a != d:
                saida[nome] = (a, d)
        return saida


def validar(lock: Lock) -> Lock:
    """Levanta `LockInvalido` com **todos** os defeitos, e nao so o primeiro."""
    defeitos: list[str] = []
    if not COMMIT.match(lock.commit):
        defeitos.append(f"commit {lock.commit!r} nao e um SHA completo de 40 hexadecimais")
    if not lock.servicos:
        defeitos.append("o lock nao tem servicos")
    for nome, entrada in sorted(lock.servicos.items()):
        if entrada.origem not in ORIGENS:
            defeitos.append(f"{nome}: origem {entrada.origem!r} (aceites: {', '.join(ORIGENS)})")
        if not REFERENCIA_POR_DIGEST.match(entrada.imagem):
            defeitos.append(f"{nome}: {entrada.imagem!r} nao e uma referencia por @sha256")
    if defeitos:
        raise LockInvalido("; ".join(defeitos))
    return lock


def ler(caminho: Path) -> Lock:
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as excepcao:
        raise LockInvalido(f"{caminho}: nao se le ({excepcao})") from excepcao
    if not isinstance(bruto, dict) or bruto.get("formato") != FORMATO:
        raise LockInvalido(f"{caminho}: `formato` tem de ser {FORMATO}")
    servicos = bruto.get("servicos")
    if not isinstance(servicos, dict):
        raise LockInvalido(f"{caminho}: `servicos` tem de ser um mapa")
    entradas: dict[str, Entrada] = {}
    for nome, valor in servicos.items():
        if not isinstance(valor, dict):
            raise LockInvalido(f"{caminho}: {nome} tem de ser um mapa")
        entradas[nome] = Entrada(str(valor.get("imagem", "")), str(valor.get("origem", "")))
    return validar(Lock(str(bruto.get("commit", "")), entradas))


def servicos_do_compose(caminho: Path, raiz: Path) -> dict[str, str | None]:
    """`servico -> image` resolvido, ou `None` para um servico `build:`.

    Le pelo mesmo leitor do `supply_chain` (gate 11), para que os dois nunca
    discordem sobre o que e um servico. Um `image:` com interpolacao sem omissao
    fica por resolver e **falha** aqui: no deploy, o lock e a fonte, e nao o
    ambiente de quem corre.
    """
    from supply_chain import compose as compose_mod

    composto = compose_mod.ler(caminho, raiz)
    saida: dict[str, str | None] = {}
    for nome, (_no, chaves) in composto.servicos.items():
        if "build" in chaves:
            saida[nome] = None
            continue
        if "image" not in chaves:
            raise LockInvalido(f"{nome}: nem `image:` nem `build:`")
        valor, _ = compose_mod.resolver_interpolacao(chaves["image"].texto())
        if valor is None:
            raise LockInvalido(
                f"{nome}: `image:` com variavel sem omissao; o lock nao implanta o "
                "que so o ambiente de quem corre sabe"
            )
        saida[nome] = valor
    return saida


def gerar(compose: dict[str, str | None], construidos: dict[str, str], commit: str) -> Lock:
    """O lock a partir do compose e dos *digests* do *build*.

    `construidos` e o JSON que o passo de *build* escreve. Um nome a mais nele
    (um servico que o compose nao tem) tambem falha: e um *build* de outra
    arvore, ou um nome trocado.
    """
    defeitos: list[str] = []
    servicos: dict[str, Entrada] = {}
    for nome, imagem in sorted(compose.items()):
        if imagem is None:
            referencia = construidos.get(nome)
            if referencia is None:
                defeitos.append(f"{nome}: servico `build:` sem digest do build")
                continue
            servicos[nome] = Entrada(referencia, "build")
        else:
            servicos[nome] = Entrada(imagem, "terceiros")
    for nome in sorted(set(construidos) - set(compose)):
        defeitos.append(f"{nome}: digest do build para um servico que o compose nao tem")
    for nome in sorted(set(construidos) & {n for n, i in compose.items() if i is not None}):
        defeitos.append(f"{nome}: o compose ja fixa a imagem; o build nao a substitui")
    if defeitos:
        raise LockInvalido("; ".join(defeitos))
    return validar(Lock(commit, servicos))
