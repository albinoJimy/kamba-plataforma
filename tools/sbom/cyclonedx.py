"""Emissao de SBOM em CycloneDX 1.6 (JSON).

O ticket pede «SBOM CycloneDX por servico». Gera-se um por componente do
monorepo (`services/*`, `packages/*`, `libs/*`) mais um do conjunto, e o KAM-067
reutiliza este gerador para o SBOM **por imagem** — que e a outra unidade, no
outro momento. A divisao esta escrita em `docs/ci.md`.

Escreve-se o JSON de forma determinista (chaves ordenadas, componentes
ordenados, sem data), para que dois `make ci-11` sobre a mesma arvore produzam
ficheiros identicos. Um SBOM com timestamp muda a cada execucao e deixa de se
poder comparar — e comparar e metade da utilidade de o ter.
"""

from __future__ import annotations

import json
from pathlib import Path

from .collect import Componente

#: Versao da especificacao. Fixa, nao «a mais recente»: o formato e um contrato
#: com quem consome o SBOM (KAM-067, e qualquer auditoria).
VERSAO_SPEC = "1.6"


def _licenca_para_cyclonedx(
    licenca: str | None, ids_spdx: frozenset[str] = frozenset()
) -> list[dict]:
    """O campo `licenses` do CycloneDX.

    Uma expressao composta (`MIT AND BUSL-1.1`) vai em `expression`; um
    identificador SPDX vai em `license.id`; **qualquer outra cadeia vai em
    `license.name`**.

    A ultima parte nao e detalhe de estilo. No CycloneDX 1.6 o `license.id`
    esta restringido a enumeracao SPDX, pelo que um documento com
    `license.id: "UNLICENSED"` nao valida contra o esquema — e `UNLICENSED` e
    convencao do npm, nao SPDX. A primeira versao punha em `id` tudo o que nao
    tivesse operador, e os 7 pacotes do monorepo que declaram `UNLICENSED`
    (mais o que vier de um campo `License:` de texto livre) tornavam os SBOM
    invalidos. Um ficheiro que nao valida e um ficheiro com a extensao certa,
    nao um SBOM — e e o KAM-067 que descobriria isso, a jusante.

    `ids_spdx` e o conjunto de identificadores que `ci/licenses.yaml` curou.
    Uma licenca SPDX legitima que nao esteja la vai em `name`: perde-se
    precisao, nao validade, e o gate nomeia o pacote quando aparecer.
    """
    if not licenca:
        return []
    if any(op in licenca.upper() for op in (" AND ", " OR ", " WITH ")):
        return [{"expression": licenca}]
    if licenca in ids_spdx:
        return [{"license": {"id": licenca}}]
    return [{"license": {"name": licenca}}]


def construir(
    nome_do_alvo: str,
    versao_do_alvo: str,
    componentes: list[Componente],
    ids_spdx: frozenset[str] = frozenset(),
) -> dict:
    """Constroi o documento CycloneDX de um alvo."""
    return {
        "bomFormat": "CycloneDX",
        "specVersion": VERSAO_SPEC,
        "version": 1,
        "metadata": {
            # Sem `timestamp`, de proposito: ver o cabecalho deste modulo.
            "component": {
                "type": "application",
                "name": nome_do_alvo,
                "version": versao_do_alvo,
                "bom-ref": f"alvo:{nome_do_alvo}",
            },
            "tools": [
                {
                    "name": "tools/sbom",
                    "vendor": "KAMBÁ",
                    "version": "1",
                }
            ],
        },
        "components": [
            {
                "type": "library",
                "bom-ref": componente.purl,
                "name": componente.nome,
                "version": componente.versao,
                "purl": componente.purl,
                "licenses": _licenca_para_cyclonedx(componente.licenca, ids_spdx),
                "properties": [
                    {
                        "name": "kamba:origem-da-licenca",
                        "value": componente.origem,
                    }
                ],
            }
            for componente in sorted(
                componentes, key=lambda c: (c.ecossistema, c.nome, c.versao)
            )
        ],
    }


def escrever(documento: dict, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(documento, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
