"""O repositorio do modulo social contra o PostgreSQL (KAM-121).

O `services/agr/tests/test_social_dono.py` corre o fluxo com o repositorio em
memoria. Aqui corre o `RepositorioSql` de `kamba_agr.tls.social`, com o papel
`kamba_app` e a RLS `FORCE` das tres tabelas da revisao `0079`:

| Propriedade | Porque precisa da base |
|---|---|
| o perfil grava-se por *compare-and-set* | o `UPDATE ... WHERE versao = %s` |
| «IDEIAS» duas vezes e o mesmo calendario, e dois «NOVA» concorrentes dao uma geracao | a tranca da transaccao e o indice unico parcial |
| um «NOVA» expira so os itens por aprovar | o `estado = ANY(...)` |
| a legenda consome **um** `posts_mes`, e regerar nao conta | o `platform.ten_consumir`, na mesma transaccao |
| sem `posts_mes`, nada se grava | a excepcao desfaz a transaccao |
| outro tenant nao ve o perfil, o calendario nem os itens | a RLS `FORCE` |
| o `kamba_app` nao muda o `is_ai_generated` nem apaga | os privilegios por coluna da revisao |
| o `sujeito_tipo` aceita `conteudo` | o `CHECK` da revisao |

E a arte, a aprovacao e a entrega do KAM-122 (revisao `0085`), com o mesmo
repositorio:

| Propriedade | Porque precisa da base |
|---|---|
| aprovar duas vezes da **um** `aprovado` e **um** `content.approved`, com o `content_item_id` e a versao | o `FOR UPDATE` e o `evt_emitir` na mesma transaccao |
| uma edicao depois da aprovacao invalida o `hash` antigo, e uma arte nova num item pendente tambem | o `UPDATE ... AND aprovacao_hash = %s`, o `aprovacao_hash = NULL` da arte e o gatilho da revisao |
| entregar duas vezes falha a segunda, e o item fica `entregue` | o `versao = %s AND estado = 'aprovado'` e o gatilho |
| os termos da primeira entrega gravam-se uma vez | o `termos_entrega_at IS NULL` |
| a quarta arte e recusada | o `arte_tentativas < 3` e o `CHECK` da revisao |
| o `imagens_mes` consome-se uma vez por chave | o `platform.ten_consumir` idempotente |
"""

from __future__ import annotations

import datetime
import hashlib
import json
import threading
import uuid
from decimal import Decimal

from tests import factories
from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK, sqlstate
from tests_agr.base import ComAgr

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr.social import regras  # noqa: E402
from kamba_agr.social.repositorio import (  # noqa: E402
    EXPIRADO,
    AprovacaoInvalidadaError,
    Arte,
    Item,
    ItemMudouError,
    ItemNovo,
    PerfilMudouError,
    SemImagensError,
    SemPublicacoesError,
    TentativasEsgotadasError,
)
from kamba_agr.tls.social import RepositorioSql  # noqa: E402
from kamba_core import tenant_guard  # noqa: E402

SEMANA = "2026-W48"
HORA = datetime.datetime(2026, 11, 23, 17, 0, tzinfo=datetime.UTC)


def _perfil(tenant: str) -> regras.Perfil:
    return regras.Perfil(
        tenant_id=tenant,
        nome="Loja da Ana",
        categoria="roupa",
        tom="proximo",
        cores=("#FFAA00",),
        publico="maes jovens",
        slots=regras.ler_slots("segunda 18h, quarta 12h"),
        factos=(regras.Facto("Entregamos em Luanda"),),
    )


def _itens(n: int = 3) -> list[ItemNovo]:
    return [
        ItemNovo(str(uuid.uuid4()), "dica", f"tema {i}", HORA + datetime.timedelta(days=i), False, "1.0.0+m.2")
        for i in range(n)
    ]


