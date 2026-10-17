"""O `once(key, fn)` contra a base real: o que a tabela promete (KAM-006, CA9).

O `once()` esta em TypeScript (`packages/core-ts/src/eventos/accoes.ts`) e tem
bateria propria com uma base falsa — a decisao («abriu», «ja estava em curso»,
«ja falhou») testa-se la, sem PostgreSQL. **O que uma base falsa nao prova e
que a base concorda**: que o `ON CONFLICT (idempotency_key) DO NOTHING` devolve
zero linhas a segunda vez, que o `AND estado = 'em_curso'` do fecho impede
fechar duas vezes, e que a RLS deixa `kamba_app` escrever so no seu tenant.

Sao essas tres, com o **mesmo SQL** do modulo — lido do ficheiro TypeScript e
convertido de `$1` para `%s`, como o espelho em Python faz. Reescrever o SQL
aqui a mao provava que a copia funciona, nao que o modulo funciona.
"""

from __future__ import annotations

import re
import unittest
import uuid
from pathlib import Path

from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK, ComBase, sqlstate

RAIZ = Path(__file__).resolve().parents[2]
CONSULTAS = RAIZ / "packages" / "core-ts" / "src" / "eventos" / "consultas_consumo.ts"

#: `consumer:event_id:accao`, a forma do §6.3. A accao e um nome curto.
ACCAO = "enviar_whatsapp"


class Consulta:
    """Uma consulta do TypeScript, pronta para o `pg8000`.

    **O `pg8000` nao tem `$n`: tem `%s`, e liga-os pela ordem em que aparecem
    no texto.** O `SQL_FECHAR_ACCAO` escreve `SET estado = $2, resultado = $3
    ... WHERE idempotency_key = $1`, pelo que a troca ingenua de `$n` por `%s`
    muda o significado dos argumentos — e o PostgreSQL recusou, a primeira
    execucao desta bateria, um `'feita'` onde esperava `jsonb`. Por isso esta
    classe guarda a **ordem** em que os marcadores aparecem e reordena o que se
    lhe passa: quem chama escreve os argumentos pela numeracao do documento
    (`$1, $2, $3`) e nao pela do texto.
    """

    def __init__(self, nome: str) -> None:
        texto = CONSULTAS.read_text(encoding="utf-8")
        achado = re.search(rf"export const {nome} = `(.*?)`;", texto, re.S)
        if achado is None:
            raise AssertionError(f"nao se encontrou {nome} em {CONSULTAS.name}")
        self.nome = nome
        self.fonte = achado.group(1)
        self.ordem = [int(n) for n in re.findall(r"\$(\d+)", self.fonte)]
        self.sql = re.sub(r"\$\d+", "%s", self.fonte)

    def args(self, *valores: object) -> tuple[object, ...]:
        """Os `valores` — na numeracao do documento — pela ordem do texto."""
        if sorted(self.ordem) != list(range(1, len(valores) + 1)):
            raise AssertionError(
                f"{self.nome} tem os marcadores {self.ordem} e deram-se "
                f"{len(valores)} argumentos"
            )
        return tuple(valores[n - 1] for n in self.ordem)


