"""As duas metricas do TEN (KAM-009 criterio 7, ADR-018).

    ten_limit_denied_total{key}          counter  consumos recusados pelo tecto
    ten_entitlement_denied_total{modulo} counter  acessos recusados por entitlement

Espelho de `packages/core-ts/src/ten/metricas.ts`: os mesmos dois nomes, a
mesma gramatica de etiqueta, o mesmo tecto de series e o mesmo texto de
exposicao. O `TestParidadeDoTypeScript` confronta os quatro.

A forma e a do `Contadores` do `kamba_core.tenant_guard` — um dicionario de
numeros, em memoria, com um trinco, sem dependencias — com a diferenca de que
estes contadores tem etiqueta. Esta biblioteca nao abre portas: quem expoe
`/metrics` e o servico.

**O `tenant_id` nao entra em etiqueta nenhuma.** O
`docs/seguranca/ameacas_stride.md` (`OBS-I`) diz porque: identificadores em
etiquetas explodem a cardinalidade e re-identificam. Aqui a regra e imposta
pela **gramatica** e nao por uma lista de nomes proibidos: uma etiqueta tem de
casar `^[a-z][a-z0-9_]{1,62}$`, e um UUID canonico tem hifenes — nao casa, e a
chamada levanta. Uma lista de proibidos protegia contra os nomes que alguem se
lembrou de escrever; a gramatica protege contra a forma.

**Porque e que as etiquetas nao sao uma lista fechada.** As chaves de limite
crescem com `registry/entitlement_keys.schema.json` e os modulos com as
verticais de `registry/*.yaml`. Uma lista fechada aqui obrigava esta biblioteca
a importar o registo e a falhar sempre que o registo andasse a frente dela. O
que a substitui e o par gramatica + tecto de series, que e o que o
`medirPorTipo` do `eventos/metricas.ts` ja faz para o `evt_dlq_open{tipo}`.
"""

from __future__ import annotations

import re
import threading

#: Consumos recusados porque o tecto nao chegava. Etiqueta: a chave.
METRICA_LIMITE_NEGADO = "ten_limit_denied_total"

#: Acessos recusados porque o entitlement nao permite. Etiqueta: o modulo.
METRICA_ENTITLEMENT_NEGADO = "ten_entitlement_denied_total"

#: A gramatica de uma etiqueta. E a do `CHECK` de `tenant_usage.chave_limite` e
#: a de `entitlements.modulo` na `0001`, com um tecto de comprimento: uma chave
#: de 4 KB nao e uma chave.
ETIQUETA = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

#: Quantas series se aceitam por metrica antes de desistir.
MAXIMO_DE_SERIES = 64

_AJUDA = {
    METRICA_LIMITE_NEGADO: (
        "counter",
        "Consumos recusados pelo tecto do plano, por chave de limite.",
    ),
    METRICA_ENTITLEMENT_NEGADO: (
        "counter",
        "Acessos recusados por entitlement inactivo ou estado do tenant, por modulo.",
    ),
}

#: Como se chama a etiqueta de cada metrica no formato de exposicao.
_NOME_DA_ETIQUETA = {
    METRICA_LIMITE_NEGADO: "key",
    METRICA_ENTITLEMENT_NEGADO: "modulo",
}


class EtiquetaInvalida(ValueError):
    """Uma etiqueta que nao casa a gramatica. Um `tenant_id` cai sempre aqui."""


class MetricasDoTen:
    """Contadores em memoria, seguros entre *threads*. So numeros."""

    def __init__(self) -> None:
        self._trinco = threading.Lock()
        self._valores: dict[str, int] = {}

    def contar(self, metrica: str, etiqueta: str, quanto: int = 1) -> None:
        """Soma `quanto` (1 por omissao) ao contador da etiqueta."""
        if metrica not in _NOME_DA_ETIQUETA:
            raise EtiquetaInvalida(
                f"{metrica}: metrica desconhecida. So existem "
                f"{METRICA_LIMITE_NEGADO} e {METRICA_ENTITLEMENT_NEGADO}."
            )
        if not isinstance(etiqueta, str) or not ETIQUETA.match(etiqueta):
            raise EtiquetaInvalida(
                f"{metrica}: etiqueta nao casa ^[a-z][a-z0-9_]{{1,62}}$. "
                "Identificadores (tenant_id, contact_id) nao entram em metricas "
                "(docs/seguranca/ameacas_stride.md, OBS-I)"
            )
        nome = f"{metrica}:{etiqueta}"
        prefixo = f"{metrica}:"
        with self._trinco:
            if nome not in self._valores:
                series = sum(1 for chave in self._valores if chave.startswith(prefixo))
                if series >= MAXIMO_DE_SERIES:
                    raise OverflowError(
                        f"{metrica}: {MAXIMO_DE_SERIES} series e o tecto, e "
                        f"{etiqueta} seria mais uma. Uma metrica que cresce sem "
                        "fim deixa de ser observabilidade."
                    )
            self._valores[nome] = self._valores.get(nome, 0) + quanto

    def ler(self) -> dict[str, int]:
        with self._trinco:
            return dict(self._valores)

    def repor(self) -> None:
        with self._trinco:
            self._valores.clear()

    def exposicao(self) -> str:
        """Formato de exposicao do Prometheus.

        As duas metricas aparecem sempre, mesmo a zero: um painel que mostre
        «sem dados» nao distingue «ninguem foi recusado» de «o processo nao
        arrancou». E a mesma escolha do `eventos/metricas.ts`.
        """
        valores = self.ler()
        linhas: list[str] = []
        for nome, (tipo, ajuda) in _AJUDA.items():
            linhas.append(f"# HELP {nome} {ajuda}")
            linhas.append(f"# TYPE {nome} {tipo}")
            series = sorted(
                chave for chave in valores if chave.startswith(f"{nome}:")
            )
            if not series:
                linhas.append(f"{nome} 0")
                continue
            etiqueta = _NOME_DA_ETIQUETA[nome]
            for chave in series:
                linhas.append(
                    f'{nome}{{{etiqueta}="{chave[len(nome) + 1:]}"}} {valores[chave]}'
                )
        return "\n".join(linhas) + "\n"


#: As metricas do processo.
METRICAS = MetricasDoTen()