class ComSocial(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        self.tenant = factories.tenant(self.semente)
        self.outro = factories.tenant(self.semente)
        self._tenants.extend([self.tenant, self.outro])
        factories.entitlement(
            self.semente, self.tenant, modulo="social", limites={"posts_mes": 2, "imagens_mes": 1}
        )
        factories.contexto(self.semente, None)
        # Antes dos tenants: a limpeza do `ComAgr` foi registada primeiro, e corre depois desta.
        self.addCleanup(self._limpar_social)
        self.app = self.ligar("app")
        self.repo = RepositorioSql(self.app)

    def _limpar_social(self) -> None:
        for tenant in self._tenants:
            for tabela in (
                "content_items",
                "content_calendar",
                "brand_profile",
                "usage_ledger",
                "tenant_usage",
                "entitlements",
                "events_outbox",
                "events_log",
                "evt_agregado_seq",
            ):
                self.semente.execute(f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (tenant,))

    def _consumidos(self) -> int:
        self.semente.execute("SELECT count(*) FROM platform.usage_ledger WHERE tenant_id = %s", (self.tenant,))
        return int(self.semente.fetchone()[0])


class TestPerfil(ComSocial):
    def test_o_perfil_nasce_vazio_e_grava_se_por_versao(self) -> None:
        vazio = self.repo.gravar_perfil(regras.Perfil(tenant_id=self.tenant), None)
        self.assertEqual(self.repo.ler_perfil(self.tenant), vazio)
        with self.assertRaises(PerfilMudouError):
            self.repo.gravar_perfil(regras.Perfil(tenant_id=self.tenant), None)
        nome = regras.com_resposta(vazio, "nome", "Loja da Ana")
        self.repo.gravar_perfil(nome, vazio.versao)
        with self.assertRaises(PerfilMudouError):
            self.repo.gravar_perfil(regras.com_resposta(vazio, "nome", "Outra"), vazio.versao)
        completo = _perfil(self.tenant)
        self.repo.gravar_perfil(dataclass_versao(completo, nome.versao + 1), nome.versao)
        lido = self.repo.ler_perfil(self.tenant)
        assert lido is not None
        self.assertTrue(lido.completo)
        self.assertEqual((lido.slots, lido.factos, lido.cores), (completo.slots, completo.factos, completo.cores))
        self.assertIsNone(self.repo.ler_perfil(self.outro))

    def test_uma_cor_fora_da_forma_e_recusada_pela_base(self) -> None:
        mau = regras.Perfil(tenant_id=self.tenant, cores=("azul",))
        with self.assertRaises(Exception) as erro:
            self.repo.gravar_perfil(mau, None)
        self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_CHECK)


def dataclass_versao(perfil: regras.Perfil, versao: int) -> regras.Perfil:
    return regras.Perfil(**{**perfil.__dict__, "versao": versao})