class ComAccoes(ComBase):
    """Um cursor de `kamba_app` com contexto, e as consultas do modulo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.abrir_accao = Consulta("SQL_ABRIR_ACCAO")
        cls.ler_accao = Consulta("SQL_LER_ACCAO")
        cls.fechar_accao = Consulta("SQL_FECHAR_ACCAO")
        cls.definir_tenant = Consulta("SQL_DEFINIR_TENANT")

    def setUp(self) -> None:
        super().setUp()
        self.tenant = str(uuid.uuid4())
        self.consumer = "ensaio"
        self.event_id = str(uuid.uuid4())
        self.chave = f"{self.consumer}:{self.event_id}:{ACCAO}"
        self.cursor = self.ligar("app").cursor()
        self.definir(self.tenant)

    def definir(self, tenant: str | None) -> None:
        """O `SET LOCAL app.tenant_id`, pela consulta do modulo."""
        self.cursor.execute(
            self.definir_tenant.sql, self.definir_tenant.args(tenant or "", True)
        )
        self.cursor.fetchone()

    def ler(self):
        self.cursor.execute(self.ler_accao.sql, self.ler_accao.args(self.chave))
        return self.cursor.fetchone()

    def abrir(self, chave: str | None = None, tenant: str | None = None) -> int:
        self.cursor.execute(
            self.abrir_accao.sql,
            self.abrir_accao.args(
                chave or self.chave,
                self.consumer,
                self.event_id,
                ACCAO,
                tenant or self.tenant,
            ),
        )
        return int(self.cursor.rowcount)

    def fechar(self, estado: str, resultado: str | None = None) -> int:
        self.cursor.execute(
            self.fechar_accao.sql, self.fechar_accao.args(self.chave, estado, resultado)
        )
        return int(self.cursor.rowcount)


class TestAbrirUmaVez(ComAccoes):
    def test_a_primeira_abertura_escreve_uma_linha_em_curso(self) -> None:
        self.assertEqual(self.abrir(), 1)
        estado, resultado = self.ler()
        self.assertEqual(estado, "em_curso")
        self.assertIsNone(resultado)

    def test_a_segunda_abertura_da_zero_linhas(self) -> None:
        """E este zero que o `once()` le como «outro ja a registou».

        Se o `ON CONFLICT` nao estivesse aqui, a segunda chamada levantava uma
        violacao de unicidade e o efeito externo repetia-se a cada re-entrega
        — ou, pior, o erro era apanhado e lido como «nao estava registada».
        """
        self.assertEqual(self.abrir(), 1)
        self.assertEqual(self.abrir(), 0)
        self.cursor.execute(
            "SELECT count(*) FROM platform.evt_acoes WHERE idempotency_key = %s",
            (self.chave,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 1)

    def test_o_alvo_do_conflito_esta_nomeado(self) -> None:
        """`ON CONFLICT (idempotency_key)`, e nao `ON CONFLICT` sozinho.

        Sem alvo, um conflito em **qualquer** indice unico que a tabela venha a
        ter devolve zero linhas — e esse zero le-se «ja esta registada», que e
        um efeito externo saltado em silencio.
        """
        self.assertIn("ON CONFLICT (idempotency_key) DO NOTHING", self.abrir_accao.fonte)


class TestFecharUmaVez(ComAccoes):
    def test_fecha_uma_vez_e_guarda_o_resultado(self) -> None:
        self.abrir()
        self.assertEqual(self.fechar("feita", '{"mensagem":"wamid.X"}'), 1)
        estado, resultado = self.ler()
        self.assertEqual(estado, "feita")
        self.assertEqual(resultado, {"mensagem": "wamid.X"})

    def test_o_segundo_fecho_nao_faz_nada(self) -> None:
        """O `AND estado = 'em_curso'` do fecho e o que impede reescrever.

        Sem ele, uma segunda passagem sobrescrevia o resultado da primeira — e
        numa accao `falhada` que passasse a `feita` ninguem voltava a olhar.
        """
        self.abrir()
        self.assertEqual(self.fechar("feita", None), 1)
        self.assertEqual(self.fechar("falhada", '{"erro":"500"}'), 0)
        self.assertEqual(self.ler()[0], "feita")

    def test_os_tres_estados_do_ddl_e_so_esses(self) -> None:
        self.abrir()
        for estado in ("feita", "falhada"):
            with self.subTest(estado=estado):
                self.cursor.execute("SAVEPOINT bom")
                self.assertEqual(self.fechar(estado), 1)
                self.cursor.execute("ROLLBACK TO SAVEPOINT bom")
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            self.cursor,
            self.fechar_accao.sql,
            self.fechar_accao.args(self.chave, "quase", None),
        )


class TestIsolamento(ComAccoes):
    """A RLS de `evt_acoes`: `kamba_app` escreve e le so no seu tenant."""

    def test_nao_se_registra_uma_accao_de_outro_tenant(self) -> None:
        outro = str(uuid.uuid4())
        # `42501` com texto de *row-level security*: e a politica a recusar, e
        # nao um privilegio em falta. Aceitar qualquer `42501` aqui passava se
        # alguem tirasse o `INSERT` a `kamba_app` — pela razao errada.
        self.cursor.execute("SAVEPOINT cruzado")
        try:
            import pg8000.dbapi

            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                self.abrir(tenant=outro)
        finally:
            self.cursor.execute("ROLLBACK TO SAVEPOINT cruzado")
        self.assertEqual(sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE)
        self.assertIn("row-level security", str(capturado.exception))

    def test_sem_contexto_nao_se_ve_a_propria_accao(self) -> None:
        """Falha fechada: sem contexto, zero linhas — nunca «todas»."""
        self.abrir()
        self.definir(None)
        self.assertIsNone(self.ler())


if __name__ == "__main__":
    unittest.main()
