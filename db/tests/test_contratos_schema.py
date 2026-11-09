"""A revisao 0040 contra a base: o aceite contratual versionado (KAM-090).

As listas fechadas do *gate* 8 afirmam que a revisao **declarou** o que devia;
esta bateria mede que o declarado **morde**, e os casos adversariais do bloco sao
o minimo:

* **aceite de versao antiga** — recusado a entrada (`23514`) e, se for de uma
  versao que deixou de vigorar depois, nao satisfaz o gate;
* **alteracao de texto publicado** — o `UPDATE` da versao e recusado ao dono
  (`55000`), e um aceite que cite outro `sha256` nao tem FK para onde apontar;
* **reutilizacao de `otp_challenge_id` noutro caso** — `23P01`, e **entre
  tenants**, que e o caso real: cada caso tem o seu tenant pre-alocado, pelo que
  a linha do outro caso e invisivel pela RLS;
* **aceite sem abrir os documentos** — **nao e da base**: a prova de abertura e
  um recibo assinado que o servico emite ao servir o texto, e o ensaio esta em
  `packages/core-ts/tests/contratos/aceite.test.ts`.

A `evidence_hash` confronta-se com um oraculo **fora da base** (`hashlib`), e
nao com a funcao que a calcula: duas leituras da mesma formula que concordam nao
apanham o erro que as duas tenham.
"""

from __future__ import annotations

import hashlib
import struct
import uuid
from datetime import datetime, timezone

from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    TABELAS,
    TABELAS_ATE_0039,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    ComBase,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

DOCUMENTOS = "platform.contract_document"
ACEITES = "platform.contract_acceptance"

#: `exclusion_violation`: o OTP de um caso usado noutro.
VIOLACAO_DE_EXCLUSAO = "23P01"
#: `object_not_in_prerequisite_state`: a versao publicada nao se altera.
ESTADO_PROIBIDO = "55000"

TIPOS = ("dpa", "privacidade", "subprocessadores", "tos")

_EPOCA = datetime(1970, 1, 1, tzinfo=timezone.utc)

#: O mesmo vetor de `packages/core-ts/tests/contratos.test.ts`.
VETOR_DA_EVIDENCIA = "4936cf07cef2053dda27d129a3540eaa22f4bf4907e349ddd3464ec373b9646c"


def evidencia_esperada(doc_sha256: bytes, signatario: str, aceite_em: datetime,
                       otp: str) -> bytes:
    """A formula do criterio 3, escrita aqui sem olhar para a base."""
    delta = aceite_em - _EPOCA
    micros = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
    return hashlib.sha256(
        doc_sha256
        + uuid.UUID(signatario).bytes
        + struct.pack(">q", micros)
        + uuid.UUID(otp).bytes
    ).digest()


def publicar(cursor, tipo: str, versao: str, *, conteudo: str | None = None,
             ha_horas: int = 1) -> tuple[str, bytes]:
    """Publica uma versao vigente ha `ha_horas` e devolve `(document_id, sha256)`.

    O `publicado_em` vai explicito e igual a vigencia: o `sem_retroactivo` exige
    `vigente_desde >= publicado_em`, e um ensaio que precisa de duas versoes em
    sequencia dentro da mesma transaccao (o `now()` nao anda) tem de as datar.
    """
    texto = conteudo if conteudo is not None else f"{tipo} {versao} [A CONFIRMAR POR PARECER]\n"
    cursor.execute(
        f"""
        INSERT INTO {DOCUMENTOS}
               (tipo, versao, sha256, conteudo, vigente_desde, publicado_em)
        VALUES (%s, %s, sha256(convert_to(%s, 'UTF8')), %s,
                now() - make_interval(hours => %s),
                now() - make_interval(hours => %s))
        RETURNING document_id, sha256
        """,
        (tipo, versao, texto, texto, ha_horas, ha_horas),
    )
    document_id, sha = cursor.fetchone()
    return str(document_id), bytes(sha)


