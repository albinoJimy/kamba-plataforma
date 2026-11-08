"""A porta de destinos e o *gate* de go-live (KAM-069, criterios 2, 3 e 8).

Sem base de dados: a decisao e pura (`avaliar_destino`) e o que a liga a base e
um **leitor** injectado. E o que torna estes testes a prova do criterio 2 e nao
uma amostra dela — os cinco casos que ele pede correm aqui em milissegundos, e
o que corre contra um PostgreSQL real e o esquema, em
`db/tests/test_destinos_schema.py`.

**O caso dos tres paises e o teste mais importante deste ficheiro.** O criterio
2 pede «5 casos de teste, incluindo pais `ZA`, `DE` e `US` com `pendente`
(nenhuma adequacao e inferida)», e o que ele esta a medir nao e um `if`: e a
**ausencia** de uma lista de paises adequados no codigo. Os tres sao recusados
pela mesma razao — o estado, nao o pais —, e a prova de que nenhuma adequacao se
infere e as tres recusas serem indistinguiveis excepto no nome do pais que a
mensagem cita.
"""

from __future__ import annotations

import unittest

from kamba_core.destinos import (
    AMBIENTE_PROD,
    ESTADO_AUTORIZADO,
    FINALIDADES,
    TTL_POR_OMISSAO_MS,
    VARIAVEL_SINTETICOS,
    CacheDeDestinos,
    ConfiguracaoDeProdInvalida,
    ConfiguracaoSintetica,
    ConfiguracaoSinteticaInvalida,
    Decisao,
    DestinoActivo,
    FinalidadeDesconhecida,
    GoLiveNegado,
    PortaSobreDestinos,
    TransferenciaNegada,
    avaliar_destino,
    avaliar_go_live,
    destinos_do_tenant,
    estado_bloqueia,
    exigir_ambiente,
    exigir_go_live,
)

TENANT = "11111111-1111-4111-8111-111111111111"
OUTRO = "22222222-2222-4222-8222-222222222222"
MAPA = "1.0+0123456789ab"


def linha(
    *,
    especifica: bool = False,
    status: str = "pendente",
    tem_apd_ref: bool = False,
    country: str = "US",
) -> dict:
    return {
        "especifica": especifica,
        "status": status,
        "tem_apd_ref": tem_apd_ref,
        "country": country,
    }


AUTORIZADA = linha(status=ESTADO_AUTORIZADO, tem_apd_ref=True)


class LeitorFalso:
    """Devolve linhas fixas e **conta** as leituras.

    A contagem nao e cosmetica: e ela que prova que a *cache* evita a ida a base
    (criterio 3) e que uma finalidade fora do dominio **nao** chega a consultar
    nada — duas propriedades que uma asercao sobre o resultado nao distingue de
    uma implementacao que consulta sempre.
    """

    def __init__(self, linhas=(), erro: Exception | None = None) -> None:
        self.linhas = list(linhas)
        self.erro = erro
        self.leituras: list[tuple[str, str, str]] = []

    def __call__(self, tenant: str, fornecedor: str, finalidade: str):
        self.leituras.append((tenant, fornecedor, finalidade))
        if self.erro is not None:
            raise self.erro
        return list(self.linhas)


