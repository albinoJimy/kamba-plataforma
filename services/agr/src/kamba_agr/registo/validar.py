"""As **seis** validacoes de arranque de `docs/tecnica/02` §5.2.

O §5.2 escreve-as por extenso, e a numeracao abaixo e a dele:

| # | Nome | O que exige | Fonte da verdade | Estado hoje |
|---|---|---|---|---|
| 1 | `tools` | cada `tools[]` existe no catalogo da TLS e **nenhuma** tem parametro proibido no esquema visivel ao modelo | catalogo da ToolLayer | **por ligar** (KAM-028) |
| 2 | `entitlements` | cada chave de `entitlements.limites` existe no TEN | `kamba_core.ten.CHAVES_DE_LIMITE` | corre |
| 3 | `grafo` | o grafo compilado tem os seis nos obrigatorios | o `build_graph` da vertical | **por ligar** (KAM-031/035) |
| 4 | `subscriptions` | cada `{tipo, versao}` tem contrato publicado | `kamba_core.eventos.contratos.CATALOGO` | corre |
| 5 | `fase` | `phase: D` e rejeitada com `KAMBA_FASE=piloto` | `kamba_core.fluxo_piloto` | corre |
| 6 | `golden` | o *dataset* referido existe e o gate da versao esta verde | o disco, e o eval harness | **por ligar** (KAM-040) |

## Uma validacao por ligar nao e uma validacao que passa

As tres da coluna da direita nao tem fonte no repositorio, e havia duas
maneiras erradas de lidar com isso. A primeira era devolve-las verdes, que e o
defeito que o critero de aceitacao deste ticket avisa — «um critero pode estar
satisfeito pela razao errada». A segunda era pô-las a falhar, que impedia o AGR
de arrancar hoje por causa de um ticket de amanha.

O que se faz e o que o **critero 8** do bloco do KAM-027 manda fazer para a (6):
a validacao **corre sempre** e o `registry/gates.yaml` diz se o que ela encontra
bloqueia ou avisa, com o ticket que o fecha.

**Mas o `aviso` cala UMA classe de problema e nao a validacao.** Um problema e de
uma de duas classes:

* **`PorLigar`** — «a fonte que esta validacao confronta nao existe neste
  repositorio». E o unico que o `modo: aviso` pode calar.
* qualquer outro — «confrontei e esta errado». **Bloqueia sempre**, seja qual
  for o modo.

A distincao e a correccao de um defeito que a revisao adversarial encontrou, e
vale a pena escrever o caso: sem ela, no dia em que o KAM-028 ligasse o catalogo,
uma tool inexistente — ou uma que exponha `tenant_id` ao modelo — passava a ser
**aviso**, porque a linha `tools: { modo: aviso }` sobreviveria ao credor. O
mecanismo de adiamento engolia o defeito que a validacao existe para apanhar.

Com a distincao, os criterios 2 e 3 do bloco ficam cumpridos **a letra** sem
mexer no `gates.yaml`: um problema real reprova o arranque hoje e amanha.

**E um `aviso` que sobreviva ao credor e erro.** Se uma validacao em `aviso` nao
devolver problema nenhum de `PorLigar`, a fonte dela **ja existe** e a linha do
`gates.yaml` esta morta: o arranque falha a dizer isso. E a disciplina do
`canon/extensoes.yaml` («uma extensao que nenhuma superficie usa falha o gate»),
e e o que torna verdadeira a frase «fechar um aviso e apagar uma linha».

Nenhuma destas funcoes conhece nomes de vertical. Os nomes estao no dicionario
canonico, o *gate* 3b impõe-nos aos ficheiros de `registry/`, e ha um teste de
arquitectura que mede este modulo contra isso.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from .esquema import VerticalDoRegisto

#: Os parametros que **nunca** aparecem num esquema de tool visivel ao modelo
#: (dicionario §3.26; critero 2 deste ticket e critero 3 do KAM-028).
#:
#: O `tenant_id` e nome canonico e e precisamente por isso que esta aqui: a TLS
#: constroi as tools por turno a partir do `ToolContext`, derivado do estado
#: validado, e «o modelo nunca ve nem fornece `tenant_id`» (`docs/tecnica/02`
#: §6.1). Um parametro destes no esquema e um campo que o modelo pode preencher
#: com o que o texto do cliente lhe disser — que e a injeccao que o ADR-015
#: existe para fechar.
PARAMETROS_PROIBIDOS: Final = ("tenant_id", "merchant_id", "seller", "account")

#: Os seis nos que um grafo de vertical tem de ter (`docs/tecnica/02` §5.2
#: validacao 3; dicionario §3.26).
#:
#: Sao nos **partilhados** e nao da vertical (§5.4, «Regra de dois»): a vertical
#: acrescenta `retrieve`/`cart_build`/`create_order` ou
#: `slots_collect`/`check_availability`/`book_slot`, e estes seis sao o
#: esqueleto que as duas tem igual. E por isso que a validacao e por **inclusao**
#: e nunca por igualdade: um grafo com mais nos esta certo.
NOS_OBRIGATORIOS: Final = (
    "ingest", "guard_in", "validate", "guard_out", "send", "handoff_wait",
)

#: A fase em que `phase: D` e rejeitada. O nome da variavel e o valor vem de
#: `kamba_core.fluxo_piloto`, que e quem ja os tinha (KAM-003) — nao se
#: redeclaram aqui para que nao possam divergir.
from kamba_core.fluxo_piloto import FASE_PILOTO, VARIAVEL as VARIAVEL_DE_FASE  # noqa: E402

#: As fases em que uma vertical `phase: D` pode correr. **Vazia, de proposito.**
#:
#: O canon define **um** valor para o `KAMBA_FASE`: `piloto`. O `fluxo_piloto` do
#: KAM-003 escreve-o por extenso — «`piloto` e o unico valor que o canon define.
#: Ausente, vazia ou com outro valor, a guarda levanta — nao se desliga».
#:
#: A primeira versao desta validacao lia `env.fase != FASE_PILOTO` como «ja nao
#: e Piloto, logo o Fluxo B pode correr», e com isso um `KAMBA_FASE=clusters`
#: escrito por engano no *deploy* punha o `assistente` em producao — exactamente
#: o que o ADR-011 difere ate haver resposta escrita da Meta (D2). Inventar um
#: valor de fase e inventar canon.
#:
#: Quando a Fase C abrir, o valor dela entra aqui **e** no dicionario, por
#: emenda. Ate la, uma vertical `phase: D` nao arranca em ambiente nenhum.
FASES_POSTERIORES: Final[tuple[str, ...]] = ()


class PorLigar(str):
    """Um problema da classe «a fonte desta validacao nao existe aqui».

    E `str` para que nada mais no caminho precise de saber que existe: as
    validacoes devolvem `tuple[str, ...]` e o `carregar` junta-os como sempre. O
    que muda e que o `modo: aviso` do `registry/gates.yaml` **so** cala estes —
    ver a *docstring* do modulo.

    Subclasse de `str` e nao um `dataclass` com um campo `adiavel`: a alternativa
    obrigava as seis validacoes, o `carregar` e os testes a mudar de tipo para
    distinguir duas classes de problema, e isto distingue-as com `isinstance`.
    """


@runtime_checkable
class CatalogoDeTools(Protocol):
    """O que o registo precisa de saber do catalogo da ToolLayer (KAM-028).

    Duas perguntas, e nada mais: que tools existem, e que parametros de uma
    delas sao visiveis ao modelo. Nao e o contrato da TLS — e a fatia dele de
    que a validacao (1) depende, declarada aqui para que o KAM-028 saiba o que
    tem de satisfazer.
    """

    def nomes(self) -> frozenset[str]:
        """Os nomes das tools do catalogo."""
        ...

    def parametros_visiveis(self, tool: str) -> frozenset[str]:
        """Os parametros do esquema que o modelo ve, para uma tool do catalogo."""
        ...


@runtime_checkable
class GrafoCompilado(Protocol):
    """O que a validacao (3) le de um grafo compilado: os nomes dos nos.

    E o `nodes` de um `CompiledStateGraph` do LangGraph. Le-se por `Protocol` e
    nao por `isinstance` da classe concreta porque e so isto que a validacao
    precisa, e porque um grafo de teste tem de poder ser um grafo de teste.
    """

    nodes: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class AmbienteDoRegisto:
    """O `env` de `load_all(env)` (§5.2): as fontes contra as quais se valida.

    Os dois campos que podem ser `None` sao os que **nao tem fonte no
    repositorio**. `None` nao significa «salta»: significa «a validacao devolve
    o problema de a fonte nao existir», e quem decide se isso bloqueia e o
    `registry/gates.yaml`.
    """

    #: O valor de `KAMBA_FASE`. `None` quando a variavel nao esta definida — e
    #: isso **nao** e «nao e piloto»: ver `validar_fase`.
    fase: str | None
    #: As chaves de `entitlements.limites` que o TEN conhece.
    chaves_de_limite: frozenset[str]
    #: `tipo -> versoes publicadas`, do catalogo de eventos.
    eventos: Mapping[str, frozenset[int]]
    #: A raiz contra a qual se resolve o caminho de um *dataset* golden.
    raiz: Path
    #: O catalogo da ToolLayer. `None` ate KAM-028.
    catalogo: CatalogoDeTools | None = None
    #: Como se compila o grafo de uma vertical. `None` ate KAM-031/035.
    construir_grafo: Callable[[VerticalDoRegisto], GrafoCompilado] | None = None

    @classmethod
    def do_repositorio(
        cls, raiz: Path, ambiente: Mapping[str, str] | None = None
    ) -> "AmbienteDoRegisto":
        """O ambiente real, com as tres fontes que existem hoje.

        As importacoes sao locais de proposito: o `kamba_core.eventos.contratos`
        tem 700 linhas de `TypedDict` e o catalogo inteiro, e nao se paga isso
        ao importar o esquema do registo.
        """
        import os

        from kamba_core.eventos.contratos import CATALOGO
        from kamba_core.ten import CHAVES_DE_LIMITE

        alvo = os.environ if ambiente is None else ambiente
        return cls(
            fase=alvo.get(VARIAVEL_DE_FASE),
            chaves_de_limite=frozenset(CHAVES_DE_LIMITE),
            eventos={
                tipo: frozenset(entrada["versoes"]) for tipo, entrada in CATALOGO.items()
            },
            raiz=raiz,
        )


def validar_tools(vertical: VerticalDoRegisto, env: AmbienteDoRegisto) -> tuple[str, ...]:
    """Validacao (1): as tools existem e nenhuma expoe parametro proibido."""
    if env.catalogo is None:
        return (
            PorLigar(
                "o catalogo da ToolLayer nao esta ligado, pelo que nao se confirma que as "
                f"{len(vertical.tools)} tools de `{vertical.id}` existem nem que nenhuma expoe "
                f"{list(PARAMETROS_PROIBIDOS)} ao modelo"
            ),
        )
    problemas: list[str] = []
    conhecidas = env.catalogo.nomes()
    for tool in vertical.tools:
        if tool not in conhecidas:
            problemas.append(f"a tool `{tool}` nao existe no catalogo da ToolLayer")
            continue
        expostos = sorted(env.catalogo.parametros_visiveis(tool) & set(PARAMETROS_PROIBIDOS))
        if expostos:
            problemas.append(
                f"a tool `{tool}` expoe {expostos} no esquema visivel ao modelo; o modelo "
                "nunca ve nem fornece estes parametros (`docs/tecnica/02` §6.1, ADR-015)"
            )
    return tuple(problemas)


def validar_entitlements(
    vertical: VerticalDoRegisto, env: AmbienteDoRegisto
) -> tuple[str, ...]:
    """Validacao (2): as chaves de `entitlements.limites` existem no TEN.

    Uma chave que o TEN nao conhece e um tecto que nao existe, e o
    `platform.ten_consumir` nega quando nenhum entitlement activo a declara. O
    efeito de a deixar passar aqui era descobri-la no dia em que um tenant
    batesse num limite que ninguem definiu.
    """
    fora = [
        chave for chave in vertical.entitlements.limites if chave not in env.chaves_de_limite
    ]
    if not fora:
        return ()
    return (
        f"as chaves de limite {sorted(fora)} nao existem no TEN; as que existem sao "
        f"{sorted(env.chaves_de_limite)} (dicionario §3.2, «Entitlement (chaves)»; "
        "`registry/entitlement_keys.schema.json`)",
    )


def nos_do_grafo(grafo: GrafoCompilado) -> frozenset[str]:
    """Os nos de um grafo compilado, sem os sentinelas do LangGraph.

    O `CompiledStateGraph.nodes` traz tambem `__start__` (e, em algumas
    versoes, `__end__`), que sao a entrada e a saida e nao nos de desenho.
    Filtram-se por prefixo e nao por lista, para que uma versao que acrescente
    outro sentinela nao passe a contar como no.
    """
    return frozenset(nome for nome in grafo.nodes if not nome.startswith("__"))


def validar_grafo(vertical: VerticalDoRegisto, env: AmbienteDoRegisto) -> tuple[str, ...]:
    """Validacao (3): o grafo compilado tem os seis nos obrigatorios."""
    if env.construir_grafo is None:
        return (
            PorLigar(
                f"nao ha como compilar o grafo de `{vertical.id}` (`{vertical.graph}`), pelo "
                f"que nao se confirma que ele tem os nos {list(NOS_OBRIGATORIOS)}"
            ),
        )
    try:
        grafo = env.construir_grafo(vertical)
    except Exception as excepcao:  # noqa: BLE001 — qualquer falha e um registo invalido
        return (
            f"o grafo de `{vertical.id}` nao compila: {type(excepcao).__name__} "
            f"({excepcao})",
        )
    em_falta = sorted(set(NOS_OBRIGATORIOS) - nos_do_grafo(grafo))
    if not em_falta:
        return ()
    return (
        f"ao grafo de `{vertical.id}` faltam os nos obrigatorios {em_falta} "
        "(`docs/tecnica/02` §5.2 validacao 3)",
    )


def validar_subscriptions(
    vertical: VerticalDoRegisto, env: AmbienteDoRegisto
) -> tuple[str, ...]:
    """Validacao (4): cada subscricao refere tipo e versao conhecidos.

    «Versoes desconhecidas falham de forma visivel, nunca ignoradas em
    silencio» (dicionario §3.5, e `specs/01` §5). Um consumidor que subscreve
    uma versao que nao existe nunca recebe nada, e um que nao valida a versao
    recebe um envelope cujo payload nao sabe ler.
    """
    problemas: list[str] = []
    for subscricao in vertical.subscriptions:
        versoes = env.eventos.get(subscricao.tipo)
        if versoes is None:
            problemas.append(
                f"`{subscricao.tipo}` nao tem contrato em `contratos/eventos/`"
            )
        elif subscricao.versao not in versoes:
            problemas.append(
                f"`{subscricao.tipo}` v{subscricao.versao}: as versoes publicadas sao "
                + ", ".join(f"v{v}" for v in sorted(versoes))
            )
    return tuple(problemas)


def validar_fase(vertical: VerticalDoRegisto, env: AmbienteDoRegisto) -> tuple[str, ...]:
    """Validacao (5): `phase: D` e rejeitada com `KAMBA_FASE=piloto` (ADR-011).

    **A variavel ausente ou vazia nao e um passe.** O `fluxo_piloto` do KAM-003
    ja escreveu a razao por extenso: `piloto` e o unico valor que o canon
    define, e «ausente, vazia ou com outro valor, a guarda levanta — nao se
    desliga». Aqui isso traduz-se em so deixar passar uma vertical diferida
    quando a variavel traz um valor **nao vazio** que nao e `piloto`. Sem isto,
    um `KAMBA_FASE` esquecido no *deploy* punha o `assistente` do Fluxo B em
    producao, que e exactamente o que o ADR-011 difere.
    """
    if vertical.phase != "D":
        return ()
    if env.fase in FASES_POSTERIORES:
        return ()
    if env.fase == FASE_PILOTO:
        como = f"{VARIAVEL_DE_FASE}={FASE_PILOTO}"
    elif env.fase:
        como = (
            f"{VARIAVEL_DE_FASE}={env.fase!r}, que nao e uma fase que o canon defina "
            f"(as posteriores ao Piloto sao {list(FASES_POSTERIORES)})"
        )
    else:
        como = f"{VARIAVEL_DE_FASE} ausente ou vazia"
    return (
        f"`{vertical.id}` tem `phase: D` e {como}: o ADR-011 difere o Fluxo B ate resposta "
        "escrita da Meta (D2), e uma vertical diferida nao entra em producao",
    )


def validar_golden(
    vertical: VerticalDoRegisto, env: AmbienteDoRegisto
) -> tuple[str, ...]:
    """Validacao (6): o *dataset* golden existe e o gate da versao esta verde.

    As duas metades, e so a primeira se mede hoje: o caminho existe no disco. O
    «gate verde» e o eval harness do KAM-040, e a ausencia dele devolve-se como
    problema — nao como silencio.
    """
    problemas: list[str] = []
    caminho = env.raiz / vertical.golden.dataset
    if not caminho.is_dir():
        # **`PorLigar` e nao problema real**, e a razao e de propriedade: o
        # dataset nao e configuracao nossa — e o artefacto que o KAM-040
        # entrega. A sua ausencia e «o credor ainda nao entregou», que e
        # exactamente a classe que o `aviso` pode calar. No dia em que ele
        # existir, um caminho **errado** no YAML ja e problema real: o
        # directorio existe e o que esta escrito aponta para outro.
        problemas.append(
            PorLigar(
                f"o dataset golden `{vertical.golden.dataset}` de `{vertical.id}` nao existe"
            )
        )
    # shortcut: a segunda metade do §5.2 (6) — «o gate da versao esta verde» —
    # nao se mede, e devolve-se sempre como problema em vez de se omitir; revê-se
    # quando o KAM-040 entregar o eval harness, e nesse dia esta linha sai daqui
    # **e** a linha `golden` sai de `registry/gates.yaml`.
    problemas.append(
        PorLigar(
            f"nao ha eval harness que diga se o gate golden de `{vertical.id}` "
            f"v{vertical.version} esta verde"
        )
    )
    return tuple(problemas)


#: As seis, por nome, pela ordem do §5.2. A chave e a que o
#: `registry/gates.yaml` usa, e e a mesma lista fechada que o *gate* 3b impõe
#: ao ficheiro — ha um teste que confronta as duas.
VALIDACOES: Final[Mapping[str, Callable[[VerticalDoRegisto, AmbienteDoRegisto], tuple[str, ...]]]] = {
    "tools": validar_tools,
    "entitlements": validar_entitlements,
    "grafo": validar_grafo,
    "subscriptions": validar_subscriptions,
    "fase": validar_fase,
    "golden": validar_golden,
}