def aceitar(cursor, *, onboarding: str, tenant: str, document_id: str, versao: str,
            sha: bytes, otp: str | None = None, signatario: str | None = None):
    cursor.execute(
        f"""
        INSERT INTO {ACEITES}
               (onboarding_id, tenant_id, document_id, versao, doc_sha256,
                signatario_ref, otp_challenge_id, aceite_em, evidence_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s, '2001-01-01T00:00:00Z', '\\x00'::bytea)
        ON CONFLICT ON CONSTRAINT contract_acceptance_aceite_uq DO NOTHING
        RETURNING id
        """,
        (onboarding, tenant, document_id, versao, sha,
         signatario or str(uuid.uuid4()), otp or str(uuid.uuid4())),
    )
    linha = cursor.fetchone()
    return None if linha is None else str(linha[0])


class TestOTextoPublicado(ComBase):
    """Criterio 1: versao SemVer, `sha256` do conteudo canonico, imutavel."""

    def test_o_sha256_e_o_do_conteudo_e_a_base_confere_o(self) -> None:
        cursor = self.ligar("admin").cursor()
        _, sha = publicar(cursor, "dpa", "7.0.0", conteudo="Texto do DPA.\n")
        self.assertEqual(sha, hashlib.sha256("Texto do DPA.\n".encode()).digest())
        self.assertErroSql(
            VIOLACAO_DE_CHECK, cursor,
            f"INSERT INTO {DOCUMENTOS} (tipo, versao, sha256, conteudo, vigente_desde) "
            "VALUES ('dpa', '7.0.1', sha256('outro'::bytea), 'Texto.', now())",
        )

    def test_conteudo_nao_canonico_versao_e_tipo_fora_do_dominio(self) -> None:
        cursor = self.ligar("admin").cursor()
        casos = (
            ("dpa", "7.1.0", "linha\r\noutra\n"),
            ("dpa", "v7.2", "texto\n"),
            ("dpa", "7.3.0-rc1", "texto\n"),
            ("cookies", "7.4.0", "texto\n"),
        )
        for tipo, versao, texto in casos:
            with self.subTest(tipo=tipo, versao=versao):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, cursor,
                    f"INSERT INTO {DOCUMENTOS} (tipo, versao, sha256, conteudo, "
                    "vigente_desde) VALUES (%s, %s, sha256(convert_to(%s, 'UTF8')), "
                    "%s, now())",
                    (tipo, versao, texto, texto),
                )

    def test_alterar_o_texto_publicado_e_recusado_ao_dono(self) -> None:
        cursor = self.ligar("admin").cursor()
        document_id, _ = publicar(cursor, "tos", "7.0.0")
        for coluna, valor in (("conteudo", "'outro texto\n'"), ("versao", "'7.0.9'"),
                              ("vigente_desde", "now()")):
            with self.subTest(coluna=coluna):
                self.assertErroSql(
                    ESTADO_PROIBIDO, cursor,
                    f"UPDATE {DOCUMENTOS} SET {coluna} = {valor} WHERE document_id = %s",
                    (document_id,),
                )

    def test_uma_versao_nao_vigora_antes_de_ser_publicada(self) -> None:
        cursor = self.ligar("admin").cursor()
        self.assertErroSql(
            VIOLACAO_DE_CHECK, cursor,
            f"INSERT INTO {DOCUMENTOS} (tipo, versao, sha256, conteudo, vigente_desde) "
            "VALUES ('dpa', '7.5.0', sha256(convert_to('x', 'UTF8')), 'x', "
            "now() - interval '1 day')",
        )

    def test_a_aplicacao_nao_publica_e_ninguem_apaga(self) -> None:
        app = self.ligar("app").cursor()
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, app,
            f"INSERT INTO {DOCUMENTOS} (tipo, versao, sha256, conteudo, vigente_desde) "
            "VALUES ('dpa', '7.6.0', sha256(convert_to('x', 'UTF8')), 'x', now())",
        )
        for identidade in ("app", "batch", "audit"):
            with self.subTest(identidade=identidade):
                cursor = self.ligar(identidade).cursor()
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, cursor, f"DELETE FROM {DOCUMENTOS}"
                )


