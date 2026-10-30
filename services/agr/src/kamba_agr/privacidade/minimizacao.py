"""`minimise(texto, ctx) -> (MinimisedText, Mapa)`: a unica via para o LLM e o STT.

E o KAM-112. Este modulo e a barreira; o `detector.py` e o `negocio.py` sao o
como.

## As quatro barreiras, e nenhuma delas e uma convencao

**1. O tipo e a barreira (criterio 1).** O `ClienteDeLlm.chamar` passou a exigir
`MinimisedText`, e um `MinimisedText` **so se constroi aqui**. Nao e um `NewType`
nem um alias: e uma classe com um selo privado deste modulo, e
`MinimisedText("telefone 912345678")` levanta.

Porque e que nao e um `NewType`: **nao ha verificador de tipos para Python neste
repositorio**, medido — o `make typecheck` e `pnpm -r run typecheck` e cobre
TypeScript; o `ci-2` corre `typecheck`, `lint-arch` e `log-lint`, e nenhum le
anotacoes de Python. Um `NewType` seria exactamente a «convencao documentada» que
o bloco recusa: invisivel em execucao e nao verificada por maquina nenhuma. Com o
selo, a barreira morde **em execucao** e o teste de arquitectura morde na
**fonte**, e nenhuma das duas depende de um verificador que nao existe.

**2. Falha fechada (criterio 7).** Qualquer erro do detector levanta
`FalhaDeMinimizacao`, que vive no `llm/erros.py` e **e** um `ErroDeLlm`: o
`classify` do Vendedor apanha-a pelo tipo que ja apanha, o `degradacao.py` da-lhe
o motivo `minimizacao`, e o turno responde pelo menu deterministico (KAM-037) ou
vai a *handoff*. Nunca «segue sem minimizar» — nao ha caminho no codigo que
devolva o texto original.

E ha um tecto de tempo: o `TECTO_MS`. Um detector que demore mais do que isso
**falha** em vez de atrasar o turno, porque o criterio 7 nomeia o *timeout* ao
lado do erro.

**3. O mapa nunca sai do AGR (criterio 6).** Vive no `ConversaState["pii_map"]`,
com a retencao do *checkpointer*, e o `Mapa` tem um `__repr__` que mostra
**contagens por tipo** e nunca valores — para que um `f"{mapa}"` num log, que e
como isto vazaria, nao leve nada. Nao entra em `dat.llm_call_log` (que nao tem
coluna de texto, verificado), nao entra em metrica (as metricas levam **o tipo**),
nao entra em evento.

**4. Um token devolvido pelo modelo e ausente do mapa e removido**, nunca
adivinhado (`reidentificar`). Um modelo que invente `TELEFONE_7` nao faz aparecer
um telefone que ninguem escreveu.

## O mapa e por *thread* e nao por turno, e a razao foi medida nesta casa

O `pii_map` entra no `ConversaState` e fica **fora** de duas tabelas: fora do
`CAMPOS_DO_TURNO` (que o `reiniciar` devolve) e fora do `estado_inicial` (que o
`turno.py` passa ao `ainvoke` em **cada** turno, sobrescrevendo o que o
*checkpoint* tinha). E exactamente a assimetria do `turn_seq` do KAM-114, e pela
mesma razao mecanica: uma chave que nasca no `estado_inicial` sobrescreve a do
*checkpoint*.

Porque e que tem de atravessar turnos: a janela de mensagens (`recortar_janela`,
20 mensagens) leva as mensagens **minimizadas** dos turnos anteriores. Um
`TELEFONE_1` escrito no turno 1 reaparece no *prompt* do turno 3; com um mapa por
turno, o turno 3 nao sabia o que ele era e a re-identificacao removia-o — isto e,
a resposta ao cliente perdia o telefone que ele proprio tinha dado. E a
numeracao tem de ser estavel pela mesma razao: o mesmo telefone da o mesmo token
em toda a conversa, o que tambem poupa *tokens* de modelo.

A retencao e a do *checkpointer* e nao uma nossa: o `adelete_thread` apaga o
*thread* e leva o mapa com ele, e a purga por classe de dados e o KAM-071. Nao se
acrescenta tabela nenhuma — a licao do KAM-160 («um terceiro sitio para o mesmo
facto seria uma terceira verdade»).

## O que este modulo nao faz, por decisao do bloco

O *gate* de destino (KAM-069) — que o `llm/destinos.py` ja consulta —, os logs
sem conteudo (KAM-068, fechado), o classificador de dados sensiveis (KAM-033) e
os agregados anonimizados. E **nao mascara audio**: o criterio diz que no STT a
minimizacao e nao enviar metadados com o *blob*, e a transcricao entra depois
neste mesmo caminho (o gancho do KAM-036).
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Callable
from typing import Any, Final

from .. import metricas as metricas_mod
from ..llm.erros import FalhaDeMinimizacao
from . import detector as detector_mod
from . import negocio
from . import catalogo as catalogo_mod
from .catalogo import CatalogoVazio, PortaDeCatalogo
from .dicionarios import dobrar

#: A chave do `ConversaState` onde o mapa vive. Dicionario §3.37.
CHAVE_DO_MAPA: Final = "pii_map"

#: O tecto de tempo do detector, em milissegundos. Passa-lo **falha fechado**.
#:
#: **Nao e o limiar do criterio 7, e a diferenca importa.** O criterio da uma
#: *sobrecarga p95 <= 30 ms para 2.000 caracteres* como ***proposta a calibrar no
#: Piloto***: e um alvo de desenho que se **mede**, e nada falha por o exceder.
#: Este `TECTO_MS` e outra coisa — e o ponto a partir do qual a minimizacao se
#: **recusa**, e esta muito acima do alvo de proposito, porque um detector a
#: 40 ms e lento e nao esta avariado.
#:
#: **E uma verificacao a posteriori e NAO um *timeout*, e a primeira versao desta
#: nota afirmava o contrario.** Dizia «um detector que demore mais do que isso
#: **falha** em vez de atrasar o turno» e que «o que ele apanha e a expressao
#: regular que entrou em retrocesso catastrofico» — e as duas eram falsas: o
#: `decorrido` mede-se **depois** de o detector ter corrido, pelo que o turno **e**
#: atrasado o tempo inteiro e uma expressao em retrocesso bloquearia o
#: trabalhador os trinta segundos que levasse. Medido pela revisao adversarial,
#: com um detector a dormir 400 ms: levantou **depois** dos 400 ms.
#:
#: O que este tecto garante, e e o que o criterio 7 pede pela letra, e que uma
#: minimizacao lenta **nao chega ao LLM**: a chamada nao sai e o turno degrada.
#: O que ele **nao** garante e que o turno nao demore.
#:
#: Interromper a serio obrigava a um `signal.alarm` (que nao vale em *threads*,
#: e o AGR corre um `asyncio.Task` por conversa) ou a correr o detector noutro
#: processo — que e muito mais caro do que o problema, enquanto o p95 medido e de
#: 5 ms contra um tecto de 250. Fica como lacuna declarada, nao como propriedade
#: afirmada.
#:
#: *Proposta*. Calibra-se no Piloto (KAM-109) com a distribuicao real de
#: comprimentos de mensagem.
#:
#: shortcut: verificacao a posteriori e nao interrupcao — um detector patologico
#: atrasa o turno antes de a chamada ser recusada; revê-se no KAM-109 se o p95
#: medido se aproximar do tecto.
TECTO_MS: Final = 250

#: O comprimento de texto a que o alvo do criterio 7 se refere.
COMPRIMENTO_DE_REFERENCIA: Final = 2_000

#: A sobrecarga p95 que o criterio 7 da como ***proposta***, em milissegundos,
#: para `COMPRIMENTO_DE_REFERENCIA` caracteres. **Mede-se e publica-se; nao
#: falha nada.** Ver a nota do `TECTO_MS`.
ALVO_P95_MS: Final = 30

#: A forma de um token. Fechada, e e a dos seis tipos do criterio 2.
#:
#: Usa-se para **remover** os tokens que o modelo invente (criterio 6), pelo que
#: tem de casar exactamente o que o `_token` produz — ha um teste de ida e volta
#: que o garante.
FORMA_DO_TOKEN: Final = re.compile(
    r"\b(?:" + "|".join(detector_mod.TIPOS) + r")_\d+\b"
)

#: A chave do selo, nova a cada arranque do processo. **Privada do modulo.**
#:
#: **A primeira versao deste modulo tinha um `_SELO: Final = object()` passado
#: como campo, e a revisao adversarial forjou um `MinimisedText` de tres
#: maneiras.** Vale escreve-las, porque o remedio e desenhado contra elas:
#:
#: | Forja | Porque passava |
#: |---|---|
#: | `dataclasses.replace(m, texto=cru)` | o `replace` reinvoca o `__init__` com o selo **real** do objecto de partida, e o `__post_init__` aceitava-o |
#: | `object.__setattr__(m, "texto", cru)` | o `frozen=True` protege o `__setattr__` da classe, nao o do `object` |
#: | `MinimisedText(cru, m.selo)` | o selo era **campo publico**: o `repr=False` esconde-o do `repr`, nao do acesso |
#:
#: As tres tem a mesma causa: **o selo provava quem construiu, nao o que ficou
#: construido.** Um selo que seja o mesmo valor para qualquer texto pode ser
#: copiado de um objecto legitimo para um forjado.
#:
#: O remedio e **ligar o selo ao texto**: a `impressao` e um HMAC do texto com
#: esta chave, pelo que copia-la para outro texto da uma impressao que nao
#: corresponde. As tres forjas fecham de uma vez — as duas primeiras no
#: `__post_init__`, a terceira porque nao ha impressao valida para um texto que
#: nao passou aqui —, e a quarta (construir a mao um `MensagemMinimizada` com um
#: pato qualquer) fecha no `__post_init__` dela.
#:
#: **Nao e criptografia a serio e nao precisa de ser.** O que esta barreira
#: defende nao e contra um atacante: e contra o proximo programador desta casa a
#: escrever, de boa-fe, a linha que parece funcionar. Contra isso, uma chave de
#: processo e um HMAC de 32 octetos sao mais do que suficientes, e o custo e de
#: microssegundos por chamada.
_CHAVE_DO_SELO: Final = secrets.token_bytes(32)


def _impressao(texto: str) -> str:
    """O selo de um texto que passou pelo detector. **Privado do modulo.**

    A politica AST recusa uma referencia a este nome fora do
    `privacidade/minimizacao.py`, pela mesma razao que recusava a do `_SELO`:
    e a unica via para construir um `MinimisedText` valido.
    """
    return hmac.new(_CHAVE_DO_SELO, texto.encode("utf-8"), hashlib.sha256).hexdigest()


class TextoNaoMinimizado(TypeError):
    """Alguem tentou construir um `MinimisedText` sem passar pelo `minimise`.

    **E `TypeError` e nao `ValueError`**, e nao e cosmetica: o criterio 1 pede que
    chamar o gateway com texto nao minimizado «falhe **no tipo**», e esta e a
    excepcao que o diz. Nao e um `ErroDeLlm`: nao e uma falha de execucao que
    degrade um turno, e um defeito de programacao — e um defeito de programacao
    deve fazer o turno falhar e voltar a fila, nao responder ao cliente por menu.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class MinimisedText:
    """Texto que passou pelo detector. **Construido so pelo `minimise`.**

    O nome fica em ingles porque e o nome do criterio 1 e do dicionario §3.37 —
    a mesma regra que deixou `Verdict`, `Policy` e `handoff_wait` em ingles
    (`validador/__init__.py`).

    A `impressao` nao e dado: e a prova de que **este texto** passou pelo
    detector. Nao prova quem construiu — prova o que ficou construido, e e essa
    a diferenca que fechou as tres forjas que a revisao adversarial encontrou
    (ver a nota do `_CHAVE_DO_SELO`).
    """

    texto: str
    #: O HMAC do `texto` com a chave do processo. `compare=False` porque nao e
    #: dado — dois textos iguais tem a mesma impressao, e compara-la era compara
    #: o texto duas vezes; `repr=False` porque nao serve a ninguem num registo.
    impressao: str = dataclasses.field(default="", compare=False, repr=False)

    def __post_init__(self) -> None:
        self._exigir()

    def _exigir(self) -> None:
        """A impressao corresponde ao texto? Levanta se nao.

        `compare_digest` e nao `==`: e a comparacao que nao vaza por tempo. Aqui
        nao ha atacante a medir (ver a nota do `_CHAVE_DO_SELO`), e usa-se de
        qualquer maneira porque e a forma certa de comparar um HMAC e porque
        escrever `==` aqui ensinava a escreve-lo onde conta.
        """
        # `isinstance` antes do `compare_digest`: aquele levanta `TypeError`
        # sobre um `None` ou um `int`, e o criterio 1 pede que isto falhe **no
        # tipo** com a nossa excepcao e nao com a do `hmac`. Medido pela bateria.
        if not isinstance(self.impressao, str) or not isinstance(self.texto, str):
            raise TextoNaoMinimizado(
                "um `MinimisedText` leva texto e uma impressao, os dois cadeias"
            )
        if not hmac.compare_digest(self.impressao, _impressao(self.texto)):
            raise TextoNaoMinimizado(
                "um `MinimisedText` so se obtem de `minimise(texto, ctx)`: "
                "chamar o gateway de LLM com texto nao minimizado e a "
                "transferencia que o KAM-112 existe para fechar (ADR-008, "
                "ADR-010, criterio 1)"
            )

    def verificada(self) -> str:
        """O texto, **re-verificado no momento de o usar**.

        **Existe por causa de uma das tres forjas**, e e a unica que o
        `__post_init__` nao pode apanhar: um `object.__setattr__(m, "texto",
        cru)` reescreve o campo **sem** passar pelo construtor, pelo que a
        validacao da construcao nunca corre outra vez. A impressao, porem,
        continua a ser a do texto antigo — e por isso uma re-verificacao no
        ponto de uso apanha-a.

        Quem chama isto e o `MensagemMinimizada.para_esquema`, que e o ultimo
        ponto antes do corpo HTTP. E o sitio certo: entre a construcao e a
        chamada pode ter acontecido qualquer coisa, e o que importa e o que vai
        **sair**.
        """
        self._exigir()
        return self.texto

    def __str__(self) -> str:
        return self.texto


