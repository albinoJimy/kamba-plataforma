"""Embeddings do catalogo e da pergunta, com o *gate* de destino (KAM-063).

    ClienteDeEmbeddings    o **unico** sitio que chama um fornecedor de embeddings,
                           e so depois de a porta de destinos autorizar **todos**
                           os fornecedores que ele pode alcancar
    ConsultaVectorial      o vector da pergunta, ou `None` (modo lexical) quando o
                           destino nao esta autorizado, o texto e sensivel, passa
                           o tecto de 1,5 s ou falha
    embeber_catalogo       uma volta do *worker*: le os documentos por embeber,
                           pede os vectores e grava-os com o modelo

## O embedding da pergunta e uma transferencia, e a falha e para lexical

O texto do cliente pode trazer nome, bairro ou um tema de saude, e o fornecedor
esta no estrangeiro: e transferencia por defeito (`docs/tecnica/08` §8.3,
INDICIO; a pseudonimizacao e a confirmar por parecer). Por isso a regra do
modulo e a do `kamba_core.destinos.porta`: **sem destino autorizado com
`apd_ref`, a chamada nao sai** — e a pesquisa responde em lexical (`p_qvec =
NULL`), sem erro ao cliente. O `idx.candidatos` ja aceita o vector nulo com o
mesmo ranking lexical (KAM-061); nao se toca na funcao.

Qualquer erro da porta e uma recusa: linha ausente, base indisponivel, tenant
ilegivel, excepcao de quem a implementa. **Falha fechada sobre a uniao** dos
fornecedores do alias, pela razao do `cliente.py` do AGR: o *fallback* do proxy
escolhe o fornecedor depois de o pedido sair, e autorizar so o primeiro deixava
o segundo receber o texto sem ninguem o ter autorizado.

## O que nunca vai ao fornecedor

* **Uma pergunta sensivel ou com identificador directo** (criterio 4). Quem
  decide e um detector que o chamador passa (`sensivel`): este nucleo nao tem
  detector de PII, e o do AGR (`kamba_agr.privacidade`, KAM-112 e KAM-033) e o
  que corre na pergunta do cliente. Um detector que levanta conta como sensivel
  — falha fechada outra vez.
* **Preco, stock, telefone ou contacto no texto do catalogo** (criterio 5, a
  regra (b) do §4.2): o `texto.exigir_texto_de_embedding` recusa-o, e o
  documento fica sem vector, isto e, so lexical.

## O tecto da pergunta corta a espera, e a chamada fica pelo lado

O criterio 3 da 1,5 s. A porta corre **antes** e fora do tecto — e local e tem
*cache* de 60 s —, e o fornecedor corre numa *thread* com `result(timeout)`: ao
passar o tecto a pesquisa segue em lexical. O fornecedor recebe o mesmo tecto
para o seu transporte, que e quem de facto liberta a *thread*; uma resposta
tardia deita-se fora. **O que isto nao faz:** cancelar um pedido HTTP ja em voo.
Um fornecedor que ignore o tecto ocupa uma das `_TRABALHADORES` *threads* ate
acabar.

## Um vector so se compara com vectores do mesmo modelo

A coluna `idx.search_doc.embedding` e uma so (`halfvec(1024)`, PROP-IDX-4), e
dois modelos na mesma coluna dao distancias sem significado. Tres defesas, das
quais nenhuma e DDL:

1. o *worker* **nao escreve** um modelo num tenant que ja tenha vectores de
   outro (`modelo_divergente`, no SQL e antes de chamar o fornecedor);
2. a pesquisa so passa a hibrida se o tenant tem vectores de **um** modelo, e e
   esse o que a pergunta tem de trazer (`modelos_do_indice`);
3. a dimensao do vector confere com a da coluna antes de chegar ao SQL.

A troca **atomica** de modelo do criterio 6 — escrever numa coluna nova e
comutar — e uma revisao de base de dados e nao se faz aqui: hoje trocar de
modelo e limpar os vectores do tenant e reembeber, com a pesquisa em lexical
entretanto. Ver a verificacao do bloco.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as EsperaEsgotada
from dataclasses import dataclass
from typing import Final, Protocol

from kamba_core.destinos import FINALIDADE_EMBEDDINGS
from kamba_core.eventos.consumo import ClienteSql

from .metricas import METRICAS, MetricasDoIdx
from .texto import TextoDeEmbeddingProibido, exigir_texto_de_embedding, normalizar

#: A finalidade de transferencia destas chamadas, do dominio da `0036`.
FINALIDADE: Final = FINALIDADE_EMBEDDINGS

#: A dimensao da coluna `idx.search_doc.embedding` (`halfvec(1024)`, §4.2). Um
#: vector com outra dimensao nao cabe nela, e no `<=>` do `idx.candidatos` a
#: diferenca de dimensao e um erro e nao uma distancia.
DIMENSAO: Final = 1024

#: O maior valor finito de meia precisao, que e o que o `halfvec` guarda.
MAXIMO_DO_HALFVEC: Final = 65504.0

#: O tecto do embedding da pergunta, em segundos (criterio 3).
TECTO_DA_CONSULTA_S: Final = 1.5

#: O tecto de uma chamada do catalogo, em segundos. **Proposta**: e o `timeout`
#: do `kamba-embed` em `llm/aliases.yaml`, e calibra-se com o modelo (KAM-064).
TECTO_DO_CATALOGO_S: Final = 20.0

#: Documentos por chamada do *worker*. **Proposta**, como o lote do KAM-062: uma
#: chamada curta por lote, e o alvo dos 2 000 em <= 10 min mede-se no KAM-194.
LOTE_DE_EMBEDDINGS: Final = 64

#: *Threads* para a espera com tecto da pergunta. Ver a nota do modulo.
_TRABALHADORES: Final = 8

#: Os motivos de queda que este modulo escreve; o dominio e o das metricas.
QUEDA_DESTINO: Final = "destino_negado"
QUEDA_SENSIVEL: Final = "sensivel"
QUEDA_TEMPO: Final = "tempo_esgotado"
QUEDA_FALHA: Final = "falha"
QUEDA_MODELO: Final = "modelo_divergente"


class EmbeddingNegado(RuntimeError):
    """A porta nao autorizou. A mensagem e a da porta: fornecedor, pais, estado."""


class EmbeddingInvalido(RuntimeError):
    """O fornecedor respondeu, e a resposta nao serve. Nunca leva o texto."""


class TempoEsgotado(TimeoutError):
    """O fornecedor nao respondeu dentro do tecto."""


@dataclass(frozen=True)
class Vectores:
    """O que um fornecedor devolve: o modelo que respondeu e um vector por texto."""

    modelo: str
    vectores: tuple[tuple[float, ...], ...]


class FornecedorDeEmbeddings(Protocol):
    """Quem transforma texto em vectores. **So o `ClienteDeEmbeddings` o chama.**

    `fornecedores` sao **todos** os que a chamada pode alcancar (o *fallback* do
    proxy incluido): e sobre eles que a porta corre. Em producao e o adaptador
    do AGR sobre o gateway LiteLLM, com a chave virtual do tenant e a linha em
    `dat.llm_call_log`; nos ensaios, um falso com contador.

    Pode ter um `aceita(texto) -> bool`, opcional: os textos que recusaria
    sozinho, para que o *worker* os conte como recusados um a um em vez de
    perder o lote (`ClienteDeEmbeddings.aceita`).
    """

    fornecedores: tuple[str, ...]

    def __call__(
        self, tenant_id: str, textos: Sequence[str], tecto_s: float
    ) -> Vectores: ...


class PortaDeDestinos(Protocol):
    """O `autorizar` do KAM-069: nao devolve nada, **levanta** se nao autorizar."""

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None: ...


_EXECUTOR: ThreadPoolExecutor | None = None
_TRINCO_DO_EXECUTOR = threading.Lock()


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    with _TRINCO_DO_EXECUTOR:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(
                max_workers=_TRABALHADORES, thread_name_prefix="idx-embeddings"
            )
        return _EXECUTOR


def _validar(resposta: object, quantos: int) -> Vectores:
    """A resposta do fornecedor, ou `EmbeddingInvalido`. **Nao confia nela.**

    Um vector com a dimensao errada rebentava no SQL; um `NaN` ou um infinito
    entrava na coluna e envenenava todas as distancias do tenant; um vector a
    menos deslocava os seguintes para o documento errado.
    """
    if not isinstance(resposta, Vectores):
        raise EmbeddingInvalido(f"o fornecedor devolveu {type(resposta).__name__}")
    if not isinstance(resposta.modelo, str) or not resposta.modelo.strip():
        raise EmbeddingInvalido("o fornecedor nao disse que modelo respondeu")
    if len(resposta.vectores) != quantos:
        raise EmbeddingInvalido(
            f"pediram-se {quantos} vectores e vieram {len(resposta.vectores)}"
        )
    for posicao, vector in enumerate(resposta.vectores):
        if len(vector) != DIMENSAO:
            raise EmbeddingInvalido(
                f"o vector {posicao} tem dimensao {len(vector)} e a coluna {DIMENSAO}"
            )
        if not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
            for x in vector
        ):
            raise EmbeddingInvalido(f"o vector {posicao} tem um valor que nao e finito")
        # O `halfvec` guarda meia precisao: acima de 65 504 o `::halfvec` levanta
        # no SQL — na pesquisa, um erro ao cliente; no *worker*, fora do `try`.
        if any(abs(x) > MAXIMO_DO_HALFVEC for x in vector):
            raise EmbeddingInvalido(f"o vector {posicao} nao cabe em meia precisao")
        # Um vector nulo da `NaN` no `<=>` e o ramo `sem` ordena por `doc_id`.
        if not any(vector):
            raise EmbeddingInvalido(f"o vector {posicao} e nulo")
    return resposta


class ClienteDeEmbeddings:
    """A porta antes de cada chamada, e a chamada. Nao ha outro caminho.

    O ensaio de arquitectura (`services/agr/tests/test_embeddings_arquitectura.py`)
    recusa qualquer chamada ao gateway de embeddings fora do adaptador, e o
    adaptador fora do construtor desta classe.
    """

    def __init__(
        self,
        porta: PortaDeDestinos,
        fornecedor: FornecedorDeEmbeddings,
        *,
        metricas: MetricasDoIdx = METRICAS,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._porta = porta
        self._fornecedor = fornecedor
        self._metricas = metricas
        self._relogio = relogio

    def autorizar(self, tenant_id: str) -> None:
        """Levanta `EmbeddingNegado` se **algum** fornecedor nao estiver autorizado."""
        fornecedores = tuple(getattr(self._fornecedor, "fornecedores", ()) or ())
        if not fornecedores:
            # Um fornecedor que nao diz para onde envia nao se autoriza: nao ha
            # linha de `tenant_destinations` a consultar.
            raise EmbeddingNegado(
                "o fornecedor de embeddings nao declara os seus fornecedores: sem "
                "eles nao ha destino a autorizar (ADR-008, KAM-069)"
            )
        try:
            for fornecedor in fornecedores:
                self._porta.autorizar(tenant_id, fornecedor, FINALIDADE)
        except Exception as erro:  # noqa: BLE001 — falha fechada, e por desenho
            raise EmbeddingNegado(str(erro) or type(erro).__name__) from erro

    def aceita(self, texto: str) -> bool:
        """Se o fornecedor aceita este texto **sozinho**. Um que levanta, nao.

        Existe para que um texto que o fornecedor recusa nao derrube o lote
        inteiro (achado 1 da revisao adversarial): o *worker* pergunta texto a
        texto antes de juntar, e o recusado conta como `recusados`. Um
        fornecedor sem `aceita` aceita tudo o que o *lint* deixou passar.
        """
        filtro = getattr(self._fornecedor, "aceita", None)
        if filtro is None:
            return True
        try:
            return bool(filtro(texto))
        except Exception:  # noqa: BLE001 — na duvida, o texto nao sai
            return False

    def vectores(
        self,
        tenant_id: str,
        textos: Sequence[str],
        *,
        uso: str,
        tecto_s: float,
        esperar: bool = False,
        prazo: float | None = None,
    ) -> Vectores:
        """Os vectores de `textos`, depois da porta. Levanta; nunca devolve meio.

        Com `esperar`, a chamada corre numa *thread* e a espera e cortada no
        `tecto_s` (`TempoEsgotado`). Sem ele, o tecto vai so para o transporte.
        Com `prazo` (no relogio deste cliente), o tecto e o que **sobra** dele
        depois da porta: a porta pode ir a base, e esse tempo conta.
        """
        textos = tuple(textos)
        if not textos:
            raise ValueError("embeber zero textos nao e uma chamada")
        self.autorizar(tenant_id)
        inicio = self._relogio()
        if prazo is not None:
            tecto_s = min(tecto_s, prazo - inicio)
            if tecto_s <= 0:
                raise TempoEsgotado("a porta gastou o prazo do embedding da pergunta")
        if esperar:
            futuro = _executor().submit(self._fornecedor, tenant_id, textos, tecto_s)
            try:
                resposta = futuro.result(timeout=tecto_s)
            except EsperaEsgotada as erro:
                futuro.cancel()
                raise TempoEsgotado(
                    f"o fornecedor de embeddings passou do tecto de {tecto_s} s"
                ) from erro
        else:
            resposta = self._fornecedor(tenant_id, textos, tecto_s)
        decorrido_ms = max(0.0, (self._relogio() - inicio) * 1000.0)
        if decorrido_ms > tecto_s * 1000.0:
            # Um fornecedor que respondeu depois do tecto (sem `esperar`, ou com
            # um transporte que nao o respeita): a resposta nao conta.
            raise TempoEsgotado(
                f"o fornecedor de embeddings respondeu em {decorrido_ms:.0f} ms, "
                f"acima do tecto de {tecto_s} s"
            )
        validada = _validar(resposta, len(textos))
        self._metricas.registar_embedding(uso=uso, duracao_ms=decorrido_ms)
        return validada


# ------------------------------------------------------------------ pergunta


#: Os modelos dos vectores do tenant do contexto, nos documentos visiveis. Ate
#: dois chegam para saber se ha **um** so. Um vector sem modelo conta como um
#: modelo proprio (`NULL`), e por isso nunca se compara com nenhum.
SQL_MODELOS_DO_INDICE: Final = """
  SELECT DISTINCT embedding_modelo
    FROM idx.search_doc
   WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     AND visivel
     AND embedding IS NOT NULL
   LIMIT 2
