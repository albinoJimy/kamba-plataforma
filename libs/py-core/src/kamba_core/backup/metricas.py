"""As metricas de backup (KAM-079, criterios 2 e 5).

    backup_wal_idade_segundos              gauge    idade do ultimo WAL arquivado
    backup_restauro_desfecho_total{desfecho} counter desfecho do restauro mensal
    backup_restauro_duracao_segundos       gauge    duracao do ultimo restauro
    backup_restauro_debito_mbps            gauge    debito efectivo do ultimo restauro

================================================================================
NENHUM PROCESSO SERVE ESTAS QUATRO METRICAS, E ISSO NAO E UM ESQUECIMENTO
================================================================================

Este modulo **declara** e nao expoe. A razao esta escrita no
`ops/metricas/catalogo.yaml` e e a mesma com que o KAM-076 recusou um
`scrape_config` para um `/metrics` inexistente:

    «uma regra sobre uma serie que ninguem produz nunca dispara, e um alerta
    que nunca dispara parece cobertura — e e pior do que a sua ausencia,
    porque ninguem volta a olhar»

Servir estas metricas exige o pgBackRest a correr, que exige um `repo1`
alcancavel, que exige a D1/KAM-105 decidida. Por isso as duas entradas do
`regras_por_escrever` do catalogo continuam la, com o que falta **actualizado**:
ja nao e «nao ha metrica de idade do WAL» — e o processo que a sirva.

A propriedade deste modulo, dita sem contar quantos outros a tem: a fonte dos
seus valores **nao esta no processo que o importa**. O `ten/metricas.py` conta
recusas que o proprio processo decidiu; estes quatro numeros lem-se do
`pgbackrest info` de **fora**, por um processo que ainda nao existe. E isso que
explica porque tres das quatro sao *gauges* com `definir` (os valores entram de
uma leitura) e so o desfecho do restauro e um contador que se incrementa.

A primeira versao deste paragrafo escrevia «e o unico cuja fonte de valores nao
esta no processo que o importa» e, quatro linhas abaixo, «nao e um ordinal».
Eram incompativeis, e a revisao adversarial apanhou-o: «e o unico» e uma
afirmacao sobre o **resto da arvore** e nao sobre este ficheiro, e fica falsa no
dia em que nascer outro modulo assim — sem ninguem tocar aqui. A propriedade
descreve-se; a unicidade conta-se, e contar nao e deste sitio.

================================================================================
A ETIQUETA, E PORQUE SO HA UMA
================================================================================

O `desfecho` tem **dominio fechado em tres** (`ok`, `falhado`, `inconclusivo`) e
e a unica etiqueta deste modulo. A gramatica e a mesma do `ten/metricas.py` e do
`tools/obs_lint`, repetida aqui de proposito: as tres sao a mesma regra e nenhuma
importa as outras.

Nao ha etiqueta de `tenant`: um backup e do **cluster** e nao de um tenant, e o
`docs/seguranca/ameacas_stride.md` (`OBS-I`) recusa identificadores em etiquetas.
Tambem nao ha etiqueta de destino: o nome do `repo1` e um FQDN, e um FQDN em
etiqueta e a localizacao do repositorio de backup num painel que muita gente le.

O `inconclusivo` existe pela razao que o bloco do KAM-078 escreve para o *smoke*
da Meta: «falhas por indisponibilidade classificam-se `inconclusivo`, nao
`verde`». Um restauro que nao correu porque o *host* descartavel nao arrancou nao
e um restauro falhado nem um restauro bem-sucedido, e juntar os dois casos
apagaria a diferenca entre «a rede de seguranca esta rota» e «nao a conseguimos
testar».
"""

from __future__ import annotations

import math
import re
import threading

#: Idade do ultimo segmento de WAL arquivado, em segundos. **Gauge**: e um
#: estado e nao uma soma, e o alerta le-a directamente contra os 300 s.
METRICA_WAL_IDADE = "backup_wal_idade_segundos"

#: Desfecho do restauro mensal, por `desfecho`. **Counter**: a pergunta do
#: criterio 5 e «correu 2x em staging com resultado arquivado», que e uma
#: contagem.
METRICA_RESTAURO_DESFECHO = "backup_restauro_desfecho_total"

#: Duracao do ultimo restauro completo, em segundos (criterio 4).
METRICA_RESTAURO_DURACAO = "backup_restauro_duracao_segundos"

#: Debito efectivo do ultimo restauro, em **megabits** por segundo. A unidade
#: esta no nome porque confundi-la com megabytes da um factor de 8, e um factor
#: de 8 num orcamento de RTO e a diferenca entre 30 minutos e 4 horas.
METRICA_RESTAURO_DEBITO = "backup_restauro_debito_mbps"

#: Os tres desfechos. Lista **fechada**, ao contrario das etiquetas do
#: `ten/metricas.py`: as chaves de limite crescem com o registo e estes tres nao
#: crescem com nada — sao o vocabulario do criterio 5.
DESFECHOS = ("ok", "falhado", "inconclusivo")

#: A gramatica de uma etiqueta. A mesma do `ten/metricas.py:45`.
ETIQUETA = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

_AJUDA = {
    METRICA_WAL_IDADE: (
        "gauge",
        "Idade do ultimo segmento de WAL arquivado, em segundos.",
    ),
    METRICA_RESTAURO_DESFECHO: (
        "counter",
        "Restauros mensais por desfecho (ok, falhado, inconclusivo).",
    ),
    METRICA_RESTAURO_DURACAO: (
        "gauge",
        "Duracao do ultimo restauro completo medido, em segundos.",
    ),
    METRICA_RESTAURO_DEBITO: (
        "gauge",
        "Debito efectivo do ultimo restauro, em megabits por segundo.",
    ),
}