@dataclasses.dataclass(frozen=True, slots=True)
class Mapa:
    """Token -> valor original. **Nunca sai do AGR** (criterio 6).

    Vive no `ConversaState[CHAVE_DO_MAPA]` e persiste com o *checkpointer*; o
    `para_estado` e o `do_estado` sao as duas unicas travessias, e sao para la e
    de la.
    """

    #: Token -> o texto original que ele substituiu.
    #:
    #: **Nao leva o telefone do contacto do turno**, e isso e o §8.4 do
    #: `docs/tecnica/02` mais o KAM-008: o contacto e sempre «Cliente» e o
    #: telefone dele continua so em `contact_endpoints` cifrado. O que entra aqui
    #: e o que o **cliente escreveu no texto**, que e outra coisa — um telefone de
    #: terceiro, a morada de entrega, o nome de um colega.
    valores: dict[str, str] = dataclasses.field(default_factory=dict)

    def __repr__(self) -> str:
        """Contagens por tipo. **Nunca valores, nunca tokens.**

        E a barreira do criterio 6 na forma mais barata que ha: o modo como um
        mapa vazaria e alguem pôr `f"{mapa}"` ou `repr(mapa)` num `extra` de log,
        num *trace* ou numa mensagem de excepcao. Com este `__repr__` isso leva
        `Mapa(telefone=2, morada=1)` e mais nada.

        **Tambem nao mostra os tokens**, e a primeira versao mostrava: um
        `TELEFONE_3` nao e PII por si, mas a contagem por tipo ja diz tudo o que
        um painel precisa e um token num log convida a cruza-lo com o
        *checkpoint*.
        """
        contagem: dict[str, int] = {}
        for token in self.valores:
            tipo = token.rsplit("_", 1)[0].lower()
            contagem[tipo] = contagem.get(tipo, 0) + 1
        dentro = ", ".join(f"{tipo}={quantos}" for tipo, quantos in sorted(contagem.items()))
        return f"Mapa({dentro})"

    def para_estado(self) -> dict[str, str]:
        """O `dict` simples que o *checkpointer* serializa.

        Copia e nao a referencia: o estado do LangGraph passa por redutores que
        comparam identidade, e devolver a referencia deixava quem mutasse o
        `dict` a mudar o mapa sem passar por aqui.
        """
        return dict(self.valores)

    def quantos(self) -> int:
        return len(self.valores)


