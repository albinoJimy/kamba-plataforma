"""As seis metricas do IDX (KAM-193, KAM-063 e KAM-194; DoD «metricas» do KAM-061).

    idx_query_ms{ramo,modo}           gauge    duracao da ultima pesquisa, em ms
    idx_results_total                 counter  candidatos devolvidos, somados
    idx_mode{modo}                    counter  pesquisas, por modo (`hibrido` ou `lexical`)
    embedding_latency_ms{uso}         gauge    duracao da ultima chamada de embeddings
    embedding_fallback_total{motivo}  counter  consultas que cairam em lexical, por motivo
    idx_reindexed_total               counter  documentos reescritos pelo ciclo da
                                               reindexacao (KAM-194), sem etiquetas

As tres primeiras sao do bloco KAM-061 (Detalhes Tecnicos) e do criterio do
KAM-193; a quarta e a quinta, do DoD do KAM-063 («metricas `idx_mode`,
`embedding_latency_ms`, `embedding_fallback_total`»); a sexta, do KAM-194, que
so o processo do IDX (`kamba_core.idx.processo`) escreve — e o unico a correr o
`reindexar` em ciclo. Vivem no mesmo registo porque quem serve `/metrics` serve
o registo inteiro, e cada serie so aparece depois de escrita: o AGR nunca
publica a sexta. A
forma e a das outras bibliotecas de metricas desta arvore
(`kamba_core.ten.metricas`, `kamba_agr.metricas`): numeros em memoria, com um
trinco, sem dependencias, e **sem porta** — quem serve `/metrics` e o processo
que importa o modulo. Hoje e o AGR, que e onde a pesquisa corre (o executor do
`search_catalog`, `kamba_agr.tls.idx`); o `docs/tecnica/05` §15 poe a medicao
dos dois p95 na «metrica do TLS», e e la que a chamada esta.

## Nenhuma etiqueta e aberta, e nenhuma leva texto de consulta

As quatro etiquetas tem **dominio fechado**, escrito aqui e repetido no
`ops/metricas/catalogo.yaml`: `modo` em {`hibrido`, `lexical`}, `ramo` em
{`todos`}, `uso` em `USOS` e `motivo` em `MOTIVOS_DE_QUEDA`. Um valor fora da
lista levanta, e um `tenant_id` levanta antes disso, pela gramatica (um UUID tem
hifenes). **O texto da pergunta nao tem por onde entrar**: nenhum metodo deste
modulo recebe texto, so valores de dominio, duracoes e um numero de resultados. E a regra do `OBS-I` e do *handoff* do KAM-193 («nada de
texto de consulta em etiquetas nem em logs»), imposta pela assinatura e nao por
uma lista de proibidos.

## Porque e que o `ramo` so tem um valor, e a escolha escrita

O bloco pede `idx_query_ms` **por ramo** (`sem`, `tri`, `fts`), e os Detalhes
Tecnicos do KAM-193 avisam que isso nao sai de graca: o `idx.candidatos` corre
os tres ramos **numa so instrucao SQL** (`db/indice.py`), e do lado do cliente
so se ve a duracao da instrucao inteira. Separar os ramos pede que a funcao
exponha o tempo de cada um, ou que o chamador corra cada ramo a parte — e as
duas coisas sao **mudar o `idx.candidatos`**, que nao e deste ticket (corre ao
lado o KAM-062, dono da normalizacao e da funcao). Por isso o eixo existe, com o
valor que hoje se mede com verdade: `todos`, a pesquisa inteira — a funcao, o
*join* com a oferta viva e o limiar por transaccao. Um valor por ramo entra na
lista no dia em que houver quem o meca; ate la, declara-lo era publicar uma
serie que nunca se escreve. O tempo por ramo **mede-se** hoje, mas fora do
processo: o `db/desempenho_indice.py` le-o do `EXPLAIN ANALYZE`.

## Dois nomes que sao do bloco e nao da convencao

* **`idx_mode` e um *counter* sem o sufixo `_total`.** A convencao do Prometheus
  pede-o, e o `promtool check metrics` avisa; o formato 0.0.4 que o AGR serve
  aceita-o. O nome e o que o bloco KAM-061 e o criterio do KAM-193 escrevem, e
  muda-lo era mudar o contrato que eles citam — fica dito aqui, e nao em silencio.
* **`modo="hibrido"` so se escreve com vector e com indice que o use**: o
  executor so o escreve quando a pergunta foi embebida e o tenant tem
  documentos embebidos com o mesmo modelo (`kamba_core.idx.embeddings`). Sem
  modelo escolhido (o alias `kamba-embed` esta `por_decidir`), toda a pesquisa
  continua lexical.

## O motivo da queda e o uso da chamada sao dominios fechados

O `embedding_fallback_total{motivo}` conta **so** as consultas que tinham com
que ir ao fornecedor e nao foram: destino negado, assunto sensivel ou
identificador, tecto de 1,5 s, falha, e vector de outro modelo. Um tenant sem
documentos embebidos, ou um processo sem fornecedor ligado, cai em lexical
**sem** contar aqui: nao e uma queda, e o estado de repouso, e conta-lo afogava
o sinal. O `embedding_latency_ms{uso}` separa a pergunta (`consulta`, a que tem
o tecto do criterio 3) do catalogo (`catalogo`, que corre em lote).

## Um *gauge* e nao um histograma

Pela razao do `agr_tool_latency_ms` e do `agr_turn_latency_ms`: esta biblioteca
nao implementa histogramas (ADR-018, observabilidade leve no Piloto), pelo que a
serie e o **ultimo** valor. **Nao da o p95.** Os dois p95 do criterio 10 medem-se
com o instrumento, sobre os valores todos, e nao com esta serie.

## Um processo fresco serve corpo vazio

Uma serie so aparece depois de escrita, como no `kamba_agr.metricas`. Nao e a
regra dos modulos TypeScript (que publicam zeros), e e de proposito: o AGR serve
os dois registos na mesma `/metrics`, e o ensaio
`test_um_processo_fresco_serve_corpo_vazio` prende o corpo **vazio** de um
processo acabado de arrancar. Um registo que publicasse zeros partia-o, e era
mudar a decisao de outro ticket (`docs/observabilidade.md` §5).
"""

