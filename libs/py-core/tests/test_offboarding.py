"""O off-boarding do lado dos dados, sem base (KAM-098).

Os testes requeridos do bloco que sao unitarios: a seleccao das classes a reter,
o calculo do manifesto e do *hash*, a ligacao de 24 h e o certificado. O
calendario D0–D30 e do lado TypeScript (`packages/core-ts/tests/offboarding.test.ts`).

A purga e a exportacao correm aqui sobre uma base falsa que **le o texto** de
cada instrucao (a licao do KAM-070: um duplo que decide pelo argumento fica
verde com o predicado apagado). O que so a base prova — os privilegios, a RLS, o
isolamento cruzado, os caminhos — esta em `db/tests/test_offboarding.py`.
"""

from __future__ import annotations

import hashlib
import io
import json
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kamba_core.offboarding import (
    CAMINHOS_DO_ENCERRAMENTO,
    emitir_certificado,
    TABELAS_DOS_CONTACTOS,
    FaseForaDeOrdem,
    LigacaoRecusada,
    abrir_ligacao,
    exportar,
    ligacao_assinada,
    montar_pacote,
    purgar,
    reaplicar_apos_restauro,
    subestado,
    verificar_certificado,
)
from kamba_core.offboarding.certificado import FUNDAMENTO_FISCAL, assinar, montar
from kamba_core.offboarding.contrato import LinhaDaFase
from kamba_core.offboarding.exportacao import COLECCOES, RAZAO_SEM_CATALOGO
from kamba_core.offboarding.purga import sem_caminho
from kamba_core.retencao import hold, politica
from kamba_core.storage.fake import MotorEmMemoria
from kamba_core.storage.guarda import ArmazenamentoPorTenant
from kamba_core.storage.port import ObjectRef

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
D0 = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
CHAVE = b"c" * 32
RAIZ = Path(__file__).resolve().parents[3]


# ------------------------------------------------------------- base falsa


class BaseFalsa:
    """Responde pelo texto da instrucao. As fases de cada tenant vivem num dicionario."""

    def __init__(self, fases: dict[str, dict[str, LinhaDaFase]], disputas: int = 0) -> None:
        self.fases = fases
        self.disputas = disputas
        self.instrucoes: list[tuple[str, tuple]] = []
        self.purge_log: list[tuple] = []
        self.apagadas: dict[str, int] = {}
        self.falhar_em: str | None = None
        self.linhas = {"clientes": [(A, D0)]}
        self.trancados: set[str] = set()
        self.estados: dict[str, str] = {}
        self.eventos: list[tuple] = []
        self.hold_a_meio_em: str | None = None
        self.holds: set[str] = set()