class TestAvaliarDestino(unittest.TestCase):
    """A regra dos cinco passos, sem *cache* e sem base."""

    def test_sem_linha_nega(self) -> None:
        decisao = avaliar_destino([], "openai", "conversa")
        self.assertFalse(decisao.autorizado)
        self.assertIn("ausencia de registo", decisao.motivo)

    def test_autorizado_com_apd_ref_passa(self) -> None:
        self.assertEqual(
            avaliar_destino([AUTORIZADA], "openai", "conversa"),
            Decisao(autorizado=True, motivo=None),
        )

    def test_os_tres_paises_pendentes_sao_os_tres_recusados(self) -> None:
        """Criterio 2: «pais `ZA`, `DE` e `US` com `pendente`».

        **Nenhuma adequacao e inferida**, e e isso que estes tres casos medem.
        A Africa do Sul e a UE sao **hipoteses** de adequacao (INDICIO,
        `docs/tecnica/08` §8.3.1) e os EUA provavelmente exigem autorizacao —
        pelo que uma implementacao que «ajudasse» tratava o `ZA` e o `DE`
        diferente do `US`. Aqui os tres sao recusados pelo **estado**, e a unica
        diferenca entre as tres mensagens e o nome do pais.
        """
        motivos = {}
        for pais in ("ZA", "DE", "US"):
            with self.subTest(pais=pais):
                decisao = avaliar_destino(
                    [linha(country=pais)], "fornecedor", "conversa"
                )
                self.assertFalse(decisao.autorizado)
                self.assertIn(f"`{pais}` esta `pendente`", decisao.motivo)
                motivos[pais] = decisao.motivo.replace(pais, "<pais>")
        self.assertEqual(len(set(motivos.values())), 1, "as recusas divergem")

    def test_revogado_e_negado_tambem_negam(self) -> None:
        for status in ("revogado", "negado"):
            with self.subTest(status=status):
                decisao = avaliar_destino(
                    [linha(status=status, tem_apd_ref=True)], "f", "conversa"
                )
                self.assertFalse(decisao.autorizado)

    def test_um_estado_desconhecido_nega(self) -> None:
        """`estado_bloqueia` pergunta «e `autorizado`?» e nao «esta na lista?».

        Um valor que uma revisao futura acrescente ao `CHECK` e que esta versao
        do codigo nao conheca **nega**. A alternativa — `status in (pendente,
        revogado, negado)` — autorizava-o.
        """
        self.assertTrue(estado_bloqueia("estado_que_ainda_nao_existe"))
        decisao = avaliar_destino(
            [linha(status="estado_que_ainda_nao_existe", tem_apd_ref=True)],
            "f",
            "conversa",
        )
        self.assertFalse(decisao.autorizado)

    def test_a_linha_do_tenant_tapa_a_global(self) -> None:
        """Passo 2: uma decisao propria do tenant tapa a configuracao global.

        Sem a precedencia, um destino **negado** por decisao do tenant passava
        pela linha global `autorizado` — o inverso do que uma decisao especifica
        significa.
        """
        decisao = avaliar_destino(
            [linha(especifica=True, status="negado"), AUTORIZADA], "f", "conversa"
        )
        self.assertFalse(decisao.autorizado)
        self.assertIn("no registo do tenant", decisao.motivo)

    def test_a_global_vale_quando_o_tenant_nao_tem_linha(self) -> None:
        """O canario do teste acima: sem linha propria, a global decide."""
        decisao = avaliar_destino([AUTORIZADA], "f", "conversa")
        self.assertTrue(decisao.autorizado)

    def test_exige_todas_e_nao_alguma(self) -> None:
        """Passo 4: a chamada nao escolhe o pais.

        Um fornecedor registado com dois paises — `ZA` autorizado e `US`
        `pendente` — pode servir de qualquer um deles. **Falha fechada sobre a
        uniao**, que e a mesma regra que o dicionario §3.29 fixa para os
        fornecedores de um alias.
        """
        decisao = avaliar_destino(
            [
                linha(status=ESTADO_AUTORIZADO, tem_apd_ref=True, country="ZA"),
                linha(country="US"),
            ],
            "f",
            "conversa",
        )
        self.assertFalse(decisao.autorizado)
        self.assertIn("`US` esta `pendente`", decisao.motivo)

    def test_autorizado_sem_apd_ref_nega(self) -> None:
        """Defesa em profundidade: a base ja o recusa, e isto tambem.

        O `tenant_destinations_autorizado_com_apd_ref_ck` da `0036` torna esta
        linha impossivel **atraves desta base**. O ramo fica porque o criterio 1
        e sobre a propriedade e nao sobre o sitio onde ela se impoe.
        """
        decisao = avaliar_destino(
            [linha(status=ESTADO_AUTORIZADO, tem_apd_ref=False)], "f", "conversa"
        )
        self.assertFalse(decisao.autorizado)
        self.assertIn("sem `apd_ref`", decisao.motivo)

    def test_uma_linha_ilegivel_nega(self) -> None:
        for quebrada in (
            {"especifica": False, "status": None, "tem_apd_ref": True, "country": "US"},
            {"especifica": False, "status": "autorizado", "tem_apd_ref": "true",
             "country": "US"},
            {"especifica": "nao", "status": "autorizado", "tem_apd_ref": True,
             "country": "US"},
        ):
            with self.subTest(linha=sorted(quebrada)):
                with self.assertRaises(TransferenciaNegada):
                    avaliar_destino([quebrada], "f", "conversa")

    def test_tem_apd_ref_em_texto_nao_passa_por_booleano(self) -> None:
        """`bool("false")` e `True`, e por isso o leitor exige o tipo.

        Uma ligacao que devolvesse o booleano como texto punha um destino **sem**
        `apd_ref` a passar — a cadeia `"false"` e verdadeira.
        """
        with self.assertRaises(TransferenciaNegada):
            avaliar_destino(
                [{"especifica": False, "status": "autorizado",
                  "tem_apd_ref": "false", "country": "US"}],
                "f",
                "conversa",
            )


