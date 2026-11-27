"""A rotacao de chaves no `audit_log` (KAM-072, revisao `0066`).

Duas coisas, contra a base:

* o SQL do adaptador (`SQL_AUDITAR_ROTACAO` de
  `packages/core-ts/src/keyring/auditoria.ts`, lido do proprio ficheiro) escreve
  as duas accoes na cadeia de plataforma, com o papel que a escreve
  (`kamba_batch`), e uma accao fora do dominio e recusada;
* o `downgrade` da `0066` recusa com uma linha `secret.*` escrita, e sem ela
  desce e volta a subir.

**Desce pelo `down_revision` da revisao, lido do ficheiro, e nao por `-1`**,
pela licao do KAM-071, e **nao exige `em_head()` depois de recusar**, pela do
KAM-089: com outra revisao por cima, o Alembic desce-a primeiro e a base fica
nesta. O numero da `0066` e provisorio, e ler o `down_revision` do ficheiro e o
que impede este ensaio de partir quando o orquestrador o renumerar.
"""

from __future__ import annotations

import hashlib
import re
import unittest
import uuid
from pathlib import Path

import ligacao
from tests.base import (
    VIOLACAO_DE_CHECK,
    ComBase,
    ConsultaDoTypeScript,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)
from tests.test_auditoria import ACCOES, CHAVE_DA_PLATAFORMA, _desligar, _religar

RAIZ = Path(__file__).resolve().parents[2]
AUDITORIA_TS = RAIZ / "packages" / "core-ts" / "src" / "keyring" / "auditoria.ts"
VERSOES = RAIZ / "db" / "migrations" / "versions"


def _revisao() -> tuple[str, str]:
    """`(revision, down_revision)` da revisao desta suite, lidos do ficheiro."""
    [ficheiro] = [p for p in VERSOES.glob("*_rotacao_de_chaves.py")]
    texto = ficheiro.read_text(encoding="utf-8")
    revisao = re.search(r'^revision = "(\d{4})"$', texto, re.M)
    abaixo = re.search(r'^down_revision = "(\d{4})"$', texto, re.M)
    assert revisao and abaixo, "a revisao nao declara revision e down_revision"
    return revisao.group(1), abaixo.group(1)


def _sha(texto: str) -> bytes:
    return hashlib.sha256(texto.encode("utf-8")).digest()


class TestAccoesDaRotacao(ComBase):
    """As duas accoes entram pela porta do adaptador; uma terceira nao."""

    def test_o_lote_escreve_as_duas_na_cadeia_de_plataforma(self) -> None:
        lote = self.ligar("batch").cursor()
        q = ConsultaDoTypeScript("SQL_AUDITAR_ROTACAO", AUDITORIA_TS)
        marca = uuid.uuid4().hex[:8]
        segredo = f"meta_app_secret/{marca}"
        lote.execute(q.sql, q.args("seguranca", "secret.rotate", segredo, "k2", _sha("rotacao")))
        lote.execute(q.sql, q.args("seguranca", "secret.revoke", segredo, "k1", _sha("revogacao")))
        lote.execute(
            "SELECT tenant_id, actor_type, actor_id, action, entity, entity_id "
            "  FROM platform.audit_log WHERE entity = %s ORDER BY id",
            (segredo,),
        )
        self.assertEqual(
            [tuple(linha) for linha in lote.fetchall()],
            [
                (None, "staff", "seguranca", "secret.rotate", segredo, "k2"),
                (None, "staff", "seguranca", "secret.revoke", segredo, "k1"),
            ],
        )

    def test_uma_accao_fora_do_dominio_e_recusada(self) -> None:
        lote = self.ligar("batch").cursor()
        q = ConsultaDoTypeScript("SQL_AUDITAR_ROTACAO", AUDITORIA_TS)
        self.assertErroSql(
            VIOLACAO_DE_CHECK, lote, q.sql,
            q.args("seguranca", "secret.export", "meta_app_secret", "k1", _sha("x")),
        )

    def test_o_dominio_tem_as_dezanove(self) -> None:
        [(definicao,)] = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'audit_log_action'"
        )
        for accao in (
            "secret.rotate", "secret.revoke", "trust.tecto", "llm.orcamento_zerado",
            "review.recusa", "price.update",
        ):
            self.assertIn(f"'{accao}'", definicao)


