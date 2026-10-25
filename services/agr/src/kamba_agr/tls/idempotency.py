"""A idempotencia das tools `write`/`money` por `cart_id` (KAM-029).

O passo 5 do pipeline do §6.1 tinha, desde o KAM-028, uma regra e um lugar
vazio: «uma tool `write` ou `money` **nunca corre sem chave**». Este modulo
preenche o lugar — deriva a chave do `docs/tecnica/02` §6.3, guarda-a em
`platform.tool_idempotency`, e devolve o resultado guardado com
`idempotent_replay=True` quando a mesma intencao volta.

## Duas chaves, duas perguntas, e nao e duplicacao

Ha **duas** chaves de idempotencia no caminho de uma invocacao, e confundi-las
era a forma mais barata de duplicar uma encomenda:

| Chave | De quem | Responde a |
|---|---|---|
| `Invocacao.idempotency_key` | do chamador (o grafo) | «este **turno** ja foi contado?» — vai ao `hook_de_tool` do passo 2, que escreve o `usage_ledger`, e a coluna `tool_audit.idempotency_key`. O KAM-025 usa `turn_id:seq` |
| `Invocacao.chave` (daqui) | derivada | «este **carrinho** ja foi comprado?» — e a chave de `tool_idempotency` |

**A chave do chamador nao pode servir para o carrinho**, e a razao e o criterio
8 deste ticket: um segundo toque com `wamid` novo e um **turno novo**, com
`turn_id` novo e portanto chave de turno nova. Se o carrinho se desduplicasse
pela chave do turno, esse segundo toque nao encontrava nada guardado e cobrava
outra vez — que e exactamente a encomenda a dobrar que este ticket existe para
fechar. A chave do carrinho nao tem turno dentro, de proposito.

Por isso a coluna `tool_audit.idempotency_key` continua a guardar a chave do
**chamador** e nao esta. O inventario de `db/tests/test_inventario.py` dizia o
contrario — «a chave do §6.3» — e e uma divergencia que este ticket resolve
escrevendo a razao, nao mudando a coluna: as duas linhas ficam ligadas pelo
`tool` e pelo `args_hash`, que sao os mesmos nas duas tabelas.

## A formula, e porque e que `|` nao e um separador

O §6.3 escreve `sha256(tenant_id | contact_id | tool | cart_id)`. O `|` ali
denota «concatenado com separacao», e nao o caractere: o `cart_id` e **opaco**
(e gerado pelo `propose_cart`, KAM-046), pelo que nenhum caractere e seguro
como separador. Com um separador literal, um `cart_id` que o contivesse tornava
a chave ambigua — `(a, b|c)` e `(a|b, c)` dao a mesma chave, e numa tool
`money` isso e uma encomenda de um cliente a responder pela de outro.

Escreve-se por isso com o **comprimento a prefixar** cada parte, que e
inequivoco sem supor nada sobre o conteudo. A propriedade que o criterio 6 pede
— independencia de telefone, BSUID e relogio — le-se da assinatura: as quatro
partes sao as quatro do §6.3 e nenhuma delas e tempo.

## Nao ha telefone nesta chave, e nao e so por nao o passarmos

A coluna `key` tem um `CHECK` de forma (`^[0-9a-f]{64}$`, revisao `0022`): um
telefone nao cabe la **por recusa da base**, qualquer que seja o chamador. O
criterio 6 pede «a coluna `key` nunca contem `+244`» e isto prova-o sem depender
de nenhum teste nosso estar certo (ADR-010).

## O protocolo, e os tres estados

`INSERT … ON CONFLICT DO NOTHING RETURNING` e o que serializa: quem inserir e
o dono e corre o backend; quem nao inserir le a linha que existe.

| O que a linha diz | O que se faz |
|---|---|
| `args_hash` diferente | `INTENT_REUSED_WITH_DIFFERENT_CONTENT`, **sem** chamar o backend (criterio 3) |
| `concluida` | devolve-se o `result` guardado, com `idempotent_replay=True` (criterio 1) |
| `falhada` | **retoma-se**: volta a `em_curso` por `UPDATE` condicional e corre-se o backend outra vez. Nao duplica o efeito porque o backend recebe a chave e e idempotente por ela — e o criterio 4 |
| `em_curso` | espera-se ate `TECTO_DE_ESPERA_MS`; se continuar `em_curso`, `UPSTREAM_TIMEOUT` **sem executar** (criterio 5) |

**A retoma e por `UPDATE` condicional e nao por leitura-e-escrita**, porque dois
leitores concorrentes de uma linha `falhada` liam os dois `falhada` e corriam os
dois o backend. O `WHERE estado = 'falhada'` deixa um so passar.

shortcut: uma linha que fique `em_curso` por morte do processo (um `SIGKILL`
entre o backend e o `fechar`) nunca se retoma, e o `cart_id` dela responde
`UPSTREAM_TIMEOUT` para sempre; o cliente sai pelo carrinho novo, que tem
`cart_id` novo. Fecha-se quando houver a reconciliacao do `docs/tecnica/03`
§10.3 (que retoma intencoes `em_curso` do COM) com dono nomeado para a TLS.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Final

from kamba_core import tenant_guard

from .contexto import ToolContext

#: O tecto de espera por uma linha `em_curso` de outro. E o `poll <= 3 s` do
#: `docs/tecnica/03` §6.3, citado pelo criterio 5 deste ticket.
TECTO_DE_ESPERA_MS: Final = 3_000

#: Quanto se dorme entre leituras, enquanto se espera. Nao e configuravel: o que
#: o criterio nomeia e o tecto, e este valor so decide quantas leituras cabem
#: dentro dele.
INTERVALO_DE_ESPERA_MS: Final = 50

#: Ao fim de quanto tempo uma linha `em_curso` se considera **abandonada** e se
#: retoma. E o ponto 4 do `docs/tecnica/03` §6.3, que escreve o mesmo para o COM:
#: «intencoes `em_curso` > 2 min sao retomadas ou marcadas `falhada`».
#:
#: **Sem isto havia um caminho que deixava um `cart_id` envenenado para sempre, e
#: com a encomenda ja feita.** Nao e o `SIGKILL` exotico: e o caminho que o
#: `except` do `_correr` existe para tratar — o backend corre, a ligacao cai, o
#: `fechar` levanta e e engolido ali de proposito. A linha ficava `em_curso`, a
#: varredura recusa apagar `em_curso` por idade (e bem: pode ser uma invocacao a
#: correr), e nada mais a tocava. Toda a repeticao daquele `cart_id` respondia
#: `UPSTREAM_TIMEOUT`; o cliente saia por um carrinho novo, que tem `cart_id`
#: novo, logo **chave nova** — e a segunda barreira do COM tambem nao o apanhava,
#: porque um carrinho novo e `draft_id` novo e portanto `intent_key` nova. **Duas
#: encomendas.** Achado 2 da revisao adversarial (`ANALISE-31`).
#:
#: **Dois minutos e nao oito segundos e meio**, que e o tecto da camada para uma
#: classe de escrita: o tecto diz quanto o dono pode demorar, e retomar por cima
#: de um dono vivo e exactamente o que duplica o efeito. A folga entre os dois e
#: a margem para um relogio desacertado entre o servidor e nos. A retoma e segura
#: porque o backend recebe a chave e e idempotente por ela — a mesma premissa do
#: criterio 4.
MINUTOS_PARA_RETOMAR: Final = 2

#: Os tres estados de uma linha. Lista **fechada**, e a mesma do `CHECK` da
#: revisao `0022`.
ESTADOS: Final = ("em_curso", "concluida", "falhada")

SQL_RESERVAR = """
  INSERT INTO platform.tool_idempotency (key, tenant_id, tool, args_hash)
  VALUES (%s, %s::uuid, %s, %s)
  ON CONFLICT (key) DO NOTHING
  RETURNING key