class Cursor:
    def __init__(self, base: BaseFalsa) -> None:
        self.base = base
        self._linhas: list[tuple] = []
        self.rowcount = 0
        self.description: list[tuple] = []

    def execute(self, sql: str, parametros: tuple = ()) -> None:
        b = self.base
        b.instrucoes.append((sql, tuple(parametros)))
        self._linhas, self.rowcount = [], 0
        if "set_config" in sql:
            self._linhas = [("",)]
        elif "FROM platform.offboarding_run" in sql and "FOR UPDATE" in sql:
            t = parametros[0]
            self._linhas = [(f.fase, f.estado, f.prazo_at, dict(f.resultado)) for f in b.fases.get(t, {}).values()]
        elif sql.lstrip().startswith("UPDATE platform.offboarding_run"):
            estado, resultado, t, fase = parametros
            antiga = b.fases[t][fase]
            b.fases[t][fase] = LinhaDaFase(fase, estado, antiga.prazo_at, json.loads(resultado))
            self.rowcount = 1
        elif "audit_append" in sql:
            self._linhas = [(1,)]
        elif "retention.hold_aplicado" in sql:
            self._linhas = [(t, "retention_hold_tenant", t) for t in sorted(b.holds)]
        elif "pg_try_advisory_lock" in sql:
            livre = parametros[0] not in b.trancados
            b.trancados.add(parametros[0])
            self._linhas = [(livre,)]
        elif "pg_advisory_unlock" in sql:
            b.trancados.discard(parametros[0])
            self._linhas = [(True,)]
        elif "FROM platform.tenants WHERE id" in sql:
            self._linhas = [(b.estados.get(parametros[0], "encerrado"),)]
        elif "transition_tenant" in sql:
            mudou = b.estados.get(parametros[0]) in ("ativo", "suspenso")
            if mudou:
                b.estados[parametros[0]] = "encerrado"
            self._linhas = [(mudou,)]
        elif "evt_emitir" in sql:
            b.eventos.append(tuple(parametros))
            self._linhas = [("e",)]
        elif sql.startswith("UPDATE platform.entitlements"):
            self.rowcount = 1
        elif "estado = 'em_disputa'" in sql:
            self._linhas = [(b.disputas,)]
        elif sql.startswith("DELETE FROM"):
            tabela = sql.split()[2]
            # O predicado tem de estar no texto: sem ele, a base falsa recusa.
            if "WHERE tenant_id = %s" not in sql:
                raise AssertionError("um DELETE sem o predicado do tenant")
            if b.falhar_em == tabela:
                b.falhar_em = None
                raise RuntimeError("falha simulada")
            if b.hold_a_meio_em == tabela:
                # Um hold aplicado enquanto a corrida vai a meio.
                b.hold_a_meio_em = None
                b.holds.add(A)
            self.rowcount = 2
            b.apagadas[tabela] = b.apagadas.get(tabela, 0) + 2
        elif "FROM platform.purge_log" in sql:
            execucoes, t = parametros
            self._linhas = [(p[2], p[5], p[6], p[7]) for p in b.purge_log if p[0] in execucoes and p[3] == t]
        elif "INSERT INTO platform.purge_log" in sql:
            b.purge_log.append(tuple(parametros))
        elif "FROM platform.contacts" in sql:
            assert "tenant_id = %s" in sql
            self.description = [("contact_id",), ("criado_at",)]
            self._linhas = list(b.linhas["clientes"]) if parametros[0] == A else []
        elif any(f"FROM platform.{t}" in sql for t in ("orders_mirror", "conversations", "consent_actual")):
            assert "tenant_id = %s" in sql
            self.description = [("id",)]
        else:
            raise AssertionError(f"instrucao inesperada: {sql[:80]}")

    def fetchone(self):
        return self._linhas[0] if self._linhas else None

    def fetchall(self):
        return list(self._linhas)

    def close(self) -> None:
        pass


class Ligacao:
    autocommit = False

    def __init__(self, base: BaseFalsa) -> None:
        self.base = base

    def cursor(self) -> Cursor:
        return Cursor(self.base)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def fases(**estados: str) -> dict[str, LinhaDaFase]:
    dias = {"verificacao": 0, "canal": 1, "pendentes": 7, "exportacao": 7, "revogacao": 7,
            "purga": 30, "certificado": 30}
    saida = {}
    for fase, dia in dias.items():
        estado = "concluida" if fase == "verificacao" else estados.get(fase, "pendente")
        resultado = {"origem": "titular"} if fase == "verificacao" else {}
        saida[fase] = LinhaDaFase(fase, estado, D0 + timedelta(days=dia), resultado)
    return saida


def ate_a_purga() -> dict[str, LinhaDaFase]:
    return fases(pendentes="concluida", canal="concluida", exportacao="concluida", revogacao="concluida")


# --------------------------------------------------------------- o pacote