class TestAEvidenciaInstalada(ComBase):
    """A funcao da base contra o vetor fixo que o TypeScript tambem confronta."""

    def test_o_vetor_fixo(self) -> None:
        signatario = "11111111-2222-4333-8444-555555555555"
        otp = "66666666-7777-4888-9999-aaaaaaaaaaaa"
        cursor = self.ligar("admin").cursor()
        cursor.execute(
            "SELECT platform.contrato_evidencia(%s, %s, "
            "to_timestamp(1762689600) + interval '123456 microseconds', %s)",
            (bytes(range(32)), signatario, otp),
        )
        obtido = bytes(cursor.fetchone()[0]).hex()
        self.assertEqual(obtido, VETOR_DA_EVIDENCIA)
        self.assertEqual(
            obtido,
            evidencia_esperada(
                bytes(range(32)), signatario,
                datetime(2025, 11, 9, 12, 0, 0, 123456, tzinfo=timezone.utc), otp,
            ).hex(),
        )


class TestOAceite(ComBase):
    """Criterios 3 e 5, e tres dos quatro casos adversariais."""

    def contexto(self):
        """Uma ligacao da aplicacao no contexto de um tenant pre-alocado, e as
        quatro versoes vigentes publicadas pelo administrador **noutra** ligacao.

        As versoes publicam-se pela ligacao da aplicacao? Nao: ela nao tem
        `INSERT`. E uma ligacao de administrador nao confirma (`ComBase`), pelo
        que a aplicacao nao veria o que ela publicasse. Por isso o
        administrador faz as duas coisas aqui, e a aplicacao so entra nos
        ensaios de privilegio e de isolamento.
        """
        cursor = self.ligar("admin").cursor()
        tenant = str(uuid.uuid4())
        documentos = {tipo: publicar(cursor, tipo, "9.0.0") for tipo in TIPOS}
        return cursor, tenant, documentos

    def test_a_base_escreve_a_hora_e_a_evidencia_e_ignora_as_do_chamador(self) -> None:
        cursor, tenant, documentos = self.contexto()
        document_id, sha = documentos["dpa"]
        signatario, otp = str(uuid.uuid4()), str(uuid.uuid4())
        aceite = aceitar(cursor, onboarding=tenant, tenant=tenant,
                         document_id=document_id, versao="9.0.0", sha=sha,
                         otp=otp, signatario=signatario)
        cursor.execute(
            f"SELECT aceite_em, evidence_hash, now() FROM {ACEITES} WHERE id = %s",
            (aceite,),
        )
        aceite_em, evidencia, agora = cursor.fetchone()
        self.assertEqual(aceite_em, agora)
        self.assertEqual(bytes(evidencia),
                         evidencia_esperada(sha, signatario, aceite_em, otp))

    def test_aceite_de_versao_antiga_e_recusado(self) -> None:
        cursor, tenant, documentos = self.contexto()
        antiga, sha_antiga = publicar(cursor, "dpa", "8.0.0", ha_horas=5)
        self.assertErroSql(
            VIOLACAO_DE_CHECK, cursor,
            f"INSERT INTO {ACEITES} (onboarding_id, tenant_id, document_id, versao, "
            "doc_sha256, signatario_ref, otp_challenge_id, evidence_hash) "
            "VALUES (%s, %s, %s, '8.0.0', %s, %s, %s, '\\x00'::bytea)",
            (tenant, tenant, antiga, sha_antiga, str(uuid.uuid4()), str(uuid.uuid4())),
        )

    def test_aceite_que_cita_outro_texto_nao_tem_fk(self) -> None:
        cursor, tenant, documentos = self.contexto()
        document_id, _ = documentos["tos"]
        adulterado = hashlib.sha256(b"texto que o cliente mostrou").digest()
        self.assertErroSql(
            VIOLACAO_DE_FK, cursor,
            f"INSERT INTO {ACEITES} (onboarding_id, tenant_id, document_id, versao, "
            "doc_sha256, signatario_ref, otp_challenge_id, evidence_hash) "
            "VALUES (%s, %s, %s, '9.0.0', %s, %s, %s, '\\x00'::bytea)",
            (tenant, tenant, document_id, adulterado, str(uuid.uuid4()), str(uuid.uuid4())),
        )

    def test_o_mesmo_aceite_repetido_e_uma_linha(self) -> None:
        cursor, tenant, documentos = self.contexto()
        document_id, sha = documentos["privacidade"]
        primeiro = aceitar(cursor, onboarding=tenant, tenant=tenant,
                           document_id=document_id, versao="9.0.0", sha=sha)
        segundo = aceitar(cursor, onboarding=tenant, tenant=tenant,
                          document_id=document_id, versao="9.0.0", sha=sha)
        self.assertIsNotNone(primeiro)
        self.assertIsNone(segundo)
        cursor.execute(f"SELECT count(*) FROM {ACEITES} WHERE onboarding_id = %s",
                       (tenant,))
        self.assertEqual(cursor.fetchone()[0], 1)

    def test_o_otp_de_um_caso_nao_serve_noutro_caso(self) -> None:
        """Os quatro documentos do mesmo caso partilham o OTP; outro caso nao."""
        cursor, tenant, documentos = self.contexto()
        otp = str(uuid.uuid4())
        for tipo in TIPOS:
            document_id, sha = documentos[tipo]
            aceitar(cursor, onboarding=tenant, tenant=tenant, document_id=document_id,
                    versao="9.0.0", sha=sha, otp=otp)
        outro = str(uuid.uuid4())
        document_id, sha = documentos["dpa"]
        self.assertErroSql(
            VIOLACAO_DE_EXCLUSAO, cursor,
            f"INSERT INTO {ACEITES} (onboarding_id, tenant_id, document_id, versao, "
            "doc_sha256, signatario_ref, otp_challenge_id, evidence_hash) "
            "VALUES (%s, %s, %s, '9.0.0', %s, %s, %s, '\\x00'::bytea)",
            (outro, outro, document_id, sha, str(uuid.uuid4()), otp),
        )

    def test_a_aplicacao_escreve_no_seu_tenant_e_nao_ve_o_dos_outros(self) -> None:
        """A RLS e o OTP entre tenants, pela ligacao que escreve em producao.

        A aplicacao nao ve o que uma ligacao do `ComBase` publique, porque essas
        nunca confirmam. Por isso o DPA deste ensaio publica-se por uma ligacao
        de administrador **em autocommit**, e apaga-se no fim: a linha de aceite
        que o referencia e da ligacao da aplicacao, que desfaz tudo, pelo que no
        `cleanup` ja nao ha FK a prende-lo.
        """
        import ligacao

        publicador = ligacao.ligar("admin")
        publicador.autocommit = True
        self.addCleanup(publicador.close)
        cursor = publicador.cursor()
        versao = f"77.{uuid.uuid4().int % 100000}.0"
        texto = f"DPA de ensaio {versao} [A CONFIRMAR POR PARECER]\n"
        cursor.execute(
            f"INSERT INTO {DOCUMENTOS} (tipo, versao, sha256, conteudo, vigente_desde) "
            "VALUES ('dpa', %s, sha256(convert_to(%s, 'UTF8')), %s, now()) "
            "RETURNING document_id, sha256",
            (versao, texto, texto),
        )
        document_id, sha = cursor.fetchone()
        document_id, sha = str(document_id), bytes(sha)
        self.addCleanup(
            cursor.execute, f"DELETE FROM {DOCUMENTOS} WHERE document_id = %s",
            (document_id,),
        )

        app = self.ligar("app").cursor()
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        otp = str(uuid.uuid4())
        factories.contexto(app, a)
        aceitar(app, onboarding=a, tenant=a, document_id=document_id, versao=versao,
                sha=sha, otp=otp)
        factories.contexto(app, b)
        app.execute(f"SELECT count(*) FROM {ACEITES} WHERE tenant_id = %s", (a,))
        self.assertEqual(app.fetchone()[0], 0)
        self.assertErroSql(
            VIOLACAO_DE_EXCLUSAO, app,
            f"INSERT INTO {ACEITES} (onboarding_id, tenant_id, document_id, versao, "
            "doc_sha256, signatario_ref, otp_challenge_id, evidence_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, '\\x00'::bytea)",
            (b, b, document_id, versao, sha, str(uuid.uuid4()), otp),
        )
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, app,
            f"INSERT INTO {ACEITES} (onboarding_id, tenant_id, document_id, versao, "
            "doc_sha256, signatario_ref, otp_challenge_id, evidence_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, '\\x00'::bytea)",
            (a, a, document_id, versao, sha, str(uuid.uuid4()), str(uuid.uuid4())),
        )

    def test_ninguem_emenda_nem_apaga_um_aceite(self) -> None:
        for identidade in ("app", "batch", "audit"):
            cursor = self.ligar(identidade).cursor()
            for instrucao in (f"UPDATE {ACEITES} SET versao = '0.0.0'",
                              f"DELETE FROM {ACEITES}"):
                with self.subTest(identidade=identidade, instrucao=instrucao):
                    self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, instrucao)