from __future__ import annotations

import re
import threading
from typing import Final

#: Duracao da ultima pesquisa, em milissegundos. Etiquetas: `ramo` e `modo`.
METRICA_LATENCIA: Final = "idx_query_ms"

#: Candidatos devolvidos pela pesquisa, somados (ate tres por pesquisa, §6.3).
METRICA_RESULTADOS: Final = "idx_results_total"

#: Pesquisas, por modo. Etiqueta: `modo`.
METRICA_MODO: Final = "idx_mode"

#: Documentos reescritos pelo ciclo da reindexacao (KAM-194). Sem etiquetas:
#: nem *tenant*, nem lote — e o numero que mede o alvo do KAM-062.
METRICA_REINDEXADOS: Final = "idx_reindexed_total"

#: Os modos do §6.5. `lexical` e o de hoje: sem embedding da pergunta (KAM-063).
MODOS: Final = ("hibrido", "lexical")

#: Os ramos medidos. So `todos`: ver a nota do modulo.
RAMOS: Final = ("todos",)

#: Duracao da ultima chamada ao fornecedor de embeddings, em ms (KAM-063).
METRICA_EMBEDDING_LATENCIA: Final = "embedding_latency_ms"

#: Consultas que cairam em lexical tendo com que ir ao fornecedor (KAM-063).
METRICA_EMBEDDING_QUEDA: Final = "embedding_fallback_total"

#: Para que serviu a chamada: a pergunta do cliente ou o texto do catalogo.
USOS: Final = ("catalogo", "consulta")

#: Porque e que a consulta caiu em lexical. Lista fechada: ver a nota do modulo
#: e o `kamba_core.idx.embeddings`, que e quem os escreve.
MOTIVOS_DE_QUEDA: Final = (
    "destino_negado",
    "falha",
    "modelo_divergente",
    "sensivel",
    "tempo_esgotado",
)