def do_estado(estado: dict[str, Any] | None) -> Mapa:
    """O mapa de um estado de *thread*, ou um vazio.

    `estado.get(CHAVE_DO_MAPA) or {}` e nao `estado[CHAVE_DO_MAPA]`: a chave esta
    **ausente** no primeiro turno, porque nao nasce no `estado_inicial` (ver a
    nota do modulo). Todos os leitores desta casa usam a forma com `get`, e o
    `total=False` do `ConversaState` e o que a permite.

    Um valor que nao seja um `dict` de texto para texto conta como vazio em vez
    de levantar: um *checkpoint* escrito a mao nao deve parar uma conversa, e o
    pior que acontece com um mapa vazio e perderem-se re-identificacoes — nunca
    uma transferencia.
    """
    if not estado:
        return Mapa()
    bruto = estado.get(CHAVE_DO_MAPA) or {}
    if not isinstance(bruto, dict):
        return Mapa()
    return Mapa(
        {
            str(token): str(valor)
            for token, valor in bruto.items()
            if isinstance(token, str) and isinstance(valor, str)
        }
    )


@dataclasses.dataclass(frozen=True, slots=True)
class ContextoDeMinimizacao:
    """O que o `minimise` precisa de saber. **Nenhum identificador do contacto.**

    O `ctx` do criterio 1. Nao leva `contact_id` nem telefone: o contacto do turno
    e sempre «Cliente» (`docs/tecnica/02` §8.4) e isso nao precisa de saber quem
    ele e. Leva o `thread_id` porque e a chave do mapa, e o `tenant_id` porque e
    por ele que os nomes do catalogo se leem.
    """

    tenant_id: str
    thread_id: str
    #: O mapa que vem do *checkpoint*, para que a numeracao seja estavel na
    #: conversa inteira.
    mapa: Mapa = dataclasses.field(default_factory=Mapa)
    #: Os nomes que sao *facts* do catalogo (criterio 5), na forma dobrada.
    do_catalogo: frozenset[str] = frozenset()
    #: O padrao do NIF. `None` significa «o NIF nao e detectado por padrao
    #: proprio» — ver o `detector.PADRAO_DE_NIF`.
    padrao_de_nif: re.Pattern[str] | None = None


