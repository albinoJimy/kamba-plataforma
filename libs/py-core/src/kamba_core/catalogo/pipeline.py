"""O pipeline foto -> rascunho de produto do Catalogo AI (KAM-049; `docs/tecnica/03` §8.2).

As nove etapas, e quem faz cada uma:

| Etapa | Aqui | Estado de saida |
|---|---|---|
| 1. Captura | `FonteDeMedia.descarregar` (bytes, nunca a URL da Meta), `exif.limpar_metadados`, STO | `recebida` |
| 2. Qualidade | `Descodificador` + `imagem.analisar` | `rejeitada_qualidade` |
| 2b. Duplicado | `Repositorio.com_phash` | fica `recebida`, pergunta «e o mesmo produto?» |
| 3. *Gate* de transferencia | `PortaDeDestinos.autorizar`, finalidade `visao`, todos os fornecedores do alias | `bloqueada_gate` |
| 4. Extraccao | `ExtractorDeVisao.extrair` + `extraccao.ler_resposta_da_visao` | `em_extraccao` |
| 5. Normalizacao PT-AO | `normalizacao.normalizar` (o lexico do KAM-062) | — |
| 6. Screening | `PortaDeScreening.screen` (o do KAM-088) | `bloqueada_categoria` |
| 7. Completude | `completude.proximas_perguntas` | `a_perguntar` |
| 8. Rascunho | `PortaDoRegisto.rascunho` | `rascunho` |
| 9. Confirmacao | `confirmar` com `ConfirmacaoDoDono` | `publicada` |

## Onde corre, e porque e uma biblioteca

Corre na **ingestao**, nunca no atendimento: nada aqui e chamado por um no do
Vendedor, e o custo de visao so se paga quando o dono manda uma foto. O bloco
pede que se decida entre um grafo registado e um servico do COM com API
interna. **A decisao, registada no bloco: nenhum dos dois neste ticket.** E uma
biblioteca do `kamba-core` com tres entradas (`receber`, `responder`,
`confirmar`) e duas de operacao (`retomar`, `descartar`), porque as tres
dependencias que a fazem — a normalizacao do KAM-062, a porta de destinos do
KAM-069 e o cliente de LLM com o papel `vision` — sao Python; e porque o canal
do dono nao esta fixado (D10). A rota que a expoe e do canal: a API interna do
AGR e «minima» por desenho (`api_interna.py`) e uma rota «para depois» e o que
ela recusa por escrito.

## Texto em imagens e dado

Nenhum valor que venha da visao decide nada: nem o estado, nem o preco, nem o
`stock`, nem a confirmacao. O preco de uma etiqueta e `preco_sugerido` e vai
**dentro** da pergunta do preco; o estado so muda pelas transicoes deste
modulo; e a `publicada` exige `ConfirmacaoDoDono` com a versao do resumo que o
dono viu (criterio 8, ADR-007).

## Sem conteudo em registos

Este modulo **nao regista nada** (ADR-010): os campos de um produto e o texto
de uma resposta do dono nao saem para um *logger*. O que se mede vive na
propria linha — `custo_llm_usd`, o estado, os campos com `corrigido` — e le-se
pelo `indicadores.py`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final, Protocol, runtime_checkable

from ..destinos.porta import FINALIDADE_VISAO
from ..idx.normalizacao import Lexico, passo_1
from ..idx.numeros import por_extenso
from ..storage.port import Ctx, ObjectMeta, ObjectRef, StorageProvider
from ..storage.chave import nova_chave
from . import completude, estados
from .exif import FormatoNaoSuportado, ImagemInvalida, limpar_metadados, tem_metadados
from .extraccao import (
    CAMPOS_DA_VISAO,
    DONO_TEXTO,
    DONO_VOZ,
    Campo,
    ExtraccaoInvalida,
    confirmar as confirmar_campo,
    do_dono,
    ler_resposta_da_visao,
)
from .imagem import Descodificador, ImagemIlegivel, analisar
from .normalizacao import ler_preco, normalizar
from .repositorio import Ingestao, Repositorio, novo_id
from .screening import PortaDeScreening, ResultadoDoScreen, categoria_restrita

#: A classe da chave no STO (`t/{tenant}/{classe}/…`).
CLASSE_STO: Final = "catalogo"

#: *Proposta*: quanto tempo a foto limpa fica no STO. A foto de um produto
#: publicado passa a ser do Registo (KAM-120); esta e a copia da ingestao.
RETENCAO_DA_FOTO: Final = timedelta(days=90)

#: A validade da URL interna assinada. *Proposta*.
TTL_DA_URL_INTERNA: Final = 300

#: Os ambientes em que so entram imagens sinteticas (criterio 3).
AMBIENTE_PROD: Final = "prod"

#: Os campos que o screening le: os que dizem o que o produto e.
CAMPOS_DO_SCREENING: Final = ("nome", "marca", "categoria", "material", "variantes")

#: Os motivos que o resultado leva, para quem compoe a mensagem ao dono.
MOTIVO_FORMATO: Final = "formato"
MOTIVO_ILEGIVEL: Final = "ilegivel"
MOTIVO_SEM_DESTINO: Final = "sem_destino"
MOTIVO_SO_SINTETICAS: Final = "so_sinteticas"
MOTIVO_METADADOS: Final = "metadados"
MOTIVO_LIMITE_DE_PERGUNTAS: Final = "limite_de_perguntas"

#: A chave da sugestao de preco dentro do `extraido`. Nao e um campo do
#: produto: nunca entra no Registo, no resumo, na completude nem na
#: confirmacao — e o «vi 45 mil na etiqueta» que a pergunta do preco mostra.
SUGESTAO: Final = "preco_sugerido"


# ---------------------------------------------------------------- portas


@runtime_checkable
class FonteDeMedia(Protocol):
    """Descarrega uma media da Meta pelo `media_id`. Devolve bytes, nunca a URL.

    A URL da Meta expira e e de um terceiro: quem a resolve e esta porta, e ela
    nao sai daqui — nem para a linha, nem para o STO, nem para o resultado.
    """

    def descarregar(self, tenant_id: str, media_id: str) -> bytes: ...


@dataclass(frozen=True)
class RespostaDaVisao:
    texto: str
    custo_usd: Decimal


class ErroDaVisao(RuntimeError):
    """A visao falhou. Leva o custo que ja se pagou, para a soma do criterio 9."""

    def __init__(self, mensagem: str, custo_usd: Decimal = Decimal(0)) -> None:
        super().__init__(mensagem)
        self.custo_usd = custo_usd


@runtime_checkable
class ExtractorDeVisao(Protocol):
    """O modelo de visao (alias `kamba-vision`).

    `fornecedores` sao todos os que o alias pode alcancar, com o *fallback*:
    o *gate* autoriza-os a todos, pela razao do cliente do AGR.
    """

    fornecedores: tuple[str, ...]

    def extrair(self, tenant_id: str, imagem: bytes) -> RespostaDaVisao: ...


@runtime_checkable
class PortaDeDestinos(Protocol):
    """O `autorizar` do KAM-069: levanta se o destino nao estiver autorizado."""

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None: ...


@dataclass(frozen=True)
class ConfirmacaoDoDono:
    """A `OwnerConfirmation` do §8.2 etapa 9: quem, quando, e que texto viu."""

    actor: str
    em: datetime
    versao_texto: str


@runtime_checkable
class PortaDoRegisto(Protocol):
    """O produto no Registo e a `offer_terms` (o `upsertProductDraft` e o `publishProduct`)."""

    def rascunho(self, tenant_id: str, sku: str, campos: Mapping[str, Campo]) -> None: ...

    def publicar(self, tenant_id: str, sku: str, confirmacao: ConfirmacaoDoDono) -> None: ...


class ConfirmacaoRecusada(ValueError):
    """A confirmacao nao vale: estado, texto ou campos por confirmar."""


class IngestaoInexistente(LookupError):
    """Nao ha ingestao com esse `id` **neste** tenant."""


# ---------------------------------------------------------------- resultado


@dataclass(frozen=True)
class Resultado:
    """O que o canal precisa para responder ao dono."""

    ingestao: Ingestao
    perguntas: tuple[completude.Pergunta, ...] = ()
    motivo: str | None = None
    mesmo_produto_que: str | None = None
    resumo: str | None = None
    versao_texto: str | None = None

    @property
    def estado(self) -> str:
        return self.ingestao.estado


# ---------------------------------------------------------------- respostas do dono


def _ler_preco_tipo(texto: str) -> str | None:
    tokens = passo_1(texto)
    frase = " ".join(tokens)
    if "consulta" in tokens:
        return "sob_consulta"
    if "partir" in tokens or "apartir" in tokens or frase.startswith("desde"):
        return "a_partir_de"
    if "fixo" in tokens:
        return "fixo"
    return None


def _ler_stock_modo(texto: str) -> str | None:
    tokens = set(passo_1(texto))
    if tokens & {"garantido", "garantida"}:
        return "garantido"
    if tokens & {"indicativo", "aproximado"}:
        return "indicativo"
    if tokens & {"confirmo", "confirmar", "pedido", "cada"}:
        return "confirmar_dono"
    return None


def _ler_inteiro(texto: str, fonte: str) -> int | None:
    tokens = passo_1(texto)
    if fonte == DONO_VOZ:
        tokens = por_extenso(tokens)
    numeros = [t for t in tokens if t.isdigit()]
    if len(numeros) != 1:
        return None
    valor = int(numeros[0])
    return valor if 0 <= valor <= 1_000_000 else None


def interpretar(campo: str, texto: str, fonte: str) -> str | tuple[str, ...] | None:
    """A resposta do dono a uma pergunta, no valor do campo; `None` se nao se le."""
    if campo == "preco_tipo":
        return _ler_preco_tipo(texto)
    if campo == "stock_modo":
        return _ler_stock_modo(texto)
    if campo == "preco":
        preco = ler_preco(texto, origem=fonte)
        return str(preco.minor) if preco else None
    if campo == "stock":
        valor = _ler_inteiro(texto, fonte)
        return str(valor) if valor is not None else None
    limpo = " ".join(texto.split())[:200]
    if not limpo:
        return None
    if campo == "variantes":
        partes = [p.strip() for p in limpo.replace(" e ", ",").split(",")]
        return tuple(p for p in partes if p) or None
    return limpo


# ---------------------------------------------------------------- resumo


def _kz(minor: str) -> str:
    inteiro = int(minor) // 100
    return f"{inteiro:,}".replace(",", " ") + " Kz"


def resumo(campos: Mapping[str, Campo]) -> str:
    """O resumo da etapa 9 («Camisa Nike, tam. M e L, 12 000 Kz, 5 em stock»)."""
    partes: list[str] = []

    def valor(nome: str) -> str | None:
        c = campos.get(nome)
        if c is None:
            return None
        return " e ".join(c.valor) if isinstance(c.valor, tuple) else c.valor

    cabeca = " ".join(v for v in (valor("nome"), valor("marca")) if v)
    if cabeca:
        partes.append(cabeca)
    if valor("variantes"):
        partes.append(f"variantes {valor('variantes')}")
    tipo = valor("preco_tipo")
    preco = valor("preco")
    if tipo == "sob_consulta":
        partes.append("preco sob consulta")
    elif preco and preco.isdigit():
        partes.append(("a partir de " if tipo == "a_partir_de" else "") + _kz(preco))
    stock = valor("stock")
    if stock is not None:
        partes.append(f"{stock} em stock")
    elif valor("stock_modo") == "confirmar_dono":
        partes.append("stock a confirmar a cada pedido")
    return ", ".join(partes)


def versao_do_texto(texto: str) -> str:
    """A versao do resumo que o dono confirma: os primeiros 16 hex do sha256."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- o servico


