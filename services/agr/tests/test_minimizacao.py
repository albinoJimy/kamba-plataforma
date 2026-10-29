"""A bateria da minimizacao de PII (KAM-112).

| Classe | Criterio |
|---|---|
| `TestBarreiraDeTipo` | 1 — `minimise` e a unica via para o gateway |
| `TestArquitectura` | 1 — politica AST: nenhuma chamada ao cliente fora de `minimise` |
| `TestTokens` | 2 — as formas de cada identificador |
| `TestCorpusDePii` | 3 — recall por tipo no corpus de >= 300 casos |
| `TestNumerosDeNegocio` | 4 — 0 precos, totais, quantidades, horas ou `sku` alterados |
| `TestCatalogoDoTenant` | 5 — nomes que sao *facts* nao se mascaram |
| `TestMapaEReidentificacao` | 6 — o mapa nao sai do AGR; token desconhecido e removido |
| `TestIsolamento` | 6 — o mapa e por `thread_id` |
| `TestFalhaFechada` | 7 — erro ou tecto de tempo impedem a chamada |
| `TestLatencia` | 7 — a sobrecarga p95, **medida e publicada** |
| `TestLimitesDeclarados` | o risco residual, medido em vez de esquecido |
| `TestMetricasSemValores` | «metricas sem valores» do bloco |

## O que esta bateria mede e o que ela **nao** prova

Os limiares do criterio 3 (recall >= 99% em telefone, BSUID, e-mail e NIF; >= 90%
em moradas e nomes) e a sobrecarga do criterio 7 (p95 <= 30 ms para 2.000
caracteres) sao ***propostas a calibrar no Piloto***, e o bloco di-lo. Esta
bateria mede-os sobre um corpus **sintetico que eu escrevi**: um recall de 100%
aqui diz que o detector apanha o que este corpus tem, e **nao** que apanha o que
um cliente angolano escreve. O que limita a leitura esta no `LIMITES` do
`corpus_pii.py`, e sao seis casos que o detector nao apanha de propósito.

A medicao publica-se em `ci/pii/recall.json` — e o «`pii_recall{tipo}` e
publicada no CI» do criterio 3, na forma que esta casa usa para alertas e
medicoes (uma metrica com nome mais um ficheiro, porque nao ha sistema de
metricas de CI neste repositorio). **E abaixo do limiar o `build` falha**: os
limiares sao asercoes desta bateria, que o `make test-py` corre e o *gate* 4
executa — nao se abriu *gate* novo, pela decisao do `politica_ast.py`.
"""

from __future__ import annotations

import ast
import json
import re
import time
import unittest
from pathlib import Path

import corpus_pii as corpus
import politica_llm_ast as politica
from kamba_agr import metricas as metricas_mod
from kamba_agr.degradacao import MOTIVO_MINIMIZACAO, MOTIVOS_QUE_NAO_CONTAM, motivo_do_erro
from kamba_agr.estado import CAMPOS_DO_TURNO, ConversaState, estado_inicial
from kamba_agr.llm.erros import ErroDeLlm, FalhaDeMinimizacao
from kamba_agr.privacidade import (
    ALVO_P95_MS,
    BSUID,
    CHAVE_DO_MAPA,
    COMPRIMENTO_DE_REFERENCIA,
    EMAIL,
    MORADA,
    NIF,
    PESSOA,
    TECTO_MS,
    TELEFONE,
    TIPOS,
    TIPOS_DE_DICIONARIO,
    TIPOS_DE_FORMA,
    CatalogoVazio,
    ContextoDeMinimizacao,
    Mapa,
    MensagemMinimizada,
    MinimisedText,
    TextoNaoMinimizado,
    contexto_de,
    detectar,
    dobrar,
    mensagem,
    minimise,
    nomes_dobrados,
    reidentificar,
    tokens_desconhecidos,
)
from kamba_agr.privacidade import minimizacao as minimizacao_mod
from kamba_agr.privacidade import negocio as negocio_mod

TENANT = "22222222-2222-2222-2222-222222222222"
CONTACTO = "33333333-3333-3333-3333-333333333333"
THREAD = f"{TENANT}:{CONTACTO}"

#: Os limiares do criterio 3. ***Propostas***, e o bloco di-lo.
LIMIAR_DE_FORMA = 99.0
LIMIAR_DE_DICIONARIO = 90.0

#: Onde a medicao se publica (criterio 3).
RAIZ = Path(__file__).resolve().parents[3]
DESTINO_DA_MEDICAO = RAIZ / "ci" / "pii" / "recall.json"

#: A raiz da fonte do AGR, para a politica AST.
FONTE = RAIZ / "services" / "agr" / "src" / "kamba_agr"


def _ctx(**extra: object) -> ContextoDeMinimizacao:
    campos: dict[str, object] = {"tenant_id": TENANT, "thread_id": THREAD}
    campos.update(extra)
    return ContextoDeMinimizacao(**campos)  # type: ignore[arg-type]


def _ctx_com_nif(**extra: object) -> ContextoDeMinimizacao:
    """O contexto com o padrao de NIF **de ensaio**. Ver a nota no corpus."""
    return _ctx(padrao_de_nif=corpus.PADRAO_DE_NIF_DE_ENSAIO, **extra)


# ------------------------------------------------------------- criterio 1