"""


@dataclass(frozen=True)
class ModeloDoIndice:
    """O modelo unico dos vectores do tenant (ou `None`), e se ha mistura."""

    modelo: str | None
    misturado: bool


def modelo_do_indice(
    linhas: Sequence[Mapping[str, object] | Sequence[object]],
) -> ModeloDoIndice:
    """Le as linhas do `SQL_MODELOS_DO_INDICE`.

    Zero linhas: o tenant nao tem vectores, e nao ha mistura. Uma linha com
    modelo: esse. Duas linhas, ou um vector sem modelo: mistura — nenhum vector
    deste tenant se compara com a pergunta.
    """
    if not linhas:
        return ModeloDoIndice(None, False)
    if len(linhas) != 1:
        return ModeloDoIndice(None, True)
    linha = linhas[0]
    valor = linha["embedding_modelo"] if isinstance(linha, Mapping) else linha[0]
    if isinstance(valor, str) and valor:
        return ModeloDoIndice(valor, False)
    return ModeloDoIndice(None, True)


@dataclass(frozen=True)
class VectorDaConsulta:
    """O vector da pergunta, ou `None`, e porque. `motivo` so quando caiu."""

    qvec: tuple[float, ...] | None
    modelo: str | None
    motivo: str | None


_SEM_VECTOR: Final = VectorDaConsulta(None, None, None)


@dataclass(frozen=True)
class ConsultaVectorial:
    """O que a camada de resposta precisa para tentar o modo hibrido.

    `sensivel` e o detector do criterio 4: `True` quando o texto **nao** pode ir
    ao fornecedor. Quem o passa e o processo que tem o detector (o AGR).
    """

    cliente: ClienteDeEmbeddings
    sensivel: Callable[[str], bool]
    tecto_s: float = TECTO_DA_CONSULTA_S
    metricas: MetricasDoIdx = METRICAS

    def vector(
        self,
        tenant_id: str,
        texto: str,
        modelo_do_indice: str | None,
        *,
        enviar: str | None = None,
        prazo: float | None = None,
    ) -> VectorDaConsulta:
        """O vector da pergunta com o modelo do indice, ou lexical. **Nunca levanta.**

        O detector le o `texto` **cru** (o `@` de um e-mail e o `+` de um
        indicativo so existem nele); o que sai e o `enviar` — na pesquisa, o
        `q_norm` da normalizacao PT-AO do KAM-062, sem as restricoes de preco,
        que e a mesma forma do `nome_norm` do documento. Sem `enviar`, sai o
        passo 1 do §5.1 do `texto`. O `prazo` (relogio `time.monotonic`) e o
        da `ClienteDeEmbeddings.vectores`.

        Sem modelo no indice (nenhum vector, ou mais de um modelo), a pergunta
        **nao** vai ao fornecedor: seria uma transferencia sem nada com que a
        comparar. Conta como queda so quando ha mistura de modelos.
        """
        if modelo_do_indice is None:
            return _SEM_VECTOR
        try:
            recusar = bool(self.sensivel(texto))
        except Exception:  # noqa: BLE001 — um detector que falha nao deixa passar
            recusar = True
        if recusar:
            return self._caiu(QUEDA_SENSIVEL)
        normal = normalizar(texto) if enviar is None else enviar
        if not normal:
            return _SEM_VECTOR
        try:
            resposta = self.cliente.vectores(
                tenant_id,
                (normal,),
                uso="consulta",
                tecto_s=self.tecto_s,
                esperar=True,
                prazo=prazo,
            )
        except EmbeddingNegado:
            return self._caiu(QUEDA_DESTINO)
        except TempoEsgotado:
            return self._caiu(QUEDA_TEMPO)
        except Exception:  # noqa: BLE001 — criterio 3: sem erro ao cliente
            return self._caiu(QUEDA_FALHA)
        if resposta.modelo != modelo_do_indice:
            return self._caiu(QUEDA_MODELO)
        return VectorDaConsulta(resposta.vectores[0], resposta.modelo, None)

    def com_tecto(self, tecto_s: float) -> ConsultaVectorial:
        """A mesma consulta com outro tecto: o que cabe no tecto de quem chama."""
        return ConsultaVectorial(self.cliente, self.sensivel, tecto_s, self.metricas)

    def _caiu(self, motivo: str) -> VectorDaConsulta:
        self.metricas.contar_queda(motivo=motivo)
        return VectorDaConsulta(None, None, motivo)

    def mistura(self) -> None:
        """O indice tem mais de um modelo: a pergunta nao se compara com nenhum."""
        self.metricas.contar_queda(motivo=QUEDA_MODELO)


# ------------------------------------------------------------------ catalogo


def texto_de_embedding(
    nome: str,
    marca: str | None = None,
    categoria: str | None = None,
    descricao: str | None = None,
) -> str:
    """O texto que gera o embedding de um produto, ou `TextoDeEmbeddingProibido`.

    **So nome, marca, categoria e descricao**, e e por construcao: nenhum
    parametro recebe preco, stock ou contacto. O *lint* corre na mesma, porque
    o nome e escrito pela PME e pode trazer o preco («Arroz 25 kg 15 000 Kz») ou
    o telefone dela.
    """
    partes = [
        parte.strip()
        for parte in (nome, marca, categoria, descricao)
        if isinstance(parte, str) and parte.strip()
    ]
    return exigir_texto_de_embedding(". ".join(partes))


#: Os documentos visiveis do tenant do contexto ainda sem vector, pela ordem do
#: `doc_id`, depois do cursor (`NULL` = do inicio). O nome vem da **oferta
#: viva**, e nao do `nome_norm`: e o texto da PME com a pontuacao, que e onde o
#: *lint* ve o `@` de um e-mail e o `$` de um preco. A vista nao da preco a
#: esta consulta — so se le o `nome`.
SQL_POR_EMBEBER: Final = """
  SELECT d.doc_id::text AS doc_id, v.nome, d.nome_norm, d.marca_canon,
         d.categoria_canon, d.descr_norm
    FROM idx.search_doc d
    JOIN platform.v_oferta_viva v
      ON v.tenant_id = d.tenant_id AND v.product_ref = d.product_ref
   WHERE d.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     AND d.visivel
     AND d.embedding IS NULL
     AND (%s::uuid IS NULL OR d.doc_id > %s::uuid)
   ORDER BY d.doc_id
   LIMIT %s
