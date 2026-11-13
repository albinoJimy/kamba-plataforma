"""A revisao da Foto de produtos contra a base: platform.image_jobs (KAM-120).

O que so uma base prova, e por isso este ficheiro existe:

1. **A maquina do *trigger***: o `CHECK` do estado contra os cinco estados do
   bloco, e as 25 combinacoes de transicao contra a tabela escrita **aqui**, por
   extenso — e nao importada de `kamba_core.foto.estados`: um oraculo importado
   do alvo fica verde com a constante trocada. Cada recusa e medida pela
   mensagem do *trigger*, porque um `CHECK` de linha da o mesmo `23514` e
   esconderia uma transicao que o *trigger* deixou passar.
2. **O que o *trigger* congela**: um `falhado` nao muda, um `concluido` so muda a
   `escolhida`, o `custo_usd` nao desce, e a `versao` sobe a cada escrita sem
   que o `kamba_app` a possa escrever.
3. **As restricoes de linha**: o `motivo` amarrado ao estado, o `gerado_por_ia`
   gerado da operacao, a `escolhida` so num `concluido`, as chaves do STO presas
   ao tenant da linha, e a idempotencia por `(tenant_id, idempotency_key)`.
4. **Privilegios e RLS `FORCE`**: o `kamba_app` nao apaga, nao muda a
   identidade do pedido, nao le nem escreve outro tenant, e sem contexto nao ve
   nada.
5. **A finalidade `imagem`** no dominio de `tenant_destinations.purpose`.
6. **O `downgrade`**, para a revisao de baixo lida do proprio ficheiro: com um
   destino `imagem` registado, recusa e a base fica como estava; sem ele, a
   tabela desaparece e o dominio volta as treze.

A revisao encontra-se pelo *glob* `*_foto_de_produtos.py` e nunca pelo numero,
que e provisorio.
"""

from __future__ import annotations

import ast
import itertools
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

import bootstrap
import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
    sqlstate,
)

RAIZ = Path(__file__).resolve().parents[2]
TABELA = "platform.image_jobs"
DESTINOS = "platform.tenant_destinations"
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_foto_de_produtos.py"))

#: Os cinco estados do bloco (`docs/tecnica/03` §17).
ESTADOS = ("pendente", "a_processar", "concluido", "bloqueada_gate", "falhado")

#: A tabela de transicoes, **por extenso e nao importada**. O `concluido` e o
#: `falhado` sao finais.
TRANSICOES: dict[str, frozenset[str]] = {
    "pendente": frozenset({"a_processar", "bloqueada_gate", "falhado"}),
    "a_processar": frozenset({"concluido", "bloqueada_gate", "falhado"}),
    "bloqueada_gate": frozenset({"a_processar", "falhado"}),
    "concluido": frozenset(),
    "falhado": frozenset(),
}

OPERACOES = ("cutout", "fundo_simples", "luz_basica", "variacao_lifestyle")
MOTIVOS_DO_BLOQUEIO = ("sem_destino", "so_sinteticas", "sem_carta", "minimizacao")
MOTIVOS_DA_FALHA = ("dados_pessoais", "formato", "fornecedor", "resultado_invalido")

#: As catorze finalidades na cabeca, e as treze da `0036` a que o `downgrade`
#: volta. Por extenso, pela razao da `TRANSICOES`.
FINALIDADES_DA_0036 = (
    "alojamento", "canal", "conversa", "copias_de_seguranca", "embeddings",
    "entrega_de_conteudo", "facturacao", "observabilidade",
    "otp_e_avisos_de_servico", "pagamentos", "segredos", "transcricao", "visao",
)
FINALIDADES = tuple(sorted((*FINALIDADES_DA_0036, "imagem")))

#: As mensagens do *trigger*: cada recusa diz qual das quatro regras a deu.
FINAL = "falhado e final"
SO_A_ESCOLHA = "so a escolha do dono muda"
CUSTO = "custo_usd nao desce"
TRANSICAO = "transicao de image_jobs recusada"

#: O SQLSTATE de escrever numa coluna gerada (`generated_always`).
COLUNA_GERADA = "428C9"


