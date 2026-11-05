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
    "metrica_sem_produtor",
)

#: Palavras do PromQL que aparecem onde um nome de metrica apareceria e que
#: **nao** sao metricas. Sem esta lista, `increase(...[10m]) > 0` dava
#: `increase` como metrica em falta no catalogo.
PALAVRAS_DO_PROMQL = frozenset(
    """
    abs absent absent_over_time acos acosh and asin asinh atan atanh atan2 avg
    avg_over_time bool bottomk by ceil changes clamp clamp_max clamp_min cos cosh
    count count_over_time count_values day_of_month day_of_week day_of_year
    days_in_month deg delta deriv double_exponential_smoothing end exp floor
    group group_left group_right histogram_avg histogram_count histogram_fraction
    histogram_quantile histogram_stddev histogram_stdvar histogram_sum
    holt_winters hour idelta ignoring increase info irate label_join
    label_replace last_over_time limitk limit_ratio ln log10 log2 mad_over_time
    max max_over_time min min_over_time minute month offset on or pi
    predict_linear present_over_time quantile quantile_over_time rad rate resets
    round scalar sgn sin sinh sort sort_by_label sort_by_label_desc sort_desc
    sqrt start stddev stddev_over_time stdvar stdvar_over_time sum sum_over_time
    tan tanh time timestamp topk unless vector without year inf nan
    """.split()
)

#: Um identificador dentro de uma expressao PromQL.
_IDENTIFICADOR = re.compile(r"\b[a-z_][a-z0-9_]*\b")

#: Uma etiqueta usada dentro de um selector: `{rating="red"}`.
_ETIQUETA_EM_SELECTOR = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=~|!~|!=|=)")

#: O nome de uma metrica escondido num selector `__name__`.
#:
#: **Este e o furo que o `_metricas_citadas` deixava aberto por desenho.** Ele
#: apaga as cadeias antes de varrer, e o nome da metrica dentro de
#: `{__name__="x"}` vive **dentro** de uma cadeia — pelo que qualquer serie do
#: TSDB se podia citar sem passar pelo catalogo, o que anula a premissa da
#: `regras_por_escrever` («uma regra sobre uma serie que ninguem produz nao se
#: escreve»). Medido.
_NOME_POR_SELECTOR = re.compile(r"__name__\s*(?:=~|!~|!=|=)\s*([\"'])(.*?)\1")

#: As duas funcoes que **criam** uma etiqueta em vez de filtrar por ela.
_CRIA_ETIQUETA = re.compile(r"\blabel_(?:replace|join)\s*\(")

#: As clausulas que nomeiam **etiquetas** e nao metricas.
#:
#: Sem isto, o `on(job, instance)` da `latencia_de_resposta_alta` dava `job` e
#: `instance` como metricas em falta no catalogo — dois falsos positivos no meu
#: proprio ficheiro de regras, que foi como este caso apareceu.
#:
#: E o mesmo tratamento melhora uma mensagem: um `sum by (contact_id)` era
#: apanhado, mas pela regra errada («a expressao cita `contact_id`, que nao esta
#: no catalogo») — e quem le aquilo acrescenta o `contact_id` ao catalogo e o
#: achado desaparece. Lido como **etiqueta**, a mensagem passa a ser a certa.
_AGRUPAMENTO = re.compile(
    r"\b(?:on|ignoring|by|without|group_left|group_right)\s*\(([^)]*)\)"
)


def _argumentos(texto: str) -> list[str]:
    """Reparte a lista de argumentos de uma chamada, ao nivel de topo.

    `texto` comeca **depois** do parentese de abertura. Respeita parenteses,
    chaves, parentesis rectos e cadeias — porque o primeiro argumento de um
    `label_replace` e um vector que pode trazer tudo isso dentro
    (`label_replace(sum(x{a="1"}), "dst", ...)`), e uma reparticao por virgulas
    com `[^,]+` apanhava `"1"` em vez de `"dst"`.
    """
    argumentos: list[str] = []
    actual: list[str] = []
    profundidade = 0
    aspa = ""
    for caractere in texto:
        if aspa:
            actual.append(caractere)
            if caractere == aspa:
                aspa = ""
            continue
        if caractere in "\"'":
            aspa = caractere
            actual.append(caractere)
        elif caractere in "([{":
            profundidade += 1
            actual.append(caractere)
        elif caractere in ")]}":
            if profundidade == 0:
                argumentos.append("".join(actual))
                return argumentos
            profundidade -= 1
            actual.append(caractere)
        elif caractere == "," and profundidade == 0:
            argumentos.append("".join(actual))
            actual = []
        else:
            actual.append(caractere)
    argumentos.append("".join(actual))
    return argumentos


