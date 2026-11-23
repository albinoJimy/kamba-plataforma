"""O canal do dono no AGR (KAM-118): porta, registo, grafo, allowlist, ritmo e botoes.

    TestPorta              `persona` opcional: ausente e `cliente`, fora da lista recusa
    TestChaveDoRegisto     a matriz papel x vertical do canal, no `resolve` e na `da_thread`
    TestRetomaPeloPapel    a retoma pelo papel de agora, e nao pelo do *checkpoint* (KAM-211)
    TestAllowlistDoDono    50 tentativas de um cliente: 0 sucessos, erro tipado, auditoria
    TestGrafoDoDono        compila, seis nos, reaproveitamento >= 70%, um turno ponta a ponta
    TestRitmoDoDono        60/h pelo mesmo mecanismo do ritmo, so para a persona `dono`
    TestAccoesSensiveis    o botao `confirm:{action_id}`, contra um duplo da base
    TestBotaoNaInvocacao   o `agent_invocation.botao` (KAM-211): forma, e so em `interactive`
    TestBotaoNoGrafoDoDono o botao pelo turno do dono ate ao `confirmar` (KAM-211)
    TestBotaoPeloContrato  o corpo que o CHR monta, lido pelo AGR ate ao `confirmar` (KAM-211)

A suite contra PostgreSQL das accoes esta em `db/tests_agr/test_owner_actions.py`:
o `UPDATE ... RETURNING` concorrente e a RLS nao se provam com um duplo.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import re
import unittest
import uuid
from typing import Any

from apoio import Relogio, invocacao_crua
from kamba_agr import grafos as grafos_mod
from kamba_agr import registo
from kamba_agr.admissao import JANELA_DO_DONO_S, RITMO_DO_DONO_POR_HORA, Admissao, Tectos
from kamba_agr.contexto import (
    CAMPOS,
    CHAVE_DO_DONO,
    PERSONA_POR_OMISSAO,
    InvocacaoInvalidaError,
    chave_do_registo,
    ler_invocacao,
)
from kamba_agr.dono import accoes
from kamba_agr.estado import estado_inicial
from kamba_agr.metricas import METRICAS
from kamba_agr.registo.validar import NOS_OBRIGATORIOS, nos_do_grafo
from kamba_agr.tls import auditoria, erros
from kamba_agr.tls.catalogo import ESPECIFICACOES_DO_PILOTO, catalogo_do_piloto
from kamba_agr.tls.contexto import Confirmation
from kamba_agr.tls.especificacoes import EspecificacaoDeTool, EspecificacaoInvalidaError
from kamba_agr.verticais.dono import arestas as tabela_do_dono
from kamba_agr.verticais.dono import encaminhadores as enc_do_dono
from kamba_agr.verticais.dono import nos as nos_do_dono
from kamba_agr.verticais.vendedor import encaminhadores as enc_do_vendedor
from kamba_agr.verticais.vendedor import nos as nos_do_vendedor
from test_grafos import PASTA, RAIZ, _config, _estado_com_texto, _papeis, _porta
from test_tls import (
    CONTACTO,
    ArgumentosDeEnsaio,
    _Base,
    _chave_do_sql,
    _Cursor,
    _executor_ok,
    _Ligacao,
    contexto,
)

TOOLS_DO_DONO_SO = ("create_product_draft", "ask_missing_fields", "publish_product", "get_catalog_status")


def _inv(**sobrepor: Any):
    return ler_invocacao(invocacao_crua(**sobrepor))


# ------------------------------------------------------------------ a porta


class TestPorta(unittest.TestCase):
    def test_sem_o_campo_a_persona_e_cliente(self) -> None:
        """O corpo de um CHR anterior ao KAM-118 continua a ler-se, como cliente."""
        corpo = invocacao_crua()
        self.assertNotIn("persona", corpo)
        invocacao = ler_invocacao(corpo)
        self.assertEqual(invocacao.persona, "cliente")
        self.assertEqual(PERSONA_POR_OMISSAO, "cliente")
        self.assertEqual(invocacao.chave_do_registo, invocacao.vertical)

    def test_com_o_campo_le_se_as_duas(self) -> None:
        for persona in ("cliente", "dono"):
            with self.subTest(persona=persona):
                self.assertEqual(_inv(persona=persona).persona, persona)

    def test_um_valor_fora_da_lista_recusa_com_o_codigo_do_campo(self) -> None:
        for valor in ("DONO", "admin", "", " dono", None, 1, True, ["dono"], {"x": 1}):
            with self.subTest(valor=valor), self.assertRaises(InvocacaoInvalidaError) as apanhado:
                ler_invocacao(invocacao_crua(persona=valor))
            self.assertEqual(apanhado.exception.codigo, "campo_invalido_persona")

    def test_a_persona_nao_e_campo_obrigatorio_nem_abre_a_porta_a_outros(self) -> None:
        self.assertNotIn("persona", CAMPOS)
        corpo = invocacao_crua(persona="dono")
        corpo["papel"] = "dono"
        with self.assertRaises(InvocacaoInvalidaError) as apanhado:
            ler_invocacao(corpo)
        self.assertEqual(apanhado.exception.codigo, "campo_desconhecido")

    def test_a_vertical_dono_continua_recusada(self) -> None:
        """A persona nao e vertical de canal: `vertical: dono` nao passa a porta."""
        with self.assertRaises(InvocacaoInvalidaError) as apanhado:
            ler_invocacao(invocacao_crua(vertical="dono"))
        self.assertEqual(apanhado.exception.codigo, "campo_invalido_vertical")

    def test_a_persona_e_imutavel_e_vai_para_o_estado(self) -> None:
        invocacao = _inv(persona="dono")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            invocacao.persona = "cliente"  # type: ignore[misc]
        estado = estado_inicial(invocacao)
        self.assertEqual(estado["persona"], "dono")
        # A vertical do estado e a do canal, e nao a persona.
        self.assertEqual(estado["vertical"], "vendedor")


# --------------------------------------------------------- a chave do registo


def _agentes_com(permitidos: set[str]) -> registo.AgentRegistry:
    def ler(_tenant_id: str, modulo: str) -> Any:
        return type("E", (), {"permitido": modulo in permitidos})()

    agentes = registo.AgentRegistry(ler)
    agentes.load_all(
        registo.AmbienteDoRegisto.do_repositorio(
            RAIZ,
            {"KAMBA_FASE": "piloto"},
            catalogo=catalogo_do_piloto(),
            construir_grafo=grafos_mod.para_validar,
        ),
        PASTA,
    )
    return agentes


class TestChaveDoRegisto(unittest.TestCase):
    #: (persona, vertical do canal) -> chave. A persona ausente e a omissao.
    MATRIZ = {
        (None, "vendedor"): "vendedor",
        (None, "servicos"): "servicos",
        ("cliente", "vendedor"): "vendedor",
        ("cliente", "servicos"): "servicos",
        ("dono", "vendedor"): "dono",
        ("dono", "servicos"): "dono",
    }

    def test_a_matriz_papel_por_vertical(self) -> None:
        for (persona, vertical), esperada in self.MATRIZ.items():
            with self.subTest(persona=persona, vertical=vertical):
                sobrepor = {"vertical": vertical}
                if persona is not None:
                    sobrepor["persona"] = persona
                invocacao = _inv(**sobrepor)
                self.assertEqual(invocacao.chave_do_registo, esperada)
                self.assertEqual(chave_do_registo(persona, vertical), esperada)

    def test_um_checkpoint_sem_persona_da_a_vertical(self) -> None:
        self.assertEqual(chave_do_registo(None, "servicos"), "servicos")
        self.assertEqual(chave_do_registo("dono", None), CHAVE_DO_DONO)
        self.assertEqual(chave_do_registo(None, None), "")

    def test_o_dono_de_um_tenant_sem_catalogo_e_atendido(self) -> None:
        """Decisao do fundador de 2026-11-18: o Assistente do Dono serve todo o dono.

        Sem o `catalogo`, e com os modulos dos dois canais, o dono resolve o
        registo dele nos dois, e o cliente o do canal.
        """
        agentes = _agentes_com({"vendedor", "servicos"})
        for vertical in ("vendedor", "servicos"):
            with self.subTest(vertical=vertical):
                self.assertEqual(
                    agentes.resolve(_inv(vertical=vertical, persona="dono")).vertical.id, "dono"
                )
                self.assertEqual(
                    agentes.resolve(_inv(vertical=vertical, persona="cliente")).vertical.id,
                    vertical,
                )

    def test_o_entitlement_do_dono_e_o_do_canal(self) -> None:
        """O dono herda o modulo do canal: sem ele, e recusado como o cliente.

        O tenant tem o `catalogo` e o `vendedor`, e nao o `servicos`: o dono
        que escreve no canal de Servicos e recusado, e o `catalogo` nao o abre.
        """
        agentes = _agentes_com({"vendedor", "catalogo"})
        self.assertEqual(agentes.resolve(_inv(vertical="vendedor", persona="dono")).vertical.id, "dono")
        for persona in ("dono", "cliente"):
            with self.subTest(persona=persona):
                recusa = agentes.resolve(_inv(vertical="servicos", persona=persona))
                self.assertIsNone(recusa.vertical)
                self.assertEqual(recusa.motivo, "sem_entitlement")

    def test_so_a_persona_do_dono_pode_omitir_o_modulo(self) -> None:
        """Uma vertical de canal sem `entitlements.modulo` nao arranca."""
        caminho = RAIZ / "registry" / "vendedor.yaml"
        documento = registo.esquema.ler_yaml(caminho)
        documento["entitlements"] = {
            k: v for k, v in documento["entitlements"].items() if k != "modulo"
        }
        with self.assertRaises(registo.esquema.FicheiroIlegivelError) as capturado:
            registo.esquema.ler_vertical(caminho, documento)
        self.assertIn("entitlements.modulo", str(capturado.exception))
        do_dono = registo.esquema.ler_vertical(
            RAIZ / "registry" / "dono.yaml",
            registo.esquema.ler_yaml(RAIZ / "registry" / "dono.yaml"),
        )
        self.assertIsNone(do_dono.entitlements.modulo)

    def test_o_turno_e_a_thread_do_dono_resolvem_o_grafo_do_dono(self) -> None:
        """A `da_thread` reencontra o grafo do dono enquanto o contacto o e."""
        dono = _inv(persona="dono")
        porta, compilados, saida = _porta(
            permitidos={"vendedor", "servicos", "catalogo"},
            papel=_papeis({(dono.tenant_id, dono.contact_id): "dono"}),
        )
        grafo = asyncio.run(porta.do_turno(dono))
        self.assertIs(grafo._grafo, compilados["dono"])
        asyncio.run(grafo.ainvoke(_estado_com_texto(dono, "ola"), _config(dono)))
        self.assertIs(asyncio.run(porta.da_thread(dono.thread_id)), compilados["dono"])

        # O mesmo par (tenant, contacto) como cliente cai no grafo do canal.
        cliente = _inv(
            tenant_id=dono.tenant_id, contact_id=dono.contact_id, persona="cliente"
        )
        grafo = asyncio.run(porta.do_turno(cliente))
        self.assertIs(grafo._grafo, compilados["vendedor"])


class TestRetomaPeloPapel(unittest.TestCase):
    """KAM-211, criterio «Retoma» (achado 4 da revisao do KAM-118).

    Uma *thread* interrompida retoma no grafo do papel **actual** do contacto, e
    nao no da persona guardada no *checkpoint*: depois de uma troca de telefone,
    o *handoff* do dono antigo retoma como `cliente`.
    """

    def _dono_em_handoff(self, papeis: dict):
        """Um turno do dono que para em `handoff_wait`; o papel le-se de `papeis`."""
        from test_vendedor import Handoff

        dono = _inv(persona="dono")
        papeis[(dono.tenant_id, dono.contact_id)] = "dono"
        porta, compilados, _ = _porta(
            permitidos={"vendedor", "servicos", "catalogo"},
            papel=_papeis_vivos(papeis),
            hnd=Handoff(),
        )
        grafo = asyncio.run(porta.do_turno(dono))
        self.assertIs(grafo._grafo, compilados["dono"])
        asyncio.run(
            grafo.ainvoke(_estado_com_texto(dono, "quero falar com um humano"), _config(dono))
        )
        foto = asyncio.run(compilados["dono"].aget_state(_config(dono)))
        self.assertEqual(foto.next, ("handoff_wait",))
        self.assertEqual(foto.values["persona"], "dono")
        return dono, porta, compilados

    def test_depois_da_troca_o_handoff_do_dono_antigo_retoma_como_cliente(self) -> None:
        from kamba_agr.handoff.retoma import Retomador
        from test_handoff import BaseFalsa

        papeis: dict = {}
        dono, porta, compilados = self._dono_em_handoff(papeis)
        # A troca de telefone: a `definir_dono` passou o contacto a `cliente`.
        papeis[(dono.tenant_id, dono.contact_id)] = "cliente"

        base = BaseFalsa(
            {"h1": {"tenant": dono.tenant_id, "status": "waiting"}},
            {"h1": dono.contact_id},
        )
        resolvidos: list[Any] = []

        async def grafos(thread_id: str):
            grafo = await porta.da_thread(thread_id)
            resolvidos.append(grafo)
            return grafo

        retomador = Retomador(abrir_ligacao=lambda: base, grafos=grafos)
        self.assertEqual(
            asyncio.run(retomador.retomar(dono.thread_id, "h1", "resolved")), "retomado"
        )
        self.assertEqual(resolvidos, [compilados["vendedor"]])
        self.assertEqual(asyncio.run(compilados["vendedor"].aget_state(_config(dono))).next, ())

    def test_sem_troca_o_handoff_do_dono_retoma_no_grafo_do_dono(self) -> None:
        papeis: dict = {}
        dono, porta, compilados = self._dono_em_handoff(papeis)
        self.assertIs(asyncio.run(porta.da_thread(dono.thread_id)), compilados["dono"])

    def test_o_cliente_que_passou_a_dono_retoma_no_grafo_do_dono(self) -> None:
        """O sentido contrario: o *checkpoint* diz `cliente`, e o contacto ja foi
        promovido pelo OTP. O grafo e o do papel de agora."""
        cliente = _inv(persona="cliente")
        papeis: dict = {}
        porta, compilados, _ = _porta(
            permitidos={"vendedor", "servicos", "catalogo"}, papel=_papeis_vivos(papeis)
        )
        grafo = asyncio.run(porta.do_turno(cliente))
        asyncio.run(grafo.ainvoke(_estado_com_texto(cliente, "ola"), _config(cliente)))
        self.assertIs(asyncio.run(porta.da_thread(cliente.thread_id)), compilados["vendedor"])
        papeis[(cliente.tenant_id, cliente.contact_id)] = "dono"
        self.assertIs(asyncio.run(porta.da_thread(cliente.thread_id)), compilados["dono"])

    def test_so_o_papel_exacto_dono_da_o_grafo_do_dono(self) -> None:
        """Lista de permitidos: `None` (apagado, fundido, ou que a RLS esconde) e
        qualquer outro valor dao a vertical do canal."""
        papeis: dict = {}
        dono, porta, compilados = self._dono_em_handoff(papeis)
        for papel in (None, "", "Dono", "DONO", "admin", "dono ", 1, True):
            with self.subTest(papel=papel):
                papeis[(dono.tenant_id, dono.contact_id)] = papel
                self.assertIs(asyncio.run(porta.da_thread(dono.thread_id)), compilados["vendedor"])

    def test_o_papel_le_se_com_o_par_da_thread(self) -> None:
        lidos: list[tuple[str, str]] = []

        async def papel(tenant_id: str, contact_id: str) -> str:
            lidos.append((tenant_id, contact_id))
            return "cliente"

        dono = _inv(persona="dono")
        porta, _, _ = _porta(permitidos={"vendedor", "servicos", "catalogo"}, papel=papel)
        grafo = asyncio.run(porta.do_turno(dono))
        asyncio.run(grafo.ainvoke(_estado_com_texto(dono, "ola"), _config(dono)))
        asyncio.run(porta.da_thread(dono.thread_id))
        self.assertEqual(lidos, [(dono.tenant_id, dono.contact_id)])

    def test_uma_leitura_do_papel_que_falha_nao_abre_a_base_do_cas(self) -> None:
        """A leitura do papel e antes do CAS: falhando, sobe, e a retoma nao
        escreve nada — a rota responde 503 e o *handoff* fica `waiting`."""
        from kamba_agr.handoff.retoma import Retomador

        class BaseEmBaixo(RuntimeError):
            pass

        async def papel(_tenant_id: str, _contact_id: str) -> str:
            raise BaseEmBaixo("ligacao_recusada")

        dono = _inv(persona="dono")
        porta, _, _ = _porta(permitidos={"vendedor", "servicos", "catalogo"}, papel=papel)
        grafo = asyncio.run(porta.do_turno(dono))
        asyncio.run(grafo.ainvoke(_estado_com_texto(dono, "ola"), _config(dono)))
        aberturas: list[int] = []
        retomador = Retomador(abrir_ligacao=lambda: aberturas.append(1), grafos=porta.da_thread)
        with self.assertRaises(BaseEmBaixo):
            asyncio.run(retomador.retomar(dono.thread_id, "h1", "resolved"))
        self.assertEqual(aberturas, [])

    def test_um_thread_id_que_nao_e_um_par_nao_le_o_papel(self) -> None:
        from kamba_agr.turno import GrafoNaoRegistadoError

        lidos: list[Any] = []

        async def papel(*par: str) -> str:
            lidos.append(par)
            return "dono"

        porta, compilados, _ = _porta(papel=papel)
        for thread_id in ("sem-separador", ":so-contacto", "so-tenant:", "a:b:c"):
            # Um *checkpoint* com esse `thread_id`, para a recusa ser do par e
            # nao da falta de *checkpoint*.
            asyncio.run(
                compilados["vendedor"].aupdate_state(
                    {"configurable": {"thread_id": thread_id}},
                    {"vertical": "vendedor", "persona": "dono"},
                )
            )
            with self.subTest(thread_id=thread_id):
                with self.assertRaises(GrafoNaoRegistadoError):
                    asyncio.run(porta.da_thread(thread_id))
        self.assertEqual(lidos, [])


def _papeis_vivos(papeis: dict):
    """Como `_papeis`, mas le o dicionario em cada chamada: o ensaio muda-o a meio."""

    async def papel(tenant_id: str, contact_id: str) -> object:
        return papeis.get((tenant_id, contact_id))

    return papel


# --------------------------------- as tools do dono, pelo modulo de cada uma


class _CursorDosModulos(_Cursor):
    """Responde ao entitlement **pelo modulo pedido** (o segundo parametro).

    O duplo da `test_tls` responde o mesmo a todo o modulo; aqui a resposta e a
    do modulo que o `SQL_ENTITLEMENT` leva, e por isso um passo 2 que pedisse o
    modulo errado (o do canal, em vez do da tool) dava outra resposta.
    """

    def execute(self, sql: str, parametros: Any = ()) -> None:
        if _chave_do_sql(sql) == "entitlement":
            self._ligacao.sql.append((sql, tuple(parametros)))
            modulo = tuple(parametros)[1]
            self.description = [("permitido",), ("modulo",)]
            self._linhas = [(modulo in self._ligacao.modulos, modulo)]
            return
        super().execute(sql, parametros)


class _LigacaoDosModulos(_Ligacao):
    def __init__(self, modulos: set[str]) -> None:
        super().__init__()
        self.modulos = modulos

    def cursor(self) -> _CursorDosModulos:
        return _CursorDosModulos(self)

    def nova_vaga(self) -> "_LigacaoDosModulos":
        return self

    def modulos_pedidos(self) -> list[str]:
        return [p[1] for sql, p in self.sql if _chave_do_sql(sql) == "entitlement"]


def _ligada(nome: str, modulo: str | None) -> EspecificacaoDeTool:
    """Uma tool do dono **ligada** para o ensaio, com o modulo que o catalogo lhe da."""
    return EspecificacaoDeTool(
        nome=nome,
        klass="read",
        backend="plataforma",
        modelo=ArgumentosDeEnsaio,
        executor=_executor_ok,
        modulo=modulo,
    )


class TestModulosDasToolsDoDono(_Base):
    """Decisao do fundador de 2026-11-18: cada tool fecha-se pelo seu modulo.

    As quatro do catalogo estao **declaradas** no catalogo real (credor
    KAM-119), e o passo 1 recusa-as antes do 2. O ensaio liga-as aqui com o
    `modulo` que o catalogo real lhes da, que e o que o KAM-119 herda.
    """

    def _camada(self, modulos: set[str]):
        do_catalogo = catalogo_do_piloto()
        especificacoes = tuple(
            _ligada(nome, do_catalogo[nome].modulo) for nome in ("get_catalog_status", "ask_missing_fields")
        ) + (_ligada("get_store_info", do_catalogo["get_store_info"].modulo),)
        return self.camada(especificacoes=especificacoes, ligacao=_LigacaoDosModulos(modulos))

    def _invocar(self, camada, nome: str):
        return self.invocar(
            camada,
            ctx=contexto(vertical="vendedor", turn_id=f"m-{nome}"),
            name=nome,
            args={"cart_id": "c-1"},
            allowed=("get_catalog_status", "ask_missing_fields", "get_store_info"),
            confirmation=None,
            idempotency_key=None,
        )

    def test_o_catalogo_real_fecha_as_quatro_pelo_catalogo(self) -> None:
        catalogo = catalogo_do_piloto()
        for nome in TOOLS_DO_DONO_SO:
            with self.subTest(tool=nome):
                self.assertEqual(catalogo[nome].modulo, "catalogo")
        self.assertIsNone(catalogo["get_store_info"].modulo)

    def test_sem_catalogo_o_dono_e_atendido_e_as_do_catalogo_recusam(self) -> None:
        camada, ligacao, _ = self._camada({"vendedor"})
        self.assertTrue(self._invocar(camada, "get_store_info").ok)
        for nome in ("get_catalog_status", "ask_missing_fields"):
            with self.subTest(tool=nome):
                resultado = self._invocar(camada, nome)
                self.assertFalse(resultado.ok)
                self.assertEqual(resultado.error.codigo, erros.ENTITLEMENT_DENIED)
        # O passo 2 pediu o modulo de cada tool, e nao o do canal para todas.
        self.assertEqual(ligacao.modulos_pedidos(), ["vendedor", "catalogo", "catalogo"])

    def test_com_catalogo_as_do_catalogo_abrem(self) -> None:
        camada, _ligacao, _ = self._camada({"vendedor", "catalogo"})
        for nome in ("get_catalog_status", "ask_missing_fields", "get_store_info"):
            with self.subTest(tool=nome):
                self.assertTrue(self._invocar(camada, nome).ok)

    def test_o_catalogo_nao_abre_as_tools_do_canal(self) -> None:
        """Sem o modulo do canal, a `get_store_info` recusa, com ou sem `catalogo`."""
        camada, _ligacao, _ = self._camada({"catalogo"})
        resultado = self._invocar(camada, "get_store_info")
        self.assertEqual(resultado.error.codigo, erros.ENTITLEMENT_DENIED)
        self.assertTrue(self._invocar(camada, "get_catalog_status").ok)

    def test_um_modulo_que_nao_e_nome_e_recusado(self) -> None:
        with self.assertRaises(EspecificacaoInvalidaError):
            _ligada("get_catalog_status", "Catalogo AI")


# ------------------------------------------------- a allowlist, 50 tentativas


class TestAllowlistDoDono(_Base):
    """Criterio 6: um cliente que injecte o nome de uma tool do dono."""

    def test_cinquenta_tentativas_de_um_cliente_dao_zero_sucessos_e_cinquenta_linhas(self) -> None:
        camada, ligacao, _ = self.camada(especificacoes=ESPECIFICACOES_DO_PILOTO)
        allowed_do_vendedor = tuple(
            registo.esquema.ler_vertical(
                RAIZ / "registry" / "vendedor.yaml",
                registo.esquema.ler_yaml(RAIZ / "registry" / "vendedor.yaml"),
            ).tools
        )
        allowed_de_servicos = tuple(
            registo.esquema.ler_vertical(
                RAIZ / "registry" / "servicos.yaml",
                registo.esquema.ler_yaml(RAIZ / "registry" / "servicos.yaml"),
            ).tools
        )
        sucessos = 0
        codigos: set[str] = set()
        detalhes: set[str] = set()
        for n in range(50):
            nome = TOOLS_DO_DONO_SO[n % len(TOOLS_DO_DONO_SO)]
            vertical, allowed = (
                ("vendedor", allowed_do_vendedor) if n % 2 else ("servicos", allowed_de_servicos)
            )
            resultado = self.invocar(
                camada,
                ctx=contexto(vertical=vertical, turn_id=f"t-{n}"),
                name=nome,
                args={"product_id": "p-1", "tenant_id": "outro"},
                allowed=allowed,
                confirmation=Confirmation(
                    botao=f"confirm:{uuid.uuid4()}", contact_id=CONTACTO, turn_id=f"t-{n}"
                ),
                idempotency_key=f"k-{n}",
            )
            sucessos += int(resultado.ok)
            codigos.add(resultado.error.codigo)
            detalhes.add(resultado.error.detalhe.split("`")[2])
        self.assertEqual(sucessos, 0)
        self.assertEqual(codigos, {erros.TOOL_NOT_ALLOWED})
        # **A recusa e a da lista, e nao a do estado `declarada`.** As quatro
        # estao por ligar e o passo 1 recusava-as tambem ao dono, com o mesmo
        # codigo: sem afirmar o motivo, o ensaio ficava verde com a comparacao
        # com o `allowed` apagada (achado da revisao adversarial).
        self.assertEqual(detalhes, {" nao esta na lista "})
        linhas = ligacao.linhas_de_auditoria()
        self.assertEqual(len(linhas), 50)
        for parametros in linhas:
            por_nome = dict(zip(auditoria.COLUNAS, parametros, strict=True))
            self.assertIn(por_nome["tool"], TOOLS_DO_DONO_SO)
            self.assertEqual(por_nome["status"], auditoria.STATUS_ERRO)
            self.assertEqual(por_nome["error_code"], erros.TOOL_NOT_ALLOWED)
        # Nenhuma tentativa passou do passo 1: nem o entitlement foi lido.
        self.assertNotIn("entitlement", ligacao.instrucoes())

    def test_o_dono_passa_a_lista_e_para_no_estado_declarada(self) -> None:
        """O contraponto: com a lista do `dono.yaml`, a mesma tool passa a lista.

        Para no estado `declarada` — que e o que o KAM-119 liga. Prova que a
        lista do dono e outra, e nao que todas as listas recusam.
        """
        camada, _ligacao, _ = self.camada(especificacoes=ESPECIFICACOES_DO_PILOTO)
        allowed_do_dono = tuple(
            registo.esquema.ler_vertical(
                RAIZ / "registry" / "dono.yaml",
                registo.esquema.ler_yaml(RAIZ / "registry" / "dono.yaml"),
            ).tools
        )
        for n, nome in enumerate(TOOLS_DO_DONO_SO):
            with self.subTest(tool=nome):
                resultado = self.invocar(
                    camada,
                    ctx=contexto(vertical="vendedor", turn_id=f"d-{n}"),
                    name=nome,
                    args={"product_id": "p-1"},
                    allowed=allowed_do_dono,
                    confirmation=Confirmation(
                        botao=f"confirm:{uuid.uuid4()}", contact_id=CONTACTO, turn_id=f"d-{n}"
                    ),
                    idempotency_key=f"d-{n}",
                )
                self.assertFalse(resultado.ok)
                self.assertIn("declarada e por ligar", resultado.error.detalhe)

    def test_as_quatro_do_dono_estao_declaradas_com_o_credor_e_a_classe_do_documento(self) -> None:
        catalogo = catalogo_do_piloto()
        declaradas = catalogo.declaradas()
        for nome in TOOLS_DO_DONO_SO:
            with self.subTest(tool=nome):
                self.assertEqual(declaradas[nome], "KAM-119")
        self.assertEqual(catalogo["publish_product"].klass, "write")
        self.assertEqual(catalogo["create_product_draft"].klass, "write")
        self.assertEqual(catalogo["ask_missing_fields"].klass, "read")
        self.assertEqual(catalogo["get_catalog_status"].klass, "read")

    def test_nenhuma_tool_do_dono_esta_na_lista_de_um_cliente(self) -> None:
        import sys

        sys.path.insert(0, str(RAIZ / "tools"))
        import kamba_yaml

        do_dono = set(kamba_yaml.load_file(RAIZ / "registry" / "dono.yaml")["tools"])
        for vertical in ("vendedor", "servicos"):
            with self.subTest(vertical=vertical):
                do_cliente = set(kamba_yaml.load_file(RAIZ / "registry" / f"{vertical}.yaml")["tools"])
                self.assertEqual((do_dono & do_cliente) - {"get_store_info"}, set())


# ------------------------------------------------------------------ o grafo


class TestGrafoDoDono(unittest.TestCase):
    def _compilado(self) -> Any:
        from kamba_agr.verticais.dono import build_graph

        deps = nos_do_vendedor.Dependencias(tools=None, saida=grafos_mod.SaidaPorLigar())
        return build_graph(deps)

    def test_compila_com_os_seis_nos_obrigatorios(self) -> None:
        compilado = self._compilado()
        self.assertEqual(set(NOS_OBRIGATORIOS) - nos_do_grafo(compilado), set())
        self.assertEqual(nos_do_grafo(compilado), frozenset(tabela_do_dono.NOS))

    def test_as_arestas_compiladas_sao_as_da_tabela(self) -> None:
        self.assertEqual(
            tabela_do_dono.pares_do_compilado(self._compilado()), tabela_do_dono.pares()
        )

    def test_o_reaproveitamento_e_de_pelo_menos_setenta_por_cento(self) -> None:
        """Criterio 10: reutilizados / total >= 0,70, sem excepcoes no core."""
        self.assertGreaterEqual(
            tabela_do_dono.reaproveitamento(), tabela_do_dono.REAPROVEITAMENTO_MINIMO
        )
        self.assertEqual(tabela_do_dono.REAPROVEITAMENTO_MINIMO, 0.70)
        # KAM-211: o `confirm` e o quinto proprio, e o reaproveitamento passa a
        # doze em dezassete (70,6%), ainda acima do piso.
        self.assertEqual((len(tabela_do_dono.NOS_REUTILIZADOS), len(tabela_do_dono.NOS)), (12, 17))

    def test_os_reutilizados_sao_os_mesmos_objectos_do_vendedor(self) -> None:
        """Pela identidade, e nao pelo nome: uma copia contava como reuso."""
        for nome in tabela_do_dono.NOS_REUTILIZADOS:
            with self.subTest(no=nome):
                self.assertIs(nos_do_dono.NOS_DO_GRAFO[nome], nos_do_vendedor.NOS_DO_GRAFO[nome])
        proprios = set(tabela_do_dono.NOS) - set(tabela_do_dono.NOS_REUTILIZADOS)
        self.assertEqual(proprios, {"classify", "confirm", "compose", "safe_reply", "ask_repeat"})
        for nome in proprios:
            with self.subTest(no=nome):
                self.assertIsNot(nos_do_dono.NOS_DO_GRAFO[nome], nos_do_vendedor.NOS_DO_GRAFO.get(nome))
        do_vendedor = [v for v in vars(enc_do_vendedor).values() if callable(v)]
        for encaminhador in enc_do_dono.REUTILIZADOS:
            self.assertIn(encaminhador, do_vendedor)

    def test_o_registo_do_dono_passa_a_validacao_do_arranque(self) -> None:
        verticais, gates, adiadas = registo.carregar(
            registo.AmbienteDoRegisto.do_repositorio(
                RAIZ,
                {"KAMBA_FASE": "piloto"},
                catalogo=catalogo_do_piloto(),
                construir_grafo=grafos_mod.para_validar,
            ),
            PASTA,
        )
        self.assertIn("dono", verticais)
        self.assertEqual(gates["dono"].golden, verticais["dono"].golden.dataset)
        self.assertIn(("golden", "dono", "KAM-125"), {(a.validacao, a.vertical, a.credor) for a in adiadas})

    def test_nenhum_texto_do_dono_leva_digitos(self) -> None:
        textos = [
            valor
            for nome, valor in vars(nos_do_dono).items()
            if nome.startswith("MSG_") and isinstance(valor, str)
        ] + list(nos_do_dono.FRASE_DO_AVISO.values())
        self.assertGreaterEqual(len(textos), 5)
        for texto in textos:
            with self.subTest(texto=texto[:30]):
                self.assertIsNone(re.search(r"\d", texto))

    def _turno(self, texto: str) -> list[str]:
        porta, _compilados, saida = _porta(permitidos={"vendedor", "servicos", "catalogo"})
        invocacao = _inv(persona="dono")
        grafo = asyncio.run(porta.do_turno(invocacao))
        asyncio.run(grafo.ainvoke(_estado_com_texto(invocacao, texto), _config(invocacao)))
        return [t for t, _, _ in saida.enviadas]

    def test_um_pedido_do_catalogo_com_as_tools_declaradas_diz_que_o_modulo_nao_esta_activo(self) -> None:
        # KAM-119: o catalogo real deste ensaio nao traz executores, e as quatro
        # ficam declaradas; a ToolLayer recusa-as e o dono e avisado.
        from kamba_agr.verticais.dono import catalogo as catalogo_do_dono

        enviados = self._turno("quero publicar um produto novo no catalogo")
        self.assertEqual(len(enviados), 1)
        self.assertIn(catalogo_do_dono.MSG_CATALOGO_INACTIVO, enviados[0])

    def test_um_sim_por_texto_nao_chama_tool_nenhuma(self) -> None:
        import test_grafos

        enviados = self._turno("sim, confirmo")
        self.assertEqual(len(enviados), 1)
        backend = test_grafos._ULTIMO_BACKEND[0]
        self.assertEqual(backend.chamadas, {})

    def test_o_classify_nao_aceita_intencao_fora_da_lista(self) -> None:
        deps = nos_do_vendedor.Dependencias(
            tools=None, saida=grafos_mod.SaidaPorLigar(), classificador=lambda _t: "comprar"
        )
        no = nos_do_dono.classify(deps)
        estado = {"messages": [{"role": "user", "content": "bla"}], "input_kind": "text"}
        self.assertEqual(asyncio.run(no(estado))["intent"], "outro")
        self.assertEqual(enc_do_dono.r_intent({"intent": "comprar"}), "other")


# ------------------------------------------------------------------ o ritmo


class TestRitmoDoDono(unittest.TestCase):
    def setUp(self) -> None:
        METRICAS.repor()
        self.relogio = Relogio()
        self.admissao = Admissao(tectos=Tectos(), relogio=self.relogio)

    def _sessenta_em_tres_minutos(self, **sobrepor: Any) -> tuple[str, str, list[bool]]:
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        aceites = []
        for minuto in range(3):
            for _ in range(20):
                aceites.append(
                    self.admissao.aceita_o_ritmo(
                        _inv(tenant_id=tenant, contact_id=contacto, **sobrepor)
                    )
                )
            self.relogio.avancar(60.5)
        return tenant, contacto, aceites

    def test_o_dono_passa_sessenta_numa_hora_e_a_seguinte_e_descartada(self) -> None:
        self.assertEqual(RITMO_DO_DONO_POR_HORA, 60)
        tenant, contacto, aceites = self._sessenta_em_tres_minutos(persona="dono")
        self.assertEqual(aceites, [True] * 60)
        self.assertFalse(
            self.admissao.aceita_o_ritmo(_inv(tenant_id=tenant, contact_id=contacto, persona="dono"))
        )
        # Passada a hora desde a primeira, volta a haver quota.
        self.relogio.avancar(JANELA_DO_DONO_S)
        self.assertTrue(
            self.admissao.aceita_o_ritmo(_inv(tenant_id=tenant, contact_id=contacto, persona="dono"))
        )

    def test_um_cliente_nao_paga_a_janela_da_hora(self) -> None:
        tenant, contacto, aceites = self._sessenta_em_tres_minutos(persona="cliente")
        self.assertEqual(aceites, [True] * 60)
        self.assertTrue(
            self.admissao.aceita_o_ritmo(_inv(tenant_id=tenant, contact_id=contacto))
        )

    def test_o_dono_continua_a_pagar_a_janela_do_minuto(self) -> None:
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        aceites = [
            self.admissao.aceita_o_ritmo(_inv(tenant_id=tenant, contact_id=contacto, persona="dono"))
            for _ in range(21)
        ]
        self.assertEqual(aceites, [True] * 20 + [False])

    def test_a_reentrega_do_mesmo_turno_nao_gasta_quota_da_hora(self) -> None:
        corpo = invocacao_crua(persona="dono")
        for _ in range(100):
            self.relogio.avancar(61)
            self.assertTrue(self.admissao.aceita_o_ritmo(ler_invocacao(corpo)))

    def test_o_tecto_le_se_do_ambiente_e_zero_e_sem_tecto(self) -> None:
        self.assertEqual(
            Tectos.do_ambiente({"AGR_RITMO_DO_DONO_POR_HORA": "5"}).ritmo_do_dono_por_hora, 5
        )
        admissao = Admissao(tectos=Tectos(ritmo_do_dono_por_hora=0), relogio=self.relogio)
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        for _ in range(4):
            for _ in range(20):
                self.assertTrue(
                    admissao.aceita_o_ritmo(
                        _inv(tenant_id=tenant, contact_id=contacto, persona="dono")
                    )
                )
            self.relogio.avancar(60.5)


# -------------------------------------------------------- as accoes sensiveis


AGORA = datetime.datetime(2026, 11, 17, 12, 0, tzinfo=datetime.UTC)


class BaseDeAccoes:
    """`platform.contacts` e `platform.owner_actions` em memoria.

    **Executa as instrucoes do modulo, e nao respostas enlatadas**: cada
    `SQL_*` de `accoes.py` tem aqui a semantica do PostgreSQL — a `UNIQUE` do
    `ON CONFLICT`, os quatro predicados do *compare-and-set*. E por identidade
    da constante, para que uma instrucao nova sem semantica aqui levante.
    """

    def __init__(self) -> None:
        self.autocommit = False
        self.contactos: dict[tuple[str, str], dict[str, Any]] = {}
        self.accoes: dict[str, dict[str, Any]] = {}
        self.instrucoes: list[str] = []

    def contacto(self, tenant: str, papel: str = "dono", mudou: Any = None) -> str:
        contact_id = str(uuid.uuid4())
        self.contactos[(tenant, contact_id)] = {"papel": papel, "papel_mudou_at": mudou}
        return contact_id

    def cursor(self) -> "_CursorDeAccoes":
        return _CursorDeAccoes(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def confirmadas(self) -> int:
        return sum(1 for a in self.accoes.values() if a["estado"] == "confirmada")


class _CursorDeAccoes:
    def __init__(self, base: BaseDeAccoes) -> None:
        self.base = base
        self.linhas: list[tuple[Any, ...]] = []

    def execute(self, sql: str, p: tuple = ()) -> None:
        b = self.base
        b.instrucoes.append(sql)
        self.linhas = []
        if sql.startswith("SELECT set_config"):
            self.linhas = [(p[0],)]
        elif sql is accoes.SQL_PAPEL_DO_CONTACTO:
            c = b.contactos.get((p[0], p[1]))
            self.linhas = [] if c is None else [(c["papel"], c["papel_mudou_at"])]
        elif sql is accoes.SQL_PROPOR:
            tenant, contacto, tipo, ref, expira = p
            if any(a["tenant"] == tenant and a["tipo"] == tipo and a["ref"] == ref for a in b.accoes.values()):
                return
            action_id = str(uuid.uuid4())
            b.accoes[action_id] = {
                "tenant": tenant, "contacto": contacto, "tipo": tipo, "ref": ref,
                "estado": "pendente", "expira_at": expira, "confirmada_at": None,
            }
            self.linhas = [(uuid.UUID(action_id),)]
        elif sql is accoes.SQL_ACCAO_DA_REF:
            self.linhas = [
                (uuid.UUID(i),) for i, a in b.accoes.items()
                if (a["tenant"], a["tipo"], a["ref"]) == p
            ]
        elif sql is accoes.SQL_CONFIRMAR:
            quando, tenant, action_id, contacto, agora = p
            a = b.accoes.get(action_id)
            # **Cada predicado so vale se estiver no texto da instrucao**: um
            # duplo que decidisse pelos argumentos ficava verde com o
            # `AND estado = 'pendente'` apagado do SQL.
            predicados = {
                "tenant_id = %s": lambda: a["tenant"] == tenant,
                "contact_id = %s": lambda: a["contacto"] == contacto,
                "estado = 'pendente'": lambda: a["estado"] == "pendente",
                "expira_at > %s": lambda: a["expira_at"] > agora,
            }
            if a is not None and all(
                cumpre() for texto, cumpre in predicados.items() if texto in sql
            ):
                a["estado"], a["confirmada_at"] = "confirmada", quando
                self.linhas = [(uuid.UUID(action_id),)]
        elif sql is accoes.SQL_DIAGNOSTICO:
            a = b.accoes.get(p[1])
            if a is not None and a["tenant"] == p[0]:
                self.linhas = [(a["estado"], uuid.UUID(a["contacto"]), a["expira_at"])]
        elif sql is accoes.SQL_EXPIRAR:
            a = b.accoes.get(p[1])
            if a is not None and a["tenant"] == p[0] and a["estado"] == "pendente" and a["expira_at"] <= p[2]:
                a["estado"] = "expirada"
        else:
            raise AssertionError(f"instrucao sem semantica no duplo: {sql[:60]}")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.linhas[0] if self.linhas else None

    def close(self) -> None:
        return None


class TestAccoesSensiveis(unittest.TestCase):
    def setUp(self) -> None:
        self.base = BaseDeAccoes()
        self.tenant = str(uuid.uuid4())
        self.dono = self.base.contacto(self.tenant)

    def _propor(self, ref: str = "rascunho-1", contacto: str | None = None) -> str:
        return accoes.propor(
            self.base, self.tenant, contacto or self.dono, "preco_stock_em_massa", ref, AGORA
        )

    def _confirmar(self, botao: object, contacto: str | None = None, agora=AGORA) -> str:
        return accoes.confirmar(self.base, self.tenant, contacto or self.dono, botao, agora)

    def test_propor_tres_vezes_da_uma_accao(self) -> None:
        ids = {self._propor() for _ in range(3)}
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(self.base.accoes), 1)
        accao = self.base.accoes[ids.pop()]
        self.assertEqual(accao["expira_at"], AGORA + accoes.VALIDADE_DO_BOTAO)

    def test_so_o_dono_propoe(self) -> None:
        cliente = self.base.contacto(self.tenant, papel="cliente")
        with self.assertRaises(accoes.AccaoRecusadaError) as apanhado:
            self._propor(contacto=cliente)
        self.assertEqual(apanhado.exception.codigo, accoes.NAO_E_DONO)
        self.assertEqual(self.base.accoes, {})
        with self.assertRaises(ValueError):
            accoes.propor(self.base, self.tenant, self.dono, "apagar_tudo", "r", AGORA)

    def test_o_botao_confirma_e_o_duplo_toque_executa_uma_vez(self) -> None:
        action_id = self._propor()
        desfechos = [self._confirmar(f"confirm:{action_id}") for _ in range(2)]
        self.assertEqual(desfechos, [accoes.CONFIRMADA, accoes.JA_CONFIRMADA])
        self.assertEqual(desfechos.count(accoes.CONFIRMADA), 1)
        self.assertEqual(self.base.confirmadas(), 1)

    def test_vinte_textos_nao_confirmam_nada_nem_tocam_na_base(self) -> None:
        action_id = self._propor()
        textos = (
            "sim", "Sim", "SIM", "ok", "OK", "confirmo", "confirmar", "sim confirmo",
            "pode", "podes publicar", "esta bem", "ta bem", "claro", "yes", "1",
            f"sim {action_id}", f"confirmo {action_id}", f"confirm: {action_id}",
            f"confirm:{action_id.upper()}", "confirm:",
        )
        self.assertEqual(len(textos), 20)
        antes = len(self.base.instrucoes)
        for texto in textos:
            with self.subTest(texto=texto):
                self.assertEqual(self._confirmar(texto), accoes.NAO_E_BOTAO)
        self.assertEqual(len(self.base.instrucoes), antes)
        self.assertEqual(self.base.confirmadas(), 0)

    def test_o_botao_com_mais_de_quinze_minutos_expira(self) -> None:
        action_id = self._propor()
        depois = AGORA + accoes.VALIDADE_DO_BOTAO
        self.assertEqual(self._confirmar(f"confirm:{action_id}", agora=depois), accoes.EXPIRADA)
        self.assertEqual(self.base.accoes[action_id]["estado"], "expirada")
        self.assertEqual(self.base.confirmadas(), 0)
        # Um segundo antes do prazo, um outro botao ainda vale.
        outro = self._propor(ref="rascunho-2")
        quase = AGORA + accoes.VALIDADE_DO_BOTAO - datetime.timedelta(seconds=1)
        self.assertEqual(self._confirmar(f"confirm:{outro}", agora=quase), accoes.CONFIRMADA)

    def test_o_botao_de_outro_contacto_nao_confirma(self) -> None:
        action_id = self._propor()
        # Um cliente com o botao do dono: nem chega a accao.
        cliente = self.base.contacto(self.tenant, papel="cliente")
        self.assertEqual(self._confirmar(f"confirm:{action_id}", contacto=cliente), accoes.NAO_E_DONO)
        # Depois de uma troca de telefone ja fora do bloqueio, o dono novo com o
        # botao que o antigo recebeu: e de outro contacto, e nao confirma.
        self.base.contactos[(self.tenant, self.dono)]["papel"] = "cliente"
        novo = self.base.contacto(self.tenant, mudou=AGORA - datetime.timedelta(days=2))
        self.assertEqual(self._confirmar(f"confirm:{action_id}", contacto=novo), accoes.OUTRO_CONTACTO)
        # E o antigo, agora cliente, tambem nao.
        self.assertEqual(self._confirmar(f"confirm:{action_id}"), accoes.NAO_E_DONO)
        self.assertEqual(self.base.confirmadas(), 0)

    def test_um_botao_de_outro_tenant_e_desconhecido(self) -> None:
        action_id = self._propor()
        outro_tenant = str(uuid.uuid4())
        dono_b = self.base.contacto(outro_tenant)
        desfecho = accoes.confirmar(self.base, outro_tenant, dono_b, f"confirm:{action_id}", AGORA)
        self.assertEqual(desfecho, accoes.DESCONHECIDA)
        self.assertEqual(self.base.confirmadas(), 0)

    def test_depois_da_troca_de_telefone_ha_vinte_e_quatro_horas_de_bloqueio(self) -> None:
        trocou = AGORA - datetime.timedelta(hours=1)
        novo = self.base.contacto(self.tenant, mudou=trocou)
        action_id = accoes.propor(self.base, self.tenant, novo, "enviar_proposta", "p-1", AGORA)
        self.assertEqual(
            accoes.confirmar(self.base, self.tenant, novo, f"confirm:{action_id}", AGORA),
            accoes.BLOQUEADA_PELA_TROCA,
        )
        self.assertEqual(self.base.confirmadas(), 0)
        passado = trocou + accoes.BLOQUEIO_DEPOIS_DA_TROCA
        action_id = accoes.propor(self.base, self.tenant, novo, "enviar_proposta", "p-2", passado)
        self.assertEqual(
            accoes.confirmar(self.base, self.tenant, novo, f"confirm:{action_id}", passado),
            accoes.CONFIRMADA,
        )

    def test_tirar_um_predicado_do_compare_and_set_e_apanhado(self) -> None:
        """A prova de que o duplo le o texto: cada predicado e o unico que para
        um cenario, e sem ele o cenario confirma."""

        def segundo_toque(base, dono, _outro, botao):
            accoes.confirmar(base, self.tenant, dono, botao, AGORA)
            return accoes.confirmar(base, self.tenant, dono, botao, AGORA)

        def de_outro_dono(base, _dono, outro, botao):
            return accoes.confirmar(base, self.tenant, outro, botao, AGORA)

        def fora_de_prazo(base, dono, _outro, botao):
            return accoes.confirmar(base, self.tenant, dono, botao, AGORA + accoes.VALIDADE_DO_BOTAO)

        cenarios = {
            "AND estado = 'pendente' ": segundo_toque,
            "AND contact_id = %s ": de_outro_dono,
            "AND expira_at > %s ": fora_de_prazo,
        }
        original = accoes.SQL_CONFIRMAR
        for predicado, cenario in cenarios.items():
            for sql, esperado_confirma in ((original, False), (original.replace(predicado, ""), True)):
                with self.subTest(predicado=predicado, mutado=esperado_confirma):
                    accoes.SQL_CONFIRMAR = sql
                    try:
                        base = BaseDeAccoes()
                        dono = base.contacto(self.tenant)
                        outro = base.contacto(self.tenant, mudou=AGORA - datetime.timedelta(days=2))
                        action_id = accoes.propor(base, self.tenant, dono, "aprovar_conteudo", "r", AGORA)
                        desfecho = cenario(base, dono, outro, f"confirm:{action_id}")
                    finally:
                        accoes.SQL_CONFIRMAR = original
                    self.assertEqual(desfecho == accoes.CONFIRMADA, esperado_confirma, desfecho)

    def test_os_limiares_sao_os_da_proposta(self) -> None:
        self.assertEqual(accoes.VALIDADE_DO_BOTAO, datetime.timedelta(minutes=15))
        self.assertEqual(accoes.BLOQUEIO_DEPOIS_DA_TROCA, datetime.timedelta(hours=24))

    def test_um_nome_registar_nao_existe_no_modulo(self) -> None:
        """O `log_policy` reserva `registar`; o modulo nao escreve logs."""
        import inspect

        fonte = inspect.getsource(accoes)
        self.assertNotIn(".registar(", fonte)
        self.assertNotIn("logger", fonte)



# ------------------------------------------- o botao ate ao estado do turno (KAM-211)


class TestBotaoNaInvocacao(unittest.TestCase):
    """KAM-211, criterio «Botao»: o `agent_invocation.botao`, aditivo e opcional."""

    BOTAO = "confirm:3f2a1c4e-0b7d-4e8a-9c61-2d5f8e7a9b10"

    def test_sem_o_campo_o_botao_e_nenhum(self) -> None:
        self.assertIsNone(_inv().botao)
        self.assertIsNone(estado_inicial(_inv())["botao"])

    def test_numa_resposta_interactiva_o_botao_chega_ao_estado(self) -> None:
        invocacao = _inv(type="interactive", botao=self.BOTAO)
        self.assertEqual(invocacao.botao, self.BOTAO)
        estado = estado_inicial(invocacao)
        self.assertEqual(estado["botao"], self.BOTAO)
        self.assertEqual(estado["input_kind"], "interactive")
        # Nao entra na janela: e um identificador, nao texto do cliente.
        self.assertEqual(estado["messages"], [])

    def test_um_texto_com_botao_e_recusado(self) -> None:
        """O «texto que imita um botao»: o CHR nao lhe da `botao`, e um corpo
        que o traga num `text` e incoerente."""
        for tipo in ("text", "button", "outro", "image"):
            with self.subTest(type=tipo):
                with self.assertRaises(InvocacaoInvalidaError) as capturado:
                    _inv(type=tipo, botao=self.BOTAO)
                self.assertEqual(capturado.exception.codigo, "campo_invalido_botao")

    def test_um_botao_sem_a_forma_de_um_id_e_recusado(self) -> None:
        for botao in (None, "", " ", "sim confirmo", "confirm: x", "a" * 257, 7, ["x"], "olá"):
            with self.subTest(botao=botao):
                with self.assertRaises(InvocacaoInvalidaError) as capturado:
                    _inv(type="interactive", botao=botao)
                self.assertEqual(capturado.exception.codigo, "campo_invalido_botao")

    def test_o_tecto_do_botao_e_o_da_cloud_api(self) -> None:
        self.assertEqual(_inv(type="interactive", botao="a" * 256).botao, "a" * 256)

    def test_os_opcionais_sao_a_persona_o_botao_o_message_id_e_o_asset_id(self) -> None:
        # KAM-223 acrescentou o `message_id`, e o KAM-231 o `asset_id`, aditivos
        # como os outros dois.
        from kamba_agr.contexto import CAMPOS_OPCIONAIS

        self.assertEqual(CAMPOS_OPCIONAIS, ("persona", "botao", "message_id", "asset_id"))
        self.assertNotIn("botao", CAMPOS)


class TestBotaoNoGrafoDoDono(unittest.TestCase):
    """KAM-211, criterio «Botao»: o `confirm:{action_id}` pelo turno do dono ate
    ao `confirmar`, com a porta real sobre a base em memoria das accoes."""

    def setUp(self) -> None:
        self.base = BaseDeAccoes()
        self.tenant = str(uuid.uuid4())
        self.dono = self.base.contacto(self.tenant)
        self.aberturas = 0

        def abrir():
            self.aberturas += 1
            return self.base

        self.agora = AGORA
        self.porta_de_accoes = accoes.PortaDeConfirmacao(abrir, relogio=lambda: self.agora)
        self.porta, self.compilados, self.saida = _porta(
            permitidos={"vendedor", "servicos", "catalogo"},
            accoes_do_dono=self.porta_de_accoes,
        )

    def _propor(self, ref: str = "lote-1") -> str:
        return accoes.propor(
            self.base, self.tenant, self.dono, "preco_stock_em_massa", ref, AGORA
        )

    def _tocar(self, botao: str, contacto: str | None = None) -> dict[str, Any]:
        """Um turno `interactive` do dono, com um `wamid` novo — um toque."""
        invocacao = _inv(
            tenant_id=self.tenant,
            contact_id=contacto or self.dono,
            persona="dono",
            type="interactive",
            botao=botao,
        )
        grafo = asyncio.run(self.porta.do_turno(invocacao))
        self.assertIs(grafo._grafo, self.compilados["dono"])
        return asyncio.run(grafo.ainvoke(estado_inicial(invocacao), _config(invocacao)))

    def _escrever(self, texto: str) -> dict[str, Any]:
        invocacao = _inv(tenant_id=self.tenant, contact_id=self.dono, persona="dono")
        grafo = asyncio.run(self.porta.do_turno(invocacao))
        return asyncio.run(grafo.ainvoke(_estado_com_texto(invocacao, texto), _config(invocacao)))

    def test_o_botao_confirma_pelo_turno(self) -> None:
        action_id = self._propor()
        estado = self._tocar(f"confirm:{action_id}")
        self.assertEqual(estado["intent"], "confirmar")
        self.assertEqual(estado["draft"]["texto"], nos_do_dono.MSG_CONFIRMADA)
        self.assertEqual(self.base.confirmadas(), 1)
        self.assertEqual(self.base.accoes[action_id]["estado"], "confirmada")

    def test_duplo_toque_por_dois_turnos_da_uma_confirmacao(self) -> None:
        """Dois `wamid` diferentes com o mesmo botao — dois turnos — e **1**."""
        action_id = self._propor()
        textos = [self._tocar(f"confirm:{action_id}")["draft"]["texto"] for _ in range(2)]
        self.assertEqual(textos, [nos_do_dono.MSG_CONFIRMADA, nos_do_dono.MSG_JA_CONFIRMADA])
        self.assertEqual(self.base.confirmadas(), 1)

    def test_vinte_textos_pelo_turno_nao_confirmam_nem_abrem_a_base(self) -> None:
        """«sim»/«ok» por texto -> **0**/20, e o texto que imita um botao tambem:
        um turno de texto nao tem `botao`, e o `confirm` nunca corre."""
        action_id = self._propor()
        textos = (
            "sim", "Sim", "SIM", "ok", "OK", "confirmo", "confirmar", "sim confirmo",
            "pode", "podes publicar", "esta bem", "ta bem", "claro", "yes", "1",
            f"confirm:{action_id}", f"sim {action_id}", f"confirm: {action_id}",
            f"confirm:{action_id.upper()}", "confirm:",
        )
        self.assertEqual(len(textos), 20)
        for texto in textos:
            with self.subTest(texto=texto):
                estado = self._escrever(texto)
                self.assertNotEqual(estado.get("intent"), "confirmar")
        self.assertEqual(self.base.confirmadas(), 0)
        self.assertEqual(self.aberturas, 0)

    def test_o_replay_de_um_botao_antigo_expira(self) -> None:
        action_id = self._propor()
        self.agora = AGORA + accoes.VALIDADE_DO_BOTAO
        estado = self._tocar(f"confirm:{action_id}")
        self.assertEqual(estado["draft"]["texto"], nos_do_dono.MSG_EXPIRADA)
        self.assertEqual(self.base.confirmadas(), 0)

    def test_o_botao_de_outro_tenant_nao_confirma_e_nao_diz_porque(self) -> None:
        outro_tenant = str(uuid.uuid4())
        outro_dono = self.base.contacto(outro_tenant)
        alheia = accoes.propor(
            self.base, outro_tenant, outro_dono, "preco_stock_em_massa", "lote-b", AGORA
        )
        estado = self._tocar(f"confirm:{alheia}")
        self.assertEqual(estado["draft"]["texto"], nos_do_dono.MSG_PEDIDO_NAO_ENCONTRADO)
        self.assertEqual(self.base.accoes[alheia]["estado"], "pendente")

    def test_o_botao_de_outro_contacto_diz_o_mesmo_que_o_desconhecido(self) -> None:
        """Sem oraculo: `outro_contacto`, `desconhecida` e `nao_e_dono` dao a
        mesma frase."""
        action_id = self._propor()
        self.base.contactos[(self.tenant, self.dono)]["papel"] = "cliente"
        intruso = self.base.contacto(self.tenant)
        frases = {
            self._tocar(f"confirm:{action_id}", contacto=intruso)["draft"]["texto"],
            self._tocar(f"confirm:{uuid.uuid4()}")["draft"]["texto"],
        }
        self.assertEqual(frases, {nos_do_dono.MSG_PEDIDO_NAO_ENCONTRADO})
        self.assertEqual(self.base.confirmadas(), 0)

    def test_um_botao_que_nao_e_confirm_nao_chama_o_portao(self) -> None:
        estado = self._tocar("continuar")
        self.assertNotEqual(estado.get("intent"), "confirmar")
        self.assertEqual(self.aberturas, 0)

    def test_o_botao_de_um_turno_nao_vale_no_seguinte(self) -> None:
        """O `botao` e do turno: um texto depois de um toque nao herda o toque."""
        action_id = self._propor()
        self._tocar(f"confirm:{uuid.uuid4()}")
        estado = self._escrever("ok")
        self.assertIsNone(estado["botao"])
        self.assertEqual(self.base.accoes[action_id]["estado"], "pendente")

    def test_sem_porta_ligada_nada_se_confirma(self) -> None:
        porta, compilados, _ = _porta(permitidos={"vendedor", "servicos", "catalogo"})
        action_id = self._propor()
        invocacao = _inv(
            tenant_id=self.tenant, contact_id=self.dono, persona="dono",
            type="interactive", botao=f"confirm:{action_id}",
        )
        grafo = asyncio.run(porta.do_turno(invocacao))
        estado = asyncio.run(grafo.ainvoke(estado_inicial(invocacao), _config(invocacao)))
        self.assertEqual(estado["draft"]["texto"], nos_do_dono.MSG_CONFIRMACAO_INDISPONIVEL)
        self.assertEqual(self.base.confirmadas(), 0)

    def test_o_portao_recebe_o_tenant_e_o_contacto_do_estado(self) -> None:
        vistos: list[tuple] = []

        class Espiao:
            async def confirmar(self, *argumentos: Any) -> str:
                vistos.append(argumentos)
                return accoes.CONFIRMADA

        porta, _, _ = _porta(
            permitidos={"vendedor", "servicos", "catalogo"}, accoes_do_dono=Espiao()
        )
        botao = f"confirm:{uuid.uuid4()}"
        invocacao = _inv(
            tenant_id=self.tenant, contact_id=self.dono, persona="dono",
            type="interactive", botao=botao,
        )
        grafo = asyncio.run(porta.do_turno(invocacao))
        asyncio.run(grafo.ainvoke(estado_inicial(invocacao), _config(invocacao)))
        self.assertEqual(vistos, [(self.tenant, self.dono, botao)])

    def test_as_frases_da_confirmacao_nao_levam_digitos(self) -> None:
        frases = (
            nos_do_dono.MSG_CONFIRMADA, nos_do_dono.MSG_JA_CONFIRMADA,
            nos_do_dono.MSG_EXPIRADA, nos_do_dono.MSG_BLOQUEADA_PELA_TROCA,
            nos_do_dono.MSG_PEDIDO_NAO_ENCONTRADO, nos_do_dono.MSG_CONFIRMACAO_INDISPONIVEL,
        )
        for frase in frases:
            with self.subTest(frase=frase):
                self.assertIsNone(re.search(r"\d", frase))

    def test_o_classify_so_le_o_botao_num_turno_interactivo(self) -> None:
        """A barreira do proprio no, sem a guarda de entrada a frente: um texto
        com a forma `confirm:{uuid}` nao da a intencao `confirmar`, e um `botao`
        num turno que nao e `interactive` tambem nao."""
        from kamba_agr.verticais.vendedor.nos import Dependencias

        no = nos_do_dono.classify(Dependencias(tools=None, saida=None))
        botao = f"confirm:{uuid.uuid4()}"
        texto = estado_inicial(_inv(persona="dono"))
        texto["messages"] = [{"role": "user", "content": botao}]
        self.assertNotEqual(asyncio.run(no(texto))["intent"], "confirmar")
        forjado = dict(estado_inicial(_inv(persona="dono")), botao=botao)
        self.assertNotEqual(asyncio.run(no(forjado))["intent"], "confirmar")
        tocado = estado_inicial(_inv(persona="dono", type="interactive", botao=botao))
        self.assertEqual(asyncio.run(no(tocado))["intent"], "confirmar")
        # Um `interactive` sem `botao` (um `id` fora da forma, um `nfm_reply`)
        # com um `confirm:{uuid}` escrito num turno anterior na janela: nao e um
        # toque (achado 2 da revisao adversarial).
        sem_botao = estado_inicial(_inv(persona="dono", type="interactive"))
        sem_botao["messages"] = [
            {"role": "user", "content": botao},
            {"role": "assistant", "content": "resposta"},
        ]
        self.assertNotEqual(asyncio.run(no(sem_botao))["intent"], "confirmar")

    def test_a_porta_nao_abre_a_base_para_um_texto(self) -> None:
        self.assertEqual(
            asyncio.run(self.porta_de_accoes.confirmar(self.tenant, self.dono, "sim")),
            accoes.NAO_E_BOTAO,
        )
        self.assertEqual(self.aberturas, 0)


class TestBotaoPeloContrato(unittest.TestCase):
    """KAM-211, criterio «Botao», pelo caminho CHR -> AGR.

    O corpo de `packages/core-ts/tests/fixtures/invocacao_do_botao.json` e o que
    o `chr.botao.test.ts` prova sair do `Chr.tratar` para um toque no botao do
    dono. Aqui o mesmo ficheiro entra pelo `ler_invocacao` e corre o turno ate
    ao `confirmar`: duplo toque x2 -> **1** confirmacao.
    """

    def setUp(self) -> None:
        import json

        caminho = RAIZ / "packages" / "core-ts" / "tests" / "fixtures" / "invocacao_do_botao.json"
        self.fixture = json.loads(caminho.read_text(encoding="utf-8"))
        corpo = self.fixture["corpo"]
        self.base = BaseDeAccoes()
        self.tenant, self.dono = corpo["tenant_id"], corpo["contact_id"]
        self.base.contactos[(self.tenant, self.dono)] = {"papel": "dono", "papel_mudou_at": None}
        self.base.accoes[self.fixture["action_id"]] = {
            "tenant": self.tenant, "contacto": self.dono, "tipo": "preco_stock_em_massa",
            "ref": "lote-fixture", "estado": "pendente",
            "expira_at": AGORA + accoes.VALIDADE_DO_BOTAO, "confirmada_at": None,
        }
        self.porta, self.compilados, _ = _porta(
            permitidos={"vendedor", "servicos", "catalogo"},
            accoes_do_dono=accoes.PortaDeConfirmacao(lambda: self.base, relogio=lambda: AGORA),
        )

    def _turno(self, wamid: str) -> dict[str, Any]:
        invocacao = ler_invocacao(dict(self.fixture["corpo"], wamid=wamid))
        grafo = asyncio.run(self.porta.do_turno(invocacao))
        self.assertIs(grafo._grafo, self.compilados["dono"])
        return asyncio.run(grafo.ainvoke(estado_inicial(invocacao), _config(invocacao)))

    def test_o_corpo_do_chr_le_se_e_o_botao_chega_ao_estado(self) -> None:
        invocacao = ler_invocacao(self.fixture["corpo"])
        self.assertEqual(invocacao.botao, f"confirm:{self.fixture['action_id']}")
        self.assertEqual(invocacao.persona, "dono")

    def test_duplo_toque_pelo_contrato_da_uma_confirmacao(self) -> None:
        textos = [
            self._turno(self.fixture["corpo"]["wamid"])["draft"]["texto"],
            self._turno(self.fixture["corpo"]["wamid"] + "B")["draft"]["texto"],
        ]
        self.assertEqual(textos, [nos_do_dono.MSG_CONFIRMADA, nos_do_dono.MSG_JA_CONFIRMADA])
        self.assertEqual(self.base.confirmadas(), 1)


if __name__ == "__main__":
    unittest.main()