def _literal(nome: str) -> str:
    """O `revision` ou o `down_revision` da revisao, lidos do ficheiro."""
    arvore = ast.parse(REVISAO.read_text(encoding="utf-8"))
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(getattr(t, "id", None) == nome for t in no.targets):
            return ast.literal_eval(no.value)
    raise AssertionError(f"{nome} nao encontrado em {REVISAO.name}")


def _origem(tenant_id: str) -> str:
    return f"t/{tenant_id}/catalogo/2026/11/{uuid.uuid4()}"


def _colunas_para(estado: str, tenant_id: str) -> dict[str, object]:
    """O que uma linha precisa para satisfazer os `CHECK` de um estado.

    **Deterministico por tenant**: a mesma linha reescrita para o mesmo estado
    nao muda coluna nenhuma, e um `concluido -> concluido` mede so o estado.
    """
    if estado == "bloqueada_gate":
        return {"motivo": "sem_destino", "versao_ref": None, "latencia_ms": None}
    if estado == "falhado":
        return {"motivo": "fornecedor", "versao_ref": None, "latencia_ms": None}
    if estado == "concluido":
        return {"motivo": None, "versao_ref": f"t/{tenant_id}/foto/v1", "latencia_ms": 1200}
    return {"motivo": None, "versao_ref": None, "latencia_ms": None}


def inserir(cursor, tenant_id: str, estado: str = "pendente", **campos) -> str:
    """Um trabalho pela ligacao de quem chama. Devolve o `image_job_id`."""
    valores: dict[str, object] = {
        "tenant_id": tenant_id,
        "origem_ref": _origem(tenant_id),
        "operacao": "cutout",
        "provider": "photoroom",
        "idempotency_key": uuid.uuid4().hex,
        "estado": estado,
    }
    valores.update(_colunas_para(estado, tenant_id))
    valores.update(campos)
    colunas = ", ".join(valores)
    marcadores = ", ".join(["%s"] * len(valores))
    cursor.execute(
        f"INSERT INTO {TABELA} ({colunas}) VALUES ({marcadores}) RETURNING image_job_id::text",
        tuple(valores.values()),
    )
    return cursor.fetchone()[0]


class _ComRecusa(ComBase):
    def assertRecusaDoGatilho(self, texto: str, cursor, sql: str, parametros: tuple = ()) -> None:
        """`23514` **e** a mensagem da regra: um `CHECK` de linha da o mesmo codigo."""
        import pg8000.dbapi

        cursor.execute("SAVEPOINT recusa")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                cursor.execute(sql, parametros)
        finally:
            cursor.execute("ROLLBACK TO SAVEPOINT recusa")
        self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK, str(capturado.exception))
        self.assertIn(texto, str(capturado.exception))