class TestBarreiraDeTipo(unittest.TestCase):
    """O `minimise` e a **unica** via para o gateway de LLM (criterio 1)."""

    def test_nao_se_constroi_um_minimised_text_a_mao(self) -> None:
        """E a barreira. Sem ela, o resto deste ficheiro nao vale nada."""
        with self.assertRaises(TextoNaoMinimizado):
            MinimisedText("o meu numero e 912345678")

    def test_nem_com_um_selo_inventado(self) -> None:
        """Um selo adivinhado nao serve: o `_SELO` e um `object()` do modulo."""
        for falso in (None, "_SELO", object(), 0, True):
            with self.subTest(falso=falso), self.assertRaises(TextoNaoMinimizado):
                MinimisedText("texto cru", falso)

    def test_o_minimise_constroi_um(self) -> None:
        minimo, _mapa = minimise("ola", _ctx())
        self.assertIsInstance(minimo, MinimisedText)
        self.assertEqual(str(minimo), "ola")

    def test_a_mensagem_recusa_texto_cru(self) -> None:
        with self.assertRaises(TextoNaoMinimizado):
            mensagem("user", "o meu numero e 912345678")  # type: ignore[arg-type]

    def test_a_mensagem_aceita_um_minimised_text(self) -> None:
        minimo, _ = minimise("ola", _ctx())
        msg = mensagem("user", minimo)
        self.assertIsInstance(msg, MensagemMinimizada)
        self.assertEqual(msg.para_esquema(), {"role": "user", "content": "ola"})

    def test_o_gateway_recusa_um_dicionario(self) -> None:
        """A assinatura do `chamar` era `list[dict[str, str]]` ate este ticket.

        **E uma guarda em execucao e nao so uma anotacao**, porque nao ha
        verificador de tipos para Python neste repositorio: o `make typecheck` e
        `pnpm -r run typecheck`. Uma anotacao sozinha era a «convencao
        documentada» que o bloco recusa.
        """
        from test_llm_cliente import _cliente  # a bateria do gateway ja tem o duplo

        cliente, _lig, _met = _cliente()
        with self.assertRaises(TextoNaoMinimizado):
            cliente.chamar("chat", [{"role": "user", "content": "ola"}], _CTX_DO_GATEWAY)

    def test_o_gateway_aceita_uma_mensagem_minimizada(self) -> None:
        from test_llm_cliente import _cliente

        cliente, _lig, _met = _cliente()
        minimo, _ = minimise("ola", _ctx())
        resposta = cliente.chamar("chat", [mensagem("user", minimo)], _CTX_DO_GATEWAY)
        self.assertEqual(resposta.texto, "ola")

    def test_o_payload_nao_leva_o_identificador_plantado(self) -> None:
        """Integracao: o LiteLLM falso captura o corpo; 0 correspondencias.

        E o «Integracao: LiteLLM falso que captura o payload; 0 correspondencias
        aos identificadores plantados» dos Testes Requeridos.
        """
        from test_llm_cliente import _cliente

        from test_llm_cliente import _Transporte, _cliente

        plantados = (
            "912345678",
            "AO.a1b2c3d4e5",
            "joao.silva@exemplo.co.ao",
            "Maianga",
        )
        texto = (
            "Liga ao 912345678, o BSUID e AO.a1b2c3d4e5, o e-mail e "
            "joao.silva@exemplo.co.ao e entrego no Maianga. Total 12.500 Kz."
        )
        transporte = _Transporte()
        cliente, _lig, _met = _cliente(transporte)
        minimo, mapa = minimise(texto, _ctx())
        cliente.chamar("chat", [mensagem("user", minimo)], _CTX_DO_GATEWAY)

        # O `_Transporte` grava `(url, cabecalhos, corpo, timeout)` por chamada.
        _url, _cabecalhos, corpo_enviado, _timeout = transporte.chamadas[-1]
        corpo = json.dumps(corpo_enviado, ensure_ascii=False)
        for plantado in plantados:
            with self.subTest(plantado=plantado):
                self.assertNotIn(plantado, corpo)
        # E o controlo positivo: o numero de negocio **esta** no payload.
        self.assertIn("12.500", corpo)
        # E os quatro estao no mapa, que fica no AGR.
        self.assertEqual(len(mapa.valores), 4)


# ------------------------------------------------------------- arquitectura


class TestArquitectura(unittest.TestCase):
    """Politica AST: nenhuma chamada ao cliente LLM fora de `minimise`.

    Le a **fonte** e nao importa nada, pela razao do `politica_ast.py`: uma
    barreira que so morde em execucao nao apanha o caminho que ninguem
    exercitou — e e esse o caminho por onde texto cru sairia.
    """

    def _fontes(self) -> list[Path]:
        return sorted(FONTE.rglob("*.py"))

    def test_ha_fontes_para_ler(self) -> None:
        """Sem isto, um `rglob` que devolva zero dava «tudo conforme»."""
        self.assertGreater(len(self._fontes()), 30)

    def test_a_fonte_do_agr_esta_conforme(self) -> None:
        achados: list[str] = []
        for caminho in self._fontes():
            e_o_selo = caminho.name == "minimizacao.py" and caminho.parent.name == "privacidade"
            for achado in politica.verificar(
                caminho.read_text(encoding="utf-8"), e_o_modulo_do_selo=e_o_selo
            ):
                achados.append(f"{caminho.relative_to(RAIZ)}: {achado}")
        self.assertEqual(achados, [], "\n".join(achados))

    def test_o_canario_morde_cada_regra(self) -> None:
        """Cada regra obrigatoria tem de recusar a sua fonte negativa.

        «O repositorio esta conforme» e uma linha que um `verificar` vazio passa.
        """
        for regra in politica.REGRAS_OBRIGATORIAS:
            with self.subTest(regra=regra):
                achados = politica.verificar(politica.CANARIOS[regra])
                self.assertTrue(
                    any(achado.startswith(regra) for achado in achados),
                    f"o canario de `{regra}` nao foi recusado: {achados}",
                )

    def test_o_modulo_do_selo_e_o_unico_que_o_pode_referir(self) -> None:
        caminho = FONTE / "privacidade" / "minimizacao.py"
        fonte = caminho.read_text(encoding="utf-8")
        # Com a dispensa, conforme; sem ela, recusado — e e o que prova que a
        # dispensa e o que separa este ficheiro dos outros, e nao um `if` morto.
        self.assertEqual(politica.verificar(fonte, e_o_modulo_do_selo=True), [])
        self.assertNotEqual(politica.verificar(fonte), [])

    def test_o_cliente_de_llm_e_o_unico_egresso_para_um_modelo(self) -> None:
        """Nenhum outro ficheiro do AGR fala HTTP com o proxy.

        A politica AST nao prova isto (ver a sua nota), e por isso mede-se aqui:
        o `chat/completions` aparece **so** no `llm/cliente.py`.
        """
        com_o_caminho = [
            caminho.relative_to(RAIZ).as_posix()
            for caminho in self._fontes()
            if "chat/completions" in caminho.read_text(encoding="utf-8")
        ]
        self.assertEqual(
            com_o_caminho, ["services/agr/src/kamba_agr/llm/cliente.py"]
        )


# ------------------------------------------------------------- criterio 2


