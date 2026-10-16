"""Base comum dos testes do gate 8.

Estes testes sao **destrutivos**: fazem `downgrade base`, que apaga o schema
`platform`. Por isso ha um trinco, e ele nao e opcional:

    a base tem de se chamar exactamente `kamba_gate8`.

`db/gate_bd.py` cria uma base com esse nome num PostgreSQL descartavel. Apontar
estes testes a `kamba_platform` — por engano num `.env`, por uma variavel
herdada da shell — faz a suite recusar-se a correr em vez de apagar a base de
desenvolvimento.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

import bootstrap
import ligacao

DB = Path(__file__).resolve().parents[1]
BASE_DESCARTAVEL = "kamba_gate8"

#: O que a revisao 0001 cria em `platform`.
TABELAS_0001 = ("entitlements", "tenant_channels", "tenants")

#: O que a revisao 0003 (KAM-008) acrescenta: identidade de contacto.
TABELAS_0003 = ("contact_deks", "contact_endpoints", "contacts", "hmac_key_versions")

#: O que a revisao 0004 (KAM-005) acrescenta: outbox, sequencia por agregado,
#: subscricoes e o arquivo de eventos. O `events_log_default` esta aqui porque
#: o `pg_tables` lista a particao (`relkind` 'r') ao lado da particionada
#: ('p'): sao duas linhas do catalogo, e a lista e do catalogo.
TABELAS_0004 = (
    "events_log",
    "events_log_default",
    "events_outbox",
    "evt_agregado_seq",
    "evt_subscricoes",
)

#: Tudo o que existe em `platform` em `head`, por ordem alfabetica. Lista
#: fechada: uma tabela a mais (encomendas, pagamentos, consumidores) e escopo de
#: outro ticket, e entra aqui pela mao de quem a criar.
TABELAS = tuple(sorted(TABELAS_0001 + TABELAS_0003 + TABELAS_0004))

#: O que existe em `platform` quando a base esta na revisao `0003`.
#:
#: Faz falta porque o Alembic corre **uma transaccao por revisao**
#: (`transaction_per_migration=True` em `migrations/env.py`): um `downgrade 0002`
#: a partir da cabeca desce a `0004` — que confirma — e so depois tenta a
#: `0003`. Se a `0003` recusar (tem linhas de identidade e nao ha copia), a base
#: fica em `0003`, nao em `head`. Os testes que provam essa recusa comparam com
#: esta lista, e nao com `TABELAS`.
TABELAS_ATE_0003 = tuple(sorted(TABELAS_0001 + TABELAS_0003))


def exigir_base_descartavel() -> None:
    base = os.environ.get("KAMBA_DB_NAME", "")
    # Igualdade e nao sufixo: com `endswith("_gate8")`, uma base chamada
    # `producao_gate8` passava o trinco.
    if base != BASE_DESCARTAVEL:
        raise unittest.SkipTest(
            f"KAMBA_DB_NAME={base!r} nao e {BASE_DESCARTAVEL!r}. Os testes do "
            "gate 8 apagam o schema `platform` e so correm contra a base "
            "descartavel que `python db/gate_bd.py` cria."
        )


def alembic_cli(*argumentos: str) -> subprocess.CompletedProcess:
    """Corre o Alembic pela linha de comandos, como o criterio de aceitacao diz.

    Um processo novo por chamada. E o que `test_migracao.TestCiclo` usa para o
    ciclo `upgrade -> downgrade -> upgrade` do criterio 1 do KAM-003; o resto
    da suite usa `alembic`, que faz o mesmo sem pagar o arranque do processo.
    """
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", *argumentos],
        cwd=DB,
        capture_output=True,
        text=True,
    )


def alembic(*argumentos: str) -> subprocess.CompletedProcess:
    """Corre o Alembic **neste processo**, pela entrada da linha de comandos.

    `CommandLine` e a classe que o executavel `alembic` usa: o mesmo analisador
    de argumentos, a mesma leitura do `alembic.ini`, o mesmo `env.py`, as mesmas
    revisoes. O que nao se paga e o arranque de um interpretador e a importacao
    do SQLAlchemy em cada chamada — medido em Windows, oito a nove segundos por
    chamada, numa suite que faz dezenas. Devolve o mesmo que `alembic_cli`:
    codigo de saida, saida e erros, com o *traceback* de uma revisao que falhe
    nos erros. `TestCiclo` confere que os dois dizem o mesmo.

    A `Config` constroi-se aqui, e nao por `CommandLine.main`, so para lhe dar
    onde escrever: a omissao do seu `stdout` e o `sys.stdout` do momento em que
    o modulo foi importado, que um `redirect_stdout` ja nao apanha.
    """
    import contextlib
    import io
    import traceback

    from alembic.config import CommandLine, Config

    saida, erros = io.StringIO(), io.StringIO()
    codigo = 0
    comando = ["-c", "migrations/alembic.ini", *argumentos]
    with (
        contextlib.chdir(DB),
        contextlib.redirect_stdout(saida),
        contextlib.redirect_stderr(erros),
    ):
        try:
            linha = CommandLine(prog="alembic")
            opcoes = linha.parser.parse_args(comando)
            linha.run_cmd(
                Config(file_="migrations/alembic.ini", stdout=saida, cmd_opts=opcoes),
                opcoes,
            )
        except SystemExit as saiu:
            codigo = saiu.code if isinstance(saiu.code, int) else int(saiu.code is not None)
        except Exception:  # noqa: BLE001 — uma revisao que falha e um resultado, nao um erro do teste
            traceback.print_exc(file=erros)
            codigo = 1
    return subprocess.CompletedProcess(comando, codigo, saida.getvalue(), erros.getvalue())


def _exigir_sucesso(resultado: subprocess.CompletedProcess, argumentos: tuple) -> None:
    if resultado.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(argumentos)} falhou ({resultado.returncode}):\n"
            f"{resultado.stdout}\n{resultado.stderr}"
        )


def alembic_ok(*argumentos: str) -> None:
    _exigir_sucesso(alembic(*argumentos), argumentos)


def alembic_cli_ok(*argumentos: str) -> None:
    _exigir_sucesso(alembic_cli(*argumentos), argumentos)


def sqlstate(excepcao: BaseException) -> str:
    """O SQLSTATE de um erro do pg8000 (campo `C` da mensagem do servidor)."""
    for argumento in excepcao.args:
        if isinstance(argumento, dict) and "C" in argumento:
            return str(argumento["C"])
    return ""


#: SQLSTATE por nome, para os testes dizerem o que esperam e nao um numero.
VIOLACAO_DE_CHECK = "23514"
VIOLACAO_DE_UNICIDADE = "23505"
VIOLACAO_DE_FK = "23503"
VIOLACAO_DE_NOT_NULL = "23502"
PRIVILEGIO_INSUFICIENTE = "42501"


def revisao_de_cabeca() -> str:
    """A revisao mais alta de `migrations/versions/` (os ficheiros sao `NNNN_*.py`)."""
    return max(
        ficheiro.name[:4]
        for ficheiro in (DB / "migrations" / "versions").glob("[0-9][0-9][0-9][0-9]_*.py")
    )


def em_head() -> bool:
    """A base ja esta na revisao de cabeca? Sem lancar um processo do Alembic.

    Cada `alembic upgrade head` e um processo novo, e sao segundos — mesmo
    quando nao ha nada para fazer, que e o caso de quase todas as classes de
    teste. Pergunta-se a base em que revisao esta e so se chama o Alembic
    quando a resposta nao e a cabeca. Quem prova as migracoes em si
    (`test_migracao.TestCiclo`, `test_identidade_schema.TestDowngradeDa0003`)
    chama o Alembic sempre, e nao passa por aqui.
    """
    import pg8000.dbapi

    conexao = ligacao.ligar("admin")
    try:
        cursor = conexao.cursor()
        cursor.execute("SELECT version_num FROM public.alembic_version")
        return [tuple(linha) for linha in cursor.fetchall()] == [(revisao_de_cabeca(),)]
    except pg8000.dbapi.DatabaseError:
        return False  # a tabela de versao ainda nao existe: base por migrar
    finally:
        conexao.close()


class ComBase(unittest.TestCase):
    """Garante papeis criados e o schema em `head` antes de cada classe."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self._conexoes = []

    def tearDown(self) -> None:
        for conexao in self._conexoes:
            try:
                conexao.rollback()
            finally:
                conexao.close()

    def ligar(self, identidade: str):
        """Ligacao que nunca faz `commit`: cada teste desfaz o que escreveu."""
        conexao = ligacao.ligar(identidade)
        self._conexoes.append(conexao)
        return conexao

    def consultar(self, sql: str, parametros: tuple = (), identidade: str = "admin"):
        cursor = self.ligar(identidade).cursor()
        cursor.execute(sql, parametros)
        # O pg8000 devolve listas; normaliza-se para tuplos, que se comparam
        # e entram em conjuntos.
        return [tuple(linha) for linha in cursor.fetchall()]

    def assertErroSql(self, esperado: str, cursor, sql: str, parametros: tuple = ()):
        """A instrucao tem de falhar, e com o SQLSTATE esperado.

        Corre dentro de um `SAVEPOINT`: um erro aborta a transaccao inteira no
        PostgreSQL, e sem ele o teste perdia o que ja tinha inserido (o tenant
        de que o caso negativo precisa) e nao podia continuar na mesma ligacao.
        """
        import pg8000.dbapi

        cursor.execute("SAVEPOINT caso_negativo")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                cursor.execute(sql, parametros)
        finally:
            cursor.execute("ROLLBACK TO SAVEPOINT caso_negativo")
        self.assertEqual(
            sqlstate(capturado.exception),
            esperado,
            f"falhou, mas nao pela razao esperada: {capturado.exception}",
        )