class TestDowngradeDaRotacao(unittest.TestCase):
    """O `downgrade` recusa com uma linha `secret.*`, e sem ela desce e volta."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _admin(self):
        conexao = ligacao.ligar("admin")
        self.addCleanup(conexao.close)
        return conexao

    def _definicao(self) -> str:
        c = self._admin().cursor()
        c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'audit_log_action'")
        return c.fetchone()[0]

    def _tem_as_accoes(self) -> bool:
        return "secret.rotate" in self._definicao()

    def _e_o_dominio_de_baixo(self) -> None:
        """Descida feita: o dominio e o da bateria sem as duas do rotador.

        O oraculo e a lista fechada do `test_auditoria.py`, e nao os literais
        da revisao: uma descida que repusesse o dominio sem uma accao de outro
        ticket (o `trust.tecto` da `0065`) passava o `_tem_as_accoes`.
        """
        definicao = self._definicao()
        # **Sem as de cima tambem**: descer a `0066` desce primeiro as revisoes
        # por cima dela, e a `0082` (KAM-206) tira o `order.contact_view`. Sem
        # esta exclusao o oraculo esperava vinte e a base tinha dezoito. E a
        # `0086` (KAM-233) tira o `privacy.telefones_exportados`.
        # E a `0093` (KAM-259) tira o `breakglass.close`.
        posteriores = {"order.contact_view", "privacy.telefones_exportados", "breakglass.close"}
        esperadas = [a for a in ACCOES if not a.startswith("secret.") and a not in posteriores]
        for accao in esperadas:
            self.assertIn(f"'{accao}'", definicao)
        self.assertEqual(definicao.count("'::text"), len(esperadas))

    def _cabeca(self, cursor):
        cursor.execute(
            "SELECT last_hash FROM platform.audit_heads WHERE chave = %s::uuid",
            (CHAVE_DA_PLATAFORMA,),
        )
        linha = cursor.fetchone()
        return None if linha is None else bytes(linha[0])

    def test_com_uma_linha_recusa_e_sem_ela_desce_e_volta(self) -> None:
        revisao, abaixo = _revisao()
        conexao = self._admin()
        c = conexao.cursor()
        cabeca = self._cabeca(c)
        segredo = f"meta_app_secret/{uuid.uuid4().hex[:8]}"
        c.execute(
            "SELECT platform.audit_append(NULL, 'staff', 'seguranca', 'secret.rotate', "
            "%s, 'k1', NULL, %s)",
            (segredo, _sha("descida")),
        )
        conexao.commit()
        try:
            resultado = alembic("downgrade", abaixo)
            self.assertNotEqual(resultado.returncode, 0, "o downgrade devia recusar")
            self.assertIn(f"downgrade da {revisao} recusado", resultado.stderr)
            self.assertTrue(self._tem_as_accoes(), "o dominio ficou, com a linha")
        finally:
            if not em_head():
                alembic_ok("upgrade", "head")
            # A linha sai, e a cabeca da cadeia de plataforma volta a que era:
            # sem isso, a proxima linha encadeava num hash que ja nao existe.
            _desligar(c)
            c.execute("DELETE FROM platform.audit_log WHERE entity = %s", (segredo,))
            _religar(c)
            if cabeca is None:
                c.execute("DELETE FROM platform.audit_heads WHERE chave = %s::uuid", (CHAVE_DA_PLATAFORMA,))
            else:
                c.execute(
                    "UPDATE platform.audit_heads SET last_hash = %s WHERE chave = %s::uuid",
                    (cabeca, CHAVE_DA_PLATAFORMA),
                )
            conexao.commit()
        alembic_ok("downgrade", abaixo)
        try:
            self._e_o_dominio_de_baixo()
        finally:
            alembic_ok("upgrade", "head")
        self.assertTrue(self._tem_as_accoes())


if __name__ == "__main__":
    unittest.main()