class TestTokens(unittest.TestCase):
    """As formas de cada identificador, e os tokens que saem (criterio 2)."""

    def test_os_seis_tipos_sao_os_do_criterio(self) -> None:
        self.assertEqual(
            set(TIPOS), {TELEFONE, BSUID, EMAIL, NIF, MORADA, PESSOA}
        )
        self.assertEqual(len(TIPOS), 6)
        self.assertEqual(set(TIPOS_DE_FORMA) | set(TIPOS_DE_DICIONARIO), set(TIPOS))

    def test_cada_tipo_casa_a_gramatica_de_etiqueta_em_minusculas(self) -> None:
        """E porque e que o `contar` leva `tipo.lower()`.

        A gramatica do `metricas.py` e `^[a-z][a-z0-9_]{1,62}$`: um valor em
        maiusculas **levanta**, e os tipos sao maiusculos porque sao a raiz do
        token (`TELEFONE` -> `TELEFONE_1`).
        """
        for tipo in TIPOS:
            with self.subTest(tipo=tipo):
                self.assertRegex(tipo.lower(), metricas_mod.ETIQUETA)
                self.assertIsNone(metricas_mod.ETIQUETA.match(tipo))

    def test_o_contacto_do_turno_e_sempre_cliente(self) -> None:
        """`docs/tecnica/02` §8.4: o contacto segue como «Cliente», sem telefone.

        O `ContextoDeMinimizacao` **nao tem** `contact_id` nem telefone, e e
        assim que isto se cumpre: nao ha nada no contexto que permita identificar
        o contacto, pelo que nenhum caminho o pode pôr no *prompt*.
        """
        campos = {campo.name for campo in ContextoDeMinimizacao.__dataclass_fields__.values()}
        self.assertNotIn("contact_id", campos)
        self.assertNotIn("telefone", campos)
        self.assertNotIn("bsuid", campos)

    def test_as_dez_formas_de_telefone(self) -> None:
        """Uma asercao por forma, para que um vermelho diga **qual** falhou."""
        for forma, escrever in corpus.FORMAS_DE_TELEFONE:
            with self.subTest(forma=forma):
                escrito = escrever("912345678")
                minimo, mapa = minimise(f"o meu numero e {escrito}", _ctx())
                self.assertNotIn(escrito, minimo.texto, forma)
                self.assertIn("TELEFONE_1", minimo.texto, forma)
                self.assertEqual(mapa.valores["TELEFONE_1"], escrito)

    def test_o_token_numera_por_ordem_de_leitura(self) -> None:
        """Um *prompt* cujo primeiro identificador e o `_3` convida a inferir.

        A primeira versao substituia de tras para a frente **e** atribuia na
        mesma passagem, pelo que a numeracao saia ao contrario da leitura.
        """
        minimo, _ = minimise(
            "entregar no Maianga, perto do Golfe, e liga ao 912345678", _ctx()
        )
        self.assertLess(
            minimo.texto.index("MORADA_1"), minimo.texto.index("MORADA_2")
        )

    def test_o_mesmo_valor_da_o_mesmo_token(self) -> None:
        minimo, mapa = minimise(
            "os meus numeros sao 912345678 e 912345678", _ctx()
        )
        self.assertEqual(minimo.texto.count("TELEFONE_1"), 2)
        self.assertEqual(len(mapa.valores), 1)

    def test_o_toponimo_composto_e_um_token_e_nao_dois(self) -> None:
        """«Nova Vida» e **um** local; dois tokens faziam o modelo ver dois."""
        minimo, mapa = minimise("entregar em Nova Vida", _ctx())
        self.assertEqual(minimo.texto, "entregar em MORADA_1")
        self.assertEqual(mapa.valores["MORADA_1"], "Nova Vida")

    def test_o_nif_nao_se_detecta_sem_padrao(self) -> None:
        """**Por desenho, e o bloco manda nao inventar o formato.**

        O `docs/tecnica/08` nao define o NIF angolano. Sem padrao passado, o
        recall de NIF e 0% — e isso diz-se em voz alta. O precedente e o
        `make x11 X11_NIF` do KAM-068.
        """
        minimo, mapa = minimise("o meu NIF e 5417238690", _ctx())
        self.assertIn("5417238690", minimo.texto)
        self.assertEqual(mapa.valores, {})

    def test_o_nif_detecta_se_com_padrao(self) -> None:
        minimo, mapa = minimise("o meu NIF e 5417238690", _ctx_com_nif())
        self.assertNotIn("5417238690", minimo.texto)
        self.assertEqual(mapa.valores["NIF_1"], "5417238690")

    def test_dobrar_preserva_o_comprimento(self) -> None:
        """E a propriedade que faz os indices do detector valerem no original.

        Um normalizador que encolhesse o texto dava intervalos deslocados e
        mascarava o caracter errado. Mede-se sobre o corpus **inteiro**, que e a
        unica forma de isto continuar verdadeiro quando alguem acrescentar casos.
        """
        for caso in (*corpus.COM_PII, *corpus.NUMEROS):
            with self.subTest(caso=caso.nome):
                self.assertEqual(len(dobrar(caso.texto)), len(caso.texto))

    def test_dobrar_reduz_digitos_unicode_e_acentos(self) -> None:
        self.assertEqual(dobrar("٩١٢"), "912")
        self.assertEqual(dobrar("Maiánga"), "maianga")
        self.assertEqual(dobrar("ÀÉÎÕÜ"), "aeiou")


# ------------------------------------------------------------- criterio 3


