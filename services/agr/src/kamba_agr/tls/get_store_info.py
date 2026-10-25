"""A `get_store_info`: a primeira tool real da ToolLayer (`docs/tecnica/02` §6.2).

É a tool que o bloco do KAM-028 nomeia («aqui entra o *framework* e
`get_store_info` como primeira tool real»), e e das onze do catalogo a unica que
nao precisa do COM, do PAY nem do IDX: o que ela devolve esta na
`platform.tenants` desde a revisao `0001`.

**Isso e deliberado e vale mais do que um *fake*.** Os *Detalhes Tecnicos* do
bloco autorizam «*fakes* para os backends ainda inexistentes», e um *fake* teria
provado o pipeline contra um duplo. Esta tool corre contra a base a serio, com a
RLS a serio e o `SET LOCAL app.tenant_id` a serio — que e o passo 6 do §6.1 e a
razao pela qual o critero 8 (X-02) se consegue medir neste ticket em vez de
ficar a espera do KAM-031.

## O que devolve, e o que o §6.2 pede e nao existe

O §6.2 escreve «Horario, morada, Plus Code». A `platform.tenants` tem
`fuso_horario`, `zona` e `plus_code`, e **nao tem coluna de morada** — e
`morada` e um dos sete nomes que o *lint* de PII do `docs/tecnica/08` §7.3
proibe. Devolvem-se as tres que ha, e a divergencia esta registada no dicionario
§3.27: acrescentar uma morada a `tenants` e decisao de quem a acrescentar, nao
deste ticket.

O `fuso_horario` nao e «o horario da loja» — e o fuso. O horario de abertura nao
esta no esquema em sitio nenhum, e inventar uma coluna para ele aqui era
inventar canon. Fica nomeado como o que falta, com o ticket que o traz: e
informacao de perfil de negocio, que e o KAM-041 (registo de comercio).

## Nao devolve *facts*, e isso nao e esquecimento

O ADR-007 manda que **numeros** venham de tools com `fact_id`, e o §6.2 da
*facts* ao `get_price_stock` (`price`, `stock`), ao `propose_cart` (`total`) e ao
`get_availability` (`datetime`). O que esta tool devolve e texto de
configuracao: um `plus_code` nao e um numero que o modelo possa citar errado por
um algarismo, e os quatro `kind` do §6.2 nao tem onde o por. Uma lista de
*facts* vazia aqui e a resposta certa; a lista enche-se com as tools que
devolvem numeros, que sao do KAM-031 e do KAM-035.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from kamba_core import tenant_guard

from .erros import NOT_FOUND
from .especificacoes import ErroDeBackend, Pedido, Resposta

#: A consulta. **Um `%s` so**, e e o `id` — o `tenant_id` do contexto nao entra
#: no predicado alem disto porque a chave de `tenants` **e** o `id` (dicionario
#: §3.2, emenda 1.2) e a politica `tenant_iso` dela e sobre `id` (revisao
#: `0002`). Logo a RLS ja filtra a linha, e o `WHERE id = %s` e defesa em
#: profundidade: sem contexto, zero linhas; com o contexto de outro tenant,
#: zero linhas.
#:
#: O `deleted_at IS NULL` esta aqui e nao na RLS: um tenant apagado continua a
#: ser o tenant do contexto, e o que se recusa e **responder por ele**.
#: O nome do tecto de tempo do lado do servidor. E o `statement_timeout` do
#: PostgreSQL, e esta numa constante porque um teste confronta o SQL que sai com
#: o tecto que a camada calculou.
VARIAVEL_DE_TECTO = "statement_timeout"

#: O SQLSTATE com que o PostgreSQL cancela uma consulta que passou do
#: `statement_timeout`: `57014`, `query_canceled`.
SQLSTATE_CANCELADA = "57014"


def _e_cancelamento(erro: Exception) -> bool:
    """Se a excepcao e um `query_canceled` do servidor.

    Le o SQLSTATE do corpo do erro do `pg8000`, que e um `dict` com a chave
    `C` — a mesma leitura que o `sqlstate()` de `db/tests/base.py` faz. Nao se
    olha para o **texto** da mensagem: e localizavel, e um teste que dependesse
    dele passava a depender da locale do servidor.
    """
    for argumento in getattr(erro, "args", ()):
        if isinstance(argumento, dict) and argumento.get("C") == SQLSTATE_CANCELADA:
            return True
    return False


SQL_INFORMACAO_DA_LOJA = """
SELECT nome, zona, plus_code, fuso_horario
  FROM platform.tenants
 WHERE id = %s
   AND deleted_at IS NULL