"""

#: Os modelos de **todos** os vectores do tenant, visiveis ou nao: e a coluna
#: que nao pode ter dois (criterio 6).
SQL_OUTRO_MODELO: Final = """
  SELECT 1 AS existe
    FROM idx.search_doc
   WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     AND embedding IS NOT NULL
     AND embedding_modelo IS DISTINCT FROM %s
   LIMIT 1
"""

#: Grava os vectores de um lote. **So onde o texto ainda e o que se embebeu**: o
#: documento que mudou de nome entretanto tem o vector anulado pelo consumidor e
#: ficava com o do nome antigo. E so num tenant sem vectores de outro modelo.
#: **O limite desta guarda, dito:** em `READ COMMITTED`, dois *workers* com
#: modelos diferentes no mesmo tenant, ao mesmo tempo, nao veem a escrita um do
#: outro e gravam os dois. A pesquisa apanha a mistura (`modelos_do_indice`) e
#: cai em lexical — falha fechada —, e o processo do KAM-194 corre um *worker*
#: por tenant. Parametros: o modelo, seis por linha, e o modelo.
_SQL_GRAVAR: Final = """
  UPDATE idx.search_doc d
     SET embedding = u.vec::halfvec, embedding_modelo = %s
    FROM (VALUES {linhas}) AS u(doc_id, vec, nome_norm, marca_canon, categoria_canon,
                                descr_norm)
   WHERE d.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
     AND d.doc_id = u.doc_id
     AND d.embedding IS NULL
     AND d.nome_norm = u.nome_norm
     AND d.marca_canon IS NOT DISTINCT FROM u.marca_canon
     AND d.categoria_canon IS NOT DISTINCT FROM u.categoria_canon
     AND d.descr_norm = u.descr_norm
     AND NOT EXISTS (
           SELECT 1 FROM idx.search_doc o
            WHERE o.tenant_id = d.tenant_id
              AND o.embedding IS NOT NULL
              AND o.embedding_modelo IS DISTINCT FROM %s)