class TestCorpusDePii(unittest.TestCase):
    """Recall por tipo no corpus sintetico (criterio 3)."""

    @classmethod
    def setUpClass(cls) -> None:
        ctx = _ctx_com_nif()
        cls.apanhados: dict[str, int] = {}
        cls.esperados: dict[str, int] = {}
        cls.escapes: list[str] = []
        for caso in corpus.COM_PII:
            minimo, _mapa = minimise(caso.texto, ctx)
            for tipo, valor in caso.espera:
                cls.esperados[tipo] = cls.esperados.get(tipo, 0) + 1
                if valor not in minimo.texto:
                    cls.apanhados[tipo] = cls.apanhados.get(tipo, 0) + 1
                else:
                    cls.escapes.append(f"{caso.nome}: {tipo} `{valor}` ficou")
        cls.recall = {
            tipo: 100.0 * cls.apanhados.get(tipo, 0) / total
            for tipo, total in cls.esperados.items()
        }

    def test_o_corpus_tem_pelo_menos_300_casos(self) -> None:
        """A letra, e nao o espirito: «>= 300 casos» com 280 nao esta cumprido."""
        self.assertGreaterEqual(len(corpus.COM_PII), 300)

    def test_os_nomes_dos_casos_sao_unicos(self) -> None:
        """Dois casos com o mesmo nome e um caso que ninguem consegue localizar."""
        nomes = [caso.nome for caso in corpus.COM_PII]
        self.assertEqual(len(nomes), len(set(nomes)))

    def test_os_seis_tipos_estao_no_corpus(self) -> None:
        """Um tipo sem casos dava um recall ausente que ninguem notava."""
        self.assertEqual(set(self.esperados), set(TIPOS))

    def test_zero_dados_reais(self) -> None:
        """Os Termos da Meta §4.7 proibem dados da plataforma para melhorar ML.

        Nao se pode provar a negativa por varrimento; o que se verifica e que os
        telefones do corpus sao **os sinteticos declarados** e mais nenhum, que e
        a parte mecanizavel da afirmacao (ADR-018, `E1` §4).
        """
        declarados = set(corpus.NUMEROS_SINTETICOS) | set(corpus.NIFS_SINTETICOS)
        # **Os grupos MAXIMOS de digitos, e nao um `\\d{9}` deslizante.** A
        # primeira versao deste ensaio procurava `\\d{9}` e apanhava as janelas de
        # nove digitos **dentro** dos numeros com prefixo (`00244912345678` da
        # `002449123`), pelo que acusava quarenta e dois numeros «nao
        # declarados» que eram os declarados vistos a meio. Um ensaio que acusa
        # o que esta certo e pior do que nenhum.
        nao_declarados: set[str] = set()
        for caso in corpus.COM_PII:
            for grupo in re.findall(r"\d+", dobrar(caso.texto)):
                if len(grupo) < 9:
                    # Numeros de negocio dos casos mistos (`12`, `500`, `3.500`).
                    continue
                nu = grupo.removeprefix("00244").removeprefix("244")
                if nu not in declarados:
                    nao_declarados.add(grupo)
        self.assertEqual(
            nao_declarados,
            set(),
            f"numeros de 9+ digitos nao declarados no corpus: {sorted(nao_declarados)}",
        )
        # E o controlo positivo: os declarados **estao** la. Sem isto, um corpus
        # que perdesse os telefones passava este ensaio com zero achados.
        self.assertGreaterEqual(len(declarados), 20)

    def test_recall_dos_tipos_de_forma(self) -> None:
        """>= 99% em telefone, BSUID, e-mail e NIF. ***Limiar proposta.***"""
        for tipo in TIPOS_DE_FORMA:
            with self.subTest(tipo=tipo):
                self.assertGreaterEqual(
                    self.recall[tipo],
                    LIMIAR_DE_FORMA,
                    f"{tipo}: {self.apanhados.get(tipo, 0)}/{self.esperados[tipo]}",
                )

    def test_recall_dos_tipos_de_dicionario(self) -> None:
        """>= 90% em moradas e nomes de terceiros. ***Limiar proposta.***"""
        for tipo in TIPOS_DE_DICIONARIO:
            with self.subTest(tipo=tipo):
                self.assertGreaterEqual(
                    self.recall[tipo],
                    LIMIAR_DE_DICIONARIO,
                    f"{tipo}: {self.apanhados.get(tipo, 0)}/{self.esperados[tipo]}",
                )

    def test_a_medicao_publica_se(self) -> None:
        """O «`pii_recall{tipo}` e publicada no CI» do criterio 3.

        Escreve-se um ficheiro porque nao ha sistema de metricas de CI neste
        repositorio — e a mesma forma que o KAM-027 e o KAM-114 usaram para os
        seus alertas, e a mesma que o `ci/x11/` usa para o varrimento do KAM-068.
        """
        DESTINO_DA_MEDICAO.parent.mkdir(parents=True, exist_ok=True)
        DESTINO_DA_MEDICAO.write_text(
            json.dumps(
                {
                    "ticket": "KAM-112",
                    "nota": (
                        "Corpus sintetico PT-AO, 0 dados reais. Os limiares sao "
                        "propostas a calibrar no Piloto (KAM-109). O NIF e medido "
                        "com um padrao de ensaio, nao com canon: o docs/tecnica/08 "
                        "nao define o formato e o bloco manda nao o inventar."
                    ),
                    "casos": len(corpus.COM_PII),
                    "limiares_propostos": {
                        "forma": LIMIAR_DE_FORMA,
                        "dicionario": LIMIAR_DE_DICIONARIO,
                    },
                    "pii_recall": {
                        tipo: {
                            "apanhados": self.apanhados.get(tipo, 0),
                            "esperados": self.esperados[tipo],
                            "recall_pc": round(self.recall[tipo], 2),
                        }
                        for tipo in sorted(self.esperados)
                    },
                    "limites_declarados": [limite.nome for limite in corpus.LIMITES],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        lido = json.loads(DESTINO_DA_MEDICAO.read_text(encoding="utf-8"))
        self.assertEqual(set(lido["pii_recall"]), set(TIPOS))


# ------------------------------------------------------------- criterio 4


class TestNumerosDeNegocio(unittest.TestCase):
    """0 precos, totais, quantidades, horas ou `sku` alterados (criterio 4)."""

    def test_o_corpus_tem_pelo_menos_200_casos(self) -> None:
        """A letra: «>= 200 casos adversariais»."""
        self.assertGreaterEqual(len(corpus.NUMEROS), 200)

    def test_zero_alterados(self) -> None:
        """**Zero, e um e zero falhado.**

        Cada caso diz que cadeias tem de sobreviver **literalmente**. Um
        detector que mascarasse um preco destroi o produto: os numeros sao
        *facts* (ADR-007) e o validador de citacao (KAM-032) recusa uma resposta
        que cite o que nao veio de uma tool.
        """
        ctx = _ctx_com_nif()
        alterados: list[str] = []
        total = 0
        for caso in corpus.NUMEROS:
            minimo, _mapa = minimise(caso.texto, ctx)
            for cadeia in caso.intactos:
                total += 1
                if cadeia not in minimo.texto:
                    alterados.append(f"{caso.nome}: `{cadeia}` -> {minimo.texto}")
        self.assertEqual(alterados, [], "\n".join(alterados))
        self.assertGreaterEqual(total, 200)

    def test_o_total_que_parece_telefone_passa_intacto(self) -> None:
        """O caso que o bloco nomeia por extenso, isolado para ser legivel."""
        for texto, numero in (
            ("O total da encomenda e 912500000 Kz.", "912500000"),
            ("Fica em 912.500.000 Kz, tudo incluido.", "912.500.000"),
            ("Kz 912500000 e o total.", "912500000"),
        ):
            with self.subTest(texto=texto):
                minimo, mapa = minimise(texto, _ctx())
                self.assertIn(numero, minimo.texto)
                self.assertEqual(mapa.valores, {})

    def test_um_reclamador_que_cobre_tudo_falha_fechado(self) -> None:
        """O modo de falha deste desenho: reclamar e esconder.

        Um intervalo reclamado e PII que nao se mascara. Uma expressao que
        reclamasse o texto inteiro fazia o `minimise` devolver o original **sem
        mascarar nada e sem falhar** — a pior falha deste ticket, porque passa
        por sucesso. O tecto converte-a em falha fechada.
        """
        # 11 caracteres reclamados em cada 12 (`1.234.567Kz` mais a virgula)
        # = 91,6%, acima do `FRACCAO_MAXIMA` de 90%. A virgula e precisa: sem
        # separador, o `_na_fronteira` recusava cada reclamacao a seguir a um
        # `z` e a cobertura dava zero.
        texto = "1.234.567Kz," * 20
        with self.assertRaises(negocio_mod.ReclamouDemais):
            negocio_mod.reclamar(texto)
        with self.assertRaises(FalhaDeMinimizacao):
            minimise(texto, _ctx())

    def test_a_fronteira_recusa_uma_reclamacao_a_meio_de_um_simbolo(self) -> None:
        """Tres defeitos da mesma familia, os tres sobre BSUID.

        O `_na_fronteira` substituiu duas guardas por padrao que nao cobriam a
        familia. Cada um destes era um BSUID a sair em claro para o modelo.
        """
        for texto, bsuid in (
            ("O identificador e AO.abc123def456.", "AO.abc123def456"),
            ("O identificador e PT.x9k2m4p8q1.", "PT.x9k2m4p8q1"),
            ("O identificador e PT.d4s3a2z1x0.", "PT.d4s3a2z1x0"),
        ):
            with self.subTest(bsuid=bsuid):
                minimo, mapa = minimise(texto, _ctx())
                self.assertNotIn(bsuid, minimo.texto)
                self.assertEqual(mapa.valores["BSUID_1"], bsuid)

    def test_um_preco_antes_do_ponto_final_continua_reclamado(self) -> None:
        """O lado simetrico da fronteira, e o que a torna assimetrica.

        Recusar um intervalo seguido de pontuacao deixava de reclamar «12.500
        Kz.» — e o defeito oposto, que e pior.
        """
        minimo, _ = minimise("O total e 12.500 Kz.", _ctx())
        self.assertIn("12.500", minimo.texto)


# ------------------------------------------------------------- criterio 5


class TestCatalogoDoTenant(unittest.TestCase):
    """Nomes que sao *facts* do catalogo nao se mascaram (criterio 5).

    **A caixa deste criterio fica `parcial`**, e a razao esta no
    `privacidade/catalogo.py`: o `CommerceRegistry` e o KAM-042 (aberto) e o
    contrato proposto no `docs/tecnica/03` §3.2 **nao tem operacao que devolva
    uma lista de nomes**. Tres das quatro classes que o criterio enumera tem
    fonte hoje (marcas, servicos, recursos); os **produtos** nao.
    """

    def test_um_nome_do_catalogo_nao_se_mascara(self) -> None:
        ctx = _ctx(do_catalogo=nomes_dobrados(["Rosa", "Salao da Rosa"]))
        minimo, mapa = minimise("Fala com a Rosa sobre a marcacao.", ctx)
        self.assertIn("Rosa", minimo.texto)
        self.assertEqual(mapa.valores, {})

    def test_um_nome_que_nao_e_do_catalogo_mascara_se(self) -> None:
        """O controlo positivo: sem ele, o teste de cima e satisfeito por nada."""
        ctx = _ctx(do_catalogo=nomes_dobrados(["Rosa"]))
        minimo, mapa = minimise("Fala com o Joao sobre a marcacao.", ctx)
        self.assertNotIn("Joao", minimo.texto)
        self.assertEqual(mapa.valores["PESSOA_1"], "Joao")

    def test_o_nome_do_catalogo_nao_entra_em_par_com_um_apelido(self) -> None:
        """E porque e que a barreira corre **antes** das tres vias.

        Sem isso, uma «Rosa» do catalogo entrava em par com o apelido seguinte e
        o par inteiro virava `PESSOA_1` — o *fact* perdido por outro caminho.
        """
        ctx = _ctx(do_catalogo=nomes_dobrados(["Rosa"]))
        minimo, _ = minimise("A Rosa Silva ja pagou.", ctx)
        self.assertIn("Rosa", minimo.texto)

    def test_o_catalogo_vazio_e_a_omissao(self) -> None:
        self.assertEqual(CatalogoVazio().nomes(TENANT), frozenset())
        self.assertEqual(_ctx().do_catalogo, frozenset())

    def test_um_nome_curto_nao_protege(self) -> None:
        """Um servico chamado «A» era uma dispensa geral, nao uma proteccao.

        O filtro tem de estar nos **dois** caminhos para a lista — a porta e o
        `nomes_dobrados` —, e a primeira versao so o tinha na porta.
        """
        self.assertEqual(nomes_dobrados(["A", "ab", "abc", "Rosa"]), {"abc", "rosa"})
        self.assertEqual(nomes_dobrados("nao e coleccao"), frozenset())
        self.assertEqual(nomes_dobrados([None, 7, ""]), frozenset())

    def test_o_contexto_de_le_o_catalogo_uma_vez(self) -> None:
        """O `minimise` **nao** vai a base de dados: o p95 do criterio 7 e 30 ms.

        Quem le e o `contexto_de`, uma vez por turno.
        """
        chamadas: list[str] = []

        class _Porta:
            def nomes(self, tenant_id: str) -> frozenset[str]:
                chamadas.append(tenant_id)
                return nomes_dobrados(["Rosa"])

        estado = {"tenant_id": TENANT, "thread_id": THREAD}
        ctx = contexto_de(estado, catalogo=_Porta())
        self.assertEqual(chamadas, [TENANT])
        for _ in range(5):
            minimise("Fala com a Rosa.", ctx)
        self.assertEqual(chamadas, [TENANT], "o `minimise` leu o catalogo")


# ------------------------------------------------------------- criterio 6


class TestMapaEReidentificacao(unittest.TestCase):
    """O mapa nao sai do AGR; um token desconhecido e removido (criterio 6)."""

    def test_o_repr_do_mapa_nao_mostra_valores(self) -> None:
        """E a barreira mais barata que ha, e e a que fecha o vazamento real.

        O modo como um mapa vazaria e alguem pôr `f"{mapa}"` num `extra` de log,
        num *trace* ou numa mensagem de excepcao.
        """
        _minimo, mapa = minimise(
            "liga ao 912345678, entrego no Maianga", _ctx()
        )
        texto = f"{mapa!r} {mapa}"
        self.assertNotIn("912345678", texto)
        self.assertNotIn("Maianga", texto)
        # E nem os tokens: a contagem por tipo e o que um painel precisa.
        self.assertNotIn("TELEFONE_1", texto)
        self.assertIn("telefone=1", texto)
        self.assertIn("morada=1", texto)

    def test_o_mapa_nao_entra_na_linha_de_llm_call_log(self) -> None:
        """Com canario, e nao a olhar para a lista de colunas.

        E a mesma forma do `test_a_linha_nao_leva_conteudo` do gateway: a lista
        de colunas nao prova que ninguem escreveu o mapa num campo de texto.
        """
        from test_llm_cliente import _cliente

        cliente, lig, _met = _cliente()
        minimo, mapa = minimise("liga ao 912345678", _ctx())
        cliente.chamar("chat", [mensagem("user", minimo)], _CTX_DO_GATEWAY)
        tudo = " ".join(
            str(valor) for linha in lig.linhas() for valor in linha.values()
        )
        self.assertNotIn("912345678", tudo)
        self.assertNotIn("TELEFONE_1", tudo)
        self.assertTrue(mapa.valores)

    def test_a_chave_do_estado_e_a_do_dicionario(self) -> None:
        self.assertEqual(CHAVE_DO_MAPA, "pii_map")
        self.assertIn(CHAVE_DO_MAPA, ConversaState.__annotations__)

    def test_o_mapa_atravessa_turnos(self) -> None:
        """Fora do `estado_inicial` **e** fora do `CAMPOS_DO_TURNO`.

        E a assimetria do `turn_seq` (KAM-114). A janela de mensagens leva as
        mensagens minimizadas dos turnos anteriores: um `TELEFONE_1` do turno 1
        reaparece no *prompt* do turno 3, e com um mapa por turno a
        `reidentificar` **removia-o**.
        """
        from apoio import invocacao_crua  # noqa: PLC0415 — o apoio da bateria
        from kamba_agr.contexto import ler_invocacao

        inicial = estado_inicial(ler_invocacao(invocacao_crua()))
        self.assertNotIn(CHAVE_DO_MAPA, inicial)
        self.assertNotIn(CHAVE_DO_MAPA, CAMPOS_DO_TURNO)

    def test_a_numeracao_continua_entre_turnos(self) -> None:
        primeiro, mapa = minimise("liga ao 912345678", _ctx())
        self.assertIn("TELEFONE_1", primeiro.texto)
        segundo, mapa2 = minimise("e tambem ao 923456789", _ctx(mapa=mapa))
        self.assertIn("TELEFONE_2", segundo.texto)
        self.assertEqual(len(mapa2.valores), 2)
        # E o telefone do turno 1 continua a dar o mesmo token no turno 3.
        terceiro, _ = minimise("volta a ligar ao 912345678", _ctx(mapa=mapa2))
        self.assertIn("TELEFONE_1", terceiro.texto)

    def test_o_mapa_repoe_o_texto_original(self) -> None:
        """A propriedade dos Testes Requeridos: «o mapa permite repor o original».

        Mede-se sobre o corpus **inteiro**, que e a unica forma de continuar
        verdadeira quando alguem acrescentar casos. As remocoes declaradas sao as
        do `reidentificar` (brancos e espaco antes de pontuacao), e por isso
        compara-se a forma normalizada.
        """
        ctx = _ctx_com_nif()
        for caso in corpus.COM_PII:
            with self.subTest(caso=caso.nome):
                minimo, mapa = minimise(caso.texto, ctx)
                reposto = reidentificar(minimo.texto, mapa)
                self.assertEqual(_normalizar(reposto), _normalizar(caso.texto))

    def test_um_token_que_o_modelo_invente_e_removido(self) -> None:
        """**Removido, nunca adivinhado** (criterio 6).

        Um modelo que invente `TELEFONE_7` nao faz aparecer um telefone que
        ninguem escreveu.
        """
        _minimo, mapa = minimise("liga ao 912345678", _ctx())
        resposta = "Ligo ao TELEFONE_1 e ao TELEFONE_7, obrigado."
        reposto = reidentificar(resposta, mapa)
        self.assertIn("912345678", reposto)
        self.assertNotIn("TELEFONE_7", reposto)
        self.assertEqual(tokens_desconhecidos(resposta, mapa), ("TELEFONE_7",))

    def test_um_token_inventado_nao_deixa_espaco_a_mais(self) -> None:
        _minimo, mapa = minimise("ola", _ctx())
        self.assertEqual(reidentificar("liga ao MORADA_9 por favor", mapa), "liga ao por favor")

    def test_a_forma_do_token_casa_o_que_o_minimise_produz(self) -> None:
        """Ida e volta: se divergissem, a remocao do criterio 6 nao mordia."""
        ctx = _ctx_com_nif()
        for caso in corpus.COM_PII:
            minimo, mapa = minimise(caso.texto, ctx)
            for token in mapa.valores:
                with self.subTest(token=token):
                    self.assertRegex(token, minimizacao_mod.FORMA_DO_TOKEN)

    def test_o_mapa_le_se_de_um_estado_e_escreve_se_para_um(self) -> None:
        _minimo, mapa = minimise("liga ao 912345678", _ctx())
        estado = {"tenant_id": TENANT, "thread_id": THREAD, CHAVE_DO_MAPA: mapa.para_estado()}
        relido = minimizacao_mod.do_estado(estado)
        self.assertEqual(relido.valores, mapa.valores)

    def test_um_estado_sem_a_chave_da_um_mapa_vazio(self) -> None:
        """A chave esta **ausente** no primeiro turno; quem le usa `get`."""
        self.assertEqual(minimizacao_mod.do_estado({}).valores, {})
        self.assertEqual(minimizacao_mod.do_estado(None).valores, {})
        self.assertEqual(minimizacao_mod.do_estado({CHAVE_DO_MAPA: None}).valores, {})

    def test_um_mapa_escrito_a_mao_nao_para_a_conversa(self) -> None:
        """O pior que um mapa invalido faz e perder re-identificacoes."""
        for bruto in ("texto", 7, [1, 2], {"TELEFONE_1": 9}, {4: "x"}):
            with self.subTest(bruto=bruto):
                self.assertEqual(
                    minimizacao_mod.do_estado({CHAVE_DO_MAPA: bruto}).valores, {}
                )

    def test_o_para_estado_devolve_uma_copia(self) -> None:
        """O estado do LangGraph compara identidade; mutar no sitio escondia."""
        _minimo, mapa = minimise("liga ao 912345678", _ctx())
        copia = mapa.para_estado()
        copia["TELEFONE_1"] = "outro"
        self.assertNotEqual(mapa.valores["TELEFONE_1"], "outro")


def _normalizar(texto: str) -> str:
    """O texto sem brancos repetidos e sem espaco antes de pontuacao."""
    sem_brancos = re.sub(r"[ \t]{2,}", " ", texto)
    return re.sub(r" +([,.;:!?])", r"\1", sem_brancos).strip()


class TestIsolamento(unittest.TestCase):
    """O mapa e por `thread_id` (DoD «Isolamento de tenant»)."""

    def test_dois_threads_nao_partilham_o_mapa(self) -> None:
        """O mapa vem do **estado do thread**, pelo que nao ha estado global.

        E a propriedade que o desenho da de graca: nao ha dicionario de modulo,
        nao ha *cache* por processo, e o `minimise` e uma funcao do contexto que
        lhe passam.
        """
        outro = f"44444444-4444-4444-4444-444444444444:{CONTACTO}"
        _m1, mapa1 = minimise("liga ao 912345678", _ctx())
        _m2, mapa2 = minimise("liga ao 923456789", _ctx(thread_id=outro))
        self.assertEqual(set(mapa1.valores.values()), {"912345678"})
        self.assertEqual(set(mapa2.valores.values()), {"923456789"})

    def test_o_token_de_um_thread_nao_se_repoe_no_outro(self) -> None:
        """Teste cruzado do caminho novo, que o DoD pede pelo nome."""
        _m1, mapa1 = minimise("liga ao 912345678", _ctx())
        outro = f"44444444-4444-4444-4444-444444444444:{CONTACTO}"
        _m2, mapa2 = minimise("ola", _ctx(thread_id=outro))
        reposto = reidentificar("ligo ao TELEFONE_1", mapa2)
        self.assertNotIn("912345678", reposto)
        self.assertIn("912345678", reidentificar("ligo ao TELEFONE_1", mapa1))

    def test_o_minimise_nao_guarda_estado_de_modulo(self) -> None:
        """Duas chamadas iguais com contextos vazios dao o mesmo resultado."""
        primeiro, _ = minimise("liga ao 912345678", _ctx())
        segundo, _ = minimise("liga ao 912345678", _ctx())
        self.assertEqual(primeiro.texto, segundo.texto)


# ------------------------------------------------------------- criterio 7


class TestFalhaFechada(unittest.TestCase):
    """Erro ou tecto de tempo impedem a chamada ao LLM (criterio 7)."""

    def test_a_falha_e_um_erro_de_llm(self) -> None:
        """E o que faz o `classify` do Vendedor apanha-la pelo tipo que ja apanha.

        Sem isto, a falha do detector fazia o turno falhar e voltar a fila — e o
        cliente nao recebia nada, que e o oposto de «degradar, nunca calar».
        """
        self.assertTrue(issubclass(FalhaDeMinimizacao, ErroDeLlm))

    def test_o_motivo_e_proprio_e_nao_o_breaker(self) -> None:
        """O defeito C4 do KAM-037 por outra porta."""
        erro = FalhaDeMinimizacao("ensaio")
        self.assertEqual(motivo_do_erro(erro), MOTIVO_MINIMIZACAO)
        self.assertIn(MOTIVO_MINIMIZACAO, MOTIVOS_QUE_NAO_CONTAM)

    def test_um_detector_que_levanta_nao_devolve_texto(self) -> None:
        """**Nao ha ramo que devolva o original.** E o criterio 7 por inteiro."""
        original = minimizacao_mod.detector_mod.detectar

        def rebentar(*_a: object, **_k: object) -> None:
            raise RuntimeError("o detector avariou (ensaio)")

        minimizacao_mod.detector_mod.detectar = rebentar  # type: ignore[assignment]
        try:
            with self.assertRaises(FalhaDeMinimizacao) as apanhado:
                minimise("o meu numero e 912345678", _ctx())
        finally:
            minimizacao_mod.detector_mod.detectar = original  # type: ignore[assignment]
        # E a mensagem **nao leva o texto**: seria PII numa excepcao, que e o
        # caminho que o `llm/erros.py` fechou para o corpo do fornecedor.
        self.assertNotIn("912345678", str(apanhado.exception))

    def test_passar_o_tecto_de_tempo_falha(self) -> None:
        """Devolver «porque ja esta feito» deixava o turno seguinte igual."""
        relogio = iter([0.0, (TECTO_MS + 1) / 1000.0])
        with self.assertRaises(FalhaDeMinimizacao) as apanhado:
            minimise("ola", _ctx(), agora=lambda: next(relogio))
        self.assertIn(str(TECTO_MS), str(apanhado.exception))

    def test_o_tecto_nao_e_o_alvo_do_criterio(self) -> None:
        """Um detector a 40 ms e lento, nao esta avariado.

        O alvo p95 de 30 ms e ***proposta a calibrar*** e **nada falha por o
        exceder**; o tecto e o ponto a partir do qual se desiste.
        """
        self.assertGreater(TECTO_MS, ALVO_P95_MS)

    def test_texto_que_nao_e_texto_falha_fechado(self) -> None:
        for mau in (None, 7, b"bytes", ["lista"]):
            with self.subTest(mau=mau), self.assertRaises(FalhaDeMinimizacao):
                minimise(mau, _ctx())  # type: ignore[arg-type]


class TestLatencia(unittest.TestCase):
    """A sobrecarga, **medida e publicada**. Nada falha por ela (criterio 7)."""

    def test_mede_se_o_p95_para_2000_caracteres(self) -> None:
        """O alvo e ***proposta***: mede-se e escreve-se, nao se afirma cumprido.

        Deliberadamente **sem asercao sobre o alvo**: uma asercao de 30 ms numa
        maquina de CI partilhada e um teste instavel que alguem acabaria por
        desligar — e o que se perderia era a medicao. O que se afirma e o
        `TECTO_MS`, que e a barreira e tem folga de uma ordem de grandeza.
        """
        ctx = _ctx_com_nif()
        base = " ".join(caso.texto for caso in corpus.COM_PII)
        amostra = (base * 8)[:COMPRIMENTO_DE_REFERENCIA]
        self.assertEqual(len(amostra), COMPRIMENTO_DE_REFERENCIA)

        duracoes: list[float] = []
        for _ in range(40):
            inicio = time.perf_counter()
            minimise(amostra, ctx)
            duracoes.append((time.perf_counter() - inicio) * 1000)
        duracoes.sort()
        p95 = duracoes[int(len(duracoes) * 0.95) - 1]

        DESTINO_DA_MEDICAO.parent.mkdir(parents=True, exist_ok=True)
        (DESTINO_DA_MEDICAO.parent / "latencia.json").write_text(
            json.dumps(
                {
                    "ticket": "KAM-112",
                    "nota": (
                        "Sobrecarga do minimise. O alvo p95 <= 30 ms para 2.000 "
                        "caracteres e proposta a calibrar no Piloto (KAM-109); "
                        "nada falha por o exceder. Medido nesta maquina, nao no "
                        "runner."
                    ),
                    "caracteres": COMPRIMENTO_DE_REFERENCIA,
                    "execucoes": len(duracoes),
                    "alvo_p95_ms_proposto": ALVO_P95_MS,
                    "tecto_ms": TECTO_MS,
                    "p50_ms": round(duracoes[len(duracoes) // 2], 2),
                    "p95_ms": round(p95, 2),
                    "max_ms": round(duracoes[-1], 2),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        # O que se afirma e a barreira, nao o alvo.
        self.assertLess(p95, TECTO_MS)


# ------------------------------------------------------------- os limites


class TestLimitesDeclarados(unittest.TestCase):
    """O risco residual, **medido** em vez de esquecido.

    Sao as limitacoes que o bloco declara («nomes proprios em texto livre e
    referencias a locais escapam a regras») mais as que a construcao
    acrescenta. **Nao entram no recall.**

    Este teste existe para que elas nao mudem em silencio: o dia em que um
    destes passar a ser apanhado, a linha do `corpus_pii.LIMITES` fica errada e
    este teste di-lo.
    """

    def test_cada_limite_continua_a_escapar(self) -> None:
        # **Sem o padrao de NIF**, que e o detector por omissao: um dos limites
        # **e** precisamente «sem padrao, o NIF nao se detecta». Medi-los com o
        # padrao de ensaio era medir outro detector.
        ctx = _ctx()
        for limite in corpus.LIMITES:
            with self.subTest(limite=limite.nome):
                minimo, _mapa = minimise(limite.texto, ctx)
                self.assertIn(
                    limite.escapa,
                    minimo.texto,
                    f"`{limite.nome}` deixou de escapar: actualiza o "
                    f"`corpus_pii.LIMITES` e o recall do criterio 3",
                )

    def test_cada_limite_tem_a_razao_escrita(self) -> None:
        """Um limite sem razao volta na proxima auditoria e paga-se outra vez."""
        for limite in corpus.LIMITES:
            with self.subTest(limite=limite.nome):
                self.assertGreater(len(limite.razao), 80, limite.nome)

    def test_o_nif_sem_padrao_e_um_limite_declarado(self) -> None:
        nomes = {limite.nome for limite in corpus.LIMITES}
        self.assertIn("nif_sem_padrao", nomes)


# ------------------------------------------------------------- as metricas


class TestMetricasSemValores(unittest.TestCase):
    """«Metricas sem valores»: o tipo e a duracao, nunca o texto detectado."""

    def test_conta_por_tipo(self) -> None:
        met = metricas_mod.MetricasDoAgr()
        minimise(
            "liga ao 912345678 e ao 923456789, entrego no Maianga",
            _ctx(),
            metricas=met,
        )
        lido = met.ler()
        self.assertEqual(lido[f"{metricas_mod.METRICA_PII_MASCARADA}:telefone"], 2)
        self.assertEqual(lido[f"{metricas_mod.METRICA_PII_MASCARADA}:morada"], 1)

    def test_a_exposicao_nao_leva_nenhum_valor_detectado(self) -> None:
        """A barreira medida no sitio onde ela importa: o texto do `/metrics`."""
        met = metricas_mod.MetricasDoAgr()
        minimise(
            "liga ao 912345678, o e-mail e joao@exemplo.co.ao, entrego no Maianga",
            _ctx(),
            metricas=met,
        )
        exposto = met.exposicao()
        for plantado in ("912345678", "joao@exemplo.co.ao", "Maianga", "maianga"):
            with self.subTest(plantado=plantado):
                self.assertNotIn(plantado, exposto)
        self.assertIn(metricas_mod.METRICA_PII_MASCARADA, exposto)
        self.assertIn(metricas_mod.METRICA_MINIMISE_LATENCIA, exposto)

    def test_os_valores_da_etiqueta_derivam_dos_tipos(self) -> None:
        """Uma lista literal transformava uma invariante num numero."""
        met = metricas_mod.MetricasDoAgr()
        for tipo in TIPOS:
            with self.subTest(tipo=tipo):
                met.contar(metricas_mod.METRICA_PII_MASCARADA, tipo.lower())
        with self.assertRaises(metricas_mod.EtiquetaInvalida):
            met.contar(metricas_mod.METRICA_PII_MASCARADA, "inventado")

    def test_a_latencia_e_uma_medida(self) -> None:
        met = metricas_mod.MetricasDoAgr()
        minimise("ola", _ctx(), metricas=met)
        self.assertIn(metricas_mod.METRICA_MINIMISE_LATENCIA, met.ler())

    def test_o_tenant_id_nao_entra_em_etiqueta(self) -> None:
        """`OBS-I`: um UUID tem hifenes e nao casa a gramatica."""
        met = metricas_mod.MetricasDoAgr()
        with self.assertRaises(metricas_mod.EtiquetaInvalida):
            met.contar(metricas_mod.METRICA_PII_MASCARADA, TENANT)


# -------------------------------------------------- o contexto do gateway

#: O `ContextoDeChamada` que os ensaios do gateway usam. Importa-se da bateria
#: dele para nao haver duas verdades sobre a forma dele.
from test_llm_cliente import CTX as _CTX_DO_GATEWAY  # noqa: E402


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
