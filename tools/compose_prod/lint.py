"""O contrato do compose de producao do conjunto reduzido (KAM-076).

Verifica, por leitura, os criterios 1 a 5 e 8 do bloco KAM-076 — os que se
podem afirmar sobre um ficheiro. Os que exigem contentores a correr estao
noutro sitio, de proposito:

| Criterio | Onde se prova | Porque |
|---|---|---|
| 1 denylist, conjunto exacto | aqui | e uma propriedade do ficheiro |
| 2 imagens por digest | aqui, e `supply_chain imagens` | ver a nota abaixo |
| 3 redes isoladas, egress | aqui (a forma) e `compose_prod egress-dez` (o facto) | uma rota nao se le |
| 4 endurecimento e limites | aqui, e `supply_chain runtime` | ver a nota abaixo |
| 5 replicas, `/healthz`, portas | aqui | forma do ficheiro |
| 6 compatibilidade da fila | `docs/adr/ADR-L009-ensaio-da-valkey.md` | exige a fila a correr |
| 7 SeaweedFS (D6) | `docs/evidencia/KAM-076.md` §6 | a D6 esta aberta |
| 8 *flags* de licenca | aqui (Chatwoot, Langfuse) e `lint_arch medusa` (Medusa) | — |

## O QUE ESTE MODULO **NAO** VERIFICA, E JA ESTA VERIFICADO

Duas coisas do criterio 4 nao tem regra aqui, e a ausencia e deliberada:

* **`read_only: true`** — o `supply_chain runtime` ja o exige em **todos** os
  servicos de **todos** os compose do repositorio (`fs-so-de-leitura`), e com
  canario proprio. Repeti-lo aqui dava duas mensagens para o mesmo defeito e
  duas regras a divergir com o tempo.
* **imagem por `@sha256:` e no inventario** — o `supply_chain imagens` ja o
  exige em todo o repositorio, com o digest lido da fonte e a entrada morta
  tambem apanhada. A regra `imagem-por-etiqueta` daqui **existe mesmo assim**,
  e e a unica duplicacao consciente: o criterio 2 do KAM-076 pede «um teste de
  CI falha caso contrario» **sobre o ficheiro de producao**, e um gate que vive
  no varrimento do repositorio inteiro nao diz, quando falha, que foi o
  ficheiro de producao que o quebrou. A mensagem diferente e o que se ganha.

## A REGRA QUE NAO MORDE HOJE, E ESTA DITO

`admin-sem-vpn` (criterio 5: «Medusa admin e Grafana so por VPN») **ve zero
servicos**: nem o `medusa` nem o `grafana` estao no compose de producao — o
primeiro nao tem imagem publicada (KAM-042), os dois ultimos sao AGPL-3.0, que
o `ci/licenses.yaml` nega (KAM-080). E uma **sentinela**: fica verde sobre nada
e dispara no dia em que um deles nascer com `ports:`. Esta nomeada como tal na
verificacao dos criterios, e nao dada por cumprida — a forma e a mesma do
`_rotas_internas_do_com` em `tools/lint_arch/medusa.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file
from supply_chain import arvore_yaml
from supply_chain import compose as compose_mod

PROD = "infra/compose/docker-compose.prod.yml"
STAGING = "infra/compose/docker-compose.staging.yml"
MANIFESTO = "infra/compose/conjunto-reduzido.yaml"
ALLOWLIST = "infra/egress/proxy-saida.yaml"
ENVOY = "infra/compose/envoy/envoy.yaml"

#: As quatro redes do `docs/tecnica/09` §3.2 regra 2, e qual delas tem rota.
#: `edge` e a unica nao-interna: e a propriedade que faz o resto funcionar.
REDES = {"edge": False, "app": True, "data": True, "ops": True}

#: Os unicos servicos que podem estar em `edge`. Um servico de aplicacao aqui
#: era um caminho para fora que ninguem registava.
SO_EM_EDGE = frozenset({"proxy-tls", "proxy-saida"})

#: Servicos de dados: estao **so** em `data`. Nao e o mesmo que estar em `data`
#: — o `gwy` tambem esta, e deve estar.
SO_EM_DATA = frozenset({"postgres", "queue", "seaweedfs"})

#: Criterio 5: duas replicas e `/healthz`. O bloco diz «GWY e *workers* AGR».
DUAS_REPLICAS = frozenset({"gwy", "agr"})

#: O unico servico que publica porta, e a unica porta. O WireGuard corre no
#: *host* (KAM-075) e nao em contentor.
QUEM_PUBLICA = {"proxy-tls": {"443"}}

#: Criterio 5, sentinela: admin que so se alcanca por VPN nao publica porta.
SO_POR_VPN = frozenset({"medusa", "grafana"})

#: Criterio 2: o perfil que **so** existe em *staging*. O Langfuse v4 corre la
#: com dados sinteticos (ADR-018) e nunca em producao.
PERFIL_OBS = "staging-obs"

#: As capacidades que cada servico pode acrescentar, por nome. Toda a pilha
#: corre com `cap_drop: ALL`; o que esta aqui e a excepcao, e tem de ser
#: nomeada uma a uma para que nenhuma entre em silencio.
#:
#: Ha **uma**, e nao e para ser usada: o `/usr/bin/caddy` traz
#: `cap_net_bind_service=ep` como capacidade de **ficheiro**, e com
#: `cap_drop: ALL` o kernel recusa **executar** o binario — medido a
#: 2026-11-03, com e sem `no-new-privileges`. O Caddy escuta em 8443, acima de
#: 1024, pelo que a capacidade fica concedida e nunca exercida.
CAPACIDADES_PERMITIDAS: dict[str, frozenset[str]] = {
    "proxy-tls": frozenset({"NET_BIND_SERVICE"}),
}

#: Chaves que, num servico, desfazem o isolamento que os criterios 3 e 4
#: constroem. **Nenhuma pode aparecer**, e nao ha excepcao nomeada: se alguma
#: vier a ser necessaria, entra aqui com a razao, como as capacidades.
#:
#: NASCEU DE UM BURACO MEDIDO. A primeira versao deste lint verificava o
#: utilizador, os limites e as capacidades acrescentadas — e **passava em
#: silencio** por `privileged: true`, por `network_mode: host`, por `pid: host`
#: e pelo `cap_drop: ALL` simplesmente apagado. O `network_mode: host` e o pior
#: dos quatro: um contentor com ele nao esta em rede nenhuma do compose, pelo
#: que as quatro redes do criterio 3 deixam de o conter — e o guiao dos dez
#: destinos continuaria verde, porque mede o proxy e nao aquele servico.
CHAVES_DE_FUGA: dict[str, str] = {
    "privileged": "um contentor privilegiado tem todas as capacidades e acesso aos dispositivos do *host*",
    "network_mode": "tira o servico das redes do compose; com `host` as quatro redes do criterio 3 deixam de o conter",
    "pid": "partilhar o espaco de PIDs do *host* deixa o contentor ver e sinalizar processos de fora",
    "ipc": "partilhar o IPC do *host* abre memoria partilhada entre o contentor e a maquina",
    "userns_mode": "desfaz o mapeamento de utilizadores, e com ele o valor de correr nao-root",
    "cgroup": "partilhar o cgroup do *host* desfaz os limites do criterio 4",
    "devices": "expor um dispositivo do *host* e expor o *host*",
    "device_cgroup_rules": "idem, pela regra de cgroup",
    # As tres seguintes vieram da revisao adversarial, que as atravessou todas.
    "dns": "um resolvedor proprio contorna o DNS do compose, e com ele a allowlist por FQDN do proxy",
    "extra_hosts": "fixar um IP para um FQDN engana a allowlist: o `:authority` continua permitido e o destino e outro",
    "dns_search": "um dominio de busca proprio muda o que um nome curto resolve",
}

#: O que **tem** de estar em todos os servicos, e o valor que conta.
#: `read_only` nao esta aqui: ja e `fs-so-de-leitura` do `supply_chain runtime`.
CAP_DROP_EXIGIDO = "ALL"
SECURITY_OPT_EXIGIDO = "no-new-privileges:true"

#: Montar isto num contentor e dar-lhe o *daemon* do Docker, e com ele a
#: maquina inteira. Nenhum servico do conjunto reduzido precisa.
SOCKET_DO_DOCKER = "/var/run/docker.sock"

#: O tecto do criterio 4, **em codigo**, para que os dois lados da comparacao
#: nao venham do mesmo ficheiro que a regra le.
#:
#: NASCEU DE UMA PROVA CIRCULAR MEDIDA. O manifesto declara `host_ram_mib` e
#: `fraccao_maxima_pct`, e a regra comparava a soma contra eles: subir
#: `fraccao_maxima_pct` de 80 para 95, ou `host_ram_mib` de 32768 para 65536,
#: punha o lint verde sobre uma pilha que nao cabe. Os numeros do criterio —
#: «<= 80% da RAM do *host* (<= 25,6 GB em 32 GB)» e o perfil P0 de 32 GB do
#: `docs/tecnica/09` §4.4 — passam a estar aqui, e o manifesto tem de concordar
#: com eles. Mudar o tecto deixa de ser uma linha de YAML: e uma alteracao de
#: codigo, que se ve numa revisao.
HOST_RAM_MIB = 32 * 1024
FRACCAO_MAXIMA_PCT = 80

#: ADR-001: o Chatwoot nunca fala com a Meta; o GWY e o unico endpoint. Estas
#: tres variaveis dao-lhe um caminho proprio para o mesmo numero.
META_NO_CHATWOOT = ("WHATSAPP_APP_ID", "WHATSAPP_CONFIGURATION_ID", "WHATSAPP_APP_SECRET")

#: Criterio 8: as *flags* de edicao paga que tem de estar inactivas, por
#: servico, e o valor que as desliga. O Medusa nao esta aqui: as cinco *flags*
#: dele ja sao verificadas por `tools/lint_arch/medusa.py`, com canario.
FLAGS_DE_LICENCA = {
    "chatwoot": ("DISABLE_ENTERPRISE", "true"),
    "chatwoot-worker": ("DISABLE_ENTERPRISE", "true"),
}

#: Quem sai para fora passa pelo proxy. Um servico de `app` com destinos
#: declarados e sem `HTTPS_PROXY` tem o contrato num ficheiro e a rota noutro.
VARIAVEL_DE_SAIDA = "HTTPS_PROXY"
PROXY_ESPERADO = "http://proxy-saida:3128"

_MEMORIA = re.compile(r"^(?P<numero>[0-9]+(?:\.[0-9]+)?)(?P<unidade>[kmgt]?)b?$", re.IGNORECASE)
_UNIDADES = {"": 1 / (1024 * 1024), "k": 1 / 1024, "m": 1.0, "g": 1024.0, "t": 1024.0 * 1024}


class ConfiguracaoInvalida(ValueError):
    """Um ficheiro de politica em falta ou ilegivel. Saida 2, nunca achado.

    Um manifesto que nao se le nao pode parecer um compose conforme.
    """


@dataclass(frozen=True)
class Achado:
    regra: str
    ficheiro: str
    linha: int
    mensagem: str

    def __str__(self) -> str:
        onde = f"{self.ficheiro}:{self.linha}" if self.linha else self.ficheiro
        return f"[{self.regra}] {onde}: {self.mensagem}"


@dataclass(frozen=True)
class Servico:
    """Um servico do manifesto `conjunto-reduzido.yaml`.

    `memoria_mib` e o **total do servico**; `replicas` diz por quantos
    contentores esse total se divide. A distincao custou um defeito: ver a nota
    no cabecalho do manifesto.
    """

    nome: str
    estado: str
    memoria_mib: int
    rede: str | None
    ticket: str | None
    replicas: int = 1


@dataclass
class Dados:
    raiz: Path
    #: nome -> Servico, do manifesto.
    manifesto: dict[str, Servico]
    #: nome -> razao, da *denylist*.
    proibidos: dict[str, str]
    host_ram_mib: int
    fraccao_maxima_pct: int
    #: O compose de producao, lido.
    prod: compose_mod.Compose
    #: O texto cru do compose de producao: a *denylist* le-o todo, e nao so os
    #: nomes dos servicos. Um `langfuse` num `volumes:` ou num `command:` conta.
    prod_texto: str
    #: O compose de *staging*, se existir.
    staging: compose_mod.Compose | None
    #: fqdn -> servicos que o declaram, de `egress.yaml` de quem corre em `app`.
    declarados: dict[str, set[str]]
    #: fqdn de `infra/egress/proxy-saida.yaml`.
    allowlist: set[str]


# --------------------------------------------------------------------- leitura


def _memoria_mb(texto: str) -> float | None:
    correspondencia = _MEMORIA.match(texto.strip())
    if not correspondencia:
        return None
    numero = float(correspondencia.group("numero"))
    return numero * _UNIDADES[correspondencia.group("unidade").lower()]


def _ler_manifesto(raiz: Path) -> tuple[dict[str, Servico], dict[str, str], float, float]:
    caminho = raiz / MANIFESTO
    if not caminho.is_file():
        raise ConfiguracaoInvalida(f"manifesto ausente: {MANIFESTO}")
    try:
        dados = load_file(caminho)
    except YamlSubsetError as excepcao:
        raise ConfiguracaoInvalida(f"{MANIFESTO}: ilegivel: {excepcao}") from excepcao

    servicos: dict[str, Servico] = {}
    for item in dados.get("servicos") or []:
        nome = item.get("nome")
        estado = item.get("estado")
        if not nome or estado not in ("presente", "pendente"):
            raise ConfiguracaoInvalida(
                f"{MANIFESTO}: servico sem `nome` ou com `estado` que nao e "
                f"`presente` nem `pendente`: {item!r}"
            )
        if nome in servicos:
            raise ConfiguracaoInvalida(f"{MANIFESTO}: `{nome}` declarado duas vezes")
        if estado == "pendente" and not item.get("ticket"):
            raise ConfiguracaoInvalida(
                f"{MANIFESTO}: `{nome}` esta `pendente` sem `ticket`. Um servico "
                "que falta sem ticket e um servico que ninguem vai trazer."
            )
        try:
            memoria = int(item.get("memoria_mib"))
        except (TypeError, ValueError) as excepcao:
            raise ConfiguracaoInvalida(
                f"{MANIFESTO}: `{nome}` sem `memoria_mib` legivel (inteiro, em MiB)"
            ) from excepcao
        try:
            replicas = int(item.get("replicas") or 1)
        except (TypeError, ValueError) as excepcao:
            raise ConfiguracaoInvalida(
                f"{MANIFESTO}: `{nome}` tem `replicas` ilegivel"
            ) from excepcao
        if replicas < 1:
            raise ConfiguracaoInvalida(f"{MANIFESTO}: `{nome}` tem `replicas` < 1")
        if memoria % replicas:
            raise ConfiguracaoInvalida(
                f"{MANIFESTO}: `{nome}` tem {memoria} MiB para {replicas} replicas, "
                "que nao divide em inteiros — o `mem_limit` por contentor nao daria "
                "um numero exacto e a soma deixaria de fechar."
            )
        servicos[nome] = Servico(
            nome, estado, memoria, item.get("rede"), item.get("ticket"), replicas
        )

    proibidos: dict[str, str] = {}
    for item in dados.get("proibidos") or []:
        nome = item.get("nome")
        if not nome or not item.get("adr"):
            raise ConfiguracaoInvalida(
                f"{MANIFESTO}: entrada de `proibidos` sem `nome` ou sem `adr`: {item!r}"
            )
        proibidos[nome] = item.get("razao") or ""
    if not proibidos:
        raise ConfiguracaoInvalida(
            f"{MANIFESTO}: `proibidos` vazia. Uma *denylist* vazia passa sempre, "
            "e o criterio 1 nomeia seis servicos."
        )
    if not servicos:
        raise ConfiguracaoInvalida(f"{MANIFESTO}: `servicos` vazia")

    try:
        ram = int(dados.get("host_ram_mib"))
        fraccao = int(dados.get("fraccao_maxima_pct"))
    except (TypeError, ValueError) as excepcao:
        raise ConfiguracaoInvalida(
            f"{MANIFESTO}: `host_ram_mib` ou `fraccao_maxima_pct` ilegivel"
        ) from excepcao
    if not 0 < fraccao <= 100:
        raise ConfiguracaoInvalida(
            f"{MANIFESTO}: `fraccao_maxima_pct` fora de (0, 100]"
        )
    return servicos, proibidos, ram, fraccao


def _ler_compose(raiz: Path, relativo: str, obrigatorio: bool) -> compose_mod.Compose | None:
    caminho = raiz / relativo
    if not caminho.is_file():
        if obrigatorio:
            raise ConfiguracaoInvalida(f"compose ausente: {relativo}")
        return None
    try:
        return compose_mod.ler(caminho, raiz)
    except arvore_yaml.YamlIlegivel as excepcao:
        raise ConfiguracaoInvalida(f"{relativo}: ilegivel: {excepcao}") from excepcao


def _ler_saidas(raiz: Path) -> tuple[dict[str, set[str]], set[str]]:
    """Os destinos declarados por servico, e a allowlist do proxy."""
    declarados: dict[str, set[str]] = {}
    for caminho in sorted((raiz / "infra" / "egress").glob("*.yaml")) + sorted(
        (raiz / "services").glob("*/egress.yaml")
    ):
        try:
            dados = load_file(caminho)
        except YamlSubsetError as excepcao:
            raise ConfiguracaoInvalida(f"{caminho.name}: ilegivel: {excepcao}") from excepcao
        servico = dados.get("servico")
        if not servico:
            raise ConfiguracaoInvalida(f"{caminho.name}: sem `servico`")
        for destino in dados.get("destinos") or []:
            fqdn = destino.get("fqdn")
            if fqdn:
                declarados.setdefault(servico, set()).add(fqdn)

    caminho = raiz / ALLOWLIST
    if not caminho.is_file():
        raise ConfiguracaoInvalida(f"allowlist ausente: {ALLOWLIST}")
    try:
        dados = load_file(caminho)
    except YamlSubsetError as excepcao:
        raise ConfiguracaoInvalida(f"{ALLOWLIST}: ilegivel: {excepcao}") from excepcao
    if dados.get("por_omissao") != "negar":
        raise ConfiguracaoInvalida(
            f"{ALLOWLIST}: `por_omissao` nao e `negar`. A allowlist do proxy de "
            "saida que nao negue por omissao nao e uma allowlist."
        )
    allowlist = {d.get("fqdn") for d in (dados.get("destinos") or []) if d.get("fqdn")}
    return declarados, allowlist


def ler(raiz: Path) -> Dados:
    manifesto, proibidos, ram, fraccao = _ler_manifesto(raiz)
    prod = _ler_compose(raiz, PROD, obrigatorio=True)
    assert prod is not None
    declarados, allowlist = _ler_saidas(raiz)
    return Dados(
        raiz=raiz,
        manifesto=manifesto,
        proibidos=proibidos,
        host_ram_mib=ram,
        fraccao_maxima_pct=fraccao,
        prod=prod,
        prod_texto=(raiz / PROD).read_text(encoding="utf-8"),
        staging=_ler_compose(raiz, STAGING, obrigatorio=False),
        declarados=declarados,
        allowlist=allowlist,
    )


# ---------------------------------------------------------------- utilitarios


#: Os utilitarios recebem o **ficheiro** e nao os `Dados`, de proposito: a
#: primeira versao lia sempre `dados.prod.documento`, e usada numa regra de
#: *staging* resolvia os nos de um ficheiro contra a arvore do outro. Nao dava
#: erro — dava silencio.


def _valor(ficheiro: compose_mod.Compose, chaves: dict, chave: str) -> str | None:
    no = chaves.get(chave)
    if no is None:
        return None
    return ficheiro.documento.resolver(no).texto()


def _lista(ficheiro: compose_mod.Compose, chaves: dict, chave: str) -> list[str]:
    no = chaves.get(chave)
    if no is None:
        return []
    try:
        return ficheiro.documento.itens(no)
    except arvore_yaml.YamlIlegivel:
        return []


def _submapa(ficheiro: compose_mod.Compose, chaves: dict, chave: str) -> dict:
    no = chaves.get(chave)
    if no is None:
        return {}
    try:
        return ficheiro.documento.mapa(ficheiro.documento.resolver(no))
    except arvore_yaml.YamlIlegivel:
        return {}


def _ambiente(ficheiro: compose_mod.Compose, chaves: dict) -> dict[str, str]:
    """`environment:` como mapa, em qualquer das duas formas do compose."""
    no = chaves.get("environment")
    if no is None:
        return {}
    documento = ficheiro.documento
    no = documento.resolver(no)
    # Forma de lista: `- NOME=valor`.
    if no.filhos and all(filho.chave is None for filho in no.filhos):
        resultado: dict[str, str] = {}
        for item in documento.itens(no):
            nome, _, valor = item.partition("=")
            resultado[nome.strip()] = valor.strip()
        return resultado
    try:
        return {
            nome: documento.resolver(filho).texto()
            for nome, filho in documento.mapa(no).items()
        }
    except arvore_yaml.YamlIlegivel:
        return {}


def _linha(chaves: dict, chave: str, por_omissao: int) -> int:
    no = chaves.get(chave)
    return no.linha if no is not None else por_omissao


def _replicas(dados: Dados, chaves: dict) -> int:
    """`deploy.replicas` do compose, ou 1. **E honrado fora de swarm** (medido)."""
    deploy = _submapa(dados.prod, chaves, "deploy")
    if "replicas" not in deploy:
        return 1
    texto = dados.prod.documento.resolver(deploy["replicas"]).texto()
    try:
        return int(texto)
    except ValueError:
        return 1


# -------------------------------------------------------------------- regras
#
# Uma funcao por regra. Cada uma devolve achados e nenhuma levanta: um ficheiro
# que nao se le e `ConfiguracaoInvalida` na leitura, nao achado numa regra.


def r_conjunto(dados: Dados) -> list[Achado]:
    """Criterio 1: o compose lista **exactamente** o conjunto reduzido."""
    achados: list[Achado] = []
    no_compose = set(dados.prod.servicos)
    presentes = {n for n, s in dados.manifesto.items() if s.estado == "presente"}
    pendentes = {n for n, s in dados.manifesto.items() if s.estado == "pendente"}

    for nome in sorted(no_compose - set(dados.manifesto)):
        achados.append(
            Achado(
                "conjunto-servico-nao-declarado", dados.prod.ficheiro,
                dados.prod.servicos[nome][0].linha,
                f"o servico `{nome}` nao consta de {MANIFESTO}. Um servico novo em "
                "producao passa pelo manifesto, com a razao e a memoria, ou nao passa.",
            )
        )
    for nome in sorted(presentes - no_compose):
        achados.append(
            Achado(
                "conjunto-servico-em-falta", MANIFESTO, 0,
                f"`{nome}` esta `presente` no manifesto e **nao** esta em "
                f"{PROD}. O criterio 1 diz «exactamente», e isto e o outro sentido.",
            )
        )
    for nome in sorted(pendentes & no_compose):
        servico = dados.manifesto[nome]
        achados.append(
            Achado(
                "conjunto-servico-pendente-presente", dados.prod.ficheiro,
                dados.prod.servicos[nome][0].linha,
                f"`{nome}` esta `pendente` no manifesto (ticket {servico.ticket}) e "
                "apareceu no compose. Se entrou, passa a `presente` com a memoria "
                "contada na soma do criterio 4.",
            )
        )
    return achados


def r_denylist(dados: Dados) -> list[Achado]:
    """Criterio 1: os seis nomes proibidos nao aparecem no ficheiro de producao.

    Le o **texto todo** e nao so os nomes dos servicos: um `langfuse` num
    `image:`, num `volumes:`, num `command:` ou numa variavel de ambiente punha
    o servico em producao tal como um `services:` o faria.

    Os comentarios **saltam-se**, e e a mesma razao do `tools/lint_arch/medusa.py`:
    este ficheiro explica por escrito porque e que o Langfuse nao entra, e um
    *lint* que falhasse por isso proibia documentar a propria regra.

    A fronteira e por caractere nao alfanumerico, como a `tools/blocklist.yaml`:
    apanha `langfuse`, `langfuse/langfuse` e `langfuse-worker`, e nao apanha uma
    palavra que apenas contenha o nome.
    """
    achados: list[Achado] = []
    for numero, linha in enumerate(dados.prod_texto.split("\n"), start=1):
        sem_comentario = linha.split("#", 1)[0]
        if not sem_comentario.strip():
            continue
        for nome, razao in sorted(dados.proibidos.items()):
            if re.search(rf"(?:^|[^a-z0-9]){re.escape(nome)}(?:[^a-z0-9]|$)",
                         sem_comentario, re.IGNORECASE):
                achados.append(
                    Achado(
                        "denylist", dados.prod.ficheiro, numero,
                        f"`{nome}` aparece no ficheiro de producao. {razao.strip()} "
                        "Fora de producao nao e o mesmo que fora do repositorio: em "
                        "*staging* alguns destes correm, e e la que entram.",
                    )
                )
    return achados


def r_imagens(dados: Dados) -> list[Achado]:
    """Criterio 2: 100% das imagens do ficheiro de producao por `@sha256:`.

    Duplica de proposito o `supply_chain imagens` — a razao esta no cabecalho
    deste modulo: um gate do repositorio inteiro nao diz, ao falhar, que foi o
    compose de producao que o quebrou.
    """
    achados: list[Achado] = []
    documento = dados.prod.documento
    for nome, (_no, chaves) in sorted(dados.prod.servicos.items()):
        if "image" not in chaves:
            continue
        no = documento.resolver(chaves["image"])
        bruto = no.texto()
        valor, _ = compose_mod.resolver_interpolacao(bruto)
        if valor is None:
            achados.append(
                Achado(
                    "imagem-nao-resolvida", dados.prod.ficheiro, no.linha,
                    f"a imagem de `{nome}` (`{bruto}`) depende de um valor que nao "
                    "esta no repositorio. De-lhe uma omissao com digest "
                    "(`${VAR:-nome:etiqueta@sha256:...}`).",
                )
            )
            continue
        if "@sha256:" not in valor:
            achados.append(
                Achado(
                    "imagem-por-etiqueta", dados.prod.ficheiro, no.linha,
                    f"a imagem de `{nome}` (`{valor}`) vem por etiqueta e nao por "
                    "digest. Uma etiqueta pode passar a apontar para outra imagem; "
                    "leia o digest da fonte e registe-o em ci/supply-chain/imagens.yaml.",
                )
            )
    return achados


def r_redes_declaradas(dados: Dados) -> list[Achado]:
    """Criterio 3: as quatro redes existem, e so `edge` tem rota para fora."""
    achados: list[Achado] = []
    documento = dados.prod.documento
    topo = documento.mapa(documento.raiz)
    if "networks" not in topo:
        return [
            Achado(
                "rede-em-falta", dados.prod.ficheiro, 0,
                "o compose de producao nao declara `networks:`. O criterio 3 pede "
                "quatro redes isoladas.",
            )
        ]
    declaradas = documento.mapa(documento.resolver(topo["networks"]))
    for rede, interna_esperada in REDES.items():
        if rede not in declaradas:
            achados.append(
                Achado(
                    "rede-em-falta", dados.prod.ficheiro, topo["networks"].linha,
                    f"a rede `{rede}` nao esta declarada. As quatro do "
                    "`docs/tecnica/09` §3.2 regra 2 sao `edge`, `app`, `data` e `ops`.",
                )
            )
            continue
        corpo = documento.mapa(documento.resolver(declaradas[rede]))
        interna = (
            documento.resolver(corpo["internal"]).texto().lower() == "true"
            if "internal" in corpo else False
        )
        if interna_esperada and not interna:
            achados.append(
                Achado(
                    "rede-com-rota", dados.prod.ficheiro, declaradas[rede].linha,
                    f"a rede `{rede}` nao e `internal: true`. Medido a 2026-11-03: "
                    "sem isto um contentor dela tem rota por omissao **e DNS** para "
                    "a Internet, e o egress deixa de passar pelo proxy.",
                )
            )
        if not interna_esperada and interna:
            achados.append(
                Achado(
                    "rede-sem-rota", dados.prod.ficheiro, declaradas[rede].linha,
                    f"a rede `{rede}` e `internal: true`. E a unica que tem de ter "
                    "rota: sem ela o `proxy-tls` nao publica 443 e o `proxy-saida` "
                    "nao tem por onde sair.",
                )
            )

    # E **nenhuma** alem das quatro. A revisao adversarial atravessou isto: uma
    # quinta rede sem `internal`, com um servico de `app` dentro, dava-lhe saida
    # directa — e o guiao dos dez destinos continuava verde, porque sonda `app`.
    for rede in sorted(set(declaradas) - set(REDES)):
        achados.append(
            Achado(
                "rede-nao-declarada", dados.prod.ficheiro, declaradas[rede].linha,
                f"a rede `{rede}` nao e uma das quatro do `docs/tecnica/09` §3.2 "
                "regra 2. Uma rede a mais e um caminho de saida que nenhuma regra "
                "verifica e que o guiao dos dez destinos nao sonda.",
            )
        )
    return achados


def r_redes_por_servico(dados: Dados) -> list[Achado]:
    """Criterio 3: quem esta em `edge`, e quem nao sai de `data`."""
    achados: list[Achado] = []
    for nome, (no, chaves) in sorted(dados.prod.servicos.items()):
        redes = set(_lista(dados.prod, chaves, "networks"))
        linha = _linha(chaves, "networks", no.linha)
        if not redes:
            achados.append(
                Achado(
                    "servico-sem-rede", dados.prod.ficheiro, no.linha,
                    f"o servico `{nome}` nao declara `networks:`. Sem isso cai na "
                    "rede por omissao do compose, que tem rota para fora.",
                )
            )
            continue
        if "edge" in redes and nome not in SO_EM_EDGE:
            achados.append(
                Achado(
                    "servico-em-edge", dados.prod.ficheiro, linha,
                    f"o servico `{nome}` esta em `edge`, que e a unica rede com rota "
                    f"para fora. So {', '.join(sorted(SO_EM_EDGE))} podem estar la: "
                    "qualquer outro ganha um caminho de saida que o proxy nao registar.",
                )
            )
        # Uma rede que o topo nao declara, num servico. A `r_redes_declaradas`
        # olha para o topo; esta olha para quem as usa.
        for rede in sorted(redes - set(REDES)):
            achados.append(
                Achado(
                    "rede-nao-declarada", dados.prod.ficheiro, linha,
                    f"o servico `{nome}` esta na rede `{rede}`, que nao e uma das "
                    "quatro. Uma rede a mais e um caminho que nenhuma regra verifica.",
                )
            )
        # O manifesto diz em que rede o servico vive; se disser uma e o compose
        # nao a tiver, uma das duas esta errada e vale saber qual.
        esperada = dados.manifesto.get(nome).rede if nome in dados.manifesto else None
        if esperada and esperada not in redes:
            achados.append(
                Achado(
                    "rede-divergente-do-manifesto", dados.prod.ficheiro, linha,
                    f"o manifesto poe `{nome}` em `{esperada}` e o compose tem-no em "
                    f"{sorted(redes)}. O manifesto e a fonte do criterio 1: divergir "
                    "aqui faz a leitura dele descrever outra topologia.",
                )
            )
        if nome in SO_EM_DATA and redes != {"data"}:
            achados.append(
                Achado(
                    "dados-fora-de-data", dados.prod.ficheiro, linha,
                    f"o servico de dados `{nome}` esta em {sorted(redes)} e devia "
                    "estar so em `data`. O `docs/tecnica/09` §3.2 regra 2 poe a base "
                    "de dados sem rota de saida; juntar-lhe `app` dava-lhe uma.",
                )
            )
    return achados


def r_saida_pelo_proxy(dados: Dados) -> list[Achado]:
    """Criterio 3: quem declara destinos sai pelo proxy, e a allowlist bate."""
    achados: list[Achado] = []
    for nome, (no, chaves) in sorted(dados.prod.servicos.items()):
        if nome in SO_EM_EDGE or not dados.declarados.get(nome):
            continue
        ambiente = _ambiente(dados.prod, chaves)
        valor = ambiente.get(VARIAVEL_DE_SAIDA)
        if valor != PROXY_ESPERADO:
            achados.append(
                Achado(
                    "saida-sem-proxy", dados.prod.ficheiro, no.linha,
                    f"o servico `{nome}` declara destinos em egress.yaml e o seu "
                    f"`{VARIAVEL_DE_SAIDA}` e {valor!r} e nao {PROXY_ESPERADO!r}. "
                    "O contrato ficava num ficheiro e a rota noutro.",
                )
            )
        # `NO_PROXY: "*"` tira **tudo** do proxy, e e uma linha. A revisao
        # adversarial atravessou-a: o `saida-sem-proxy` ve o `HTTPS_PROXY`
        # correcto ao lado e nao olha para o que o desliga.
        sem_proxy = ambiente.get("NO_PROXY", "")
        entradas = {e.strip() for e in sem_proxy.split(",")}
        if "*" in entradas:
            achados.append(
                Achado(
                    "no-proxy-aberto", dados.prod.ficheiro,
                    _linha(chaves, "environment", no.linha),
                    f"o `NO_PROXY` de `{nome}` tem `*`, o que tira **todos** os "
                    "destinos do proxy de saida. O `HTTPS_PROXY` ao lado passa a ser "
                    "decoracao, e a allowlist do criterio 3 deixa de se aplicar.",
                )
            )

    # A allowlist nos dois sentidos. Nao se olha para `dados.declarados` todo:
    # so para os servicos que correm **em producao**, que sao os que o proxy
    # serve. Um destino declarado por um servico que nao esta no compose de
    # producao nao tem de estar na allowlist dele.
    em_producao = set(dados.prod.servicos) - SO_EM_EDGE
    pedidos: dict[str, set[str]] = {}
    for servico in em_producao:
        for fqdn in dados.declarados.get(servico, set()):
            pedidos.setdefault(fqdn, set()).add(servico)

    for fqdn in sorted(set(pedidos) - dados.allowlist):
        achados.append(
            Achado(
                "allowlist-em-falta", ALLOWLIST, 0,
                f"`{fqdn}` e declarado por {sorted(pedidos[fqdn])} e nao esta na "
                "allowlist do proxy. O servico declarou uma saida que o proxy "
                "recusa: o contrato mentia.",
            )
        )
    for fqdn in sorted(dados.allowlist - set(pedidos)):
        achados.append(
            Achado(
                "allowlist-sem-dono", ALLOWLIST, 0,
                f"`{fqdn}` esta na allowlist do proxy e nenhum servico de producao "
                "o declara. Um destino aprovado sem dono e o contrario de negar "
                "por omissao.",
            )
        )
    return achados


def r_endurecimento(dados: Dados) -> list[Achado]:
    """Criterio 4: utilizador nao-root, `mem_limit` e `cpus` em todos.

    `read_only: true` **nao** esta aqui: ja e `fs-so-de-leitura` do
    `supply_chain runtime`, em todos os compose do repositorio.
    """
    achados: list[Achado] = []
    for nome, (no, chaves) in sorted(dados.prod.servicos.items()):
        utilizador = _valor(dados.prod, chaves, "user")
        if utilizador is None:
            achados.append(
                Achado(
                    "utilizador-por-omissao", dados.prod.ficheiro, no.linha,
                    f"o servico `{nome}` nao declara `user:`. Sem isso corre com o "
                    "utilizador da imagem, que na maioria e `root`.",
                )
            )
        elif utilizador.strip().strip("\"'").split(":")[0] in ("root", "0"):
            achados.append(
                Achado(
                    "utilizador-root", dados.prod.ficheiro, _linha(chaves, "user", no.linha),
                    f"o servico `{nome}` corre como `root` (`{utilizador}`).",
                )
            )
        if "mem_limit" not in chaves:
            achados.append(
                Achado(
                    "sem-limite-de-memoria", dados.prod.ficheiro, no.linha,
                    f"o servico `{nome}` nao tem `mem_limit`. Sem limite, um servico "
                    "a crescer derruba os outros (`docs/tecnica/09` §3.2 regra 3).",
                )
            )
        if "cpus" not in chaves:
            achados.append(
                Achado(
                    "sem-limite-de-cpu", dados.prod.ficheiro, no.linha,
                    f"o servico `{nome}` nao tem `cpus`. O criterio 4 pede os dois "
                    "limites, e 8 vCPU e o piso do perfil P0.",
                )
            )
        # Capacidades: toda a pilha corre com `cap_drop: ALL`, e cada excepcao
        # tem de estar nomeada em `CAPACIDADES_PERMITIDAS` com a razao. Sem esta
        # regra, acrescentar `SYS_ADMIN` a um contentor era uma linha que
        # nenhum gate via.
        acrescentadas = {c.strip().upper() for c in _lista(dados.prod, chaves, "cap_add")}
        permitidas = CAPACIDADES_PERMITIDAS.get(nome, frozenset())
        a_mais = acrescentadas - permitidas
        if a_mais:
            achados.append(
                Achado(
                    "capacidade-acrescentada", dados.prod.ficheiro,
                    _linha(chaves, "cap_add", no.linha),
                    f"o servico `{nome}` acrescenta {sorted(a_mais)} e isso nao esta "
                    "em CAPACIDADES_PERMITIDAS. Toda a pilha corre com "
                    "`cap_drop: ALL`; uma capacidade nova nomeia-se no lint, com a "
                    "razao, ou nao entra.",
                )
            )

        # O que tem de estar, e que a primeira versao deste lint nao exigia:
        # apagar o `cap_drop: ALL` ou o `no-new-privileges` passava em silencio.
        largadas = {c.strip().upper() for c in _lista(dados.prod, chaves, "cap_drop")}
        if CAP_DROP_EXIGIDO not in largadas:
            achados.append(
                Achado(
                    "sem-cap-drop", dados.prod.ficheiro, no.linha,
                    f"o servico `{nome}` nao tem `cap_drop: [{CAP_DROP_EXIGIDO}]`. Sem "
                    "isso corre com o conjunto de capacidades por omissao do Docker, e "
                    "o `capacidade-acrescentada` ao lado nao serve de nada: nao e "
                    "preciso **acrescentar** uma capacidade que nunca foi largada.",
                )
            )
        opcoes = {o.strip() for o in _lista(dados.prod, chaves, "security_opt")}
        if SECURITY_OPT_EXIGIDO not in opcoes:
            achados.append(
                Achado(
                    "sem-no-new-privileges", dados.prod.ficheiro, no.linha,
                    f"o servico `{nome}` nao tem `security_opt: [{SECURITY_OPT_EXIGIDO}]`. "
                    "Sem isso um binario com `setuid` dentro da imagem pode elevar "
                    "privilegio a partir de um processo nao-root.",
                )
            )

        # E o que nao pode estar. Cada uma destas desfaz o isolamento que os
        # criterios 3 e 4 constroem, e nenhuma e apanhada por outra regra.
        for chave, razao in sorted(CHAVES_DE_FUGA.items()):
            if chave not in chaves:
                continue
            valor = _valor(dados.prod, chaves, chave) or "(presente)"
            achados.append(
                Achado(
                    "fuga-de-isolamento", dados.prod.ficheiro,
                    _linha(chaves, chave, no.linha),
                    f"o servico `{nome}` declara `{chave}: {valor}`. {razao}. Nenhum "
                    "servico do conjunto reduzido precisa desta chave; se algum vier "
                    "a precisar, entra em CHAVES_DE_FUGA com a razao, como as "
                    "capacidades.",
                )
            )

        # O socket do Docker: dar o *daemon* a um contentor e dar-lhe a maquina.
        for montagem in _lista(dados.prod, chaves, "volumes"):
            if SOCKET_DO_DOCKER in montagem:
                achados.append(
                    Achado(
                        "fuga-de-isolamento", dados.prod.ficheiro,
                        _linha(chaves, "volumes", no.linha),
                        f"o servico `{nome}` monta `{SOCKET_DO_DOCKER}`. Quem fala com "
                        "o *daemon* do Docker pode levantar um contentor privilegiado, "
                        "e com ele sair de todo o isolamento deste ficheiro.",
                    )
                )
    return achados


def r_memoria(dados: Dados) -> list[Achado]:
    """Criterio 4: cada limite e o do manifesto, e a soma cabe em 80% da RAM.

    A soma conta os `pendente` tambem: a memoria deles esta reservada, e um
    conjunto que so cabe porque falta metade dos servicos nao cabe.
    """
    achados: list[Achado] = []
    for nome, (no, chaves) in sorted(dados.prod.servicos.items()):
        if "mem_limit" not in chaves or nome not in dados.manifesto:
            continue
        bruto = _valor(dados.prod, chaves, "mem_limit") or ""
        medido = _memoria_mb(bruto)
        if medido is None:
            achados.append(
                Achado(
                    "memoria-ilegivel", dados.prod.ficheiro,
                    _linha(chaves, "mem_limit", no.linha),
                    f"o `mem_limit` de `{nome}` (`{bruto}`) nao se le como memoria.",
                )
            )
            continue
        servico = dados.manifesto[nome]
        # O `mem_limit` e **por contentor**; o manifesto declara o total do
        # servico. Multiplicar pelas replicas e o que o defeito do §4 da
        # evidencia ensinou: sem isto, o GWY reservava o dobro do que o bloco
        # propoe e a soma nao dava por isso.
        replicas_do_compose = _replicas(dados, chaves)
        if replicas_do_compose != servico.replicas:
            achados.append(
                Achado(
                    "replicas-divergentes", dados.prod.ficheiro, no.linha,
                    f"`{nome}` corre com {replicas_do_compose} replica(s) no compose e "
                    f"o manifesto diz {servico.replicas}. A soma do criterio 4 "
                    "multiplica o `mem_limit` pelas replicas do **manifesto**: "
                    "divergir aqui faz a soma medir outra pilha.",
                )
            )
        esperado = servico.memoria_mib / servico.replicas
        if abs(medido - esperado) > 0.5:
            achados.append(
                Achado(
                    "memoria-divergente", dados.prod.ficheiro,
                    _linha(chaves, "mem_limit", no.linha),
                    f"o `mem_limit` de `{nome}` e `{bruto}` ({medido:.0f} MiB por "
                    f"contentor) e o manifesto diz {servico.memoria_mib} MiB para "
                    f"{servico.replicas} replica(s), ou seja {esperado:.0f} MiB cada. "
                    "O `mem_limit` do compose e **por contentor**, e o "
                    "`deploy.replicas` e honrado fora de swarm: contar o total uma "
                    "vez por servico subestima a reserva no *host*.",
                )
            )

    # O manifesto tem de concordar com os numeros do criterio, que estao em
    # codigo. Sem isto, subir uma linha de YAML punha o tecto onde se quisesse.
    if (dados.host_ram_mib, dados.fraccao_maxima_pct) != (HOST_RAM_MIB, FRACCAO_MAXIMA_PCT):
        achados.append(
            Achado(
                "tecto-alterado", MANIFESTO, 0,
                f"o manifesto diz `host_ram_mib: {dados.host_ram_mib}` e "
                f"`fraccao_maxima_pct: {dados.fraccao_maxima_pct}`, e o criterio 4 fixa "
                f"{HOST_RAM_MIB} MiB (perfil P0, doc 09 §4.4) e {FRACCAO_MAXIMA_PCT}%. "
                "Os dois lados da comparacao nao podem vir do mesmo ficheiro que a "
                "regra le: mudar o tecto e alteracao de codigo, nao de YAML.",
            )
        )

    soma = sum(s.memoria_mib for s in dados.manifesto.values())
    tecto = HOST_RAM_MIB * FRACCAO_MAXIMA_PCT / 100
    if soma > tecto + 1e-9:
        achados.append(
            Achado(
                "soma-de-memoria", MANIFESTO, 0,
                f"a soma dos limites do manifesto e {soma} MiB ({soma / 1024:.2f} GiB) e "
                f"o tecto do criterio 4 e {tecto:.0f} MiB "
                f"({dados.fraccao_maxima_pct}% de {dados.host_ram_mib} MiB). "
                "Os limites sao ESTIMATIVA do bloco; "
                "quem os mede e corrige e o KAM-084.",
            )
        )
    return achados


def r_replicas_e_healthz(dados: Dados) -> list[Achado]:
    """Criterio 5: GWY e *workers* AGR com 2 replicas e `/healthz`."""
    achados: list[Achado] = []
    for nome, (no, chaves) in sorted(dados.prod.servicos.items()):
        if "healthcheck" not in chaves:
            achados.append(
                Achado(
                    "sem-healthcheck", dados.prod.ficheiro, no.linha,
                    f"o servico `{nome}` nao tem `healthcheck`. Sem ele o "
                    "`depends_on: service_healthy` de quem dele depende nao tem o "
                    "que esperar, e o *rolling* do KAM-078 nao sabe quando parar.",
                )
            )
        if nome not in DUAS_REPLICAS:
            continue
        deploy = _submapa(dados.prod, chaves, "deploy")
        replicas = (
            dados.prod.documento.resolver(deploy["replicas"]).texto()
            if "replicas" in deploy else None
        )
        if replicas != "2":
            achados.append(
                Achado(
                    "sem-duas-replicas", dados.prod.ficheiro, no.linha,
                    f"o servico `{nome}` tem `deploy.replicas` = {replicas!r} e o "
                    "criterio 5 pede 2. Sao elas que tornam o *rolling* do KAM-078 "
                    "possivel sem janela de indisponibilidade.",
                )
            )
        sonda = " ".join(_lista(dados.prod, _submapa(dados.prod, chaves, "healthcheck"), "test")) or (
            _valor(dados.prod, _submapa(dados.prod, chaves, "healthcheck"), "test") or ""
        )
        if "/healthz" not in sonda:
            achados.append(
                Achado(
                    "healthcheck-sem-healthz", dados.prod.ficheiro, no.linha,
                    f"o `healthcheck` de `{nome}` nao chama `/healthz`. O criterio 5 "
                    "nomeia a rota, e e a que o *rolling* e a sonda externa usam.",
                )
            )
    return achados


def r_portas(dados: Dados) -> list[Achado]:
    """Criterio 5: no exterior so 443; admin so por VPN (sentinela)."""
    achados: list[Achado] = []
    for nome, (no, chaves) in sorted(dados.prod.servicos.items()):
        publicadas = _lista(dados.prod, chaves, "ports")
        if not publicadas:
            continue
        if nome in SO_POR_VPN:
            achados.append(
                Achado(
                    "admin-sem-vpn", dados.prod.ficheiro, _linha(chaves, "ports", no.linha),
                    f"o servico `{nome}` publica {publicadas}. O criterio 5 diz "
                    "«Medusa admin e Grafana so por VPN»: chega-se por WireGuard, "
                    "que corre no *host* (KAM-075), e nao por porta publicada.",
                )
            )
            continue
        if nome not in QUEM_PUBLICA:
            achados.append(
                Achado(
                    "porta-publicada", dados.prod.ficheiro, _linha(chaves, "ports", no.linha),
                    f"o servico `{nome}` publica {publicadas}. O criterio 5 diz que no "
                    f"exterior so 443 e a porta UDP do WireGuard estao abertas, e quem "
                    f"publica 443 e o `proxy-tls`.",
                )
            )
            continue
        for porta in publicadas:
            externa = porta.strip().strip("\"'").split(":")[0]
            if externa not in QUEM_PUBLICA[nome]:
                achados.append(
                    Achado(
                        "porta-publicada", dados.prod.ficheiro,
                        _linha(chaves, "ports", no.linha),
                        f"o servico `{nome}` publica a porta externa {externa}, e as "
                        f"permitidas sao {sorted(QUEM_PUBLICA[nome])}.",
                    )
                )
    return achados


def r_meta_so_no_gwy(dados: Dados) -> list[Achado]:
    """ADR-001: o Chatwoot nunca fala com a Meta; o GWY e o unico endpoint."""
    achados: list[Achado] = []
    for nome in ("chatwoot", "chatwoot-worker"):
        if nome not in dados.prod.servicos:
            continue
        _no, chaves = dados.prod.servicos[nome]
        ambiente = _ambiente(dados.prod, chaves)
        for variavel in META_NO_CHATWOOT:
            if variavel in ambiente:
                achados.append(
                    Achado(
                        "chatwoot-fala-com-a-meta", dados.prod.ficheiro,
                        _linha(chaves, "environment", _no.linha),
                        f"`{nome}` tem `{variavel}`. Com as credenciais da Meta o "
                        "Chatwoot ganha um caminho proprio para o mesmo numero, e o "
                        "ADR-001 faz do GWY o unico endpoint. O Chatwoot recebe "
                        "espelho por inbox de tipo API.",
                    )
                )
    return achados


def r_flags_de_licenca(dados: Dados) -> list[Achado]:
    """Criterio 8: `enterprise/` do Chatwoot inactivo (o Medusa e no lint_arch)."""
    achados: list[Achado] = []
    for nome, (variavel, esperado) in sorted(FLAGS_DE_LICENCA.items()):
        if nome not in dados.prod.servicos:
            continue
        no, chaves = dados.prod.servicos[nome]
        ambiente = _ambiente(dados.prod, chaves)
        valor = ambiente.get(variavel)
        if (valor or "").strip().strip("\"'").lower() != esperado:
            achados.append(
                Achado(
                    "flag-de-licenca", dados.prod.ficheiro,
                    _linha(chaves, "environment", no.linha),
                    f"`{nome}` tem `{variavel}` = {valor!r} e devia ser {esperado!r}. "
                    "A imagem traz o codigo da edicao paga; o criterio 8 pede que "
                    "esteja inactivo, e correr codigo de uma licenca que nao temos "
                    "nao e opcao de configuracao.",
                )
            )
    return achados


def r_staging(dados: Dados) -> list[Achado]:
    """Criterio 2: as mesmas imagens, e o `staging-obs` so aqui e sem dados reais.

    Tres propriedades, e a primeira e a que da sentido as outras:

    1. **As mesmas imagens.** Todo o digest que corre em producao corre em
       *staging*. E o que faz do *smoke* do KAM-078 uma prova sobre producao e
       nao sobre outra pilha parecida.
    2. **O perfil `staging-obs` existe, e tem o Langfuse dentro.** O criterio 2
       diz que ele «so existe em *staging*»; que nao exista em producao e a
       regra `denylist`, que le o ficheiro de producao. Aqui verifica-se o outro
       lado: que existe, e que o Langfuse esta atras dele e nao solto.
    3. **Nunca com dados reais.** Os *traces* do Langfuse levam conversas, logo
       transferencia sob ADR-008. Um `kamba_data_class` com valor `real` neste
       ficheiro contradiz o criterio, e e procurado no texto todo — a variavel
       pode chegar por `environment`, por `env_file` ou por omissao de
       interpolacao, e as tres escrevem o mesmo nome.
    """
    if dados.staging is None:
        return [
            Achado(
                "staging-ausente", STAGING, 0,
                "nao ha compose de *staging*. O objectivo do KAM-076 e «o Compose de "
                "producao (e o de *staging*, com as mesmas imagens)».",
            )
        ]
    achados: list[Achado] = []
    staging = dados.staging

    def digests(ficheiro: compose_mod.Compose) -> dict[str, str]:
        """digest -> servico que o referencia."""
        encontrados: dict[str, str] = {}
        for nome, (_no, chaves) in ficheiro.servicos.items():
            if "image" not in chaves:
                continue
            valor, _ = compose_mod.resolver_interpolacao(
                ficheiro.documento.resolver(chaves["image"]).texto()
            )
            if valor and "@sha256:" in valor:
                encontrados.setdefault(valor.split("@sha256:")[1], nome)
        return encontrados

    de_staging = digests(staging)
    for digest, servico in sorted(digests(dados.prod).items()):
        if digest not in de_staging:
            achados.append(
                Achado(
                    "staging-com-outras-imagens", STAGING, 0,
                    f"o digest de `{servico}` (`sha256:{digest[:12]}...`) corre em "
                    "producao e nao aparece em *staging*. «Com as mesmas imagens» e o "
                    "que faz do *smoke* de *staging* uma prova sobre producao.",
                )
            )

    no_perfil: set[str] = set()
    for nome, (_no, chaves) in staging.servicos.items():
        if PERFIL_OBS in _lista(staging, chaves, "profiles"):
            no_perfil.add(nome)
    if not no_perfil:
        achados.append(
            Achado(
                "staging-sem-perfil-obs", STAGING, 0,
                f"nenhum servico esta no perfil `{PERFIL_OBS}`. O criterio 2 diz que "
                "o perfil «so existe em *staging*», e um perfil sem servicos nao "
                "existe em sitio nenhum.",
            )
        )

    for nome, (no, chaves) in sorted(staging.servicos.items()):
        if not re.search(r"(?:^|[^a-z0-9])langfuse(?:[^a-z0-9]|$)", nome, re.IGNORECASE):
            continue
        if nome not in no_perfil:
            achados.append(
                Achado(
                    "langfuse-sem-perfil", STAGING, no.linha,
                    f"o servico `{nome}` nao esta no perfil `{PERFIL_OBS}`. Sem o "
                    "perfil, um arranque de *staging* sem `--profile` levanta-o sempre — e "
                    "o criterio 2 poe o Langfuse atras de um perfil, nao ao lado.",
                )
            )

    texto = (dados.raiz / STAGING).read_text(encoding="utf-8")
    for numero, linha in enumerate(texto.splitlines(), start=1):
        sem_comentario = linha.split("#", 1)[0]
        limpa = sem_comentario.replace('"', "").replace("'", "").lower()
        if re.search(r"kamba_data_class\s*[:=]\s*real(?![a-z0-9_-])", limpa):
            achados.append(
                Achado(
                    "staging-obs-com-dados-reais", STAGING, numero,
                    "`kamba_data_class` vale `real` no compose de *staging*. O "
                    "criterio 2 diz que o perfil `staging-obs` «nao arranca com "
                    "`kamba_data_class=real`», e os *traces* do Langfuse levam "
                    "conversas (ADR-008).",
                )
            )
    return achados



REGRAS = (
    r_conjunto,
    r_denylist,
    r_imagens,
    r_redes_declaradas,
    r_redes_por_servico,
    r_saida_pelo_proxy,
    r_endurecimento,
    r_memoria,
    r_replicas_e_healthz,
    r_portas,
    r_meta_so_no_gwy,
    r_flags_de_licenca,
    r_staging,
)


def varrer(raiz: Path) -> tuple[list[Achado], dict[str, int]]:
    """Todos os achados, e **quanto** se leu.

    O segundo valor nao e decoracao: um verde sobre zero servicos le-se como
    «esta tudo bem», e e a razao pela qual o `env_lint` e o `canon_lint` pagam
    a mesma linha.
    """
    dados = ler(raiz)
    achados: list[Achado] = []
    for regra in REGRAS:
        achados += regra(dados)
    numeros = {
        "servicos": len(dados.prod.servicos),
        "presentes": sum(1 for s in dados.manifesto.values() if s.estado == "presente"),
        "pendentes": sum(1 for s in dados.manifesto.values() if s.estado == "pendente"),
        "proibidos": len(dados.proibidos),
        "destinos": len(dados.allowlist),
        "regras": len(REGRAS),
    }
    return achados, numeros