def _etiquetas_criadas(expressao: str) -> set[str]:
    """As etiquetas que a expressao **cria**, nao as que filtra.

    O `label_replace(v, dst, repl, src, regex)` e o `label_join(v, dst, sep,
    src...)` tem o nome novo no **segundo** argumento. E a forma mais natural de
    **por** um identificador numa serie, e era a que escapava inteira: o nome
    viaja dentro de uma cadeia, logo o `_metricas_citadas` apaga-o e o
    `_etiquetas_citadas` nao tem operador para o casar. Medido nas duas
    superficies.
    """
    criadas: set[str] = set()
    for achado in _CRIA_ETIQUETA.finditer(str(expressao)):
        argumentos = _argumentos(str(expressao)[achado.end() :])
        if len(argumentos) < 2:
            continue
        destino = argumentos[1].strip()
        if len(destino) >= 2 and destino[0] in "\"'" and destino[-1] == destino[0]:
            criadas.add(destino[1:-1])
    return criadas


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

    # **Um nome permitido por nome tem de declarar lista fechada**, e nunca
    # basta um tecto.
    #
    # Era o furo que esvaziava a regra 1. O `tenant_id` passa pelo nome (e o que
    # o criterio 3 escreve), e com `cardinalidade_maxima: 64` passava tambem a
    # regra do dominio **sem que nenhum valor fosse olhado** — porque a gramatica
    # do valor so corre no ramo da lista. Um tecto de 64 e 64 UUIDs: exactamente
    # a re-identificacao que o `OBS-I` recusa. Medido.
    #
    # A lista fechada forca os valores a existirem, e e la que a gramatica os
    # apanha. Para um `tenant_id` isso quer dizer, na pratica, que ele nao entra:
    # nenhum conjunto de UUIDs casa `^[a-z][a-z0-9_]{1,62}$`. E o resultado certo,
    # e a saida continua a ser a que as emendas 1.21 e 1.25 escreveram — o
    # por-tenant sai de consulta.
    if nome in ETIQUETAS_PERMITIDAS_POR_NOME and dominio is None:
        achados.append(
            Achado(
                "etiqueta_sem_dominio",
                sitio,
                (
                    f"`{nome}` e permitido pelo nome e por isso tem de declarar "
                    "`dominio` (lista fechada), nunca so `cardinalidade_maxima`: "
                    "um tecto nao faz olhar valor nenhum, e 64 UUIDs cabem num "
                    "tecto de 64"
                ),
            )
        )
        return achados

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
        # `isinstance(True, int)` e **verdade** em Python, pelo que um
        # `cardinalidade_maxima: true` passava como se fosse o inteiro 1. O
        # `type(...) is int` e o que recusa o booleano — e e a mesma disciplina
        # que o `logger` desta casa usa («tipos exactos, nunca `isinstance`»).
        if type(tecto) is not int or tecto <= 0:
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
    # Os nomes escondidos em `__name__` leem-se **antes** de apagar as cadeias,
    # que e onde eles vivem.
    escondidos = {achado.group(2) for achado in _NOME_POR_SELECTOR.finditer(str(expressao))}
    sem_cadeias = re.sub(r'"[^"]*"', '""', str(expressao))
    sem_cadeias = re.sub(r"'[^']*'", "''", sem_cadeias)
    # As clausulas de agrupamento saem **antes** da varredura: o que esta dentro
    # delas sao nomes de etiqueta, e lidos como metricas davam falsos positivos.
    sem_agrupamento = _AGRUPAMENTO.sub("", sem_cadeias)
    sem_etiquetas = _ETIQUETA_EM_SELECTOR.sub("", sem_agrupamento)
    candidatos = set(_IDENTIFICADOR.findall(sem_etiquetas))
    return {c for c in candidatos if c not in PALAVRAS_DO_PROMQL} | escondidos