"""

SQL_LER = """
  SELECT estado, args_hash, result, created_at
  FROM platform.tool_idempotency
  WHERE key = %s
"""

#: O instante do **servidor**, para comparar com o `created_at` dele.
#:
#: Nao se usa o relogio do processo: o `created_at` e escrito pelo `DEFAULT
#: now()` do PostgreSQL, e comparar dois relogios diferentes punha a decisao de
#: retomar — que e a decisao de correr o backend outra vez — a depender de uma
#: deriva de NTP. O relogio simulado dos ensaios entra pelo `agora`, nao por
#: aqui.
SQL_AGORA = "SELECT now()"

#: A retoma de uma linha `falhada`. O `WHERE estado = 'falhada'` e o que faz
#: dela atomica: de dois leitores concorrentes, so um actualiza uma linha.
SQL_RETOMAR = """
  UPDATE platform.tool_idempotency
  SET estado = 'em_curso', result = NULL
  WHERE key = %s AND estado = 'falhada'
  RETURNING key
"""

#: A retoma de uma linha `em_curso` **abandonada**, por idade. Ver a nota do
#: `MINUTOS_PARA_RETOMAR`.
#:
#: O `created_at < %s` esta **dentro** do `UPDATE` e nao numa leitura anterior, e
#: e isso que a torna atomica: de dois leitores concorrentes de uma linha velha,
#: so um actualiza. E o `estado = 'em_curso'` no mesmo `WHERE` impede-a de tocar
#: uma linha que o dono acabou de fechar entre a leitura e esta instrucao.
#:
#: **Nao mexe no `created_at`**, de proposito: se a retoma o reescrevesse, uma
#: linha que fosse retomada e falhasse outra vez ganhava idade nova a cada volta
#: e a varredura de retencao nunca lhe chegava.
SQL_RETOMAR_ABANDONADA = """
  UPDATE platform.tool_idempotency
  SET estado = 'em_curso', result = NULL
  WHERE key = %s AND estado = 'em_curso' AND created_at < %s
  RETURNING key