def contexto_de(
    estado: dict[str, Any],
    *,
    catalogo: PortaDeCatalogo | None = None,
    padrao_de_nif: re.Pattern[str] | None = None,
) -> ContextoDeMinimizacao:
    """O contexto a partir de um `ConversaState`. A via que o grafo usa.

    Le o mapa do *checkpoint* e os nomes do catalogo **uma vez por turno** — o
    `minimise` nao vai a base de dados (ver a nota do `catalogo.py`).
    """
    porta = catalogo or CatalogoVazio()
    tenant_id = str(estado.get("tenant_id") or "")
    return ContextoDeMinimizacao(
        tenant_id=tenant_id,
        thread_id=str(estado.get("thread_id") or ""),
        mapa=do_estado(estado),
        do_catalogo=porta.nomes(tenant_id),
        padrao_de_nif=padrao_de_nif,
    )


def _token(tipo: str, indice: int) -> str:
    return f"{tipo}_{indice}"


def _aplicar(
    texto: str, achados: tuple[detector_mod.Achado, ...], anterior: Mapa
) -> tuple[str, dict[str, str], dict[str, int]]:
    """Substitui os achados por tokens. Devolve `(texto, mapa, contagem)`.

    Extraido do `minimise` para que o `try` dele cubra **esta** parte tambem —
    ver a nota la. A numeracao continua a de `anterior`, que e o mapa do
    *checkpoint*: um valor que ja tem token mantem-no, e e isso que torna o
    token estavel no *thread*.
    """
    valores = dict(anterior.valores)
    por_valor = {valor: token for token, valor in valores.items()}
    proximo: dict[str, int] = {}
    for token in valores:
        tipo, _, numero = token.rpartition("_")
        if numero.isdigit():
            proximo[tipo] = max(proximo.get(tipo, 0), int(numero))

    # **Duas passagens, e a separacao corrige um defeito medido.** A primeira
    # atribui tokens pela ordem do **texto**; a segunda substitui de **tras para
    # a frente**, porque substituir da frente desloca os indices dos seguintes.
    #
    # Numa passagem so, de tras para a frente, a atribuicao seguia a ordem da
    # substituicao: «entregar em X, perto do Y» dava `MORADA_2` ao X e `MORADA_1`
    # ao Y — a numeracao ao contrario da leitura. Nao e cosmetica: o criterio 2
    # da `TELEFONE_n` como uma sequencia, e um *prompt* onde o primeiro
    # identificador e o `_3` convida o modelo a inferir que houve dois antes dele.
    contagem: dict[str, int] = {}
    atribuido: list[tuple[detector_mod.Achado, str]] = []
    for achado in achados:  # ja vem ordenado por posicao
        token = por_valor.get(achado.valor)
        if token is None:
            proximo[achado.tipo] = proximo.get(achado.tipo, 0) + 1
            token = _token(achado.tipo, proximo[achado.tipo])
            valores[token] = achado.valor
            por_valor[achado.valor] = token
        atribuido.append((achado, token))
        contagem[achado.tipo] = contagem.get(achado.tipo, 0) + 1

    pedacos = list(texto)
    for achado, token in reversed(atribuido):
        pedacos[achado.inicio : achado.fim] = list(token)

    return "".join(pedacos), valores, contagem


