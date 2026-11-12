"""As tres metricas do IDX (KAM-193, DoD «metricas» do KAM-061).

    idx_query_ms{ramo,modo}  gauge    duracao da ultima pesquisa, em milissegundos
    idx_results_total        counter  candidatos devolvidos pela pesquisa, somados
    idx_mode{modo}           counter  pesquisas, por modo (`hibrido` ou `lexical`)

Os nomes sao os do bloco KAM-061 (Detalhes Tecnicos) e do criterio do KAM-193. A
forma e a das outras bibliotecas de metricas desta arvore
(`kamba_core.ten.metricas`, `kamba_agr.metricas`): numeros em memoria, com um
trinco, sem dependencias, e **sem porta** — quem serve `/metrics` e o processo
que importa o modulo. Hoje e o AGR, que e onde a pesquisa corre (o executor do
`search_catalog`, `kamba_agr.tls.idx`); o `docs/tecnica/05` §15 poe a medicao
dos dois p95 na «metrica do TLS», e e la que a chamada esta.

## Nenhuma etiqueta e aberta, e nenhuma leva texto de consulta

As duas etiquetas tem **dominio fechado**, escrito aqui e repetido no
`ops/metricas/catalogo.yaml`: `modo` em {`hibrido`, `lexical`} e `ramo` em
{`todos`}. Um valor fora da lista levanta, e um `tenant_id` levanta antes disso,
pela gramatica (um UUID tem hifenes). **O texto da pergunta nao tem por onde
entrar**: nenhum metodo deste modulo recebe texto, so o modo, a duracao e um
numero de resultados. E a regra do `OBS-I` e do *handoff* do KAM-193 («nada de
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
* **`modo="hibrido"` esta no dominio e o executor de hoje nunca o escreve**: sem
  embedding da pergunta (KAM-063), toda a pesquisa e lexical. A diferenca para
  o `ramo` e que este valor esta escrito no criterio (`idx_mode{hibrido|lexical}`)
  e tem quem o venha a produzir; um valor por ramo nao tem.

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

#: Os modos do §6.5. `lexical` e o de hoje: sem embedding da pergunta (KAM-063).
MODOS: Final = ("hibrido", "lexical")

#: Os ramos medidos. So `todos`: ver a nota do modulo.
RAMOS: Final = ("todos",)

#: A gramatica de uma etiqueta, a mesma das outras bibliotecas.
ETIQUETA: Final = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

_AJUDA: Final = {
    METRICA_LATENCIA: (
        "gauge",
        "Duracao da ultima pesquisa no indice, em milissegundos, por ramo e modo.",
    ),
    METRICA_RESULTADOS: ("counter", "Candidatos devolvidos pela pesquisa no indice."),
    METRICA_MODO: ("counter", "Pesquisas no indice, por modo (hibrido ou lexical)."),
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
    """As tres series do IDX, em memoria e seguras entre *threads*. So numeros."""

    def __init__(self) -> None:
        self._trinco = threading.Lock()
        self._latencia: dict[tuple[str, str], float] = {}
        self._resultados = 0
        self._por_modo: dict[str, int] = {}
        self._resultados_escritos = False

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
        return valores

    def repor(self) -> None:
        with self._trinco:
            self._latencia.clear()
            self._por_modo.clear()
            self._resultados = 0
            self._resultados_escritos = False

    def exposicao(self) -> str:
        """O texto no formato do Prometheus, com `# TYPE` e `# HELP`."""
        with self._trinco:
            latencia = dict(self._latencia)
            por_modo = dict(self._por_modo)
            resultados = self._resultados if self._resultados_escritos else None
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
        return "\n".join(linhas) + ("\n" if linhas else "")


def _numero(valor: float) -> str:
    return str(int(valor)) if float(valor).is_integer() else repr(float(valor))


#: O registo do processo.
METRICAS: Final = MetricasDoIdx()