class TestCalendario(ComSocial):
    def test_ideias_duas_vezes_e_o_mesmo_e_nova_expira_so_os_por_aprovar(self) -> None:
        um, novo = self.repo.abrir(self.tenant, SEMANA, str(uuid.uuid4()), 1, "permitida", "v1", _itens())
        self.assertTrue(novo)
        self.assertEqual(len(um.itens), 3)
        self.assertTrue(all(i.estado == "rascunho" and i.is_ai_generated for i in um.itens))
        outra, novo = self.repo.abrir(self.tenant, SEMANA, str(uuid.uuid4()), 1, "permitida", "v1", _itens())
        self.assertFalse(novo)
        self.assertEqual(outra.calendar_id, um.calendar_id)
        # Aprovado pelo caminho que o gatilho da revisao da arte e da aprovacao
        # (KAM-122) aceita: a legenda, a arte e o hash em `pendente_aprovacao`, e
        # so depois a passagem a `aprovado`. Um `rascunho -> aprovado` directo e
        # recusado pela base desde essa revisao.
        self.semente.execute(
            "UPDATE platform.content_items SET legenda = 'Legenda.', arte_ref = %s, "
            "arte_sha256 = %s, arte_fundo = 'gradiente', arte_texto = 'Loja da Ana', "
            "arte_formato = 'quadrado', aprovacao_hash = %s, "
            "estado = 'pendente_aprovacao' WHERE content_item_id = %s",
            (
                f"t/{self.tenant}/social/2026/11/{uuid.uuid4()}",
                "a" * 64,
                "b" * 64,
                um.itens[0].content_item_id,
            ),
        )
        self.semente.execute(
            "UPDATE platform.content_items SET estado = 'aprovado', aprovado_at = now() "
            "WHERE content_item_id = %s",
            (um.itens[0].content_item_id,),
        )
        dois, novo = self.repo.abrir(self.tenant, SEMANA, str(uuid.uuid4()), 2, "permitida", "v1", _itens(4))
        self.assertTrue(novo)
        self.assertEqual(self.repo.calendario(self.tenant, SEMANA).calendar_id, dois.calendar_id)  # type: ignore[union-attr]
        self.semente.execute(
            "SELECT content_item_id::text, estado FROM platform.content_items WHERE calendar_id = %s",
            (um.calendar_id,),
        )
        estados = dict(self.semente.fetchall())
        self.assertEqual(estados[um.itens[0].content_item_id], "aprovado")
        self.assertEqual({estados[i.content_item_id] for i in um.itens[1:]}, {EXPIRADO})
        self.semente.execute("SELECT estado FROM platform.content_calendar WHERE calendar_id = %s", (um.calendar_id,))
        self.assertEqual(self.semente.fetchone()[0], "substituido")

    def test_dois_nova_concorrentes_dao_uma_geracao(self) -> None:
        self.repo.abrir(self.tenant, SEMANA, str(uuid.uuid4()), 1, "permitida", "v1", _itens())
        ligacoes = [self.ligar("app"), self.ligar("app")]
        barreira = threading.Barrier(2)
        abertos: list[tuple[str, bool]] = []
        erros: list[BaseException] = []

        def nova(ligacao) -> None:
            try:
                barreira.wait()
                calendario, novo = RepositorioSql(ligacao).abrir(
                    self.tenant, SEMANA, str(uuid.uuid4()), 2, "permitida", "v1", _itens()
                )
                abertos.append((calendario.calendar_id, novo))
            except BaseException as erro:  # noqa: BLE001 — o fio nao propaga
                erros.append(erro)

        fios = [threading.Thread(target=nova, args=(c,)) for c in ligacoes]
        for f in fios:
            f.start()
        for f in fios:
            f.join(30)
        self.assertEqual(erros, [])
        self.assertEqual(len({c for c, _ in abertos}), 1)
        self.assertEqual(sorted(n for _, n in abertos), [False, True])
        self.semente.execute(
            "SELECT count(*) FROM platform.content_calendar WHERE tenant_id = %s AND estado = 'activo'",
            (self.tenant,),
        )
        self.assertEqual(self.semente.fetchone()[0], 1)

    def test_o_outro_tenant_nao_ve_o_calendario_nem_os_itens(self) -> None:
        um, _ = self.repo.abrir(self.tenant, SEMANA, str(uuid.uuid4()), 1, "permitida", "v1", _itens())
        self.assertIsNone(self.repo.calendario(self.outro, SEMANA))
        prefixo = uuid.UUID(um.itens[0].content_item_id).hex[:8]
        self.assertEqual(len(self.repo.itens_por_prefixo(self.tenant, prefixo)), 1)
        self.assertEqual(self.repo.itens_por_prefixo(self.outro, prefixo), ())


class TestLegenda(ComSocial):
    def test_a_legenda_consome_um_post_e_regerar_nao_conta(self) -> None:
        um, _ = self.repo.abrir(self.tenant, SEMANA, str(uuid.uuid4()), 1, "condicional", "v1", _itens())
        item = um.itens[0]
        gravado = self.repo.gravar_legenda(item, "Uma ideia simples.", True, "v2")
        self.assertEqual((gravado.legenda, gravado.revisao_reforcada, gravado.versao), ("Uma ideia simples.", True, 2))
        self.assertEqual(self._consumidos(), 1)
        de_novo = self.repo.gravar_legenda(gravado, "Outra ideia.", False, "v2")
        self.assertTrue(de_novo.revisao_reforcada, "uma condicional nao se desfaz")
        self.assertEqual(self._consumidos(), 1)
        with self.assertRaises(ItemMudouError):
            self.repo.gravar_legenda(gravado, "Uma versao antiga.", False, "v2")

    def test_sem_posts_nada_se_grava(self) -> None:
        um, _ = self.repo.abrir(self.tenant, SEMANA, str(uuid.uuid4()), 1, "permitida", "v1", _itens(3))
        for item in um.itens[:2]:
            self.repo.gravar_legenda(item, "Legenda.", False, "v1")
        with self.assertRaises(SemPublicacoesError):
            self.repo.gravar_legenda(um.itens[2], "Legenda a mais.", False, "v1")
        self.semente.execute("SELECT legenda FROM platform.content_items WHERE content_item_id = %s", (um.itens[2].content_item_id,))
        self.assertIsNone(self.semente.fetchone()[0])

    def test_uma_legenda_bloqueada_rejeita_o_item(self) -> None:
        um, _ = self.repo.abrir(self.tenant, SEMANA, str(uuid.uuid4()), 1, "permitida", "v1", _itens())
        rejeitado = self.repo.rejeitar(um.itens[0], "v3")
        self.assertEqual(rejeitado.estado, "rejeitado")
        with self.assertRaises(ItemMudouError):
            self.repo.gravar_legenda(rejeitado, "Depois de rejeitado.", False, "v3")