def minimise(
    texto: str,
    ctx: ContextoDeMinimizacao,
    *,
    metricas: metricas_mod.MetricasDoAgr | None = None,
    agora: Callable[[], float] = time.monotonic,
) -> tuple[MinimisedText, Mapa]:
    """Mascara a PII de `texto` e devolve o texto minimo e o mapa.

    E a **unica** via para o `ClienteDeLlm.chamar` (criterio 1) e para o gancho do
    STT (KAM-036).

    Levanta `FalhaDeMinimizacao` — que e um `ErroDeLlm` — quando o detector falha
    ou passa o `TECTO_MS`. **Nao ha ramo que devolva o texto original**: o
    criterio 7 e falha fechada, e a chamada ao LLM nao acontece.

    O mapa devolvido **inclui** o que ja vinha de `ctx.mapa`, para que a
    numeracao seja estavel no *thread* e para que a `reidentificar` de um turno
    saiba dos tokens dos anteriores.
    """
    medidor = metricas or metricas_mod.METRICAS
    inicio = agora()

    if not isinstance(texto, str):
        raise FalhaDeMinimizacao(
            f"o `minimise` recebeu {type(texto).__name__} e nao texto"
        )

    # **O `try` cobre o corpo inteiro e nao so o `detectar`, e e a correccao do
    # achado 12 da revisao adversarial.** A primeira versao envolvia so a chamada
    # ao detector, e tudo o que vem depois — a leitura do `ctx.mapa`, a
    # atribuicao de tokens, a substituicao e as duas chamadas as metricas —
    # corria fora dela. Isto e, metade da funcao podia levantar uma excepcao que
    # **nao** era `FalhaDeMinimizacao`, e o comentario abaixo explicava porque e
    # que isso nao podia acontecer.
    #
    # Medido pela revisao: um `ctx.mapa` que nao fosse um `Mapa` dava
    # `AttributeError`, e um tipo fora da lista fechada dava `EtiquetaInvalida`.
    # Nenhum dos dois era alcancavel hoje — o `TIPOS` e derivado e o contexto e
    # um dataclass —, mas a barreira estava no sitio errado e pôr-la no sitio
    # certo custa zero.
    try:
        achados = detector_mod.detectar(
            texto,
            do_catalogo=ctx.do_catalogo,
            padrao_de_nif=ctx.padrao_de_nif,
        )
        minimo, valores, contagem = _aplicar(texto, achados, ctx.mapa)
    except negocio.ReclamouDemais as erro:
        # Uma das expressoes do `negocio.py` esta errada. Falha fechada: a
        # alternativa era devolver o texto quase intacto a dizer que estava
        # minimizado, que e a pior falha deste ticket porque passa por sucesso.
        raise FalhaDeMinimizacao(f"os numeros de negocio cobrem o texto: {erro}") from erro
    except FalhaDeMinimizacao:
        # Ja e a nossa: nao se embrulha outra vez, senao a mensagem fica aninhada.
        raise
    except Exception as erro:  # noqa: BLE001 — criterio 7, e a razao vai na mensagem
        # **O `except Exception` esta aqui de proposito e e o oposto do que o
        # `degradacao.py` faz**, que nao tem nenhum. A diferenca: ali, engolir
        # escondia um Postgres em baixo; aqui, **nao** engolir deixava um defeito
        # do detector transformar-se num turno falhado em vez de um turno
        # degradado — e o cliente nao recebia nada. O criterio 7 nomeia os dois
        # desfechos aceitaveis (deterministico ou *handoff*) e nenhum deles e
        # «o turno falha».
        #
        # **A mensagem nao leva o texto**, e isso e deliberado: seria PII numa
        # excepcao, que e o caminho que o `llm/erros.py` fechou para o corpo do
        # fornecedor. Ha um ensaio que o mede.
        raise FalhaDeMinimizacao(f"o detector de PII falhou: {erro}") from erro

    decorrido = max(0, int((agora() - inicio) * 1000))

    if decorrido > TECTO_MS:
        # **Passar o tecto falha, e nao se devolve o resultado.** Devolve-lo
        # «porque ja esta feito» era deixar um turno demorar um segundo por uma
        # expressao em retrocesso, e o proximo turno igual.
        raise FalhaDeMinimizacao(
            f"o detector de PII levou {decorrido} ms, acima do tecto de {TECTO_MS} ms"
        )

    # **As metricas levam o tipo e a duracao. Nunca o texto detectado** — e o
    # «metricas sem valores» do bloco. O tipo e lista fechada e casa a gramatica
    # de etiqueta em minusculas.
    for tipo, quantos in contagem.items():
        medidor.contar(metricas_mod.METRICA_PII_MASCARADA, tipo.lower(), quantos)
    medidor.medir(metricas_mod.METRICA_MINIMISE_LATENCIA, decorrido)

    return MinimisedText(minimo, _impressao(minimo)), Mapa(valores)