"""

SQL_FECHAR = """
  UPDATE platform.tool_idempotency
  SET estado = %s, result = %s::jsonb
  WHERE key = %s
"""


def derivar(ctx: ToolContext, tool: str, referencia: str) -> str:
    """`sha256(tenant_id | contact_id | tool | cart_id)`, em hexadecimal.

    A `referencia` e o `cart_id` (Vendedor) ou o `hold_id` (Servicos) — o que o
    botao `confirm:{…}` cita e o passo 4 ja confrontou com os argumentos. E
    opaca: nao se interpreta, nao se valida pela forma, e **nao** se deriva de
    nada (o produtor e o `propose_cart`, KAM-046).

    Ver a nota do modulo sobre o comprimento a prefixar: o `|` do §6.3 nao e um
    caractere separador.
    """
    partes = (ctx.tenant_id, ctx.contact_id, tool, referencia)
    crua = b"".join(f"{len(p.encode('utf-8'))}:".encode("ascii") + p.encode("utf-8") for p in partes)
    return hashlib.sha256(crua).hexdigest()


@dataclass(frozen=True, slots=True)
class Reserva:
    """O desfecho de uma reserva. **Exactamente um** dos tres vale.

    O invariante esta aqui e nao no chamador pela razao do `ToolResult`: um
    desfecho com dois lados, ou com nenhum, e um desfecho ilegivel, e quem o
    constroi e que sabe qual queria.
    """

    #: Corremos o backend: a linha e nossa.
    dono: bool = False
    #: O `result` guardado de uma invocacao anterior (replay).
    guardado: dict[str, Any] | None = None
    #: Um dos codigos tipados do §6.5, quando se recusa sem executar.
    codigo: str | None = None

    def __post_init__(self) -> None:
        quantos = sum((self.dono, self.guardado is not None, self.codigo is not None))
        if quantos != 1:
            raise ValueError(
                "uma reserva e dono, ou replay, ou recusa — e exactamente uma das tres"
            )


def reservar(
    ligacao: Any,
    ctx: ToolContext,
    chave: str,
    tool: str,
    args_hash: bytes,
    *,
    tecto_ms: int = TECTO_DE_ESPERA_MS,
    relogio: Any = time.monotonic,
    dormir: Any = time.sleep,
) -> Reserva:
    """O protocolo do §6.3. Ver a tabela dos tres estados na nota do modulo.

    Cada ida a base e a sua **propria** transaccao, e nao e desperdicio: a linha
    `em_curso` tem de estar **confirmada** antes de o backend correr, senao
    nenhum leitor concorrente a ve e os dois executam. E a razao pela qual este
    passo nao pode correr dentro de uma transaccao de outro passo — o que o
    `tenant_guard` ja impoe por outro lado (`LigacaoEmUso`).

    O `relogio` e o `dormir` sao parametros para o relogio simulado dos ensaios;
    em producao sao os do `time`.
    """
    if _reservou(ligacao, ctx, chave, tool, args_hash):
        return Reserva(dono=True)

    limite = relogio() + tecto_ms / 1000
    while True:
        linha = _ler(ligacao, ctx, chave)
        if linha is not None:
            estado, guardado_hash, resultado, nascida_em = linha
            if bytes(guardado_hash) != args_hash:
                return Reserva(codigo="INTENT_REUSED_WITH_DIFFERENT_CONTENT")
            if estado == "em_curso" and _abandonada(ligacao, ctx, nascida_em):
                # Ninguem a vai fechar: o dono morreu, ou a ligacao dele caiu
                # entre o backend e o `fechar`. Retoma-se. Ver a nota do
                # `MINUTOS_PARA_RETOMAR`.
                if _retomou(ligacao, ctx, chave, nascida_em=nascida_em):
                    return Reserva(dono=True)
                # Outro retomou-a primeiro: volta a `em_curso` com dono vivo, e
                # espera-se por ele como por qualquer outro.
            if estado == "concluida":
                # O `jsonb` chega como dicionario ou como texto, conforme o
                # que o driver decida; aceitam-se os dois em vez de se supor um.
                if isinstance(resultado, str):
                    resultado = json.loads(resultado)
                return Reserva(guardado=resultado if resultado is not None else {})
            if estado == "falhada" and _retomou(ligacao, ctx, chave):
                return Reserva(dono=True)
            # `em_curso`, ou `falhada` que outro retomou primeiro: espera-se.
        elif _reservou(ligacao, ctx, chave, tool, args_hash):
            # A linha desapareceu entre o `ON CONFLICT` e esta leitura — so a
            # retencao apaga, e ela corre fora de qualquer pedido. Reservou-se
            # outra vez em vez de se inventar um desfecho.
            return Reserva(dono=True)

        # **O tecto fecha o ciclo inteiro e nao um ramo dele.** A primeira versao
        # so o media no ramo `em_curso` e os outros dois faziam `continue`: com
        # uma linha que nunca aparecesse, ou uma `falhada` que outro retomasse
        # sempre primeiro, isto girava para sempre — numa *thread* da camada, com
        # uma tomada presa. Apanhado a correr a bateria, que pendurou.
        if relogio() >= limite:
            return Reserva(codigo="UPSTREAM_TIMEOUT")
        dormir(INTERVALO_DE_ESPERA_MS / 1000)


def fechar(
    ligacao: Any, ctx: ToolContext, chave: str, *, ok: bool, resultado: Any
) -> None:
    """Fecha a linha que `reservar` nos deu: `concluida` com o resultado, ou
    `falhada`.

    Chama-se **sempre** que a reserva nos fez donos, inclusive quando o pipeline
    levantou — e a janela que a `ANALISE-30` (achado 12) deixou aberta: o backend
    de uma tool `money` corria, o registo falhava, o *job* voltava a fila, e a
    repeticao cobrava outra vez.

    Uma linha `falhada` **nao** guarda o resultado, e o `CHECK` da revisao `0022`
    impoe-o: um resultado guardado numa linha que se vai retomar era um resultado
    que a retoma devolvia como replay de uma invocacao que ninguem confirmou.
    """
    estado = "concluida" if ok else "falhada"
    carga = json.dumps(resultado, sort_keys=True, ensure_ascii=False) if ok else None
    with tenant_guard.tx(ligacao, ctx.tenant_id) as cursor:
        cursor.execute(SQL_FECHAR, (estado, carga, chave))


def _reservou(
    ligacao: Any, ctx: ToolContext, chave: str, tool: str, args_hash: bytes
) -> bool:
    with tenant_guard.tx(ligacao, ctx.tenant_id) as cursor:
        cursor.execute(SQL_RESERVAR, (chave, ctx.tenant_id, tool, args_hash))
        return cursor.fetchone() is not None


def _ler(ligacao: Any, ctx: ToolContext, chave: str) -> tuple[Any, ...] | None:
    with tenant_guard.tx(ligacao, ctx.tenant_id) as cursor:
        cursor.execute(SQL_LER, (chave,))
        return cursor.fetchone()


def _retomou(
    ligacao: Any, ctx: ToolContext, chave: str, *, nascida_em: Any = None
) -> bool:
    """Retoma uma linha `falhada`, ou uma `em_curso` abandonada por idade.

    As duas instrucoes tem a condicao **dentro** do `UPDATE`, e e isso que as
    torna atomicas: de dois leitores concorrentes da mesma linha, so um
    actualiza, e so esse corre o backend.
    """
    with tenant_guard.tx(ligacao, ctx.tenant_id) as cursor:
        if nascida_em is None:
            cursor.execute(SQL_RETOMAR, (chave,))
        else:
            cursor.execute(SQL_RETOMAR_ABANDONADA, (chave, _limite_de_abandono(cursor)))
        return cursor.fetchone() is not None


def _agora_do_servidor(cursor: Any) -> Any:
    cursor.execute(SQL_AGORA)
    return cursor.fetchone()[0]


def _limite_de_abandono(cursor: Any) -> Any:
    """`now()` do servidor menos `MINUTOS_PARA_RETOMAR`."""
    return _agora_do_servidor(cursor) - _dt.timedelta(minutes=MINUTOS_PARA_RETOMAR)


def _abandonada(ligacao: Any, ctx: ToolContext, nascida_em: Any) -> bool:
    """Se uma linha `em_curso` e velha o suficiente para ninguem a vir fechar."""
    if nascida_em is None:
        return False
    with tenant_guard.tx(ligacao, ctx.tenant_id) as cursor:
        return nascida_em < _limite_de_abandono(cursor)


# ------------------------------------------------------------------- retencao
#
# **A varredura vive aqui e nao no `retencao.py`, e nao e arrumacao.** O
# `lint_arch tool-schema` do KAM-028 recusa qualquer escrita no esquema
# `platform` em ficheiro de servico fora da `tls/` — e a ADR-015 esta certa: a
# TLS e a unica via de escrita. A varredura do `lg` (KAM-026) vive no
# `retencao.py` porque escreve no `lg`, que a regra nao cobre; esta apaga linhas
# do `platform`, e o `DELETE` dela ali era precisamente o que o *lint* existe
# para apanhar. **Apanhou**, a primeira vez que se correu a bateria.
#
# Posta aqui, a invariante le-se inteira: tudo o que escreve
# `platform.tool_idempotency` esta neste ficheiro, reservas e apagamentos.

#: Dias ao fim dos quais uma reserva **fechada** se apaga (criterio 7).
#: ***Proposta***, e o proprio criterio a declara como tal.
#:
#: O criterio pede «>= validade da reserva (72 h) + prazo de disputa». A
#: validade esta fixada — o `docs/tecnica/03` §6.4 poe o tecto da reserva de
#: stock em 72 h (CONFIRMADO para a referencia AppyPay, `evidencia/E2` §1.3) —
#: mas **o prazo de disputa nao esta fixado em documento nenhum**: o
#: `docs/tecnica/04` tem a transicao `paga -> reembolso_pendente: disputa` e a
#: tabela `refund_cases`, e nao da prazo. Procurado por varrimento, nao de
#: memoria.
#:
#: 30 dias e portanto *proposta* com a aritmetica a vista: 72 h de reserva mais
#: 27 dias de margem, que e o valor que a `events_dlq` da revisao `0005` usa
#: para a mesma classe de pergunta. **O que nao se faz e fixar aqui um prazo de
#: disputa**: quem o fixar no `04` recalibra esta constante, que e o sitio onde
#: se muda. Apagar antes do prazo apaga a prova de que a encomenda foi uma so.
DIAS_DE_RETENCAO: Final = 30

#: Apaga **so linhas fechadas**. Uma reserva `em_curso` nao se apaga por idade,
#: por mais velha que seja: pode ser de uma invocacao a correr — o tecto da
#: camada para `money` e de 8,5 s, mas daqui um `created_at` antigo e um relogio
#: desacertado nao se distinguem — e apagar a reserva de uma tool que ainda esta
#: no backend era abrir a janela que este modulo fecha.
SQL_APAGAR_RESERVAS_FECHADAS = """
  DELETE FROM platform.tool_idempotency
  WHERE created_at < %s AND estado IN ('concluida', 'falhada')
