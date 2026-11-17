"""A revisao do off-boarding e o lado dos dados contra a base (KAM-098).

O que so aqui se prova:

* **o esquema morde**: a chave `(tenant_id, fase)`, os dominios, a RLS `FORCE`,
  o `UPDATE` so do `estado` e do `resultado`, e o `kamba_app` sem nada;
* **a exportacao** corre com o papel da aplicacao e o contexto do tenant, nao
  traz nada de outro tenant (o ensaio cruzado do bloco), sai de um tenant
  `suspenso` (o criterio 7 do KAM-058) e audita cada geracao;
* **a purga** apaga pelos caminhos medidos e escreve o `purge_log` na mesma
  transaccao, deixa o que nao tem caminho como `recusada`, para numa disputa,
  nao apaga nada de um pedido cancelado, retoma depois de uma falha a meio, e
  volta a apagar depois de um restauro;
* **o certificado** le o `purge_log` da execucao, nao afirma o apagamento das
  copias, e a assinatura nao sobrevive a uma alteracao.

As fases do lado TypeScript (o pedido, os pendentes, o canal, a revogacao)
semeiam-se aqui como o administrador, com a forma que o `encerramento.ts`
escreve; correm de verdade no `packages/core-ts/tests_bd/offboarding.bd.test.ts`.

**Nada fica na base.** Cada unidade do lado dos dados corre na transaccao do
ensaio (a `LigacaoDeEnsaio` do KAM-071: `SAVEPOINT` e `SET ROLE` por unidade), e
o `tearDown` reverte tudo — incluindo as linhas *append-only* do `audit_log` e do
`purge_log`. Nenhum ensaio daqui transita o tenant, pelo que o
`tenant_state_log` fica intacto.

Nada aqui e um dado real.
"""

from __future__ import annotations

import io
import json
import re
import sys
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_NUCLEO = str(_RAIZ / "libs" / "py-core" / "src")
if _NUCLEO not in sys.path:
    sys.path.insert(0, _NUCLEO)

from kamba_core.offboarding import (  # noqa: E402
    CAMINHOS_DO_ENCERRAMENTO,
    FaseForaDeOrdem,
    LigacaoRecusada,
    abrir_ligacao,
    emitir_certificado,
    exportar,
    ligacao_assinada,
    purgar,
    reaplicar_apos_restauro,
    tenants_purgados,
    verificar_certificado,
)
from kamba_core.offboarding.purga import sem_caminho  # noqa: E402
from kamba_core.retencao import hold, politica  # noqa: E402
from kamba_core.storage.fake import MotorEmMemoria  # noqa: E402
from kamba_core.storage.guarda import ArmazenamentoPorTenant  # noqa: E402

from tests import factories  # noqa: E402
from tests.base import (  # noqa: E402
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    ComBase,
    sqlstate,
)

VIOLACAO_DE_UNICIDADE = "23505"
FASES = ("verificacao", "pendentes", "canal", "exportacao", "revogacao", "purga", "certificado")
DIAS = {"verificacao": 0, "canal": 1, "pendentes": 7, "exportacao": 7, "revogacao": 7,
        "purga": 30, "certificado": 30}
D0 = datetime.now(timezone.utc) - timedelta(days=31)
D31 = D0 + timedelta(days=31)
CHAVE = b"k" * 32


class LigacaoDeEnsaio:
    """Uma unidade com um papel, dentro da transaccao do ensaio (a do KAM-071)."""

    autocommit = False

    def __init__(self, conexao, papel: str = "kamba_batch") -> None:
        self.conexao = conexao
        self.papel = papel

    def _executar(self, *instrucoes: str) -> None:
        cursor = self.conexao.cursor()
        for instrucao in instrucoes:
            cursor.execute(instrucao)

    def cursor(self):
        self._executar("SAVEPOINT unidade", f"SET ROLE {self.papel}")
        return self.conexao.cursor()

    def commit(self) -> None:
        self._executar("RESET ROLE", "RELEASE SAVEPOINT unidade")

    def rollback(self) -> None:
        self._executar("ROLLBACK TO SAVEPOINT unidade", "RELEASE SAVEPOINT unidade", "RESET ROLE")

    def close(self) -> None:
        pass


