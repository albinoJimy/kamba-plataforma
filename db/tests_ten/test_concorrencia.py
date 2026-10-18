"""Criterio 3 do KAM-009: mil chamadas paralelas de 1 contra limite 100.

«1 000 chamadas paralelas de 1 unidade contra limite 100 aceitam exactamente
**100** e negam **900**; o contador final e **100**.» O numero e o do criterio
e nao folga: com cem chamadas a afirmacao era outra.

**Mil a serio, em ligacoes concorrentes.** Nao se simula concorrencia com um
laco: o que esta em prova e a serializacao no bloqueio da linha de
`tenant_usage` e a reavaliacao do `WHERE` do `ON CONFLICT DO UPDATE` sobre o
valor **ja actualizado** pela transaccao anterior. Um laco sequencial dava os
mesmos cem e nao provava nada disso.

**Trinta e duas ligacoes, e nao mil.** Mil ligacoes abertas ao mesmo tempo
estouram o `max_connections` por omissao (100) e o que se media passava a ser
a gestao do *pool*. Com 32 ha sempre dezenas de transaccoes a disputar a mesma
linha, que e o que se quer. E a mesma escolha, pela mesma razao, do
`tests_auditoria_carga` do KAM-012.

**O livro conta tanto como o contador.** Cada chamada negada inseriu a sua
chave de idempotencia e levou-a consigo no *rollback* da subtransaccao. Se o
desfazer nao funcionasse sob concorrencia, ficavam no livro mil chaves em vez
de cem — e nenhuma delas podia ser repetida. E a mesma propriedade que o
`test_idempotencia` prova numa ligacao so; aqui prova-se com novecentos
*rollbacks* em paralelo.
"""

from __future__ import annotations

import concurrent.futures
import time
import unittest

import ligacao
from tests import factories
from tests.base import ComBase
from tests_ten.base import CHAVE, consumir

#: Os numeros do criterio. Nao sao folga.
CHAMADAS = 1000
LIMITE = 100

#: Quantas ligacoes em paralelo. Ver a docstring do modulo.
LIGACOES = 32


class TestMilChamadasParalelas(ComBase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._admin = ligacao.ligar("admin")
        cls._admin.autocommit = True
        semente = cls._admin.cursor()
        cls.tenant = factories.tenant(semente)
        factories.entitlement(semente, cls.tenant, limites={CHAVE: LIMITE})

        cls.resultados = []
        cls.erros: list[str] = []
        comecou = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=LIGACOES) as piscina:
            tarefas = [piscina.submit(cls._consumir, n) for n in range(CHAMADAS)]
            for tarefa in concurrent.futures.as_completed(tarefas):
                consumo, erro = tarefa.result()
                if erro:
                    cls.erros.append(erro)
                else:
                    cls.resultados.append(consumo)
        cls.segundos = time.monotonic() - comecou
        # O numero fica na saida do gate, como o p95 da carga de eventos: e o
        # que permite dizer no bloco do ticket quanto custou, em vez de o
        # estimar.
        print(
            f"\nconcorrencia TEN: {CHAMADAS} chamadas de 1 unidade contra tecto "
            f"{LIMITE}, {LIGACOES} ligacoes, {cls.segundos:.1f}s"
        )

    @classmethod
    def _consumir(cls, n: int):
        """Uma chamada de 1 unidade, numa ligacao propria, com `commit`.

        Cada chamada tem a sua chave de idempotencia: o que se mede e a
        concorrencia, e mil chamadas com a mesma chave mediam outra coisa (e
        essa tem suite propria).
        """
        conexao = ligacao.ligar("app")
        try:
            cursor = conexao.cursor()
            cursor.execute(
                "SELECT set_config('app.tenant_id', %s, true)", (cls.tenant,)
            )
            cursor.fetchone()
            consumo = consumir(
                cursor, cls.tenant, quantidade=1, idempotency_key=f"paralela-{n}"
            )
            conexao.commit()
            return consumo, None
        except Exception as erro:  # noqa: BLE001 — queremos a mensagem, seja qual for
            return None, f"{type(erro).__name__}: {erro}"
        finally:
            conexao.close()

    @classmethod
    def tearDownClass(cls) -> None:
        cursor = cls._admin.cursor()
        for tabela in ("usage_ledger", "tenant_usage", "entitlements"):
            cursor.execute(
                f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (cls.tenant,)
            )
        cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (cls.tenant,))
        cls._admin.close()
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()

    def test_nenhuma_chamada_falhou(self) -> None:
        """Negar nao e falhar: uma excepcao aqui e a serializacao a ceder.

        Um `deadlock detected` ou um `could not serialize` quer dizer que as
        mil nao se puseram em fila no bloqueio da linha — e entao nem as
        contagens abaixo significam o que dizem.
        """
        self.assertEqual(self.erros[:5], [], f"{len(self.erros)} falha(s)")
        self.assertEqual(len(self.resultados), CHAMADAS)

    def test_aceitam_exactamente_cem(self) -> None:
        aceites = [r for r in self.resultados if r.aceite]
        self.assertEqual(
            len(aceites), LIMITE, f"em {CHAMADAS} paralelas, {self.segundos:.1f}s"
        )

    def test_negam_exactamente_novecentas(self) -> None:
        negadas = [r for r in self.resultados if not r.aceite]
        self.assertEqual(len(negadas), CHAMADAS - LIMITE)
        # E nenhuma delas e uma repeticao: as chaves sao todas diferentes.
        self.assertEqual([r for r in negadas if r.repetido], [])

    def test_o_contador_final_e_cem(self) -> None:
        self.cursor.execute(
            "SELECT valor FROM platform.tenant_usage "
            " WHERE tenant_id = %s AND chave_limite = %s",
            (self.tenant, CHAVE),
        )
        linhas = self.cursor.fetchall()
        self.assertEqual(len(linhas), 1, "uma linha por (tenant, chave, periodo)")
        self.assertEqual(int(linhas[0][0]), LIMITE)

    def test_cada_aceite_viu_um_valor_entre_um_e_cem(self) -> None:
        """Os valores devolvidos sao a sequencia 1..100, sem repeticoes.

        E a prova de que as cem aceites nao leram um valor obsoleto: duas a
        devolverem `37` eram duas a contar sobre a mesma leitura.
        """
        valores = sorted(int(r.valor) for r in self.resultados if r.aceite)
        self.assertEqual(valores, list(range(1, LIMITE + 1)))

    def test_o_livro_so_guarda_as_cem_aceites(self) -> None:
        """As novecentas negadas levaram a chave consigo no *rollback*."""
        self.cursor.execute(
            "SELECT count(*) FROM platform.usage_ledger WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(int(self.cursor.fetchone()[0]), LIMITE)

    def test_o_tecto_devolvido_e_sempre_o_do_entitlement(self) -> None:
        self.assertEqual({int(r.limite) for r in self.resultados}, {LIMITE})


if __name__ == "__main__":
    unittest.main()