class TestPortaSobreDestinos(unittest.TestCase):
    def test_autoriza_e_guarda_em_cache(self) -> None:
        leitor = LeitorFalso([AUTORIZADA])
        porta = PortaSobreDestinos(leitor)
        porta.autorizar(TENANT, "openai", "conversa")
        porta.autorizar(TENANT, "openai", "conversa")
        self.assertEqual(len(leitor.leituras), 1, "a segunda chamada foi a base")

    def test_a_finalidade_fora_do_dominio_nao_consulta_nada(self) -> None:
        """Passo 1, e a contagem e que o prova.

        Uma finalidade fora do dominio **nao tem linha onde caiba** — o `CHECK`
        da `0036` e fechado —, pelo que a consulta devolveria sempre vazio e o
        erro do chamador lia-se como «destino nao registado».
        """
        leitor = LeitorFalso([AUTORIZADA])
        porta = PortaSobreDestinos(leitor)
        with self.assertRaises(FinalidadeDesconhecida):
            porta.autorizar(TENANT, "openai", "finalidade_inventada")
        self.assertEqual(leitor.leituras, [])

    def test_a_finalidade_desconhecida_e_uma_transferencia_negada(self) -> None:
        """O efeito tem de ser o mesmo: nao sair nada.

        Um `ValueError` a subir por um caminho que apanha `TransferenciaNegada`
        escapava a barreira, e a barreira e o unico ponto deste modulo.
        """
        self.assertTrue(issubclass(FinalidadeDesconhecida, TransferenciaNegada))

    def test_um_erro_da_base_nega_e_nao_guarda(self) -> None:
        """Passo 5. Guardar uma indisponibilidade por 60 s era um corte de
        servico com a duracao do TTL."""
        leitor = LeitorFalso(erro=RuntimeError("a base nao responde"))
        porta = PortaSobreDestinos(leitor)
        with self.assertRaises(TransferenciaNegada) as apanhado:
            porta.autorizar(TENANT, "openai", "conversa")
        self.assertIn("RuntimeError", str(apanhado.exception))
        self.assertNotIn("a base nao responde", str(apanhado.exception))
        self.assertEqual(porta.cache.tamanho, 0)

    def test_um_tenant_invalido_nega_pela_porta_e_nao_por_outro_erro(self) -> None:
        leitor = LeitorFalso([AUTORIZADA])
        porta = PortaSobreDestinos(leitor)
        for tenant in (None, "", "nao-e-uuid", 42):
            with self.subTest(tenant=tenant):
                with self.assertRaises(TransferenciaNegada):
                    porta.autorizar(tenant, "openai", "conversa")
        self.assertEqual(leitor.leituras, [])

    def test_a_decisao_de_um_tenant_nao_serve_outro(self) -> None:
        leitor = LeitorFalso([AUTORIZADA])
        porta = PortaSobreDestinos(leitor)
        porta.autorizar(TENANT, "openai", "conversa")
        leitor.linhas = [linha()]
        with self.assertRaises(TransferenciaNegada):
            porta.autorizar(OUTRO, "openai", "conversa")

    def test_o_fornecedor_e_a_finalidade_entram_na_chave(self) -> None:
        leitor = LeitorFalso([AUTORIZADA])
        porta = PortaSobreDestinos(leitor)
        porta.autorizar(TENANT, "openai", "conversa")
        leitor.linhas = [linha()]
        with self.assertRaises(TransferenciaNegada):
            porta.autorizar(TENANT, "anthropic", "conversa")
        with self.assertRaises(TransferenciaNegada):
            porta.autorizar(TENANT, "openai", "embeddings")


