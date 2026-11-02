"""O canario do `env_lint`: a prova de que o lint morde.

## Porque e por mutacao e nao por *fixtures*, que e a forma da casa

O `log_policy` e o `money_lint` provam que mordem com *fixtures*: um ficheiro
por regra, numa pasta, e exige-se que cada negativa falhe. Aqui isso nao
funciona, e vale dizer porque em vez de se inventar uma forma nova em silencio.

As regras deste lint sao sobre **relacoes entre tres ambientes e uma tabela**:
«dois projectos nao se repetem», «a matriz bate com a configuracao», «uma
referencia de `prod` nao aparece em `staging`». Uma *fixture* para uma dessas
regras nao e um ficheiro — e uma arvore inteira: uma matriz, tres `env.yaml` e
os `.tf`. Dezesseis regras davam dezesseis copias da arvore, e dezesseis copias
divergem da arvore real **sem que nada avise**. O canario passaria a verde sobre
uma configuracao que ja nao se parece com a que o gate verifica.

Por mutacao e o contrario: parte-se da arvore **real**, muda-se uma coisa, e
exige-se o achado. O que se prova e mais forte — que a regra morde nesta
configuracao, e nao numa configuracao de laboratorio.

## A armadilha desta forma, e como se fecha

Um canario por mutacao tem um modo de falha proprio: a arvore muda, a mutacao
deixa de mudar nada, e o caso passa a verde por nao ter medido nada — que e
exactamente o defeito que o `money_lint` fecha ao recusar uma pasta de
*fixtures* vazia.

Daí **cada caso declarar a sua precondicao**. Antes de mutar, verifica-se que o
campo esta no estado de que o caso parte; se nao estiver, o caso falha com
`precondicao` em vez de passar. Uma mutacao que nao muda nada e uma falha, nunca
um verde.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import lint


@dataclass(frozen=True)
class Caso:
    codigo: str
    descricao: str
    #: Devolve uma mensagem quando a arvore nao esta no estado de partida.
    precondicao: Callable[[lint.Dados], str | None]
    mutacao: Callable[[lint.Dados], None]


def _dados(dados: lint.Dados, ambiente: str) -> dict:
    return dados.ambientes[ambiente]["dados"]


def _exige(condicao: bool, mensagem: str) -> str | None:
    return None if condicao else mensagem


def _injectar(dados: lint.Dados, caminho: str, linha: str) -> None:
    dados.ficheiros[caminho] = dados.ficheiros.get(caminho, "") + "\n" + linha + "\n"


def _real_com_d1_e_sem_apd(dados: lint.Dados) -> None:
    """Passa `prod` a `real` **com** referencia de D1 e sem `apd_ref`.

    As duas metades do criterio 4 testam-se separadas de proposito: com as duas
    em falta, um unico achado dava a impressao de cobrir as duas.
    """
    secao = _dados(dados, "prod")
    secao["classe"] = "real"
    secao["decisao_d1"] = "D1/2026-12-01/jnb-cpt"


def _tirar_a_primeira_linha_da_matriz(dados: lint.Dados) -> None:
    dados.linhas_da_matriz.pop(0)


CASOS: tuple[Caso, ...] = (
    Caso(
        "restauro-de-prod",
        "`staging` a aceitar restauro de `prod` (criterio 3, teste negativo)",
        lambda d: _exige(
            _dados(d, "staging")["restauro_de"] == [],
            "staging.dados.restauro_de ja nao esta vazia",
        ),
        lambda d: _dados(d, "staging").__setitem__("restauro_de", ["prod"]),
    ),
    Caso(
        "real-sem-d1",
        "`prod` a passar a `real` sem referencia de decisao D1 (criterio 4)",
        lambda d: _exige(
            _dados(d, "prod")["classe"] == "synthetic" and _dados(d, "prod")["decisao_d1"] is None,
            "prod ja nao esta em synthetic com decisao_d1 nula",
        ),
        lambda d: _dados(d, "prod").__setitem__("classe", "real"),
    ),
    Caso(
        "real-sem-apd-ref",
        "`prod` a passar a `real` sem nenhum `apd_ref` (criterio 4)",
        lambda d: _exige(
            _dados(d, "prod")["apd_refs"] == [], "prod.dados.apd_refs ja nao esta vazia"
        ),
        _real_com_d1_e_sem_apd,
    ),
    Caso(
        "d1-mal-formada",
        "uma referencia de D1 fora de `D1/<AAAA-MM-DD>/<slug>`",
        lambda d: _exige(_dados(d, "prod")["decisao_d1"] is None, "prod ja tem decisao_d1"),
        lambda d: _dados(d, "prod").__setitem__("decisao_d1", "decidido na reuniao"),
    ),
    Caso(
        "apd-ref-mal-formada",
        "um `apd_ref` com espacos (a forma e a de KAM-011)",
        lambda d: _exige(_dados(d, "prod")["apd_refs"] == [], "prod ja tem apd_refs"),
        lambda d: _dados(d, "prod").__setitem__("apd_refs", ["protocolo 123 de 2026"]),
    ),
    Caso(
        "restauro-desconhecido",
        "`restauro_de` a nomear algo que nao e um ambiente",
        lambda d: _exige(_dados(d, "dev")["restauro_de"] == [], "dev ja tem restauro_de"),
        lambda d: _dados(d, "dev").__setitem__("restauro_de", ["qa"]),
    ),
    Caso(
        "classe-desconhecida",
        "`dados.classe` em portugues em vez de `synthetic`/`real`",
        lambda d: _exige(
            _dados(d, "staging")["classe"] == "synthetic", "staging ja nao esta em synthetic"
        ),
        lambda d: _dados(d, "staging").__setitem__("classe", "sinteticos"),
    ),
    Caso(
        "etiqueta-de-classe-divergente",
        "a etiqueta de custo a dizer `real` com a classe em `synthetic`",
        lambda d: _exige(
            d.ambientes["prod"]["custo"]["etiquetas"]["kamba_data_class"] == "synthetic",
            "a etiqueta de prod ja nao diz synthetic",
        ),
        lambda d: d.ambientes["prod"]["custo"]["etiquetas"].__setitem__(
            "kamba_data_class", "real"
        ),
    ),
    Caso(
        "projecto-repetido",
        "`staging` e `prod` no mesmo projecto de segredos (criterio 5)",
        lambda d: _exige(
            d.ambientes["staging"]["segredos"]["projecto"]
            != d.ambientes["prod"]["segredos"]["projecto"],
            "staging e prod ja partilham projecto",
        ),
        lambda d: d.ambientes["staging"]["segredos"].__setitem__("projecto", "prod"),
    ),
    Caso(
        "projecto-local-fora-de-dev",
        "`staging` com segredos locais, que o doc 09 §6 reserva a `dev`",
        lambda d: _exige(
            d.ambientes["staging"]["segredos"]["projecto"] != lint.PROJECTO_LOCAL,
            "staging ja tem projecto local",
        ),
        lambda d: d.ambientes["staging"]["segredos"].__setitem__(
            "projecto", lint.PROJECTO_LOCAL
        ),
    ),
    Caso(
        "segredo-de-outro-ambiente",
        "um segredo de `prod` referenciado em `staging` (criterio 5, o negativo)",
        lambda d: _exige(
            "meta_app_secret" in d.inventario, "meta_app_secret saiu do inventario"
        ),
        lambda d: _injectar(
            d, "infra/envs/staging/main.tf", '  segredo = "prod/META_APP_SECRET"'
        ),
    ),
    Caso(
        "segredo-fora-de-um-ambiente",
        "uma referencia de segredo dentro de um modulo, que nao sabe de que ambiente e",
        lambda d: _exige(
            "meta_app_secret" in d.inventario, "meta_app_secret saiu do inventario"
        ),
        lambda d: _injectar(
            d, "infra/modules/host-base/main.tf", '  segredo = "staging/META_APP_SECRET"'
        ),
    ),
    Caso(
        "segredo-nao-existe-no-ambiente",
        "`dev` a pedir a chave do facilitador, que o inventario tem so em staging/prod",
        lambda d: _exige(
            "dev" not in d.inventario.get("proxypay_api_key", ()),
            "proxypay_api_key passou a existir em dev",
        ),
        lambda d: _injectar(
            d, "infra/envs/dev/env.yaml", '  # local/PROXYPAY_API_KEY'
        ),
    ),
    Caso(
        "segredo-fora-do-inventario",
        "uma referencia a um segredo que o inventario do KAM-010 nao tem",
        lambda d: _exige(
            "segredo_inventado" not in d.inventario, "o inventario tem um segredo_inventado"
        ),
        lambda d: _injectar(
            d, "infra/envs/prod/main.tf", '  segredo = "prod/SEGREDO_INVENTADO"'
        ),
    ),
    Caso(
        "recurso-fora-da-costura",
        "um `resource` num modulo de raiz, que e o fornecedor a entrar pela janela (criterio 6)",
        lambda d: _exige(
            "infra/envs/prod/main.tf" in d.ficheiros, "infra/envs/prod/main.tf desapareceu"
        ),
        lambda d: _injectar(d, "infra/envs/prod/main.tf", 'resource "qualquer_vm" "host" {}'),
    ),
    Caso(
        "ttl-acima-do-proposto",
        f"um TTL de DNS acima do tecto *proposto* de {lint.TTL_MAXIMO_PROPOSTO} s",
        lambda d: _exige(
            d.ambientes["dev"]["dns"]["ttl_segundos"] <= lint.TTL_MAXIMO_PROPOSTO,
            "dev ja esta acima do tecto",
        ),
        lambda d: d.ambientes["dev"]["dns"].__setitem__("ttl_segundos", 3600),
    ),
    Caso(
        "matriz-divergente",
        "a configuracao a mudar sem a matriz mudar com ela (criterio 1)",
        lambda d: _exige(
            d.ambientes["staging"]["compute"]["forma"] == "4vcpu-16gb",
            "a forma de staging ja nao e 4vcpu-16gb",
        ),
        lambda d: d.ambientes["staging"]["compute"].__setitem__("forma", "2vcpu-8gb"),
    ),
    Caso(
        "ambiente-mal-declarado",
        "um `env.yaml` a declarar um ambiente que nao e o da sua pasta",
        lambda d: _exige(d.ambientes["dev"]["ambiente"] == "dev", "dev ja nao se declara dev"),
        lambda d: d.ambientes["dev"].__setitem__("ambiente", "staging"),
    ),
    Caso(
        "matriz-linha-em-falta",
        "uma das sete linhas do doc 09 §6 fora da matriz (criterio 1)",
        lambda d: _exige(len(d.linhas_da_matriz) >= 1, "a matriz nao tem linhas"),
        _tirar_a_primeira_linha_da_matriz,
    ),
)


def correr(raiz: Path) -> tuple[list[str], dict[str, int]]:
    """Devolve as falhas e os numeros. Zero falhas = o lint morde em todos.

    Primeiro passo, e e ele que torna o resto significativo: a arvore **sem**
    mutacao tem de dar zero achados. Um canario sobre uma arvore que ja esta
    vermelha nao prova que a regra morde — prova que ha ruido.
    """
    falhas: list[str] = []
    base = lint.carregar(raiz)

    limpos = lint.avaliar(base)
    if limpos:
        falhas.append(
            f"a arvore sem mutacao da {len(limpos)} achados; o canario so diz algo "
            f"sobre uma arvore limpa (primeiro: {limpos[0]})"
        )

    codigos_cobertos = set()
    for caso in CASOS:
        mutados = copy.deepcopy(base)
        razao = caso.precondicao(mutados)
        if razao is not None:
            falhas.append(
                f"{caso.codigo}: precondicao falhou ({razao}). A mutacao nao mudaria "
                "nada, e um caso que nao muda nada passa sempre"
            )
            continue
        caso.mutacao(mutados)
        achados = lint.avaliar(mutados)
        if not any(achado.codigo == caso.codigo for achado in achados):
            obtidos = sorted({achado.codigo for achado in achados})
            falhas.append(
                f"{caso.codigo}: a mutacao ({caso.descricao}) nao produziu o achado; "
                f"obtive {obtidos or ['nenhum']}"
            )
        else:
            codigos_cobertos.add(caso.codigo)

    return falhas, {
        "casos": len(CASOS),
        "cobertos": len(codigos_cobertos),
        "regras": len(lint.REGRAS),
    }