@dataclasses.dataclass(frozen=True, slots=True)
class MensagemMinimizada:
    """Uma mensagem para o modelo, cujo conteudo passou pelo detector.

    **E este o tipo que o `ClienteDeLlm.chamar` exige, e nao um `dict`.** A
    primeira versao deste modulo devolvia `dict[str, str]` daqui — o esquema que
    o proxy espera — e isso **perdia a barreira exactamente onde ela importa**:
    um `dict` construido a mao e indistinguivel de um construido aqui, pelo que
    `chamar(papel, [{"role": "user", "content": texto_cru}], ctx)` voltava a
    passar. O criterio 1 pede que isso «falhe no tipo», e so falha se o tipo
    sobreviver ate ao `chamar`.

    A traducao para o `dict` do esquema OpenAI-compativel faz-se **dentro** do
    `cliente.py`, no ultimo momento antes do corpo HTTP, onde ja nao ha caminho
    por onde alguem passe outra coisa.
    """

    papel: str
    conteudo: MinimisedText

    def __post_init__(self) -> None:
        """**Valida o tipo do conteudo, e a primeira versao nao validava.**

        Era a quarta forja da revisao adversarial, e a mais barata de todas:
        `MensagemMinimizada("user", pato)` com qualquer objecto que tivesse um
        `.texto` punha texto cru no esquema. A validacao estava na funcao
        `mensagem()`, que se contorna construindo a classe directamente — e uma
        barreira que se contorna por construir a classe nao e uma barreira.

        A guarda do `chamar` verificava `isinstance(item, MensagemMinimizada)` e
        **nao** o conteudo, pelo que esta via era suficiente por si so.
        """
        if not isinstance(self.conteudo, MinimisedText):
            raise TextoNaoMinimizado(
                "o conteudo de uma `MensagemMinimizada` tem de ser um "
                "`MinimisedText` obtido de `minimise(texto, ctx)` e nao um "
                f"{type(self.conteudo).__name__} (KAM-112, criterio 1)"
            )

    def para_esquema(self) -> dict[str, str]:
        """O `{"role": …, "content": …}` que o proxy espera.

        Chama `verificada()` e nao `.texto`: e o ultimo ponto antes do corpo
        HTTP, e e aqui que um `object.__setattr__` entre a construcao e a chamada
        se apanha. Ver a nota do `MinimisedText.verificada`.
        """
        return {"role": self.papel, "content": self.conteudo.verificada()}