class TestPacote(unittest.TestCase):
    def pacote(self):
        coleccoes = {"clientes": [{"contact_id": A, "criado_at": D0}],
                     "encomendas": [{"id": "e1", "lines_snapshot": [{"sku": "x"}], "total_minor": 1500}]}
        objectos = [ObjectRef(f"t/{A}/media/2026/10/b", 3), ObjectRef(f"t/{A}/media/2026/10/a", 7)]
        return montar_pacote(A, coleccoes, objectos, D0, indisponiveis={"catalogo": RAZAO_SEM_CATALOGO})

    def test_o_mesmo_conteudo_da_o_mesmo_sha256(self) -> None:
        um, m1 = self.pacote()
        dois, m2 = self.pacote()
        self.assertEqual(hashlib.sha256(um).hexdigest(), hashlib.sha256(dois).hexdigest())
        self.assertEqual(m1, m2)

    def test_o_manifesto_resume_cada_ficheiro_do_zip(self) -> None:
        corpo, manifesto = self.pacote()
        with zipfile.ZipFile(io.BytesIO(corpo)) as z:
            ficheiros = {n: z.read(n) for n in z.namelist()}
        self.assertEqual(json.loads(ficheiros.pop("manifesto.json")), manifesto)
        self.assertEqual(sorted(ficheiros), sorted(f["nome"] for f in manifesto["ficheiros"]))
        for f in manifesto["ficheiros"]:
            self.assertEqual(hashlib.sha256(ficheiros[f["nome"]]).hexdigest(), f["sha256"])
            self.assertEqual(len(ficheiros[f["nome"]]), f["bytes"])
        self.assertEqual(manifesto["versao"], "1.0.0")
        self.assertEqual(manifesto["coleccoes"], {"clientes": 1, "encomendas": 1, "ficheiros": 2})
        self.assertEqual(manifesto["indisponiveis"], [{"coleccao": "catalogo", "razao": RAZAO_SEM_CATALOGO}])

    def test_csv_e_json_para_cada_coleccao(self) -> None:
        corpo, _ = self.pacote()
        with zipfile.ZipFile(io.BytesIO(corpo)) as z:
            csv = z.read("encomendas.csv").decode()
            self.assertIn("encomendas.json", z.namelist())
        self.assertEqual(csv.splitlines()[0], "id,lines_snapshot,total_minor")
        self.assertIn('"[{""sku"":""x""}]"', csv)

    def test_um_conteudo_diferente_muda_o_hash(self) -> None:
        um, _ = self.pacote()
        outro, _ = montar_pacote(A, {"clientes": []}, [], D0)
        self.assertNotEqual(um, outro)

    def test_toda_a_consulta_da_exportacao_filtra_pelo_tenant(self) -> None:
        for nome, sql in COLECCOES.items():
            with self.subTest(nome=nome):
                self.assertIn("WHERE tenant_id = %s::uuid", sql)


# ---------------------------------------------------------------- a ligacao


class TestLigacao(unittest.TestCase):
    def setUp(self) -> None:
        self.sto = ArmazenamentoPorTenant(MotorEmMemoria())
        self.chave = f"t/{A}/dsar/2026/10/33333333-3333-4333-8333-333333333333"
        self.token = ligacao_assinada(CHAVE, A, self.chave, D0)

    def test_vale_24_horas_e_so_para_o_tenant(self) -> None:
        self.assertTrue(abrir_ligacao(CHAVE, self.token, A, D0 + timedelta(hours=23, minutes=59), self.sto))
        for nome, token, tenant, quando, chave in (
            ("expirada", self.token, A, D0 + timedelta(hours=24), CHAVE),
            ("outro tenant", self.token, B, D0, CHAVE),
            ("outra chave", self.token, A, D0, b"x" * 32),
            ("adulterada", self.token[:-2] + "AA", A, D0, CHAVE),
            ("ilegivel", "lixo", A, D0, CHAVE),
        ):
            with self.subTest(nome=nome), self.assertRaises(LigacaoRecusada):
                abrir_ligacao(chave, token, tenant, quando, self.sto)

    def test_a_chave_curta_e_recusada(self) -> None:
        with self.assertRaises(ValueError):
            ligacao_assinada(b"curta", A, self.chave, D0)


# -------------------------------------------------------- classes e estados


