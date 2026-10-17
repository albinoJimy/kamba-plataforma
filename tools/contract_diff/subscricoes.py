"""A `versao_max` de cada subscricao existe nos contratos (critério 5).

O publicador entrega a cada consumidor a versao que ele declara em
`evt_subscricoes.versao_max`, convertendo se for preciso (`docs/tecnica/06`
§6.6). Uma subscricao que declare uma versao que nao existe em contrato nenhum
nao e um erro de execucao — e um erro de configuracao, e o sitio de o apanhar e
o CI.

## Onde se leem as subscricoes, e o que isso tem de desconfortavel

Hoje **nao ha nenhuma**. A tabela `evt_subscricoes` existe desde a revisao
`0004` e nenhuma migracao insere linhas; as subscricoes reais nascem em
`registry/*.yaml` com o EPIC-03 (KAM-038), e `registry/` tem so um `README.md`.

Isso poe esta verificacao perante a escolha entre duas coisas ruins: validar um
conjunto vazio — e passar **vacuamente**, que e a forma de uma caixa de ticket
parecer cumprida sem nada a sustentar — ou inventar a fonte, que e do KAM-038.

Escolheu-se uma terceira: a verificacao le `registry/*.yaml` **se existirem** e
diz, na saida e sempre, quantas subscricoes leu. Zero e um numero visivel, e o
relatorio do ticket cita-o. Quando o KAM-038 escrever o primeiro ficheiro, esta
verificacao comeca a morder sem ninguem lhe tocar — e o `canario` prova, com
uma subscricao inventada em memoria, que ela morde mesmo.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from contract_diff import catalogo

#: Onde o EPIC-03 vai escrever as subscricoes.
PASTA_DO_REGISTO = Path("registry")


@dataclasses.dataclass(frozen=True)
class Subscricao:
    ficheiro: str
    consumer: str
    tipo: str
    versao_max: int


@dataclasses.dataclass(frozen=True)
class Achado:
    ficheiro: str
    porque: str

    def __str__(self) -> str:
        return f"{self.ficheiro}: {self.porque}"


def ler(raiz: Path) -> list[Subscricao]:
    """As subscricoes declaradas em `registry/*.yaml`. Hoje, nenhuma."""
    import kamba_yaml

    pasta = raiz / PASTA_DO_REGISTO
    if not pasta.is_dir():
        return []
    lidas: list[Subscricao] = []
    for caminho in sorted(pasta.glob("*.yaml")):
        documento = kamba_yaml.load_file(caminho)
        relativo = caminho.relative_to(raiz).as_posix()
        consumer = str(documento.get("consumer") or caminho.stem)
        for entrada in documento.get("subscricoes") or []:
            lidas.append(
                Subscricao(
                    ficheiro=relativo,
                    consumer=consumer,
                    tipo=str(entrada["tipo"]),
                    versao_max=int(entrada["versao_max"]),
                )
            )
    return lidas


def verificar(raiz: Path, subscricoes: list[Subscricao] | None = None) -> list[Achado]:
    """Cada `(tipo, versao_max)` subscrito tem contrato.

    `subscricoes` existe para o canario: passa-se uma lista em memoria e
    prova-se que a verificacao morde enquanto `registry/` esta vazia.
    """
    if subscricoes is None:
        subscricoes = ler(raiz)
    existentes = {(c.tipo, c.versao) for c in catalogo.todos(raiz)}
    tipos = {tipo for tipo, _ in existentes}
    achados: list[Achado] = []
    for s in subscricoes:
        if s.tipo not in tipos:
            achados.append(
                Achado(
                    s.ficheiro,
                    f"{s.consumer} subscreve {s.tipo}, que nao tem contrato nenhum em "
                    f"{catalogo.PASTA.as_posix()}",
                )
            )
        elif (s.tipo, s.versao_max) not in existentes:
            disponiveis = sorted(v for t, v in existentes if t == s.tipo)
            achados.append(
                Achado(
                    s.ficheiro,
                    f"{s.consumer} declara versao_max={s.versao_max} para {s.tipo}, e "
                    f"so existe(m) a(s) versao(oes) {disponiveis}",
                )
            )
    return achados
