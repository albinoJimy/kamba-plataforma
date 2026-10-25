"""A forma de um ficheiro de `registry/`, em Pydantic com `extra="forbid"`.

As duas formas que este modulo le sao a **vertical** (`docs/tecnica/02` §5.1) e
os **gates** (`registry/gates.yaml`, critero 8 do KAM-027). A terceira forma da
superficie — os planos do KAM-009 — nao se le aqui: o AGR nao provisiona
tenants, e um modelo para um ficheiro que este servico nunca abre era codigo sem
chamador.

## Porque e que o Pydantic esta aqui, depois de o ADR-L001 o ter recusado

O [`ADR-L001`](../../../../../docs/adr/ADR-L001-toolchain.md) §4 escolheu
Starlette e nao FastAPI «porque o FastAPI traria o Pydantic para validar um
corpo de pedido que nao existe, e o Pydantic e uma dependencia compilada a fixar
com *hash* por plataforma». A razao era o **custo de o acrescentar**, e esse
custo desapareceu: o KAM-026 trouxe o `langgraph-checkpoint`, cujo fecho inclui
`pydantic==2.14.1` e `PyYAML==6.0.3`. O `requirements/runtime.in` registou-o — o
fecho passou de 12 para 43 pacotes.

O mesmo ADR escreve o gatilho de reversao por extenso: «quando o AGR tiver uma
API interna com corpo validado — o `/internal/turn` do EPIC-03 e o candidato».
Nao se contradiz nada em silencio: a razao do ADR deixou de valer porque a
dependencia ja esta paga, e o gatilho que ele proprio nomeou chegou.

**O `extra="forbid"` nao e cosmetica**, e e o que os *Detalhes Tecnicos* do
bloco pedem. Um `subscricoes:` escrito em vez de `subscriptions:` com um modelo
permissivo dava uma vertical sem subscricao nenhuma, validada com sucesso: a
validacao (4) do §5.2 passava por nao ter nada para rejeitar. E a mesma razao
pela qual o *gate* 3b tem a lista fechada de chaves de topo — duas barreiras
para o mesmo defeito, de proposito, porque uma delas corre no CI e a outra no
processo que serve clientes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

#: SemVer de um artefacto comportamental (`specs/01` §5). Sem pre-release nem
#: metadados de *build*: um `1.0.0-rc1` num registo de vertical e uma versao que
#: o *gate* golden nao sabe comparar.
SEMVER: Final = re.compile(r"^\d+\.\d+\.\d+$")

#: A forma de um `id` de vertical, de um `modulo` e de uma chave de limite.
#: E o `CHECK` de forma do dicionario §3.2 — e **so** a forma: a lista fechada
#: de verticais e do dicionario e quem a impoe e o *gate* 3b. Um `Literal` com
#: `vendedor` e `servicos` aqui punha nomes de vertical no codigo do registo,
#: que e precisamente o que o teste de arquitectura do bloco proibe.
NOME_CANONICO: Final = re.compile(r"^[a-z][a-z0-9_]*$")

#: `modulo:funcao` — o alvo de `graph`. O §5.1 escreve-o com `:`, que e a
#: convencao de *entry point* do Python.
ALVO_DO_GRAFO: Final = re.compile(r"^[a-zA-Z_][\w.]*:[a-zA-Z_]\w*$")

#: Os nomes das seis validacoes de arranque do §5.2, pela ordem de la
#: (dicionario §3.26). Lista fechada, e e ela que o `registry/gates.yaml` pode
#: nomear: um `tool` escrito por `tools` desligava a validacao em silencio.
VALIDACOES: Final = ("tools", "entitlements", "grafo", "subscriptions", "fase", "golden")

Nome = Annotated[str, Field(pattern=NOME_CANONICO.pattern)]


class _Fechado(BaseModel):
    """`extra="forbid"` para todos os modelos deste ficheiro."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _exigir_semver(valor: str) -> str:
    """O SemVer de um artefacto comportamental. Usado nas **duas** formas.

    E funcao de modulo e nao um `field_validator` herdado: a primeira versao
    reaproveitava o validador da vertical com
    `field_validator("version")(VerticalDoRegisto._semver.__func__)`, que
    funciona e nao se le. Quem passar por aqui tem de poder ver, numa linha, que
    as duas formas exigem o mesmo.
    """
    if not SEMVER.match(valor):
        raise ValueError(
            f"`version` tem de ser SemVer MAJOR.MINOR.PATCH (recebido: {valor!r}). "
            "Um ficheiro de `registry/` e artefacto comportamental (`specs/01` §5)"
        )
    return valor


