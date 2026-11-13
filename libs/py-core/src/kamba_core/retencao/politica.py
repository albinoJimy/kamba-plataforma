"""A `retention_policy`: as classes de retencao como configuracao versionada (KAM-071).

Este ficheiro e a configuracao, e nao ha outra. Nao le base de dados, nao apaga
nada e nao le relogio: diz **que** classe tem **que** prazo, a partir de **que**
instante, por **que** mecanismo, e que tabelas cobre. Quem apaga e o `jobs.py`.

## Todos os prazos sao *proposta*, e isso esta na estrutura e nao num comentario

O `docs/tecnica/08` §11 abre com «os prazos sao **propostas** de engenharia; os
legais estao por confirmar», e o `docs/tecnica/06` §7.4 diz o mesmo no titulo.
Por isso cada `Classe` leva `estado = "proposta"` e o `validar` **recusa** outro
valor: passar um prazo a facto e decisao do parecer juridico, e faz-se mudando
esta constante com a referencia do parecer — nao por esquecimento.

## Quatro conflitos entre fontes, registados aqui

1. **12 contra 13 meses** para `assistant_queries`: o `08` §11 da 12, o `06`
   §7.4 da 12 tambem, e o bloco do KAM-071 manda adoptar **13** (a vida da
   `K_epoca`). Adopta-se 13, pelo bloco, e a divergencia fica na nota da classe.
2. **WORM do SeaweedFS NAO VERIFICADO** (so Clusters): a expiracao de objectos
   e feita por este *job* (`ttl_sto`), e nao por *lifecycle* do servidor.
3. **`audit_log`**: >= prazo fiscal para dinheiro, 12 meses para acessos. Com o
   prazo fiscal nulo, nenhum dos dois e calculavel sem o outro; a classe e
   `conservar` ate o CGT ser confirmado.
4. **Prazo do CGT NAO VERIFICADO** (`E3` §6, D7 com o `08`): o
   `fiscal_retention_years` nao tem valor por omissao, e o *job* recusa purgar
   as classes fiscais sem ele.

E um quinto, de nome: o `06` §7.4 escreve `retencao_fiscal_anos` e o `08` §8.8
`fiscal_retention_years`. Fica o do `08`, que e o do bloco.

## Uma tabela esta numa classe, ou declara que nao guarda dados pessoais

E o criterio 2: o catalogo da base percorre **todas** as tabelas dos esquemas
da aplicacao e exige que cada uma esteja aqui — ou numa `Classe`, ou em
`SEM_DADOS_PESSOAIS` com a razao. E uma lista fechada pela mesma razao do
`INVENTARIO` do *gate* 8: uma lista de fragmentos proibidos nunca fecha, e uma
lista de tabelas declaradas fecha. Quem criar uma tabela responde aqui a
pergunta «que prazo tem isto?».
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

#: A versao desta configuracao. Sobe a cada alteracao de prazo, de mecanismo ou
#: de tabela, e vai em cada linha do `purge_log`: uma purga que nao diz com que
#: politica correu nao se audita.
VERSAO_DA_POLITICA: Final = "2026-11-10.1"

#: O unico estado aceite. Ver a nota do modulo.
ESTADO_PROPOSTA: Final = "proposta"

# ---------------------------------------------------------------- mecanismos

#: `DELETE` por tenant, com o predicado da classe, como `kamba_batch`.
APAGAR: Final = "apagar"
#: `DROP` de particao mensal (sem `UPDATE` nem `DELETE` em massa).
LARGAR_PARTICAO: Final = "largar_particao"
#: O objecto no `StorageProvider` primeiro, a linha depois.
TTL_STO: Final = "ttl_sto"
#: Expira pelo ciclo do repositorio de copias (KAM-079); nao se reescreve.
CICLO_DO_REPOSITORIO: Final = "ciclo_do_repositorio"
#: Vive fora desta base (Loki, Chatwoot); a classe declara o prazo.
EXTERNO: Final = "externo"
#: Corre no processo dono da loja, com o papel que a revisao lhe da.
DELEGADO: Final = "delegado"
#: Fiscal: recusa sem `fiscal_retention_years`.
FISCAL: Final = "fiscal"
#: Nunca se purga automaticamente; a razao vai na classe.
CONSERVAR: Final = "conservar"
#: Dura a relacao com o tenant; sai no encerramento (criterio 9).
ENCERRAMENTO: Final = "encerramento"

MECANISMOS: Final = (
    APAGAR,
    LARGAR_PARTICAO,
    TTL_STO,
    CICLO_DO_REPOSITORIO,
    EXTERNO,
    DELEGADO,
    FISCAL,
    CONSERVAR,
    ENCERRAMENTO,
)

#: Os mecanismos que o `jobs.py` executa nesta base.
MECANISMOS_EXECUTADOS: Final = (APAGAR, LARGAR_PARTICAO, TTL_STO, FISCAL)

#: A variavel de ambiente do prazo fiscal. **Sem omissao**: ver a nota do modulo.
VARIAVEL_FISCAL: Final = "KAMBA_FISCAL_RETENTION_YEARS"

#: O tecto do alargamento por PME da classe `conversas` (`08` §11).
CONVERSAS_MAXIMO_DIAS: Final = 365


class PoliticaInvalida(ValueError):
    """A configuracao contradiz uma regra que a torna segura."""


@dataclass(frozen=True)
class Prazo:
    """Um prazo, numa so unidade. Os meses contam-se pelo calendario."""

    horas: int = 0
    dias: int = 0
    meses: int = 0

    def __post_init__(self) -> None:
        unidades = [v for v in (self.horas, self.dias, self.meses) if v]
        if len(unidades) != 1 or unidades[0] < 0:
            raise PoliticaInvalida("um prazo tem exactamente uma unidade, positiva")

    def antes_de(self, instante: datetime) -> datetime:
        """O instante `instante - prazo`. E o limite: o que e anterior sai."""
        if instante.tzinfo is None:
            raise PoliticaInvalida("um instante sem fuso nao e um instante")
        if self.horas:
            return instante - timedelta(hours=self.horas)
        if self.dias:
            return instante - timedelta(days=self.dias)
        return recuar_meses(instante, self.meses)


def recuar_meses(instante: datetime, meses: int) -> datetime:
    """`instante` menos `meses` de calendario, com o dia limitado ao do mes.

    31 de Marco menos um mes e 28 (ou 29) de Fevereiro, e nao 3 de Marco: um
    prazo de meses que transborda para o mes seguinte apagava dados com dias de
    antecedencia.
    """
    total = instante.year * 12 + (instante.month - 1) - meses
    ano, mes = divmod(total, 12)
    mes += 1
    dia = min(instante.day, _dias_do_mes(ano, mes))
    return instante.replace(year=ano, month=mes, day=dia)


def _dias_do_mes(ano: int, mes: int) -> int:
    seguinte = datetime(ano + (mes == 12), mes % 12 + 1, 1)
    return (seguinte - timedelta(days=1)).day


@dataclass(frozen=True)
class Tabela:
    """Uma tabela coberta por uma classe.

    `ligada` diz se o `jobs.py` tem o caminho que a purga. Uma tabela por ligar
    esta **mapeada** (o criterio 2 conta-a) e o *job* regista-a como `recusada`
    com `sem_caminho` — nunca como `ok`. A `pendencia` diz porque e quem paga.
    """

    nome: str
    ligada: bool = False
    pendencia: str = ""


@dataclass(frozen=True)
class Classe:
    """Uma classe de retencao. Ver a nota do modulo."""

    nome: str
    mecanismo: str
    inicio: str
    tabelas: tuple[Tabela, ...] = ()
    prazo: Prazo | None = None
    maximo: Prazo | None = None
    fiscal: bool = False
    estado: str = ESTADO_PROPOSTA
    fonte: str = ""
    nota: str = ""


def _t(nome: str, ligada: bool = False, pendencia: str = "") -> Tabela:
    return Tabela(nome, ligada, pendencia)


_CONVERSAS_PENDENTE = (
    "conteudo de conversa sem caminho de purga nesta revisao: as FK para "
    "conversations e o append-only por trigger pedem ordem propria; credor KAM-098"
)
_RELACAO = "dura a relacao com o tenant e sai no encerramento (criterio 9, KAM-098)"
_FISCAL_IMUTAVEL = (
    "registo imutavel por trigger (deny_mutation); com o prazo fiscal definido "
    "a purga e listada em dry-run e recusada em efectiva ate haver caminho de "
    "escrita (decisao do fundador, D7)"
)

#: As classes. A ordem e a de execucao.
POLITICA: Final[tuple[Classe, ...]] = (
    Classe(
        "conversas",
        APAGAR,
        "fecho da conversa: greatest(window_expires_at, last_human_activity_at)",
        (
            _t("platform.outbound_messages", ligada=True),
            _t("platform.handoffs", pendencia=_CONVERSAS_PENDENTE),
            _t("platform.tool_audit", pendencia=_CONVERSAS_PENDENTE),
            _t("platform.draft_decisions", pendencia=_CONVERSAS_PENDENTE),
            _t("platform.tool_idempotency", pendencia=_CONVERSAS_PENDENTE),
            _t("platform.inbound_events", pendencia=_CONVERSAS_PENDENTE),
        ),
        prazo=Prazo(dias=90),
        maximo=Prazo(dias=CONVERSAS_MAXIMO_DIAS),
        fonte="docs/tecnica/08 §11",
        nota="a PME pode alargar ate 12 meses com justificacao registada",
    ),
    Classe(
        "audio",
        TTL_STO,
        "media_assets.retain_until (criacao + 24 h, KAM-020)",
        (_t("platform.media_assets", ligada=True),),
        prazo=Prazo(horas=24),
        maximo=Prazo(horas=72),
        fonte="docs/tecnica/08 §7.5 e §11",
        nota=(
            "o retain_until conta da criacao e nao da transcricao (0012), pelo "
            "que e mais curto do que os dois prazos do criterio; as imagens e os "
            "documentos expiram pelo mesmo retain_until"
        ),
    ),
    Classe(
        "assistant_queries",
        LARGAR_PARTICAO,
        "mes da particao",
        prazo=Prazo(meses=13),
        fonte="docs/tecnica/06 §7.4; bloco do KAM-071",
        nota="13 e nao os 12 do 08 §11: a vida da K_epoca (conflito 1)",
    ),
    Classe(
        "assistant_query_texto",
        LARGAR_PARTICAO,
        "mes da particao",
        prazo=Prazo(dias=90),
        fonte="docs/tecnica/06 §7.4",
    ),
    Classe(
        "logs_tecnicos",
        EXTERNO,
        "instante do registo",
        prazo=Prazo(dias=30),
        fonte="docs/tecnica/08 §11",
        nota="Loki e traces: rotacao do proprio armazenamento (KAM-080)",
    ),
    Classe(
        "events_outbox",
        APAGAR,
        "events_outbox.publicado_at",
        (
            _t("platform.events_outbox", ligada=True),
        ),
        prazo=Prazo(dias=7),
        fonte="docs/tecnica/06 §7.4",
    ),
    Classe(
        "events_log",
        LARGAR_PARTICAO,
        "mes da particao (ocorrido_em)",
        (
            _t("platform.events_log", ligada=True),
            _t(
                "platform.events_log_default",
                pendencia=(
                    "a particao DEFAULT nao se larga: tem as linhas sem mes "
                    "proprio; o job cria as mensais (M..M+2) para que deixe de "
                    "as receber"
                ),
            ),
        ),
        prazo=Prazo(meses=24),
        fonte="docs/tecnica/06 §7.4",
    ),
    Classe(
        "events_consumed",
        APAGAR,
        "events_consumed.processado_at",
        (
            _t("platform.events_consumed", ligada=True),
            _t(
                "platform.evt_acoes",
                pendencia="idempotencia de accoes externas; prazo por fixar (KAM-080)",
            ),
        ),
        prazo=Prazo(dias=90),
        fonte="docs/tecnica/06 §7.4",
    ),
    Classe(
        "events_dlq",
        APAGAR,
        "events_dlq.resolvido_at (entradas abertas nunca saem)",
        (
            _t("platform.events_dlq", ligada=True),
            _t("platform.evt_dlq_aprovacoes", ligada=True),
        ),
        prazo=Prazo(dias=30),
        fonte="docs/tecnica/06 §7.4",
    ),
    Classe(
        "entrada_em_quarentena",
        APAGAR,
        "unrouted_events.recebido_at",
        (_t("platform.unrouted_events", ligada=True),),
        prazo=Prazo(dias=7),
        fonte="docs/gwy.md (quarentena de 7 dias, KAM-018)",
    ),
    Classe(
        "llm_call_log",
        LARGAR_PARTICAO,
        "mes da particao (ts)",
        (
            _t("dat.llm_call_log", ligada=True),
            _t(
                "dat.llm_call_log_default",
                pendencia="a particao DEFAULT nao se larga (ver events_log)",
            ),
        ),
        prazo=Prazo(meses=13),
        fonte="docs/tecnica/06 §7.4",
    ),
    Classe(
        "lg_checkpoints",
        DELEGADO,
        "ultima escrita da thread",
        (
            _t("lg.checkpoints", pendencia="kamba_agr.retencao.varrer (KAM-026)"),
            _t("lg.checkpoint_writes", pendencia="kamba_agr.retencao.varrer (KAM-026)"),
        ),
        prazo=Prazo(dias=30),
        fonte="docs/tecnica/02 §12; services/agr/src/kamba_agr/retencao.py",
        nota="o 90 dias apos fecho do 08 §11 e outro relogio; o AGR fica com o seu",
    ),
    Classe(
        "chatwoot",
        EXTERNO,
        "fecho da conversa",
        prazo=Prazo(dias=90),
        fonte="docs/tecnica/08 §11",
        nota="as conversas vivem no Chatwoot; a purga e a API dele (KAM-019)",
    ),
    Classe(
        "backup_wal",
        CICLO_DO_REPOSITORIO,
        "arquivo do segmento",
        prazo=Prazo(dias=7),
        fonte="docs/tecnica/08 §11; infra/backup/cobertura.yaml (pitr_dias)",
        nota="sem reescrita; o erasure ledger e reaplicado no restauro (KAM-070/085)",
    ),
    Classe(
        "backup_diario",
        CICLO_DO_REPOSITORIO,
        "instante da copia",
        prazo=Prazo(dias=35),
        fonte="docs/tecnica/08 §11; infra/backup/cobertura.yaml (retencao_dias)",
        nota="sem reescrita; o erasure ledger e reaplicado no restauro (KAM-070/085)",
    ),
    Classe(
        "fiscal_encomendas",
        FISCAL,
        "criacao da encomenda",
        (
            _t("platform.orders_mirror", pendencia=_FISCAL_IMUTAVEL),
            _t("platform.order_state_log", pendencia=_FISCAL_IMUTAVEL),
            _t("platform.order_intents", pendencia=_FISCAL_IMUTAVEL),
            _t("platform.order_reconciliation_issues", pendencia=_FISCAL_IMUTAVEL),
            _t("platform.stock_reservations", pendencia=_FISCAL_IMUTAVEL),
            _t("platform.price_quotes", pendencia=_FISCAL_IMUTAVEL),
        ),
        fiscal=True,
        fonte="docs/tecnica/08 §8.8 e §11; E3 §6",
    ),
    Classe(
        "fiscal_pagamentos",
        FISCAL,
        "ocorrido_at do evento",
        (
            _t("platform.payment_events", pendencia=_FISCAL_IMUTAVEL),
            _t("platform.payment_charges", pendencia=_FISCAL_IMUTAVEL),
            _t("platform.payment_callbacks_inbox", pendencia=_FISCAL_IMUTAVEL),
            _t("platform.manual_confirmations", pendencia=_FISCAL_IMUTAVEL),
            _t("platform.refund_cases", pendencia=_FISCAL_IMUTAVEL),
        ),
        fiscal=True,
        fonte="docs/tecnica/08 §8.8 e §11; E3 §6",
    ),
    Classe(
        "fiscal_facturas",
        FISCAL,
        "emissao da factura",
        fiscal=True,
        fonte="docs/tecnica/08 §8.8 (fiscal_docs)",
        nota="a tabela fiscal_docs ainda nao existe; a classe fica declarada",
    ),
    Classe(
        "registo_de_conformidade",
        CONSERVAR,
        "nao se aplica",
        (
            _t("platform.audit_log", pendencia="append-only; >= prazo fiscal (conflito 3)"),
            _t("platform.audit_heads", pendencia="cabeca da cadeia do audit_log"),
            _t(
                "platform.erasure_ledger",
                pendencia=(
                    "e o que impede um restauro de ressuscitar titulares "
                    "apagados; nunca sai antes da copia mais antiga"
                ),
            ),
            _t("platform.dsar_requests", pendencia="prova do pedido do titular"),
            _t("platform.purge_log", pendencia="prova da purga"),
            _t("platform.consent_event", pendencia="relacao + prescricao (a confirmar)"),
            _t("platform.contract_acceptance", pendencia="prova contratual da PME"),
            # KAM-088 (0044). *Append-only* por *trigger*: a decisao e o que
            # justifica um produto publicado ou recusado, e o recurso e
            # uma linha nova.
            _t("platform.screening_decision", pendencia="prova da decisao de screening"),
            # KAM-089 (0048). A decisao humana e o caso que ela decidiu: o
            # registo e *append-only* por *trigger*, e o caso e o que da sentido
            # as linhas dele. A `nota_enc` do revisor pode levar dados
            # pessoais e vai cifrada; o prazo e o da prova, por decidir.
            _t("platform.review_case", pendencia="prova da revisao humana"),
            _t("platform.review_decision_log", pendencia="prova da revisao humana"),
        ),
        fonte="docs/tecnica/08 §11",
    ),
    Classe(
        "relacao",
        ENCERRAMENTO,
        "encerramento do tenant",
        (
            _t("platform.tenants", pendencia=_RELACAO),
            _t("platform.tenant_channels", pendencia=_RELACAO),
            _t("platform.contacts", pendencia=_RELACAO),
            _t("platform.contact_endpoints", pendencia=_RELACAO + "; expira_at com KAM-072"),
            _t("platform.contact_deks", pendencia=_RELACAO),
            _t("platform.conversations", pendencia=_RELACAO),
            _t("platform.owner_contacts", pendencia=_RELACAO),
            _t("platform.owner_notices", pendencia=_RELACAO),
            _t("platform.handoff_accounts", pendencia=_RELACAO),
            _t("platform.channel_onboarding", pendencia=_RELACAO),
            _t("platform.channel_coexistence", pendencia=_RELACAO),
            _t("platform.payment_accounts", pendencia=_RELACAO),
            _t("platform.payment_confirmers", pendencia=_RELACAO),
            _t("platform.fraud_signals", pendencia=_RELACAO),
            _t("platform.provisioning_step", pendencia=_RELACAO),
            # KAM-087 (0043). O caso vive com o tenant pre-alocado. Os
            # documentos K1 de um caso rejeitado ou abandonado esquecem-se a
            # D+30 do `fase_at` pelo `ServicoKyc.purgar` (TypeScript), que
            # nenhum agendador chama ainda; os de um caso vivo seguem a relacao.
            _t("platform.onboarding_case", pendencia=_RELACAO),
            _t(
                "platform.kyc_check",
                pendencia=_RELACAO + "; casos mortos: D+30 pelo ServicoKyc.purgar, sem agendador",
            ),
            # KAM-049 (revisao do Catalogo AI). A ingestao de uma foto e o que
            # a visao leu dela: vive com o catalogo do tenant e sai no
            # encerramento. A foto em si esta no STO, presa ao tenant pela
            # `media_ref`, e expira pelo `retain_until` do objecto.
            _t(
                "platform.catalog_ingestions",
                pendencia=_RELACAO + "; a foto no STO expira pelo retain_until (90 dias, proposta)",
            ),
            _t("servicos.bookings", pendencia=_RELACAO),
        ),
        fonte="docs/tecnica/08 §7.1 e §11 (PME: relacao + fiscal)",
    ),
)

#: As tabelas que nao guardam dados pessoais, com a razao. Ver a nota do modulo.
SEM_DADOS_PESSOAIS: Final[Mapping[str, str]] = {
    "platform.entitlements": "limites do plano",
    "platform.evt_subscricoes": "configuracao de consumidores",
    "platform.evt_agregado_seq": "contador por agregado",
    "platform.hmac_key_versions": "versoes de chave, sem chave",
    "platform.order_state_graph": "grafo de estados, sem tenant",
    "platform.payment_outbox_map": "mapa de tipos de evento, sem tenant",
    "platform.consent_texts": "texto do consentimento, igual para todos",
    "platform.contract_document": "texto do contrato, igual para todos",
    "platform.message_templates": "modelos de mensagem do negocio",
    "platform.tenant_usage": "contadores de uso",
    "platform.usage_ledger": "contadores de uso",
    "platform.channel_quality_log": "qualidade do numero do negocio",
    "platform.tenant_destinations": "destinos de transferencia do negocio",
    "platform.offer_terms": "catalogo: vida do catalogo",
    "servicos.services": "catalogo de servicos",
    "servicos.resources": "recursos do negocio",
    "servicos.availability_rules": "horarios do negocio",
    # KAM-061 (0045). O documento do indice e o catalogo normalizado da PME, e
    # vive com a oferta: quando ela sai, o consumidor poe-no invisivel, e a
    # purga dele segue a do catalogo. O lexico e de termos, e nunca de pessoas.
    "idx.search_doc": "catalogo normalizado: vida do catalogo",
    "idx.termo_canonico": "lexico PT-AO, sem pessoas",
    # KAM-062 (0049). Uma linha por alteracao do lexico: um numero, um booleano
    # e uma data, sem tenant e sem pessoa.
    "idx.norm_versao": "versao do lexico PT-AO, sem tenant nem pessoas",
}


def classe(nome: str) -> Classe:
    """A classe pelo nome, ou `KeyError`."""
    for c in POLITICA:
        if c.nome == nome:
            return c
    raise KeyError(nome)


def tabelas_mapeadas(politica: Iterable[Classe] = POLITICA) -> dict[str, str]:
    """`tabela -> classe`, de todas as classes."""
    return {t.nome: c.nome for c in politica for t in c.tabelas}


def tabelas_ligadas(politica: Iterable[Classe] = POLITICA) -> frozenset[str]:
    """As tabelas que a politica diz que o `jobs.py` purga."""
    return frozenset(t.nome for c in politica for t in c.tabelas if t.ligada)


def validar(
    politica: tuple[Classe, ...] = POLITICA,
    sem_dados: Mapping[str, str] = SEM_DADOS_PESSOAIS,
) -> None:
    """Recusa a configuracao que torne a purga insegura.

    Cada regra tem um ensaio que a mostra a morder. As que importam mais:

    * o `erasure_ledger` e o `purge_log` **nunca** sao purgaveis: sem eles um
      restauro devolve titulares apagados e dados purgados sem que ninguem
      saiba que tem de os tirar outra vez;
    * uma classe fiscal nao tem prazo fixo — o prazo e o parametro;
    * uma tabela esta numa so classe, e nunca tambem em `SEM_DADOS_PESSOAIS`.
    """
    nomes: set[str] = set()
    vistas: set[str] = set()
    for c in politica:
        if c.nome in nomes:
            raise PoliticaInvalida(f"classe repetida: {c.nome}")
        nomes.add(c.nome)
        if c.estado != ESTADO_PROPOSTA:
            raise PoliticaInvalida(
                f"{c.nome}: o prazo e proposta ate o parecer o confirmar"
            )
        if c.mecanismo not in MECANISMOS:
            raise PoliticaInvalida(f"{c.nome}: mecanismo desconhecido {c.mecanismo}")
        if c.fiscal != (c.mecanismo == FISCAL):
            raise PoliticaInvalida(f"{c.nome}: fiscal e mecanismo fiscal andam juntos")
        if c.fiscal and c.prazo is not None:
            raise PoliticaInvalida(
                f"{c.nome}: uma classe fiscal nao tem prazo por omissao (CGT NAO VERIFICADO)"
            )
        if c.mecanismo in (APAGAR, LARGAR_PARTICAO, TTL_STO) and c.prazo is None:
            raise PoliticaInvalida(f"{c.nome}: uma classe que purga tem prazo")
        for t in c.tabelas:
            if t.nome in vistas:
                raise PoliticaInvalida(f"{t.nome} esta em mais do que uma classe")
            vistas.add(t.nome)
            if t.nome in sem_dados:
                raise PoliticaInvalida(f"{t.nome} esta numa classe e sem dados pessoais")
            if t.ligada and c.mecanismo not in MECANISMOS_EXECUTADOS:
                raise PoliticaInvalida(f"{t.nome}: ligada num mecanismo que o job nao corre")
            if t.ligada and c.mecanismo == FISCAL:
                raise PoliticaInvalida(f"{t.nome}: uma tabela fiscal nao se liga sem decisao")
            if not t.ligada and not t.pendencia:
                raise PoliticaInvalida(f"{t.nome}: por ligar sem dizer porque nem a quem")
    # A ausencia e do ensaio de catalogo (toda a tabela esta mapeada); aqui
    # recusa-se a presenca numa classe que purga. Uma politica reduzida, so com
    # as classes de um ensaio, nao as tem e nao as purga.
    for intocavel in ("platform.erasure_ledger", "platform.purge_log"):
        dona = tabelas_mapeadas(politica).get(intocavel)
        if dona is not None and classe_em(politica, dona).mecanismo != CONSERVAR:
            raise PoliticaInvalida(
                f"{intocavel} nao pode ser purgada: e o que impede um restauro de "
                "ressuscitar o que foi apagado"
            )


def classe_em(politica: Iterable[Classe], nome: str) -> Classe:
    for c in politica:
        if c.nome == nome:
            return c
    raise KeyError(nome)


def fiscal_retention_years(ambiente: Mapping[str, str] | None = None) -> int | None:
    """O prazo fiscal, ou `None`. **Sem omissao**, e `None` quer dizer recusar.

    Um valor que nao seja um inteiro entre 1 e 30 levanta: um prazo fiscal mal
    escrito que se lesse como nulo recusava em silencio, e um que se lesse como
    zero apagava tudo.
    """
    valor = (os.environ if ambiente is None else ambiente).get(VARIAVEL_FISCAL, "").strip()
    if not valor:
        return None
    if not valor.isdigit() or not 1 <= int(valor) <= 30:
        raise PoliticaInvalida(f"{VARIAVEL_FISCAL} tem de ser um inteiro entre 1 e 30")
    return int(valor)


def limite(
    c: Classe,
    agora: datetime,
    *,
    anos_fiscais: int | None = None,
    alargamento: Prazo | None = None,
) -> datetime | None:
    """O instante antes do qual a classe sai, ou `None` se a classe nao purga.

    `None` numa classe fiscal sem prazo e a recusa do criterio 4. O
    `alargamento` e o da PME (`conversas`), e nao passa do `maximo`.
    """
    if c.fiscal:
        return None if anos_fiscais is None else recuar_meses(agora, 12 * anos_fiscais)
    prazo = c.prazo
    if prazo is None:
        return None
    if alargamento is not None:
        if c.maximo is None or c.mecanismo != APAGAR:
            raise PoliticaInvalida(f"{c.nome}: nao admite alargamento")
        if alargamento.antes_de(agora) < c.maximo.antes_de(agora):
            raise PoliticaInvalida(f"{c.nome}: o alargamento passa do maximo")
        # Um «alargamento» mais curto do que o prazo encurtava-o: a PME pode
        # conservar mais tempo, e nao apagar mais cedo do que a politica.
        if alargamento.antes_de(agora) > prazo.antes_de(agora):
            raise PoliticaInvalida(f"{c.nome}: um alargamento nao encurta o prazo")
        prazo = alargamento
    return prazo.antes_de(agora)


__all__ = [
    "APAGAR",
    "CICLO_DO_REPOSITORIO",
    "CONSERVAR",
    "CONVERSAS_MAXIMO_DIAS",
    "DELEGADO",
    "ENCERRAMENTO",
    "ESTADO_PROPOSTA",
    "EXTERNO",
    "FISCAL",
    "LARGAR_PARTICAO",
    "MECANISMOS",
    "MECANISMOS_EXECUTADOS",
    "POLITICA",
    "SEM_DADOS_PESSOAIS",
    "TTL_STO",
    "VARIAVEL_FISCAL",
    "VERSAO_DA_POLITICA",
    "Classe",
    "PoliticaInvalida",
    "Prazo",
    "Tabela",
    "classe",
    "classe_em",
    "fiscal_retention_years",
    "limite",
    "recuar_meses",
    "tabelas_ligadas",
    "tabelas_mapeadas",
    "validar",
]