@dataclass
class ServicoDeIngestao:
    """O pipeline. Todas as portas sao obrigatorias: nao ha omissao que deixe passar."""

    repositorio: Repositorio
    fonte: FonteDeMedia
    storage: StorageProvider
    descodificador: Descodificador
    destinos: PortaDeDestinos
    visao: ExtractorDeVisao
    lexico: Callable[[str], Lexico]
    screening: PortaDeScreening
    registo: PortaDoRegisto
    ambiente: str
    agora: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    # ------------------------------------------------------------ entradas

    def receber(self, tenant_id: str, media_id: str, *, sintetica: bool = False) -> Resultado:
        """Etapas 1 a 8 para uma foto nova. Reprocessar o mesmo `media_id` e *no-op*."""
        existente = self.repositorio.por_media(tenant_id, media_id)
        if existente is not None:
            return Resultado(existente)

        bruto = self.fonte.descarregar(tenant_id, media_id)
        ingestao_id = novo_id()
        try:
            limpo = limpar_metadados(bruto)
        except (FormatoNaoSuportado, ImagemInvalida):
            # Nao se guarda nem se envia o que nao se sabe limpar. A linha fica,
            # para a idempotencia e para a metrica, com uma chave que nunca foi
            # escrita: `media_ref` e o sitio onde estaria.
            linha = self.repositorio.inserir(
                Ingestao(
                    id=ingestao_id,
                    tenant_id=tenant_id,
                    media_ref=nova_chave(Ctx(tenant_id), CLASSE_STO, self.agora()),
                    media_id_meta=media_id,
                )
            )
            if linha.id != ingestao_id:
                return Resultado(linha)
            return self._mudar(linha, replace(linha, estado=estados.REJEITADA_QUALIDADE), motivo=MOTIVO_FORMATO)

        chave = nova_chave(Ctx(tenant_id), CLASSE_STO, self.agora())
        self.storage.put(
            Ctx(tenant_id),
            chave,
            limpo,
            ObjectMeta(
                content_type="image/png" if limpo.startswith(b"\x89PNG") else "image/jpeg",
                classe=CLASSE_STO,
                retain_until=self.agora() + RETENCAO_DA_FOTO,
            ),
        )
        linha = self.repositorio.inserir(
            Ingestao(id=ingestao_id, tenant_id=tenant_id, media_ref=chave, media_id_meta=media_id)
        )
        if linha.id != ingestao_id:
            # Outro processo inseriu o mesmo `media_id` entretanto: e dele.
            return Resultado(linha)
        return self._depois_da_captura(linha, limpo, sintetica=sintetica, verificar_duplicado=True)

    def mesmo_produto(self, tenant_id: str, ingestao_id: str, *, e_o_mesmo: bool, sintetica: bool = False) -> Resultado:
        """A resposta a «e o mesmo produto?». Sim descarta; nao segue o pipeline."""
        linha = self._ler(tenant_id, ingestao_id)
        if linha.estado != estados.RECEBIDA:
            return Resultado(linha)
        if e_o_mesmo:
            return self._mudar(linha, replace(linha, estado=estados.DESCARTADA))
        return self._depois_da_captura(linha, self._imagem(linha), sintetica=sintetica, verificar_duplicado=False)

    def retomar(self, tenant_id: str, ingestao_id: str, *, sintetica: bool = False) -> Resultado:
        """Depois de uma decisao humana: o *gate* autorizado, ou o T&S a levantar a categoria."""
        linha = self._ler(tenant_id, ingestao_id)
        if linha.estado == estados.BLOQUEADA_GATE:
            return self._gate_e_extraccao(linha, sintetica=sintetica)
        if linha.estado == estados.BLOQUEADA_CATEGORIA:
            return self._screening_e_completude(linha, linha.campos, preco_sugerido=None, custo=Decimal(0))
        return Resultado(linha)

    def descartar(self, tenant_id: str, ingestao_id: str) -> Resultado:
        linha = self._ler(tenant_id, ingestao_id)
        if linha.estado in estados.FINAIS:
            return Resultado(linha)
        return self._mudar(linha, replace(linha, estado=estados.DESCARTADA))

    def responder(
        self,
        tenant_id: str,
        ingestao_id: str,
        respostas: Mapping[str, str],
        *,
        fonte: str = DONO_TEXTO,
    ) -> Resultado:
        """As respostas do dono (ou uma correccao ao rascunho). Etapas 5 a 8 outra vez."""
        linha = self._ler(tenant_id, ingestao_id)
        if linha.estado not in (estados.A_PERGUNTAR, estados.RASCUNHO):
            return Resultado(linha)
        perfil = completude.perfil_da_categoria(self._texto(linha.campos, "categoria"))
        aceites = set(completude.PERFIS[perfil]) | set(CAMPOS_DA_VISAO)
        campos = dict(linha.campos)
        for nome, texto in respostas.items():
            if nome not in aceites or not isinstance(texto, str):
                continue
            valor = interpretar(nome, texto, fonte)
            if valor is None:
                continue
            campos[nome] = do_dono(valor, fonte, anterior=campos.get(nome))
        # A resposta pode ter mudado a categoria, e com ela o perfil.
        preco_sugerido = self._preco_sugerido(linha)
        mudou = self._textos(campos) != self._textos(linha.campos)
        if mudou:
            return self._screening_e_completude(linha, campos, preco_sugerido=preco_sugerido, custo=Decimal(0))
        return self._completude(linha, campos, preco_sugerido=preco_sugerido)

    def confirmar(self, tenant_id: str, ingestao_id: str, confirmacao: ConfirmacaoDoDono) -> Resultado:
        """Etapa 9. Sem confirmacao valida nao ha `publicada`."""
        linha = self._ler(tenant_id, ingestao_id)
        if linha.estado != estados.RASCUNHO:
            raise ConfirmacaoRecusada(f"so um rascunho se confirma (estado `{linha.estado}`)")
        if not confirmacao.actor or confirmacao.em.tzinfo is None:
            raise ConfirmacaoRecusada("a confirmacao leva quem confirmou e um instante com fuso")
        perfil = completude.perfil_da_categoria(self._texto(linha.campos, "categoria"))
        if completude.campos_em_falta(linha.campos, perfil):
            raise ConfirmacaoRecusada("ha campos em falta: o rascunho nao esta completo")
        texto = resumo(linha.campos)
        if confirmacao.versao_texto != versao_do_texto(texto):
            # O dono confirmou um texto que ja nao e este: um campo mudou depois.
            raise ConfirmacaoRecusada("a confirmacao e de outra versao do resumo")
        if linha.categoria_restrita is not None or not linha.sku:
            raise ConfirmacaoRecusada("categoria restrita ou sem sku")
        self.registo.publicar(tenant_id, linha.sku, confirmacao)
        # A sugestao de preco nao e um campo do produto: nao se confirma.
        confirmados = {
            nome: c if nome == SUGESTAO else confirmar_campo(c) for nome, c in linha.campos.items()
        }
        return self._mudar(
            linha,
            replace(
                linha,
                estado=estados.PUBLICADA,
                campos=confirmados,
                confirmado_at=confirmacao.em,
                confirmado_por=confirmacao.actor,
            ),
        )

    def url_interna(self, tenant_id: str, ingestao_id: str) -> str:
        """A URL interna assinada da foto limpa. Outro tenant nao a obtem (ISO-47..50)."""
        linha = self._ler(tenant_id, ingestao_id)
        return self.storage.sign_url(
            Ctx(tenant_id), ObjectRef(key=linha.media_ref, tamanho=0), ttl_seconds=TTL_DA_URL_INTERNA
        )

    # ------------------------------------------------------------ etapas

    def _depois_da_captura(self, linha: Ingestao, limpo: bytes, *, sintetica: bool, verificar_duplicado: bool) -> Resultado:
        # Etapa 2: qualidade, antes de qualquer custo de LLM.
        try:
            analise = analisar(self.descodificador.cinzento(limpo))
        except ImagemIlegivel:
            return self._mudar(linha, replace(linha, estado=estados.REJEITADA_QUALIDADE), motivo=MOTIVO_ILEGIVEL)
        motivo = analise.motivo_de_recusa
        if motivo is not None:
            return self._mudar(linha, replace(linha, estado=estados.REJEITADA_QUALIDADE, phash=analise.phash), motivo=motivo)
        if linha.phash != analise.phash:
            linha = self._mudar(linha, replace(linha, phash=analise.phash)).ingestao
        if verificar_duplicado:
            anterior = self.repositorio.com_phash(linha.tenant_id, analise.phash, linha.id)
            if anterior is not None:
                return Resultado(linha, mesmo_produto_que=anterior.id)
        return self._gate_e_extraccao(linha, sintetica=sintetica)

    def _gate_e_extraccao(self, linha: Ingestao, *, sintetica: bool) -> Resultado:
        # Etapa 3: o *gate*. Fora de `prod`, so imagens sinteticas.
        if self.ambiente != AMBIENTE_PROD and not sintetica:
            return self._bloquear_gate(linha, MOTIVO_SO_SINTETICAS)
        fornecedores = tuple(self.visao.fornecedores)
        if not fornecedores:
            return self._bloquear_gate(linha, MOTIVO_SEM_DESTINO)
        try:
            for fornecedor in fornecedores:
                self.destinos.autorizar(linha.tenant_id, fornecedor, FINALIDADE_VISAO)
        except Exception:  # noqa: BLE001 — falha fechada: qualquer erro e «nao autorizado»
            return self._bloquear_gate(linha, MOTIVO_SEM_DESTINO)

        # A imagem que sai e a que esta no STO, relida, e verifica-se outra vez.
        imagem = self._imagem(linha)
        if tem_metadados(imagem):
            return self._bloquear_gate(linha, MOTIVO_METADADOS)

        # Etapa 4: extraccao.
        linha = self._mudar(linha, replace(linha, estado=estados.EM_EXTRACCAO)).ingestao
        custo = Decimal(0)
        try:
            resposta = self.visao.extrair(linha.tenant_id, imagem)
            custo = resposta.custo_usd
            extraccao = ler_resposta_da_visao(resposta.texto)
        except ErroDaVisao as erro:
            custo = erro.custo_usd
            extraccao = None
        except ExtraccaoInvalida:
            extraccao = None
        if extraccao is None:
            # Sem extraccao, pergunta-se tudo ao dono: a foto continua a servir.
            return self._screening_e_completude(linha, {}, preco_sugerido=None, custo=custo)

        # Etapa 5: normalizacao PT-AO.
        normalizada = normalizar(extraccao, self.lexico(linha.tenant_id))
        sugestao = ler_preco(normalizada.preco_etiqueta) if normalizada.preco_etiqueta else None
        return self._screening_e_completude(
            linha,
            dict(normalizada.campos),
            preco_sugerido=str(sugestao.minor) if sugestao else None,
            custo=custo,
        )

    def _screening_e_completude(
        self,
        linha: Ingestao,
        campos: Mapping[str, Campo],
        *,
        preco_sugerido: str | None,
        custo: Decimal,
    ) -> Resultado:
        # Etapa 6: screening. Qualquer falha e restritiva.
        try:
            resultado: ResultadoDoScreen | None = self.screening.screen(
                linha.tenant_id,
                linha.id,
                self._texto(campos, "categoria") or "",
                self._textos(campos),
            )
        except Exception:  # noqa: BLE001 — falha fechada
            resultado = None
        restrita = categoria_restrita(resultado)
        campos_com_sugestao = dict(campos)
        if preco_sugerido is not None:
            campos_com_sugestao[SUGESTAO] = Campo(valor=preco_sugerido, confianca=Decimal(0), fonte="ia_visao")
        nova = replace(linha, campos=campos_com_sugestao, custo_llm_usd=linha.custo_llm_usd + custo)
        if restrita is not None:
            return self._mudar(linha, replace(nova, estado=estados.BLOQUEADA_CATEGORIA, categoria_restrita=restrita))
        nova = replace(nova, categoria_restrita=None)
        return self._completude(linha, nova.campos, preco_sugerido=self._preco_sugerido(nova), base=nova)

    def _completude(
        self,
        linha: Ingestao,
        campos: Mapping[str, Campo],
        *,
        preco_sugerido: str | None,
        base: Ingestao | None = None,
    ) -> Resultado:
        # Etapa 7: completude e perguntas.
        nova = replace(base or linha, campos=dict(campos))
        produto = {n: c for n, c in campos.items() if n != SUGESTAO}
        perfil = completude.perfil_da_categoria(self._texto(produto, "categoria"))
        falta = completude.campos_em_falta(produto, perfil)
        perguntas = completude.proximas_perguntas(
            produto, perfil, nova.perguntas_feitas, preco_sugerido=_preco_legivel(preco_sugerido)
        )
        if falta:
            motivo = None if perguntas else MOTIVO_LIMITE_DE_PERGUNTAS
            alvo = replace(
                nova,
                estado=estados.A_PERGUNTAR,
                campos_em_falta=falta,
                perguntas_feitas=nova.perguntas_feitas + len(perguntas),
            )
            return self._mudar(linha, alvo, perguntas=perguntas, motivo=motivo)

        # Etapa 8: rascunho, inactivo no Registo.
        sku = nova.sku or f"cat-{nova.id.replace('-', '')[:16]}"
        self.registo.rascunho(nova.tenant_id, sku, produto)
        texto = resumo(produto)
        alvo = replace(nova, estado=estados.RASCUNHO, campos_em_falta=(), sku=sku)
        return self._mudar(linha, alvo, resumo=texto, versao_texto=versao_do_texto(texto))

    # ------------------------------------------------------------ apoio

    def _mudar(self, lido: Ingestao, nova: Ingestao, **resultado: object) -> Resultado:
        gravada = self.repositorio.gravar(lido, nova)
        return Resultado(gravada, **resultado)  # type: ignore[arg-type]

    def _bloquear_gate(self, linha: Ingestao, motivo: str) -> Resultado:
        if linha.estado == estados.BLOQUEADA_GATE:
            return Resultado(linha, motivo=motivo)
        return self._mudar(linha, replace(linha, estado=estados.BLOQUEADA_GATE), motivo=motivo)

    def _ler(self, tenant_id: str, ingestao_id: str) -> Ingestao:
        linha = self.repositorio.ler(tenant_id, ingestao_id)
        if linha is None:
            raise IngestaoInexistente("nao ha essa ingestao neste tenant")
        return linha

    def _imagem(self, linha: Ingestao) -> bytes:
        return b"".join(self.storage.get(Ctx(linha.tenant_id), ObjectRef(key=linha.media_ref, tamanho=0)))

    @staticmethod
    def _texto(campos: Mapping[str, Campo], nome: str) -> str | None:
        c = campos.get(nome)
        return c.valor if c is not None and isinstance(c.valor, str) else None

    @staticmethod
    def _textos(campos: Mapping[str, Campo]) -> tuple[str, ...]:
        textos: list[str] = []
        for nome in CAMPOS_DO_SCREENING:
            c = campos.get(nome)
            if c is None:
                continue
            textos.extend(c.valor if isinstance(c.valor, tuple) else (c.valor,))
        return tuple(textos)

    @staticmethod
    def _preco_sugerido(linha: Ingestao) -> str | None:
        c = linha.campos.get(SUGESTAO)
        return c.valor if c is not None and isinstance(c.valor, str) else None


def _preco_legivel(minor: str | None) -> str | None:
    return _kz(minor) if minor and minor.isdigit() else None