#: A gramatica de uma etiqueta, a mesma das outras bibliotecas.
ETIQUETA: Final = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

_AJUDA: Final = {
    METRICA_LATENCIA: (
        "gauge",
        "Duracao da ultima pesquisa no indice, em milissegundos, por ramo e modo.",
    ),
    METRICA_RESULTADOS: ("counter", "Candidatos devolvidos pela pesquisa no indice."),
    METRICA_MODO: ("counter", "Pesquisas no indice, por modo (hibrido ou lexical)."),
    METRICA_REINDEXADOS: (
        "counter",
        "Documentos do indice reescritos pelo ciclo da reindexacao.",
    ),
    METRICA_EMBEDDING_LATENCIA: (
        "gauge",
        "Duracao da ultima chamada ao fornecedor de embeddings, em ms, por uso.",
    ),
    METRICA_EMBEDDING_QUEDA: (
        "counter",
        "Consultas que cairam em modo lexical em vez de ir ao fornecedor, por motivo.",
    ),
}


class EtiquetaInvalida(ValueError):
    """Um valor fora do dominio fechado. Um `tenant_id` cai sempre aqui."""


def _validar(nome: str, valor: object, dominio: tuple[str, ...]) -> str:
    if not isinstance(valor, str) or not ETIQUETA.match(valor):
        raise EtiquetaInvalida(
            f"{nome}: o valor nao casa ^[a-z][a-z0-9_]{{1,62}}$. Identificadores "
            "e texto de consulta nao entram em metricas "
            "(docs/seguranca/ameacas_stride.md, OBS-I)"
        )
    if valor not in dominio:
        raise EtiquetaInvalida(f"{nome}: {valor!r} nao esta na lista fechada {dominio}")
    return valor


