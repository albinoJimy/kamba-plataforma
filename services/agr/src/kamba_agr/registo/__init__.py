"""O `AgentRegistry`: verticais como configuracao (ADR-012, KAM-027).

    AgentRegistry.load_all(env)   valida e registra; falha o arranque se invalido
    AgentRegistry.resolve(ctx)    a vertical, por `ctx.vertical` + entitlement activo

E o contrato de `docs/tecnica/02` §5.2, e o ADR-012 diz o que ele e: uma
vertical e um tuplo de configuracao `(grafo, tools autorizadas, persona,
entitlements, subscricoes)`, e nao codigo. O que este modulo faz e ler esse
tuplo de `registry/*.yaml`, recusa-lo quando esta errado, e devolve-lo a quem
corre um turno.

## Porque e que vive aqui e nao em `libs/py-core`

A mesma razao que o `estado.py` do KAM-025 escreveu na sua *docstring*:
`libs/py-core` e o que **todos** os servicos Python precisam de fazer igual, e
o AGR e o unico que constroi e le isto. O bloco do ticket propoe
`kamba/registry/{loader,schema,validate,resolve}.py`, um caminho que nao existe
neste repositorio; o que fica e `kamba_agr/registo/`, com tres modulos em vez
de quatro — o `loader` sao as quatro funcoes de leitura de `esquema.py`, e um
ficheiro de quarenta linhas para as separar do modelo que elas devolvem nao
paga a navegacao.

## O arranque, e o que ele NAO liga

O `load_all` corre no arranque (`__main__.py`) e falha-o com o codigo **5**. O
que ele nao faz e substituir o `sem_grafos` que o KAM-025 deixou em
`turno.py`, e isso e deliberado: o `graph` das duas verticais aponta para
`kamba_agr.verticais.<id>:build_graph`, que o KAM-031 e o KAM-035 escrevem.
Ligar a porta hoje trocava um 503 por outro 503 e punha uma leitura de
entitlement no caminho de cada turno, para nada. O `resolve` e a costura, e
quem a usa e o ticket que tiver um grafo para lhe dar.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from .esquema import (
    FicheiroIlegivelError,
    GateDaVertical,
    RegistoDeGates,
    VerticalDoRegisto,
    ler_gates,
    ler_vertical,
    ler_yaml,
)
from .validar import (
    FASES_POSTERIORES,
    NOS_OBRIGATORIOS,
    PARAMETROS_PROIBIDOS,
    VALIDACOES,
    AmbienteDoRegisto,
    CatalogoDeTools,
    GrafoCompilado,
    PorLigar,
    nos_do_grafo,
)

__all__ = [
    "AgentRegistry",
    "Adiada",
    "AmbienteDoRegisto",
    "CatalogoDeTools",
    "FASES_POSTERIORES",
    "DIRECTORIO_POR_OMISSAO",
    "FicheiroIlegivelError",
    "GrafoCompilado",
    "METRICA_REGISTO_NEGADO",
    "MOTIVOS_DE_NEGACAO",
    "NOS_OBRIGATORIOS",
    "PARAMETROS_PROIBIDOS",
    "PorLigar",
    "RESPOSTA_SEM_ENTITLEMENT",
    "RegistoInvalidoError",
    "Resolucao",
    "VARIAVEL_DO_DIRECTORIO",
    "VerticalDoRegisto",
    "carregar",
    "directorio_do_registo",
    "nos_do_grafo",
]

#: A variavel que diz onde vivem os ficheiros do registo, e a omissao.
#:
#: Relativa ao directorio de trabalho do processo, que no contentor e `/app` —
#: e e por isso que o `Dockerfile` do AGR passou a ter um `COPY registry`. E o
#: primeiro ficheiro do repositorio que um servico deste conjunto le em
#: execucao, e isso e uma consequencia do ADR-012: uma vertical e configuracao,
#: logo tem de chegar ao processo como configuracao.
VARIAVEL_DO_DIRECTORIO: Final = "KAMBA_REGISTRY_DIR"
DIRECTORIO_POR_OMISSAO: Final = "registry"

#: O identificador da resposta estatica do critero 6 — nao o texto.
#:
#: O texto ao cliente e portugues de Angola e vive no `compose` (KAM-033). O que
#: cabe num `error_code` da *allowlist* de `docs/tecnica/08` §7.3 e um
#: identificador, e e por ele que um painel conta.
RESPOSTA_SEM_ENTITLEMENT: Final = "servico_indisponivel"

#: O nome da metrica e os dois motivos vem de `metricas.py`, **que e quem os
#: tem de conhecer**: o `MetricasDoAgr.contar` levanta `EtiquetaInvalida`
#: («contador desconhecido») para uma metrica que nao esteja registada la, e
#: foi assim que se descobriu que faltava — o `resolve` contava contra um duplo
#: nos testes e teria rebentado no primeiro turno em producao. Redeclara-los
#: aqui era a mesma lista em dois sitios, e um deles a divergir.
from ..metricas import METRICA_REGISTO_NEGADO, MOTIVOS_DE_NEGACAO  # noqa: E402

#: A chave de topo de cada forma da superficie `registry/*.yaml`. A da vertical
#: e a dos gates leem-se aqui; a dos planos (KAM-009) **salta-se** — e o
#: provisionamento que a le, e o AGR nao provisiona tenants.
_CHAVE_DA_VERTICAL: Final = "id"
_CHAVE_DOS_GATES: Final = "gates"
_CHAVE_DOS_PLANOS: Final = "plans"


@dataclass(frozen=True, slots=True)
class Adiada:
    """Uma validacao que corre em modo `aviso`, e o ticket que a fecha.

    **Nao leva o texto do problema, e isso e uma correccao.** A primeira versao
    devolvia a prosa e o `__main__` punha-a em `error_code` — onde a *allowlist*
    de `docs/tecnica/08` §7.3 a **deixava cair em silencio**, porque aquele campo
    e um identificador de 96 caracteres e nao uma frase. O resultado era um
    arranque que dizia ter registado os avisos e nao registava nenhum: a propria
    coisa que o critero 8 existe para evitar. Um teste apanhou-o.

    O que fica sao os tres campos que cabem: a validacao, a vertical, e o
    credor — e `codigo()` monta deles o identificador que a *allowlist* aceita.
    O «porque» nao se perde: e o que o `registry/gates.yaml` escreve, ao lado
    de cada linha.
    """

    validacao: str
    vertical: str
    credor: str

    def codigo(self) -> str:
        """`tools_kam_028` — a forma de `error_code` da *allowlist*.

        Minusculas e `_`: o `_CODIGO` de `kamba_core.logger.politica` nao admite
        o `-` do `KAM-028`. Nao leva a vertical porque o par
        (validacao, credor) ja identifica o que um painel precisa de contar, e
        porque e o par que distingue o `grafo` do Vendedor (KAM-031) do de
        Servicos (KAM-035).
        """
        return f"{self.validacao}_{self.credor.lower().replace('-', '_')}"


class RegistoInvalidoError(RuntimeError):
    """O registo nao passa as validacoes de arranque. O AGR sai com `5`.

    A mensagem junta **todos** os problemas de validacao e nao o primeiro: quem
    corrige um ficheiro de configuracao quer a lista, e um arranque que falha
    seis vezes seguidas por seis linhas erradas e seis *deploys*. Os textos vem
    deste codigo e dos nossos proprios ficheiros — nao ha conteudo de ninguem.

    **O limite, porque a promessa acima nao e absoluta:** um ficheiro que nao se
    **le** aborta antes da lista, com `FicheiroIlegivelError`. E deliberado —
    nao se validam seis coisas sobre um YAML que nao se conseguiu abrir — mas
    quer dizer que um registo com dois ficheiros, um ilegivel e outro invalido,
    reporta so o primeiro. Dois *deploys* no pior caso, e nao seis.
    """


@dataclass(frozen=True, slots=True)
class Resolucao:
    """O que `resolve` devolve: a vertical, **ou** a recusa e o seu motivo.

    O §5.2 escreve `resolve(ctx) -> Vertical`, e o critero 6 pede mais do que
    isso: «sem entitlement activo devolve a resposta estatica "servico
    indisponivel" e emite alerta». Um `Vertical` nao tem onde levar essa
    resposta, e levantar uma excepcao punha o caminho normal de um tenant sem
    plano a passar por um `except` — que e como uma recusa prevista deixa de se
    distinguir de um defeito. Exactamente um dos dois lados vem preenchido.
    """

    vertical: VerticalDoRegisto | None
    resposta: str | None = None
    motivo: str | None = None


class ContextoDeResolucao(Protocol):
    """O que `resolve` le do contexto: o tenant e a vertical, e nada mais.

    O §5.2 chama-lhe `ChannelContext`, que e o contrato do CHR; o que chega ao
    AGR e uma `InvocacaoDoAgente` (`contexto.py`). As duas satisfazem isto
    estruturalmente, e e isso que se pede — o registo nao tem de importar
    nenhuma delas.

    **Os dois campos vem do contexto validado e nunca do texto.** E a invariante
    do `contexto.py` do KAM-025 e do ADR-015: o `tenant_id` e injectado pelo CHR
    e e imutavel, e um `tenant_id` que venha de um campo do corpo e a injeccao
    que o `test_isolamento.py` mede.
    """

    tenant_id: str
    vertical: str


class _Entitlement(Protocol):
    """A fatia de `kamba_core.ten.Entitlement` de que o `resolve` depende."""

    permitido: bool


class _Metricas(Protocol):
    def contar(self, metrica: str, etiqueta: str | None = None, quanto: int = 1) -> None: ...


def directorio_do_registo(ambiente: Mapping[str, str] | None = None) -> Path:
    """O directorio dos ficheiros do registo, do ambiente ou da omissao."""
    alvo = os.environ if ambiente is None else ambiente
    return Path(alvo.get(VARIAVEL_DO_DIRECTORIO) or DIRECTORIO_POR_OMISSAO)


class AgentRegistry:
    """O registo das verticais: carrega, valida, resolve.

    Constroi-se vazio e enche-se no `load_all`. Um `resolve` antes do
    `load_all` levanta, e nao devolve «nao ha vertical»: a diferenca entre «este
    tenant nao tem a vertical» e «ninguem carregou o registo» e a diferenca
    entre uma recusa correcta e um servico a responder como se estivesse pronto.
    """

    def __init__(
        self,
        ler_entitlement: Callable[[str, str], _Entitlement],
        metricas: _Metricas | None = None,
    ) -> None:
        self._ler_entitlement = ler_entitlement
        self._metricas = metricas
        self._verticais: dict[str, VerticalDoRegisto] = {}
        self._carregado = False

    @property
    def verticais(self) -> Mapping[str, VerticalDoRegisto]:
        return dict(self._verticais)

    # ------------------------------------------------------------------ arranque

    def load_all(
        self, env: AmbienteDoRegisto, directorio: Path | None = None
    ) -> tuple[Adiada, ...]:
        """Le `registry/*.yaml`, corre as seis validacoes, e falha se alguma bloquear.

        **Devolve os avisos** em vez do `None` que o esboco do §5.2 escreve. Nao
        e alargamento do contrato: as validacoes em modo `aviso` tem de aparecer
        no registo de arranque, senao o `registry/gates.yaml` e uma lista que
        ninguem le e as tres validacoes adiadas ficam adiadas em silencio — que e
        o defeito que o critero 8 existe para fechar. Quem ignora o valor
        devolvido tem exactamente o comportamento do esboco.

        Levanta `RegistoInvalidoError` ou `FicheiroIlegivelError`; as duas levam
        ao codigo de saida 5.
        """
        self._verticais, _, adiadas = carregar(env, directorio)
        self._carregado = True
        return adiadas

    # ------------------------------------------------------------------ resolucao

    def resolve(self, ctx: ContextoDeResolucao) -> Resolucao:
        """A vertical de `ctx`, se o tenant tiver o entitlement activo.

        **Uma so vertical principal por numero no Piloto** (§5.2, «Activacao por
        tenant»): o que decide e o `ctx.vertical`, que o CHR resolveu do canal.
        Nao ha agregacao nem *front-door router* — isso e Fase C, e um registo
        que escolhesse entre duas verticais para o mesmo numero estaria a
        implementa-lo por acidente.
        """
        if not self._carregado:
            raise RegistoInvalidoError(
                "`resolve` antes de `load_all`: o registo esta vazio. Um AGR que resolvesse "
                "aqui estaria a responder como se estivesse pronto"
            )
        vertical = self._verticais.get(ctx.vertical)
        if vertical is None:
            return self._negar("vertical_desconhecida")
        entitlement = self._ler_entitlement(ctx.tenant_id, vertical.entitlements.modulo)
        if not entitlement.permitido:
            return self._negar("sem_entitlement")
        return Resolucao(vertical=vertical)

    def _negar(self, motivo: str) -> Resolucao:
        """A recusa, com o alerta. O `motivo` e etiqueta: lista fechada.

        O `tenant_id` **nao** entra na metrica (`OBS-I`), e nao e por omissao:
        a gramatica de etiqueta de `metricas.py` recusa-o pela forma, e um
        painel que precise de saber qual o tenant le o registo, onde o
        `tenant_id` esta na *allowlist* de `docs/tecnica/08` §7.3.
        """
        # Sem `assert` aqui: ele desaparece com `python -O`, e quem impoe a
        # lista fechada e o `MetricasDoAgr.contar`, que **levanta** para uma
        # etiqueta fora dela. Duas barreiras eram uma a mais, e a que ficava
        # era a que o interprete pode apagar.
        if self._metricas is not None:
            self._metricas.contar(METRICA_REGISTO_NEGADO, motivo)
        return Resolucao(vertical=None, resposta=RESPOSTA_SEM_ENTITLEMENT, motivo=motivo)


def carregar(
    env: AmbienteDoRegisto, directorio: Path | None = None
) -> tuple[dict[str, VerticalDoRegisto], dict[str, GateDaVertical], tuple[Adiada, ...]]:
    """O carregamento e as seis validacoes, sem precisar de resolver nada.

    **E funcao e nao so metodo** porque o arranque precisa das duas coisas
    separadas: validar o registo (criterio 1) nao depende de saber ler
    entitlements, e `resolve` depende. O `__main__.py` chama isto; quem resolve
    constroi um `AgentRegistry` e chama `load_all`, que e esta funcao mais o
    estado.

    Levanta `RegistoInvalidoError` (problemas bloqueantes) ou
    `FicheiroIlegivelError` (nao se le o ficheiro). As duas saem com 5.
    """
    pasta = directorio if directorio is not None else directorio_do_registo()
    if not pasta.is_dir():
        raise RegistoInvalidoError(
            f"o directorio do registo `{pasta}` nao existe "
            f"({VARIAVEL_DO_DIRECTORIO}, omissao `{DIRECTORIO_POR_OMISSAO}`)"
        )

    verticais, gates, erros = _ler_pasta(pasta)
    erros.extend(_coerencia(verticais, gates))
    adiadas: list[Adiada] = []
    for identificador, vertical in sorted(verticais.items()):
        gate = gates.get(identificador)
        for nome, validar in VALIDACOES.items():
            modo = gate.validacoes.get(nome) if gate is not None else None
            em_aviso = modo is not None and modo.modo == "aviso"
            problemas = validar(vertical, env)
            # **O `aviso` cala uma classe de problema, nao a validacao.** Um
            # `PorLigar` diz «a fonte desta validacao nao existe aqui»; qualquer
            # outro problema diz «confrontei e esta errado», e esse bloqueia
            # seja qual for o modo. Sem esta linha, no dia em que o KAM-028
            # ligasse o catalogo uma tool a expor `tenant_id` ao modelo passava
            # a ser aviso, porque a linha do `gates.yaml` sobreviveria ao credor.
            # Achado da revisao adversarial.
            por_ligar = [p for p in problemas if isinstance(p, PorLigar)]
            reais = [p for p in problemas if not isinstance(p, PorLigar)]
            erros.extend(f"[{nome}/{identificador}] {problema}" for problema in reais)
            if not em_aviso:
                erros.extend(f"[{nome}/{identificador}] {problema}" for problema in por_ligar)
                continue
            if not por_ligar:
                # **Um `aviso` que sobreviveu ao credor.** A fonte ja existe, a
                # linha do `gates.yaml` esta morta, e e isso que torna
                # verdadeira a frase «fechar um aviso e apagar uma linha»: sem
                # este erro, a linha ficava a adiar o que ja nao e adiavel. E a
                # disciplina do `canon/extensoes.yaml` — uma declaracao que
                # nenhuma superficie usa falha o gate.
                erros.append(
                    f"[{nome}/{identificador}] a linha `{nome}: {{ modo: aviso, credor: "
                    f"{modo.credor} }}` de `registry/gates.yaml` sobreviveu ao credor: a "
                    "fonte desta validacao ja existe, pelo que o adiamento esta morto. "
                    "Apague a linha — `bloqueio` e a omissao"
                )
                continue
            # Uma entrada por validacao adiada e nao uma por problema: o
            # `golden` devolve dois (o dataset e o harness) e sao a mesma
            # espera, pelo mesmo ticket.
            adiadas.append(Adiada(nome, identificador, modo.credor))

    if erros:
        raise RegistoInvalidoError(
            f"{len(erros)} problema(s) no registo de `{pasta}`: " + "; ".join(erros)
        )
    return verticais, gates, tuple(adiadas)


def _ler_pasta(
    pasta: Path,
) -> tuple[dict[str, VerticalDoRegisto], dict[str, GateDaVertical], list[str]]:
    """As verticais e os gates de uma pasta, pela **chave de topo**.

    Pela chave de topo e nunca pelo nome do ficheiro, que e a regra que o
    *gate* 3b ja segue: um `planos.yaml` ou um `tarifas.yaml` sao o mesmo
    ficheiro, e adivinhar pelo nome punha o arranque a depender de como alguem
    lhe chamou.
    """
    verticais: dict[str, VerticalDoRegisto] = {}
    gates: dict[str, GateDaVertical] = {}
    erros: list[str] = []
    registos: list[RegistoDeGates] = []
    for caminho in sorted(pasta.glob("*.yaml")):
        documento = ler_yaml(caminho)
        declaradas = [
            chave
            for chave in (_CHAVE_DA_VERTICAL, _CHAVE_DOS_GATES, _CHAVE_DOS_PLANOS)
            if chave in documento
        ]
        if len(declaradas) != 1:
            erros.append(
                f"`{caminho.name}` declara {declaradas or 'nenhuma'} das chaves de forma "
                f"(`{_CHAVE_DA_VERTICAL}`, `{_CHAVE_DOS_GATES}`, `{_CHAVE_DOS_PLANOS}`): "
                "um ficheiro do registo e exactamente uma das tres formas"
            )
            continue
        if declaradas == [_CHAVE_DOS_PLANOS]:
            continue  # KAM-009: quem le os planos e o provisionamento.
        if declaradas == [_CHAVE_DOS_GATES]:
            registos.append(ler_gates(caminho, documento))
            continue
        vertical = ler_vertical(caminho, documento)
        if vertical.id in verticais:
            erros.append(
                f"a vertical `{vertical.id}` esta declarada mais do que uma vez em "
                f"`{pasta}`: duas configuracoes para o mesmo `id` e uma que ganha por "
                "ordem alfabetica"
            )
            continue
        verticais[vertical.id] = vertical

    for registo in registos:
        for identificador, gate in registo.gates.items():
            if identificador in gates:
                erros.append(
                    f"o gate de `{identificador}` esta declarado mais do que uma vez"
                )
                continue
            gates[identificador] = gate
    if not verticais:
        erros.append(
            f"`{pasta}` nao tem vertical nenhuma; um registo vazio e um AGR que resolve "
            "zero conversas e nao diz porque"
        )
    return verticais, gates, erros


def _coerencia(
    verticais: Mapping[str, VerticalDoRegisto], gates: Mapping[str, GateDaVertical]
) -> list[str]:
    """O que se exige **entre** os ficheiros, e que bloqueia sempre.

    Nao sao validacoes do §5.2 e por isso nao tem modo: sao invariantes deste
    ticket, e um `aviso` sobre elas nao faria sentido nenhum — o que elas
    apanham e configuracao que se contradiz, nao uma fonte que falta.
    """
    problemas: list[str] = []
    for identificador, gate in sorted(gates.items()):
        vertical = verticais.get(identificador)
        if vertical is None:
            problemas.append(
                f"ha um gate para `{identificador}` e nao ha vertical com esse `id`: um gate "
                "orfao e um modo de validacao que nunca se aplica"
            )
        elif gate.golden != vertical.golden.dataset:
            problemas.append(
                f"o dataset golden de `{identificador}` nao coincide: a vertical diz "
                f"`{vertical.golden.dataset}` e o gate diz `{gate.golden}`"
            )
    return problemas
