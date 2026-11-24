"""As leituras das tools do catalogo do dono contra o PostgreSQL (KAM-119).

O `services/agr/tests/test_catalogo_dono.py` corre o fluxo com o repositorio em
memoria e substitui as tres leituras que tocam a base fora dele. Aqui correm
**essas**, com o papel `kamba_app` e a RLS `FORCE`:

| Propriedade | Porque precisa da base |
|---|---|
| o `ler_estado` conta por estado e lista os rascunhos a espera | o `GROUP BY` e o `IN ('a_perguntar', 'rascunho')` da `catalog_ingestions` |
| as bloqueadas sem decisao do screening tambem esperam (KAM-244) | o `categoria_restrita = ANY(%s::text[])` |
| o repositorio sobre a `TomadaDaInvocacao` escreve na ligacao de agora | a troca de ligacao do KAM-244, com a RLS de cada uma |
| outro tenant nao ve contagens nem rascunhos | a RLS `FORCE` da `catalog_ingestions` |
| o `ler_accao` le a accao `aprovar_conteudo` com o `ref` `{ingestao}:{versao}` e a confirmacao | os privilegios por coluna da `0070` e a RLS da `owner_actions` |
| o `RepositorioDbapi` sobre a ligacao emprestada nao a fecha | o `repositorio_sobre` da montagem, com a tomada da ToolLayer |

O SQL e o de `kamba_agr.tls.catalogo_tools`, chamado pelas funcoes do modulo.
"""

from __future__ import annotations

import datetime
from dataclasses import replace

from tests import factories
from tests_agr.base import ComAgr

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr.catalogo.montagem import TomadaDaInvocacao, repositorio_sobre  # noqa: E402
from kamba_agr.dono import accoes  # noqa: E402
from kamba_agr.tls import catalogo_tools  # noqa: E402
from kamba_core.catalogo import estados  # noqa: E402
from kamba_core.catalogo.pipeline import REGRAS_RETOMAVEIS  # noqa: E402
from kamba_core.catalogo.repositorio import Ingestao, novo_id  # noqa: E402
from kamba_core.storage.chave import nova_chave  # noqa: E402
from kamba_core.storage.port import Ctx  # noqa: E402

AGORA = datetime.datetime.now(datetime.UTC)

#: O caminho valido ate cada estado, pela tabela do KAM-049.
CAMINHOS = {
    estados.RECEBIDA: (),
    estados.A_PERGUNTAR: (estados.EM_EXTRACCAO, estados.A_PERGUNTAR),
    estados.RASCUNHO: (estados.EM_EXTRACCAO, estados.RASCUNHO),
    estados.BLOQUEADA_GATE: (estados.BLOQUEADA_GATE,),
    estados.BLOQUEADA_CATEGORIA: (estados.EM_EXTRACCAO, estados.BLOQUEADA_CATEGORIA),
}