class TestClassesARetirEReter(unittest.TestCase):
    def test_os_caminhos_e_o_resto_sao_a_classe_relacao_inteira(self) -> None:
        relacao = [t.nome for t in politica.classe("relacao").tabelas]
        com = [c.tabela for c in CAMINHOS_DO_ENCERRAMENTO]
        self.assertEqual(sorted(com + list(TABELAS_DOS_CONTACTOS) + list(sem_caminho())), sorted(relacao))

    def test_nenhuma_tabela_fiscal_tem_caminho(self) -> None:
        fiscais = {t.nome for c in politica.POLITICA if c.fiscal for t in c.tabelas}
        for caminho in CAMINHOS_DO_ENCERRAMENTO:
            with self.subTest(caminho=caminho.tabela):
                self.assertFalse(set(caminho.tabelas) & fiscais)
        self.assertIn("platform.tenants", sem_caminho())

    def test_o_subestado_le_se_das_fases(self) -> None:
        self.assertIsNone(subestado(fases(), "ativo"))
        self.assertEqual(subestado(fases(revogacao="concluida"), "encerrado"), "em_exportacao")
        f = ate_a_purga()
        f["purga"] = LinhaDaFase("purga", "concluida", D0, {"retidas": ["platform.tenants"]})
        self.assertEqual(subestado(f, "encerrado"), "em_retencao")
        f["purga"] = LinhaDaFase("purga", "suspensa_disputa", D0, {})
        self.assertEqual(subestado(f, "encerrado"), "em_retencao")
        f["purga"] = LinhaDaFase("purga", "concluida", D0, {"retidas": []})
        self.assertEqual(subestado(f, "encerrado"), "purgado")


# --------------------------------------------------------------- a purga