class MetricasDoIdx:
    """As cinco series do IDX, em memoria e seguras entre *threads*. So numeros."""

    def __init__(self) -> None:
        self._trinco = threading.Lock()
        self._latencia: dict[tuple[str, str], float] = {}
        self._resultados = 0
        self._por_modo: dict[str, int] = {}
        self._resultados_escritos = False
        self._reindexados: int | None = None
        self._embedding_latencia: dict[str, float] = {}
        self._quedas: dict[str, int] = {}

    def registar_reindexacao(self, quantos: int) -> None:
        """Uma volta do ciclo da reindexacao: quantos documentos reescreveu.

        Zero conta — e escreve a serie: um painel que nao a visse nao
        distinguia «em dia» de «o ciclo nao corre».
        """
        if isinstance(quantos, bool) or not isinstance(quantos, int) or quantos < 0:
            raise ValueError("quantos e um inteiro nao negativo")
        with self._trinco:
            self._reindexados = (self._reindexados or 0) + quantos

    def registar_embedding(self, *, uso: str, duracao_ms: float) -> None:
        """Uma chamada ao fornecedor de embeddings que respondeu, e quanto levou."""
        uso = _validar("uso", uso, USOS)
        duracao = float(duracao_ms)
        if not duracao >= 0:  # apanha tambem o NaN
            raise ValueError("duracao_ms e um numero nao negativo")
        with self._trinco:
            self._embedding_latencia[uso] = duracao

    def contar_queda(self, *, motivo: str) -> None:
        """Uma consulta que caiu em lexical. **So o motivo**, nunca a pergunta."""
        motivo = _validar("motivo", motivo, MOTIVOS_DE_QUEDA)
        with self._trinco:
            self._quedas[motivo] = self._quedas.get(motivo, 0) + 1

    def registar_pesquisa(
        self, *, modo: str, duracao_ms: float, resultados: int, ramo: str = "todos"
    ) -> None:
        """Uma pesquisa que respondeu: a duracao, o modo e quantos candidatos deu.

        So recebe numeros e valores de dominio fechado — **nunca** a pergunta.
        """
        modo = _validar("modo", modo, MODOS)
        ramo = _validar("ramo", ramo, RAMOS)
        if isinstance(resultados, bool) or not isinstance(resultados, int) or resultados < 0:
            raise ValueError("resultados e um inteiro nao negativo")
        duracao = float(duracao_ms)
        if not duracao >= 0:  # apanha tambem o NaN
            raise ValueError("duracao_ms e um numero nao negativo")
        with self._trinco:
            self._latencia[(ramo, modo)] = duracao
            self._resultados += resultados
            self._resultados_escritos = True
            self._por_modo[modo] = self._por_modo.get(modo, 0) + 1

    def ler(self) -> dict[str, float]:
        """As series escritas, com a etiqueta no nome (`metrica:valor`)."""
        with self._trinco:
            valores: dict[str, float] = {
                f"{METRICA_LATENCIA}:{ramo}:{modo}": v
                for (ramo, modo), v in self._latencia.items()
            }
            valores.update({f"{METRICA_MODO}:{m}": n for m, n in self._por_modo.items()})
            if self._resultados_escritos:
                valores[METRICA_RESULTADOS] = self._resultados
            if self._reindexados is not None:
                valores[METRICA_REINDEXADOS] = self._reindexados
            valores.update(
                {
                    f"{METRICA_EMBEDDING_LATENCIA}:{u}": v
                    for u, v in self._embedding_latencia.items()
                }
            )
            valores.update(
                {f"{METRICA_EMBEDDING_QUEDA}:{m}": n for m, n in self._quedas.items()}
            )
        return valores

    def repor(self) -> None:
        with self._trinco:
            self._latencia.clear()
            self._por_modo.clear()
            self._resultados = 0
            self._resultados_escritos = False
            self._reindexados = None
            self._embedding_latencia.clear()
            self._quedas.clear()

    def exposicao(self) -> str:
        """O texto no formato do Prometheus, com `# TYPE` e `# HELP`."""
        with self._trinco:
            latencia = dict(self._latencia)
            por_modo = dict(self._por_modo)
            resultados = self._resultados if self._resultados_escritos else None
            reindexados = self._reindexados
            embedding_latencia = dict(self._embedding_latencia)
            quedas = dict(self._quedas)
        linhas: list[str] = []

        def cabecalho(metrica: str) -> None:
            tipo, ajuda = _AJUDA[metrica]
            linhas.append(f"# HELP {metrica} {ajuda}")
            linhas.append(f"# TYPE {metrica} {tipo}")

        if latencia:
            cabecalho(METRICA_LATENCIA)
            for (ramo, modo) in sorted(latencia):
                linhas.append(
                    f'{METRICA_LATENCIA}{{ramo="{ramo}",modo="{modo}"}} '
                    f"{_numero(latencia[(ramo, modo)])}"
                )
        if resultados is not None:
            cabecalho(METRICA_RESULTADOS)
            linhas.append(f"{METRICA_RESULTADOS} {resultados}")
        if por_modo:
            cabecalho(METRICA_MODO)
            for modo in sorted(por_modo):
                linhas.append(f'{METRICA_MODO}{{modo="{modo}"}} {por_modo[modo]}')
        if reindexados is not None:
            cabecalho(METRICA_REINDEXADOS)
            linhas.append(f"{METRICA_REINDEXADOS} {reindexados}")
        if embedding_latencia:
            cabecalho(METRICA_EMBEDDING_LATENCIA)
            for uso in sorted(embedding_latencia):
                linhas.append(
                    f'{METRICA_EMBEDDING_LATENCIA}{{uso="{uso}"}} '
                    f"{_numero(embedding_latencia[uso])}"
                )
        if quedas:
            cabecalho(METRICA_EMBEDDING_QUEDA)
            for motivo in sorted(quedas):
                linhas.append(
                    f'{METRICA_EMBEDDING_QUEDA}{{motivo="{motivo}"}} {quedas[motivo]}'
                )
        return "\n".join(linhas) + ("\n" if linhas else "")


def _numero(valor: float) -> str:
    return str(int(valor)) if float(valor).is_integer() else repr(float(valor))


#: O registo do processo.
METRICAS: Final = MetricasDoIdx()