class TestOGateDeActivacao(ComBase):
    """Criterio 4: `tenant sem DPA aceite nao activa`, e o criterio 8."""

    def tenant(self, cursor) -> str:
        return factories.tenant(cursor)

    def activar(self, cursor, tenant: str) -> None:
        cursor.execute("UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s",
                       (tenant,))

    def assertRecusa(self, cursor, tenant: str, em_falta: str) -> None:
        import pg8000.dbapi

        cursor.execute("SAVEPOINT activar")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                self.activar(cursor, tenant)
        finally:
            cursor.execute("ROLLBACK TO SAVEPOINT activar")
        erro = capturado.exception.args[0]
        self.assertEqual(erro.get("C"), VIOLACAO_DE_CHECK)
        self.assertEqual(erro.get("M"), "tenant sem DPA aceite nao activa")
        self.assertEqual(erro.get("D"), f"sem aceite: {em_falta}")

    def test_sem_aceite_nenhum_nao_activa(self) -> None:
        cursor = self.ligar("admin").cursor()
        tenant = self.tenant(cursor)
        for tipo in TIPOS:
            publicar(cursor, tipo, "9.1.0")
        self.assertRecusa(cursor, tenant, "dpa, privacidade, subprocessadores, tos")

    def test_com_as_quatro_vigentes_activa(self) -> None:
        cursor = self.ligar("admin").cursor()
        tenant = self.tenant(cursor)
        factories.aceitar_contratos_vigentes(cursor, tenant)
        self.activar(cursor, tenant)
        cursor.execute("SELECT estado FROM platform.tenants WHERE id = %s", (tenant,))
        self.assertEqual(cursor.fetchone()[0], "ativo")

    def test_falta_a_lista_de_subprocessadores(self) -> None:
        cursor = self.ligar("admin").cursor()
        tenant = self.tenant(cursor)
        documentos = {tipo: publicar(cursor, tipo, "9.2.0") for tipo in TIPOS}
        for tipo in ("dpa", "privacidade", "tos"):
            document_id, sha = documentos[tipo]
            aceitar(cursor, onboarding=tenant, tenant=tenant, document_id=document_id,
                    versao="9.2.0", sha=sha)
        self.assertRecusa(cursor, tenant, "subprocessadores")

    def test_um_aceite_de_versao_que_deixou_de_vigorar_nao_satisfaz(self) -> None:
        cursor = self.ligar("admin").cursor()
        tenant = self.tenant(cursor)
        for tipo in TIPOS:
            publicar(cursor, tipo, "9.3.0", ha_horas=3)
        factories.aceitar_contratos_vigentes(cursor, tenant)
        publicar(cursor, "dpa", "9.4.0", ha_horas=2)
        self.assertRecusa(cursor, tenant, "dpa")

    def test_nascer_ativo_tambem_passa_pelo_gate(self) -> None:
        cursor = self.ligar("admin").cursor()
        for tipo in TIPOS:
            publicar(cursor, tipo, "9.5.0")
        novo = str(uuid.uuid4())
        factories.contexto(cursor, novo)
        self.assertErroSql(
            VIOLACAO_DE_CHECK, cursor,
            "INSERT INTO platform.tenants (id, tipo, nome, estado) "
            "VALUES (%s, 'pme', 'Loja de ensaio', 'ativo')",
            (novo,),
        )

    def test_onboarding_restrito_ativo_nao_contorna_o_gate(self) -> None:
        cursor = self.ligar("admin").cursor()
        tenant = self.tenant(cursor)
        for tipo in TIPOS:
            publicar(cursor, tipo, "9.6.0")
        cursor.execute("UPDATE platform.tenants SET estado = 'restrito' WHERE id = %s",
                       (tenant,))
        self.assertRecusa(cursor, tenant, "dpa, privacidade, subprocessadores, tos")

    def test_uma_versao_nova_nao_bloqueia_a_reactivacao_de_um_tenant_existente(self) -> None:
        """«Por omissao so bloqueia activacoes novas» (criterio 6)."""
        cursor = self.ligar("admin").cursor()
        tenant = self.tenant(cursor)
        for tipo in TIPOS:
            publicar(cursor, tipo, "9.7.0", ha_horas=3)
        factories.aceitar_contratos_vigentes(cursor, tenant)
        self.activar(cursor, tenant)
        cursor.execute("UPDATE platform.tenants SET estado = 'suspenso' WHERE id = %s",
                       (tenant,))
        publicar(cursor, "dpa", "9.8.0", ha_horas=2)
        self.activar(cursor, tenant)
        cursor.execute("SELECT * FROM platform.dpa_em_falta() WHERE tenant_id = %s",
                       (tenant,))
        self.assertEqual([tuple(l) for l in cursor.fetchall()],
                         [(uuid.UUID(tenant), ["dpa"])])

    def test_o_lote_activa_como_invocador_e_sem_aceite_e_recusado(self) -> None:
        """Quem muda o estado e o `kamba_batch`, e o gate corre com os olhos dele."""
        cursor = self.ligar("batch").cursor()
        tenant = self.tenant(cursor)
        self.assertErroSql(
            VIOLACAO_DE_CHECK, cursor,
            "UPDATE platform.tenants SET estado = 'ativo' WHERE id = %s", (tenant,),
        )

    def test_a_aplicacao_nao_le_a_verificacao_diaria(self) -> None:
        cursor = self.ligar("app").cursor()
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor,
                           "SELECT * FROM platform.dpa_em_falta()")