class TestMaquina(_ComRecusa):
    def test_o_dominio_do_estado_sao_os_cinco_estados(self) -> None:
        [(definicao,)] = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'image_jobs_estado_ck'"
        )
        for estado in ESTADOS:
            self.assertIn(f"'{estado}'", definicao)
        self.assertEqual(definicao.count("'::text"), len(ESTADOS))

    def test_a_maquina_do_trigger_nas_25_combinacoes(self) -> None:
        """Permitida se esta na tabela, ou se o estado nao muda e nao e `falhado`.

        O mesmo estado nao e transicao: o *trigger* so consulta a tabela quando
        o `estado` muda. O `falhado` congela a linha inteira, e por isso nem a
        reescrita do mesmo estado passa.
        """
        admin = self.ligar("admin").cursor()
        tenant = factories.tenant(admin)
        for de, para in itertools.product(ESTADOS, repeat=2):
            with self.subTest(de=de, para=para):
                linha = inserir(admin, tenant, de)
                colunas = _colunas_para(para, tenant)
                definir = ", ".join(f"{c} = %s" for c in colunas)
                sql = f"UPDATE {TABELA} SET estado = %s, {definir} WHERE image_job_id = %s"
                parametros = (para, *colunas.values(), linha)
                permitida = para in TRANSICOES[de] or (de == para and de != "falhado")
                if permitida:
                    admin.execute(sql, parametros)
                    self.assertEqual(admin.rowcount, 1)
                else:
                    texto = FINAL if de == "falhado" else SO_A_ESCOLHA if de == "concluido" else TRANSICAO
                    self.assertRecusaDoGatilho(texto, admin, sql, parametros)

    def test_um_falhado_nao_muda(self) -> None:
        admin = self.ligar("admin").cursor()
        linha = inserir(admin, factories.tenant(admin), "falhado")
        for coluna, valor in (
            ("provider", "'outro'"),
            ("latencia_ms", "10"),
            ("custo_usd", "1"),
            ("motivo", "'formato'"),
        ):
            with self.subTest(coluna=coluna):
                self.assertRecusaDoGatilho(
                    FINAL, admin, f"UPDATE {TABELA} SET {coluna} = {valor} WHERE image_job_id = %s", (linha,)
                )

    def test_um_concluido_so_muda_a_escolha(self) -> None:
        admin = self.ligar("admin").cursor()
        tenant = factories.tenant(admin)
        linha = inserir(admin, tenant, "concluido", custo_usd=Decimal("0.018"))
        for coluna, valor in (
            ("versao_ref", f"'t/{tenant}/foto/v2'"),
            ("provider", "'outro'"),
            ("custo_usd", "0.036"),
            ("latencia_ms", "900"),
        ):
            with self.subTest(coluna=coluna):
                self.assertRecusaDoGatilho(
                    SO_A_ESCOLHA, admin,
                    f"UPDATE {TABELA} SET {coluna} = {valor} WHERE image_job_id = %s", (linha,),
                )
        admin.execute(f"UPDATE {TABELA} SET escolhida = true WHERE image_job_id = %s RETURNING escolhida", (linha,))
        self.assertEqual(admin.fetchone()[0], True)
        admin.execute(f"UPDATE {TABELA} SET escolhida = false WHERE image_job_id = %s RETURNING escolhida", (linha,))
        self.assertEqual(admin.fetchone()[0], False)

    def test_o_custo_nao_desce(self) -> None:
        admin = self.ligar("admin").cursor()
        linha = inserir(admin, factories.tenant(admin), "a_processar", custo_usd=Decimal("0.018"))
        self.assertRecusaDoGatilho(
            CUSTO, admin, f"UPDATE {TABELA} SET custo_usd = 0.010 WHERE image_job_id = %s", (linha,)
        )
        admin.execute(f"UPDATE {TABELA} SET custo_usd = 0.036 WHERE image_job_id = %s RETURNING custo_usd", (linha,))
        self.assertEqual(admin.fetchone()[0], Decimal("0.036000"))

    def test_a_versao_e_o_atualizado_at_sao_do_gatilho(self) -> None:
        admin = self.ligar("admin")
        tenant = factories.tenant(admin.cursor())
        linha = inserir(admin.cursor(), tenant)
        admin.commit()
        app = self.ligar("app").cursor()
        factories.contexto(app, tenant)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                           f"UPDATE {TABELA} SET versao = 0 WHERE image_job_id = %s", (linha,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                           f"UPDATE {TABELA} SET atualizado_at = now() WHERE image_job_id = %s", (linha,))
        app.execute(f"UPDATE {TABELA} SET provider = 'a' || 'b' WHERE image_job_id = %s RETURNING versao", (linha,))
        self.assertEqual(app.fetchone()[0], 1)
        app.execute(f"UPDATE {TABELA} SET estado = 'a_processar' WHERE image_job_id = %s RETURNING versao", (linha,))
        self.assertEqual(app.fetchone()[0], 2)
        # Nem quem tem o privilegio a impoe: o *trigger* escreve `OLD.versao + 1`
        # por cima do que vier. Noutra linha, porque a de cima esta presa pela
        # transaccao da aplicacao, que nunca confirma.
        dono = admin.cursor()
        outra = inserir(dono, tenant)
        dono.execute(f"UPDATE {TABELA} SET versao = 99 WHERE image_job_id = %s RETURNING versao", (outra,))
        self.assertEqual(dono.fetchone()[0], 1)


