"""O `purge_log`: o que cada execucao fez, sem conteudo (KAM-071, criterio 5).

Uma linha por **unidade** de purga — classe, tabela e tenant —, escrita na mesma
transaccao que a eliminacao que descreve. E isso que faz o criterio 5 valer: a
linha e a eliminacao confirmam juntas ou nao confirmam nenhuma, e uma falha a
meio nao deixa nem dados meio apagados nem uma linha a dizer que se apagou o
que ficou.

## O que a linha tem, e o que nunca tem

Classe, tabela, tenant, modo, resultado, motivo, contagens, o limite da janela e
a versao da politica. **Nenhum `contact_id`, nenhuma chave de objecto, nenhum
texto livre**: o motivo e um dominio fechado, pela mesma razao do
`resultado` da `dat.llm_call_log` — um campo de texto e o sitio onde um dia
alguem escreve o identificador do titular que a purga acabou de apagar.

## Append-only, e a idempotencia nao e saltar

Ninguem tem `UPDATE` nem `DELETE` (a revisao). Repetir uma janela nao escreve
nada sobre um tenant que ja nao tem linhas nela — a corrida nao o encontra — e
**nao** e o `purge_log` que decide se uma janela corre: um *job* que saltasse as janelas ja registadas nao voltava a apagar o
que um restauro trouxe de volta, e o `purge_log` restaurado nao e o de antes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

#: Os dois modos.
MODO_EFECTIVA: Final = "efectiva"
MODO_DRY_RUN: Final = "dry_run"
MODOS: Final = (MODO_EFECTIVA, MODO_DRY_RUN)

#: Os quatro resultados.
#:
#:   ok        apagou (ou, em dry-run, contou) o que a janela pedia
#:   recusada  a politica nao deixa purgar (fiscal sem prazo, sem caminho)
#:   retida    um hold legal impediu a purga desta unidade
#:   falhou    a unidade levantou; nada dela ficou (alerta Sev2)
RESULTADO_OK: Final = "ok"
RESULTADO_RECUSADA: Final = "recusada"
RESULTADO_RETIDA: Final = "retida"
RESULTADO_FALHOU: Final = "falhou"
RESULTADOS: Final = (RESULTADO_OK, RESULTADO_RECUSADA, RESULTADO_RETIDA, RESULTADO_FALHOU)

#: Os motivos, fechados. `None` num `ok`.
MOTIVO_FISCAL_SEM_PRAZO: Final = "fiscal_sem_prazo"
MOTIVO_FISCAL_IMUTAVEL: Final = "fiscal_imutavel"
MOTIVO_HOLD_TENANT: Final = "hold_tenant"
MOTIVO_HOLD_CONTACTO: Final = "hold_contacto"
MOTIVO_SEM_CAMINHO: Final = "sem_caminho"
MOTIVO_PARTICAO: Final = "particao_por_criar"
MOTIVO_ERRO: Final = "erro"
MOTIVOS: Final = (
    MOTIVO_FISCAL_SEM_PRAZO,
    MOTIVO_FISCAL_IMUTAVEL,
    MOTIVO_HOLD_TENANT,
    MOTIVO_HOLD_CONTACTO,
    MOTIVO_SEM_CAMINHO,
    MOTIVO_PARTICAO,
    MOTIVO_ERRO,
)

#: A escrita. Doze parametros, pela ordem de `Registo`.
SQL_ESCREVER: Final = """
  INSERT INTO platform.purge_log
         (execucao_id, classe, tabela, tenant_id, modo, resultado, motivo,
          linhas, objectos, janela_ate, politica_versao, iniciado_at)
  VALUES (%s::uuid, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class Registo:
    """Uma linha do `purge_log`."""

    execucao_id: str
    classe: str
    tabela: str
    tenant_id: str | None
    modo: str
    resultado: str
    motivo: str | None
    linhas: int
    objectos: int
    janela_ate: datetime | None
    politica_versao: str
    iniciado_at: datetime

    def __post_init__(self) -> None:
        if self.modo not in MODOS:
            raise ValueError(f"modo desconhecido: {self.modo}")
        if self.resultado not in RESULTADOS:
            raise ValueError(f"resultado desconhecido: {self.resultado}")
        if (self.resultado == RESULTADO_OK) != (self.motivo is None):
            raise ValueError("um ok nao tem motivo, e tudo o resto tem")
        if self.motivo is not None and self.motivo not in MOTIVOS:
            raise ValueError(f"motivo desconhecido: {self.motivo}")
        if self.linhas < 0 or self.objectos < 0:
            raise ValueError("uma contagem nao e negativa")
        if self.resultado != RESULTADO_OK and (self.linhas or self.objectos):
            raise ValueError("so um ok apagou alguma coisa")

    def parametros(self) -> tuple[Any, ...]:
        return (
            self.execucao_id,
            self.classe,
            self.tabela,
            self.tenant_id,
            self.modo,
            self.resultado,
            self.motivo,
            self.linhas,
            self.objectos,
            self.janela_ate,
            self.politica_versao,
            self.iniciado_at,
        )


def escrever(cursor: Any, registo: Registo) -> None:
    """Escreve a linha **no cursor da unidade**. Ver a nota do modulo."""
    cursor.execute(SQL_ESCREVER, registo.parametros())


__all__ = [
    "MODOS",
    "MODO_DRY_RUN",
    "MODO_EFECTIVA",
    "MOTIVOS",
    "MOTIVO_ERRO",
    "MOTIVO_FISCAL_IMUTAVEL",
    "MOTIVO_FISCAL_SEM_PRAZO",
    "MOTIVO_HOLD_CONTACTO",
    "MOTIVO_HOLD_TENANT",
    "MOTIVO_PARTICAO",
    "MOTIVO_SEM_CAMINHO",
    "RESULTADOS",
    "RESULTADO_FALHOU",
    "RESULTADO_OK",
    "RESULTADO_RECUSADA",
    "RESULTADO_RETIDA",
    "SQL_ESCREVER",
    "Registo",
    "escrever",
]
