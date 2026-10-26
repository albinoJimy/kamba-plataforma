"""Os privilegios por coluna de `conversations`, no `downgrade` da 0016 (KAM-018).

**Este ficheiro era uma referencia a evidencia inexistente.** A revisao
`0016_modos_de_conversa.py` escreve, ao lado das constantes de colunas,
«Medido em `db/tests/test_modos_privilegios.py`» — e o ficheiro nao existia.
Era a raiz de duas sobreviventes da prova nocturna de 2026-10-26:

* `modos 0016: a app perde o UPDATE do mode`, fechada pela matriz de colunas do
  `test_privilegios.py` (a `conversations` entrou em
  `TABELAS_COM_MATRIZ_DE_COLUNA`);
* `modos 0016: o downgrade revoga tambem a janela da 0009`, que e esta.

**Porque e que o `downgrade` nao era visto.** A `0016` concede
`UPDATE (mode, last_human_activity_at)` — as `COLUNAS_NOVAS` — e revoga
exactamente essas no `downgrade`. Revogar as **quatro**
(`COLUNAS_DA_APLICACAO`, que inclui as duas da `0009`) deixava a base pior do
que a `0009` a tinha, e a propria revisao escreve-o. Mas nenhum ponto da bateria
olhava para os privilegios de `conversations` depois de um `downgrade`:

* dos `alembic downgrade` de `db/tests/`, **nenhum** tem alvo `0015` — o unico
  que faria correr so o `downgrade` da `0016` isoladamente;
* cinco correm-no a caminho de mais baixo e ficam **acima** da `0009`, pelo que
  a tabela sobrevive e o estrago fica — e quando sobem outra vez a `head`, o
  `upgrade` da `0016` so reconcede as `COLUNAS_NOVAS`: as duas da `0009` ficam
  revogadas para o resto da execucao, e continua a nao haver quem repare;
* os que descem **abaixo** da `0009` reparam-na por acidente, porque o
  `DROP TABLE` leva as concessoes com o objecto. E o ciclo completo do gate
  («aplica, reverte, reaplica») e precisamente um desses.

O modelo e o `TestDowngradeDa0013` do `test_restricao_schema.py`, que ja faz
isto para o `tenant_channels`.
"""

from __future__ import annotations

import unittest

import bootstrap
import ligacao
from tests.base import alembic_ok, em_head, exigir_base_descartavel

#: As duas colunas que a `0009` concede: a janela de 24 h que o CHR escreve.
COLUNAS_DA_0009 = ("last_inbound_at", "window_expires_at")

#: As quatro de `head`: as duas da `0009` mais as duas que a `0016` acrescenta.
COLUNAS_DE_HEAD = (
    "last_human_activity_at",
    "last_inbound_at",
    "mode",
    "window_expires_at",
)


def _colunas_de_update(cursor) -> tuple[str, ...]:
    """As colunas de `conversations` em que `kamba_app` tem `UPDATE`."""
    cursor.execute(
        """
        SELECT column_name::text
          FROM information_schema.column_privileges
         WHERE table_schema = 'platform'
           AND table_name = 'conversations'
           AND grantee = 'kamba_app'
           AND privilege_type = 'UPDATE'
         ORDER BY 1
        """
    )
    return tuple(linha[0] for linha in cursor.fetchall())


class TestDowngradeDa0016(unittest.TestCase):
    """«Migracoes reversiveis — `downgrade` testado», para a 0016."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()

    def tearDown(self) -> None:
        try:
            # Cada processo do Alembic custa segundos: so quando a base nao
            # esta em `head` (o teste desceu, ou falhou a meio de descer).
            if not em_head():
                alembic_ok("upgrade", "head")
        finally:
            self.conexao.close()

    def test_o_downgrade_devolve_a_0009_e_nao_menos_do_que_ela(self) -> None:
        """Desce a `0015` e deixa **as duas** da `0009` de pe.

        O canario e a asercao de `head` **antes** de descer: sem ela, uma base
        que chegasse aqui ja sem as quatro concessoes passava o teste por
        acidente, e o que se afirmava era «esta como estava», nao «o
        `downgrade` devolve a `0009`».
        """
        self.assertEqual(_colunas_de_update(self.cursor), COLUNAS_DE_HEAD)

        alembic_ok("downgrade", "0015")
        self.assertEqual(
            _colunas_de_update(self.cursor),
            COLUNAS_DA_0009,
            "o downgrade da 0016 revogou tambem a janela da 0009",
        )

        alembic_ok("upgrade", "head")
        self.assertEqual(_colunas_de_update(self.cursor), COLUNAS_DE_HEAD)