class TestRestricoes(ComBase):
    def test_o_motivo_anda_com_o_estado(self) -> None:
        admin = self.ligar("admin").cursor()
        a = factories.tenant(admin)
        for motivo in MOTIVOS_DO_BLOQUEIO:
            with self.subTest(estado="bloqueada_gate", motivo=motivo):
                inserir(admin, a, "bloqueada_gate", motivo=motivo)
        for motivo in MOTIVOS_DA_FALHA:
            with self.subTest(estado="falhado", motivo=motivo):
                inserir(admin, a, "falhado", motivo=motivo)
        for estado, motivo in (
            ("pendente", "sem_destino"),
            ("a_processar", "fornecedor"),
            ("concluido", "formato"),
            ("bloqueada_gate", "fornecedor"),
            ("falhado", "sem_carta"),
            ("bloqueada_gate", "inventado"),
        ):
            with self.subTest(estado=estado, motivo=motivo):
                colunas = {**_colunas_para(estado, a), "motivo": motivo}
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, admin,
                    f"INSERT INTO {TABELA} (tenant_id, origem_ref, operacao, provider, "
                    f"idempotency_key, estado, {', '.join(colunas)}) "
                    f"VALUES (%s, %s, 'cutout', 'photoroom', %s, %s, {', '.join(['%s'] * len(colunas))})",
                    (a, _origem(a), uuid.uuid4().hex, estado, *colunas.values()),
                )

    def test_um_bloqueio_ou_uma_falha_sem_motivo_e_recusado(self) -> None:
        """O dono precisa de saber porque parou: o `bloqueada_gate` e o `falhado` levam motivo."""
        admin = self.ligar("admin").cursor()
        a = factories.tenant(admin)
        for estado in ("bloqueada_gate", "falhado"):
            with self.subTest(estado=estado):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, admin,
                    f"INSERT INTO {TABELA} (tenant_id, origem_ref, operacao, provider, "
                    "idempotency_key, estado, motivo) VALUES (%s, %s, 'cutout', 'photoroom', %s, %s, NULL)",
                    (a, _origem(a), uuid.uuid4().hex, estado),
                )

    def test_gerado_por_ia_e_gerado_da_operacao(self) -> None:
        admin = self.ligar("admin").cursor()
        a = factories.tenant(admin)
        for operacao in OPERACOES:
            with self.subTest(operacao=operacao):
                linha = inserir(admin, a, operacao=operacao)
                admin.execute(f"SELECT gerado_por_ia FROM {TABELA} WHERE image_job_id = %s", (linha,))
                self.assertEqual(admin.fetchone()[0], operacao == "variacao_lifestyle")
        self.assertErroSql(
            COLUNA_GERADA, admin,
            f"INSERT INTO {TABELA} (tenant_id, origem_ref, operacao, provider, idempotency_key, gerado_por_ia) "
            "VALUES (%s, %s, 'variacao_lifestyle', 'photoroom', %s, false)",
            (a, _origem(a), uuid.uuid4().hex),
        )
        linha = inserir(admin, a, operacao="variacao_lifestyle")
        self.assertErroSql(
            COLUNA_GERADA, admin,
            f"UPDATE {TABELA} SET gerado_por_ia = false WHERE image_job_id = %s", (linha,),
        )

    def test_so_um_concluido_se_escolhe(self) -> None:
        admin = self.ligar("admin").cursor()
        a = factories.tenant(admin)
        inserir(admin, a, "concluido", escolhida=True)
        for estado in ("pendente", "a_processar", "bloqueada_gate", "falhado"):
            with self.subTest(estado=estado):
                colunas = {**_colunas_para(estado, a), "escolhida": True}
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, admin,
                    f"INSERT INTO {TABELA} (tenant_id, origem_ref, operacao, provider, "
                    f"idempotency_key, estado, {', '.join(colunas)}) "
                    f"VALUES (%s, %s, 'cutout', 'photoroom', %s, %s, {', '.join(['%s'] * len(colunas))})",
                    (a, _origem(a), uuid.uuid4().hex, estado, *colunas.values()),
                )
        # E por `UPDATE`, que e o caminho do botao: o `kamba_app` tem
        # `UPDATE (escolhida)`, e o *trigger* nao olha para ela fora do `concluido`.
        linha = inserir(admin, a, "a_processar")
        self.assertErroSql(
            VIOLACAO_DE_CHECK, admin,
            f"UPDATE {TABELA} SET escolhida = true WHERE image_job_id = %s", (linha,),
        )

    def test_so_uma_versao_escolhida_por_original(self) -> None:
        """`image_jobs_escolhida_uq`: o botao escolhe **uma** versao de cada original."""
        admin = self.ligar("admin").cursor()
        a = factories.tenant(admin)
        origem = _origem(a)
        inserir(admin, a, "concluido", origem_ref=origem, escolhida=True)
        segunda = inserir(admin, a, "concluido", origem_ref=origem)
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE, admin,
            f"UPDATE {TABELA} SET escolhida = true WHERE image_job_id = %s", (segunda,),
        )
        # Outro original, ou nenhuma escolhida, nao colide.
        inserir(admin, a, "concluido", escolhida=True)
        inserir(admin, a, "concluido", origem_ref=origem)

    def test_as_chaves_do_sto_sao_do_proprio_tenant(self) -> None:
        admin = self.ligar("admin").cursor()
        a = factories.tenant(admin)
        b = factories.tenant(admin)
        for origem in (
            _origem(b),
            "https://exemplo.invalid/foto.jpg",
            f"t/{a}",
        ):
            with self.subTest(origem_ref=origem):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, admin,
                    f"INSERT INTO {TABELA} (tenant_id, origem_ref, operacao, provider, idempotency_key) "
                    "VALUES (%s, %s, 'cutout', 'photoroom', %s)",
                    (a, origem, uuid.uuid4().hex),
                )
        for versao in (f"t/{b}/foto/v1", f"t/{a}/catalogo/v1"):
            with self.subTest(versao_ref=versao):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, admin,
                    f"INSERT INTO {TABELA} (tenant_id, origem_ref, operacao, provider, idempotency_key, "
                    "estado, versao_ref, latencia_ms) "
                    "VALUES (%s, %s, 'cutout', 'photoroom', %s, 'concluido', %s, 100)",
                    (a, _origem(a), uuid.uuid4().hex, versao),
                )

    def test_o_mesmo_pedido_no_mesmo_tenant_e_recusado(self) -> None:
        """A linha repetida e valida em tudo o resto: o `CHECK` corre antes do indice."""
        admin = self.ligar("admin").cursor()
        a = factories.tenant(admin)
        b = factories.tenant(admin)
        inserir(admin, a, idempotency_key="pedido-repetido")
        inserir(admin, b, idempotency_key="pedido-repetido")
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE, admin,
            f"INSERT INTO {TABELA} (tenant_id, origem_ref, operacao, provider, idempotency_key) "
            "VALUES (%s, %s, 'cutout', 'photoroom', 'pedido-repetido')",
            (a, _origem(a)),
        )

    def test_restricoes_de_coluna_e_de_linha(self) -> None:
        admin = self.ligar("admin").cursor()
        a = factories.tenant(admin)
        casos = (
            ("operacao inventada", "pendente", {"operacao": "remover_rosto"}),
            ("provider fora da forma", "pendente", {"provider": "PhotoRoom"}),
            ("provider de uma letra", "pendente", {"provider": "p"}),
            ("chave vazia", "pendente", {"idempotency_key": ""}),
            ("chave longa", "pendente", {"idempotency_key": "k" * 201}),
            ("custo negativo", "pendente", {"custo_usd": Decimal("-0.01")}),
            ("latencia negativa", "pendente", {"latencia_ms": -1}),
            ("estado inventado", "aprovado", {}),
            ("concluido sem versao", "concluido", {"versao_ref": None}),
            ("concluido sem latencia", "concluido", {"latencia_ms": None}),
        )
        for nome, estado, campos in casos:
            with self.subTest(caso=nome):
                valores = {
                    "tenant_id": a,
                    "origem_ref": _origem(a),
                    "operacao": "cutout",
                    "provider": "photoroom",
                    "idempotency_key": uuid.uuid4().hex,
                    "estado": estado,
                    **(_colunas_para(estado, a) if estado in ESTADOS else {}),
                    **campos,
                }
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, admin,
                    f"INSERT INTO {TABELA} ({', '.join(valores)}) "
                    f"VALUES ({', '.join(['%s'] * len(valores))})",
                    tuple(valores.values()),
                )


