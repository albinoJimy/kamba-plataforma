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
"""

from __future__ import annotations

import datetime
import threading
import uuid

from tests import factories
from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK, sqlstate
from tests_agr.base import ComAgr

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr.social import regras  # noqa: E402
from kamba_agr.social.repositorio import (  # noqa: E402
    EXPIRADO,
    ItemMudouError,
    ItemNovo,
    PerfilMudouError,
    SemPublicacoesError,
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
        factories.entitlement(self.semente, self.tenant, modulo="social", limites={"posts_mes": 2})
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
        self.semente.execute(
            "UPDATE platform.content_items SET estado = 'aprovado' WHERE content_item_id = %s",
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