class TestDowngradeDa0040(ComBase):
    """A `0040` desce e volta, e o gate desaparece com ela."""

    def tearDown(self) -> None:
        super().tearDown()
        if not em_head():
            alembic_ok("upgrade", "head")

    def test_desce_e_sobe(self) -> None:
        exigir_base_descartavel()
        alembic_ok("downgrade", "0039")
        presentes = {
            nome
            for (nome,) in self.consultar(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'platform'"
            )
        }
        self.assertEqual(presentes, set(TABELAS_ATE_0039))
        gatilhos = self.consultar(
            "SELECT count(*) FROM pg_trigger WHERE tgname = 'tenants_exige_aceite'"
        )
        self.assertEqual(gatilhos, [(0,)])
        funcoes = self.consultar(
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid = p.pronamespace WHERE n.nspname = 'platform' "
            "AND p.proname IN ('contrato_evidencia', 'contrato_em_falta', "
            "'dpa_em_falta', 'tenants_exige_aceite', 'contract_document_imutavel', "
            "'contract_acceptance_preparar')"
        )
        self.assertEqual(funcoes, [(0,)])
        alembic_ok("upgrade", "head")
        presentes = {
            nome
            for (nome,) in self.consultar(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'platform'"
            )
        }
        self.assertEqual(presentes, set(TABELAS))