class TestPrivilegios(ComBase):
    def test_a_rls_esta_ligada_e_forcada(self) -> None:
        [(ligada, forcada)] = self.consultar(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", (TABELA,)
        )
        self.assertEqual((ligada, forcada), (True, True))

    def test_a_aplicacao_insere_um_pendente(self) -> None:
        admin = self.ligar("admin")
        tenant = factories.tenant(admin.cursor())
        admin.commit()
        app = self.ligar("app").cursor()
        factories.contexto(app, tenant)
        app.execute(
            f"INSERT INTO {TABELA} (tenant_id, origem_ref, operacao, provider, idempotency_key, "
            "sintetica, aviso_at) VALUES (%s, %s, 'variacao_lifestyle', 'photoroom', %s, true, now()) "
            "RETURNING estado, versao, gerado_por_ia, escolhida",
            (tenant, _origem(tenant), uuid.uuid4().hex),
        )
        self.assertEqual(tuple(app.fetchone()), ("pendente", 0, True, False))

    def test_a_aplicacao_nao_apaga_nem_muda_a_identidade_do_pedido(self) -> None:
        admin = self.ligar("admin")
        tenant = factories.tenant(admin.cursor())
        linha = inserir(admin.cursor(), tenant)
        admin.commit()
        app = self.ligar("app").cursor()
        factories.contexto(app, tenant)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                           f"DELETE FROM {TABELA} WHERE image_job_id = %s", (linha,))
        for coluna, valor in (
            ("origem_ref", f"'{_origem(tenant)}'"),
            ("operacao", "'luz_basica'"),
            ("idempotency_key", "'outra'"),
            ("sintetica", "true"),
            ("aviso_at", "now()"),
            ("tenant_id", "gen_random_uuid()"),
            ("image_job_id", "gen_random_uuid()"),
            ("criado_at", "now()"),
        ):
            with self.subTest(coluna=coluna):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                                   f"UPDATE {TABELA} SET {coluna} = {valor} WHERE image_job_id = %s", (linha,))
        # O trabalho so nasce `pendente`: a aplicacao nao insere outro estado.
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, app,
            f"INSERT INTO {TABELA} (tenant_id, origem_ref, operacao, provider, idempotency_key, "
            "estado, versao_ref, latencia_ms) VALUES (%s, %s, 'cutout', 'photoroom', %s, 'concluido', %s, 1)",
            (tenant, _origem(tenant), uuid.uuid4().hex, f"t/{tenant}/foto/v1"),
        )

    def test_a_aplicacao_so_ve_e_escreve_o_seu_tenant(self) -> None:
        admin = self.ligar("admin")
        a = factories.tenant(admin.cursor())
        b = factories.tenant(admin.cursor())
        linha_a = inserir(admin.cursor(), a)
        admin.commit()
        app = self.ligar("app").cursor()
        factories.contexto(app, b)
        app.execute(f"SELECT count(*) FROM {TABELA} WHERE image_job_id = %s", (linha_a,))
        self.assertEqual(app.fetchone()[0], 0)
        app.execute(f"UPDATE {TABELA} SET provider = 'outro' WHERE image_job_id = %s", (linha_a,))
        self.assertEqual(app.rowcount, 0)
        # Escrever uma linha de A com o contexto de B: a `WITH CHECK` recusa.
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, app,
            f"INSERT INTO {TABELA} (tenant_id, origem_ref, operacao, provider, idempotency_key) "
            "VALUES (%s, %s, 'cutout', 'photoroom', %s)",
            (a, _origem(a), uuid.uuid4().hex),
        )
        factories.contexto(app, None)
        app.execute(f"SELECT count(*) FROM {TABELA}")
        self.assertEqual(app.fetchone()[0], 0)
        factories.contexto(app, a)
        app.execute(f"SELECT count(*) FROM {TABELA} WHERE image_job_id = %s", (linha_a,))
        self.assertEqual(app.fetchone()[0], 1)