class ComOffboarding(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cur = self.conexao.cursor()
        self.armazenamento = ArmazenamentoPorTenant(MotorEmMemoria())

    def batch(self):
        return LigacaoDeEnsaio(self.conexao)

    def app(self):
        return LigacaoDeEnsaio(self.conexao, "kamba_app")

    def tenant(self, estado: str = "ativo") -> str:
        t = factories.tenant(self.cur)
        if estado != "onboarding":
            factories.aceitar_contratos_vigentes(self.cur, t)
            self.cur.execute("UPDATE platform.tenants SET estado = %s WHERE id = %s", (estado, t))
        return t

    def pedido(self, tenant: str, d0: datetime = D0, **estados: str) -> None:
        """As sete fases com a forma do `abrirPedido`, e os estados pedidos por cima."""
        for fase in FASES:
            resultado = {"origem": "titular", "confirmacoes": ["otp", "email"],
                         "d0": d0.isoformat(), "aviso": True} if fase == "verificacao" else {}
            estado = "concluida" if fase == "verificacao" else estados.get(fase, "pendente")
            self.cur.execute(
                "INSERT INTO platform.offboarding_run (tenant_id, fase, estado, prazo_at, resultado) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (tenant, fase, estado, d0 + timedelta(days=DIAS[fase]), json.dumps(resultado)),
            )

    def ate_a_purga(self, tenant: str) -> None:
        self.pedido(tenant, pendentes="concluida", canal="concluida",
                    exportacao="concluida", revogacao="concluida")

    def semear(self, tenant: str) -> dict[str, str]:
        """Um contacto, um canal e uma conversa: o minimo com FK entre classes."""
        canal = factories.canal(self.cur, tenant)
        contacto = factories.contacto(self.cur, tenant)
        self.cur.execute(
            "INSERT INTO platform.conversations (tenant_id, contact_id, channel_id) "
            "VALUES (%s, %s, %s) RETURNING id::text",
            (tenant, contacto, canal),
        )
        conversa = self.cur.fetchone()[0]
        return {"canal": canal, "contacto": contacto, "conversa": conversa}

    def contar(self, tabela: str, tenant: str) -> int:
        self.cur.execute(f"SELECT count(*) FROM {tabela} WHERE tenant_id = %s", (tenant,))
        return self.cur.fetchone()[0]

    def fase(self, tenant: str, fase: str) -> tuple[str, dict]:
        self.cur.execute(
            "SELECT estado, resultado FROM platform.offboarding_run WHERE tenant_id = %s AND fase = %s",
            (tenant, fase),
        )
        estado, resultado = self.cur.fetchone()
        return estado, (json.loads(resultado) if isinstance(resultado, str) else resultado)

    def purge_log(self, execucao: str) -> list[tuple[str, str, str | None, int]]:
        self.cur.execute(
            "SELECT tabela, resultado, motivo, linhas FROM platform.purge_log "
            "WHERE execucao_id = %s ORDER BY tabela", (execucao,))
        return [tuple(r) for r in self.cur.fetchall()]


# ------------------------------------------------------------------- esquema


class TestEsquema(ComOffboarding):
    def test_uma_linha_por_tenant_e_por_fase(self) -> None:
        t = self.tenant()
        self.pedido(t)
        self.cur.execute("SAVEPOINT s")
        with self.assertRaises(Exception) as erro:
            self.cur.execute(
                "INSERT INTO platform.offboarding_run (tenant_id, fase, prazo_at) VALUES (%s, 'purga', now())",
                (t,))
        self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_UNICIDADE)
        self.cur.execute("ROLLBACK TO SAVEPOINT s")

    def test_os_dominios_fecham(self) -> None:
        t = self.tenant()
        for coluna, valor in (("fase", "'arquivo'"), ("estado", "'apagada'")):
            with self.subTest(coluna=coluna):
                self.cur.execute("SAVEPOINT s")
                with self.assertRaises(Exception) as erro:
                    fase = valor if coluna == "fase" else "'purga'"
                    estado = valor if coluna == "estado" else "'pendente'"
                    self.cur.execute(
                        "INSERT INTO platform.offboarding_run (tenant_id, fase, estado, prazo_at) "
                        f"VALUES (%s, {fase}, {estado}, now())", (t,))
                self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_CHECK)
                self.cur.execute("ROLLBACK TO SAVEPOINT s")

    def test_o_lote_muda_o_estado_e_o_resultado_e_nao_o_prazo(self) -> None:
        t = self.tenant()
        self.pedido(t)
        self.cur.execute("SET ROLE kamba_batch")
        self.cur.execute(
            "UPDATE platform.offboarding_run SET estado = 'em_curso', resultado = '{\"a\":1}' "
            "WHERE tenant_id = %s AND fase = 'purga'", (t,))
        self.assertEqual(self.cur.rowcount, 1)
        for instrucao in (
            "UPDATE platform.offboarding_run SET prazo_at = now() + interval '1 year' "
            "WHERE tenant_id = %s AND fase = 'purga'",
            "DELETE FROM platform.offboarding_run WHERE tenant_id = %s",
        ):
            with self.subTest(instrucao=instrucao[:30]):
                self.cur.execute("SAVEPOINT s")
                with self.assertRaises(Exception) as erro:
                    self.cur.execute(instrucao, (t,))
                self.assertEqual(sqlstate(erro.exception), PRIVILEGIO_INSUFICIENTE)
                self.cur.execute("ROLLBACK TO SAVEPOINT s")
        self.cur.execute("RESET ROLE")

    def test_a_aplicacao_nao_le_nada(self) -> None:
        t = self.tenant()
        self.pedido(t)
        self.cur.execute("SET ROLE kamba_app")
        factories.contexto(self.cur, t)
        with self.assertRaises(Exception) as erro:
            self.cur.execute("SELECT count(*) FROM platform.offboarding_run")
        self.assertEqual(sqlstate(erro.exception), PRIVILEGIO_INSUFICIENTE)

    def test_a_rls_esta_ligada_e_forcada(self) -> None:
        self.cur.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'platform.offboarding_run'::regclass")
        self.assertEqual(tuple(self.cur.fetchone()), (True, True))
        t, outro = self.tenant(), self.tenant()
        self.pedido(t)
        # **O dono da tabela**, e nao a auditoria: o `FORCE` e o que obriga o
        # dono a passar pela politica, e e so para ele que um `NO FORCE` muda
        # alguma coisa (a mutacao «as fases perdem o FORCE da RLS»).
        self.cur.execute(
            "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'platform.offboarding_run'::regclass")
        dono = self.cur.fetchone()[0]
        self.cur.execute(f"SET ROLE {dono}")
        for contexto, esperado in ((t, 7), (outro, 0), (None, 0)):
            with self.subTest(contexto=contexto):
                factories.contexto(self.cur, contexto)
                self.cur.execute("SELECT count(*) FROM platform.offboarding_run WHERE tenant_id = %s", (t,))
                self.assertEqual(self.cur.fetchone()[0], esperado)
        self.cur.execute("RESET ROLE")

    def test_o_chr_subscreve_a_suspensao_e_o_encerramento(self) -> None:
        self.cur.execute(
            "SELECT tipo, versao_max, exige_ordem, activo FROM platform.evt_subscricoes "
            "WHERE consumer = 'chr' ORDER BY tipo")
        self.assertEqual(
            [tuple(r) for r in self.cur.fetchall()],
            [("tenant.activated", 1, False, True), ("tenant.closed", 1, False, True),
             ("tenant.suspended", 1, False, True)],
        )

    def test_os_caminhos_da_purga_sao_os_que_o_lote_pode_apagar(self) -> None:
        """Os caminhos foram medidos contra a base; isto mantem-nos medidos."""
        for caminho in CAMINHOS_DO_ENCERRAMENTO:
            for tabela in caminho.tabelas:
                with self.subTest(tabela=tabela):
                    self.cur.execute("SELECT has_table_privilege('kamba_batch', %s, 'DELETE')", (tabela,))
                    self.assertTrue(self.cur.fetchone()[0])
        # E as do cofre nao: e por isso que saem pelo `apagar_contactos`.
        for tabela in ("platform.contacts", "platform.contact_deks", "platform.contact_endpoints"):
            with self.subTest(tabela=tabela):
                self.cur.execute("SELECT has_table_privilege('kamba_batch', %s, 'DELETE')", (tabela,))
                self.assertFalse(self.cur.fetchone()[0])


