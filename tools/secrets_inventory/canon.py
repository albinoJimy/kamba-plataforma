"""Leitura do canon de que o inventario depende (KAM-010).

Duas tabelas de `docs/tecnica/` sao lidas **do documento** e nao copiadas para
aqui:

- `08_Seguranca_Conformidade.md` §5 — a tabela de segredos, que o inventario tem
  de cobrir a 100%;
- `00_Arquitectura_Solucao.md` §4 — o catalogo de componentes, que da os codigos
  validos para `consumidores`.

A razao e a mesma nos dois casos: uma copia desactualiza-se em silencio. Se
alguem acrescentar um segredo ao doc 08 §5, a verificacao de cobertura tem de
falhar no dia seguinte — e falha, porque le a tabela. Se alguem acrescentar um
componente ao catalogo, o inventario passa a poder usa-lo sem editar codigo.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path


class CanonError(RuntimeError):
    """O documento do canon nao tem a forma que esta leitura espera."""


def normalizar(texto: str) -> str:
    """Forma canonica de um rotulo de tabela, para comparacao.

    Tira acentos, `backticks`, negrito e espacos a mais, e passa a minusculas.
    Sem isto, «PIN 2FA do número» no documento e `PIN 2FA do numero` no
    inventario seriam duas coisas — e a cobertura falharia por um acento, que e
    o tipo de falha que ensina as pessoas a desligar a verificacao.
    """
    limpo = texto.replace("`", "").replace("**", "").replace("*", "")
    limpo = unicodedata.normalize("NFKD", limpo)
    limpo = "".join(c for c in limpo if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", limpo).strip().lower()


def _linhas_de_tabela(texto: str, inicio: str, fim: str, cabecalho: str) -> list[list[str]]:
    """Celulas das linhas de corpo da tabela cujo cabecalho comeca por `cabecalho`.

    `inicio` e `fim` delimitam a seccao; a tabela e a primeira dentro dela cujo
    cabecalho corresponde.
    """
    try:
        corpo = texto.split(inicio, 1)[1].split(fim, 1)[0]
    except IndexError as erro:
        raise CanonError(f"nao encontrei a seccao entre {inicio!r} e {fim!r}") from erro

    linhas = [linha.strip() for linha in corpo.splitlines()]
    dentro = False
    resultado: list[list[str]] = []
    for linha in linhas:
        if not linha.startswith("|"):
            if dentro:
                break  # A tabela acabou.
            continue
        celulas = [c.strip() for c in linha.strip("|").split("|")]
        if not dentro:
            if normalizar(celulas[0]).startswith(normalizar(cabecalho)):
                dentro = True
            continue
        if set(linha) <= set("|-: "):
            continue  # Linha separadora.
        resultado.append(celulas)
    if not resultado:
        raise CanonError(f"tabela com cabecalho {cabecalho!r} vazia ou ausente")
    return resultado


def segredos_do_doc_08(raiz: Path) -> list[str]:
    """Primeira coluna da tabela de segredos de `docs/tecnica/08` §5.

    E esta lista que o inventario tem de cobrir a 100%.
    """
    caminho = raiz / "docs" / "tecnica" / "08_Seguranca_Conformidade.md"
    texto = caminho.read_text(encoding="utf-8")
    linhas = _linhas_de_tabela(texto, "## 5. Segredos e chaves", "## 6. Auditoria", "Segredo")
    return [celulas[0] for celulas in linhas if celulas[0] != ""]


def componentes_do_doc_00(raiz: Path) -> set[str]:
    """Codigos do catalogo de componentes de `docs/tecnica/00` §4.

    Nota: `specs/01` §2 (DoR) lista dezoito codigos e **nao** inclui `ENT`, que
    o catalogo de `docs/tecnica/00` §4 tem. Esta leitura segue o catalogo, que e
    a fonte do catalogo; a divergencia esta registada no PR do KAM-010.
    """
    caminho = raiz / "docs" / "tecnica" / "00_Arquitectura_Solucao.md"
    texto = caminho.read_text(encoding="utf-8")
    linhas = _linhas_de_tabela(
        texto, "## 4. Componentes (catálogo)", "```mermaid", "Código"
    )
    codigos = {celulas[0].strip() for celulas in linhas}
    return {c for c in codigos if re.fullmatch(r"[A-Z]{3}", c)}
