"""Os `enum` dos contratos contra os domínios do dicionário (KAM-159).

**Porque é que isto não existia, e porque é que a ausência não se via.** O
dicionário e os contratos de evento nomeavam, cada um, uma lista de finalidades
de consentimento. Cruzavam-se **numa só** — `marketing` —, e duas finalidades
que o canon declarava eram **impossíveis de emitir**, porque o `enum` dos
contratos era fechado e não as tinha. Isto esteve assim desde o KAM-007 e
nenhum gate o disse:

* o **3b** lê os contratos, mas o nível 1 só procura **variantes declaradas**
  na coluna «Substitui» do §3, e o nível 2 só pergunta «este *nome* existe
  algures no §3?» — `finalidade` existia, por empréstimo de outro conceito;
* o `tools/canon_lint/eventos.py` **nunca** compara um `enum` com um domínio;
* o **gate 7** não consulta o dicionário em sítio nenhum.

Cada um verificava o seu lado, e ninguém verificava a costura.

**O que isto faz.** Para cada par (domínio canónico, campo de contrato)
declarado em `DOMINIOS_VIGIADOS`, compara os dois conjuntos **nos dois
sentidos**:

* um valor no `enum` que o dicionário não tem → o contrato promete o que o
  canon não reconhece. Vale para **todas** as versões;
* um valor no dicionário que nenhum `enum` tem → o canon declara o que **nunca
  se consegue emitir**, que é o caso que esteve dois tickets de pé. Vale para a
  **última** versão de cada tipo, e só para ela.

**Porque é que o segundo sentido olha só para a última.** Uma `v1` publicada
está congelada: o §6.6 diz que «quem quer quebrar escreve `v<N+1>` e deixa o
`v<N>` como estava». Exigir que uma `v1` cubra um domínio que cresceu depois
dela seria exigir que se alterasse um contrato fundido — que é exactamente o
que este gate existe para impedir. O que tem de ser verdade é que **a versão
mais recente** cobre o domínio: é a que um produtor novo escreve.

Vive no gate 7 e não no 3b por uma razão prática: é aqui que os contratos já
estão lidos e indexados por tipo e versão. O 3b teria de os reler.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kamba_yaml import YamlSubsetError, load_file  # noqa: E402

from . import catalogo  # noqa: E402
from .pii import Achado  # noqa: E402

DICIONARIO = Path("canon") / "dicionario.yaml"


@dataclass(frozen=True)
class Vigiado:
    """Um domínio do dicionário e o caminho do campo que o deve espelhar."""

    #: A chave do domínio em `canon/dicionario.yaml`, como o exportador a
    #: escreve: `<tabela>.<coluna>`.
    dominio: str
    #: O caminho até ao `enum`, a partir da raiz do schema. Cada passo é uma
    #: chave; a travessia não adivinha, para que um `enum` noutro sítio do
    #: documento não entre por acidente.
    caminho: tuple[str, ...]
    #: Para que serve, numa frase que sobreviva ao autor.
    razao: str


#: Os pares vigiados. **Um, hoje** — e dizê-lo importa, porque este ficheiro
#: fecha uma classe e não um caso: qualquer domínio fechado que também viva num
#: contrato pertence aqui, e acrescentar um par é uma linha.
DOMINIOS_VIGIADOS = (
    Vigiado(
        dominio="consent_event.purpose",
        caminho=("properties", "finalidades", "items"),
        razao=(
            "as finalidades do envelope sao o que o publicador compara com a "
            "`finalidade` de cada subscricao; uma que o canon declare e o "
            "contrato nao tenha nunca chega a lado nenhum"
        ),
    ),
    Vigiado(
        dominio="consent_event.purpose",
        caminho=("properties", "payload", "properties", "finalidade"),
        razao=(
            "a finalidade que o proprio evento de consentimento regista. So "
            "os dois `consent.*` a tem, e os outros 36 nao sao verificados "
            "por este par"
        ),
    ),
)


class DicionarioAusente(ValueError):
    """O `canon/dicionario.yaml` falta ou não se lê. É configuração, não achado."""


def _dominios(raiz: Path) -> dict[str, list[str]]:
    caminho = raiz / DICIONARIO
    if not caminho.is_file():
        raise DicionarioAusente(
            f"{DICIONARIO.as_posix()} nao existe. Gere-o: "
            "cd tools && python -m dict_export --root .."
        )
    try:
        dados = load_file(caminho)
    except YamlSubsetError as excepcao:
        raise DicionarioAusente(str(excepcao)) from excepcao
    brutos = dados.get("dominios")
    if not isinstance(brutos, list) or not brutos:
        # Fail-closed: um dicionario sem dominios faria esta verificacao
        # passar sobre o vazio, e passar sobre o vazio e dizer verde sem ter
        # olhado.
        raise DicionarioAusente(
            f"{DICIONARIO.as_posix()}: sem `dominios`. A verificacao ficaria "
            "vazia, e uma verificacao vazia que diz verde e pior do que nenhuma"
        )
    return {
        str(d["coluna"]): [str(v) for v in (d.get("valores") or [])]
        for d in brutos
        if isinstance(d, dict) and d.get("coluna")
    }


def _enum_em(documento: dict, caminho: tuple[str, ...]) -> list[str] | None:
    """O `enum` no fim do caminho, ou `None` se o caminho não existir."""
    no: object = documento
    for passo in caminho:
        if not isinstance(no, dict) or passo not in no:
            return None
        no = no[passo]
    if not isinstance(no, dict):
        return None
    valores = no.get("enum")
    if not isinstance(valores, list):
        return None
    return [str(v) for v in valores]


def verificar(raiz: Path) -> list[Achado]:
    """Os dois sentidos, para cada par vigiado e cada contrato."""
    canonicos = _dominios(raiz)
    achados: list[Achado] = []
    vistos: set[tuple[str, str]] = set()

    contratos = catalogo.todos(raiz)
    # A ultima versao de cada tipo. E a unica a quem se exige cobrir o
    # dominio inteiro: as anteriores estao congeladas pelo §6.6.
    ultima_de: dict[str, int] = {}
    for contrato in contratos:
        ultima_de[contrato.tipo] = max(ultima_de.get(contrato.tipo, 0), contrato.versao)

    for vigiado in DOMINIOS_VIGIADOS:
        esperado = canonicos.get(vigiado.dominio)
        if esperado is None:
            achados.append(
                Achado(
                    DICIONARIO.as_posix(),
                    vigiado.dominio,
                    "esta vigiado e nao existe no dicionario. Ou se escreve "
                    "no §3 na forma `coluna` ∈ {…}, ou sai de "
                    "`DOMINIOS_VIGIADOS`",
                )
            )
            continue
        for contrato in contratos:
            valores = _enum_em(contrato.documento, vigiado.caminho)
            if valores is None:
                continue
            relativo = contrato.caminho.relative_to(raiz).as_posix()
            a_mais = sorted(set(valores) - set(esperado))
            e_a_ultima = contrato.versao == ultima_de[contrato.tipo]
            em_falta = sorted(set(esperado) - set(valores)) if e_a_ultima else []
            if a_mais:
                achados.append(
                    Achado(
                        relativo,
                        ".".join(vigiado.caminho),
                        f"tem {a_mais}, que o dominio `{vigiado.dominio}` nao "
                        "reconhece. O contrato promete o que o canon nao declara",
                    )
                )
            if em_falta:
                achados.append(
                    Achado(
                        relativo,
                        ".".join(vigiado.caminho),
                        f"o dominio `{vigiado.dominio}` tem {em_falta} e este "
                        "nao. **Sao valores que o canon declara e que ninguem "
                        "consegue emitir** — e o defeito que o KAM-159 fechou, "
                        "a repetir-se",
                    )
                )
            vistos.add((vigiado.dominio, relativo))

    if not vistos:
        # Nenhum contrato bateu em nenhum caminho vigiado: ou o catalogo esta
        # vazio, ou os caminhos mudaram de forma. Em qualquer dos casos esta
        # verificacao nao olhou para nada, e tem de o dizer.
        achados.append(
            Achado(
                "contratos/eventos/",
                "(nada lido)",
                "nenhum contrato bate em nenhum caminho de "
                "`DOMINIOS_VIGIADOS`. A verificacao passou sem ler nada — ou o "
                "catalogo esta vazio, ou a forma dos schemas mudou",
            )
        )
    return achados
