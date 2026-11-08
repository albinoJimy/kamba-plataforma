"""A porta dos pedidos do titular: aceitar, recusar, rectificar, opor (KAM-070).

Tudo o que esta aqui recebe um **cursor** e nao uma ligacao, e nao e detalhe: um
pedido do titular e uma escrita, e a transaccao e de quem chama — o
`tenant_guard.tx`, que poe o `app.tenant_id` que a RLS exige. Um modulo que
abrisse a sua propria transaccao punha o evento do criterio 3 e a linha do
pedido em transaccoes diferentes, e o *outbox* transaccional do ADR-009 deixava
de valer: haveria um instante em que o evento existe e o pedido nao.

## A identificacao do titular, e porque e que a comparacao e de `contact_id`

O criterio 1 diz «aceite so do mesmo BSUID do contacto». **Este modulo nunca ve
um BSUID**: a fronteira do ADR-010 e que o que sai do cofre para o resto da
plataforma e o `contact_id` e mais nada, e o canal ja resolveu o BSUID em
`contact_id` quando a mensagem entrou (`Identidade.resolveContact`).

Comparar dois `contact_id` **e** comparar os dois BSUID que os produziram,
porque o cofre e injectivo por tenant: o indice `contact_endpoints_bsuid_uq` e
`UNIQUE (tenant_id, hmac_kid, bsuid_hmac)`, pelo que um BSUID resolve sempre
para o mesmo contacto daquele tenant. Fazer a comparacao aqui exigia o segredo
do HMAC de pesquisa num processo que nao tem razao nenhuma para o ter — e um
segredo que circula para uma comparacao e um segredo com mais um sitio de onde
fugir.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .consultas import (
    SQL_AUDITAR,
    SQL_CONCLUIR,
    SQL_CRIAR_PEDIDO,
    SQL_EM_CURSO,
    SQL_PEDIDO,
    SQL_PEDIDO_ABERTO,
    SQL_PEDIDOS_ABERTOS,
    SQL_RECTIFICAR_TELEFONE,
)
from .contrato import (
    ACCAO_RECTIFICADO,
    ACCAO_RECUSADO,
    ESTADO_RECEBIDO,
    PAPEL_POR_OMISSAO,
    PRAZO_INTERNO_DIAS,
    SEPARADOR,
    TIPO_ELIMINACAO,
    TIPO_OPOSICAO,
    TIPO_RECTIFICACAO,
    Auditoria,
    FechoSemLedger,
    Pedido,
    PedidoDeOutroTitular,
    PedidoEmCurso,
    Relogio,
    exigir_papel,
    exigir_tipo,
    prazo_interno,
)

#: O codigo de erro do PostgreSQL para violacao de unicidade.
#:
#: Le-se do atributo `pgcode` da excepcao e **nao do texto dela**: a mensagem
#: vem traduzida conforme o `lc_messages` do servidor, e um `in str(erro)`
#: deixava de apanhar a colisao numa base com locale diferente. Foi medido
#: noutro ticket desta casa a olhar para o `23514` em vez do `23505`.
UNICIDADE_VIOLADA = "23505"

#: O nome do indice que recusa o segundo pedido aberto (revisao `0038`).
#:
#: Esta aqui para **distinguir a colisao certa das outras**: a tabela tem mais
#: unicidades (a chave primaria, o par `(tenant_id, dsar_id)`), e traduzir
#: qualquer `23505` para `PedidoEmCurso` escondia um defeito de geracao de
#: identificadores atras de uma mensagem que diz «ja ha um pedido aberto».
INDICE_DO_PEDIDO_ABERTO = "dsar_requests_aberto_uq"

#: O tipo de actor, do dominio fechado da `0006`. Um pedido do titular e do
#: `contact`: nao e um funcionario a agir, e o sistema a registar o que o
#: titular pediu.
ACTOR_DO_TITULAR = "contact"

#: A entidade auditada. Uma cadeia e nao o nome da tabela, porque o que se
#: audita e o **pedido** e nao a linha.
ENTIDADE_DO_PEDIDO = "dsar"


def _pedido(linha: Sequence[Any]) -> Pedido:
    """Um `Pedido` a partir da linha, pela ordem do `COLUNAS_DO_PEDIDO`.

    Posicional e nao por nome, e com `strict`: as consultas que devolvem um
    pedido partilham **uma** lista de colunas, e se alguma divergir o
    desempacotamento falha alto em vez de preencher o campo errado.
    """
    (
        dsar_id,
        tenant_id,
        contact_id,
        tipo,
        estado,
        papel_kamba,
        recebido_at,
        prazo_dias,
        prazo_interno_at,
        concluido_at,
    ) = linha
    return Pedido(
        dsar_id=str(dsar_id),
        tenant_id=str(tenant_id),
        contact_id=str(contact_id),
        tipo=str(tipo),
        estado=str(estado),
        papel_kamba=str(papel_kamba),
        recebido_at=recebido_at,
        prazo_dias=int(prazo_dias),
        prazo_interno_at=prazo_interno_at,
        concluido_at=concluido_at,
    )


def _texto_do_hash(partes: Sequence[str]) -> str:
    """As partes separadas por `chr(31)`, que e o separador da cadeia da `0006`.

    O mesmo separador do `CONCATENACAO_DO_ROW_HASH` e do escritor do COM. Nao e
    o mesmo *hash* — este e o `payload_hash`, aquele e o `row_hash` —, mas um
    separador diferente em cada escritor era uma canonicalizacao por escritor, e
    duas canonicalizacoes produzem *hashes* diferentes para o mesmo facto.
    """
    return SEPARADOR.join(partes)


class PortaDeDireitos:
    """Recebe e conduz pedidos do titular.

    O relogio e injectado e **le-se uma vez por decisao**, nunca por dentro de
    cada passo: e a licao do KAM-069, onde uma *cache* com relogio injectavel
    continuava a chamar `agora()` por dentro e o ensaio do prazo nao media nada.
    Aqui o `agora` de um `receber` e **um** instante, e e dele que sai o
    `recebido_at` e o `prazo_interno_at` — com duas leituras, a aritmetica do
    criterio 1 podia falhar por microssegundos e ninguem saberia porque.
    """

    def __init__(
        self,
        *,
        relogio: Relogio,
        auditoria: Auditoria,
        prazo_dias: int = PRAZO_INTERNO_DIAS,
        papel_kamba: str = PAPEL_POR_OMISSAO,
    ) -> None:
        self._relogio = relogio
        self._auditoria = auditoria
        self._prazo_dias = prazo_dias
        #: Validado no arranque e nao na escrita: um papel invalido e um erro de
        #: configuracao, e descobri-lo ao receber o primeiro pedido do titular e
        #: descobri-lo no pior instante possivel.
        self._papel_kamba = exigir_papel(papel_kamba)

    @property
    def papel_kamba(self) -> str:
        return self._papel_kamba

    @property
    def prazo_dias(self) -> int:
        return self._prazo_dias

    def receber(
        self,
        cursor: Any,
        *,
        tenant_id: str,
        requerente: str,
        tipo: str,
        alvo: str | None = None,
    ) -> Pedido:
        """Aceita um pedido do titular, ou recusa-o (criterios 1 e 8).

        O `alvo` **tem omissao e a omissao e o proprio requerente**, e isso e a
        parte do desenho que faz o criterio 1 dificil de violar por descuido:
        quem chama sem pensar no assunto obtem o caso certo. O parametro existe
        para que o caso errado se possa **recusar**, e nao para que se possa
        pedir.

        Recusa com `PedidoDeOutroTitular` e escreve no `audit_log` (criterio 1:
        «devolve 0 dados e fica registado»). Levantar e o que entrega os «0
        dados»: nao ha caminho em que esta funcao devolva um pedido sobre o
        contacto de outra pessoa.
        """
        exigir_tipo(tipo)
        titular = alvo if alvo is not None else requerente
        if titular != requerente:
            # A ordem importa: **registar antes de levantar**. Com a excepcao
            # primeiro, a escrita no `audit_log` ficava num `finally` ou perdia-se
            # — e um registo que depende de quem apanha a excepcao nao e um
            # registo.
            self._auditoria.escrever(
                tenant_id=tenant_id,
                accao=ACCAO_RECUSADO,
                contact_id=requerente,
                detalhe={"tipo": tipo, "alvo": titular},
            )
            raise PedidoDeOutroTitular

        agora = self._relogio.agora()
        try:
            cursor.execute(
                SQL_CRIAR_PEDIDO,
                (
                    tenant_id,
                    titular,
                    tipo,
                    ESTADO_RECEBIDO,
                    self._papel_kamba,
                    agora,
                    self._prazo_dias,
                    prazo_interno(agora, self._prazo_dias),
                ),
            )
        except Exception as erro:  # noqa: BLE001 - traduz-se e volta a levantar
            if not self._e_pedido_ja_aberto(erro):
                raise
            raise self._em_curso(cursor, titular, tipo) from erro
        return _pedido(cursor.fetchone())

    @staticmethod
    def _e_pedido_ja_aberto(erro: Exception) -> bool:
        """`true` so para a colisao do indice do pedido aberto.

        Duas condicoes, e as duas sao necessarias: o `pgcode` **e** o nome do
        indice. Com so o `pgcode`, um `23505` da chave primaria — isto e, um
        defeito do gerador de UUID — voltava ao chamador como «ja ha um pedido
        aberto», e quem o lesse procurava o pedido que nao existe.
        """
        if getattr(erro, "pgcode", None) != UNICIDADE_VIOLADA:
            return False
        restricao = getattr(getattr(erro, "diag", None), "constraint_name", None)
        return restricao == INDICE_DO_PEDIDO_ABERTO

    def _em_curso(self, cursor: Any, titular: str, tipo: str) -> PedidoEmCurso:
        """O `PedidoEmCurso` com o pedido que ja existe, ou sem ele.

        **A leitura pode nao devolver nada**, e nao e caso impossivel: a
        transaccao que colidiu foi abortada, pelo que ler aqui exige um
        `SAVEPOINT` ou corre numa transaccao nova — e se entretanto o outro
        pedido fechou, nao ha linha. Nesse caso diz-se «ha um pedido aberto e
        nao se conseguiu ler qual», que e a verdade, em vez de levantar um
        segundo erro por cima do primeiro.
        """
        try:
            cursor.execute(SQL_PEDIDO_ABERTO, (titular, tipo))
            linha = cursor.fetchone()
        except Exception:  # noqa: BLE001 - a transaccao pode estar abortada
            linha = None
        return PedidoEmCurso(str(linha[0]) if linha else "desconhecido", tipo)

    def em_curso(self, cursor: Any, dsar_id: str) -> Pedido | None:
        """Marca o pedido como `em_curso`. `None` se ja nao estava `recebido`."""
        cursor.execute(SQL_EM_CURSO, (dsar_id,))
        linha = cursor.fetchone()
        return _pedido(linha) if linha else None

    def ler(self, cursor: Any, dsar_id: str) -> Pedido | None:
        cursor.execute(SQL_PEDIDO, (dsar_id,))
        linha = cursor.fetchone()
        return _pedido(linha) if linha else None

    def concluir(self, cursor: Any, pedido: Pedido) -> Pedido | None:
        """Fecha o pedido. `None` se ja estava fechado — ver o `SQL_CONCLUIR`.

        **Recusa um pedido de eliminacao**, e e a correccao do achado mais serio
        da revisao adversarial deste ramo. A primeira versao recebia um
        `dsar_id` solto, fechava qualquer pedido, e dizia na *docstring* que
        quem verificava os seis escopos era uma funcao que **nao existia** — o
        criterio 3 ficava satisfeito por convencao, e o titular era informado de
        que o apagamento estava feito com o *ledger* vazio.

        **Recebe o `Pedido` e nao o `dsar_id`** por isso mesmo: com o
        identificador solto, esta funcao nao tinha como saber de que tipo era o
        pedido que estava a fechar, e a recusa era impossivel de escrever. E a
        mesma razao pela qual as quatro operacoes recebem o pedido.

        A verificacao do *ledger* fica no `eliminacao.concluir_apagamento` e nao
        aqui, e isso continua certo: um pedido de exportacao nao tem escopos
        nenhuns e teria de contornar a verificacao. O que mudou e que agora **nao
        ha caminho** que feche uma eliminacao sem passar por lá.
        """
        if pedido.tipo == TIPO_ELIMINACAO:
            raise FechoSemLedger(pedido.dsar_id)
        return self._fechar(cursor, pedido.dsar_id)

    def _fechar(self, cursor: Any, dsar_id: str) -> Pedido | None:
        """A escrita do fecho, sem guarda nenhuma.

        **Privada, e o sublinhado nao e decoracao:** e o unico sitio onde
        `estado = 'concluido'` se escreve, e o `concluir_apagamento` chama-a
        **depois** de exigir os seis escopos. Publica-la era reabrir o buraco
        que a recusa do `concluir` fecha.
        """
        cursor.execute(SQL_CONCLUIR, (self._relogio.agora(), dsar_id))
        linha = cursor.fetchone()
        return _pedido(linha) if linha else None

    def abertos(self, cursor: Any) -> tuple[Pedido, ...]:
        """Os pedidos abertos do tenant do contexto, do mais antigo ao mais novo."""
        cursor.execute(SQL_PEDIDOS_ABERTOS)
        return tuple(_pedido(linha) for linha in cursor.fetchall())

    def em_atraso(self, cursor: Any) -> tuple[Pedido, ...]:
        """Os que passaram o prazo interno (criterio 8)."""
        agora = self._relogio.agora()
        return tuple(p for p in self.abertos(cursor) if p.em_atraso(agora))

    def com_alerta_devido(self, cursor: Any) -> tuple[Pedido, ...]:
        """Os que chegaram ao dia do alerta (criterio 8, «aos 20 dias»)."""
        agora = self._relogio.agora()
        return tuple(p for p in self.abertos(cursor) if p.alerta_devido(agora))

    def rectificar_telefone(
        self,
        cursor_do_cofre: Any,
        *,
        pedido: Pedido,
        finalidade: str,
        phone_enc: bytes,
    ) -> int:
        """Rectifica o telefone cifrado do titular (criterio 7, primeira metade).

        **Recebe o `Pedido` e nao um `contact_id`**, e e a ligacao que faz o
        criterio 1 valer tambem aqui: o `contact_id` que esta funcao usa so pode
        ser o de um pedido que o `receber` aceitou — isto e, o do proprio
        requerente. Com um `contact_id` solto no argumento, rectificar os dados
        de outra pessoa era uma chamada bem formada.

        ## Porque e que isto **nao** escreve no `audit_log`, e e emenda

        O criterio 7 diz «rectificacao ... **e escreve no `audit_log`**», e a
        primeira versao fazia as duas no mesmo cursor. **Nao pode**, e a razao e
        um `GRANT` de outra revisao:

            `contact_endpoints` (UPDATE)   so `kamba_identity` (`0003`)
            `audit_append` (EXECUTE)       so `kamba_app` e `kamba_batch` (`0006`)

        Os dois conjuntos sao **disjuntos**. Na ligacao do cofre o `audit_append`
        levantava `42501` e a transaccao revertia — a rectificacao nunca
        acontecia; na ligacao da aplicacao o `UPDATE` levantava `42501`
        primeiro. Foi achado da revisao adversarial, e a primeira versao deste
        modulo entregava um criterio **impossivel de cumprir**.

        **E a ausencia desse privilegio e deliberada e nao um esquecimento:** o
        `0006` escreve que o `REVOKE ALL ... FROM PUBLIC` existe precisamente
        para que o `kamba_resolver` e o `kamba_identity` nao possam chamar a
        funcao, e que isso foi **apanhado por uma revisao adversarial** daquele
        ticket. Logo conceder-lho aqui era afrouxar o criterio do KAM-012 a
        partir deste — a mesma decisao que o `kamba_agr` nao obteve.

        Por isso a operacao tem **dois passos em duas ligacoes**, e quem a
        conduz chama os dois: este, no cursor do cofre, e o
        `auditar_rectificacao`, no cursor da aplicacao. **Nao e atomico**, e
        diz-se: entre os dois ha um instante em que o telefone esta rectificado e
        o `audit_log` nao o diz. O lado seguro e esta ordem — auditar primeiro
        deixava o registo a afirmar uma rectificacao que pode nao ter
        acontecido, e um registo de auditoria que afirma o que nao se deu e pior
        do que um que chega tarde.
        """
        if pedido.tipo != TIPO_RECTIFICACAO:
            raise ValueError(
                f"rectificar sobre um pedido de {pedido.tipo}: o tipo do pedido e "
                "que autoriza a operacao"
            )
        cursor_do_cofre.execute(
            SQL_RECTIFICAR_TELEFONE,
            (phone_enc, self._relogio.agora(), pedido.contact_id, finalidade),
        )
        return len(cursor_do_cofre.fetchall())

    def auditar_rectificacao(
        self, *, pedido: Pedido, finalidade: str, linhas: int
    ) -> None:
        """Escreve a rectificacao no `audit_log` (criterio 7, segunda metade).

        Corre na ligacao da **aplicacao**, pela razao do `rectificar_telefone`.
        O `linhas` vem de la: auditar «rectifiquei zero linhas» e informacao, e
        nao auditar nada quando nao houve linha escondia um pedido que nao
        encontrou o endpoint que o titular queria corrigir.
        """
        if pedido.tipo != TIPO_RECTIFICACAO:
            raise ValueError(
                f"auditar rectificacao sobre um pedido de {pedido.tipo}"
            )
        self._auditoria.escrever(
            tenant_id=pedido.tenant_id,
            accao=ACCAO_RECTIFICADO,
            contact_id=pedido.contact_id,
            detalhe={
                "dsar_id": pedido.dsar_id,
                "finalidade": finalidade,
                "linhas": linhas,
            },
        )


class AuditoriaNaBase:
    """A `Auditoria` sobre `platform.audit_append`.

    O `sha256` e **da base** e nao do Python, como no escritor do COM: um
    *hash* calculado do lado do cliente era um segundo sitio onde a cadeia se
    pode canonicalizar de outra maneira, e duas canonicalizacoes produzem
    *hashes* diferentes para o mesmo facto.

    O `detalhe` entra no texto que se hasheia e **nao** numa coluna: nao ha
    coluna de texto livre no `audit_log`, de proposito (`0006` §7.1). O que fica
    legivel na linha sao o actor, a accao e a entidade; o resto fica provado
    pelo *hash* e reconstroi-se por quem tiver o detalhe.
    """

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def escrever(
        self,
        *,
        tenant_id: str,
        accao: str,
        contact_id: str | None,
        detalhe: Mapping[str, object],
    ) -> None:
        alvo = contact_id or ENTIDADE_DO_PEDIDO
        texto = _texto_do_hash(
            (accao, alvo, json.dumps(dict(detalhe), sort_keys=True, default=str))
        )
        self._cursor.execute(
            SQL_AUDITAR,
            (
                tenant_id,
                ACTOR_DO_TITULAR,
                alvo,
                accao,
                ENTIDADE_DO_PEDIDO,
                alvo,
                None,
                texto.encode("utf-8"),
            ),
        )


class RelogioDoSistema:
    """O `Relogio` de producao. Em UTC, pela convencao do conjunto."""

    def agora(self) -> datetime:
        from datetime import timezone

        return datetime.now(tz=timezone.utc)


__all__ = [
    "ACTOR_DO_TITULAR",
    "ENTIDADE_DO_PEDIDO",
    "INDICE_DO_PEDIDO_ABERTO",
    "UNICIDADE_VIOLADA",
    "AuditoriaNaBase",
    "PortaDeDireitos",
    "RelogioDoSistema",
    "TIPO_OPOSICAO",
]
