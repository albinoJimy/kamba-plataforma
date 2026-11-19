"""A religacao de um canal que caiu contra a base (KAM-207).

As tres consultas que o KAM-207 acrescenta a `packages/core-ts/src/onboarding/consultas.ts`
— `SQL_CANAL_A_RELIGAR`, `SQL_REABRIR` e `SQL_RELIGAR_CANAL` —, executadas **tal como
estao escritas** e **como `kamba_batch`**, que e o papel com que o GWY corre o onboarding.
O duplo da bateria do `core-ts` responde por argumento, e por isso nao mede predicado
nenhum: e aqui que cada um se prova.

1. **O canal a religar e so o do proprio tenant, e so em `desligado`.** O `kamba_batch`
   atravessa a RLS, pelo que o `tenant_id = $1` e o isolamento: sem ele, o canal de B
   com o mesmo numero respondia a religacao de A.
2. **A tentativa so reabre de `falhado` ou `abandonado`, com outro `code` e o mesmo
   numero.** E a aresta `→ iniciado` da matriz, e as duas condicoes recusam o que nao e
   religacao: o `code` gasto e o segundo numero no mesmo WABA.
3. **O canal volta a `ativo` so se ainda estiver `desligado`** — um `suspenso` ou um
   `encerrado` sao decisoes nossas, que um popup nao revoga —, e volta a `restrito` se
   a restricao da Meta ainda la estiver (o `motivo_restricao` sobrevive a queda).
4. **A sequencia inteira**, na ordem do modulo: o criterio de integracao do bloco ao
   nivel da base — o mesmo numero do mesmo tenant volta a `ativo`, e o canal e o mesmo.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from tests import factories
from tests.base import ComBase, ConsultaDoTypeScript

RAIZ = Path(__file__).resolve().parents[2]
CONSULTAS = RAIZ / "packages" / "core-ts" / "src" / "onboarding" / "consultas.ts"

SQL_CANAL_A_RELIGAR = ConsultaDoTypeScript("SQL_CANAL_A_RELIGAR", CONSULTAS)
SQL_REABRIR = ConsultaDoTypeScript("SQL_REABRIR", CONSULTAS)
SQL_RELIGAR_CANAL = ConsultaDoTypeScript("SQL_RELIGAR_CANAL", CONSULTAS)
SQL_LIGAR_CANAL = ConsultaDoTypeScript("SQL_LIGAR_CANAL", CONSULTAS)
SQL_TRANSITAR = ConsultaDoTypeScript("SQL_TRANSITAR", CONSULTAS)

#: Os estados de `tenant_channels` de onde **nao** se religa: todos menos o `desligado`.
ESTADOS_QUE_NAO_RELIGAM = ("pendente", "ativo", "restrito", "suspenso", "encerrado")


def _resumo(semente: str) -> bytes:
    return hashlib.sha256(semente.encode("ascii")).digest()


class TestReligacaoDoCanal(ComBase):
    """Uma transaccao do administrador que nunca confirma; o `kamba_batch` por `SET LOCAL ROLE`."""

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()
        self.a = factories.tenant(self.cursor)
        self.b = factories.tenant(self.cursor)
        sufixo = uuid.uuid4().hex[:8]
        self.pnid_a = f"pnid-religa-a-{sufixo}"
        self.pnid_b = f"pnid-religa-b-{sufixo}"
        self.waba_a = f"waba-religa-a-{sufixo}"
        self.canal_a = factories.canal(
            self.cursor, self.a, estado="desligado", phone_number_id=self.pnid_a, waba_id=self.waba_a
        )
        self.canal_b = factories.canal(self.cursor, self.b, estado="desligado", phone_number_id=self.pnid_b)
        factories.contexto(self.cursor, None)

    # ----------------------------------------------------------------- ajudantes

    def como_batch(self) -> None:
        self.cursor.execute("RESET ROLE")
        factories.contexto(self.cursor, None)
        self.cursor.execute("SET LOCAL ROLE kamba_batch")

    def como_admin(self) -> None:
        self.cursor.execute("RESET ROLE")

    def linhas(self, consulta: ConsultaDoTypeScript, *argumentos) -> list[dict]:
        self.cursor.execute(consulta.sql, consulta.args(*argumentos))
        colunas = [d[0] for d in self.cursor.description or []]
        return [dict(zip(colunas, linha)) for linha in self.cursor.fetchall()]

    def canal(self, canal_id: str) -> dict:
        self.cursor.execute(
            "SELECT estado, waba_id, channel_mode, token_ref, tenant_id::text "
            "FROM platform.tenant_channels WHERE id = %s",
            (canal_id,),
        )
        estado, waba, modo, token, tenant = self.cursor.fetchone()
        return {"estado": estado, "waba_id": waba, "channel_mode": modo, "token_ref": token, "tenant_id": tenant}

    def estado_do_canal(self, canal_id: str, estado: str) -> None:
        self.como_admin()
        self.cursor.execute("UPDATE platform.tenant_channels SET estado = %s WHERE id = %s", (estado, canal_id))

    def tentativa(self, fase: str, code: str = "code-original", canal: str | None = None, **troca) -> str:
        """A tentativa original de A, na fase pedida e com o canal de A (as fases do meio exigem-no)."""
        self.como_admin()
        campos = {
            "tenant_id": self.a,
            "waba_id": self.waba_a,
            "phone_number_id": self.pnid_a,
            "code_hash": _resumo(code),
            "fase": fase,
            "channel_id": canal,
        }
        campos.update(troca)
        colunas = ", ".join(campos)
        marcas = ", ".join(["%s"] * len(campos))
        self.cursor.execute(
            f"INSERT INTO platform.channel_onboarding ({colunas}) VALUES ({marcas}) RETURNING id::text",
            tuple(campos.values()),
        )
        return self.cursor.fetchone()[0]

    # ---------------------------------------------------- 1. o canal a religar

    def test_o_canal_a_religar_e_o_desligado_do_proprio_tenant(self) -> None:
        self.como_batch()
        self.assertEqual(
            self.linhas(SQL_CANAL_A_RELIGAR, self.a, self.pnid_a),
            [{"id": self.canal_a, "token_ref": self.canal(self.canal_a)["token_ref"]}],
        )

    def test_o_numero_de_a_pedido_por_b_nao_devolve_nada(self) -> None:
        """O `tenant_id = $1`: o `kamba_batch` ve os dois, e so o predicado os separa."""
        self.como_batch()
        self.assertEqual(self.linhas(SQL_CANAL_A_RELIGAR, self.b, self.pnid_a), [])
        self.assertEqual(self.linhas(SQL_CANAL_A_RELIGAR, self.a, self.pnid_b), [])

    def test_outro_numero_do_mesmo_tenant_nao_e_o_canal_a_religar(self) -> None:
        self.como_batch()
        self.assertEqual(self.linhas(SQL_CANAL_A_RELIGAR, self.a, "pnid-que-nao-existe"), [])

    def test_so_o_desligado_religa(self) -> None:
        for estado in ESTADOS_QUE_NAO_RELIGAM:
            with self.subTest(estado=estado):
                self.estado_do_canal(self.canal_a, estado)
                self.como_batch()
                self.assertEqual(self.linhas(SQL_CANAL_A_RELIGAR, self.a, self.pnid_a), [])

    # -------------------------------------------------------- 2. a tentativa

    def test_a_tentativa_reabre_de_falhado_e_de_abandonado(self) -> None:
        for fase in ("falhado", "abandonado"):
            with self.subTest(fase=fase):
                self.cursor.execute("SAVEPOINT reabrir")
                id_ = self.tentativa(fase)
                self.como_batch()
                reabertas = self.linhas(SQL_REABRIR, self.a, self.waba_a, _resumo("code-novo"), self.pnid_a)
                self.assertEqual(len(reabertas), 1)
                self.assertEqual((reabertas[0]["id"], reabertas[0]["fase"]), (id_, "iniciado"))
                self.assertEqual(reabertas[0]["recursos_criados"], [])
                self.cursor.execute(
                    "SELECT code_hash, pin_ref, motivo FROM platform.channel_onboarding WHERE id = %s", (id_,)
                )
                code_hash, pin_ref, motivo = self.cursor.fetchone()
                self.assertEqual(bytes(code_hash), _resumo("code-novo"))
                self.assertEqual((pin_ref, motivo), (None, None))
                self.como_admin()
                self.cursor.execute("ROLLBACK TO SAVEPOINT reabrir")

    def test_a_tentativa_nao_reabre_das_fases_do_meio_nem_do_ativo(self) -> None:
        """Quem chama leva-a a `falhado` pela matriz; a consulta nao salta por cima dela."""
        for fase in ("iniciado", "es_concluido", "subscrito", "a_sincronizar", "verificado", "pronto", "ativo"):
            with self.subTest(fase=fase):
                self.cursor.execute("SAVEPOINT reabrir")
                self.tentativa(fase, canal=self.canal_a)
                self.como_batch()
                self.assertEqual(self.linhas(SQL_REABRIR, self.a, self.waba_a, _resumo("code-novo"), self.pnid_a), [])
                self.como_admin()
                self.cursor.execute("ROLLBACK TO SAVEPOINT reabrir")

    def test_o_mesmo_code_nao_reabre(self) -> None:
        self.tentativa("falhado")
        self.como_batch()
        self.assertEqual(self.linhas(SQL_REABRIR, self.a, self.waba_a, _resumo("code-original"), self.pnid_a), [])

    def test_outro_numero_no_mesmo_waba_nao_reabre(self) -> None:
        self.tentativa("falhado")
        self.como_batch()
        self.assertEqual(self.linhas(SQL_REABRIR, self.a, self.waba_a, _resumo("code-novo"), self.pnid_b), [])

    def test_a_tentativa_de_a_nao_reabre_pelo_tenant_b(self) -> None:
        self.tentativa("falhado")
        self.como_batch()
        self.assertEqual(self.linhas(SQL_REABRIR, self.b, self.waba_a, _resumo("code-novo"), self.pnid_a), [])

    # ----------------------------------------------------------- 3. o canal volta

    def test_o_canal_volta_a_ativo_com_o_token_o_waba_e_o_modo_novos(self) -> None:
        self.como_batch()
        feitas = self.linhas(
            SQL_RELIGAR_CANAL, "waba-novo-de-ensaio", "cloud_only", "ref-opaca-de-teste/religada", self.canal_a, self.a
        )
        self.assertEqual(feitas, [{"id": self.canal_a}])
        self.assertEqual(
            self.canal(self.canal_a),
            {
                "estado": "ativo",
                "waba_id": "waba-novo-de-ensaio",
                "channel_mode": "cloud_only",
                "token_ref": "ref-opaca-de-teste/religada",
                "tenant_id": self.a,
            },
        )
        # O canal de B, desligado como o de A, fica como estava.
        self.assertEqual(self.canal(self.canal_b)["estado"], "desligado")

    def test_um_canal_restrito_que_caiu_volta_restrito_com_o_motivo(self) -> None:
        """O KAM-017 desliga um `restrito` e o motivo fica; a religacao nao o apaga."""
        self.como_admin()
        self.cursor.execute(
            "UPDATE platform.tenant_channels SET motivo_restricao = 'quality' WHERE id = %s", (self.canal_a,)
        )
        self.como_batch()
        self.assertEqual(
            len(self.linhas(SQL_RELIGAR_CANAL, self.waba_a, "coexistencia", "ref-opaca-de-teste/r", self.canal_a, self.a)), 1
        )
        self.cursor.execute(
            "SELECT estado, motivo_restricao FROM platform.tenant_channels WHERE id = %s", (self.canal_a,)
        )
        self.assertEqual(tuple(self.cursor.fetchone()), ("restrito", "quality"))

    def test_o_canal_de_a_nao_volta_pelo_tenant_b(self) -> None:
        self.como_batch()
        self.assertEqual(
            self.linhas(SQL_RELIGAR_CANAL, "w", "coexistencia", "ref-opaca-de-teste/x", self.canal_a, self.b), []
        )
        self.assertEqual(self.canal(self.canal_a)["estado"], "desligado")

    def test_um_canal_que_nao_esta_desligado_nao_volta(self) -> None:
        for estado in ESTADOS_QUE_NAO_RELIGAM:
            with self.subTest(estado=estado):
                self.estado_do_canal(self.canal_a, estado)
                self.como_batch()
                self.assertEqual(
                    self.linhas(SQL_RELIGAR_CANAL, "w", "coexistencia", "ref-opaca-de-teste/x", self.canal_a, self.a), []
                )
                self.assertEqual(self.canal(self.canal_a)["estado"], estado)

    # ------------------------------------------------------- 4. a sequencia

    def test_integracao_o_mesmo_numero_do_mesmo_tenant_volta_a_ativo(self) -> None:
        """A ordem do `#religar`: canal caido, tentativa por `iniciado`, canal ligado, subscrito, `ativo`."""
        id_ = self.tentativa("subscrito", canal=self.canal_a)
        self.como_batch()
        caido = self.linhas(SQL_CANAL_A_RELIGAR, self.a, self.pnid_a)
        self.assertEqual([c["id"] for c in caido], [self.canal_a])
        # `subscrito → falhado` pela matriz, como o modulo faz antes de reabrir.
        self.assertEqual(len(self.linhas(SQL_TRANSITAR, id_, self.a, "subscrito", "falhado", "canal desligado")), 1)
        reaberta = self.linhas(SQL_REABRIR, self.a, self.waba_a, _resumo("code-da-religacao"), self.pnid_a)
        self.assertEqual([(r["id"], r["fase"]) for r in reaberta], [(id_, "iniciado")])
        self.assertEqual(len(self.linhas(SQL_LIGAR_CANAL, id_, self.a, self.canal_a)), 1)
        self.assertEqual(len(self.linhas(SQL_TRANSITAR, id_, self.a, "es_concluido", "subscrito", None)), 1)
        self.assertEqual(
            len(self.linhas(SQL_RELIGAR_CANAL, self.waba_a, "coexistencia", "ref-opaca-de-teste/nova", self.canal_a, self.a)),
            1,
        )
        self.assertEqual(self.canal(self.canal_a)["estado"], "ativo")
        self.cursor.execute(
            "SELECT fase, channel_id::text FROM platform.channel_onboarding WHERE id = %s", (id_,)
        )
        self.assertEqual(tuple(self.cursor.fetchone()), ("subscrito", self.canal_a))
        # E uma segunda passagem ja nao encontra o canal a religar.
        self.assertEqual(self.linhas(SQL_CANAL_A_RELIGAR, self.a, self.pnid_a), [])