class TestFinalidadeImagem(ComBase):
    def test_o_dominio_tem_as_catorze_e_a_imagem_e_aceite(self) -> None:
        admin = self.ligar("admin").cursor()
        admin.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'tenant_destinations_purpose_ck'"
        )
        definicao = admin.fetchone()[0]
        for finalidade in FINALIDADES:
            self.assertIn(f"'{finalidade}'", definicao)
        self.assertEqual(definicao.count("'::text"), 14)
        tenant = factories.tenant(admin)
        sql = (
            f"INSERT INTO {DESTINOS} (tenant_id, provider, country, purpose, status, "
            "retencao_zero, sem_treino) VALUES (%s, 'photoroom', 'US', %s, 'pendente', false, false)"
        )
        admin.execute(sql, (tenant, "imagem"))
        self.assertEqual(admin.rowcount, 1)
        self.assertErroSql(VIOLACAO_DE_CHECK, admin, sql, (tenant, "imagens"))


class TestDowngrade(unittest.TestCase):
    """Desce para a revisao de baixo (lida do ficheiro), com linhas, e volta a subir.

    **Nao exige `em_head()` depois de descer**: com outra revisao por cima, o
    Alembic desce-a primeiro e a base fica na de baixo desta, que e o que se
    mede. **Aplica o `bootstrap`**, como o `ComBase`: corrido sozinho, este
    modulo encontra a base sem papeis, e o Alembic liga como `kamba_migrator`.
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

    def _estado(self) -> tuple[int, int, int, str]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' "
                      "AND tablename = 'image_jobs'")
            tabelas = c.fetchone()[0]
            c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'image_jobs_transicao'")
            funcoes = c.fetchone()[0]
            c.execute(f"SELECT count(*) FROM {DESTINOS} WHERE purpose = 'imagem'")
            destinos = c.fetchone()[0]
            c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                      "WHERE conname = 'tenant_destinations_purpose_ck'")
            return tabelas, funcoes, destinos, c.fetchone()[0]
        finally:
            conexao.close()

    def _executar(self, sql: str, parametros: tuple = ()) -> str | None:
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            cursor.execute(sql, parametros)
            linha = cursor.fetchone() if cursor.description else None
            conexao.commit()
            return linha[0] if linha else None
        finally:
            conexao.close()

    def test_um_destino_imagem_recusa_a_descida_e_sem_ele_desce(self) -> None:
        """Um destino `imagem` e registo de uma decisao de transferencia: nao se apaga para descer.

        A descida recusa-se **e a base fica como estava** (a tabela, a funcao, o
        destino e o dominio de catorze). Sem o destino, desce com linhas na
        `image_jobs`, o dominio volta as treze, e volta a subir.
        """
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            tenant = factories.tenant(cursor)
            inserir(cursor, tenant, "bloqueada_gate")
            conexao.commit()
        finally:
            conexao.close()
        destino = self._executar(
            f"INSERT INTO {DESTINOS} (tenant_id, provider, country, purpose, status, "
            "retencao_zero, sem_treino) VALUES (%s, 'photoroom', 'US', 'imagem', 'pendente', false, false) "
            "RETURNING id::text",
            (tenant,),
        )
        try:
            recusa = alembic("downgrade", _literal("down_revision"))
            self.assertNotEqual(recusa.returncode, 0, "a descida com um destino imagem devia ser recusada")
            self.assertIn("purpose imagem", recusa.stdout + recusa.stderr)
            tabelas, funcoes, destinos, definicao = self._estado()
            self.assertEqual((tabelas, funcoes, destinos), (1, 1, 1))
            self.assertEqual(definicao.count("'::text"), 14)
        finally:
            self._executar(f"DELETE FROM {DESTINOS} WHERE id = %s", (destino,))

        alembic_ok("downgrade", _literal("down_revision"))
        tabelas, funcoes, destinos, definicao = self._estado()
        self.assertEqual((tabelas, funcoes, destinos), (0, 0, 0))
        self.assertNotIn("'imagem'", definicao)
        for finalidade in FINALIDADES_DA_0036:
            self.assertIn(f"'{finalidade}'", definicao)
        self.assertEqual(definicao.count("'::text"), 13)
        alembic_ok("upgrade", "head")
        tabelas, funcoes, _, definicao = self._estado()
        self.assertEqual((tabelas, funcoes), (1, 1))
        self.assertEqual(definicao.count("'::text"), 14)


if __name__ == "__main__":
    unittest.main()