class TestCacheDeDestinos(unittest.TestCase):
    """Criterio 3: «revogar um destino faz a chamada seguinte falhar em <= 60 s»."""

    def test_o_ttl_por_omissao_e_o_tecto_do_criterio(self) -> None:
        self.assertEqual(TTL_POR_OMISSAO_MS, 60_000)

    def test_um_ttl_acima_do_tecto_e_recusado(self) -> None:
        """Um ficheiro de configuracao com um zero a mais era a forma natural de
        passar dos 60 s sem ninguem dar por isso."""
        with self.assertRaises(ValueError):
            CacheDeDestinos(ttl_ms=TTL_POR_OMISSAO_MS + 1)
        for invalido in (0, -1, "60000", True):
            with self.subTest(ttl=invalido):
                with self.assertRaises(ValueError):
                    CacheDeDestinos(ttl_ms=invalido)

    def test_a_revogacao_e_visivel_ao_expirar_e_nao_antes(self) -> None:
        """O relogio e injectado nos **dois** lados, e tem de ser.

        A primeira versao deste teste guardava pela porta — que usa o relogio
        monotonico real — e lia com `agora=0`, pelo que comparava duas epocas
        diferentes e a entrada parecia nunca expirar. Com o instante passado nas
        duas chamadas, o que se mede e o TTL e nao o relogio da maquina.
        """
        cache = CacheDeDestinos()
        decisao = Decisao(autorizado=True, motivo=None)
        cache.guardar(TENANT, "openai", "conversa", decisao, agora=0.0)
        self.assertIsNotNone(cache.ler(TENANT, "openai", "conversa", agora=0.0))
        self.assertIsNotNone(
            cache.ler(TENANT, "openai", "conversa", agora=TTL_POR_OMISSAO_MS - 1)
        )
        # No instante do TTL, a entrada deixa de valer — `<=` e nao `<`.
        self.assertIsNone(
            cache.ler(TENANT, "openai", "conversa", agora=TTL_POR_OMISSAO_MS)
        )

    def test_a_porta_so_volta_a_base_depois_de_o_ttl_passar(self) -> None:
        """A outra metade do criterio 3, e e esta que fecha o ciclo.

        **Esta versao mede o TTL; a primeira nao media.** Ela chamava
        `cache.repor()` — e `repor()` esvazia o dicionario, que **nao e o que o
        TTL faz**. A revisao adversarial provou-o: mutando a `ler` da *cache*
        para ignorar a expiracao no caminho da porta, os 44 ensaios ficavam
        verdes — isto e, uma porta que guardasse uma autorizacao revogada **para
        sempre** era indistinguivel desta.

        O que fechou o buraco foi a costura de relogio no construtor da porta.
        Com ela, o ensaio mede as tres coisas que o criterio 3 pede:

        1. **antes** do TTL a porta nao volta a base (uma leitura, e a decisao
           velha);
        2. **no** instante do TTL volta (duas leituras);
        3. e o que ela le entao e a revogacao, pelo que passa a negar.
        """
        agora = [1_000.0]
        leitor = LeitorFalso([AUTORIZADA])
        porta = PortaSobreDestinos(leitor, CacheDeDestinos(), relogio=lambda: agora[0])
        porta.autorizar(TENANT, "openai", "conversa")
        self.assertEqual(len(leitor.leituras), 1)

        # Revogado na base. A *cache* ainda nao sabe, e ate ao TTL nao volta la.
        leitor.linhas = [linha(status="revogado", tem_apd_ref=True)]
        agora[0] += TTL_POR_OMISSAO_MS - 1
        porta.autorizar(TENANT, "openai", "conversa")
        self.assertEqual(len(leitor.leituras), 1, "foi a base antes do TTL")

        # No instante do TTL — `<=` e nao `<` — a entrada deixa de valer.
        agora[0] += 1
        with self.assertRaises(TransferenciaNegada) as apanhado:
            porta.autorizar(TENANT, "openai", "conversa")
        self.assertEqual(len(leitor.leituras), 2, "nao voltou a base depois do TTL")
        self.assertIn("`revogado`", str(apanhado.exception))

    def test_uma_cache_que_nunca_expirasse_reprovava_este_ensaio(self) -> None:
        """O canario do ensaio de cima, e e ele que o torna uma medicao.

        Constroi-se **a mutacao que a revisao adversarial usou** — uma *cache*
        cuja `ler` ignora a expiracao — e exige-se que a propriedade se perca.
        Sem isto, o ensaio de cima podia estar a medir o relogio em vez do TTL.
        """

        class CacheQueNuncaExpira(CacheDeDestinos):
            def ler(self, tenant, fornecedor, finalidade, agora=None):
                return super().ler(tenant, fornecedor, finalidade, agora=0.0)

        agora = [1_000.0]
        leitor = LeitorFalso([AUTORIZADA])
        porta = PortaSobreDestinos(
            leitor, CacheQueNuncaExpira(), relogio=lambda: agora[0]
        )
        porta.autorizar(TENANT, "openai", "conversa")
        leitor.linhas = [linha(status="revogado", tem_apd_ref=True)]
        agora[0] += TTL_POR_OMISSAO_MS * 10
        # Com a mutacao, a autorizacao revogada sobrevive — e e exactamente isto
        # que o ensaio de cima tem de recusar.
        porta.autorizar(TENANT, "openai", "conversa")
        self.assertEqual(len(leitor.leituras), 1)

    def test_invalidar_apaga_so_as_do_tenant(self) -> None:
        cache = CacheDeDestinos()
        decisao = Decisao(autorizado=True, motivo=None)
        cache.guardar(TENANT, "openai", "conversa", decisao)
        cache.guardar(OUTRO, "openai", "conversa", decisao)
        cache.invalidar(TENANT)
        self.assertIsNone(cache.ler(TENANT, "openai", "conversa"))
        self.assertIsNotNone(cache.ler(OUTRO, "openai", "conversa"))

    def test_a_cache_tem_tecto_de_entradas(self) -> None:
        cache = CacheDeDestinos(maximo=2)
        decisao = Decisao(autorizado=True, motivo=None)
        for n in range(5):
            cache.guardar(TENANT, f"fornecedor{n}", "conversa", decisao)
        self.assertLessEqual(cache.tamanho, 2)