def mensagem(papel: str, conteudo: MinimisedText) -> MensagemMinimizada:
    """Uma mensagem minimizada. A **unica** via para o `chamar`.

    O `conteudo` tem de ser um `MinimisedText`, e um `MinimisedText` so sai do
    `minimise`.
    """
    if not isinstance(conteudo, MinimisedText):
        raise TextoNaoMinimizado(
            "o conteudo de uma mensagem para o LLM tem de ser um "
            "`MinimisedText` obtido de `minimise(texto, ctx)` (criterio 1)"
        )
    return MensagemMinimizada(papel, conteudo)


def reidentificar(texto: str, mapa: Mapa) -> str:
    """Repoe os valores do mapa no texto que o modelo devolveu.

    **Um token ausente do mapa e removido, nunca adivinhado** (criterio 6). Um
    modelo que invente `TELEFONE_7` nao faz aparecer um telefone que ninguem
    escreveu, e deixar o token cru na resposta era mandar ao cliente uma palavra
    que nao significa nada para ele.

    A remocao apara tambem o espaco que sobre, para que «liga ao TELEFONE_7 por
    favor» nao fique com dois espacos.
    """

    def substituir(encontrado: re.Match[str]) -> str:
        return mapa.valores.get(encontrado.group(0), "")

    reposto = FORMA_DO_TOKEN.sub(substituir, texto)
    # Dois ou mais brancos seguidos viram um; um branco antes de pontuacao sai.
    reposto = re.sub(r"[ \t]{2,}", " ", reposto)
    return re.sub(r" +([,.;:!?])", r"\1", reposto).strip()


