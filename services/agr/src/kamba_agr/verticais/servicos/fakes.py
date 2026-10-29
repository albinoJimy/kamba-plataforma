"""O backend de ensaio da agenda — um *fake* por contrato das cinco tools.

## Onde isto corre, e onde nao corre

Corre na bateria e no *smoke* do *golden*. **Nao corre em producao, e nenhum
arranque importa este modulo**: o `catalogo_do_piloto()` mantem as cinco
entradas `declaradas`, e a razao esta escrita em `tls/servicos.py` — um executor
de ensaio registado no catalogo de producao devolvia *facts* `datetime` que
nenhuma agenda tem, e o validador de citacao **aceita-os**. Era confirmar a um
cliente uma marcacao que nao existe.

## «Por contrato» quer dizer o que

Cada *fake* satisfaz o contrato que o modulo `servicos` (KAM-047) ja satisfaz, e
nao menos:

* **devolve *facts*** `datetime` com `fact_id` **opaco** — nao derivado do
  argumento nem do valor (KAM-028: um `fact_id` derivado de texto do cliente poe
  texto do cliente na `tool_audit`);
* **e idempotente pela chave** no `book_slot`: o §6.3 ponto (iii) diz que «mesmo
  que ambos corram em concorrencia, a chave devolve o resultado guardado». E o
  que torna o criterio 5 mensuravel sem base de dados — e o limite esta escrito
  na seccao de verificacao do bloco: quem o serializa em producao e o `INSERT …
  ON CONFLICT DO NOTHING` da `tool_idempotency` (KAM-029) mais a restricao de
  exclusao da revisao `0025`, e aqui e um `dict`;
* **unicidade por `(contact, slot_id)`** (§6.2): um `slot_id` que outro contacto
  tenha ocupado devolve `SLOT_TAKEN`, e o **mesmo** contacto a repetir devolve a
  marcacao que ja tem. Sao dois casos diferentes e os dois estao no criterio 5;
* **`reschedule` atomico**: cancela e marca na **mesma** transacao, e a
  transacao e aqui um `copy` do estado que so se publica no fim. Uma falha
  injectada a meio deixa a marcacao original intacta — o criterio 7 por extenso.

## O catalogo de ensaio tem tres servicos, e os tres existem por uma razao

Um com preco `fixo`, um `a_partir_de` e um `sob_consulta` — os tres modos do
`03` §7.1, que o *renderer* do KAM-032 trata de tres maneiras. Um catalogo so
com precos fixos deixava o caminho do `sob_consulta` sem exercicio.

## A grelha de ensaio e de meia em meia hora, e isso e escolha de ensaio

Nao e desenho: a grelha real vem do `availability_rules` (KAM-047). Meia hora e
o que faz um dia dar **mais** do que dez intervalos, que e a unica forma de o
corte do criterio 4 ter o que cortar — com uma grelha de duas horas por dia
nunca havia uma decima primeira opcao para recusar.
"""

from __future__ import annotations

import copy
import datetime
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

from ...tls.erros import NOT_FOUND, VALIDATION_ERROR, Fact
from ...tls.especificacoes import ErroDeBackend, Pedido, Resposta
from . import datas
from .nos import HOLD_EXPIRED, SLOT_TAKEN

#: O instante dos *facts* de ensaio. Fixo para que uma bateria nao dependa do
#: relogio; quem precisar de o mover passa `retrieved_at` ao construir.
INSTANTE: Final = "2026-10-27T09:00:00Z"

#: Quanto tempo um *hold* de ensaio dura, em segundos. **Dez minutos**, que e o
#: `TTL_DO_HOLD_MS` do modulo `servicos` — e ***proposta***, como ele diz: o que
#: falta medir e o tempo entre a lista chegar ao cliente e o toque no botao.
TTL_DO_HOLD_S: Final = 10 * 60