def _etiquetas_citadas(expressao: str) -> set[str]:
    """As etiquetas usadas em selectores, para a regra do nome proibido.

    Uma regra pode filtrar por uma etiqueta que o catalogo nao declara — e e
    por ai que um `contact_id` entraria numa expressao sem passar pelo catalogo.
    """
    nos_selectores = set(_ETIQUETA_EM_SELECTOR.findall(str(expressao)))
    # E as que uma clausula de agrupamento nomeia: um `sum by (contact_id)`
    # agrupa **por** um identificador, que e a mesma fuga que um selector.
    nos_agrupamentos = {
        nome.strip()
        for achado in _AGRUPAMENTO.finditer(str(expressao))
        for nome in achado.group(1).split(",")
        if nome.strip()
    }
    return nos_selectores | nos_agrupamentos


def _verificar_regra(
    regra: dict, onde: str, conhecidas: set[str], raiz: Path, servidas: set[str] | None = None
) -> list[Achado]:
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

    achados.extend(
        _verificar_expressao(
            regra.get("expr", ""),
            sitio,
            conhecidas,
            servidas if servidas is not None else conhecidas,
            "a expressao",
        )
    )
    return achados


#: As chaves de um painel do Grafana que levam PromQL.
#:
#: O `expr` e o obvio. O `query` **nao** e: uma variavel de painel vive em
#: `templating.list[].query` e nem se chama `expr`, e uma anotacao vive em
#: `annotations.list[].expr` — as duas **fora** de `panels`.
#:
#: Era o furo: a primeira versao descia a `panels` e argumentava, na propria
#: *docstring*, que o fazia «porque e exactamente onde alguem poria a consulta
#: que nao quer que seja vista». O sitio melhor para isso era o `templating`, e
#: esse nao era visto. Medido com um painel cujo `templating` filtrava por
#: `contact_id`: zero achados.
CHAVES_COM_PROMQL = ("expr", "query")


def _expressoes_do_painel(dados: object) -> list[str]:
    """As expressoes de um painel, **do documento inteiro** e a qualquer profundidade.

    Varre o documento todo e nao so `panels`, pela razao da nota do
    `CHAVES_COM_PROMQL`: as consultas de uma variavel e de uma anotacao vivem
    fora de `panels`, e um painel pode ainda ter `panels` dentro de uma `row`.
    O preco e um falso positivo possivel num `query` que nao seja PromQL — que e
    visivel e barato, ao contrario de uma consulta que ninguem le.
    """
    encontradas: list[str] = []
    if isinstance(dados, dict):
        for chave, valor in dados.items():
            if chave in CHAVES_COM_PROMQL and isinstance(valor, str):
                encontradas.append(valor)
            else:
                encontradas.extend(_expressoes_do_painel(valor))
    elif isinstance(dados, list):
        for item in dados:
            encontradas.extend(_expressoes_do_painel(item))
    return encontradas