class Persona(_Fechado):
    """`persona` do §5.1. O `tom` e opcional: o `servicos.yaml` do §5.1 nao o tem."""

    nome: str
    idioma: str
    tom: str | None = None
    apresentacao: str


class EntitlementsDaVertical(_Fechado):
    """`entitlements` do §5.1: o modulo e os **nomes** das chaves de limite.

    Aqui `limites` e uma **lista de nomes** e nao um mapa: o valor por omissao
    de cada limite vive em `registry/plans.yaml` (KAM-009) e o valor efectivo
    em `platform.entitlements`. Uma vertical declara de que limites depende,
    nao quais sao.
    """

    modulo: Nome
    limites: tuple[Nome, ...] = ()


class Subscricao(_Fechado):
    """`subscriptions[]` do §5.1: um tipo de evento e a versao do envelope."""

    tipo: str
    versao: int = Field(ge=1)


class Modelos(_Fechado):
    """`models` do §5.1: os dois *alias* do proxy LiteLLM (ADR-005, KAM-030)."""

    router: str
    chat: str


class Guardrails(_Fechado):
    """`guardrails` do §5.1. Nenhum campo e obrigatorio: o `servicos.yaml` do
    §5.1 nao tem esta chave, e inventar-lhe gatilhos por simetria era escrever
    decisao que ninguem tomou."""

    dominio: str | None = None
    handoff_triggers: tuple[str, ...] = ()


class Golden(_Fechado):
    """`golden` do §5.1, com o caminho do *dataset*.

    O §5.1 tem aqui tambem um `gate: "gates/vendedor.yaml"`. O critero 8 do
    bloco manda o registo do modo em `registry/gates.yaml`, e e o bloco que
    prevalece (dicionario §3.26): o que fica aqui e o caminho, e o `load_all`
    exige que coincida com o que o `gates.yaml` declara.
    """

    dataset: str


class VerticalDoRegisto(_Fechado):
    """Um `registry/<id>.yaml` — o tuplo do ADR-012, validado.

    O ADR-012 define uma vertical como `(grafo, tools autorizadas, persona,
    entitlements, subscricoes)`, e esta classe e esse tuplo mais o que o §5.1
    lhe junta: a versao em SemVer, a fase, os *alias* de modelo, os *guardrails*
    e o *golden*.
    """

    id: Nome
    version: str
    phase: Literal["P", "C", "D"]
    persona: Persona
    graph: str = Field(pattern=ALVO_DO_GRAFO.pattern)
    tools: tuple[Nome, ...]
    entitlements: EntitlementsDaVertical
    subscriptions: tuple[Subscricao, ...] = ()
    models: Modelos
    guardrails: Guardrails | None = None
    golden: Golden

    _semver = field_validator("version")(_exigir_semver)

    @field_validator("tools")
    @classmethod
    def _tools_unicas(cls, valor: tuple[str, ...]) -> tuple[str, ...]:
        repetidas = sorted({t for t in valor if valor.count(t) > 1})
        if repetidas:
            raise ValueError(
                f"`tools` repete {repetidas}. A lista e o que a ToolLayer autoriza, e uma "
                "lista com repeticoes e uma lista que ninguem contou"
            )
        return valor


class ModoDaValidacao(_Fechado):
    """`validacoes.<nome>` de `registry/gates.yaml`: o modo e quem o fecha.

    `bloqueio` e a **omissao** e nao se escreve: uma validacao que o ficheiro
    nao nomeie falha fechada. So o `aviso` se declara, e so ele exige `credor` —
    um atalho sem o ticket que o fecha nao e atalho, e um `aviso` sem dono e uma
    validacao desligada para sempre com ar de temporaria.
    """

    modo: Literal["aviso", "bloqueio"]
    credor: str | None = None

    @field_validator("credor")
    @classmethod
    def _forma_do_ticket(cls, valor: str | None) -> str | None:
        if valor is not None and not re.match(r"^KAM-\d{3}$", valor):
            raise ValueError(f"`credor` tem de ser um ticket `KAM-NNN` (recebido: {valor!r})")
        return valor

    def model_post_init(self, _contexto: object) -> None:
        if self.modo == "aviso" and self.credor is None:
            raise ValueError(
                "`modo: aviso` sem `credor`: a validacao fica desligada e ninguem a volta a ligar"
            )
        if self.modo != "aviso" and self.credor is not None:
            raise ValueError(
                f"`credor: {self.credor}` com `modo: {self.modo}`: o credor e de quem espera"
            )