class TestLeiturasDoCatalogoDoDono(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        self.conversa = self.criar_conversa()
        self.tenant = self.conversa.tenant_id
        self.dono = self.conversa.contact_id
        self.semente.execute(
            "UPDATE platform.contacts SET papel = 'dono' WHERE tenant_id = %s AND contact_id = %s",
            (self.tenant, self.dono),
        )
        self.outro = factories.tenant(self.semente)
        self._tenants.append(self.outro)
        # As linhas destas tabelas apagam-se antes dos contactos e dos tenants: a
        # limpeza do `ComAgr` foi registada primeiro, e corre depois desta.
        self.addCleanup(self._limpar_catalogo)
        self.app = self.ligar("app")

    def _limpar_catalogo(self) -> None:
        for tenant in self._tenants:
            for tabela in ("owner_actions", "catalog_ingestions"):
                self.semente.execute(f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (tenant,))

    def _ingestao(self, tenant: str, estado: str, media: str, *, regra: str = "alcool", sobre: object = None) -> Ingestao:
        repo = repositorio_sobre(self.app if sobre is None else sobre)
        linha = repo.inserir(
            Ingestao(
                id=novo_id(),
                tenant_id=tenant,
                media_ref=nova_chave(Ctx(tenant), "catalogo", AGORA),
                media_id_meta=media,
            )
        )
        for seguinte in CAMINHOS[estado]:
            extra: dict[str, object] = {}
            if seguinte == estados.BLOQUEADA_CATEGORIA:
                extra["categoria_restrita"] = regra
            if seguinte == estados.A_PERGUNTAR:
                extra["campos_em_falta"] = ("preco_tipo",)
                extra["perguntas_feitas"] = 1
            linha = repo.gravar(linha, replace(linha, estado=seguinte, **extra))
        return linha

    def test_contagens_e_rascunhos_a_espera_so_deste_tenant(self) -> None:
        feitas = {
            estados.A_PERGUNTAR: 2,
            estados.RASCUNHO: 1,
            estados.BLOQUEADA_CATEGORIA: 1,
            estados.BLOQUEADA_GATE: 1,
            estados.RECEBIDA: 1,
        }
        criadas = []
        n = 0
        for estado, quantas in feitas.items():
            for _ in range(quantas):
                n += 1
                criadas.append(self._ingestao(self.tenant, estado, f"m{n}"))
        self._ingestao(self.outro, estados.A_PERGUNTAR, "m-outro")
        por_estado, pendentes = catalogo_tools.ler_estado(self.app, self.tenant)
        self.assertEqual(por_estado, feitas)
        a_espera = {i.id for i in criadas if i.estado in (estados.A_PERGUNTAR, estados.RASCUNHO)}
        self.assertEqual({i for i, _e in pendentes}, a_espera)
        self.assertEqual(len(pendentes), 3)
        # O outro tenant ve so a sua.
        por_estado_b, pendentes_b = catalogo_tools.ler_estado(self.app, self.outro)
        self.assertEqual((por_estado_b, len(pendentes_b)), ({estados.A_PERGUNTAR: 1}, 1))

    def test_a_bloqueada_sem_decisao_do_screening_espera_pelo_dono(self) -> None:
        """KAM-244: a `bloqueada_categoria` com uma das `REGRAS_RETOMAVEIS` entra nos pendentes.

        A de uma decisao (`alcool`) continua de fora, e a do outro tenant tambem.
        """
        retomaveis = [
            self._ingestao(self.tenant, estados.BLOQUEADA_CATEGORIA, f"r{n}", regra=regra)
            for n, regra in enumerate(REGRAS_RETOMAVEIS)
        ]
        self._ingestao(self.tenant, estados.BLOQUEADA_CATEGORIA, "decidida")
        self._ingestao(self.outro, estados.BLOQUEADA_CATEGORIA, "r-outro", regra=REGRAS_RETOMAVEIS[0])
        _por_estado, pendentes = catalogo_tools.ler_estado(self.app, self.tenant)
        self.assertEqual({i for i, _e in pendentes}, {i.id for i in retomaveis})
        self.assertEqual({e for _i, e in pendentes}, {estados.BLOQUEADA_CATEGORIA})

    def test_o_repositorio_sobre_a_tomada_le_a_ligacao_de_agora(self) -> None:
        """KAM-244: depois de a tomada mudar, o repositorio escreve na retomada, sob RLS."""
        outra = self.ligar("app")
        tomada = TomadaDaInvocacao(self.app, lambda trabalho: (trabalho(), outra))
        linha = self._ingestao(self.tenant, estados.RECEBIDA, "t1", sobre=tomada)
        tomada.fora_da_ligacao(lambda: None)
        self.assertIs(tomada.ligacao, outra)
        repo = repositorio_sobre(tomada)
        gravada = repo.gravar(linha, replace(linha, estado=estados.EM_EXTRACCAO))
        self.assertEqual(repo.ler(self.tenant, linha.id), gravada)
        self.assertIsNone(repo.ler(self.outro, linha.id))

    def test_a_accao_de_publicar_le_se_com_o_ref_e_a_confirmacao_e_so_neste_tenant(self) -> None:
        ingestao = self._ingestao(self.tenant, estados.RASCUNHO, "m1")
        ref = f"{ingestao.id}:{'a' * 16}"
        action_id = accoes.propor(self.app, self.tenant, self.dono, catalogo_tools.TIPO_DA_ACCAO, ref, AGORA)
        lida = catalogo_tools.ler_accao(self.app, self.tenant, action_id)
        self.assertEqual(lida[:4], (catalogo_tools.TIPO_DA_ACCAO, ref, "pendente", self.dono.lower()))  # type: ignore[index]
        self.assertIsNone(lida[4])  # type: ignore[index]
        # O prazo vem com ela: e por ele que o executor sabe se ainda serve.
        self.assertGreater(lida[5], AGORA)  # type: ignore[index]
        self.assertEqual(
            accoes.confirmar(self.app, self.tenant, self.dono, f"confirm:{action_id}", AGORA), accoes.CONFIRMADA
        )
        confirmada = catalogo_tools.ler_accao(self.app, self.tenant, action_id)
        self.assertEqual(confirmada[2], "confirmada")  # type: ignore[index]
        self.assertIsNotNone(confirmada[4])  # type: ignore[index]
        self.assertIsNone(catalogo_tools.ler_accao(self.app, self.outro, action_id))

    def test_o_repositorio_sobre_a_ligacao_da_toollayer_nao_a_fecha(self) -> None:
        linha = self._ingestao(self.tenant, estados.RECEBIDA, "m1")
        repo = repositorio_sobre(self.app)
        self.assertEqual(repo.ler(self.tenant, linha.id), linha)
        self.assertIsNone(repo.ler(self.outro, linha.id))
        # A mesma tomada continua a servir a seguinte invocacao.
        self.assertEqual(repo.por_media(self.tenant, "m1"), linha)