# ---------------------------------------------------------------- exportacao


class TestExportacao(ComOffboarding):
    def ficheiros(self, ref) -> dict[str, bytes]:
        corpo = b"".join(self.armazenamento._motor.get(str(ref.key)))
        with zipfile.ZipFile(io.BytesIO(corpo)) as z:
            return {n: z.read(n) for n in z.namelist()}

    def test_a_exportacao_de_a_nunca_contem_dados_de_b(self) -> None:
        a, b = self.tenant(), self.tenant()
        sa, sb = self.semear(a), self.semear(b)
        self.pedido(a, pendentes="concluida")
        r = exportar(self.batch, self.app, a, self.armazenamento, D0 + timedelta(days=2))
        conteudo = b"".join(self.ficheiros(r["ref"]).values())
        for valor in (sa["contacto"], sa["conversa"]):
            self.assertIn(valor.encode(), conteudo)
        for valor in (b, sb["contacto"], sb["conversa"], sb["canal"]):
            with self.subTest(valor=valor):
                self.assertNotIn(valor.encode(), conteudo)
        self.assertEqual(r["manifesto"]["coleccoes"]["clientes"], 1)
        self.assertEqual(r["manifesto"]["coleccoes"]["conversas"], 1)

    def test_o_manifesto_leva_o_sha256_de_cada_ficheiro(self) -> None:
        import hashlib
        a = self.tenant()
        self.semear(a)
        self.pedido(a, pendentes="concluida")
        r = exportar(self.batch, self.app, a, self.armazenamento, D0 + timedelta(days=2))
        ficheiros = self.ficheiros(r["ref"])
        manifesto = json.loads(ficheiros.pop("manifesto.json"))
        self.assertEqual(manifesto["versao"], "1.0.0")
        self.assertEqual(sorted(f["nome"] for f in manifesto["ficheiros"]), sorted(ficheiros))
        for f in manifesto["ficheiros"]:
            self.assertEqual(hashlib.sha256(ficheiros[f["nome"]]).hexdigest(), f["sha256"])
        self.assertIn({"coleccao": "catalogo", "razao": manifesto["indisponiveis"][0]["razao"]},
                      manifesto["indisponiveis"])

    def test_sai_de_um_tenant_suspenso(self) -> None:
        """KAM-058, criterio 7: a suspensao nao bloqueia o titular de exportar."""
        a = self.tenant(estado="suspenso")
        s = self.semear(a)
        self.pedido(a, pendentes="concluida")
        r = exportar(self.batch, self.app, a, self.armazenamento, D0 + timedelta(days=2))
        self.assertIn(s["contacto"].encode(), b"".join(self.ficheiros(r["ref"]).values()))
        self.assertEqual(self.fase(a, "exportacao")[0], "concluida")
        self.cur.execute("SELECT estado FROM platform.tenants WHERE id = %s", (a,))
        self.assertEqual(self.cur.fetchone()[0], "suspenso", "exportar nao muda o estado")

    def test_cada_geracao_e_auditada(self) -> None:
        a = self.tenant()
        self.pedido(a, pendentes="concluida")
        for n in (1, 2):
            r = exportar(self.batch, self.app, a, self.armazenamento, D0 + timedelta(days=2 + n))
            self.assertEqual(r["geracao"], n)
        self.cur.execute(
            "SELECT count(*) FROM platform.audit_log WHERE tenant_id = %s "
            "AND entity = 'offboarding_exportacao' AND action = 'batch.run'", (a,))
        self.assertEqual(self.cur.fetchone()[0], 2)
        self.assertEqual(self.fase(a, "exportacao")[1]["geracoes"], 2)

    def test_sem_pendentes_fechados_ou_cancelado_nao_exporta(self) -> None:
        a = self.tenant()
        self.pedido(a)
        with self.assertRaises(FaseForaDeOrdem):
            exportar(self.batch, self.app, a, self.armazenamento, D0)
        b = self.tenant()
        self.pedido(b, pendentes="concluida")
        self.cur.execute(
            "UPDATE platform.offboarding_run SET resultado = resultado || '{\"cancelado_at\":\"x\"}' "
            "WHERE tenant_id = %s AND fase = 'verificacao'", (b,))
        with self.assertRaises(FaseForaDeOrdem):
            exportar(self.batch, self.app, b, self.armazenamento, D0)

    def test_a_ligacao_expirada_ou_de_outro_tenant_e_recusada(self) -> None:
        """Adversarial (e): o 403."""
        a, b = self.tenant(), self.tenant()
        self.pedido(a, pendentes="concluida")
        agora = D0 + timedelta(days=2)
        r = exportar(self.batch, self.app, a, self.armazenamento, agora)
        token = ligacao_assinada(CHAVE, a, str(r["ref"].key), agora)
        self.assertTrue(abrir_ligacao(CHAVE, token, a, agora + timedelta(hours=23), self.armazenamento))
        for nome, tenant, quando in (("expirada", a, agora + timedelta(hours=24)),
                                     ("outro tenant", b, agora)):
            with self.subTest(nome=nome), self.assertRaises(LigacaoRecusada):
                abrir_ligacao(CHAVE, token, tenant, quando, self.armazenamento)