#: Como se chama a etiqueta de cada metrica. So o contador tem.
_NOME_DA_ETIQUETA = {METRICA_RESTAURO_DESFECHO: "desfecho"}


class DesfechoInvalido(ValueError):
    """Um desfecho fora dos tres. A lista e fechada de proposito."""


class MetricasDeBackup:
    """Os quatro numeros, em memoria, com trinco, sem dependencias.

    A forma e a do `MetricasDoTen`: um dicionario de numeros protegido por um
    `Lock`. A diferenca e que tres destas sao **gauges** e nao contadores, e por
    isso tem `definir` e nao `contar` — somar uma idade de WAL nao quer dizer
    nada.
    """

    def __init__(self) -> None:
        self._trinco = threading.Lock()
        self._desfechos: dict[str, int] = {}
        self._gauges: dict[str, float | None] = {
            METRICA_WAL_IDADE: None,
            METRICA_RESTAURO_DURACAO: None,
            METRICA_RESTAURO_DEBITO: None,
        }

    def contar_desfecho(self, desfecho: str, quanto: int = 1) -> None:
        if desfecho not in DESFECHOS:
            raise DesfechoInvalido(
                f"desfecho {desfecho!r} fora de {DESFECHOS}. A lista e fechada "
                "porque e o vocabulario do criterio 5 e nao um campo livre"
            )
        if not ETIQUETA.match(desfecho):  # pragma: no cover - os tres casam
            raise DesfechoInvalido(f"{desfecho!r} nao casa a gramatica da etiqueta")
        with self._trinco:
            self._desfechos[desfecho] = self._desfechos.get(desfecho, 0) + quanto

    def definir(self, metrica: str, valor: float) -> None:
        """Poe o valor de um *gauge*.

        Recusa `NaN`. Um `NaN` no formato de exposicao e aceite pelo Prometheus e
        **envenena** qualquer expressao que o toque: uma comparacao com `NaN` e
        sempre falsa, pelo que um alerta `> 300` deixa de disparar em silencio.
        O `inf` **aceita-se**, porque e o valor com significado que o
        `idade_do_wal_segundos` devolve quando nunca se arquivou nada — e ele
        dispara o alerta, que e o que esse estado merece.
        """
        if metrica not in self._gauges:
            raise DesfechoInvalido(
                f"{metrica!r} nao e um gauge deste modulo: so "
                f"{sorted(self._gauges)}"
            )
        if math.isnan(valor):
            raise DesfechoInvalido(
                f"{metrica}: NaN. Uma comparacao com NaN e sempre falsa, pelo "
                "que um alerta `> 300` deixaria de disparar sem nada avisar"
            )
        with self._trinco:
            self._gauges[metrica] = float(valor)

    def ler(self) -> dict[str, object]:
        with self._trinco:
            return {"desfechos": dict(self._desfechos), "gauges": dict(self._gauges)}

    def repor(self) -> None:
        with self._trinco:
            self._desfechos.clear()
            for chave in self._gauges:
                self._gauges[chave] = None

    def exposicao(self) -> str:
        """Formato de exposicao do Prometheus.

        O contador aparece **sempre**, e os tres desfechos aparecem a zero
        quando nenhum ocorreu: um painel que mostre «sem dados» nao distingue
        «nenhum restauro falhou» de «o processo nao arrancou». E a mesma escolha
        do `ten/metricas.py` e do `eventos/metricas.ts`.

        Os *gauges* aparecem **so quando tem valor**, e a diferenca com o
        contador e deliberada: um `backup_wal_idade_segundos 0` sem medicao
        nenhuma le-se como «acabou de arquivar», que e a leitura mais errada
        possivel — e exactamente a que o alerta nao apanharia. Ausente, o
        `absent()` do PromQL ve-o.
        """
        estado = self.ler()
        desfechos: dict[str, int] = estado["desfechos"]  # type: ignore[assignment]
        gauges: dict[str, float | None] = estado["gauges"]  # type: ignore[assignment]
        linhas: list[str] = []
        for nome, (tipo, ajuda) in _AJUDA.items():
            linhas.append(f"# HELP {nome} {ajuda}")
            linhas.append(f"# TYPE {nome} {tipo}")
            if nome == METRICA_RESTAURO_DESFECHO:
                etiqueta = _NOME_DA_ETIQUETA[nome]
                for desfecho in DESFECHOS:
                    valor = desfechos.get(desfecho, 0)
                    linhas.append(f'{nome}{{{etiqueta}="{desfecho}"}} {valor}')
                continue
            valor = gauges.get(nome)
            if valor is None:
                continue
            linhas.append(f"{nome} {_numero(valor)}")
        return "\n".join(linhas) + "\n"


def _numero(valor: float) -> str:
    """O valor no formato de exposicao.

    `+Inf` e `-Inf` em vez de `inf`: e a grafia que o formato de exposicao do
    Prometheus define, e `inf` seria recusado pelo raspador.
    """
    if math.isinf(valor):
        return "+Inf" if valor > 0 else "-Inf"
    if valor == int(valor):
        return str(int(valor))
    return repr(round(valor, 6))


#: As metricas do processo. Existe para quem ligar a porta (ver o cabecalho).
METRICAS = MetricasDeBackup()