def tokens_desconhecidos(texto: str, mapa: Mapa) -> tuple[str, ...]:
    """Os tokens que o modelo devolveu e que o mapa nao conhece.

    Existe para a bateria e para quem quiser contar o fenomeno; o
    `reidentificar` nao precisa dela para os remover.
    """
    return tuple(
        sorted(
            {
                encontrado.group(0)
                for encontrado in FORMA_DO_TOKEN.finditer(texto)
                if encontrado.group(0) not in mapa.valores
            }
        )
    )


def nomes_dobrados(nomes: object) -> frozenset[str]:
    """Normaliza uma coleccao de nomes para a forma que o detector compara.

    Conveniencia para quem tenha os nomes do catalogo em bruto — a
    `PortaDeCatalogo` ja os devolve dobrados, e esta funcao existe para os
    chamadores que os tenham de outra fonte.

    **Aplica o mesmo `COMPRIMENTO_MINIMO` que a porta, e a primeira versao nao
    aplicava.** Era uma lacuna e nao uma assimetria: esta funcao e o **segundo**
    caminho para a mesma lista, e um nome de uma ou duas letras que entrasse por
    aqui fazia qualquer «a» do texto cair na lista de nao mascarar — e com ele os
    nomes proprios que o contivessem. A barreira tem de estar nos dois caminhos
    ou nao esta em nenhum; apanhado pela bateria antes de haver chamador.
    """
    if not isinstance(nomes, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(
        dobrado
        for nome in nomes
        if isinstance(nome, str)
        and len(dobrado := dobrar(nome).strip()) >= catalogo_mod.COMPRIMENTO_MINIMO
    )