class TestPrivilegiosESujeito(ComSocial):
    def test_o_app_nao_muda_o_is_ai_generated_nem_apaga(self) -> None:
        um, _ = self.repo.abrir(self.tenant, SEMANA, str(uuid.uuid4()), 1, "permitida", "v1", _itens(3))
        for sql in (
            "UPDATE platform.content_items SET is_ai_generated = false",
            "DELETE FROM platform.content_items",
            "DELETE FROM platform.brand_profile",
            "UPDATE platform.content_calendar SET semana_iso = '2026-W49'",
        ):
            with self.subTest(sql=sql):
                with self.assertRaises(Exception) as erro:
                    with tenant_guard.tx(self.app, self.tenant) as cursor:
                        cursor.execute(sql)
                self.assertEqual(sqlstate(erro.exception), PRIVILEGIO_INSUFICIENTE)
        self.assertTrue(all(i.is_ai_generated for i in um.itens))

    def test_o_sujeito_conteudo_cabe_no_check(self) -> None:
        self.semente.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'screening_decision_sujeito_tipo_ck'")
        definicao = self.semente.fetchone()[0]
        for sujeito in ("categoria", "produto", "condicoes", "conteudo"):
            self.assertIn(f"'{sujeito}'", definicao)


# ------------------------------------------------- a arte, a aprovacao e a entrega (KAM-122)


AGORA = datetime.datetime(2026, 11, 23, 18, 0, tzinfo=datetime.UTC)


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


class ComArte(ComSocial):
    def _arte(self, custo: str = "0.0336") -> Arte:
        return Arte(
            f"t/{self.tenant}/social/2026/11/{uuid.uuid4()}",
            _hash(str(uuid.uuid4())),
            "gerado",
            Decimal(custo),
            "Loja da Ana - 12.500 Kz",
            "quadrado",
        )

    def _rascunho_com_arte(self, indice: int = 0) -> Item:
        calendario = self.repo.calendario(self.tenant, SEMANA)
        if calendario is None:
            calendario, _ = self.repo.abrir(self.tenant, SEMANA, str(uuid.uuid4()), 1, "permitida", "v1", _itens(2))
        item = self.repo.gravar_legenda(calendario.itens[indice], f"Uma legenda {indice}.", False, "v1")
        return self.repo.gravar_arte(item, self._arte())

    def _pendente(self, hash_: str, indice: int = 0) -> Item:
        item = self._rascunho_com_arte(indice)
        return self.repo.pedir_aprovacao(item, item.legenda or "", hash_)

    def _linha(self, item: Item) -> tuple:
        self.semente.execute(
            "SELECT estado, versao, aprovacao_hash, aprovado_at IS NOT NULL, entregue_at IS NOT NULL "
            "FROM platform.content_items WHERE content_item_id = %s",
            (item.content_item_id,),
        )
        return tuple(self.semente.fetchone())

    def _aprovados(self) -> list[dict]:
        self.semente.execute(
            "SELECT envelope FROM platform.events_outbox WHERE tenant_id = %s AND tipo = 'content.approved' "
            "ORDER BY (envelope->'payload'->>'versao')::int",
            (self.tenant,),
        )
        return [e if isinstance(e, dict) else json.loads(e) for (e,) in self.semente.fetchall()]


