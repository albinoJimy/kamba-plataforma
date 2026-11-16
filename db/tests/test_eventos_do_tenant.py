"""Os eventos do tenant contra a base: gates, transicoes, agregador e KPIs (KAM-092).

O que so uma base prova, e por isso este ficheiro existe:

1. **As arestas do tenant sao as oito do `docs/tecnica/00` §6.2**, medidas
   pelos 25 pares de estados contra o `transition_tenant` e contra uma lista
   escrita aqui — nao contra a funcao `tenant_transicoes()`, que e o alvo.
2. **A tabela da fase do caso** (PA-GOV-6) contra uma lista escrita aqui, par a
   par pelos 14 x 16 pares (fase, evento) do `advance_case`.
3. **O agregador**: falta exactamente uma das tres condicoes, nao ha aprovacao
   nem evento; com as tres, um `tenant.approved` que valida contra o contrato.
4. **Os seis gates**: falta exactamente um, a activacao falha e o tenant fica em
   `onboarding`; com os seis, `ativo`, o registo e um `tenant.activated` valido.
5. **Idempotencia**: a mesma transicao duas vezes da um evento.
6. **Isolamento**: o `transition_tenant` corre sob o `app.tenant_id` do proprio
   tenant, e a aplicacao nao executa nenhuma das portas nem escreve gates.
7. **O registo e append-only**, e as vistas de KPI dao a mediana e o p90.
8. **O `downgrade`** recusa-se com o registo escrito, sem exigir a cabeca.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    ComBase,
    alembic,
)
from tests.test_kyc_schema import caso as novo_caso
from tests.test_kyc_schema import verificacao
from tests.test_revisao_schema import abrir as abrir_revisao
from tests.test_revisao_schema import decidir as decidir_revisao

RAIZ = Path(__file__).resolve().parents[2]
CONTRATOS = RAIZ / "contratos" / "eventos"
PLANOS = RAIZ / "registry" / "plans.yaml"

#: `object_not_in_prerequisite_state`: o *trigger* do registo e as pre-condicoes.
PRE_CONDICAO = "55000"
SEM_DADOS = "P0002"

ESTADOS = ("onboarding", "ativo", "restrito", "suspenso", "encerrado")

#: As oito arestas do `docs/tecnica/00` §6.2, escritas a partir do diagrama e
#: nao da funcao.
ARESTAS = {
    ("onboarding", "ativo"),
    ("ativo", "restrito"),
    ("restrito", "ativo"),
    ("ativo", "suspenso"),
    ("restrito", "suspenso"),
    ("suspenso", "ativo"),
    ("ativo", "encerrado"),
    ("suspenso", "encerrado"),
}

FASES = (
    "registo", "otp_pendente", "kyc_pendente", "em_revisao", "aprovado",
    "provisionando", "aguarda_es", "lista_espera", "aguarda_catalogo",
    "aguarda_teste", "activo", "rejeitado", "abandonado", "cancelado",
)

#: A maquina dos sub-estados (PA-GOV-6), escrita aqui. `(de, evento) -> para`.
CASO = {
    ("registo", "otp_enviado"): "otp_pendente",
    ("otp_pendente", "otp_confirmado"): "kyc_pendente",
    ("kyc_pendente", "kyc_fila"): "em_revisao",
    ("em_revisao", "pedir_info"): "kyc_pendente",
    ("kyc_pendente", "aprovar"): "aprovado",
    ("em_revisao", "aprovar"): "aprovado",
    ("kyc_pendente", "rejeitar"): "rejeitado",
    ("em_revisao", "rejeitar"): "rejeitado",
    ("rejeitado", "recurso_aprovado"): "aprovado",
    ("aprovado", "saga_iniciada"): "provisionando",
    ("provisionando", "saga_concluida"): "aguarda_es",
    ("aguarda_es", "es_sem_vaga"): "lista_espera",
    ("lista_espera", "es_com_vaga"): "aguarda_es",
    ("aguarda_es", "es_concluido"): "aguarda_catalogo",
    ("aguarda_catalogo", "catalogo_minimo"): "aguarda_teste",
    ("aguarda_teste", "activar"): "activo",
}
for _fase in ("registo", "otp_pendente", "kyc_pendente", "aguarda_es",
              "lista_espera", "aguarda_catalogo", "aguarda_teste"):
    CASO[(_fase, "abandonar")] = "abandonado"
for _fase in ("registo", "otp_pendente", "kyc_pendente", "em_revisao", "aprovado",
              "aguarda_es", "lista_espera", "aguarda_catalogo", "aguarda_teste"):
    CASO[(_fase, "cancelar")] = "cancelado"
EVENTOS = tuple(sorted({evento for _, evento in CASO}))
#: Os eventos com pre-condicoes proprias, medidos em classes proprias.
COM_CONDICAO = {"aprovar", "recurso_aprovado", "es_concluido", "activar"}

GATES = ("meta_es", "meta_pagamento", "catalogo_minimo", "consentimento", "dpa", "e2e")


def _validar(tipo: str, envelope) -> None:
    if isinstance(envelope, str):
        envelope = json.loads(envelope)
    esquema = json.loads((CONTRATOS / tipo / "v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(esquema, format_checker=FormatChecker()).validate(envelope)


class ComOnboarding(ComBase):
    """Uma ligacao de administrador; as portas correm com `SET LOCAL ROLE`."""

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cur = self.conexao.cursor()

    # -- sementes -----------------------------------------------------------
    def caso(self, fase: str = "kyc_pendente") -> tuple[str, str]:
        return novo_caso(self.cur, fase=fase)

    def kyc_ok(self, caso_id: str, tenant: str) -> None:
        verificacao(self.cur, caso_id, tenant, resultado="k1_ok")

    def screening(self, caso_id: str, tenant: str, decisao: str = "permitida",
                  origem: str = "regra") -> None:
        self.cur.execute(
            "INSERT INTO platform.screening_decision (tenant_id, onboarding_id, "
            "sujeito_tipo, sujeito_ref, decisao, regras, versao_politica, origem, "
            "conteudo_sha256) VALUES (%s, %s, 'categoria', 'moda', %s, ARRAY['moda'], "
            "'1.0.0+m.2', %s, %s)",
            (tenant, caso_id, decisao, origem, uuid.uuid4().bytes * 2),
        )

    def aceite(self, tenant: str) -> None:
        factories.aceitar_contratos_vigentes(self.cur, tenant)

    def aprovavel(self, fase: str = "kyc_pendente") -> tuple[str, str]:
        caso_id, tenant = self.caso(fase)
        self.kyc_ok(caso_id, tenant)
        self.screening(caso_id, tenant)
        self.aceite(tenant)
        return caso_id, tenant

    def tenant(self, tenant: str, estado: str = "onboarding") -> None:
        factories.tenant(self.cur, id=tenant)
        if estado != "onboarding":
            self.cur.execute(
                "UPDATE platform.tenants SET estado = %s WHERE id = %s", (estado, tenant)
            )

    def gates(self, caso_id: str, tenant: str, sem: str | None = None) -> None:
        for gate in GATES:
            self.cur.execute(
                "INSERT INTO platform.onboarding_gate (onboarding_id, tenant_id, gate, ok, "
                "evidencia_ref) VALUES (%s, %s, %s, %s, 'ensaio')",
                (caso_id, tenant, gate, gate != sem),
            )

    def activavel(self, sem_gate: str | None = None) -> tuple[str, str]:
        """Um caso em `aguarda_teste` **pelas portas**: a sequencia inteira.

        Aprovado pelo agregador (`tenant.approved`), a saga falsa (os dois
        eventos dela, sem recursos), o tenant que o passo 1 escreveria, um canal
        e o `es_concluido` (`tenant.provisioned`), o catalogo minimo e os gates.
        """
        caso_id, tenant = self.aprovavel()
        for evento in ("aprovar", "saga_iniciada", "saga_concluida"):
            self.avancar(caso_id, tenant, evento)
        self.tenant(tenant)
        factories.canal(self.cur, tenant)
        for evento in ("es_concluido", "catalogo_minimo"):
            self.avancar(caso_id, tenant, evento)
        self.gates(caso_id, tenant, sem=sem_gate)
        return caso_id, tenant

    def revisao(self, caso_id: str, tenant: str, tipo: str, decisao: str | None,
                motivo: str = "ensaio") -> None:
        linha = abrir_revisao(self.cur, tenant, caso_id, tipo=tipo, motivo_codigo=motivo)
        if decisao is not None:
            decidir_revisao(self.cur, linha[0], decisao)

    # -- portas -------------------------------------------------------------
    def como(self, papel: str, contexto: str | None) -> None:
        self.cur.execute(f"SET LOCAL ROLE {papel}")
        factories.contexto(self.cur, contexto)

    def largar(self) -> None:
        self.cur.execute("RESET ROLE")

    def avancar(self, caso_id: str, tenant: str, evento: str) -> str:
        self.como("kamba_batch", tenant)
        try:
            self.cur.execute(
                "SELECT platform.advance_case(%s, %s, 'ensaio')", (caso_id, evento)
            )
            return self.cur.fetchone()[0]
        finally:
            self.largar()

    def transitar(self, tenant: str, para: str) -> bool:
        self.como("kamba_batch", tenant)
        try:
            self.cur.execute(
                "SELECT platform.transition_tenant(%s, %s, 'ensaio', 'ensaio')",
                (tenant, para),
            )
            return self.cur.fetchone()[0]
        finally:
            self.largar()

    def recusa(self, esperado: str, sql: str, parametros: tuple, papel: str = "kamba_batch",
               contexto: str | None = None) -> None:
        self.como(papel, contexto)
        try:
            self.assertErroSql(esperado, self.cur, sql, parametros)
        finally:
            self.largar()

    def eventos(self, tenant: str, tipo: str) -> list:
        self.cur.execute(
            "SELECT envelope FROM platform.events_outbox WHERE tenant_id = %s AND tipo = %s "
            "ORDER BY agregado_seq",
            (tenant, tipo),
        )
        return [linha[0] for linha in self.cur.fetchall()]

    def fase(self, caso_id: str) -> str:
        self.cur.execute("SELECT fase FROM platform.onboarding_case WHERE id = %s", (caso_id,))
        return self.cur.fetchone()[0]

    def estado(self, tenant: str) -> str:
        self.cur.execute("SELECT estado FROM platform.tenants WHERE id = %s", (tenant,))
        return self.cur.fetchone()[0]


class TestTabelas(ComOnboarding):
    def test_o_dominio_dos_gates_e_o_do_criterio(self) -> None:
        self.cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'onboarding_gate_gate_ck'"
        )
        self.assertEqual(
            tuple(sorted(re.findall(r"'([a-z0-9_]+)'", self.cur.fetchone()[0]))),
            tuple(sorted(GATES)),
        )

    def test_as_arestas_da_funcao_sao_as_do_diagrama(self) -> None:
        self.cur.execute("SELECT de, para FROM platform.tenant_transicoes()")
        self.assertEqual({tuple(l) for l in self.cur.fetchall()}, ARESTAS)

    def test_a_tabela_do_caso_e_a_proposta(self) -> None:
        self.cur.execute("SELECT de, evento, para FROM platform.onboarding_transicoes()")
        self.assertEqual({(d, e): p for d, e, p in self.cur.fetchall()}, CASO)

    def test_um_destino_por_evento(self) -> None:
        destinos: dict[str, set[str]] = {}
        for (_, evento), para in CASO.items():
            destinos.setdefault(evento, set()).add(para)
        self.assertTrue(all(len(v) == 1 for v in destinos.values()), destinos)

    def test_o_gate_de_um_caso_nao_junta_o_tenant_de_outro(self) -> None:
        caso_a, _ = self.caso()
        _, tenant_b = self.caso()
        self.assertErroSql(
            "23503", self.cur,
            "INSERT INTO platform.onboarding_gate (onboarding_id, tenant_id, gate, ok) "
            "VALUES (%s, %s, 'dpa', true)",
            (caso_a, tenant_b),
        )

    def test_o_em_do_gate_e_da_base(self) -> None:
        caso_id, tenant = self.caso()
        self.cur.execute(
            "INSERT INTO platform.onboarding_gate (onboarding_id, tenant_id, gate, ok, em) "
            "VALUES (%s, %s, 'dpa', true, '2000-01-01') RETURNING em > now() - interval '1 hour'",
            (caso_id, tenant),
        )
        self.assertTrue(self.cur.fetchone()[0])


class TestTransicoesDoTenant(ComOnboarding):
    def test_os_vinte_e_cinco_pares(self) -> None:
        for de in ESTADOS:
            for para in ESTADOS:
                with self.subTest(de=de, para=para):
                    self.cur.execute("SAVEPOINT par")
                    if de == "onboarding":
                        _, tenant = self.activavel()
                    else:
                        tenant = str(uuid.uuid4())
                        self.aceite(tenant)
                        self.tenant(tenant, estado=de)
                    if de == para:
                        self.assertFalse(self.transitar(tenant, para))
                        self.assertEqual(self.estado(tenant), de)
                    elif (de, para) in ARESTAS:
                        self.assertTrue(self.transitar(tenant, para))
                        self.assertEqual(self.estado(tenant), para)
                        self.cur.execute(
                            "SELECT de, para FROM platform.tenant_state_log WHERE tenant_id = %s",
                            (tenant,),
                        )
                        self.assertEqual([list(l) for l in self.cur.fetchall()], [[de, para]])
                    else:
                        self.recusa(
                            VIOLACAO_DE_CHECK,
                            "SELECT platform.transition_tenant(%s, %s, 'x', 'x')",
                            (tenant, para), contexto=tenant,
                        )
                        self.assertEqual(self.estado(tenant), de)
                    self.cur.execute("ROLLBACK TO SAVEPOINT par")

    def test_so_a_activacao_emite(self) -> None:
        tenant = str(uuid.uuid4())
        self.aceite(tenant)
        self.tenant(tenant, estado="ativo")
        self.transitar(tenant, "suspenso")
        self.transitar(tenant, "ativo")
        self.cur.execute(
            "SELECT count(*) FROM platform.events_outbox WHERE tenant_id = %s", (tenant,)
        )
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_tenant_inexistente(self) -> None:
        tenant = str(uuid.uuid4())
        self.recusa(
            SEM_DADOS, "SELECT platform.transition_tenant(%s, 'ativo', 'x', 'x')",
            (tenant,), contexto=tenant,
        )


class TestIsolamento(ComOnboarding):
    def test_sem_contexto_e_recusado(self) -> None:
        _, tenant = self.activavel()
        self.recusa(
            PRIVILEGIO_INSUFICIENTE,
            "SELECT platform.transition_tenant(%s, 'ativo', 'x', 'x')", (tenant,),
        )

    def test_o_tenant_a_nao_transita_o_b(self) -> None:
        _, tenant_a = self.activavel()
        caso_b, tenant_b = self.activavel()
        self.recusa(
            PRIVILEGIO_INSUFICIENTE,
            "SELECT platform.transition_tenant(%s, 'ativo', 'x', 'x')", (tenant_b,),
            contexto=tenant_a,
        )
        self.recusa(
            PRIVILEGIO_INSUFICIENTE,
            "SELECT platform.advance_case(%s, 'activar', 'x')", (caso_b,),
            contexto=tenant_a,
        )
        self.assertEqual(self.estado(tenant_b), "onboarding")

    def test_a_aplicacao_nao_executa_as_portas_nem_escreve_gates(self) -> None:
        caso_id, tenant = self.activavel()
        for sql, parametros in (
            ("SELECT platform.transition_tenant(%s, 'ativo', 'x', 'x')", (tenant,)),
            ("SELECT platform.advance_case(%s, 'activar', 'x')", (caso_id,)),
            ("SELECT platform.aprovacao_em_falta(%s)", (caso_id,)),
            ("UPDATE platform.onboarding_gate SET ok = true WHERE onboarding_id = %s", (caso_id,)),
            ("INSERT INTO platform.onboarding_gate (onboarding_id, tenant_id, gate, ok) "
             "VALUES (%s, %s, 'e2e', true)", (caso_id, tenant)),
        ):
            with self.subTest(sql=sql):
                self.recusa(PRIVILEGIO_INSUFICIENTE, sql, parametros,
                            papel="kamba_app", contexto=tenant)

    def test_a_aplicacao_le_os_gates_do_seu_tenant_e_nao_os_de_outro(self) -> None:
        caso_a, tenant_a = self.activavel(sem_gate="e2e")
        caso_b, _ = self.activavel()
        self.como("kamba_app", tenant_a)
        try:
            self.cur.execute("SELECT count(*) FROM platform.onboarding_gate")
            self.assertEqual(self.cur.fetchone()[0], 6)
            self.cur.execute("SELECT platform.onboarding_gates_em_falta(%s)", (caso_a,))
            self.assertEqual(self.cur.fetchone()[0], ["e2e"])
            self.cur.execute("SELECT platform.onboarding_gates_em_falta(%s)", (caso_b,))
            self.assertEqual(self.cur.fetchone()[0], list(GATES))
        finally:
            self.largar()


class TestRegisto(ComOnboarding):
    def test_append_only_ate_ao_dono(self) -> None:
        tenant = str(uuid.uuid4())
        self.aceite(tenant)
        self.tenant(tenant, estado="ativo")
        self.transitar(tenant, "restrito")
        for sql in ("UPDATE platform.tenant_state_log SET motivo = 'x' WHERE tenant_id = %s",
                    "DELETE FROM platform.tenant_state_log WHERE tenant_id = %s"):
            with self.subTest(sql=sql):
                self.assertErroSql(PRE_CONDICAO, self.cur, sql, (tenant,))
                self.recusa(PRIVILEGIO_INSUFICIENTE, sql, (tenant,), contexto=tenant)


    def test_a_auditoria_le_o_registo_do_seu_tenant_e_nao_o_de_outro(self) -> None:
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        for tenant in (tenant_a, tenant_b):
            self.aceite(tenant)
            self.tenant(tenant, estado="ativo")
            self.transitar(tenant, "restrito")
        for contexto, esperado in ((tenant_a, 1), (tenant_b, 0), (None, 0)):
            with self.subTest(contexto=contexto):
                self.como("kamba_audit", contexto)
                try:
                    self.cur.execute(
                        "SELECT count(*) FROM platform.tenant_state_log WHERE tenant_id = %s",
                        (tenant_a,),
                    )
                    visto = self.cur.fetchone()[0]
                finally:
                    self.largar()
                self.assertEqual(visto, esperado)

    def test_a_aplicacao_nao_le_o_registo(self) -> None:
        self.recusa(PRIVILEGIO_INSUFICIENTE, "SELECT count(*) FROM platform.tenant_state_log",
                    (), papel="kamba_app", contexto=str(uuid.uuid4()))


class TestAgregador(ComOnboarding):
    def _sem(self, condicao: str) -> tuple[str, str]:
        caso_id, tenant = self.caso("kyc_pendente")
        if condicao != "kyc":
            self.kyc_ok(caso_id, tenant)
        if condicao != "screening":
            self.screening(caso_id, tenant)
        if condicao != "aceite":
            self.aceite(tenant)
        return caso_id, tenant

    def test_falta_exactamente_uma_condicao_nao_aprova(self) -> None:
        for condicao in ("kyc", "screening", "aceite"):
            with self.subTest(condicao=condicao):
                caso_id, tenant = self._sem(condicao)
                self.como("kamba_batch", tenant)
                try:
                    self.cur.execute("SELECT platform.aprovacao_em_falta(%s)", (caso_id,))
                    self.assertEqual(self.cur.fetchone()[0], [condicao])
                    self.assertErroSql(
                        VIOLACAO_DE_CHECK, self.cur,
                        "SELECT platform.advance_case(%s, 'aprovar', 'x')", (caso_id,),
                    )
                finally:
                    self.largar()
                self.assertEqual(self.fase(caso_id), "kyc_pendente")
                self.assertEqual(self.eventos(tenant, "tenant.approved"), [])

    def test_com_as_tres_aprova_e_emite_um_evento_valido(self) -> None:
        caso_id, tenant = self.aprovavel()
        self.assertEqual(self.avancar(caso_id, tenant, "aprovar"), "aprovado")
        eventos = self.eventos(tenant, "tenant.approved")
        self.assertEqual(len(eventos), 1)
        _validar("tenant.approved", eventos[0])
        payload = eventos[0]["payload"]
        self.assertEqual(payload["onboarding_id"], caso_id)
        self.assertEqual(payload["kyc_nivel"], "K1")
        self.assertEqual(payload["currency"], "AOA")
        self.assertIs(payload["intervencao_humana"], False)
        self.assertEqual(eventos[0]["agregado"]["tipo"], "tenant")
        self.assertEqual(eventos[0]["agregado"]["id"], tenant)

    def test_a_kyc_mais_recente_e_que_conta(self) -> None:
        caso_id, tenant = self.aprovavel()
        depois = datetime.now(timezone.utc) + timedelta(hours=1)
        verificacao(self.cur, caso_id, tenant, resultado="fila", criado_at=depois)
        self.cur.execute("SELECT platform.aprovacao_em_falta(%s)", (caso_id,))
        self.assertEqual(self.cur.fetchone()[0], ["kyc"])

    def test_no_empate_basta_uma_que_nao_seja_k1_ok(self) -> None:
        caso_id, tenant = self.aprovavel()
        verificacao(self.cur, caso_id, tenant, resultado="pendente")
        self.cur.execute("SELECT platform.aprovacao_em_falta(%s)", (caso_id,))
        self.assertEqual(self.cur.fetchone()[0], ["kyc"])

    def test_a_decisao_humana_aprovar_substitui_o_k1_ok(self) -> None:
        caso_id, tenant = self.caso("em_revisao")
        verificacao(self.cur, caso_id, tenant, resultado="fila")
        self.screening(caso_id, tenant)
        self.aceite(tenant)
        self.revisao(caso_id, tenant, "kyc", "aprovar")
        self.assertEqual(self.avancar(caso_id, tenant, "aprovar"), "aprovado")
        eventos = self.eventos(tenant, "tenant.approved")
        self.assertEqual(len(eventos), 1)
        self.assertIs(eventos[0]["payload"]["intervencao_humana"], True)

    def test_uma_decisao_humana_rejeitar_nao_aprova(self) -> None:
        caso_id, tenant = self.caso("em_revisao")
        verificacao(self.cur, caso_id, tenant, resultado="fila")
        self.screening(caso_id, tenant)
        self.aceite(tenant)
        self.revisao(caso_id, tenant, "kyc", "rejeitar")
        self.cur.execute("SELECT platform.aprovacao_em_falta(%s)", (caso_id,))
        self.assertEqual(self.cur.fetchone()[0], ["kyc"])

    def test_um_caso_kyc_aprovado_e_outro_por_decidir_ou_rejeitado_nao_aprova(self) -> None:
        for segunda in (None, "rejeitar", "aprovar"):
            with self.subTest(segunda=segunda):
                caso_id, tenant = self.caso("em_revisao")
                verificacao(self.cur, caso_id, tenant, resultado="fila")
                self.screening(caso_id, tenant)
                self.aceite(tenant)
                self.revisao(caso_id, tenant, "kyc", "aprovar", motivo="nif_divergente")
                self.revisao(caso_id, tenant, "kyc", segunda, motivo="imagem_reutilizada")
                self.cur.execute("SELECT platform.aprovacao_em_falta(%s)", (caso_id,))
                self.assertEqual(self.cur.fetchone()[0], [] if segunda == "aprovar" else ["kyc"])

    def test_screening_o_mais_restritivo_e_so_a_fila_levanta_a_bloqueada(self) -> None:
        """Condicional passa; bloqueada nao; a linha que a aplicacao escreve nao levanta nada.

        A `origem` de uma linha da `screening_decision` e escrita por quem a
        insere, e o `kamba_app` insere: uma `permitida` ou um `humano` depois de
        uma `bloqueada` nao a tapam. So o recurso de `categoria` na fila.
        """
        for decisoes, recurso, falta in (
            ((), None, ["screening"]),
            ((("condicional", "regra"),), None, []),
            ((("bloqueada", "regra"),), None, ["screening"]),
            ((("bloqueada", "regra"), ("permitida", "humano")), None, ["screening"]),
            ((("permitida", "regra"), ("bloqueada", "humano")), None, ["screening"]),
            ((("bloqueada", "regra"),), "rejeitar", ["screening"]),
            ((("bloqueada", "regra"),), "aprovar", []),
        ):
            with self.subTest(decisoes=decisoes, recurso=recurso):
                caso_id, tenant = self.caso("kyc_pendente")
                self.kyc_ok(caso_id, tenant)
                self.aceite(tenant)
                for decisao, origem in decisoes:
                    self.screening(caso_id, tenant, decisao, origem)
                if recurso is not None:
                    self.revisao(caso_id, tenant, "categoria", recurso)
                self.cur.execute("SELECT platform.aprovacao_em_falta(%s)", (caso_id,))
                self.assertEqual(self.cur.fetchone()[0], falta)

    def test_a_amostragem_nao_conta_na_aprovacao(self) -> None:
        caso_id, tenant = self.aprovavel()
        self.revisao(caso_id, tenant, "auditoria", None, motivo="amostra")
        self.avancar(caso_id, tenant, "aprovar")
        payload = self.eventos(tenant, "tenant.approved")[0]["payload"]
        self.assertIs(payload["intervencao_humana"], False)

    def test_o_avanco_de_outro_tenant_e_recusado(self) -> None:
        caso_b, _ = self.aprovavel()
        for evento in ("aprovar", "cancelar", "otp_enviado"):
            with self.subTest(evento=evento):
                self.recusa(PRIVILEGIO_INSUFICIENTE,
                            "SELECT platform.advance_case(%s, %s, 'x')", (caso_b, evento),
                            contexto=str(uuid.uuid4()))
        self.assertEqual(self.fase(caso_b), "kyc_pendente")

    def test_os_valores_fixos_sao_os_do_registo_de_planos(self) -> None:
        """O plano, a vertical e o tecto confrontados com o `registry/plans.yaml`.

        Lido pelo leitor de YAML do repositorio, e nao por expressao regular: o
        tecto e o do plano `free` e do modulo activo dele, e nao o primeiro
        `valor_max_pedido_minor` do ficheiro.
        """
        sys.path.insert(0, str(RAIZ / "tools"))
        from kamba_yaml import load_file  # noqa: PLC0415

        free = load_file(PLANOS)["plans"]["free"]
        activos = [e for e in free["entitlements"] if e.get("ativo")]
        self.assertEqual([e["modulo"] for e in activos], ["vendedor"])
        caso_id, tenant = self.aprovavel()
        self.avancar(caso_id, tenant, "aprovar")
        payload = self.eventos(tenant, "tenant.approved")[0]["payload"]
        self.assertEqual(
            (payload["plano"], payload["vertical"], payload["tecto_inicial_minor"]),
            ("free", activos[0]["modulo"], activos[0]["limites"]["valor_max_pedido_minor"]),
        )


class TestMaquinaDoCaso(ComOnboarding):
    def test_os_pares_sem_pre_condicao(self) -> None:
        for fase in FASES:
            for evento in EVENTOS:
                if evento in COM_CONDICAO:
                    continue
                with self.subTest(fase=fase, evento=evento):
                    self.cur.execute("SAVEPOINT par")
                    caso_id, tenant = self.caso(fase)
                    destino = CASO.get((fase, evento))
                    repeticao = destino is None and fase in {
                        p for (_, e), p in CASO.items() if e == evento
                    }
                    if destino is not None:
                        self.assertEqual(self.avancar(caso_id, tenant, evento), destino)
                        self.assertEqual(self.fase(caso_id), destino)
                    elif repeticao:
                        self.assertEqual(self.avancar(caso_id, tenant, evento), fase)
                    else:
                        self.recusa(
                            VIOLACAO_DE_CHECK,
                            "SELECT platform.advance_case(%s, %s, 'x')",
                            (caso_id, evento), contexto=tenant,
                        )
                        self.assertEqual(self.fase(caso_id), fase)
                    self.cur.execute("ROLLBACK TO SAVEPOINT par")

    def test_os_eventos_com_pre_condicao_fora_da_fase_sao_recusados(self) -> None:
        for evento in sorted(COM_CONDICAO):
            origens = {d for (d, e) in CASO if e == evento}
            destino = CASO[next((d, e) for (d, e) in CASO if e == evento)]
            for fase in FASES:
                if fase in origens or fase == destino:
                    continue
                with self.subTest(fase=fase, evento=evento):
                    caso_id, tenant = self.caso(fase)
                    self.recusa(
                        VIOLACAO_DE_CHECK,
                        "SELECT platform.advance_case(%s, %s, 'x')",
                        (caso_id, evento), contexto=tenant,
                    )

    def test_o_recurso_aprovado_passa_pelo_agregador(self) -> None:
        caso_id, tenant = self.aprovavel("rejeitado")
        self.assertEqual(self.avancar(caso_id, tenant, "recurso_aprovado"), "aprovado")
        self.assertEqual(len(self.eventos(tenant, "tenant.approved")), 1)

    def test_caso_inexistente(self) -> None:
        caso_id = str(uuid.uuid4())
        self.recusa(SEM_DADOS, "SELECT platform.advance_case(%s, 'aprovar', 'x')",
                    (caso_id,), contexto=caso_id)


class TestProvisionamento(ComOnboarding):
    def test_sem_canal_nao_provisiona(self) -> None:
        caso_id, tenant = self.caso("aguarda_es")
        self.tenant(tenant)
        self.recusa(PRE_CONDICAO, "SELECT platform.advance_case(%s, 'es_concluido', 'x')",
                    (caso_id,), contexto=tenant)
        self.assertEqual(self.eventos(tenant, "tenant.provisioned"), [])

    def test_com_dois_canais_nao_escolhe(self) -> None:
        caso_id, tenant = self.caso("aguarda_es")
        self.tenant(tenant)
        factories.canal(self.cur, tenant)
        factories.canal(self.cur, tenant)
        self.recusa(PRE_CONDICAO, "SELECT platform.advance_case(%s, 'es_concluido', 'x')",
                    (caso_id,), contexto=tenant)

    def test_um_canal_desligado_de_outra_tentativa_nao_conta(self) -> None:
        caso_id, tenant = self.caso("aguarda_es")
        self.tenant(tenant)
        factories.canal(self.cur, tenant, estado="desligado")
        vivo = factories.canal(self.cur, tenant)
        self.assertEqual(self.avancar(caso_id, tenant, "es_concluido"), "aguarda_catalogo")
        self.assertEqual(self.eventos(tenant, "tenant.provisioned")[0]["payload"]["channel_id"],
                         vivo)

    def test_uma_fase_escrita_por_fora_nao_e_repeticao(self) -> None:
        """`aprovado` posto por `UPDATE` directo: o `aprovar` nao finge que ja emitiu."""
        caso_id, tenant = self.aprovavel("aprovado")
        self.recusa(PRE_CONDICAO, "SELECT platform.advance_case(%s, 'aprovar', 'x')",
                    (caso_id,), contexto=tenant)
        self.assertEqual(self.eventos(tenant, "tenant.approved"), [])

    def test_com_canal_emite_o_canal(self) -> None:
        caso_id, tenant = self.caso("aguarda_es")
        self.tenant(tenant)
        canal = factories.canal(self.cur, tenant, channel_mode="cloud_only")
        self.assertEqual(self.avancar(caso_id, tenant, "es_concluido"), "aguarda_catalogo")
        self.assertEqual(self.avancar(caso_id, tenant, "es_concluido"), "aguarda_catalogo")
        eventos = self.eventos(tenant, "tenant.provisioned")
        self.assertEqual(len(eventos), 1)
        _validar("tenant.provisioned", eventos[0])
        self.assertEqual(eventos[0]["payload"]["channel_id"], canal)
        self.assertEqual(eventos[0]["payload"]["channel_mode"], "cloud_only")
        self.assertEqual(eventos[0]["payload"]["vertical"], "vendedor")


class TestActivacao(ComOnboarding):
    def test_falta_exactamente_um_gate_nao_activa(self) -> None:
        for gate in GATES:
            with self.subTest(gate=gate):
                caso_id, tenant = self.activavel(sem_gate=gate)
                self.como("kamba_batch", tenant)
                try:
                    self.assertErroSql(
                        VIOLACAO_DE_CHECK, self.cur,
                        "SELECT platform.advance_case(%s, 'activar', 'x')", (caso_id,),
                    )
                    self.assertErroSql(
                        VIOLACAO_DE_CHECK, self.cur,
                        "SELECT platform.transition_tenant(%s, 'ativo', 'x', 'x')", (tenant,),
                    )
                finally:
                    self.largar()
                self.assertEqual(self.estado(tenant), "onboarding")
                self.assertEqual(self.fase(caso_id), "aguarda_teste")
                self.assertEqual(self.eventos(tenant, "tenant.activated"), [])

    def test_gate_ausente_conta_como_vermelho(self) -> None:
        caso_id, tenant = self.caso("aguarda_teste")
        self.aceite(tenant)
        self.tenant(tenant)
        self.recusa(VIOLACAO_DE_CHECK, "SELECT platform.advance_case(%s, 'activar', 'x')",
                    (caso_id,), contexto=tenant)

    def test_com_os_seis_activa_regista_e_emite_um_evento_valido(self) -> None:
        caso_id, tenant = self.activavel()
        self.cur.execute(
            "UPDATE platform.onboarding_case SET owner_active_seconds = 2700 WHERE id = %s",
            (caso_id,),
        )
        self.assertEqual(self.avancar(caso_id, tenant, "activar"), "activo")
        self.assertEqual(self.avancar(caso_id, tenant, "activar"), "activo")
        self.assertFalse(self.transitar(tenant, "ativo"))
        self.assertEqual(self.estado(tenant), "ativo")
        self.assertEqual(self.fase(caso_id), "activo")
        self.cur.execute(
            "SELECT de, para, actor FROM platform.tenant_state_log WHERE tenant_id = %s",
            (tenant,),
        )
        self.assertEqual([list(l) for l in self.cur.fetchall()], [["onboarding", "ativo", "ensaio"]])
        eventos = self.eventos(tenant, "tenant.activated")
        self.assertEqual(len(eventos), 1)
        _validar("tenant.activated", eventos[0])
        self.assertEqual(
            eventos[0]["payload"],
            {"onboarding_id": caso_id, "plano": "free", "owner_active_seconds": 2700,
             "intervencao_humana": False},
        )

    def test_a_amostragem_nao_conta_como_intervencao(self) -> None:
        caso_id, tenant = self.activavel()
        self.revisao(caso_id, tenant, "auditoria", None, motivo="amostra")
        self.transitar(tenant, "ativo")
        self.assertIs(self.eventos(tenant, "tenant.activated")[0]["payload"]["intervencao_humana"],
                      False)
        self.cur.execute(
            "SELECT intervencao_humana FROM platform.v_onboarding_kpis WHERE onboarding_id = %s",
            (caso_id,),
        )
        self.assertIs(self.cur.fetchone()[0], False)

    def test_a_activacao_pede_o_caso_em_aguarda_teste(self) -> None:
        caso_id, tenant = self.caso("aguarda_catalogo")
        self.aceite(tenant)
        self.tenant(tenant)
        self.gates(caso_id, tenant)
        self.recusa(PRE_CONDICAO, "SELECT platform.transition_tenant(%s, 'ativo', 'x', 'x')",
                    (tenant,), contexto=tenant)

    def test_a_fase_posta_a_mao_nao_activa(self) -> None:
        """A `fase` e escrevivel pelo `kamba_app`; `aguarda_teste` nao prova o caminho."""
        for com_agregador in (False, True):
            with self.subTest(com_agregador=com_agregador):
                caso_id, tenant = (self.aprovavel("aguarda_teste") if com_agregador
                                   else self.caso("aguarda_teste"))
                self.aceite(tenant)
                self.tenant(tenant)
                self.gates(caso_id, tenant)
                self.recusa(VIOLACAO_DE_CHECK,
                            "SELECT platform.advance_case(%s, 'activar', 'x')",
                            (caso_id,), contexto=tenant)
                self.assertEqual(self.estado(tenant), "onboarding")

    def test_o_aceite_volta_a_contar_na_activacao(self) -> None:
        """Uma versao nova do DPA publicada depois da aprovacao trava a activacao."""
        caso_id, tenant = self.activavel()
        conteudo = "DPA de ensaio, versao nova. [A CONFIRMAR POR PARECER]\n"
        self.cur.execute(
            "INSERT INTO platform.contract_document (tipo, versao, sha256, conteudo, "
            "vigente_desde) VALUES ('dpa', '9.9.9', sha256(convert_to(%s, 'UTF8')), %s, now())",
            (conteudo, conteudo),
        )
        self.cur.execute("SELECT platform.aprovacao_em_falta(%s)", (caso_id,))
        self.assertEqual(self.cur.fetchone()[0], ["aceite"])
        self.recusa(VIOLACAO_DE_CHECK, "SELECT platform.advance_case(%s, 'activar', 'x')",
                    (caso_id,), contexto=tenant)
        self.assertEqual(self.estado(tenant), "onboarding")

    def test_activar_nao_levanta_uma_suspensao(self) -> None:
        caso_id, tenant = self.activavel()
        self.cur.execute("UPDATE platform.tenants SET estado = 'suspenso' WHERE id = %s",
                         (tenant,))
        self.recusa(PRE_CONDICAO, "SELECT platform.advance_case(%s, 'activar', 'x')",
                    (caso_id,), contexto=tenant)
        self.assertEqual(self.estado(tenant), "suspenso")

    def test_a_sequencia_completa_emite_os_tres_por_ordem(self) -> None:
        caso_id, tenant = self.activavel()
        self.avancar(caso_id, tenant, "activar")
        self.cur.execute(
            "SELECT tipo, agregado_seq FROM platform.events_outbox "
            "WHERE tenant_id = %s AND agregado_tipo = 'tenant' ORDER BY agregado_seq",
            (tenant,),
        )
        self.assertEqual(
            [tuple(l) for l in self.cur.fetchall()],
            [("tenant.approved", 1), ("tenant.provisioned", 2), ("tenant.activated", 3)],
        )
        for tipo in ("tenant.approved", "tenant.provisioned", "tenant.activated"):
            _validar(tipo, self.eventos(tenant, tipo)[0])


class TestIdempotencia(ComOnboarding):
    def test_aprovar_duas_vezes_da_um_evento(self) -> None:
        caso_id, tenant = self.aprovavel()
        self.assertEqual(self.avancar(caso_id, tenant, "aprovar"), "aprovado")
        self.assertEqual(self.avancar(caso_id, tenant, "aprovar"), "aprovado")
        self.assertEqual(len(self.eventos(tenant, "tenant.approved")), 1)

    def test_activar_duas_vezes_da_um_evento(self) -> None:
        _, tenant = self.activavel()
        self.assertTrue(self.transitar(tenant, "ativo"))
        self.assertFalse(self.transitar(tenant, "ativo"))
        self.assertEqual(len(self.eventos(tenant, "tenant.activated")), 1)


class TestKpis(ComOnboarding):
    def _activo(self, segundos: int, dias: int, humano: bool, tentativas: int) -> str:
        caso_id, tenant = self.activavel()
        self.cur.execute(
            "UPDATE platform.onboarding_case SET owner_active_seconds = %s, "
            "criado_at = now() - make_interval(days => %s) WHERE id = %s",
            (segundos, dias, caso_id),
        )
        if humano:
            self.revisao(caso_id, tenant, "kyc", None)
        self.cur.execute(
            "INSERT INTO platform.provisioning_step (onboarding_id, tenant_id, step, status, "
            "attempt) VALUES (%s, %s, 'tenant_e_caso', 'concluido', %s)",
            (caso_id, tenant, tentativas),
        )
        self.transitar(tenant, "ativo")
        return caso_id

    def test_por_caso_e_agregado(self) -> None:
        # A base e partilhada pela suite: o que outro ensaio tenha confirmado sai
        # da vista nesta transaccao (desfeita no fim), e o oraculo e exacto.
        self.cur.execute("DELETE FROM platform.provisioning_step")
        self.cur.execute(
            "UPDATE platform.onboarding_case SET fase = 'cancelado' WHERE fase = 'activo'"
        )
        um = self._activo(1000, 1, False, 1)
        self._activo(3000, 3, True, 2)
        self._activo(2000, 2, False, 1)
        self.cur.execute(
            "SELECT owner_active_seconds, round(dias_calendario), intervencao_humana, "
            "saga_primeira_tentativa FROM platform.v_onboarding_kpis WHERE onboarding_id = %s",
            (um,),
        )
        self.assertEqual(self.cur.fetchone(), [1000, 1, False, True])
        self.cur.execute(
            "SELECT casos_activos, owner_active_seconds_mediana, owner_active_seconds_p90, "
            "round(dias_calendario_mediana::numeric, 3), round(sem_intervencao_ratio, 3), "
            "round(saga_primeira_tentativa_ratio, 3) "
            "FROM platform.v_onboarding_kpis_agregado"
        )
        casos, mediana, p90, dias, sem, saga = self.cur.fetchone()
        self.assertEqual(casos, 3)
        self.assertEqual((mediana, p90), (2000.0, 2800.0))
        self.assertEqual(float(dias), 2.0)
        self.assertEqual(float(sem), round(2 / 3, 3))
        self.assertEqual(float(saga), round(2 / 3, 3))

    def test_as_vistas_sao_security_invoker(self) -> None:
        self.cur.execute(
            "SELECT relname, reloptions FROM pg_class WHERE relname IN "
            "('v_onboarding_kpis', 'v_onboarding_kpis_agregado') ORDER BY relname"
        )
        for nome, opcoes in self.cur.fetchall():
            self.assertIn("security_invoker=true", opcoes, nome)


class TestReversivel(ComOnboarding):
    def test_o_downgrade_recusa_com_registo_escrito(self) -> None:
        """Nao exige estar na cabeca (licao do KAM-197): so mede a recusa."""
        revisao = next(
            (RAIZ / "db" / "migrations" / "versions").glob("*_eventos_do_tenant.py")
        )
        anterior = re.search(
            r'(?m)^down_revision = "([^"]+)"', revisao.read_text(encoding="utf-8")
        ).group(1)
        tenant = str(uuid.uuid4())
        self.aceite(tenant)
        self.tenant(tenant, estado="ativo")
        self.transitar(tenant, "restrito")
        self.conexao.commit()
        try:
            resultado = alembic("downgrade", anterior)
            self.assertNotEqual(resultado.returncode, 0)
            self.assertIn("downgrade da 0057 recusado", resultado.stderr + resultado.stdout)
        finally:
            # O registo e imutavel tambem para o dono: a limpeza desliga o
            # *trigger*, apaga a linha e o tenant, e volta a liga-lo.
            self.cur.execute("ALTER TABLE platform.tenant_state_log DISABLE TRIGGER USER")
            self.cur.execute("DELETE FROM platform.tenant_state_log WHERE tenant_id = %s",
                             (tenant,))
            self.cur.execute("ALTER TABLE platform.tenant_state_log ENABLE ALWAYS TRIGGER "
                             "tenant_state_log_imutavel")
            self.cur.execute("DELETE FROM platform.tenants WHERE id = %s", (tenant,))
            self.conexao.commit()


if __name__ == "__main__":
    unittest.main()
