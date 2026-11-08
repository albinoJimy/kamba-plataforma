"""Os tipos, os dominios e as portas do fluxo de direitos do titular (KAM-070).

Este ficheiro nao vai a base de dados, nao publica eventos e nao le relogio.
Tem o vocabulario e as **fronteiras**: o que entra, o que sai, e quem o modulo
precisa que lhe emprestem.

## Porque e que tudo entra por protocolo e nada por `import`

Porque as quatro operacoes atravessam seis lojas de dados que vivem em
processos diferentes — o cofre de identidade e **TypeScript**, o AGR e Python, o
STO e o Chatwoot sao servicos —, e um modulo que importasse cada um deles era um
modulo que so corre onde os seis estao instalados. O que ele importa e a forma
do que precisa: publicar um evento, escrever no `audit_log`, assinar um URL,
saber que horas sao.

E ha um ganho que nao e de arquitectura e e o que mais conta aqui: um protocolo
e substituivel por um duplo que **le o texto da instrucao**, e e assim que se
prova que a ligacao esta no sitio certo e nao so que a funcao esta correcta.

## O que este modulo nunca ve

Nome, telefone, BSUID. A fronteira do ADR-010 e que «o que sai do cofre para o
resto da plataforma e o `contact_id` — e mais nada», e este modulo esta do lado
de fora dela. Por isso a identificacao do titular chega-lhe **ja resolvida**:
comparar dois `contact_id` e comparar os dois BSUID que os produziram, porque o
cofre e injectivo por tenant (indice `contact_endpoints_bsuid_uq`). Fazer a
comparacao aqui exigia o segredo do HMAC de pesquisa num processo que nao tem
razao nenhuma para o ter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from ..storage.port import TTL_MAXIMO_S

#: Os quatro tipos de pedido, e sao os do **Objectivo** do bloco.
#:
#: O titulo do ticket diz «acesso, correccao, eliminacao e exportacao»; o
#: Objectivo diz «exportacao, rectificacao, eliminacao, oposicao». Quatro em
#: cada, cinco nomes distintos entre os dois. Seguem-se os do Objectivo, que sao
#: os que os criterios implementam, e o **acesso** do Art. 26.o e servido pelo
#: `exportacao`: o que o titular acede e o JSON portatil do criterio 2. A
#: divergencia entre as duas frases do bloco fica devolvida a quem o escreveu.
TIPO_EXPORTACAO = "exportacao"
TIPO_RECTIFICACAO = "rectificacao"
TIPO_ELIMINACAO = "eliminacao"
TIPO_OPOSICAO = "oposicao"
TIPOS = (TIPO_EXPORTACAO, TIPO_RECTIFICACAO, TIPO_ELIMINACAO, TIPO_OPOSICAO)

ESTADO_RECEBIDO = "recebido"
ESTADO_EM_CURSO = "em_curso"
ESTADO_CONCLUIDO = "concluido"
ESTADOS = (ESTADO_RECEBIDO, ESTADO_EM_CURSO, ESTADO_CONCLUIDO)

#: Os seis escopos do criterio 3, e o conjunto e **fechado** de proposito.
#:
#: Um escopo que ninguem acrescente a este conjunto nunca impede um pedido de
#: fechar: o pedido fecha **sem ele**. E e essa a falha que o criterio 3 existe
#: para tornar impossivel — «o pedido so passa a `concluido` quando todos
#: aplicaram» so quer dizer algo se «todos» for uma lista escrita.
ESCOPO_COFRE = "cofre"
ESCOPO_AGR = "agr"
ESCOPO_STO = "sto"
ESCOPO_DAT = "dat"
ESCOPO_IDX = "idx"
ESCOPO_CHATWOOT = "chatwoot"
ESCOPOS = (
    ESCOPO_COFRE,
    ESCOPO_AGR,
    ESCOPO_STO,
    ESCOPO_DAT,
    ESCOPO_IDX,
    ESCOPO_CHATWOOT,
)

#: O papel da KAMBA num pedido. **A D9 esta aberta**, e por isso isto e
#: parametro e nao constante: o bloco escreve «omissao `subcontratada`, a
#: confirmar por parecer», e a omissao vive aqui — num sitio que se le — e nao
#: num `DEFAULT` da coluna, que fazia uma decisao aberta parecer decidida a quem
#: le o esquema.
PAPEL_SUBCONTRATADA = "subcontratada"
PAPEL_RESPONSAVEL = "responsavel"
PAPEIS_DA_KAMBA = (PAPEL_SUBCONTRATADA, PAPEL_RESPONSAVEL)
PAPEL_POR_OMISSAO = PAPEL_SUBCONTRATADA

#: Nome da variavel de ambiente que fixa o papel, quando a D9 fechar.
VARIAVEL_DO_PAPEL = "KAMBA_DSAR_PAPEL"

#: O prazo **interno** em dias (requisito 13 de `E3_Regulatorio_Dados.md`).
#:
#: Os 60 dias uteis da Lei 22/11 sao **INDICIO** — o bloco di-lo por extenso — e
#: nao estao aqui: um prazo que nao esta confirmado nao se escreve como numero
#: que o codigo respeita. O que se respeita e o interno, que e mais curto, e por
#: isso cumprir o interno cumpre o legal **se** o legal for 60; se for menos, o
#: parametro muda num sitio.
PRAZO_INTERNO_DIAS = 30

#: Quantos dias antes do prazo o varrimento alerta (criterio 8: «aos 20 dias»).
#:
#: O criterio conta **desde a recepcao** e nao desde o prazo, e por isso o
#: numero aqui e o do criterio e a aritmetica fica do lado de quem varre: com 30
#: dias de prazo, alertar aos 20 e alertar a 10 do fim; com um prazo diferente,
#: «aos 20 dias» continua a ser aos 20 dias.
ALERTA_AOS_DIAS = 20

#: O tecto do TTL do URL assinado da exportacao (criterio 2: «TTL <= 5 min»).
#:
#: **Nao se declara aqui: importa-se do `kamba_core.storage`**, onde ja existia
#: com o mesmo valor, e esta linha e a correccao de um defeito que este modulo
#: teve escrito. A primeira versao declarava um `TTL_MAXIMO_S = 300` proprio e
#: um `exigir_ttl` que o verificava — e isso e **duas leitoras do mesmo
#: predicado**, que e exactamente o defeito mais serio que a revisao adversarial
#: do KAM-069 encontrou: nenhum portao deste repositorio compara duas
#: constantes com o mesmo significado em modulos diferentes, e no dia em que uma
#: subisse a outra continuava a dizer que o criterio estava cumprido.
#:
#: Quem valida e o `ArmazenamentoPorTenant.sign_url`, que exige
#: `1 <= ttl_seconds <= TTL_MAXIMO_S` e levanta `TtlInvalidoError`. Este modulo
#: nao repete a verificacao: **chama quem a tem**. O que ele acrescenta e o TTL
#: por omissao desta exportacao, que e o tecto — para um JSON que se descarrega
#: uma vez, o prazo mais curto que serve e o unico que nao obriga a repetir o
#: pedido.
TTL_DA_EXPORTACAO_S = TTL_MAXIMO_S


#: O separador da canonicalizacao do `payload_hash` do `audit_log`, `chr(31)`.
#:
#: E o mesmo do `CONCATENACAO_DO_ROW_HASH` da `0006` e do escritor do COM. Nao
#: e gosto: um separador diferente em cada escritor e uma canonicalizacao por
#: escritor, e duas canonicalizacoes produzem *hashes* diferentes para o mesmo
#: facto. Escolhe-se um carater de controlo porque nenhum identificador o
#: contem — com uma virgula, `("a,b", "c")` e `("a", "b,c")` tem o mesmo texto.
#:
#: **E so para o `audit_log`.** O `evidence_hash` do `consent_event` tem
#: separador proprio e diferente — ver o `SEPARADOR_DA_PROVA`.
SEPARADOR = chr(31)

#: O separador da prova de consentimento, `chr(0)`.
#:
#: **Nao e o `SEPARADOR` acima, e distingui-los e emenda de um achado da revisao
#: adversarial.** A primeira versao deste modulo compunha o `evidence_hash` com
#: `chr(31)` e justificava-o com a nota da `0006` — que e a coluna **errada**: o
#: `row_hash` do `audit_log` e uma coisa, o `evidence_hash` do `consent_event` e
#: outra, e esta ultima **ja tem um escritor canonico** em
#: `packages/core-ts/src/consentimento/prova.ts`, que usa `chr(0)` e sai do
#: modulo de proposito — o `index.ts` dele escreve a razao: «o `evidence_hash`
#: tem de ser reprodutivel por quem audita».
#:
#: A ironia que a revisao apanhou vale escrever: a nota do `SEPARADOR` avisa que
#: «duas canonicalizacoes produzem *hashes* diferentes para o mesmo facto» — e a
#: primeira versao cometia exactamente isso, na coluna onde a unicidade
#: `(tenant_id, contact_id, purpose, evidence_hash)` da `0015` **so e suficiente
#: por causa** da composicao canonica.
SEPARADOR_DA_PROVA = chr(0)

#: As quatro partes da prova de uma oposicao por pedido do titular.
#:
#: O `prova.ts` compoe `(textoMostrado, contactId, wamid, hora)`. Uma oposicao
#: por DSAR **nao tem `wamid`**: nao vem de uma mensagem da Meta, vem de um
#: pedido. A divergencia e inevitavel e declara-se em vez de se esconder — o que
#: nao se divergiu foi o resto: o separador e o mesmo, o `contact_id` entra, uma
#: marca de origem entra no lugar do texto mostrado, e a hora e a do pedido.
#:
#: **E continua reproduzivel por quem audita**, que e a propriedade que a `0015`
#: exige («uma prova que nao se sabe reproduzir nao e prova»): os quatro campos
#: leem-se de **duas linhas que existem** — a de `consent_event` da o
#: `contact_id` e o `ocorrido_em`, a de `dsar_requests` da o `dsar_id`, e a
#: marca e esta constante.
#:
#: E e **determinista**, que e o que torna a oposicao idempotente pela chave que
#: a `0015` ja tinha: opor-se duas vezes pelo mesmo pedido da o mesmo resumo.
FORMA_DA_PROVA_DA_OPOSICAO = ("marca", "contact_id", "dsar_id", "recebido_at")

#: As duas accoes que a revisao `0038` acrescenta ao dominio fechado de
#: `audit_log.action`. Cada uma e exigida por um criterio **pelo nome**: a
#: recusa pelo 1 («fica registado»), a rectificacao pelo 7 («escreve no
#: `audit_log`»).
ACCAO_RECUSADO = "privacy.dsar_recusado"
ACCAO_RECTIFICADO = "privacy.dsar_rectificado"
ACCOES_DE_DSAR = (ACCAO_RECUSADO, ACCAO_RECTIFICADO)

#: A finalidade que a oposicao retira (criterio 7: «lista de supressao de
#: marketing ("PARAR")»).
#:
#: **E uma e nao duas.** A lista de supressao do KAM-022 e, por definicao,
#: `purpose = 'marketing'` com `accepted = false` — e o que o `parar.ts` grava
#: quando alguem escreve «PARAR» —, pelo que escrever isso e entrar nessa lista
#: e nao criar uma segunda.
#:
#: **O que fica por decidir, e fica dito:** a `sugestoes_patrocinadas` e uma
#: decima finalidade do §3 que e marketing com outro nome, e uma oposicao que a
#: deixasse de pe era um opt-out que nao para as mensagens que existe para
#: parar. Retira-la aqui era **alargar o criterio**, que nomeia uma; fica
#: devolvido a quem escreveu o bloco, com o parecer.
FINALIDADE_DA_OPOSICAO = "marketing"

#: O transporte do consentimento. O dominio da `0015` tem **um** valor, e a nota
#: dela diz que o segundo entra por migracao e nao por insercao.
CANAL_DO_CONSENTIMENTO = "whatsapp"

#: A versao do `text_version` que uma oposicao por pedido do titular registra.
#:
#: **Nao e a versao de um texto de consentimento**, e isso tem de se dizer: a
#: `consent_texts` guarda o texto que foi mostrado a quem aceitou, e aqui nao
#: foi mostrado texto nenhum — foi exercido um direito. A coluna e `NOT NULL`
#: com `CHECK (btrim(text_version) <> '')`, pelo que nao se pode deixar vazia, e
#: inventar uma versao de texto que ninguem leu era pior do que nomear a origem.
TEXTO_DA_OPOSICAO = "dsar:oposicao"

#: Os tres eventos que este modulo publica, na versao que os contratos declaram.
#:
#: **A versao e `2` nos tres** porque e a que os esquemas publicados tem como
#: `const` mais alta, e o `evt_subscricoes.versao_max` de um consumidor e que
#: decide o que ele aceita. Publicar `1` quando ha `2` era publicar um contrato
#: que o repositorio tem por antigo.
EVENTO_ERASURE_REQUESTED = "privacy.erasure_requested"
EVENTO_ERASURE_APPLIED = "privacy.erasure_applied"
EVENTO_CONSENT_WITHDRAWN = "consent.withdrawn"
VERSAO_DOS_EVENTOS = 2

#: A classe de PII dos eventos de privacidade.
#:
#: **`P0` e nao `P1`**, e o exemplo publicado do `privacy.erasure_requested`
#: escreve `P0`. O `payload` leva so o `contact_id`, que e aleatorio — a
#: classificacao segue o que vai no envelope e nao o assunto de que ele trata.
CLASSE_PII = "P0"

#: As finalidades do envelope. Uma: o apagamento a pedido do titular e um acto
#: da relacao transaccional, e nao marketing nem analytics.
FINALIDADES_DO_EVENTO = ("transacao",)


class DireitoNegado(Exception):
    """Raiz das recusas deste modulo. **Nunca leva dado pessoal na mensagem.**"""


class TipoDesconhecido(DireitoNegado):
    def __init__(self, tipo: str) -> None:
        super().__init__(f"tipo de pedido desconhecido: {tipo!r}")
        self.tipo = tipo


class EscopoDesconhecido(DireitoNegado):
    def __init__(self, escopo: str) -> None:
        super().__init__(f"escopo de apagamento desconhecido: {escopo!r}")
        self.escopo = escopo


class PapelDesconhecido(DireitoNegado):
    def __init__(self, papel: str) -> None:
        super().__init__(f"papel da KAMBA desconhecido: {papel!r}")
        self.papel = papel


class PedidoDeOutroTitular(DireitoNegado):
    """Um pedido sobre os dados de outro contacto (criterio 1).

    **Nao nomeia nenhum dos dois contactos.** A mensagem de uma recusa chega a
    um *log*, e dizer «o contacto A pediu os dados do contacto B» punha no *log*
    uma ligacao entre dois titulares que nenhum deles autorizou — e confirmava a
    quem tentou que B existe.
    """

    def __init__(self) -> None:
        super().__init__(
            "o pedido nao e do titular dos dados: devolve 0 dados e fica no audit_log"
        )


class PedidoEmCurso(DireitoNegado):
    """Ja ha um pedido aberto do mesmo tipo para o mesmo titular (criterio 8)."""

    def __init__(self, dsar_id: str, tipo: str) -> None:
        super().__init__(f"pedido {tipo} ja aberto: {dsar_id}")
        self.dsar_id = dsar_id
        self.tipo = tipo


class FechoSemLedger(DireitoNegado):
    """Tentou-se fechar um pedido de eliminacao pelo caminho que nao verifica.

    **E a correccao do achado mais serio da revisao adversarial deste ramo.** O
    `PortaDeDireitos.concluir` escrevia `estado = 'concluido'` em qualquer
    pedido, e a prosa dele dizia que quem verificava os seis escopos era «o
    `eliminacao.concluir_apagamento`, que e o unico caminho que fecha um pedido
    de eliminacao» — uma funcao que **nao existia**. O critero 3 ficava
    satisfeito por convencao: o titular era informado de que o apagamento estava
    feito, e os seis escopos nunca tinham aplicado.

    **Nenhum ensaio o podia apanhar**, e e por isso que isto e uma classe de
    defeito e nao um lapso: os cinco ensaios sobre `apagamento_completo` e
    `escopos_em_falta` ficavam verdes qualquer que fosse o comportamento do
    `concluir`, porque **nao havia ligacao nenhuma para mutar**.

    Hoje a ligacao existe e e esta excepcao: o `concluir` **recusa** um pedido
    de eliminacao, e o unico caminho que o fecha e o `concluir_apagamento`, que
    le o *ledger* antes.
    """

    def __init__(self, dsar_id: str) -> None:
        super().__init__(
            f"o pedido de eliminacao {dsar_id} nao se fecha pelo `concluir`: "
            "use o `eliminacao.concluir_apagamento`, que exige os seis escopos "
            "no erasure_ledger (criterio 3)"
        )
        self.dsar_id = dsar_id


class ApagamentoIncompleto(DireitoNegado):
    """Faltam escopos por aplicar, e o pedido nao pode fechar (criterio 3)."""

    def __init__(self, faltam: Sequence[str]) -> None:
        super().__init__(f"escopos sem linha no ledger: {', '.join(faltam)}")
        self.faltam = tuple(faltam)


@dataclass(frozen=True)
class Pedido:
    """Uma linha de `platform.dsar_requests`.

    Imutavel: o que muda num pedido e o `estado` e o `concluido_at`, e muda na
    base. Um objecto que se deixasse emendar na memoria era uma segunda versao
    do pedido, e a pergunta «este pedido esta concluido?» passava a ter duas
    respostas possiveis conforme quem a fizesse.
    """

    dsar_id: str
    tenant_id: str
    contact_id: str
    tipo: str
    estado: str
    papel_kamba: str
    recebido_at: datetime
    prazo_dias: int
    prazo_interno_at: datetime
    concluido_at: datetime | None = None

    @property
    def aberto(self) -> bool:
        return self.estado != ESTADO_CONCLUIDO

    def em_atraso(self, agora: datetime) -> bool:
        """Passou o prazo interno sem concluir.

        Um pedido **concluido** nunca esta em atraso, mesmo que tenha concluido
        depois do prazo: o que esta em atraso e o incumprimento vivo, e e isso
        que o criterio 8 manda alertar. O historico de quem concluiu tarde le-se
        pelo par (`prazo_interno_at`, `concluido_at`), que fica na linha.
        """
        return self.aberto and agora > self.prazo_interno_at

    def alerta_devido(self, agora: datetime) -> bool:
        """Chegou ao dia do alerta do criterio 8 («aos 20 dias»).

        Conta desde `recebido_at` e nao desde o prazo, que e o que o criterio
        escreve. **Devolve `true` tambem depois do prazo**, e nao e descuido: um
        pedido que ja passou os 30 dias passou os 20, e um alerta que se calasse
        ao passar o prazo calava-se exactamente quando mais faz falta.
        """
        return self.aberto and agora >= self.recebido_at + timedelta(
            days=ALERTA_AOS_DIAS
        )


@dataclass(frozen=True)
class Aplicacao:
    """Uma linha de `platform.erasure_ledger`: um escopo que aplicou."""

    erasure_id: str
    tenant_id: str
    dsar_id: str
    contact_id: str
    escopo: str
    aplicado_at: datetime


@dataclass(frozen=True)
class SujeitoApagado:
    """O par que o restauro precisa: quem foi apagado, e quando.

    E a forma que o `specs/EPIC-08_Topologia_Operacao.md` escreve como
    `erasure_ledger(subject_ref, erased_at)` — **e os dois nomes divergem dos
    desta base**, de proposito e com razao medida:

    * `subject_ref` nao e canonico. O canonico e o `sujeito_ref` do dicionario
      §3 («Pseudonimo para analytics»), que e `HMAC(chave_mensal, contact_id)` —
      e **nao serve de chave de um ledger**: a chave roda ao mes, pelo que o
      mesmo contacto tem refs diferentes em meses diferentes e um ledger que
      atravessa meses nao se reaplica por ele. A chave e o `contact_id`, que e o
      que a DoD do bloco autoriza por escrito («so `contact_id`»);
    * `erased_at` aqui e o **primeiro** instante em que algum escopo apagou, e
      nao o ultimo nem o da conclusao. E a escolha conservadora e e a unica que
      serve o predicado do restauro: uma copia tirada depois desse instante pode
      ja nao ter o sujeito, uma tirada antes tem-no de certeza. Tomar o ultimo
      deixava de fora as copias tiradas no meio de um apagamento.

    A divergencia de nomes fica registada no bloco do KAM-070 com credor; o
    `EPIC-08` nao se toca neste ramo: a reconciliacao dos dois nomes e de quem
    governa aquele contrato, nao de quem implementa este.
    """

    contact_id: str
    erased_at: datetime


class Relogio(Protocol):
    """Quem diz as horas. Injectado, para que um prazo de 30 dias se ensaie.

    **Le-se uma vez por decisao**, e nao por dentro de cada passo: e a licao do
    KAM-069, onde uma *cache* com relogio injectavel continuava a chamar
    `agora()` por dentro e o ensaio do TTL nao media nada.
    """

    def agora(self) -> datetime: ...


#: **Nao ha protocolo `Publicador` neste modulo, e e emenda.** A primeira versao
#: tinha um, com a forma do envelope dos contratos publicados, e **nada o
#: implementava nem o recebia**: quem publica e o `platform.evt_emitir` da
#: revisao `0004`, chamado por `SQL_EMITIR` no `consultas.py`. Um protocolo que
#: ninguem usa e uma **segunda descricao** de como um evento se publica, e no dia
#: em que a funcao SQL mudasse de assinatura a descricao ficava a mentir sem
#: nenhum ensaio mudar de cor. E a mesma razao pela qual o `ACCOES_NOVAS` saiu da
#: revisao e pela qual o tecto do TTL se importa em vez de se declarar.
#:
#: **Nao ha publicador em Python**, e isso esta escrito no
#: `kamba_core.eventos.__init__`: o publicador e o reconciliador sao TypeScript
#: (KAM-005, KAM-006). O que ha e a funcao SQL, que corre na transaccao do
#: produtor — o *outbox* transaccional do ADR-009.


class Auditoria(Protocol):
    """Quem escreve no `platform.audit_log`, **sem conteudo**.

    **O metodo chama-se `escrever` e nao `registar`, e e um portao que o
    decidiu.** O `tools/log_policy` recusa qualquer `.registar(...)` em codigo
    de servico — «e a porta sem tipos do logger; usam-se `info`, `error`,
    `excepcao`» — e a primeira versao deste protocolo chamava-lhe `registar`,
    o que deu **dois** achados no *gate* 2. O nome e de um portao e nao de
    gosto: um `.registar(` em qualquer sitio le-se como a porta sem tipos do
    logger, e um registo de auditoria que se parece com um *log* convida a
    escrever conteudo nele.

    A DoD do bloco: «nenhum dado pessoal em eventos, logs ou `dsar_requests`; so
    `contact_id`». Por isso a assinatura nao tem campo de texto livre: tem a
    accao, o alvo e um mapa de detalhe que o chamador preenche com
    identificadores e com mais nada.
    """

    def escrever(
        self,
        *,
        tenant_id: str,
        accao: str,
        contact_id: str | None,
        detalhe: Mapping[str, object],
    ) -> None: ...


class Assinador(Protocol):
    """Quem produz um URL com expiracao para um objecto do STO.

    **A assinatura e a do `ArmazenamentoPorTenant.sign_url`**, e nao uma forma
    inventada. E emenda de um achado da revisao adversarial: a primeira versao
    declarava `assinar(chave, *, ttl_s)` — um metodo que **nenhuma das tres
    implementacoes do `storage` tem** (a guarda tem `sign_url(ctx, ref, *,
    ttl_seconds)`, os motores tem `sign_url(chave, ttl_segundos)` posicional) e
    que o `entregar` nao chamava. Tres formas para a mesma operacao, e o
    protocolo nao casava com nenhuma.

    **E nenhum portao deste repositorio o veria:** nao ha verificador de tipos
    de Python nesta arvore (nem `mypy` nem `pyright` em `pyproject.toml` ou no
    `Makefile`), e o *gate* 2 corre o `typecheck` de TypeScript. Passar um duplo
    com a forma errada dava `TypeError` **em execucao**, nao no CI. Por isso o
    protocolo segue a implementacao, e nao o contrario.

    O tecto do TTL nao esta aqui nem na implementacao deste modulo: esta no
    `TTL_MAXIMO_S` do `kamba_core.storage`, que e quem valida. Ver a nota do
    `TTL_DA_EXPORTACAO_S`.
    """

    def sign_url(self, ctx: object, ref: object, *, ttl_seconds: int) -> str: ...


def exigir_tipo(tipo: str) -> str:
    if tipo not in TIPOS:
        raise TipoDesconhecido(tipo)
    return tipo


def exigir_escopo(escopo: str) -> str:
    if escopo not in ESCOPOS:
        raise EscopoDesconhecido(escopo)
    return escopo


def exigir_papel(papel: str) -> str:
    if papel not in PAPEIS_DA_KAMBA:
        raise PapelDesconhecido(papel)
    return papel


def prazo_interno(recebido_at: datetime, prazo_dias: int = PRAZO_INTERNO_DIAS) -> datetime:
    """`recebido_at + prazo_dias`, que e a aritmetica do criterio 1.

    **Vive aqui e nao num `CHECK` da base**, e a razao esta na revisao `0038`
    por extenso: `timestamptz + interval` e `STABLE` e nao `IMMUTABLE` em
    PostgreSQL — somar dias le o `TimeZone` da sessao —, pelo que um `CHECK`
    assim e satisfeito por quem insere e pode deixar de o ser para quem le
    noutra sessao. O que a base garante e a ordenacao
    (`prazo_interno_at > recebido_at`); a igualdade garante-se aqui, com ensaio.
    """
    if prazo_dias <= 0:
        raise ValueError(f"prazo interno nao positivo: {prazo_dias}")
    return recebido_at + timedelta(days=prazo_dias)