class TestPurga(unittest.TestCase):
    def correr(self, base: BaseFalsa, agora: datetime = D0 + timedelta(days=31), **kw):
        return purgar(lambda: Ligacao(base), A, agora, **kw)

    def test_apaga_pelos_caminhos_e_regista_cada_unidade(self) -> None:
        base = BaseFalsa({A: ate_a_purga()})
        r = self.correr(base, apagar_contactos=lambda t: 5)
        tabelas = {t for c in CAMINHOS_DO_ENCERRAMENTO for t in c.tabelas}
        self.assertEqual(set(base.apagadas), tabelas)
        self.assertEqual(r["apagadas"]["platform.contacts"], 5)
        self.assertEqual(set(r["retidas"]), set(sem_caminho()))
        self.assertEqual(base.fases[A]["purga"].estado, "concluida")
        resultados = {(p[2], p[5]) for p in base.purge_log}
        self.assertIn(("platform.conversations", "ok"), resultados)
        self.assertIn(("platform.tenants", "recusada"), resultados)
        # Repetir devolve o mesmo e nao apaga outra vez.
        antes = dict(base.apagadas)
        self.assertEqual(self.correr(base)["execucao_id"], r["execucao_id"])
        self.assertEqual(base.apagadas, antes)

    def test_sem_o_cofre_os_contactos_ficam_sem_caminho(self) -> None:
        base = BaseFalsa({A: ate_a_purga()})
        r = self.correr(base)
        self.assertTrue(set(TABELAS_DOS_CONTACTOS) <= set(r["retidas"]))

    def test_uma_disputa_suspende(self) -> None:
        base = BaseFalsa({A: ate_a_purga()}, disputas=1)
        r = self.correr(base)
        self.assertEqual(r["disputa"], ["encomenda_em_disputa"])
        self.assertEqual(base.apagadas, {})
        self.assertEqual(base.fases[A]["purga"].estado, "suspensa_disputa")
        self.assertTrue(all(p[5] == "retida" for p in base.purge_log))
        base = BaseFalsa({A: ate_a_purga()})
        r = self.correr(base, holds_externos=hold.Holds(tenants=frozenset({A})))
        self.assertEqual(r["disputa"], ["hold_tenant"])

    def test_uma_unidade_que_falha_deixa_a_fase_falhada_e_a_seguinte_conclui(self) -> None:
        base = BaseFalsa({A: ate_a_purga()})
        base.falhar_em = "platform.handoffs"
        r = self.correr(base)
        self.assertEqual(r["falhas"], ["platform.conversations"])
        self.assertEqual(base.fases[A]["purga"].estado, "falhada")
        self.assertIn("platform.tenant_channels", base.apagadas, "as outras unidades correram")
        self.correr(base, agora=D0 + timedelta(days=32))
        self.assertEqual(base.fases[A]["purga"].estado, "concluida")

    def test_duas_corridas_do_mesmo_tenant_nao_correm_juntas(self) -> None:
        base = BaseFalsa({A: ate_a_purga()})
        base.trancados.add(A)
        with self.assertRaises(FaseForaDeOrdem):
            self.correr(base)
        self.assertEqual(base.apagadas, {})
        base.trancados.clear()
        self.correr(base)
        self.assertEqual(base.trancados, set(), "o trinco solta-se no fim")

    def test_um_hold_aplicado_a_meio_para_a_corrida(self) -> None:
        base = BaseFalsa({A: ate_a_purga()})
        base.hold_a_meio_em = "platform.handoff_accounts"
        r = self.correr(base)
        self.assertEqual(r["disputa"], ["hold_tenant"])
        self.assertEqual(base.fases[A]["purga"].estado, "suspensa_disputa")
        self.assertNotIn("platform.conversations", base.apagadas, "parou na unidade seguinte")

    def test_o_canal_do_titular_nao_sai_na_purga(self) -> None:
        base = BaseFalsa({A: ate_a_purga()})
        r = self.correr(base)
        self.assertNotIn("platform.owner_contacts", base.apagadas)
        self.assertIn("platform.owner_contacts", r["retidas"])

    def test_o_cofre_que_falha_fica_escrito(self) -> None:
        base = BaseFalsa({A: ate_a_purga()})

        def cofre(_t: str) -> int:
            raise RuntimeError("cofre")

        self.assertEqual(self.correr(base, apagar_contactos=cofre)["falhas"], ["platform.contacts"])

    def test_fora_de_ordem_recusa(self) -> None:
        for nome, f, agora in (
            ("sem pedido", {}, D0 + timedelta(days=31)),
            ("antes do D30", ate_a_purga(), D0 + timedelta(days=29)),
            ("sem revogacao", fases(pendentes="concluida", exportacao="concluida"), D0 + timedelta(days=31)),
        ):
            with self.subTest(nome=nome), self.assertRaises(FaseForaDeOrdem):
                self.correr(BaseFalsa({A: f}), agora=agora)
        cancelado = ate_a_purga()
        v = cancelado["verificacao"]
        cancelado["verificacao"] = LinhaDaFase(v.fase, v.estado, v.prazo_at, {"cancelado_at": "x"})
        with self.assertRaises(FaseForaDeOrdem):
            self.correr(BaseFalsa({A: cancelado}))

    def test_a_reaplicacao_so_reapaga_o_purgado_depois_da_copia(self) -> None:
        base = BaseFalsa({A: ate_a_purga(), B: ate_a_purga()})
        purgado_em = D0 + timedelta(days=31)
        r = reaplicar_apos_restauro(
            lambda: Ligacao(base), purgado_em - timedelta(hours=1), D0 + timedelta(days=40),
            purgados_externos=[(A, purgado_em), (B, purgado_em - timedelta(days=1))],
            holds_externos=hold.Holds())
        self.assertEqual(r, [A])
        self.assertEqual(base.fases[A]["purga"].estado, "concluida")
        self.assertEqual(base.eventos, [], "um tenant ja encerrado na copia nao emite outra vez")
        # Uma copia de antes do encerramento trouxe-o ativo: volta a encerrar-se,
        # com o evento, e os entitlements desligam-se (achado 10).
        restaurada = BaseFalsa({A: ate_a_purga()})
        restaurada.estados[A] = "ativo"
        reaplicar_apos_restauro(
            lambda: Ligacao(restaurada), purgado_em - timedelta(days=40), D0 + timedelta(days=40),
            purgados_externos=[(A, purgado_em)], holds_externos=hold.Holds())
        self.assertEqual(restaurada.estados[A], "encerrado")
        self.assertEqual([e[0] for e in restaurada.eventos], ["tenant.closed"])
        self.assertEqual(restaurada.fases[A]["purga"].resultado["estado_do_tenant"], "encerrado")
        self.assertEqual(base.fases[B]["purga"].estado, "pendente")
        with self.assertRaises(ValueError):
            reaplicar_apos_restauro(lambda: Ligacao(base), D0, D0, purgados_externos=[],
                                    holds_externos=None)  # type: ignore[arg-type]


# ------------------------------------------------------------- a exportacao