class TestGoLive(unittest.TestCase):
    """Criterio 8."""

    def test_nada_falta_quando_tudo_esta(self) -> None:
        destinos = (DestinoActivo("openai", "conversa", ESTADO_AUTORIZADO, True),)
        self.assertEqual(avaliar_go_live(destinos, True, MAPA), ())

    def test_as_tres_faltas_aparecem_juntas(self) -> None:
        """Parar na primeira obrigava a resolver uma, voltar a correr, descobrir
        a seguinte."""
        destinos = (DestinoActivo("openai", "conversa", "pendente", False),)
        faltas = avaliar_go_live(destinos, False, None)
        self.assertEqual({f.especie for f in faltas}, {"destino", "dpa", "mapa"})

    def test_a_falta_do_dpa_nomeia_o_credor(self) -> None:
        faltas = avaliar_go_live((), False, MAPA)
        self.assertEqual(len(faltas), 1)
        self.assertIn("KAM-090", faltas[0].detalhe)

    def test_zero_destinos_nao_e_falta_de_destino(self) -> None:
        """Um tenant sem destino registado nao transfere nada para fora.

        Exigir-lhe um destino autorizado era exigir autorizacao para uma
        transferencia que nao acontece. O que o impede de activar sao as outras
        duas condicoes.
        """
        self.assertEqual(avaliar_go_live((), True, MAPA), ())

    def test_uma_referencia_de_mapa_sem_forma_e_falta(self) -> None:
        for referencia in ("v1", "ultimo", "1.0", "1.0+xyz", "1.0+0123456789", ""):
            with self.subTest(referencia=referencia):
                faltas = avaliar_go_live((), True, referencia)
                self.assertEqual([f.especie for f in faltas], ["mapa"])

    def test_uma_referencia_que_nao_e_a_do_mapa_vivo_e_falta(self) -> None:
        faltas = avaliar_go_live((), True, MAPA, mapa_esperado="1.0+ffffffffffff")
        self.assertEqual([f.especie for f in faltas], ["mapa"])

    def test_em_prod_levanta_e_fora_de_prod_avisa(self) -> None:
        destinos = (DestinoActivo("openai", "conversa", "pendente", False),)
        with self.assertRaises(GoLiveNegado) as apanhado:
            exigir_go_live(AMBIENTE_PROD, TENANT, destinos, False, None)
        self.assertEqual(len(apanhado.exception.faltas), 3)
        avisos = exigir_go_live("dev", TENANT, destinos, False, None)
        self.assertEqual(len(avisos), 3)

    def test_um_ambiente_desconhecido_e_tratado_como_prod(self) -> None:
        """Um `KAMBA_ENV=producao` escrito por engano nao pode servir a politica
        de `dev`."""
        with self.assertRaises(GoLiveNegado):
            exigir_go_live("producao", TENANT, (), False, None)

    def test_prod_recusa_arrancar_com_o_ficheiro_dos_sinteticos(self) -> None:
        with self.assertRaises(ConfiguracaoDeProdInvalida):
            exigir_ambiente(AMBIENTE_PROD, {VARIAVEL_SINTETICOS: "golive.conf"})
        with self.assertRaises(ConfiguracaoDeProdInvalida):
            exigir_ambiente("producao", {VARIAVEL_SINTETICOS: "golive.conf"})

    def test_fora_de_prod_o_ficheiro_e_aceite(self) -> None:
        for ambiente in ("dev", "staging"):
            with self.subTest(ambiente=ambiente):
                exigir_ambiente(ambiente, {VARIAVEL_SINTETICOS: "golive.conf"})

    def test_prod_sem_a_variavel_arranca(self) -> None:
        exigir_ambiente(AMBIENTE_PROD, {})
        exigir_ambiente(AMBIENTE_PROD, {VARIAVEL_SINTETICOS: "   "})

    def test_destinos_do_tenant_nega_em_vez_de_devolver_vazio(self) -> None:
        """Uma lista vazia lia-se como «nao transfere nada», e a base nao disse
        isso."""

        def rebenta(_tenant):
            raise RuntimeError("a base nao responde")

        with self.assertRaises(TransferenciaNegada):
            destinos_do_tenant(rebenta, TENANT)

    def test_destinos_do_tenant_recusa_linha_ilegivel(self) -> None:
        with self.assertRaises(TransferenciaNegada):
            destinos_do_tenant(
                lambda _t: [{"provider": "openai", "purpose": "conversa",
                             "status": "pendente", "tem_apd_ref": "nao"}],
                TENANT,
            )