"""


# **Sem *docstring*, e isso e uma descoberta e nao arrumacao.** A *docstring* de
# um modelo Pydantic entra no `model_json_schema()` como `description`, e o
# esquema e **o que vai ao modelo de linguagem**. A primeira versao desta classe
# explicava aqui porque e que o `extra="forbid"` importa, e a frase mencionava
# `tenant_id` por extenso: o nome que o §6.1 diz que «o modelo nunca ve» ia no
# prompt, dentro da descricao da tool. Nao e um parametro — o critero 3 fala de
# parametros — mas ensinava ao modelo um nome que ele nao tem de conhecer, e e o
# teste `test_o_esquema_que_vai_ao_modelo_nao_tem_o_contexto` que o apanhou.
#
# A regra que fica: **o que se escreve numa classe de argumentos de tool, ou num
# `Field(description=…)`, e texto para o modelo.** A explicacao para quem le o
# codigo vive em comentario, que o esquema nao leva.
#
# E um modelo e nao um `None` porque o `extra="forbid"` e o que importa: sem ele,
# uma chamada com um argumento inventado era aceite e o argumento ignorado em
# silencio — pior do que ser recusada, porque o prompt que a produziu continuava
# a parecer valido.
class ArgumentosDeGetStoreInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")


def executar(pedido: Pedido) -> Resposta:
    """Le a informacao da loja do contexto, sob RLS.

    O `tenant_guard.tx` escreve o `app.tenant_id` e abre a transaccao; o
    `statement_timeout` e o tecto da classe `read` (2 s, §6.5) e e **do lado do
    servidor** — um tecto que so existisse no cliente deixava a consulta a
    correr na base depois de o turno desistir dela.
    """
    if pedido.ligacao is None:
        raise RuntimeError(
            "a `get_store_info` le a `platform.tenants` e precisa de ligacao. "
            "Uma especificacao de backend `plataforma` sem tomada e defeito de "
            "registo, nao resposta de negocio"
        )
    try:
        with tenant_guard.tx(pedido.ligacao, pedido.ctx.tenant_id) as cursor:
            cursor.execute(f"SET LOCAL {VARIAVEL_DE_TECTO} = {int(pedido.timeout_ms)}")
            cursor.execute(SQL_INFORMACAO_DA_LOJA, (pedido.ctx.tenant_id,))
            linha = cursor.fetchone()
    except Exception as erro:
        # **O tecto do servidor tem de voltar como `UPSTREAM_TIMEOUT`**, e sem
        # esta traducao voltava como `UPSTREAM_DOWN`: o `camada.py` so reconhece
        # `TimeoutError`, e o `pg8000` levanta `DatabaseError` com o SQLSTATE
        # `57014` (`query_canceled`). A diferenca nao e cosmetica — o §6.5 da aos
        # dois o mesmo tratamento no grafo, mas um painel que confunda «a base
        # esta em baixo» com «a consulta passou do tecto» manda olhar para o
        # sitio errado.
        if _e_cancelamento(erro):
            raise TimeoutError(
                f"a consulta passou do tecto de {pedido.timeout_ms} ms"
            ) from erro
        raise
    if linha is None:
        # Sem linha nao e «base vazia»: e o tenant do contexto a nao existir, a
        # estar apagado, ou o contexto a ser de outro. As tres dao a mesma
        # resposta ao grafo, e dizer qual delas foi era um oraculo sobre a
        # existencia de um tenant a quem perguntasse com o contexto errado.
        raise ErroDeBackend(NOT_FOUND, "a loja deste contexto nao existe ou esta apagada")
    nome, zona, plus_code, fuso_horario = linha
    return Resposta(
        data={
            "nome": nome,
            "zona": zona,
            "plus_code": plus_code,
            "fuso_horario": fuso_horario,
        }
    )