# --------------------------------------------------------------------- purga


class TestPurga(ComOffboarding):
    def test_apaga_pelos_caminhos_regista_e_retem_o_resto(self) -> None:
        a, b = self.tenant(), self.tenant()
        sa = self.semear(a)
        self.semear(b)
        self.ate_a_purga(a)
        r = purgar(self.batch, a, D31)
        # Varrimento: zero linhas do tenant nas tabelas com caminho.
        for caminho in CAMINHOS_DO_ENCERRAMENTO:
            for tabela in caminho.tabelas:
                with self.subTest(tabela=tabela):
                    self.assertEqual(self.contar(tabela, a), 0)
        # O tenant B ficou inteiro.
        self.assertEqual(self.contar("platform.conversations", b), 1)
        self.assertEqual(self.contar("platform.tenant_channels", b), 1)
        # O contacto nao tem caminho sem o cofre, e diz-se.
        self.assertEqual(self.contar("platform.contacts", a), 1)
        log = self.purge_log(r["execucao_id"])
        self.assertIn(("platform.conversations", "ok", None, 1), log)
        self.assertIn(("platform.tenant_channels", "ok", None, 1), log)
        self.assertIn(("platform.contacts", "recusada", "sem_caminho", 0), log)
        self.assertEqual({t for t, res, *_ in log if res == "recusada"},
                         set(r["retidas"]))
        self.assertEqual(self.fase(a, "purga")[0], "concluida")
        self.assertEqual(r["apagadas"]["platform.conversations"], 1)
        self.assertTrue(sa)

    def test_com_o_cofre_os_contactos_saem_e_ficam_registados(self) -> None:
        a = self.tenant()
        self.semear(a)
        self.ate_a_purga(a)
        chamados: list[str] = []
        r = purgar(self.batch, a, D31, apagar_contactos=lambda t: (chamados.append(t), 1)[1])
        self.assertEqual(chamados, [a])
        self.assertIn(("platform.contacts", "ok", None, 1), self.purge_log(r["execucao_id"]))

    def test_repetir_nao_duplica(self) -> None:
        a = self.tenant()
        self.semear(a)
        self.ate_a_purga(a)
        primeira = purgar(self.batch, a, D31)
        segunda = purgar(self.batch, a, D31 + timedelta(hours=1))
        self.assertEqual(primeira["execucao_id"], segunda["execucao_id"])
        self.cur.execute("SELECT count(DISTINCT execucao_id) FROM platform.purge_log WHERE tenant_id = %s", (a,))
        self.assertEqual(self.cur.fetchone()[0], 1)

    def test_um_crash_a_meio_retoma_e_conclui(self) -> None:
        a = self.tenant()
        self.semear(a)
        self.ate_a_purga(a)
        tentativas = []

        def cofre(t: str) -> int:
            tentativas.append(t)
            if len(tentativas) == 1:
                raise RuntimeError("o cofre caiu a meio")
            return 1

        r = purgar(self.batch, a, D31, apagar_contactos=cofre)
        self.assertEqual(r["falhas"], ["platform.contacts"])
        self.assertEqual(self.fase(a, "purga")[0], "falhada")
        self.assertEqual(self.contar("platform.conversations", a), 0, "o que correu ficou feito")
        r = purgar(self.batch, a, D31 + timedelta(hours=1), apagar_contactos=cofre)
        self.assertEqual(r["falhas"], [])
        self.assertEqual(self.fase(a, "purga")[0], "concluida")

    def test_disputa_aberta_suspende_a_purga(self) -> None:
        """Adversarial (c)."""
        a = self.tenant()
        self.semear(a)
        self.ate_a_purga(a)
        hold.aplicar(self.cur, tenant_id=a, contact_id=None, actor_type="staff",
                     actor_id="ensaio", motivo_ref="disputa-de-ensaio")
        r = purgar(self.batch, a, D31)
        self.assertEqual(r["disputa"], ["hold_tenant"])
        self.assertEqual(self.fase(a, "purga")[0], "suspensa_disputa")
        self.assertEqual(self.contar("platform.conversations", a), 1, "nada saiu")
        self.cur.execute("SELECT DISTINCT resultado, motivo FROM platform.purge_log WHERE tenant_id = %s", (a,))
        self.assertEqual([tuple(r) for r in self.cur.fetchall()], [("retida", "hold_tenant")])
        # Levantado o hold, a purga corre.
        hold.levantar(self.cur, tenant_id=a, contact_id=None, actor_type="staff",
                      actor_id="ensaio", motivo_ref="disputa-de-ensaio")
        purgar(self.batch, a, D31 + timedelta(days=1))
        self.assertEqual(self.contar("platform.conversations", a), 0)

    def test_pedido_cancelado_nao_apaga_nada(self) -> None:
        """Adversarial (b): cancelado em D3."""
        a = self.tenant()
        self.semear(a)
        self.ate_a_purga(a)
        self.cur.execute(
            "UPDATE platform.offboarding_run SET resultado = resultado || "
            "'{\"cancelado_at\":\"2026-11-03T00:00:00+00:00\"}' "
            "WHERE tenant_id = %s AND fase = 'verificacao'", (a,))
        with self.assertRaises(FaseForaDeOrdem):
            purgar(self.batch, a, D31)
        self.assertEqual(self.contar("platform.conversations", a), 1)
        self.assertEqual(self.contar("platform.tenant_channels", a), 1)

    def test_antes_do_d30_ou_sem_revogacao_nao_purga(self) -> None:
        a = self.tenant()
        self.ate_a_purga(a)
        with self.assertRaises(FaseForaDeOrdem):
            purgar(self.batch, a, D0 + timedelta(days=29))
        b = self.tenant()
        self.pedido(b, pendentes="concluida", exportacao="concluida")
        with self.assertRaises(FaseForaDeOrdem):
            purgar(self.batch, b, D31)

    def test_o_restauro_traz_o_tenant_de_volta_e_a_reaplicacao_volta_a_apaga_lo(self) -> None:
        """Criterio 10 e adversarial (d), com restauro simulado."""
        a = self.tenant()
        self.ate_a_purga(a)
        antes_da_purga = D31 - timedelta(hours=1)
        purgar(self.batch, a, D31)
        externos = tenants_purgados(self.cur)
        self.assertIn(a, [t for t, _ in externos])
        # O «restauro»: uma copia de antes da purga traz o canal e a conversa de volta.
        s = self.semear(a)
        self.assertEqual(self.contar("platform.conversations", a), 1)
        # Uma copia de depois da purga nao pede reaplicacao.
        self.assertEqual(
            reaplicar_apos_restauro(self.batch, D31 + timedelta(hours=1), D31 + timedelta(days=1),
                                    purgados_externos=externos, holds_externos=hold.Holds()),
            [])
        self.assertEqual(self.contar("platform.conversations", a), 1)
        reapagados = reaplicar_apos_restauro(
            self.batch, antes_da_purga, D31 + timedelta(days=1),
            purgados_externos=externos, holds_externos=hold.Holds())
        self.assertEqual(reapagados, [a])
        self.assertEqual(self.contar("platform.conversations", a), 0)
        self.assertEqual(self.contar("platform.tenant_channels", a), 0)
        self.assertTrue(s)

    def test_a_reaplicacao_exige_as_fontes_de_fora(self) -> None:
        with self.assertRaises(ValueError):
            reaplicar_apos_restauro(self.batch, D0, D31, purgados_externos=None,  # type: ignore[arg-type]
                                    holds_externos=hold.Holds())

    def test_o_que_nao_tem_caminho_e_o_resto_da_classe_relacao(self) -> None:
        relacao = {t.nome for t in politica.classe("relacao").tabelas}
        com = {c.tabela for c in CAMINHOS_DO_ENCERRAMENTO}
        self.assertTrue(com <= relacao, com - relacao)
        self.assertTrue(set(sem_caminho()) <= relacao)


