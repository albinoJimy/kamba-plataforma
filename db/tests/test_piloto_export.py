"""O `piloto-export` sem base e contra a base (KAM-109).

Duas metades:

1. **Sem base**: a coorte em CSV, a contagem de conversas pela regra do
   `h6-export`, e o `montar` com a lista fechada de campos.
2. **Contra o PostgreSQL de ensaio**, com dados **sinteticos** semeados numa
   transaccao que nunca confirma, e as leituras feitas **como `kamba_batch`**
   (`SET LOCAL ROLE`): cada campo da exportacao contra o que se semeou, as
   conversas de teste em producao (`is_test`) de fora, as accoes que nao sao do
   dono de fora, e nenhum `contact_id` na saida.

Os ciclos pagos medem-se em `db/tests_pagamentos/test_subscricao_paga_no_piloto.py`,
que tem a maquinaria do ledger.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
for _caminho in (_RAIZ / "libs" / "py-core" / "src", _RAIZ / "tools"):
    if str(_caminho) not in sys.path:
        sys.path.insert(0, str(_caminho))

import h6_export  # noqa: E402
import piloto_export as pe  # noqa: E402
from tests import factories  # noqa: E402
from tests.base import ComBase  # noqa: E402

LUANDA = dt.timezone(dt.timedelta(hours=1))
DIA = dt.date(2027, 1, 10)
FIM_DO_CICLO = dt.date(2027, 2, 10)
T1 ="00000000-0000-4000-8000-000000000001"


class TestCoorte(unittest.TestCase):
    def test_le_a_coorte_e_as_saidas(self) -> None:
        linhas = pe.ler_coorte(
            "pme,tenant_id,saida_dia,motivo\n"
            f"P01,{T1.upper()},,\n"
            "P02,00000000-0000-4000-8000-000000000002,2027-01-19,sem_uso_semana_2\n"
        )
        self.assertEqual(linhas[0]["tenant_id"], T1)
        self.assertEqual(linhas[1]["saida"], dt.date(2027, 1, 19))

    def test_recusa_o_que_nao_e_coorte(self) -> None:
        for texto in (
            "",
            "pme,tenant_id\nP01,x\n",
            "pme,tenant_id,saida_dia,motivo\nLoja,x,,\n",
            "pme,tenant_id,saida_dia,motivo\nP01,x,2027-01-19,\n",
            "pme,tenant_id,saida_dia,motivo\nP01,x,2027-01-19,o dono ligou\n",
            "pme,tenant_id,saida_dia,motivo\n",
        ):
            with self.subTest(texto=texto), self.assertRaises(pe.ErroDeUso):
                pe.ler_coorte(texto)


def _m(contacto: int, quando: dt.datetime) -> h6_export.Mensagem:
    return h6_export.Mensagem(T1, contacto, quando, quando.date(), False, None)


class TestMontar(unittest.TestCase):
    def test_conversas_iniciadas_por_dia(self) -> None:
        manha = dt.datetime(2027, 1, 10, 9, tzinfo=dt.timezone.utc)
        contagem = pe.conversas_por_dia([
            _m(1, manha), _m(1, manha + dt.timedelta(hours=23)),  # a mesma conversa
            _m(1, manha + dt.timedelta(hours=48)),                # pausa > 24 h: outra
            _m(2, manha),
        ])
        self.assertEqual(contagem, {(T1, DIA): 2, (T1, DIA + dt.timedelta(days=2)): 1})

    def test_montar_corta_no_ultimo_dia_e_passa_a_lista_fechada(self) -> None:
        coorte = pe.ler_coorte(f"pme,tenant_id,saida_dia,motivo\nP01,{T1},,\n")
        depois = DIA + dt.timedelta(days=5)
        bruto = pe.montar(
            coorte, True, DIA, {T1: DIA - dt.timedelta(days=3)}, {T1: True}, {T1},
            {(T1, DIA): 2, (T1, depois): 9}, {(T1, DIA): (3, 1)}, {(T1, DIA): 1},
            {(T1, DIA): (Decimal("0.5"), Decimal("0.004"))},
            [(T1, DIA, FIM_DO_CICLO, DIA, 3_000_000, "AOA", True, False),
             (T1, DIA, FIM_DO_CICLO, DIA, 1, "AOA", False, False),
             (T1, DIA, FIM_DO_CICLO, depois, 3_000_000, "AOA", False, True)],
        )
        pme = bruto["pmes"][0]
        self.assertEqual(list(pme["dias"]), [DIA.isoformat()])
        self.assertEqual(pme["dias"][DIA.isoformat()],
                         {"conversas": 2, "accoes_dono": 3, "actualizacoes_catalogo": 1,
                          "handoffs": 1, "custo_llm_usd": "0.5", "custo_meta_usd": "0.004"})
        # O ciclo sem via conhecida e o pago depois do ultimo dia ficam de fora.
        self.assertEqual(pme["ciclos_pagos"],
                         [{"inicio": DIA.isoformat(), "fim": FIM_DO_CICLO.isoformat(),
                           "pago_em": DIA.isoformat(), "valor_minor": 3_000_000,
                           "moeda": "AOA", "via": "facilitador"}])

    def test_uma_activacao_depois_do_ultimo_dia_nao_aparece(self) -> None:
        coorte = pe.ler_coorte(f"pme,tenant_id,saida_dia,motivo\nP01,{T1},,\n")
        bruto = pe.montar(coorte, True, DIA, {T1: DIA + dt.timedelta(days=1)}, {}, set(),
                          {}, {}, {}, {}, [])
        self.assertIsNone(bruto["pmes"][0]["activada_em"])
        self.assertIsNone(bruto["pmes"][0]["self_service"])


class TestContraABase(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cur = self.conexao.cursor()
        self.cur.execute("SELECT (now() AT TIME ZONE 'Africa/Luanda')::date")
        self.hoje: dt.date = self.cur.fetchone()[0]
        self.d10 = self.hoje - dt.timedelta(days=10)
        self.d8 = self.hoje - dt.timedelta(days=8)

        self.t1 = factories.tenant(self.cur)
        factories.aceitar_contratos_vigentes(self.cur, self.t1)
        self.cur.execute(
            "INSERT INTO platform.tenant_state_log (tenant_id, de, para, motivo, actor, em) "
            "VALUES (%s, 'onboarding', 'ativo', 'ensaio', 'ensaio', %s)",
            (self.t1, self._meio_dia(self.hoje - dt.timedelta(days=20))),
        )
        canal = factories.canal(self.cur, self.t1)
        self.contactos = [factories.contacto(self.cur, self.t1) for _ in range(3)]
        conversas = [self._conversa(canal, c, teste=(i == 2)) for i, c in enumerate(self.contactos)]
        # Contacto 0: duas mensagens no d10 (uma conversa) e uma no d8 (outra).
        self._mensagem(canal, self.contactos[0], conversas[0], self._meio_dia(self.d10))
        self._mensagem(canal, self.contactos[0], conversas[0],
                       self._meio_dia(self.d10) + dt.timedelta(hours=1))
        self._mensagem(canal, self.contactos[0], conversas[0], self._meio_dia(self.d8))
        # Contacto 1: uma no d10. Contacto 2: conversa de teste, fica de fora.
        self._mensagem(canal, self.contactos[1], conversas[1], self._meio_dia(self.d10))
        self._mensagem(canal, self.contactos[2], conversas[2], self._meio_dia(self.d10))
        self.cur.execute(
            "INSERT INTO platform.handoffs (handoff_id, tenant_id, conversation_id, motivo, "
            "opened_at) VALUES (%s, %s, %s, 'ensaio sintetico', %s)",
            (f"h_{uuid.uuid4().hex[:8]}", self.t1, conversas[0], self._meio_dia(self.d8)),
        )
        for actor, accao in (("owner", "price.update"), ("owner", "stock.adjust"),
                             ("agent", "price.update")):
            self.cur.execute(
                "SELECT platform.audit_append(%s, %s, 'ensaio', %s, 'offer_terms', 'sku-1', "
                "NULL, sha256('ensaio'::bytea))",
                (self.t1, actor, accao),
            )
        self.cur.execute(
            "INSERT INTO dat.llm_call_log "
            "(ts, tenant_id, trace_id, vertical, no_grafo, papel, graph_version, "
            " modelo, fornecedor, tokens_in, tokens_out, tokens_cache, "
            " custo_usd, latencia_ms, resultado) "
            "VALUES (%s, %s, %s, 'vendedor', 'no_de_teste', 'chat', '1.0.0', "
            " 'modelo-de-teste', 'fornecedor_de_teste', 10, 10, 0, '0.5', 1, 'ok')",
            (self._meio_dia(self.d10), self.t1, str(uuid.uuid4())),
        )
        self.t2 = factories.tenant(self.cur)
        self.coorte = pe.ler_coorte(
            f"pme,tenant_id,saida_dia,motivo\nP01,{self.t1},,\n"
            f"P02,{self.t2},{self.d8.isoformat()},desistiu\n"
        )
        self.cur.execute("SET LOCAL ROLE kamba_batch")

    @staticmethod
    def _meio_dia(dia: dt.date) -> dt.datetime:
        return dt.datetime.combine(dia, dt.time(12), LUANDA)

    def _conversa(self, canal: str, contacto: str, teste: bool) -> str:
        conversa = str(uuid.uuid4())
        self.cur.execute(
            "INSERT INTO platform.conversations (id, tenant_id, contact_id, channel_id) "
            "VALUES (%s, %s, %s, %s)",
            (conversa, self.t1, contacto, canal),
        )
        if teste:
            # A conversa nasce sempre com `is_test = false` (o *trigger*
            # `conversations_is_test_nasce_falso`, `0064`); marca-se depois.
            self.cur.execute(
                "UPDATE platform.conversations SET is_test = true WHERE id = %s", (conversa,)
            )
        return conversa

    def _mensagem(self, canal: str, contacto: str, conversa: str, quando: dt.datetime) -> None:
        self.cur.execute(
            "INSERT INTO platform.outbound_messages "
            "(id, tenant_id, channel_id, contact_id, conversation_id, idempotency_key, "
            " wamid, kind, state, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'service', 'sent', %s)",
            (str(uuid.uuid4()), self.t1, canal, contacto, conversa,
             f"chave-{uuid.uuid4()}", f"wamid.ENSAIO{uuid.uuid4().hex[:12]}", quando),
        )

    def test_cada_campo_contra_o_semeado_como_kamba_batch(self) -> None:
        self.cur.execute("SELECT current_user")
        self.assertEqual(self.cur.fetchone()[0], "kamba_batch")
        bruto = pe.exportar(self.cur, self.coorte, sintetico=True, ate=self.hoje)
        p1, p2 = bruto["pmes"]
        self.assertTrue(bruto["sintetico"])
        self.assertEqual(p1["activada_em"], (self.hoje - dt.timedelta(days=20)).isoformat())
        self.assertTrue(p1["dpa_aceite"])
        self.assertIsNone(p1["self_service"], "sem onboarding_case, nao se sabe")
        dias = p1["dias"]
        self.assertEqual(dias[self.d10.isoformat()]["conversas"], 2, "a de teste fica de fora")
        self.assertEqual(Decimal(dias[self.d10.isoformat()]["custo_llm_usd"]), Decimal("0.5"))
        self.assertEqual(dias[self.d8.isoformat()]["conversas"], 1)
        self.assertEqual(dias[self.d8.isoformat()]["handoffs"], 1)
        self.assertEqual(dias[self.hoje.isoformat()]["accoes_dono"], 2, "a do agente nao conta")
        self.assertEqual(dias[self.hoje.isoformat()]["actualizacoes_catalogo"], 2)
        self.assertEqual((p2["na_coorte"], p2["activada_em"], p2["dpa_aceite"]), (False, None, False))

    def test_nenhum_contact_id_sai(self) -> None:
        texto = json.dumps(pe.exportar(self.cur, self.coorte, sintetico=True, ate=self.hoje))
        for contacto in self.contactos:
            self.assertNotIn(contacto, texto)

    def test_por_omissao_o_ultimo_dia_e_ontem(self) -> None:
        bruto = pe.exportar(self.cur, self.coorte, sintetico=True)
        self.assertEqual(bruto["ultimo_dia"], (self.hoje - dt.timedelta(days=1)).isoformat())
        self.assertNotIn(self.hoje.isoformat(), bruto["pmes"][0]["dias"])

    def test_um_tenant_que_nao_existe_e_erro_de_uso(self) -> None:
        coorte = pe.ler_coorte(f"pme,tenant_id,saida_dia,motivo\nP01,{uuid.uuid4()},,\n")
        with self.assertRaises(pe.ErroDeUso):
            pe.exportar(self.cur, coorte, sintetico=True)

    def test_os_produtos_do_sorteio(self) -> None:
        self.cur.execute("RESET ROLE")
        factories.contexto(self.cur, self.t1)
        for sku, estado, quantidade, preco in (
            ("sku-a", "publicado", None, 1000), ("sku-b", "publicado", 0, 2000),
            ("sku-c", "pausado", 5, 3000), ("sku-d", "rascunho", 5, 4000),
        ):
            self.cur.execute(
                "INSERT INTO platform.offer_terms (tenant_id, sku, nome, preco_tipo, preco_minor, "
                "currency, stock_modo, estado, stock_quantidade) "
                "VALUES (%s, %s, %s, 'fixo', %s, 'AOA', 'indicativo', %s, %s)",
                (self.t1, sku, f"Produto sintetico {sku}", preco, estado, quantidade),
            )
        self.cur.execute("SET LOCAL ROLE kamba_batch")
        linhas = pe.produtos(self.cur, self.coorte, "P01").splitlines()
        self.assertEqual(linhas, [
            "produto_id,nome,preco_minor,disponivel",
            "sku-a,Produto sintetico sku-a,1000,sim",
            "sku-b,Produto sintetico sku-b,2000,nao",
            "sku-c,Produto sintetico sku-c,3000,nao",
        ])


if __name__ == "__main__":
    unittest.main()
