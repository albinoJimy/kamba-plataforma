"""O achado, e as duas mensagens que todas as superficies partilham."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .dicionario import EXTENSOES, Saber, Variante

#: Nivel 1 — variante que o dicionario substitui. Falha sempre.
VARIANTE = "variante"
#: Nivel 2 — nome que o §3 nao cobre e que nao esta em `canon/extensoes.yaml`.
FORA = "fora-do-dicionario"
#: O dicionario fixa uma regra (dominio, unicidade, identificador) e o texto viola-a.
REGRA = "regra"
#: O lint nao consegue ler o que la esta. Nao e saltado: falha.
ILEGIVEL = "ilegivel"
#: Um ficheiro com forma de superficie que nenhum padrao cobre.
SENTINELA = "sentinela"


@dataclass(frozen=True)
class Achado:
    ficheiro: str
    linha: int
    classe: str
    mensagem: str

    def __str__(self) -> str:
        onde = f"{self.ficheiro}:{self.linha}" if self.linha else self.ficheiro
        return f"{onde}: [{self.classe}] {self.mensagem}"


def variante(ficheiro: str, linha: int, v: Variante) -> Achado:
    return Achado(ficheiro, linha, VARIANTE, v.mensagem())


def fora(ficheiro: str, linha: int, tipo: str, nome: str, contexto: str = "") -> Achado:
    """Nivel 2. `contexto`, quando existe, e a forma canonica mais proxima."""
    if contexto:
        cabeca = f"`{nome}` → {contexto}"
    else:
        cabeca = f"`{nome}` nao esta no dicionário §3"
    return Achado(
        ficheiro,
        linha,
        FORA,
        f"{cabeca} ({tipo} fora do dicionário; se for um nome novo, declare-o em "
        f"{EXTENSOES} com tipo `{tipo}`, ticket e data)",
    )


def aceita(saber: Saber, tipo: str, nome: str, simples: str | None = None) -> bool:
    """`True` se o nome esta no §3 (para esse tipo) ou numa extensao do tipo certo.

    `simples` e o nome sem qualificacao (`nif` para `tenants.nif`): o §3 e uma
    lista de nomes por conceito, pelo que um nome do dicionario vale em qualquer
    tabela; a **extensao**, pelo contrario, e sempre qualificada, para que
    declarar `tenants.nif` nao torne `nif` valido em todo o lado.
    """
    if saber.conhecido(simples if simples is not None else nome, tipo):
        return True
    return saber.extensoes.tem(tipo, nome)


_PADROES: dict[str, re.Pattern] = {}


def variantes_em_texto(saber: Saber, texto: str) -> list[Variante]:
    """As variantes de **nome** que aparecem dentro de um texto, com fronteira de palavra.

    `valor_max_pedido_kz` e uma chave de `limites jsonb`: numa migracao so existe
    dentro de uma cadeia (`'{"valor_max_pedido_kz": 5}'`), nunca como
    identificador. `max_preco_kz` nao contem `preco_kz` para este efeito.
    """
    achadas = []
    for nome, v in saber.dicionario.variantes_nome.items():
        if nome not in texto:
            continue
        padrao = _PADROES.get(nome)
        if padrao is None:
            padrao = _PADROES[nome] = re.compile(
                r"(?<![A-Za-z0-9_])" + re.escape(nome) + r"(?![A-Za-z0-9_])"
            )
        if padrao.search(texto):
            achadas.append(v)
    return achadas