"""


def varrer(ligacao: Any, agora: Any, dias: int = DIAS_DE_RETENCAO) -> int:
    """Apaga as reservas fechadas com mais de `dias` e devolve quantas.

    Um numero basta, ao contrario do `retencao.varrer` do `lg`: ali o que se
    apaga e o estado de uma conversa e quem audita quer saber **qual**; aqui e
    uma marca de desduplicacao cuja identidade e um `sha256`. Registar as chaves
    apagadas era pôr num log a chave que a tabela existe para nao divulgar.

    Corre com a ligacao de quem chama — a do `kamba_batch`, o unico papel com
    `DELETE` nesta tabela (revisao `0022`) — e **sem contexto de tenant**: ele e
    `BYPASSRLS` e a varredura nao e de ninguem. Nao passa pelo `tenant_guard`
    por isso mesmo.

    **Nao ha agendador nesta fase**, como no KAM-026 e no KAM-017: quem a chama
    a horas e o KAM-071 (retencao global) com o KAM-079. Entrega-se o que apaga
    e prova-se com relogio simulado; agendar sem agendador era escrever um que
    ninguem pediu.
    """
    if dias < 0:
        raise ValueError("os dias de retencao nao podem ser negativos")
    limite = agora - _dt.timedelta(days=dias)
    cursor = ligacao.cursor()
    try:
        cursor.execute(SQL_APAGAR_RESERVAS_FECHADAS, (limite,))
        apagadas = cursor.rowcount
    finally:
        cursor.close()
    ligacao.commit()
    return apagadas