class TestAprovacao(ComArte):
    def test_aprovar_duas_vezes_da_um_aprovado_e_um_evento(self) -> None:
        hash_ = _hash("a primeira")
        pendente = self._pendente(hash_)
        aprovado, evento = self.repo.aprovar(pendente, hash_, AGORA)
        self.assertIsNotNone(evento)
        de_novo, outro = self.repo.aprovar(pendente, hash_, AGORA)
        self.assertIsNone(outro, "o segundo toque nao emite")
        self.assertEqual((aprovado.estado, de_novo.estado), ("aprovado", "aprovado"))
        self.assertEqual(self._linha(pendente)[:3], ("aprovado", aprovado.versao, hash_))
        eventos = self._aprovados()
        self.assertEqual(len(eventos), 1)
        self.assertEqual(
            eventos[0]["payload"], {"content_item_id": pendente.content_item_id, "versao": aprovado.versao}
        )

    def test_dois_toques_concorrentes_dao_um_evento(self) -> None:
        hash_ = _hash("concorrente")
        pendente = self._pendente(hash_)
        ligacoes = [self.ligar("app"), self.ligar("app")]
        barreira = threading.Barrier(2)
        eventos: list[object] = []
        erros: list[BaseException] = []

        def tocar(ligacao) -> None:
            try:
                barreira.wait()
                eventos.append(RepositorioSql(ligacao).aprovar(pendente, hash_, AGORA)[1])
            except BaseException as erro:  # noqa: BLE001 — o fio nao propaga
                erros.append(erro)

        fios = [threading.Thread(target=tocar, args=(c,)) for c in ligacoes]
        for f in fios:
            f.start()
        for f in fios:
            f.join(30)
        self.assertEqual(erros, [])
        self.assertEqual(sum(e is not None for e in eventos), 1)
        self.assertEqual(len(self._aprovados()), 1)

    def test_uma_edicao_depois_da_aprovacao_invalida_o_hash_antigo(self) -> None:
        antigo, novo = _hash("a primeira"), _hash("a editada")
        aprovado, _ = self.repo.aprovar(self._pendente(antigo), antigo, AGORA)
        editado = self.repo.pedir_aprovacao(aprovado, "A legenda editada.", novo)
        self.assertEqual(self._linha(editado)[:4], ("pendente_aprovacao", editado.versao, novo, False))
        with self.assertRaises(AprovacaoInvalidadaError):
            self.repo.aprovar(editado, antigo, AGORA)
        self.assertEqual(self._linha(editado)[0], "pendente_aprovacao")
        self.assertEqual(len(self._aprovados()), 1)
        reaprovado, evento = self.repo.aprovar(editado, novo, AGORA)
        self.assertIsNotNone(evento)
        self.assertEqual(
            [e["payload"]["versao"] for e in self._aprovados()], [aprovado.versao, reaprovado.versao]
        )


    def test_uma_arte_nova_num_pendente_invalida_a_aprovacao_pedida(self) -> None:
        antigo = _hash("a primeira")
        pendente = self._pendente(antigo)
        regerado = self.repo.gravar_arte(pendente, self._arte())
        self.assertIsNone(regerado.aprovacao_hash)
        self.assertEqual(self._linha(pendente)[:3], ("pendente_aprovacao", regerado.versao, None))
        with self.assertRaises(AprovacaoInvalidadaError):
            self.repo.aprovar(regerado, antigo, AGORA)
        self.assertEqual(self._linha(pendente)[0], "pendente_aprovacao")
        self.assertEqual(self._aprovados(), [])


    def test_o_pedido_com_reforco_marca_a_revisao_reforcada_e_nao_a_desfaz(self) -> None:
        item = self._rascunho_com_arte()
        self.assertFalse(item.revisao_reforcada)
        pedido = self.repo.pedir_aprovacao(item, item.legenda or "", _hash("reforcada"), reforcada=True)
        self.semente.execute(
            "SELECT revisao_reforcada FROM platform.content_items WHERE content_item_id = %s",
            (item.content_item_id,),
        )
        self.assertIs(self.semente.fetchone()[0], True)
        # Um pedido seguinte sem reforco nao o tira: e um `OR`.
        self.repo.pedir_aprovacao(pedido, pedido.legenda or "", _hash("outra vez"))
        self.semente.execute(
            "SELECT revisao_reforcada FROM platform.content_items WHERE content_item_id = %s",
            (item.content_item_id,),
        )
        self.assertIs(self.semente.fetchone()[0], True)

    def test_a_arte_grava_o_texto_e_o_formato(self) -> None:
        item = self._rascunho_com_arte()
        self.semente.execute(
            "SELECT arte_texto, arte_formato FROM platform.content_items WHERE content_item_id = %s",
            (item.content_item_id,),
        )
        self.assertEqual(tuple(self.semente.fetchone()), ("Loja da Ana - 12.500 Kz", "quadrado"))
        lido = self.repo.item(self.tenant, item.content_item_id)
        assert lido is not None
        self.assertEqual((lido.arte_texto, lido.arte_formato), (item.arte_texto, item.arte_formato))