class TestConfiguracaoSintetica(unittest.TestCase):
    def test_le_as_tres_chaves(self) -> None:
        cfg = ConfiguracaoSintetica.de_texto(
            "# comentario\n"
            f"mapa_ref = {MAPA}\n"
            "dpa = aceite\n"
            "destino = openai:conversa\n"
            "destino = groq:transcricao\n"
            "\n"
        )
        self.assertEqual(cfg.mapa_ref, MAPA)
        self.assertTrue(cfg.dpa_aceite)
        self.assertEqual(
            {(d.provider, d.purpose) for d in cfg.destinos},
            {("openai", "conversa"), ("groq", "transcricao")},
        )
        self.assertTrue(all(d.autorizado for d in cfg.destinos))
        self.assertEqual(avaliar_go_live(cfg.destinos, cfg.dpa_aceite, cfg.mapa_ref), ())

    def test_a_omissao_e_negar(self) -> None:
        cfg = ConfiguracaoSintetica.de_texto("")
        self.assertEqual(cfg.destinos, ())
        self.assertFalse(cfg.dpa_aceite)
        self.assertIsNone(cfg.mapa_ref)

    def test_dpa_que_nao_seja_aceite_nao_aceita(self) -> None:
        for valor in ("sim", "true", "aceito", ""):
            with self.subTest(valor=valor):
                self.assertFalse(
                    ConfiguracaoSintetica.de_texto(f"dpa = {valor}\n").dpa_aceite
                )

    def test_recusa_o_que_nao_sabe_ler(self) -> None:
        for texto in (
            "linha sem igual\n",
            "chave_inventada = 1\n",
            "destino = openai\n",
            "destino = a:b:c\n",
        ):
            with self.subTest(texto=texto.strip()):
                with self.assertRaises(ConfiguracaoSinteticaInvalida):
                    ConfiguracaoSintetica.de_texto(texto)

    def test_sem_a_variavel_nao_ha_configuracao(self) -> None:
        self.assertIsNone(ConfiguracaoSintetica.ler({}))
        self.assertIsNone(ConfiguracaoSintetica.ler({VARIAVEL_SINTETICOS: "  "}))

    def test_um_ficheiro_que_nao_se_le_e_erro_e_nao_silencio(self) -> None:
        with self.assertRaises(ConfiguracaoSinteticaInvalida):
            ConfiguracaoSintetica.ler(
                {VARIAVEL_SINTETICOS: "nao_existe_este_ficheiro.conf"}
            )


class TestDominios(unittest.TestCase):
    def test_sao_treze_finalidades_e_estao_ordenadas(self) -> None:
        """O numero e o do dicionario §3.49, e a ordem e a da revisao `0036`.

        **Fixo no codigo e nao derivado**, que e a diferenca entre um teste e um
        espelho: `len(FINALIDADES)` contra `len(FINALIDADES)` passa sempre.
        """
        self.assertEqual(len(FINALIDADES), 13)
        self.assertEqual(list(FINALIDADES), sorted(FINALIDADES))
        self.assertEqual(len(set(FINALIDADES)), 13)


if __name__ == "__main__":
    unittest.main()