class TestExportacao(unittest.TestCase):
    def test_gera_o_pacote_e_conclui_e_audita(self) -> None:
        base = BaseFalsa({A: fases(pendentes="concluida")})
        sto = ArmazenamentoPorTenant(MotorEmMemoria())
        r = exportar(lambda: Ligacao(base), lambda: Ligacao(base), A, sto, D0 + timedelta(days=2))
        self.assertEqual(r["geracao"], 1)
        self.assertEqual(base.fases[A]["exportacao"].estado, "concluida")
        self.assertEqual(base.fases[A]["exportacao"].resultado["sha256"], r["sha256"])
        info = sto.head(__import__("kamba_core.storage.port", fromlist=["Ctx"]).Ctx(A), r["ref"])
        self.assertEqual(info.retain_until, D0 + timedelta(days=30), "o pacote expira na purga")
        self.assertTrue(any("audit_append" in s for s, _ in base.instrucoes))
        r2 = exportar(lambda: Ligacao(base), lambda: Ligacao(base), A, sto, D0 + timedelta(days=3),
                      fonte_do_catalogo=lambda t: [{"sku": "x"}])
        self.assertEqual(r2["geracao"], 2)
        self.assertEqual(r2["manifesto"]["indisponiveis"], [])
        self.assertEqual(r2["manifesto"]["coleccoes"]["ficheiros"], 0, "o pacote anterior nao entra")

    def test_sem_pendentes_ou_depois_da_purga_recusa(self) -> None:
        sto = ArmazenamentoPorTenant(MotorEmMemoria())
        for f in (fases(), fases(pendentes="concluida", purga="concluida")):
            base = BaseFalsa({A: f})
            with self.subTest(f=f["purga"].estado), self.assertRaises(FaseForaDeOrdem):
                exportar(lambda: Ligacao(base), lambda: Ligacao(base), A, sto, D0)


# ------------------------------------------------------------- o certificado


def _retencao_das_copias() -> int:
    import re

    texto = (RAIZ / "infra" / "backup" / "cobertura.yaml").read_text(encoding="utf-8")
    return int(re.search(r"(?m)^\s*retencao_dias:\s*(\d+)\s*$", texto).group(1))