#: A grelha de ensaio: de meia em meia hora, das 9h as 18h de Luanda. Ver o
#: cabecalho — o que importa e dar mais do que dez intervalos num dia.
PRIMEIRO_MINUTO: Final = 9 * 60
ULTIMO_MINUTO: Final = 18 * 60
PASSO_EM_MINUTOS: Final = 30


@dataclass(frozen=True, slots=True)
class Servico:
    """Uma linha do catalogo de ensaio."""

    service_id: str
    nome: str
    duracao_min: int
    preco_tipo: str
    preco_minor: int | None


#: Os tres servicos de ensaio. **Nenhum nome leva digitos**: a `Oferta` do
#: *renderer* recusa um nome com marca de moeda ou valor monetario, e um nome
#: terminado em digitos colava-se ao numero seguinte (ver o `_PRECO_NO_NOME`).
CATALOGO: Final = (
    Servico("srv-corte", "Corte de cabelo", 30, "fixo", 250_000),
    Servico("srv-coloracao", "Coloracao", 90, "a_partir_de", 800_000),
    Servico("srv-noiva", "Penteado de noiva", 120, "sob_consulta", None),
)


@dataclass
class AgendaFalsa:
    """A agenda de ensaio: servicos, *holds*, marcacoes e avarias injectaveis.

    **Nao e `frozen`**: as tools de escrita mudam-na, e e isso que a torna capaz
    de provar o duplo toque e a atomicidade. Um duplo imutavel media o nada.
    """

    catalogo: tuple[Servico, ...] = CATALOGO
    retrieved_at: str = INSTANTE
    #: O relogio desta agenda, em segundos desde a epoca. **O mesmo que as
    #: `Dependencias` recebem** — ver o `_agora`.
    relogio: Callable[[], float] = time.time
    #: O dia de Luanda que a grelha de ensaio oferece quando ninguem da
    #: intervalo.
    dia: str = "2026-11-16"
    #: O recurso que executa. **Um so, e a lacuna e declarada:** nao existe
    #: ligacao entre servico e recurso — nem no DDL do KAM-047, nem no
    #: `docs/tecnica/02` §8.3, nem no `00` §4 —, pelo que o `getAvailability`
    #: devolve horas de **todos** os recursos activos do tenant. Um duplo com
    #: dois recursos modelava a lacuna melhor; com um, modela o caso em que ela
    #: nao morde. E a divida **137**, e resolve-la e esquema novo: decisao do
    #: fundador. O `_unica_na_hora` do `nos.py` ja cai para o lado seguro
    #: quando duas opcoes batem a mesma hora.
    recurso: str = "rec-1"
    #: `hold_id` -> `{slot_id, contact_id, expira_at}`.
    holds: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: `booking_id` -> `{slot_id, contact_id, estado}`. O ambito do §6.2.
    marcacoes: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: `chave` de idempotencia -> `booking_id`. O §6.3 ponto (iii).
    por_chave: dict[str, str] = field(default_factory=dict)
    #: Codigos a levantar na proxima chamada de uma tool, para exercitar o §6.5.
    avarias: dict[str, list[str]] = field(default_factory=dict)
    #: Quantas chamadas cada tool levou. E o instrumento do criterio 5: «duplo
    #: toque produz **exactamente** 1 marcacao» mede-se contando marcacoes, e
    #: «sem repetir a tool» mede-se contando chamadas.
    chamadas: dict[str, int] = field(default_factory=dict)
    #: **A falha a meio da remarcacao** (criterio 7). Posto a `True`, o
    #: `reschedule_booking` rebenta **depois** de cancelar e **antes** de marcar,
    #: dentro da transacao — e e a transacao que tem de desfazer o cancelamento.
    falhar_a_meio_da_remarcacao: bool = False
    _contador: int = 0

    # ------------------------------------------------------------- utilitarios
    def _proximo(self, prefixo: str) -> str:
        self._contador += 1
        return f"{prefixo}{self._contador}"

    def _fact(self, kind: str, value: Any, sku: str | None = None) -> Fact:
        # O `fact_id` e **opaco**: um contador, e nao o `slot_id` nem a hora.
        return Fact(
            fact_id=self._proximo("f"),
            kind=kind,
            value=value,
            retrieved_at=self.retrieved_at,
            sku=sku,
        )

    def _contar(self, tool: str) -> None:
        self.chamadas[tool] = self.chamadas.get(tool, 0) + 1

    def _avaria(self, tool: str) -> None:
        """Levanta o codigo que o ensaio tenha posto na fila desta tool."""
        fila = self.avarias.get(tool) or []
        if fila:
            raise ErroDeBackend(fila.pop(0), f"avaria de ensaio em {tool}")

    def _servico(self, service_id: str) -> Servico:
        for servico in self.catalogo:
            if servico.service_id == service_id:
                return servico
        raise ErroDeBackend(NOT_FOUND, "service_id fora do catalogo")

    def _ocupados(self) -> set[str]:
        """Os `slot_id` que um *hold* ou uma marcacao activa ja tomam.

        E o predicado da restricao de exclusao da revisao `0025`: os estados
        `hold` e `confirmada` ocupam o intervalo, e os outros dois nao.
        """
        tomados = {h["slot_id"] for h in self.holds.values()}
        tomados |= {
            m["slot_id"]
            for m in self.marcacoes.values()
            if m["estado"] in ("hold", "confirmada")
        }
        return tomados

    def _grelha(self, service_id: str, dia: str) -> list[tuple[str, int]]:
        """Os `(slot_id, minuto_do_dia_de_luanda)` livres de um dia.

        O `slot_id` e deterministico no *fake* — `s:{service}:{dia}:{minutos}` —
        e isso **nao** contradiz «o `slot_id` e opaco»: opaco e o que quem o
        recebe nao deve interpretar, e ninguem fora deste modulo o interpreta. O
        que se ganha e uma bateria em que o mesmo pedido da o mesmo intervalo.
        """
        ocupados = self._ocupados()
        livres = []
        minuto = PRIMEIRO_MINUTO
        while minuto <= ULTIMO_MINUTO:
            slot_id = f"s:{service_id}:{dia}:{minuto}"
            if slot_id not in ocupados:
                livres.append((slot_id, minuto))
            minuto += PASSO_EM_MINUTOS
        return livres

    # ---------------------------------------------------------------- read
    def list_services(self, pedido: Pedido) -> Resposta:
        """Os servicos da loja, com um *fact* `price` por servico com preco.

        Um servico `sob_consulta` **nao** leva *fact* `price`, e nao e omissao: o
        `preco_display` do *renderer* escreve «preco sob consulta» sem numero
        nenhum, pelo que um *fact* ali era um numero que ninguem cita.
        """
        self._contar("list_services")
        self._avaria("list_services")
        facts: list[Fact] = []
        linhas = []
        for servico in self.catalogo:
            linhas.append(
                {
                    "service_id": servico.service_id,
                    "nome": servico.nome,
                    "preco_tipo": servico.preco_tipo,
                }
            )
            if servico.preco_minor is not None:
                facts.append(
                    self._fact("price", servico.preco_minor, sku=servico.service_id)
                )
        return Resposta(data={"servicos": tuple(linhas)}, facts=tuple(facts))

    def get_availability(self, pedido: Pedido) -> Resposta:
        """As opcoes livres, **no maximo dez**, cada uma com um *fact* `datetime`.

        ## O corte e aqui e tambem no no

        O `MAXIMO_DE_OPCOES` do modulo `servicos` corta no backend, e o
        `check_availability` corta no grafo. **As duas verificacoes olham para a
        mesma regra por dois lados**, e e de proposito: confiar so no backend era
        deixar o limite da Meta a depender de um componente que nao e nosso.

        ## O *hold* sai daqui quando o pedido estreita a um intervalo

        E a leitura ***proposta*** que a nota do `tls/servicos.py` escreve, e a
        hipotese devolvida ao fundador: um intervalo que cubra **um** passo da
        grelha devolve essa opcao com `hold_id` e `expira_at`, porque e o `hold`
        curto do §8.2. Um intervalo largo devolve opcoes **sem** `hold_id`, e
        nenhum recurso fica preso por uma pergunta.
        """
        self._contar("get_availability")
        self._avaria("get_availability")
        servico = self._servico(pedido.args.service_id)
        dia, de_minuto, ate_minuto = self._janela(pedido)

        livres = [
            (slot_id, minuto)
            for slot_id, minuto in self._grelha(servico.service_id, dia)
            if de_minuto <= minuto <= ate_minuto
        ]
        fora_do_intervalo = False
        if not livres:
            # «Sem disponibilidade responde com *fact* de indisponibilidade e
            # **alternativas**» (criterio 4): as alternativas sao o dia inteiro,
            # e quem diz ao cliente que sao doutra hora e o aviso que o no
            # escreve. Sem isto, o cliente recebia uma lista vazia e nada.
            livres = self._grelha(servico.service_id, dia)
            fora_do_intervalo = bool(livres)

        from .arestas import MAXIMO_DE_OPCOES

        opcoes = []
        facts: list[Fact] = []
        for slot_id, minuto in livres[:MAXIMO_DE_OPCOES]:
            inicio = datas.instante_utc(dia, minuto)
            fact = self._fact("datetime", inicio)
            facts.append(fact)
            # **Os campos sao os do `Opcao` do contrato, e nao mais.** O
            # `services/com/src/servicos/contrato.ts` da-lhe `slotId`,
            # `serviceId`, `resourceId`, `inicioAt` e `fimAt` — em
            # `snake_case` na fronteira da tool, que e a forma do §6.2. O
            # `fact_id` e o unico acrescento, e e nosso: e o que liga a opcao ao
            # *fact* `datetime` que esta resposta traz, sem o qual o `compose`
            # nao a pode citar (ADR-007).
            #
            # **Nao ha `minutos_em_luanda`**, e e de proposito: a primeira
            # versao deste duplo inventava-o e o `check_availability` lia-o —
            # isto e, o no estava escrito contra o *fake* e nao contra o
            # contrato. Quem o deriva do `inicio_at` e o `_minuto_em_luanda` do
            # `nos.py`. Apanhado pela nota do KAM-047 depois de o PR abrir.
            opcao: dict[str, Any] = {
                "slot_id": slot_id,
                "service_id": servico.service_id,
                "resource_id": self.recurso,
                "inicio_at": inicio,
                "fim_at": datas.instante_utc(dia, minuto + servico.duracao_min),
                "fact_id": fact.fact_id,
            }
            opcoes.append(opcao)

        if len(opcoes) == 1 and not fora_do_intervalo:
            # Um intervalo que estreita a **um** passo: toma-se o *hold*.
            unica = opcoes[0]
            hold_id = self._proximo("h")
            expira = self._agora(pedido) + TTL_DO_HOLD_S
            self.holds[hold_id] = {
                "slot_id": unica["slot_id"],
                "contact_id": pedido.ctx.contact_id,
                "expira_at": expira,
                "inicio_at": unica["inicio_at"],
            }
            unica["hold_id"] = hold_id
            # **ISO e nao epoca**, como o `Marcacao.holdExpiresAt` do contrato
            # (`string | null`). Devolver um `float` era o duplo a facilitar a
            # vida ao no: com a cadeia, o `float()` que ele fazia levantava.
            unica["hold_expires_at"] = (
                datetime.datetime.fromtimestamp(expira, tz=datetime.timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )

        return Resposta(
            data={"opcoes": tuple(opcoes), "fora_do_intervalo": fora_do_intervalo},
            facts=tuple(facts),
        )

    def _janela(self, pedido: Pedido) -> tuple[str, int, int]:
        """O dia de Luanda e os minutos que o `intervalo` pedido cobre.

        Sem intervalo, o dia de ensaio inteiro. **Converte-se para Luanda** e nao
        se usa o instante UTC cru: a grelha e em minutos do dia de Luanda, e
        comparar com minutos de UTC deslocava tudo uma hora — que e exactamente
        a armadilha que o `datas.py` descreve.
        """
        from ...validador.render import em_luanda

        de_at = getattr(pedido.args, "de_at", None)
        ate_at = getattr(pedido.args, "ate_at", None)
        if not de_at or not ate_at:
            return self.dia, 0, datas.MINUTOS_DO_DIA - 1
        inicio = em_luanda(de_at)
        fim = em_luanda(ate_at)
        return (
            inicio.date().isoformat(),
            inicio.hour * 60 + inicio.minute,
            fim.hour * 60 + fim.minute,
        )

    def _agora(self, _pedido: Pedido) -> float:
        """O instante do pedido, em segundos desde a epoca.

        **E o `relogio` desta agenda e nao o do sistema**, e isso nao e
        comodidade de ensaio: o `expira_at` de um *hold* e escrito **aqui** e
        comparado pelo `confirm_gate` contra o `deps.relogio`. Dois relogios
        diferentes davam um *hold* valido ou expirado **por acaso**, e um ensaio
        que avancasse o relogio simulado em onze minutos para provar o
        `HOLD_EXPIRED` media o relogio de parede — isto e, nao media nada. Quem
        monta a bateria passa o mesmo `relogio` as duas pontas.
        """
        return self.relogio()

    # --------------------------------------------------------------- write
    def book_slot(self, pedido: Pedido) -> Resposta:
        """Confirma um *hold*. **Idempotente pela chave e por `(contact, slot)`.**

        Tres recusas, e as tres estao no criterio 5 ou no 8:

        * `VALIDATION_ERROR` — o `hold_id` nao foi emitido por este backend;
        * `HOLD_EXPIRED` — o *hold* venceu antes de alguem o confirmar;
        * `SLOT_TAKEN` — o intervalo foi ocupado **por outro contacto** entre a
          oferta e o pedido.

        **O duplo toque do mesmo contacto nao e nenhuma das tres**: devolve a
        marcacao que ja existe, e a contagem de marcacoes nao sobe. E o que faz
        «exactamente 1 marcacao» ser uma medida e nao uma esperanca.
        """
        self._contar("book_slot")
        self._avaria("book_slot")

        # A chave primeiro: o §6.3 ponto (iii) diz que uma repeticao com a mesma
        # chave devolve o resultado guardado **sem** executar.
        if pedido.chave and pedido.chave in self.por_chave:
            return self._resposta_da_marcacao(self.por_chave[pedido.chave], replay=True)

        hold = self.holds.get(pedido.args.hold_id)
        if hold is None:
            # Pode ser um *hold* que **este** contacto ja confirmou: o duplo
            # toque com `wamid` novo tem chave de turno **nova**, pelo que nao
            # cai no `por_chave` acima. Procura-se a marcacao.
            ja = self._marcacao_do_hold(pedido.args.hold_id, pedido.ctx.contact_id)
            if ja is not None:
                return self._resposta_da_marcacao(ja, replay=True)
            raise ErroDeBackend(VALIDATION_ERROR, "hold_id nao emitido por este backend")

        if hold["contact_id"] != pedido.ctx.contact_id:
            # Um *hold* de outro contacto **nao** e `NOT_FOUND` nem um oraculo: e
            # `SLOT_TAKEN`, que e o que o cliente precisa de saber. Dizer «esse
            # hold nao e seu» era confirmar que ele existe.
            raise ErroDeBackend(SLOT_TAKEN, "o intervalo esta tomado")
        if hold["expira_at"] <= self._agora(pedido):
            del self.holds[pedido.args.hold_id]
            raise ErroDeBackend(HOLD_EXPIRED, "o hold venceu")
        if hold["slot_id"] in self._ocupados() - {hold["slot_id"]}:
            raise ErroDeBackend(SLOT_TAKEN, "o intervalo esta tomado")

        booking_id = self._proximo("b")
        self.marcacoes[booking_id] = {
            "slot_id": hold["slot_id"],
            "contact_id": pedido.ctx.contact_id,
            "estado": "confirmada",
            "hold_id": pedido.args.hold_id,
            # **O instante guarda-se, nao se deriva do `slot_id`.** O `slot_id`
            # real e um *token* assinado e opaco, e um duplo que o parta ensina
            # a interpreta-lo — que e exactamente o que o KAM-047 pede que nao
            # se faca. O modulo real le a coluna `inicio_at`; este le o campo.
            "inicio_at": hold.get("inicio_at"),
        }
        del self.holds[pedido.args.hold_id]
        if pedido.chave:
            self.por_chave[pedido.chave] = booking_id
        return self._resposta_da_marcacao(booking_id)

    def cancel_booking(self, pedido: Pedido) -> Resposta:
        """Cancela uma marcacao **do proprio contacto** (§6.2).

        Um `booking_id` de outro contacto da `NOT_FOUND` e nao uma recusa de
        permissao: e a metade do X-09 que vive na tool, e a mensagem de «nao e
        seu» era um oraculo sobre marcacoes alheias. E o mesmo que o
        `get_order_status` do Vendedor faz.
        """
        self._contar("cancel_booking")
        self._avaria("cancel_booking")
        marcacao = self._minha(pedido.args.booking_id, pedido.ctx.contact_id)
        marcacao["estado"] = "cancelada"
        return Resposta(
            data={"booking_id": pedido.args.booking_id, "estado": "cancelada"}
        )

    def reschedule_booking(self, pedido: Pedido) -> Resposta:
        """Cancela e marca **na mesma transacao** (criterio 7).

        ## A transacao e um `deepcopy` que so se publica no fim

        E o que torna a atomicidade mensuravel sem base de dados: as duas
        escritas fazem-se numa **copia** do estado, e a copia substitui o estado
        so quando as duas correm. Uma falha a meio — `falhar_a_meio_da_remarcacao`
        — rebenta antes da publicacao, e o estado que o ensaio ve a seguir e o de
        antes: a marcacao original **intacta** e no estado `confirmada`.

        Quem garante isto em producao e a transacao do `rescheduleBooking` do
        modulo `servicos` (KAM-047) com o `pg_advisory_xact_lock(hashtext(...))`
        da agenda do recurso. O limite deste duplo esta escrito na seccao de
        verificacao do bloco.
        """
        self._contar("reschedule_booking")
        self._avaria("reschedule_booking")
        self._minha(pedido.args.booking_id, pedido.ctx.contact_id)

        marcacoes = copy.deepcopy(self.marcacoes)
        holds = copy.deepcopy(self.holds)

        marcacoes[pedido.args.booking_id]["estado"] = "cancelada"

        if self.falhar_a_meio_da_remarcacao:
            # **Rebenta e nao devolve `ErroDeBackend`.** Uma falha de infra a
            # meio de uma transacao nao e um estado de negocio: o `invoke`
            # traduz qualquer outra excepcao em `UPSTREAM_DOWN`, que e o que o
            # criterio 8 manda mandar ao `handoff_prepare`. E nada se publica.
            raise RuntimeError("falha injectada a meio da remarcacao")

        novo = self._proximo("b")
        marcacoes[novo] = {
            "slot_id": pedido.args.slot_id,
            "contact_id": pedido.ctx.contact_id,
            "estado": "confirmada",
            "hold_id": None,
            # O modulo real le o `inicio_at` do *token* assinado; este duplo
            # nao o sabe para um `slot_id` que nao tenha passado por uma oferta,
            # e por isso deixa-o em `None` em vez de o adivinhar — com o efeito
            # de o `compose` nao citar instante nenhum, que e o lado certo de
            # errar (ADR-007: nao se cita o que nao veio de uma tool).
            "inicio_at": None,
        }
        # A publicacao: as duas escritas entram juntas.
        self.marcacoes = marcacoes
        self.holds = holds
        if pedido.chave:
            self.por_chave[pedido.chave] = novo
        return self._resposta_da_marcacao(novo)

    # ------------------------------------------------------------- internos
    def _minha(self, booking_id: str, contact_id: str) -> dict[str, Any]:
        marcacao = self.marcacoes.get(booking_id)
        if marcacao is None or marcacao["contact_id"] != contact_id:
            raise ErroDeBackend(NOT_FOUND, "marcacao fora do ambito do contacto")
        return marcacao

    def _marcacao_do_hold(self, hold_id: str, contact_id: str) -> str | None:
        for booking_id, marcacao in self.marcacoes.items():
            if (
                marcacao.get("hold_id") == hold_id
                and marcacao["contact_id"] == contact_id
            ):
                return booking_id
        return None

    def _resposta_da_marcacao(self, booking_id: str, replay: bool = False) -> Resposta:
        """A marcacao, **com o *fact* `datetime` do instante marcado**.

        O *fact* nao e decoracao: sem ele o turno da confirmacao nao tinha dia
        nem hora para citar, e o cliente ouvia «a sua marcacao ficou registada»
        e mais nada — medido pela revisao adversarial (`ANALISE-40`, achado 13).
        O ADR-007 nao deixa escrever o instante em prosa, pelo que a unica forma
        de o dizer e esta.

        **O instante deriva-se do `slot_id` e nao se inventa.** O `slot_id` do
        *fake* e `s:{service}:{dia}:{minutos}`, e o modulo real le a coluna
        `inicio_at`; nos dois casos quem sabe o instante e quem emitiu o
        intervalo. Um `slot_id` de outra forma devolve a marcacao **sem** *fact*,
        e o `compose` nao cita nada — e o lado certo de errar.
        """
        marcacao = self.marcacoes[booking_id]
        facts: tuple[Fact, ...] = ()
        inicio = marcacao.get("inicio_at")
        if isinstance(inicio, str) and inicio:
            facts = (self._fact("datetime", inicio),)
        return Resposta(
            data={
                "booking_id": booking_id,
                "slot_id": marcacao["slot_id"],
                "estado": marcacao["estado"],
                "idempotent_replay": replay,
            },
            facts=facts,
        )


def executores_de_ensaio(agenda: AgendaFalsa) -> dict[str, Any]:
    """Os cinco executores que o `especificacoes_de_servicos` pede.

    E uma funcao e nao um `dict` de modulo: um `dict` de modulo ligava **uma**
    agenda a todos os ensaios, e dois ensaios a partilhar marcacoes e a classe
    de defeito que uma bateria nunca explica.
    """
    return {
        "list_services": agenda.list_services,
        "get_availability": agenda.get_availability,
        "book_slot": agenda.book_slot,
        "cancel_booking": agenda.cancel_booking,
        "reschedule_booking": agenda.reschedule_booking,
    }


#: Os codigos que um ensaio pode pôr em `avarias`. **Nao e a lista dos treze**: e
#: a dos que um backend de agenda pode devolver. Um `TENANT_MISMATCH` nao vem do
#: backend — vem do passo 2 do `invoke`, e quem o exercita e a bateria da
#: ToolLayer.
AVARIAS_POSSIVEIS: Final = (NOT_FOUND, SLOT_TAKEN, HOLD_EXPIRED, VALIDATION_ERROR)
