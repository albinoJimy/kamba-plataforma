"""A revisao da idempotencia do painel contra a base (KAM-240).

O que so uma base prova, e o que duas superficies dizem do mesmo:

1. **As restricoes mordem**: a forma da chave, o tamanho da impressao, o
   dominio do estado, a resposta inteira ou nenhuma, e o prazo depois da
   reserva. O `test_inventario` so confere os nomes.
2. **Quem apaga**: o `kamba_app` nao apaga (42501), e o `kamba_batch` apaga as
   vencidas pelo predicado do `CAMINHO_IDEMPOTENCIA_DO_PAINEL`.
3. **As duas superficies cruzadas**: a forma da chave da revisao e a do
   `FORMA_DA_CHAVE` que a rota valida (uma chave que a rota aceita e a base
   recusa dava 500); e a validade da chave (`VALIDADE_DA_CHAVE_MS`) abaixo do
   prazo da classe de retencao (uma purga antes do fim apagava chaves vivas).
4. **A descida**, pelo numero da revisao anterior, lido da revisao.
"""

from __future__ import annotations

import hashlib
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ligacao
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    ComBase,
    alembic_ok,
    em_head,
    sqlstate,
)

RAIZ = Path(__file__).resolve().parents[2]
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_idempotencia_do_painel.py"))
DUPLO = RAIZ / "services" / "onboarding-web" / "src" / "painel" / "idempotencia.ts"
_NUCLEO = str(RAIZ / "libs" / "py-core" / "src")
if _NUCLEO not in sys.path:
    sys.path.insert(0, _NUCLEO)

from kamba_core.retencao import jobs, politica  # noqa: E402

TABELA = "platform.painel_idempotencia"
VIOLACAO_DE_CHECK = "23514"


def _impressao() -> bytes:
    return hashlib.sha256(uuid.uuid4().bytes).digest()


class TestIdempotenciaDoPainel(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = self.ligar("admin").cursor()

    def _inserir(self, *, chave: str | None = None, impressao: bytes | None = None, estado=200,
                 corpo: str | None = "{}", prazo: str = "now() + interval '1 day'") -> None:
        self.admin.execute(
            f"INSERT INTO {TABELA} (tenant_id, chave, impressao, estado, corpo, expira_at) "
            f"VALUES (%s, %s, %s, %s, %s::json, {prazo})",
            (str(uuid.uuid4()), chave or f"kam-240-{uuid.uuid4()}", impressao or _impressao(), estado, corpo),
        )

    def _recusa(self, **campos) -> None:
        self.admin.execute("SAVEPOINT caso")
        import pg8000.dbapi

        with self.assertRaises(pg8000.dbapi.DatabaseError) as erro:
            self._inserir(**campos)
        self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_CHECK, campos)
        self.admin.execute("ROLLBACK TO SAVEPOINT caso")

    def test_as_restricoes_mordem(self) -> None:
        self._inserir()
        self._recusa(chave="curta")
        self._recusa(chave="com espaco no meio da chave")
        self._recusa(impressao=b"\x00" * 31)
        self._recusa(estado=503)
        self._recusa(estado=99)
        # A resposta vai inteira ou nao vai.
        self._recusa(estado=None)
        self._recusa(corpo=None)
        self._inserir(estado=None, corpo=None)
        self._recusa(prazo="now() - interval '1 second'")

    def test_o_kamba_app_nao_apaga_e_o_lote_apaga_as_vencidas(self) -> None:
        tenant = str(uuid.uuid4())
        chave = f"kam-240-{uuid.uuid4()}"
        self.admin.execute(
            f"INSERT INTO {TABELA} (tenant_id, chave, impressao, estado, corpo, criado_at, expira_at) "
            "VALUES (%s, %s, %s, 200, '{}'::json, now() - interval '2 days', now() - interval '1 day')",
            (tenant, chave, _impressao()),
        )
        self.admin.execute("SAVEPOINT papel")
        self.admin.execute("SET LOCAL ROLE kamba_app")
        self.admin.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.admin, f"DELETE FROM {TABELA} WHERE tenant_id = %s", (tenant,))
        self.admin.execute("ROLLBACK TO SAVEPOINT papel")
        self.admin.execute("SAVEPOINT papel")
        self.admin.execute("SET LOCAL ROLE kamba_batch")
        caminho = jobs.CAMINHOS["idempotencia_do_painel"][0]
        limite = politica.classe("idempotencia_do_painel").prazo.antes_de(datetime.now(timezone.utc))
        self.admin.execute(caminho.sql_apagar, caminho.parametros(tenant, limite, ()))
        self.assertEqual(self.admin.rowcount, 1)
        self.admin.execute("ROLLBACK TO SAVEPOINT papel")

    def test_a_forma_da_chave_e_a_da_rota(self) -> None:
        da_rota = re.search(r"FORMA_DA_CHAVE = /(.+)/;", DUPLO.read_text(encoding="utf-8"))
        da_revisao = re.search(r"""FORMA_DA_CHAVE = "'(.+)'"$""", REVISAO.read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(da_rota)
        self.assertIsNotNone(da_revisao)
        self.assertEqual(da_rota.group(1), da_revisao.group(1))

    def test_a_validade_da_chave_acaba_antes_da_purga(self) -> None:
        validade = re.search(
            r"VALIDADE_DA_CHAVE_MS = (\d+) \* (\d+) \* (\d+);", DUPLO.read_text(encoding="utf-8")
        )
        self.assertIsNotNone(validade, "a forma da constante mudou: o ensaio tem de a ler outra vez")
        ms = int(validade.group(1)) * int(validade.group(2)) * int(validade.group(3))
        agora = datetime(2026, 11, 22, tzinfo=timezone.utc)
        limite = politica.classe("idempotencia_do_painel").prazo.antes_de(agora)
        self.assertLess(timedelta(milliseconds=ms), agora - limite)


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


class TestDowngradeDaIdempotenciaDoPainel(ComBase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro.
    """

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _existe(self) -> int:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' AND tablename = 'painel_idempotencia'"
            )
            n = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_policies WHERE tablename = 'painel_idempotencia'")
            return n + int(c.fetchone()[0])
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        alembic_ok("downgrade", _anterior())
        try:
            self.assertEqual(self._existe(), 0)
        finally:
            alembic_ok("upgrade", "head")
        self.assertEqual(self._existe(), 2)