class TestCertificado(unittest.TestCase):
    def doc(self, **kw):
        registos = [("platform.conversations", "ok", None, 3), ("platform.conversations", "ok", None, 1),
                    ("platform.tenants", "recusada", "sem_caminho", 0),
                    ("platform.contacts", "recusada", "sem_caminho", 0)]
        return montar(A, D0, registos, copias_expiram_em_dias=kw.get("dias", 35), anos_fiscais=None)

    def test_lista_o_que_saiu_e_o_que_ficou_com_fundamento(self) -> None:
        d = self.doc()
        self.assertEqual(d["apagadas"], [{"tabela": "platform.conversations", "linhas": 4}])
        classes = {x.get("classe") for x in d["retidas"]}
        self.assertTrue({c.nome for c in politica.POLITICA if c.fiscal} <= classes)
        self.assertTrue(all(x["fundamento"] for x in d["retidas"]))
        self.assertIn(FUNDAMENTO_FISCAL, {x["fundamento"] for x in d["retidas"]})
        self.assertEqual(d["prazo_fiscal"]["estado"], "NAO VERIFICADO")

    def test_nao_afirma_o_apagamento_das_copias(self) -> None:
        d = self.doc()
        self.assertFalse(d["copias_de_seguranca"]["apagamento_afirmado"])
        self.assertEqual(d["copias_de_seguranca"]["podem_conter_dados_ate"],
                         (D0 + timedelta(days=35)).isoformat())
        texto = json.dumps(d).lower()
        for promessa in ("backups apagados", "copias apagadas", "cópias apagadas"):
            self.assertNotIn(promessa, texto)

    def test_o_ciclo_das_copias_e_o_do_repositorio(self) -> None:
        """Os 35 dias que os ensaios passam sao os do `infra/backup/cobertura.yaml`."""
        self.assertEqual(_retencao_das_copias(), 35)
        with self.assertRaises(ValueError):
            self.doc(dias=0)

    def test_emite_depois_da_purga_entrega_e_repete_o_mesmo(self) -> None:
        base = BaseFalsa({A: ate_a_purga()})
        abrir = lambda: Ligacao(base)  # noqa: E731
        with self.assertRaises(FaseForaDeOrdem):
            emitir_certificado(abrir, A, D0, chave=CHAVE, kid="k1", copias_expiram_em_dias=35,
                               entregar=lambda *_: True)
        purgar(abrir, A, D0 + timedelta(days=31))
        entregues: list[bytes] = []
        falha = emitir_certificado(abrir, A, D0 + timedelta(days=31), chave=CHAVE, kid="k1",
                                   copias_expiram_em_dias=35, entregar=lambda *_: False)
        self.assertEqual(base.fases[A]["certificado"].estado, "em_curso")
        r = emitir_certificado(abrir, A, D0 + timedelta(days=32), chave=CHAVE, kid="k1",
                               copias_expiram_em_dias=35,
                               entregar=lambda t, corpo: (entregues.append(corpo), True)[1])
        self.assertEqual(r["sha256"], falha["sha256"], "a mesma emissao, entregue depois")
        self.assertEqual(base.fases[A]["certificado"].estado, "concluida")
        cert = json.loads(entregues[0])
        self.assertTrue(verificar_certificado(cert, CHAVE))
        self.assertIn({"tabela": "platform.conversations", "linhas": 2}, cert["apagadas"])
        # O que fica fora da base declara-se, com fundamento (achado 6).
        escopos = {x.get("escopo") for x in cert["retidas"]}
        self.assertTrue({"sto", "chatwoot", "traces", "caches", "fornecedores_llm_stt"} <= escopos)
        # O canal do titular sai depois da entrega, e fica no purge_log (achado 4).
        self.assertTrue(any("DELETE FROM platform.owner_contacts" in s for s, _ in base.instrucoes))
        self.assertIn("platform.owner_contacts", [p[2] for p in base.purge_log if p[5] == "ok"])
        # Concluido, repetir devolve o que foi emitido sem entregar outra vez.
        self.assertTrue(emitir_certificado(abrir, A, D0 + timedelta(days=33), chave=CHAVE, kid="k1",
                                           copias_expiram_em_dias=35, entregar=None)["entregue"])  # type: ignore[arg-type]

    def test_depois_de_uma_falha_o_certificado_soma_as_duas_execucoes(self) -> None:
        """Achado 7: com so a ultima execucao, o que a primeira apagou aparecia a zero."""
        base = BaseFalsa({A: ate_a_purga()})
        abrir = lambda: Ligacao(base)  # noqa: E731
        base.falhar_em = "platform.channel_quality_log"
        purgar(abrir, A, D0 + timedelta(days=31))
        self.assertEqual(base.fases[A]["purga"].estado, "falhada")
        purgar(abrir, A, D0 + timedelta(days=32))
        self.assertEqual(len(base.fases[A]["purga"].resultado["execucoes"]), 2)
        entregues: list[bytes] = []
        emitir_certificado(abrir, A, D0 + timedelta(days=32), chave=CHAVE, kid="k1",
                           copias_expiram_em_dias=35,
                           entregar=lambda t, corpo: (entregues.append(corpo), True)[1])
        cert = json.loads(entregues[0])
        # As conversas sairam nas duas corridas (2 + 2 no duplo), e somam-se.
        self.assertIn({"tabela": "platform.conversations", "linhas": 4}, cert["apagadas"])
        self.assertNotIn("platform.channel_quality_log", {x.get("tabela") for x in cert["retidas"]},
                         "uma tabela que saiu numa execucao nao fica retida pela que falhou")

    def test_a_assinatura_nao_sobrevive_a_uma_alteracao(self) -> None:
        cert = assinar(self.doc(), CHAVE, "k1")
        self.assertTrue(verificar_certificado(cert, CHAVE))
        self.assertFalse(verificar_certificado(cert, b"z" * 32))
        cert["apagadas"][0]["linhas"] = 99
        self.assertFalse(verificar_certificado(cert, CHAVE))
        with self.assertRaises(ValueError):
            assinar(self.doc(), b"curta", "k1")


if __name__ == "__main__":
    unittest.main()
