"""O experimento dos modulos de entrada contra a base (KAM-127).

O que so uma base prova:

1. **As vistas e as funcoes** (criterios 2 e 3): as colunas sao exactamente as
   da lista fechada, escrita **aqui** e nao importada do alvo; nenhuma aponta
   para uma pessoa; as fronteiras de 14 e de 30 dias, a censura, a exclusao da
   equipa e dos testes, e o que conta como resultado de valor em cada modulo.
2. **A H11**: entrar por um modulo, a resposta ao dono e a conversa de teste que
   nao contam, e as tres condicoes da activacao.
3. **A H12**: so um plano de um so modulo conta como pagamento isolado.
4. **A reproducao por script** (criterio 3): cinco tenants, e o
   `experimento-modulos reproduzir` da diferenca 0 — e da diferenca quando o
   Python e a base discordam.
5. **As duas tabelas**: so de acrescentar, nem ao administrador; so o
   `kamba_batch` escreve; o `catalogo` nao se abate e um «ajustar» leva data.
6. **O `downgrade`** para a revisao de baixo, lida do ficheiro.

Tudo o que escreve corre numa transaccao do administrador que **nunca
confirma**, e os papeis medem-se com `SET LOCAL ROLE`. As funcoes recebem um
relogio fixo num ano longe de tudo o que os outros ensaios escrevem. A revisao
encontra-se pelo *glob* `*_experimento_dos_modulos.py`: o numero e provisorio.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import bootstrap
import ligacao

_RAIZ = Path(__file__).resolve().parents[2]
_NUCLEO = str(_RAIZ / "libs" / "py-core" / "src")
if _NUCLEO not in sys.path:
    sys.path.insert(0, _NUCLEO)

import experimento_modulos as em  # noqa: E402
from tests import factories  # noqa: E402
from tests.base import (  # noqa: E402
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    ComBase,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
    sqlstate,
)

UTC = dt.timezone.utc
REVISAO = next((_RAIZ / "db" / "migrations" / "versions").glob("*_experimento_dos_modulos.py"))
DECISOES = "platform.module_decisions"
EXCLUSOES = "platform.module_experiment_exclusions"

#: As colunas das vistas, **por extenso**: um oraculo importado do alvo muda com ele.
COLUNAS_H10 = ("tenant_id", "provisionado_em", "censurado", "catalogo", "foto", "social", "orcamento", "algum")
COLUNAS_H11 = (
    "tenant_id", "primeiro_valor_em", "primeiro_modulo", "primeira_conversa_em",
    "entrou_por_modulo", "censurado", "activou",
)
COLUNAS_PAGANTES = ("tenant_id", "plano", "modulo", "ciclos_pagos")
PROIBIDAS = ("contact_id", "conversation_id", "telefone", "phone", "wamid", "texto", "legenda", "nome")

#: O relogio: um ano onde nenhum outro ensaio escreve.
T0 = dt.datetime(2033, 6, 1, 12, 0, tzinfo=UTC)
DIA = dt.timedelta(days=1)
SEGUNDO = dt.timedelta(seconds=1)


def _literal(nome: str):
    arvore = ast.parse(REVISAO.read_text(encoding="utf-8"))
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(getattr(t, "id", None) == nome for t in no.targets):
            return ast.literal_eval(no.value)
    raise AssertionError(f"{nome} nao encontrado em {REVISAO.name}")


class _ComTransaccao(ComBase):
    """Uma transaccao de administrador que nunca confirma."""

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        factories.contexto(self.cursor, None)
        # So os tenants deste ensaio: os de outros ensaios confirmados na base
        # nao tem `tenant.provisioned` em 2033, mas uma exclusao torna-o explicito.
        self.tenants: list[str] = []

    def como(self, papel: str) -> None:
        self.cursor.execute("RESET ROLE")
        if papel != "admin":
            self.cursor.execute(f"SET LOCAL ROLE {papel}")
        factories.contexto(self.cursor, None)

    def erro(self, esperado: str, sql: str, parametros: tuple = (), texto: str | None = None) -> None:
        import pg8000.dbapi

        self.cursor.execute("SAVEPOINT caso")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                self.cursor.execute(sql, parametros)
        finally:
            self.cursor.execute("ROLLBACK TO SAVEPOINT caso")
        self.assertEqual(sqlstate(capturado.exception), esperado, str(capturado.exception))
        if texto is not None:
            self.assertIn(texto, str(capturado.exception))

    # --- a semente ---------------------------------------------------------------

    def tenant(self, *, provisionado: dt.datetime | None = T0, tipo: str = "pme", plano: str | None = None) -> str:
        campos = {"tipo": tipo}
        if plano is not None:
            campos["plano"] = plano
        tenant = factories.tenant(self.cursor, **campos)
        factories.contexto(self.cursor, None)
        self.tenants.append(tenant)
        if provisionado is not None:
            self.evento(tenant, "tenant.provisioned", provisionado)
        return tenant

    def evento(self, tenant: str, tipo: str, quando: dt.datetime, payload: dict | None = None) -> None:
        self.cursor.execute(
            "INSERT INTO platform.events_log (event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
            "agregado_seq, ocorrido_em, registado_em, classe_pii, envelope) "
            "VALUES (%s, %s, 2, %s, 'ensaio', %s, 1, %s, %s, 'P0', %s::jsonb)",
            (str(uuid.uuid4()), tipo, tenant, str(uuid.uuid4()), quando, quando,
             json.dumps({"tipo": tipo, "payload": payload or {}})),
        )

    def catalogo(self, tenant: str, quando: dt.datetime, estado: str = "publicada") -> None:
        publicada = estado == "publicada"
        self.cursor.execute(
            "INSERT INTO platform.catalog_ingestions (tenant_id, media_ref, estado, sku, confirmado_at, confirmado_por) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (tenant, f"t/{tenant}/catalogo/{uuid.uuid4()}", estado, "SKU-1" if publicada else None,
             quando if publicada else None, "dono" if publicada else None),
        )

    def foto(self, tenant: str, quando: dt.datetime, *, escolhida: bool = True, sintetica: bool = False) -> None:
        self.cursor.execute(
            "INSERT INTO platform.image_jobs (tenant_id, origem_ref, versao_ref, operacao, provider, estado, "
            "idempotency_key, sintetica, escolhida, latencia_ms, atualizado_at) "
            "VALUES (%s, %s, %s, 'cutout', 'fornecedor_ensaio', 'concluido', %s, %s, %s, 10, %s)",
            (tenant, f"t/{tenant}/foto/{uuid.uuid4()}", f"t/{tenant}/foto/{uuid.uuid4()}",
             f"k-{uuid.uuid4()}", sintetica, escolhida, quando),
        )

    def resposta(self, tenant: str, quando: dt.datetime, *, papel: str = "cliente", teste: bool = False,
                 canal: str = "whatsapp") -> None:
        contacto = factories.contacto(self.cursor, tenant, papel=papel)
        canal_id = factories.canal(self.cursor, tenant)
        factories.contexto(self.cursor, None)
        if papel == "dono":
            # A `definir_dono` escreve as duas na mesma transaccao (`0070`).
            self.cursor.execute("UPDATE platform.tenants SET owner_contact_id = %s WHERE id = %s", (contacto, tenant))
        self.cursor.execute(
            "INSERT INTO platform.conversations (tenant_id, contact_id, channel_id) VALUES (%s, %s, %s) RETURNING id",
            (tenant, contacto, canal_id),
        )
        conversa = str(self.cursor.fetchone()[0])
        if teste:
            self.cursor.execute("UPDATE platform.conversations SET is_test = true WHERE id = %s", (conversa,))
        self.evento(tenant, "agent.replied", quando,
                    {"contact_id": contacto, "conversation_id": conversa, "canal": canal})

    def atendimento(self, tenant: str) -> None:
        """Canal ligado e vertical de atendimento activa."""
        factories.canal(self.cursor, tenant, estado="ativo")
        factories.entitlement(self.cursor, tenant, modulo="vendedor")
        factories.contexto(self.cursor, None)

    # --- as leituras --------------------------------------------------------------

    def h10(self, agora: dt.datetime, janela: int = 14) -> dict[str, tuple]:
        self.cursor.execute("SELECT * FROM platform.experimento_h10(%s, %s)", (agora, janela))
        return {str(l[0]): tuple(l[1:]) for l in self.cursor.fetchall() if str(l[0]) in self.tenants}

    def h11(self, agora: dt.datetime, janela: int = 30) -> dict[str, tuple]:
        self.cursor.execute("SELECT * FROM platform.experimento_h11(%s, %s)", (agora, janela))
        return {str(l[0]): tuple(l[1:]) for l in self.cursor.fetchall() if str(l[0]) in self.tenants}


class TestAsVistas(_ComTransaccao):
    def colunas(self, vista: str) -> tuple[str, ...]:
        self.cursor.execute(
            "SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass AND attnum > 0 "
            "AND NOT attisdropped ORDER BY attnum",
            (f"platform.{vista}",),
        )
        return tuple(l[0] for l in self.cursor.fetchall())

    def test_as_colunas_sao_a_lista_fechada_e_nenhuma_aponta_para_uma_pessoa(self) -> None:
        for vista, esperadas in (("v_h10", COLUNAS_H10), ("v_h11", COLUNAS_H11), ("v_h12_pagantes", COLUNAS_PAGANTES)):
            with self.subTest(vista=vista):
                colunas = self.colunas(vista)
                self.assertEqual(colunas, esperadas)
                self.assertFalse([c for c in colunas if any(p in c for p in PROIBIDAS)])

    def test_as_vistas_usam_as_janelas_pre_registadas(self) -> None:
        from kamba_core.modulos import experimento as ex

        limiares = ex.ler(_RAIZ / "config" / "experimento_modulos.yaml")
        self.assertEqual(_literal("JANELA_DE_USO_DIAS"), limiares.janela_de_uso_dias)
        self.assertEqual(_literal("JANELA_DE_ACTIVACAO_DIAS"), limiares.janela_de_activacao_dias)
        for vista, janela in (("v_h10", limiares.janela_de_uso_dias), ("v_h11", limiares.janela_de_activacao_dias)):
            self.cursor.execute("SELECT pg_get_viewdef(%s::regclass)", (f"platform.{vista}",))
            definicao = self.cursor.fetchone()[0]
            self.assertRegex(definicao, rf"now\(\),\s*{janela}\)")

    def test_so_o_lote_le_as_vistas(self) -> None:
        for vista in ("v_h10", "v_h11", "v_h12_pagantes"):
            with self.subTest(vista=vista):
                self.como("kamba_app")
                self.erro(PRIVILEGIO_INSUFICIENTE, f"SELECT * FROM platform.{vista}")
                self.como("kamba_batch")
                self.cursor.execute(f"SELECT count(*) FROM platform.{vista}")
                self.como("admin")

    def test_sem_relogio_ou_com_janela_invalida_falha_fechado(self) -> None:
        for funcao in ("experimento_h10", "experimento_h11"):
            for agora, janela in ((None, 14), (T0, 0), (T0, None)):
                with self.subTest(funcao=funcao, agora=agora, janela=janela):
                    self.erro("22023", f"SELECT * FROM platform.{funcao}(%s, %s)", (agora, janela))


class TestH10(_ComTransaccao):
    def test_a_fronteira_dos_14_dias_e_a_censura(self) -> None:
        tenant = self.tenant()
        self.catalogo(tenant, T0 + 14 * DIA - SEGUNDO)
        # Um segundo antes do fim da janela: censurado, e o uso ja conta.
        linha = self.h10(T0 + 14 * DIA - SEGUNDO)[tenant]
        self.assertEqual(linha[1:], (True, True, False, False, False, True))
        # Aos 14 dias exactos deixa de estar censurado.
        self.assertFalse(self.h10(T0 + 14 * DIA)[tenant][1])

    def test_um_valor_no_fim_exacto_da_janela_nao_conta(self) -> None:
        tenant = self.tenant()
        self.catalogo(tenant, T0 + 14 * DIA)
        linha = self.h10(T0 + 20 * DIA)[tenant]
        self.assertEqual(linha[2:], (False, False, False, False, False))

    def test_um_valor_antes_do_provisionamento_conta(self) -> None:
        """O painel web serve o dono antes de o WhatsApp estar ligado."""
        tenant = self.tenant()
        self.evento(tenant, "quote.sent", T0 - 3 * DIA)
        self.assertTrue(self.h10(T0 + 20 * DIA)[tenant][5])

    def test_cada_modulo_pelo_seu_resultado_de_valor(self) -> None:
        tenant = self.tenant()
        self.catalogo(tenant, T0 + DIA)
        self.foto(tenant, T0 + DIA)
        self.evento(tenant, "content.approved", T0 + DIA)
        self.evento(tenant, "quote.sent", T0 + DIA)
        self.assertEqual(self.h10(T0 + 20 * DIA)[tenant][2:], (True, True, True, True, True))

    def test_abrir_sem_resultado_nao_conta(self) -> None:
        tenant = self.tenant()
        self.catalogo(tenant, T0 + DIA, estado="rascunho")
        self.foto(tenant, T0 + DIA, escolhida=False)
        self.foto(tenant, T0 + DIA, sintetica=True)
        self.evento(tenant, "quote.requested", T0 + DIA)
        self.assertEqual(self.h10(T0 + 20 * DIA)[tenant][2:], (False, False, False, False, False))

    def test_o_valor_futuro_nao_conta(self) -> None:
        tenant = self.tenant()
        self.catalogo(tenant, T0 + 10 * DIA)
        self.assertFalse(self.h10(T0 + 5 * DIA)[tenant][2])

    def test_a_coorte_exclui_equipa_teste_e_quem_nao_e_pme(self) -> None:
        dentro = self.tenant()
        equipa = self.tenant()
        teste = self.tenant()
        courier = self.tenant(tipo="courier")
        sem_provisionamento = self.tenant(provisionado=None)
        self.como("kamba_batch")
        for tenant, motivo in ((equipa, "equipa"), (teste, "teste")):
            self.cursor.execute(f"INSERT INTO {EXCLUSOES} (tenant_id, motivo, registado_por) VALUES (%s, %s, 'ensaio')",
                                (tenant, motivo))
        self.como("admin")
        coorte = set(self.h10(T0 + 20 * DIA))
        self.assertIn(dentro, coorte)
        for fora in (equipa, teste, courier, sem_provisionamento):
            self.assertNotIn(fora, coorte)

    def test_o_primeiro_provisionamento_e_a_entrada(self) -> None:
        tenant = self.tenant()
        self.evento(tenant, "tenant.provisioned", T0 + 5 * DIA)
        self.assertEqual(self.h10(T0 + 20 * DIA)[tenant][0], T0)


class TestH11(_ComTransaccao):
    def test_entrou_por_um_modulo_e_activou(self) -> None:
        tenant = self.tenant()
        self.foto(tenant, T0 + DIA)
        self.catalogo(tenant, T0 + 2 * DIA)
        self.atendimento(tenant)
        self.resposta(tenant, T0 + 10 * DIA)
        linha = self.h11(T0 + 40 * DIA)[tenant]
        self.assertEqual(linha[0], T0 + DIA)
        self.assertEqual(linha[1], "foto")
        self.assertEqual(linha[2], T0 + 10 * DIA)
        self.assertEqual(linha[3:], (True, False, True))

    def test_a_conversa_antes_do_modulo_nao_e_entrar_por_um_modulo(self) -> None:
        tenant = self.tenant()
        self.resposta(tenant, T0 + DIA)
        self.catalogo(tenant, T0 + 2 * DIA)
        self.assertFalse(self.h11(T0 + 40 * DIA)[tenant][3])

    def test_a_resposta_ao_dono_e_a_conversa_de_teste_nao_contam(self) -> None:
        tenant = self.tenant()
        self.catalogo(tenant, T0 + 2 * DIA)
        self.atendimento(tenant)
        self.resposta(tenant, T0 + DIA, papel="dono")
        self.resposta(tenant, T0 + DIA, teste=True)
        self.resposta(tenant, T0 + DIA, canal="painel")
        linha = self.h11(T0 + 40 * DIA)[tenant]
        self.assertIsNone(linha[2])
        self.assertEqual(linha[3:], (True, False, False))

    def test_as_tres_condicoes_da_activacao(self) -> None:
        sem_canal = self.tenant()
        self.catalogo(sem_canal, T0 + DIA)
        factories.entitlement(self.cursor, sem_canal, modulo="vendedor")
        factories.contexto(self.cursor, None)
        self.resposta(sem_canal, T0 + 5 * DIA)
        # A janela e semiaberta: aos 30 dias exactos ja nao conta.
        tarde = self.tenant()
        self.catalogo(tarde, T0 + DIA)
        self.atendimento(tarde)
        self.resposta(tarde, T0 + 31 * DIA)
        no_limite = self.tenant()
        self.catalogo(no_limite, T0 + DIA)
        self.atendimento(no_limite)
        self.resposta(no_limite, T0 + 31 * DIA - SEGUNDO)
        leitura = self.h11(T0 + 60 * DIA)
        # `resposta` cria um canal `pendente`: o `sem_canal` nao tem nenhum activo.
        self.assertFalse(leitura[sem_canal][5])
        self.assertFalse(leitura[tarde][5])
        self.assertTrue(leitura[no_limite][5])

    def test_o_dono_e_o_owner_contact_id_e_nao_le_o_cofre(self) -> None:
        """A resposta ao dono nao conta, e o lote nao tem privilegio nenhum na `contacts`."""
        self.cursor.execute(
            "SELECT has_any_column_privilege('kamba_batch', 'platform.contacts', 'SELECT')"
        )
        self.assertFalse(self.cursor.fetchone()[0])
        tenant = self.tenant()
        self.catalogo(tenant, T0 + DIA)
        self.atendimento(tenant)
        self.resposta(tenant, T0 + 2 * DIA, papel="dono")
        self.como("kamba_batch")
        self.assertIsNone(self.h11(T0 + 40 * DIA)[tenant][2])

    def test_menos_de_30_dias_depois_do_primeiro_valor_e_censurado(self) -> None:
        tenant = self.tenant()
        self.catalogo(tenant, T0 + DIA)
        self.assertTrue(self.h11(T0 + 30 * DIA)[tenant][4])
        self.assertFalse(self.h11(T0 + 31 * DIA)[tenant][4])


class TestH12Pagantes(_ComTransaccao):
    def pago(self, tenant: str, plano: str) -> None:
        self.cursor.execute("UPDATE platform.tenants SET plano = %s WHERE id = %s", (plano, tenant))
        self.cursor.execute(
            "INSERT INTO platform.subscriptions (tenant_id, plano, estado, periodo_dia) VALUES (%s, %s, 'ativa', 1) "
            "RETURNING id",
            (tenant, plano),
        )
        subscricao = self.cursor.fetchone()[0]
        self.cursor.execute(
            "INSERT INTO platform.billing_cycles (subscription_id, tenant_id, periodo, valor_minor, estado) "
            "VALUES (%s, %s, daterange('2033-06-01', '2033-07-01'), 1500000, 'aberto') RETURNING id",
            (subscricao, tenant),
        )
        ciclo = self.cursor.fetchone()[0]
        self.cursor.execute("ALTER TABLE platform.billing_cycles DISABLE TRIGGER USER")
        self.cursor.execute("UPDATE platform.billing_cycles SET estado = 'paga' WHERE id = %s", (ciclo,))
        self.cursor.execute("ALTER TABLE platform.billing_cycles ENABLE TRIGGER USER")

    def precos(self) -> None:
        self.cursor.execute("DELETE FROM platform.module_test_prices")
        self.cursor.execute(
            "INSERT INTO platform.module_test_prices (plano, modulo, preco_teste_minor, estado) VALUES "
            "('entrada_foto', 'foto', 1500000, 'hipotese_nao_validada'), "
            "('entrada_completo', 'foto', 1500000, 'hipotese_nao_validada'), "
            "('entrada_completo', 'social', 6000000, 'hipotese_nao_validada')"
        )

    def test_so_um_plano_de_um_so_modulo_conta(self) -> None:
        self.precos()
        # A vista le a coorte de `now()`: o T0 de 2033 ainda nao chegou.
        passado = dt.datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
        isolado = self.tenant(provisionado=passado)
        completo = self.tenant(provisionado=passado)
        fora = self.tenant(provisionado=T0)
        self.pago(isolado, "entrada_foto")
        self.pago(fora, "entrada_foto")
        self.pago(completo, "entrada_completo")
        self.cursor.execute("SELECT tenant_id, plano, modulo, ciclos_pagos FROM platform.v_h12_pagantes")
        linhas = {str(l[0]): tuple(l[1:]) for l in self.cursor.fetchall()}
        self.assertEqual(linhas.get(isolado), ("entrada_foto", "foto", 1))
        self.assertNotIn(completo, linhas)
        self.assertNotIn(fora, linhas, "um tenant que ainda nao entrou na coorte nao conta")


class TestAsTabelas(_ComTransaccao):
    def decisao(self, modulo: str = "social", decisao: str = "manter", revisao: dt.date | None = None) -> str:
        self.cursor.execute(
            f"INSERT INTO {DECISOES} (modulo, data_decisao, metricas, criterio, decisao, responsavel, justificacao, "
            "revisao_em) VALUES (%s, '2033-08-24', '{\"uso\": {\"n\": 6, \"total\": 10}}'::jsonb, NULL, %s, "
            "'Responsavel de Produto', 'ensaio', %s) RETURNING id",
            (modulo, decisao, revisao),
        )
        return str(self.cursor.fetchone()[0])

    def test_so_o_lote_escreve_e_nem_o_administrador_emenda(self) -> None:
        self.como("kamba_batch")
        decisao = self.decisao()
        self.como("kamba_app")
        self.erro(PRIVILEGIO_INSUFICIENTE, f"SELECT * FROM {DECISOES}")
        self.como("admin")
        for sql in (f"UPDATE {DECISOES} SET decisao = 'abater' WHERE id = %s", f"DELETE FROM {DECISOES} WHERE id = %s"):
            with self.subTest(sql=sql.split()[0]):
                self.erro("55000", sql, (decisao,), "nao se emenda")
        for tabela in (DECISOES, EXCLUSOES):
            with self.subTest(truncate=tabela):
                self.erro("55000", f"TRUNCATE {tabela}", (), "nao se emenda")

    def test_os_gatilhos_sao_enable_always(self) -> None:
        self.cursor.execute(
            "SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid IN (%s::regclass, %s::regclass) "
            "AND NOT tgisinternal ORDER BY tgname",
            (DECISOES, EXCLUSOES),
        )
        self.assertEqual(
            [tuple(l) for l in self.cursor.fetchall()],
            [("module_decisions_imutavel", "A"), ("module_decisions_sem_truncate", "A"),
             ("module_experiment_exclusions_imutavel", "A"), ("module_experiment_exclusions_sem_truncate", "A")],
        )

    def test_o_catalogo_nao_se_abate_e_ajustar_leva_data(self) -> None:
        self.como("kamba_batch")
        self.cursor.execute("SAVEPOINT a")
        self.erro(VIOLACAO_DE_CHECK, f"INSERT INTO {DECISOES} (modulo, data_decisao, metricas, decisao, responsavel, "
                  "justificacao) VALUES ('catalogo', '2033-08-24', '{}', 'abater', 'x', 'y')",
                  texto="module_decisions_catalogo_ck")
        self.erro(VIOLACAO_DE_CHECK, f"INSERT INTO {DECISOES} (modulo, data_decisao, metricas, decisao, responsavel, "
                  "justificacao) VALUES ('foto', '2033-08-24', '{}', 'ajustar', 'x', 'y')",
                  texto="module_decisions_ajustar_ck")
        self.decisao(modulo="catalogo", decisao="ajustar", revisao=dt.date(2033, 9, 7))
        self.decisao(modulo="foto", decisao="abater")

    def test_a_exclusao_e_so_de_acrescentar(self) -> None:
        tenant = self.tenant()
        self.como("kamba_batch")
        self.cursor.execute(f"INSERT INTO {EXCLUSOES} (tenant_id, motivo, registado_por) VALUES (%s, 'equipa', 'x')",
                            (tenant,))
        self.erro(VIOLACAO_DE_CHECK, f"INSERT INTO {EXCLUSOES} (tenant_id, motivo, registado_por) "
                  "VALUES (%s, 'cliente', 'x')", (self.tenant(),))
        self.como("admin")
        self.erro("55000", f"DELETE FROM {EXCLUSOES} WHERE tenant_id = %s", (tenant,))


class TestAReproducao(_ComTransaccao):
    """Criterio 3: a metrica reproduzida por script da diferenca 0 em cinco tenants."""

    def semear_cinco(self) -> list[str]:
        tenants = []
        for i in range(5):
            tenant = self.tenant(provisionado=T0 + i * DIA)
            tenants.append(tenant)
        a, b, c, d, _e = tenants
        self.catalogo(a, T0 + 2 * DIA)
        self.atendimento(a)
        self.resposta(a, T0 + 5 * DIA)
        self.foto(b, T0 + 3 * DIA)
        self.resposta(b, T0 + 2 * DIA)
        self.evento(c, "content.approved", T0 + 20 * DIA)
        self.evento(d, "quote.sent", T0 + 4 * DIA)
        self.resposta(d, T0 + 4 * DIA, papel="dono")
        return tenants

    def argumentos(self, **campos) -> argparse.Namespace:
        base = {"limiares": _RAIZ / "config" / "experimento_modulos.yaml", "agora": T0 + 45 * DIA,
                "amostra": 5, "comando": "reproduzir"}
        base.update(campos)
        return argparse.Namespace(**base)

    def test_cinco_tenants_diferenca_zero(self) -> None:
        tenants = self.semear_cinco()
        # So os cinco deste ensaio na coorte de 2033: os outros saem por exclusao.
        self.cursor.execute(
            "SELECT tenant_id FROM platform.experimento_coorte(%s) WHERE NOT (tenant_id = ANY(%s::uuid[]))",
            (T0 + 45 * DIA, tenants),
        )
        for (outro,) in self.cursor.fetchall():
            self.cursor.execute(f"INSERT INTO {EXCLUSOES} (tenant_id, motivo, registado_por) VALUES (%s, 'teste', 'x')",
                                (outro,))
        self.como("kamba_batch")
        dados, codigo = em.correr(self.argumentos(), self.cursor)
        self.assertEqual(dados["amostra"], 5)
        self.assertEqual(dados["diferencas"], {"H10": [], "H11": []})
        self.assertEqual(codigo, em.SAIDA_OK)

    def test_a_reproducao_ve_uma_diferenca(self) -> None:
        """O canario: com o Python a contar a resposta ao dono, a diferenca aparece."""
        self.semear_cinco()
        self.como("kamba_batch")
        cru = em._cru(self.cursor, T0 + 45 * DIA, 1000)
        base = [l for l in em._h11_da_base(self.cursor, T0 + 45 * DIA, 30) if l.tenant_id in cru.provisionados]
        mexido = em.Cru(cru.agora, cru.provisionados, cru.valores,
                        {t: [T0] for t in cru.provisionados}, cru.atendimento)
        self.assertTrue(em.diferencas(base, em.h11_em_python(mexido, 30)))

    def test_registar_grava_um_modulo_com_a_decisao_de_quem_decide(self) -> None:
        self.semear_cinco()
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        incidentes = Path(pasta.name) / "incidentes.json"
        incidentes.write_text(json.dumps({m: {"alta": 0, "media": 0} for m in em.MODULOS}), encoding="utf-8")
        self.como("kamba_batch")
        argumentos = self.argumentos(
            comando="decidir", incidentes=incidentes, data=dt.date(2033, 7, 16), registar=True,
            modulo="social", decisao="ajustar", responsavel="Responsavel de Produto",
            justificacao="ensaio", revisao_em=dt.date(2033, 8, 1),
        )
        dados, codigo = em.correr(argumentos, self.cursor)
        self.assertEqual(codigo, em.SAIDA_OK)
        self.assertEqual(len(dados["decisoes"]), 4)
        self.cursor.execute(f"SELECT modulo, decisao, metricas->>'decisao_proposta' FROM {DECISOES} "
                            "WHERE data_decisao = '2033-07-16'")
        linhas = [tuple(l) for l in self.cursor.fetchall()]
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0][:2], ("social", "ajustar"))
        proposta = next(d["decisao"] for d in dados["decisoes"] if d["modulo"] == "social")
        self.assertEqual(linhas[0][2], proposta)
        # Sem --modulo nao regista nada.
        with self.assertRaises(em.ErroDeUso):
            em.correr(self.argumentos(
                comando="decidir", incidentes=incidentes, data=None, registar=True, modulo=None,
                decisao=None, responsavel="x", justificacao="y", revisao_em=None,
            ), self.cursor)

    def test_ler_devolve_n_de_N_e_o_intervalo(self) -> None:
        self.semear_cinco()
        self.como("kamba_batch")
        dados, codigo = em.correr(self.argumentos(comando="ler"), self.cursor)
        self.assertEqual(codigo, em.SAIDA_OK)
        for chave in ("n", "total", "proporcao", "wilson_95", "cumpre", "censurados"):
            self.assertIn(chave, dados["H10"])
        self.assertGreaterEqual(dados["H10"]["total"], 5)


class TestDowngrade(unittest.TestCase):
    """Desce para a revisao de baixo (lida do ficheiro), com uma decisao, e volta a subir.

    **Nao exige `em_head()` depois de descer**: com outra revisao por cima, o
    Alembic desce-a primeiro e a base fica na de baixo desta, que e o que se mede.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _objectos(self) -> int:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                "SELECT count(*) FROM pg_class WHERE relnamespace = 'platform'::regnamespace AND relname IN "
                "('module_decisions', 'module_experiment_exclusions', 'v_h10', 'v_h11', 'v_h12_pagantes')"
            )
            return int(c.fetchone()[0])
        finally:
            conexao.close()

    def test_desce_com_uma_decisao_e_volta_a_subir(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                f"INSERT INTO {DECISOES} (modulo, data_decisao, metricas, decisao, responsavel, justificacao) "
                "VALUES ('foto', '2033-08-24', '{}', 'manter', 'x', 'descida')"
            )
            conexao.commit()
        finally:
            conexao.close()
        self.assertEqual(self._objectos(), 5)
        alembic_ok("downgrade", _literal("down_revision"))
        self.assertEqual(self._objectos(), 0)
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT has_column_privilege('kamba_batch', 'platform.contacts', 'papel', 'SELECT')")
            self.assertFalse(c.fetchone()[0])
        finally:
            conexao.close()
        alembic_ok("upgrade", "head")
        self.assertEqual(self._objectos(), 5)


if __name__ == "__main__":
    unittest.main()