# --------------------------------------------------------------- certificado


def _retencao_das_copias() -> int:
    texto = (_RAIZ / "infra" / "backup" / "cobertura.yaml").read_text(encoding="utf-8")
    return int(re.search(r"(?m)^\s*retencao_dias:\s*(\d+)\s*$", texto).group(1))


class TestCertificado(ComOffboarding):
    def purgado(self) -> str:
        a = self.tenant()
        self.semear(a)
        self.ate_a_purga(a)
        purgar(self.batch, a, D31)
        return a

    def test_lista_o_que_saiu_e_o_que_ficou_e_nao_promete_as_copias(self) -> None:
        a = self.purgado()
        entregues: list[bytes] = []
        r = emitir_certificado(
            self.batch, a, D31, chave=CHAVE, kid="k-ensaio",
            copias_expiram_em_dias=_retencao_das_copias(),
            entregar=lambda t, corpo: (entregues.append(corpo), True)[1])
        self.assertEqual(self.fase(a, "certificado")[0], "concluida")
        cert = json.loads(entregues[0])
        self.assertTrue(verificar_certificado(cert, CHAVE))
        self.assertIn({"tabela": "platform.conversations", "linhas": 1}, cert["apagadas"])
        retidas = {x.get("classe") or x.get("tabela") for x in cert["retidas"]}
        self.assertTrue({"fiscal_pagamentos", "fiscal_encomendas", "platform.contacts"} <= retidas)
        for x in cert["retidas"]:
            self.assertTrue(x["fundamento"])
        self.assertFalse(cert["copias_de_seguranca"]["apagamento_afirmado"])
        self.assertEqual(
            datetime.fromisoformat(cert["copias_de_seguranca"]["podem_conter_dados_ate"]) - D31,
            timedelta(days=35))
        self.assertEqual(r["sha256"], cert["sha256"])
        # Alterado, nao verifica.
        cert["apagadas"][0]["linhas"] += 1
        self.assertFalse(verificar_certificado(cert, CHAVE))

    def test_a_entrega_que_falha_repete_o_mesmo_documento(self) -> None:
        a = self.purgado()
        primeira = emitir_certificado(self.batch, a, D31, chave=CHAVE, kid="k", copias_expiram_em_dias=35,
                                      entregar=lambda *_: False)
        self.assertEqual(self.fase(a, "certificado")[0], "em_curso")
        segunda = emitir_certificado(self.batch, a, D31 + timedelta(days=1), chave=CHAVE, kid="k",
                                     copias_expiram_em_dias=35, entregar=lambda *_: True)
        self.assertEqual(primeira["sha256"], segunda["sha256"])
        self.assertEqual(self.fase(a, "certificado")[0], "concluida")

    def test_sem_purga_concluida_nao_ha_certificado(self) -> None:
        a = self.tenant()
        self.ate_a_purga(a)
        with self.assertRaises(FaseForaDeOrdem):
            emitir_certificado(self.batch, a, D31, chave=CHAVE, kid="k", copias_expiram_em_dias=35,
                               entregar=lambda *_: True)


if __name__ == "__main__":
    import unittest

    unittest.main()