"""

_LINHA_A_GRAVAR: Final = "(%s::uuid, %s::text, %s::text, %s::text, %s::text, %s::text)"


def sql_gravar_embeddings(quantos: int) -> str:
    """A instrucao que grava `quantos` vectores (modelo, 6 por linha, modelo)."""
    if quantos < 1:
        raise ValueError("gravar zero vectores nao e uma instrucao")
    return _SQL_GRAVAR.replace("{linhas}", ", ".join([_LINHA_A_GRAVAR] * quantos))


def em_texto(vector: Sequence[float]) -> str:
    """Um vector na forma de texto que o `halfvec` le: `[x,y,...]`."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


@dataclass(frozen=True)
class VoltaDoCatalogo:
    """O que uma volta fez. `ultimo` e o cursor da seguinte; `None` = acabou.

    `motivo` diz porque nao se gravou nada (a porta, o tecto, uma falha, ou um
    modelo diferente no tenant); `recusados` sao os documentos cujo texto o
    *lint* ou o fornecedor (`ClienteDeEmbeddings.aceita`) recusou, **um a um**,
    e que ficam so lexicais. Um texto recusado nunca derruba o lote.
    """

    lidos: int
    gravados: int
    recusados: int
    ultimo: str | None
    motivo: str | None = None


def embeber_catalogo(
    bd: ClienteSql,
    tenant_id: str,
    cliente: ClienteDeEmbeddings,
    modelo: str,
    *,
    depois_de: str | None = None,
    lote: int = LOTE_DE_EMBEDDINGS,
    tecto_s: float = TECTO_DO_CATALOGO_S,
) -> VoltaDoCatalogo:
    """Uma volta do *worker* sobre o tenant do contexto. **Nao levanta** pela porta.

    Corre com o contexto do tenant posto pelo chamador, como o `reindexar` do
    KAM-062. Le um lote, pede os vectores dos textos que passam o *lint* numa
    chamada, e grava-os. A chamada ao fornecedor fica **entre** a leitura e a
    escrita: quem corre isto pode faze-las em transaccoes separadas, porque a
    escrita confere o texto e nao confia no que leu. Quem a chama em ciclo, com
    o cursor `ultimo`, e o processo do KAM-194; uma volta que nao gravou por
    `motivo` repete-se na volta seguinte, que e o *retry*.
    """
    linhas = bd.executar(
        SQL_POR_EMBEBER, (depois_de, depois_de, int(lote))
    ).linhas
    if not linhas:
        return VoltaDoCatalogo(0, 0, 0, None)
    ultimo = str(linhas[-1]["doc_id"])
    a_embeber: list[tuple[Mapping[str, object], str]] = []
    recusados = 0
    for linha in linhas:
        texto = _texto_da_linha(linha)
        # Texto a texto, antes de juntar: um so recusado pelo fornecedor (um
        # nome que o detector de PII le como morada) derrubava o lote inteiro,
        # e para sempre — o *retry* da volta seguinte recusava-o outra vez.
        if texto is None or not cliente.aceita(texto):
            recusados += 1
        else:
            a_embeber.append((linha, texto))
    if not a_embeber:
        return VoltaDoCatalogo(len(linhas), 0, recusados, ultimo)
    if bd.executar(SQL_OUTRO_MODELO, (modelo,)).linhas:
        return VoltaDoCatalogo(len(linhas), 0, recusados, ultimo, QUEDA_MODELO)
    try:
        resposta = cliente.vectores(
            tenant_id, [texto for _, texto in a_embeber], uso="catalogo", tecto_s=tecto_s
        )
    except EmbeddingNegado:
        return VoltaDoCatalogo(len(linhas), 0, recusados, ultimo, QUEDA_DESTINO)
    except TempoEsgotado:
        return VoltaDoCatalogo(len(linhas), 0, recusados, ultimo, QUEDA_TEMPO)
    except Exception:  # noqa: BLE001 — o lote repete-se na volta seguinte
        return VoltaDoCatalogo(len(linhas), 0, recusados, ultimo, QUEDA_FALHA)
    if resposta.modelo != modelo:
        return VoltaDoCatalogo(len(linhas), 0, recusados, ultimo, QUEDA_MODELO)
    parametros: list[object] = [modelo]
    for (linha, _), vector in zip(a_embeber, resposta.vectores, strict=True):
        parametros.extend(
            (
                linha["doc_id"],
                em_texto(vector),
                linha["nome_norm"],
                linha["marca_canon"],
                linha["categoria_canon"],
                linha["descr_norm"],
            )
        )
    parametros.append(modelo)
    gravados = bd.executar(sql_gravar_embeddings(len(a_embeber)), parametros).contagem
    return VoltaDoCatalogo(len(linhas), int(gravados or 0), recusados, ultimo)


def _texto_da_linha(linha: Mapping[str, object]) -> str | None:
    """O texto que sai para o fornecedor, ou `None` se o *lint* o recusa.

    **Duas formas do mesmo documento, e cada uma para uma coisa.** O *lint* le
    o nome **cru** da oferta viva, com a pontuacao — e onde estao o `@` de um
    e-mail e o `$` de um preco. O que sai e a forma **normalizada** do
    documento (`nome_norm`, `marca_canon`, `categoria_canon`, `descr_norm`, os
    passos do §5.1 do KAM-062), que e a mesma forma do `q_norm` que a pergunta
    envia: os dois lados do vector sao embebidos da mesma maneira.
    """
    nome = linha.get("nome")
    if not isinstance(nome, str):
        return None
    partes = (
        linha.get("marca_canon"),
        linha.get("categoria_canon"),
        linha.get("descr_norm"),
    )
    try:
        texto_de_embedding(nome, *partes)  # type: ignore[arg-type]
        normal = texto_de_embedding(linha.get("nome_norm") or "", *partes)  # type: ignore[arg-type]
    except TextoDeEmbeddingProibido:
        return None
    return normal or None