class TestEntrega(ComArte):
    def test_entregar_duas_vezes_falha_a_segunda_e_os_termos_gravam_se_uma_vez(self) -> None:
        self.repo.gravar_perfil(regras.Perfil(tenant_id=self.tenant), None)
        um, _ = self.repo.aprovar(self._pendente(_hash("o primeiro")), _hash("o primeiro"), AGORA)
        entregue, primeira = self.repo.entregar(um, AGORA)
        self.assertTrue(primeira)
        depois = AGORA + datetime.timedelta(minutes=1)
        with self.assertRaises(ItemMudouError):
            self.repo.entregar(um, depois)
        lido = self.repo.item(self.tenant, um.content_item_id)
        assert lido is not None
        with self.assertRaises(ItemMudouError):
            self.repo.entregar(lido, depois)
        linha = self._linha(um)
        self.assertEqual((linha[0], linha[1], linha[4]), ("entregue", entregue.versao, True))

        # Um segundo item entrega-se, e os termos ficam com a hora da primeira.
        dois, _ = self.repo.aprovar(self._pendente(_hash("o segundo"), 1), _hash("o segundo"), AGORA)
        _, primeira = self.repo.entregar(dois, AGORA + datetime.timedelta(hours=1))
        self.assertFalse(primeira)
        self.semente.execute(
            "SELECT termos_entrega_at FROM platform.brand_profile WHERE tenant_id = %s", (self.tenant,)
        )
        self.assertEqual(self.semente.fetchone()[0], AGORA)


class TestArteEImagens(ComArte):
    def test_a_quarta_arte_e_recusada(self) -> None:
        item = self._rascunho_com_arte()
        item = self.repo.gravar_arte(item, self._arte("0.01"))
        item = self.repo.gravar_arte(item, self._arte("0.01"))
        self.assertEqual(item.arte_tentativas, 3)
        with self.assertRaises(TentativasEsgotadasError):
            self.repo.gravar_arte(item, self._arte())
        # A guarda da base, e nao so a do codigo: uma copia que diz duas
        # tentativas, com a versao certa, tambem nao passa.
        copia = Item(**{**item.__dict__, "arte_tentativas": 2})
        with self.assertRaises(ItemMudouError):
            self.repo.gravar_arte(copia, self._arte())
        self.semente.execute(
            "SELECT arte_tentativas, arte_custo_usd FROM platform.content_items WHERE content_item_id = %s",
            (item.content_item_id,),
        )
        self.assertEqual(tuple(self.semente.fetchone()), (3, Decimal("0.0536")))

    def test_o_imagens_mes_consome_se_uma_vez_por_chave(self) -> None:
        self.repo.consumir_imagem(self.tenant, "arte:um")
        self.repo.consumir_imagem(self.tenant, "arte:um")
        with self.assertRaises(SemImagensError):
            self.repo.consumir_imagem(self.tenant, "arte:dois")
        self.semente.execute(
            "SELECT idempotency_key, quantidade FROM platform.usage_ledger "
            "WHERE tenant_id = %s AND chave_limite = 'imagens_mes'",
            (self.tenant,),
        )
        self.assertEqual([tuple(l) for l in self.semente.fetchall()], [("arte:um", 1)])
