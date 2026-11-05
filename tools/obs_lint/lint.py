"""O *lint* de observabilidade do KAM-080 — cardinalidade e runbooks.

Duas verificacoes que o bloco pede por extenso, e que nao se separam em duas
ferramentas porque leem o mesmo par de superficies:

    criterio 3   «`tenant_id` permitido como etiqueta; `contact_id`, telefone e
                 BSUID proibidos»
    criterio 4   «as 12 regras existem com severidade P1/P2/P3 e `runbook_url`
                 valido»; «CI falha para alerta sem runbook»

As superficies sao duas:

    ops/metricas/catalogo.yaml                 o catalogo de metricas
    infra/compose/prometheus/regras/*.yml      as regras de alerta

## Porque e que a cardinalidade se mede no catalogo e nao no codigo

Porque medir no codigo exigia ler TypeScript, e um varredor de TypeScript cego
as cadeias e um defeito conhecido desta casa: o `//` de um `"https://…"` apaga o
resto da linha e o `/*` de um `api.use("/internal/*", …)` abre um comentario
falso que engole tudo ate ao proximo `*/`. Foi medido no KAM-066, e custou um
portao que dava verde sobre 24 de 31 rotas.

O catalogo evita o problema em vez de o resolver: e um YAML, declara cada
etiqueta com o seu dominio, e e ele que o painel e a regra citam. **O limite
disto esta escrito e nao se esconde:** este *lint* prova que o catalogo e as
regras respeitam a politica; **nao** prova que o codigo nao declara uma etiqueta
que o catalogo nao conhece. Quem fecha esse lado sao as bibliotecas de metricas,
que ja recusam por gramatica uma etiqueta que nao case `^[a-z][a-z0-9_]{1,62}$`
(`packages/core-ts/src/ten/metricas.ts`, e o mesmo em Python) — e um `tenant_id`
e um UUID com hifenes, que nao casa, pelo que **a chamada levanta**.

## A politica, e a distincao que ela codifica

O `OBS-I` de `docs/seguranca/ameacas_stride.md` — que vive no repositorio
privado — **recusa identificadores, nao dimensoes pequenas**. A frase e do
dicionario, §3.16, na linha da `channel_quality{rating}`: uma etiqueta de tres
valores fechados passa onde uma de *tenant* nao passava.

Daqui saem as duas regras, que sao diferentes e e preciso que o sejam:

1. **nome** — um nome que e um identificador recusa-se (`contact_id`, telefone,
   BSUID, `wamid`, …). O `tenant_id` **passa pelo nome**, que e o que o criterio
   3 escreve a letra;
2. **dominio** — toda a etiqueta declara uma lista fechada de valores, ou um
   tecto explicito. E esta que apanha o defeito a serio: uma etiqueta chamada
   `tenant_id` passa a regra 1 e morre nesta, porque o conjunto dos *tenants*
   nao e fechado nem cabe no tecto.

A regra 2 e que torna a 1 honesta. Sem ela, o criterio 3 lia-se como «basta nao
usar aqueles quatro nomes», e uma etiqueta `cliente` com um UUID dentro passava
limpa.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import kamba_yaml

#: O catalogo de metricas. Unica fonte sobre que etiqueta cada metrica leva.
CATALOGO = "ops/metricas/catalogo.yaml"

#: A pasta das regras de alerta, no formato de ficheiro de regras do Prometheus.
REGRAS = "infra/compose/prometheus/regras"

#: A pasta dos paineis como codigo (criterio 6), em JSON do Grafana.
#:
#: E a terceira superficie, e entra pela mesma razao que as outras duas: uma
#: consulta de painel e um sitio onde uma etiqueta proibida cabe. Um `contact_id`
#: num `expr` de painel nao passa por regra de alerta nenhuma e vazava do mesmo
#: modo — e um painel que cita uma metrica que ninguem expoe mostra um grafico
#: vazio para sempre, que e o irmao do alerta que nunca dispara.
PAINEIS = "ops/paineis"

#: Onde vivem os *stubs* de runbook, e a raiz contra a qual um `runbook_url` se
#: resolve.
RUNBOOKS = "docs/runbooks"

#: O prefixo que um `runbook_url` tem de ter. E o repositorio publico, na `main`.
#: Nao se aceita um caminho relativo: o `runbook_url` e lido por quem esta a
#: atender um alerta num telemovel, e tem de ser clicavel a partir do
#: Alertmanager.
PREFIXO_DO_RUNBOOK = (
    "https://github.com/albinoJimy/kamba-plataforma/blob/main/docs/runbooks/"
)

#: As severidades, exactamente as do `docs/tecnica/09` §9.2.
SEVERIDADES = ("P1", "P2", "P3")

#: A gramatica de um nome de etiqueta. E a mesma das bibliotecas de metricas
#: (`ten/metricas.ts:53`, `ten/metricas.py:45`, `agr/metricas.py:559`), e esta
#: repetida aqui de proposito: as tres sao a mesma regra e nenhuma importa as
#: outras, porque o *lint* corre antes de qualquer instalacao.
GRAMATICA_DA_ETIQUETA = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

#: Quantos valores se aceitam no dominio de uma etiqueta. O mesmo numero do
#: `MAXIMO_DE_SERIES` das bibliotecas.
MAXIMO_DE_VALORES = 64

#: Nomes de etiqueta recusados por serem identificadores. A lista e por nome e
#: nao por forma, porque e a forma que a regra do dominio apanha: estes estao
#: aqui para que a mensagem de erro diga **qual** identificador e porque.
#:
#: Os tres primeiros sao os que o criterio 3 nomeia; os restantes sao os
#: identificadores que este repositorio ja tem e que cairiam na mesma classe.
ETIQUETAS_PROIBIDAS: dict[str, str] = {
    "contact_id": "identificador de contacto (criterio 3)",
    "telefone": "numero de telefone (criterio 3); e dado pessoal directo",
    "phone": "numero de telefone (criterio 3); e dado pessoal directo",
    "msisdn": "numero de telefone (criterio 3); e dado pessoal directo",
    "bsuid": "identificador de utilizador da Meta (criterio 3)",
    "contact_hmac": (
        "pseudonimizacao, nao anonimizacao: o espaco de numeros moveis "
        "angolanos e enumeravel (`docs/tecnica/08` §7.2)"
    ),
    "contact_hmac_prefix": "prefixo do HMAC do contacto; continua a ser do contacto",
    "wamid": "identificador de mensagem da Meta; cresce com o trafego",
    "msg_id": "identificador de mensagem; cresce com o trafego",
    "turn_id": "identificador de turno; cresce com o trafego",
    "conversation_id": "identificador de conversa; cresce com o trafego",
    "channel_id": "identificador de canal; cresce com os canais",
    "phone_number_id": "identificador do numero na Meta; e por canal",
    "user_id": "identificador de pessoa",
    "email": "dado pessoal directo",
    "ip": "dado pessoal indirecto, e cresce sem limite",
}

#: Nomes que passam a regra 1 **pelo nome**, e so por ela.
#:
#: O `tenant_id` esta aqui porque o criterio 3 o escreve: «`tenant_id` permitido
#: como etiqueta». Passa a regra do nome e **continua sujeito a regra do
#: dominio** — e e la que ele cai, porque o conjunto dos *tenants* nao e fechado.
#: As emendas 1.21 e 1.25 do dicionario ja tinham tomado esta decisao para a
#: `meta_cost_usd_total{tenant}` e para as metricas do KAM-023, e a saida que as
#: duas escolheram foi a mesma: **o por-tenant sai de consulta SQL**.
ETIQUETAS_PERMITIDAS_POR_NOME = ("tenant_id",)

#: As regras, pelo nome com que aparecem num achado. Fixa no codigo e **nao**
#: lida das fixtures: um manifesto vazio nao pode dar «tudo verde».
REGRAS_OBRIGATORIAS = (
    "etiqueta_proibida",
    "etiqueta_sem_dominio",
    "dominio_grande",
    "etiqueta_fora_da_gramatica",
    "valor_fora_da_gramatica",
    "alerta_sem_runbook",
    "runbook_inexistente",
    "severidade_invalida",
    "metrica_fora_do_catalogo",
)

#: Palavras do PromQL que aparecem onde um nome de metrica apareceria e que
#: **nao** sao metricas. Sem esta lista, `increase(...[10m]) > 0` dava
#: `increase` como metrica em falta no catalogo.
PALAVRAS_DO_PROMQL = frozenset(
    """
    abs absent absent_over_time avg avg_over_time bool by ceil changes clamp
    clamp_max clamp_min count count_over_time count_values day_of_month
    day_of_week day_of_year days_in_month delta deriv exp floor group group_left
    group_right histogram_quantile holt_winters hour idelta ignoring increase
    irate label_join label_replace last_over_time ln log10 log2 max max_over_time
    min min_over_time minute month offset on or and unless predict_linear
    present_over_time quantile quantile_over_time rate resets round scalar sgn
    sort sort_desc sqrt stddev stddev_over_time stdvar stdvar_over_time sum
    sum_over_time time timestamp topk bottomk vector without year inf nan
    """.split()
)

#: Um identificador dentro de uma expressao PromQL.
_IDENTIFICADOR = re.compile(r"\b[a-z_][a-z0-9_]*\b")

#: Uma etiqueta usada dentro de um selector: `{rating="red"}`.
_ETIQUETA_EM_SELECTOR = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=~|!~|!=|=)")


class ConfiguracaoInvalida(Exception):
    """A superficie nao se le, ou nao ha nada para ler.

    Separa-se de um achado pela razao do `canon_lint` e do `env_lint`: um
    catalogo que nao se le **nao pode parecer um catalogo conforme**. O `cli`
    traduz isto em codigo de saida 2.
    """


@dataclass(frozen=True)
class Achado:
    """Um defeito, com o sitio onde esta.

    `onde` e um caminho relativo a raiz mais o nome do objecto — nunca um valor
    de etiqueta, pela mesma razao por que o `Achado` do X-11 nao leva o valor:
    uma mensagem de erro que repete o identificador escreve-o no *log* do CI.
    """

    regra: str
    onde: str
    detalhe: str

    def __str__(self) -> str:
        return f"{self.onde}: {self.regra} — {self.detalhe}"


def _ler(caminho: Path, onde: str) -> dict:
    try:
        return kamba_yaml.load_file(caminho)
    except (OSError, kamba_yaml.YamlSubsetError) as erro:
        raise ConfiguracaoInvalida(f"{onde} nao se le: {erro}") from erro


def _etiquetas_do_catalogo(dados: dict, onde: str) -> list[tuple[str, dict]]:
    """Devolve `(nome_da_metrica, etiqueta)` para cada etiqueta declarada."""
    metricas = dados.get("metricas")
    if not isinstance(metricas, list) or not metricas:
        raise ConfiguracaoInvalida(f"{onde}: `metricas` vazia ou ausente")
    pares: list[tuple[str, dict]] = []
    for metrica in metricas:
        if not isinstance(metrica, dict) or "nome" not in metrica:
            raise ConfiguracaoInvalida(f"{onde}: uma metrica sem `nome`")
        etiquetas = metrica.get("etiquetas") or []
        if not isinstance(etiquetas, list):
            raise ConfiguracaoInvalida(f"{onde}: `etiquetas` de {metrica['nome']} nao e lista")
        for etiqueta in etiquetas:
            if not isinstance(etiqueta, dict):
                raise ConfiguracaoInvalida(
                    f"{onde}: etiqueta de {metrica['nome']} nao e um mapa"
                )
            pares.append((str(metrica["nome"]), etiqueta))
    return pares


def _verificar_etiqueta(nome_da_metrica: str, etiqueta: dict, onde: str) -> list[Achado]:
    """As duas regras de cardinalidade, por esta ordem.

    A ordem importa para a mensagem: um `contact_id` sem dominio devia dizer
    «identificador», e nao «falta o dominio», que e verdade e nao e a razao.
    """
    achados: list[Achado] = []
    nome = str(etiqueta.get("nome", "")).strip()
    sitio = f"{onde}:{nome_da_metrica}{{{nome or '?'}}}"

    if not nome:
        return [Achado("etiqueta_fora_da_gramatica", sitio, "etiqueta sem `nome`")]

    if nome in ETIQUETAS_PROIBIDAS:
        return [
            Achado(
                "etiqueta_proibida",
                sitio,
                f"`{nome}` nao entra em etiqueta: {ETIQUETAS_PROIBIDAS[nome]}",
            )
        ]

    if not GRAMATICA_DA_ETIQUETA.match(nome):
        achados.append(
            Achado(
                "etiqueta_fora_da_gramatica",
                sitio,
                f"`{nome}` nao casa {GRAMATICA_DA_ETIQUETA.pattern}",
            )
        )
        return achados

    dominio = etiqueta.get("dominio")
    tecto = etiqueta.get("cardinalidade_maxima")

    if dominio is None and tecto is None:
        achados.append(
            Achado(
                "etiqueta_sem_dominio",
                sitio,
                (
                    f"`{nome}` nao declara `dominio` (lista fechada) nem "
                    "`cardinalidade_maxima`. O `OBS-I` recusa identificadores e "
                    "aceita dimensoes pequenas — e a diferenca entre as duas e "
                    "exactamente esta declaracao"
                ),
            )
        )
        return achados

    if dominio is not None:
        if not isinstance(dominio, list) or not dominio:
            achados.append(
                Achado("etiqueta_sem_dominio", sitio, f"`dominio` de `{nome}` vazio ou nao e lista")
            )
        elif len(dominio) > MAXIMO_DE_VALORES:
            achados.append(
                Achado(
                    "dominio_grande",
                    sitio,
                    f"`{nome}` declara {len(dominio)} valores, acima do tecto de {MAXIMO_DE_VALORES}",
                )
            )
        else:
            # A terceira regra, e a que fecha o buraco que as duas primeiras
            # deixavam aberto.
            #
            # Sem ela, `tenant_id` passava a regra do nome (criterio 3), passava
            # a do dominio declarando 64 UUIDs, e re-identificava na mesma. O
            # valor tem de casar a **mesma gramatica** que as bibliotecas de
            # metricas ja impoem em execucao — e um UUID canonico tem hifenes e
            # comeca frequentemente por digito, pelo que nao casa.
            #
            # E por isto que o `tenant_id` pode estar nas permitidas por nome
            # sem que isso abra porta nenhuma: o nome passa, o valor e que nao.
            for valor in dominio:
                if not GRAMATICA_DA_ETIQUETA.match(str(valor)):
                    achados.append(
                        Achado(
                            "valor_fora_da_gramatica",
                            sitio,
                            (
                                f"um valor do dominio de `{nome}` nao casa "
                                f"{GRAMATICA_DA_ETIQUETA.pattern}. E a gramatica que as "
                                "bibliotecas de metricas ja impoem: um UUID nao casa, e e "
                                "assim que um identificador fica de fora mesmo quando o "
                                "nome da etiqueta e permitido"
                            ),
                        )
                    )
                    break
    if tecto is not None:
        if not isinstance(tecto, int) or tecto <= 0:
            achados.append(
                Achado("etiqueta_sem_dominio", sitio, f"`cardinalidade_maxima` de `{nome}` invalida")
            )
        elif tecto > MAXIMO_DE_VALORES:
            achados.append(
                Achado(
                    "dominio_grande",
                    sitio,
                    f"`{nome}` pede tecto {tecto}, acima de {MAXIMO_DE_VALORES}",
                )
            )
    return achados


def _metricas_citadas(expressao: str) -> set[str]:
    """Os nomes de metrica de uma expressao PromQL.

    **O limite esta aqui escrito.** Isto nao e um parser de PromQL: e uma
    varredura de identificadores menos as palavras da linguagem. Pode apanhar a
    mais (um valor de etiqueta sem aspas, que o PromQL nao permite) e, se o
    Prometheus ganhar uma funcao nova, pode dar essa funcao como metrica em
    falta. A correccao, nesse dia, e acrescentar a palavra — e o erro e visivel
    e barato, ao contrario de o lint deixar passar uma metrica inexistente.
    """
    sem_cadeias = re.sub(r'"[^"]*"', '""', str(expressao))
    sem_cadeias = re.sub(r"'[^']*'", "''", sem_cadeias)
    sem_etiquetas = _ETIQUETA_EM_SELECTOR.sub("", sem_cadeias)
    candidatos = set(_IDENTIFICADOR.findall(sem_etiquetas))
    return {c for c in candidatos if c not in PALAVRAS_DO_PROMQL}


def _etiquetas_citadas(expressao: str) -> set[str]:
    """As etiquetas usadas em selectores, para a regra do nome proibido.

    Uma regra pode filtrar por uma etiqueta que o catalogo nao declara — e e
    por ai que um `contact_id` entraria numa expressao sem passar pelo catalogo.
    """
    return set(_ETIQUETA_EM_SELECTOR.findall(str(expressao)))


def _verificar_regra(regra: dict, onde: str, conhecidas: set[str], raiz: Path) -> list[Achado]:
    achados: list[Achado] = []
    nome = str(regra.get("alert") or regra.get("record") or "?")
    sitio = f"{onde}:{nome}"

    if "alert" not in regra:
        # Uma regra de gravacao (`record:`) nao e um alerta e nao leva runbook.
        # Continua sujeita a cardinalidade, que e o que o resto desta funcao faz.
        pass
    else:
        etiquetas = regra.get("labels") or {}
        severidade = str(etiquetas.get("severity", "")).strip()
        if severidade not in SEVERIDADES:
            achados.append(
                Achado(
                    "severidade_invalida",
                    sitio,
                    f"`severity` e {severidade!r}; esperava uma de {', '.join(SEVERIDADES)}",
                )
            )

        anotacoes = regra.get("annotations") or {}
        url = str(anotacoes.get("runbook_url", "")).strip()
        if not url:
            achados.append(
                Achado(
                    "alerta_sem_runbook",
                    sitio,
                    (
                        "sem `runbook_url`. A regra do `docs/tecnica/09` §9.2 e "
                        "«alerta sem runbook e removido»"
                    ),
                )
            )
        elif not url.startswith(PREFIXO_DO_RUNBOOK):
            achados.append(
                Achado(
                    "runbook_inexistente",
                    sitio,
                    f"`runbook_url` nao comeca por {PREFIXO_DO_RUNBOOK}",
                )
            )
        else:
            ficheiro = url[len(PREFIXO_DO_RUNBOOK) :]
            if not (raiz / RUNBOOKS / ficheiro).is_file():
                achados.append(
                    Achado(
                        "runbook_inexistente",
                        sitio,
                        f"`runbook_url` aponta para {RUNBOOKS}/{ficheiro}, que nao existe",
                    )
                )

    expressao = regra.get("expr", "")
    for metrica in sorted(_metricas_citadas(expressao)):
        if metrica not in conhecidas:
            achados.append(
                Achado(
                    "metrica_fora_do_catalogo",
                    sitio,
                    (
                        f"a expressao cita `{metrica}`, que nao esta em {CATALOGO}. "
                        "Um alerta sobre uma metrica que ninguem expoe nunca dispara, "
                        "e um alerta que nunca dispara parece cobertura"
                    ),
                )
            )
    for etiqueta in sorted(_etiquetas_citadas(expressao)):
        if etiqueta in ETIQUETAS_PROIBIDAS:
            achados.append(
                Achado(
                    "etiqueta_proibida",
                    sitio,
                    f"a expressao filtra por `{etiqueta}`: {ETIQUETAS_PROIBIDAS[etiqueta]}",
                )
            )
    return achados


def _expressoes_do_painel(dados: object, caminho: str = "panels") -> list[str]:
    """As expressoes de um painel, a qualquer profundidade.

    Desce recursivamente porque um painel pode ter `panels` dentro de uma `row`,
    e uma varredura so do primeiro nivel perdia as consultas de dentro das
    linhas — que e exactamente onde alguem poria a consulta que nao quer que
    seja vista.
    """
    encontradas: list[str] = []
    if isinstance(dados, dict):
        for chave, valor in dados.items():
            if chave == "expr" and isinstance(valor, str):
                encontradas.append(valor)
            else:
                encontradas.extend(_expressoes_do_painel(valor, f"{caminho}.{chave}"))
    elif isinstance(dados, list):
        for item in dados:
            encontradas.extend(_expressoes_do_painel(item, caminho))
    return encontradas


def _verificar_painel(
    expressao: str, onde: str, conhecidas: set[str]
) -> list[Achado]:
    achados: list[Achado] = []
    for metrica in sorted(_metricas_citadas(expressao)):
        if metrica not in conhecidas:
            achados.append(
                Achado(
                    "metrica_fora_do_catalogo",
                    onde,
                    (
                        f"o painel cita `{metrica}`, que nao esta em {CATALOGO}. "
                        "Um painel sobre uma metrica que ninguem expoe mostra um "
                        "grafico vazio para sempre"
                    ),
                )
            )
    for etiqueta in sorted(_etiquetas_citadas(expressao)):
        if etiqueta in ETIQUETAS_PROIBIDAS:
            achados.append(
                Achado(
                    "etiqueta_proibida",
                    onde,
                    f"o painel filtra por `{etiqueta}`: {ETIQUETAS_PROIBIDAS[etiqueta]}",
                )
            )
    return achados


def verificar(raiz: Path) -> tuple[list[Achado], dict[str, int]]:
    """Corre as duas verificacoes sobre as duas superficies.

    Levanta `ConfiguracaoInvalida` quando uma superficie nao existe ou esta
    vazia. **Passar sem ter lido nada nao e passar** — e a disciplina que o
    `log_policy` e o `env_lint` ja impoem, e existe porque um verde sobre zero
    ficheiros le-se como «esta tudo bem».
    """
    caminho_do_catalogo = raiz / CATALOGO
    if not caminho_do_catalogo.is_file():
        raise ConfiguracaoInvalida(f"{CATALOGO} nao existe")
    catalogo = _ler(caminho_do_catalogo, CATALOGO)

    pasta = raiz / REGRAS
    if not pasta.is_dir():
        raise ConfiguracaoInvalida(f"{REGRAS} nao existe")
    ficheiros = sorted(p for p in pasta.iterdir() if p.suffix in (".yml", ".yaml"))
    if not ficheiros:
        raise ConfiguracaoInvalida(f"{REGRAS} nao tem ficheiros de regras")

    achados: list[Achado] = []

    pares = _etiquetas_do_catalogo(catalogo, CATALOGO)
    for nome_da_metrica, etiqueta in pares:
        achados.extend(_verificar_etiqueta(nome_da_metrica, etiqueta, CATALOGO))

    conhecidas = {str(m["nome"]) for m in catalogo["metricas"] if isinstance(m, dict) and "nome" in m}

    total_de_regras = 0
    total_de_alertas = 0
    for ficheiro in ficheiros:
        onde = f"{REGRAS}/{ficheiro.name}"
        dados = _ler(ficheiro, onde)
        grupos = dados.get("groups")
        if not isinstance(grupos, list) or not grupos:
            raise ConfiguracaoInvalida(f"{onde}: sem `groups`")
        for grupo in grupos:
            if not isinstance(grupo, dict):
                raise ConfiguracaoInvalida(f"{onde}: um grupo que nao e mapa")
            regras = grupo.get("rules") or []
            if not isinstance(regras, list):
                raise ConfiguracaoInvalida(f"{onde}: `rules` nao e lista")
            for regra in regras:
                if not isinstance(regra, dict):
                    raise ConfiguracaoInvalida(f"{onde}: uma regra que nao e mapa")
                total_de_regras += 1
                if "alert" in regra:
                    total_de_alertas += 1
                achados.extend(_verificar_regra(regra, onde, conhecidas, raiz))

    if total_de_regras == 0:
        raise ConfiguracaoInvalida(f"{REGRAS}: zero regras lidas")

    pasta_de_paineis = raiz / PAINEIS
    if not pasta_de_paineis.is_dir():
        raise ConfiguracaoInvalida(f"{PAINEIS} nao existe")
    ficheiros_de_painel = sorted(pasta_de_paineis.glob("*.json"))
    if not ficheiros_de_painel:
        raise ConfiguracaoInvalida(f"{PAINEIS} nao tem paineis")

    total_de_consultas = 0
    for ficheiro in ficheiros_de_painel:
        onde = f"{PAINEIS}/{ficheiro.name}"
        try:
            dados = json.loads(ficheiro.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erro:
            raise ConfiguracaoInvalida(f"{onde} nao se le: {erro}") from erro
        for expressao in _expressoes_do_painel(dados.get("panels")):
            total_de_consultas += 1
            achados.extend(_verificar_painel(expressao, onde, conhecidas))

    numeros = {
        "metricas": len(conhecidas),
        "etiquetas": len(pares),
        "ficheiros_de_regras": len(ficheiros),
        "regras": total_de_regras,
        "alertas": total_de_alertas,
        "paineis": len(ficheiros_de_painel),
        "consultas_de_painel": total_de_consultas,
    }
    return achados, numeros