def _verificar_expressao(
    expressao: str, onde: str, conhecidas: set[str], servidas: set[str], sujeito: str
) -> list[Achado]:
    """As verificacoes que valem para uma expressao, venha de regra ou de painel.

    Estava duplicada entre o `_verificar_regra` e o `_verificar_painel`, e a
    duplicacao custou dois furos: o `label_replace` e o `__name__` foram
    fechados num sitio e nao no outro durante a mesma revisao. Uma funcao, duas
    chamadas.
    """
    achados: list[Achado] = []

    for metrica in sorted(_metricas_citadas(expressao)):
        if metrica not in conhecidas:
            achados.append(
                Achado(
                    "metrica_fora_do_catalogo",
                    onde,
                    (
                        f"{sujeito} cita `{metrica}`, que nao esta em {CATALOGO}. "
                        "Um alerta sobre uma metrica que ninguem expoe nunca dispara, "
                        "e um painel sobre ela mostra um grafico vazio para sempre"
                    ),
                )
            )
        elif metrica not in servidas:
            achados.append(
                Achado(
                    "metrica_sem_produtor",
                    onde,
                    (
                        f"{sujeito} cita `{metrica}`, que esta no catalogo com "
                        "`exposta_por` vazio — nenhum processo a serve. O catalogo "
                        "promete que «nenhuma regra de alerta a pode citar»; esta "
                        "e a verificacao que o cumpre"
                    ),
                )
            )

    for etiqueta in sorted(_etiquetas_citadas(expressao)):
        if etiqueta in ETIQUETAS_PROIBIDAS:
            achados.append(
                Achado(
                    "etiqueta_proibida",
                    onde,
                    f"{sujeito} filtra por `{etiqueta}`: {ETIQUETAS_PROIBIDAS[etiqueta]}",
                )
            )

    for etiqueta in sorted(_etiquetas_criadas(expressao)):
        if etiqueta in ETIQUETAS_PROIBIDAS:
            achados.append(
                Achado(
                    "etiqueta_proibida",
                    onde,
                    (
                        f"{sujeito} **cria** a etiqueta `{etiqueta}` com um "
                        f"`label_replace`/`label_join`: {ETIQUETAS_PROIBIDAS[etiqueta]}. "
                        "Criar e pior do que filtrar: filtrar le um identificador que "
                        "ja existe, criar po-lo numa serie nova"
                    ),
                )
            )
        elif not GRAMATICA_DA_ETIQUETA.match(etiqueta):
            achados.append(
                Achado(
                    "etiqueta_fora_da_gramatica",
                    onde,
                    f"{sujeito} cria `{etiqueta}`, que nao casa {GRAMATICA_DA_ETIQUETA.pattern}",
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

    # As que **algum processo serve**. O catalogo promete, por escrito, que uma
    # metrica com `exposta_por` vazio nao pode ser citada por regra nenhuma — «e
    # o que o *lint* verifica». Nao verificava: o `conhecidas` era o conjunto de
    # todos os nomes, sem filtro, e a garantia nao existia em codigo. Medido.
    #
    # Uma chave `exposta_por` **ausente** conta como servida: as entradas
    # sinteticas do Prometheus (`up`, `scrape_duration_seconds`) nao vem de
    # codigo nosso e a ausencia da chave nao e uma declaracao de que ninguem as
    # serve. O que a regra apanha e a **lista vazia**, que e a declaracao.
    servidas = {
        str(m["nome"])
        for m in catalogo["metricas"]
        if isinstance(m, dict) and "nome" in m and m.get("exposta_por", ["?"]) != []
    }

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
                achados.extend(_verificar_regra(regra, onde, conhecidas, raiz, servidas))

    if total_de_regras == 0:
        raise ConfiguracaoInvalida(f"{REGRAS}: zero regras lidas")

    pasta_de_paineis = raiz / PAINEIS
    if not pasta_de_paineis.is_dir():
        raise ConfiguracaoInvalida(f"{PAINEIS} nao existe")
    # `rglob` e nao `glob`: o *file provider* do Grafana varre a pasta
    # **recursivamente**, e o `foldersFromFilesStructure: false` do
    # `provisionamento.yaml` so decide se as subpastas se tornam pastas do
    # Grafana — nao se sao lidas. Com `glob`, um painel em `paineis/sub/mau.json`
    # era provisionado e nao era verificado. Medido.
    ficheiros_de_painel = sorted(pasta_de_paineis.rglob("*.json"))
    if not ficheiros_de_painel:
        raise ConfiguracaoInvalida(f"{PAINEIS} nao tem paineis")

    total_de_consultas = 0
    for ficheiro in ficheiros_de_painel:
        onde = f"{PAINEIS}/{ficheiro.relative_to(pasta_de_paineis).as_posix()}"
        try:
            dados = json.loads(ficheiro.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erro:
            raise ConfiguracaoInvalida(f"{onde} nao se le: {erro}") from erro
        for expressao in _expressoes_do_painel(dados):
            total_de_consultas += 1
            achados.extend(
                _verificar_expressao(expressao, onde, conhecidas, servidas, "o painel")
            )

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
