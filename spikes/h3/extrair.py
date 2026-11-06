"""Do corpo da Meta para as linhas do registo (KAM-100).

Este modulo e a fronteira: le corpos que nao controlamos e devolve **so** o que
`registo.PERMITIDOS` admite. Tudo o que nao reconhece e **descartado em
silencio**, e e a unica parte do spike onde o silencio e a resposta certa — a
Meta acrescenta campos sem avisar, e um campo novo nao pode entrar no ficheiro
de evidencia por omissao.

## As formas dos corpos nao foram inventadas aqui

Vem de `tools/meta-sim/src/campos.ts`, que e o registo deste repositorio sobre
os onze campos de `docs/tecnica/01` §4.4, e **herdam-se os estados que ele
declara** em vez de os promover:

| O que | Estado, como `campos.ts` o declara |
|---|---|
| Os onze campos de webhook e os seis motivos de `PARTNER_REMOVED` | CONFIRMADO (`docs/tecnica/01` §4.4) |
| `X-Hub-Signature-256` sobre o corpo bruto | CONFIRMADO (`E1` §5) |
| O erro 2593109 = «o cliente nao partilhou historico» | CONFIRMADO (`E1` §2) |
| O nome do array dentro de `smb_message_echoes` (`message_echoes`) | **proposta** — nenhuma pagina primaria lida o diz |
| A forma interna de `history` e de `smb_app_state_sync` | **INDICIO** — as paginas nomeiam os campos e os motivos, nao a estrutura do `value` |

Por isso o extractor **nao exige** nenhuma destas estruturas: cada acesso e
tolerante, e um corpo que nao tenha o sub-objecto esperado produz uma linha com
menos campos em vez de uma excepcao. Uma excepcao aqui faria o spike perder o
evento que viesse numa forma ligeiramente diferente — que e precisamente o que
ha para medir.

## Os telefones nao chegam a sair daqui

Nenhum ramo abaixo le `display_phone_number`, `wa_id`, `from`, `to`,
`recipient_id` nem `phone_number` para dentro de uma linha. O unico uso de
`metadata.phone_number_id` e consultar o mapa de rotulos, que vive **fora do
repositorio**; um `phone_number_id` sem rotulo faz a linha sair sem `numero`, e
nao com o identificador em claro.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from registo import opaco

#: O nome do array dentro de `smb_message_echoes`. **Proposta**, como
#: `ARRAY_DOS_ECHOES` de `packages/core-ts/src/entrada/explosao.ts` o declara: o
#: `E1` §5 nao o nomeia. Fica numa constante para que o dia em que o KAM-017 o
#: fixar mude um sitio.
ARRAY_DOS_ECHOES = "message_echoes"

#: O campo que traz mensagens e estados no mesmo `value`
#: (`packages/core-ts/src/entrada/contrato.ts`).
CAMPO_DAS_MENSAGENS = "messages"

#: Os cinco campos que este spike subscreve, pelo bloco do KAM-100. Os outros
#: seis de `docs/tecnica/01` §4.4 chegam ao mesmo endpoint e sao descartados: o
#: spike mede coexistencia, nao qualidade de templates.
CAMPOS_SUBSCRITOS = (
    CAMPO_DAS_MENSAGENS,
    "history",
    "smb_app_state_sync",
    "smb_message_echoes",
    "account_update",
)


def _dicionarios(valor: Any) -> list[Mapping[str, Any]]:
    """Os elementos de `valor` que sao dicionarios, ou lista vazia.

    Tolerante de proposito: um `null`, um escalar ou uma lista de escalares onde
    se esperava uma lista de objectos devolve vazio em vez de levantar.
    """
    if not isinstance(valor, list):
        return []
    return [e for e in valor if isinstance(e, Mapping)]


def _inteiro(valor: Any) -> int | None:
    """Um inteiro, aceitando a forma em texto que a Meta usa nos carimbos.

    Os `timestamp` chegam como cadeias (`"1790812800"`), e os `phase`,
    `chunk_order` e `progress` como numeros. Um `bool` **nao** e um inteiro
    aqui: `type(valor) is int` recusa-o, senao um `true` entrava como `1` numa
    contagem.
    """
    if type(valor) is int:
        return valor
    if type(valor) is str and valor.isdigit():
        return int(valor)
    return None


def _com(linha: dict[str, Any], chave: str, valor: Any) -> None:
    """Poe `chave` na linha se `valor` nao for `None`.

    Uma chave com `None` falhava a forma em `registo.validar`, e com razao: o
    JSON-lines nao leva `null` nenhum, porque um `null` num ficheiro de
    evidencia nao distingue «nao veio» de «veio vazio».
    """
    if valor is not None:
        linha[chave] = valor


def _base(tipo: str, recebido_em: str, numero: str | None) -> dict[str, Any]:
    linha: dict[str, Any] = {"tipo": tipo, "recebido_em": recebido_em}
    _com(linha, "numero", numero)
    return linha


def _de_mensagens(
    valor: Mapping[str, Any], recebido_em: str, numero: str | None
) -> list[dict[str, Any]]:
    """Uma linha por mensagem de entrada. Os `statuses` nao entram.

    Os estados de entrega sao do KAM-017 e nao medem nada de H3; incluir-los
    enchia o ficheiro com linhas que a tabela N1-N3 nao le.
    """
    saida: list[dict[str, Any]] = []
    for m in _dicionarios(valor.get(CAMPO_DAS_MENSAGENS)):
        linha = _base(CAMPO_DAS_MENSAGENS, recebido_em, numero)
        linha["direccao"] = "entrada"
        _com(linha, "carimbo", _inteiro(m.get("timestamp")))
        ident = m.get("id")
        if type(ident) is str and ident:
            linha["id"] = opaco(ident)
        contexto = m.get("context")
        if isinstance(contexto, Mapping):
            pai = contexto.get("id")
            if type(pai) is str and pai:
                linha["contexto_id"] = opaco(pai)
        saida.append(linha)
    return saida


def _de_echoes(
    valor: Mapping[str, Any],
    recebido_em: str,
    numero: str | None,
    nossos: frozenset[str],
) -> list[dict[str, Any]]:
    """Uma linha por eco, com a medicao que o `01` §10.3 deixou NAO VERIFICADA.

    `enviada_por_nos` responde «uma mensagem enviada pela API gera eco?». O
    criterio e o mesmo do Outbound real: o `wamid` do eco esta, ou nao esta, no
    conjunto dos que **nos** enviamos (`docs/tecnica/01` §10.2, a transicao
    `bot -> dono`).

    **O conjunto compara-se com o `wamid` em claro e nunca o guarda**: entra na
    linha o `id_opaco`, e o booleano e o que fica do confronto.
    """
    saida: list[dict[str, Any]] = []
    for e in _dicionarios(valor.get(ARRAY_DOS_ECHOES)):
        linha = _base("smb_message_echoes", recebido_em, numero)
        linha["direccao"] = "echo"
        _com(linha, "carimbo", _inteiro(e.get("timestamp")))
        ident = e.get("id")
        if type(ident) is str and ident:
            linha["id"] = opaco(ident)
            linha["enviada_por_nos"] = ident in nossos
        saida.append(linha)
    return saida


def _de_history(
    valor: Mapping[str, Any], recebido_em: str, numero: str | None
) -> list[dict[str, Any]]:
    """Uma linha por pedaco de historico: contagens, fase e o 2593109.

    Conta `threads` e soma as `messages` de cada uma — **conta, nao copia**. O
    `errors[]` traz o 2593109 («o cliente nao partilhou historico»), que o
    limiar H3 trata como exito so se o dono tiver recusado partilhar, e por isso
    tem de aparecer no ficheiro em vez de se perder como «nao aconteceu».
    """
    saida: list[dict[str, Any]] = []
    for pedaco in _dicionarios(valor.get("history")):
        linha = _base("history", recebido_em, numero)
        meta = pedaco.get("metadata")
        if isinstance(meta, Mapping):
            _com(linha, "fase", _fase(meta.get("phase")))
            _com(linha, "chunk_order", _inteiro(meta.get("chunk_order")))
            _com(linha, "progresso", _inteiro(meta.get("progress")))
        threads = _dicionarios(pedaco.get("threads"))
        linha["threads"] = len(threads)
        linha["mensagens"] = sum(len(_dicionarios(t.get("messages"))) for t in threads)
        for erro in _dicionarios(pedaco.get("errors")):
            codigo = _inteiro(erro.get("code"))
            if codigo is not None:
                linha["error_code"] = codigo
            subcodigo = _inteiro(erro.get("error_subcode"))
            if subcodigo is not None:
                linha["error_subcode"] = subcodigo
        saida.append(linha)
    return saida


def _fase(valor: Any) -> str | None:
    """A `phase` do `history` como texto, que e a forma que o registo admite.

    A Meta manda-a como numero (`campos.ts`: `phase: 0`). `fase` no registo e
    `^[a-z_]{1,32}$`, pelo que um numero entrava como `0` e falhava a forma — e
    falhar a forma e o comportamento certo. Converte-se aqui, no sitio que sabe
    o que o numero quer dizer, e nao se relaxa a forma do registo.
    """
    numero = _inteiro(valor)
    if numero is None:
        if type(valor) is str and valor.islower() and valor.replace("_", "").isalpha():
            return valor
        return None
    return f"fase_{numero}"


def _de_state_sync(
    valor: Mapping[str, Any], recebido_em: str, numero: str | None
) -> list[dict[str, Any]]:
    """Uma linha com a **contagem** de contactos sincronizados.

    O criterio pede «n.o de contactos em `smb_app_state_sync`». Cada elemento de
    `state_sync` traz um `contact` com `full_name` e `phone_number`: nome e
    telefone de uma pessoa real. Nenhum dos dois e lido — conta-se quantos
    elementos ha, e e a contagem que entra.
    """
    elementos = _dicionarios(valor.get("state_sync"))
    if not elementos:
        return []
    linha = _base("smb_app_state_sync", recebido_em, numero)
    linha["contactos"] = sum(
        1 for e in elementos if isinstance(e.get("contact"), Mapping)
    )
    for e in elementos:
        meta = e.get("metadata")
        if isinstance(meta, Mapping):
            fase = _fase(meta.get("phase"))
            if fase is not None:
                linha["fase"] = fase
                break
    return [linha]


def _de_account_update(
    valor: Mapping[str, Any], recebido_em: str, numero: str | None
) -> list[dict[str, Any]]:
    """O `event` e o motivo da remocao, que sao enumeracoes e nao conteudo.

    O `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` do criterio 2 chega por aqui, e
    o `PARTNER_REMOVED` com um dos seis motivos de `docs/tecnica/01` §4.4.
    """
    linha = _base("account_update", recebido_em, numero)
    evento = valor.get("event")
    if type(evento) is str and evento:
        linha["evento"] = evento
    info = valor.get("partner_removed_info")
    if isinstance(info, Mapping):
        razao = info.get("reason")
        if type(razao) is str and razao:
            linha["razao"] = razao
    return [linha]


def extrair(
    corpo: Mapping[str, Any],
    rotulos: Mapping[str, str],
    nossos: Iterable[str] = (),
    recebido_em: str = "",
) -> list[dict[str, Any]]:
    """As linhas de registo de um corpo de webhook. Tudo o que nao reconhece cai.

    `rotulos` mapeia `phone_number_id` em `N1`, `N2` ou `N3`, e vive fora do
    repositorio. `nossos` sao os `wamid` que enviamos pela API, para o
    `enviada_por_nos` dos ecos.
    """
    conjunto = frozenset(nossos)
    saida: list[dict[str, Any]] = []
    for entrada in _dicionarios(corpo.get("entry")):
        for mudanca in _dicionarios(entrada.get("changes")):
            campo = mudanca.get("field")
            if campo not in CAMPOS_SUBSCRITOS:
                continue
            valor = mudanca.get("value")
            if not isinstance(valor, Mapping):
                continue
            meta = valor.get("metadata")
            canal = meta.get("phone_number_id") if isinstance(meta, Mapping) else None
            numero = rotulos.get(canal) if type(canal) is str else None
            if campo == CAMPO_DAS_MENSAGENS:
                saida.extend(_de_mensagens(valor, recebido_em, numero))
            elif campo == "smb_message_echoes":
                saida.extend(_de_echoes(valor, recebido_em, numero, conjunto))
            elif campo == "history":
                saida.extend(_de_history(valor, recebido_em, numero))
            elif campo == "smb_app_state_sync":
                saida.extend(_de_state_sync(valor, recebido_em, numero))
            elif campo == "account_update":
                saida.extend(_de_account_update(valor, recebido_em, numero))
    return saida