class GateDaVertical(_Fechado):
    """`gates.<vertical>` de `registry/gates.yaml`."""

    golden: str
    validacoes: dict[str, ModoDaValidacao]

    @field_validator("validacoes")
    @classmethod
    def _so_as_seis(cls, valor: dict[str, ModoDaValidacao]) -> dict[str, ModoDaValidacao]:
        if not valor:
            raise ValueError(
                "`validacoes` vazio: `bloqueio` e a omissao, pelo que quem nao tem nada a "
                "declarar nao escreve a vertical em `registry/gates.yaml`"
            )
        fora = sorted(set(valor) - set(VALIDACOES))
        if fora:
            raise ValueError(
                f"{fora} nao sao validacoes de arranque; as seis sao {list(VALIDACOES)} "
                "(`docs/tecnica/02` §5.2, dicionario §3.26)"
            )
        return valor


class RegistoDeGates(_Fechado):
    """O ficheiro `registry/gates.yaml` inteiro."""

    version: str
    gates: dict[str, GateDaVertical]

    _semver = field_validator("version")(_exigir_semver)


class FicheiroIlegivelError(ValueError):
    """O YAML nao se le, ou nao bate com a forma. O arranque falha.

    Distinta de `RegistoInvalidoError`: esta e «nao consigo ler o ficheiro», a
    outra e «li e esta errado». As duas falham o arranque com o mesmo codigo,
    mas no registo de arranque sao causas diferentes.
    """


def ler_yaml(caminho: Path) -> dict:
    """O documento de topo de um YAML, com `safe_load`.

    `safe_load` e nao `load`: um `!!python/object` num ficheiro de configuracao
    e execucao de codigo arbitrario no arranque de um servico que serve
    clientes. O `PyYAML` entra no fecho por transitividade do `langchain-core`
    (`requirements/runtime.in`) — nao e dependencia nova.
    """
    try:
        bruto = caminho.read_text(encoding="utf-8")
    except OSError as excepcao:
        raise FicheiroIlegivelError(f"{caminho.name}: nao se le ({excepcao.strerror})") from excepcao
    try:
        documento = yaml.safe_load(bruto)
    except yaml.YAMLError as excepcao:
        raise FicheiroIlegivelError(f"{caminho.name}: YAML invalido ({type(excepcao).__name__})") from excepcao
    if not isinstance(documento, dict):
        raise FicheiroIlegivelError(f"{caminho.name}: o topo do ficheiro nao e um mapa")
    return documento


def ler_vertical(caminho: Path, documento: dict | None = None) -> VerticalDoRegisto:
    """Uma vertical, validada contra o §5.1. Levanta `FicheiroIlegivelError`.

    O `documento` e o YAML **ja lido**, para quem o leu para descobrir a forma —
    e o caso do `_ler_pasta`, que precisa da chave de topo antes de saber que
    modelo aplicar. Sem este parametro cada ficheiro era aberto e desserializado
    duas vezes.
    """
    return _montar(VerticalDoRegisto, caminho, documento)


def ler_gates(caminho: Path, documento: dict | None = None) -> RegistoDeGates:
    """O `registry/gates.yaml`, validado. Levanta `FicheiroIlegivelError`."""
    return _montar(RegistoDeGates, caminho, documento)


def _montar(modelo, caminho: Path, documento: dict | None = None):
    if documento is None:
        documento = ler_yaml(caminho)
    try:
        return modelo.model_validate(documento)
    except ValidationError as excepcao:
        # Os `loc` e as mensagens do Pydantic sao do nosso proprio ficheiro de
        # configuracao, nao de conteudo de ninguem: cabem no registo. O que nao
        # cabe e o `input`, que o `errors(include_input=False)` deixa de fora
        # por precaucao — um ficheiro mal copiado pode trazer qualquer coisa.
        partes = [
            f"{'.'.join(str(p) for p in erro['loc']) or '<topo>'}: {erro['msg']}"
            for erro in excepcao.errors(include_input=False, include_url=False)
        ]
        raise FicheiroIlegivelError(f"{caminho.name}: " + "; ".join(partes)) from excepcao
