"""O registo em JSON-lines **sem campos de conteudo** (KAM-100).

O criterio de privacidade do ticket: «nenhum conteudo de mensagem armazenado (so
tipo de evento, ids, carimbos e contagens)». O DoD acrescenta: «nenhum conteudo
de conversa nem telefone em claro nos ficheiros de evidencia (ADR-010)».

Este modulo e as duas metades disso, e a segunda e a que importa.

## Primeira metade: uma *allowlist*, e nao uma lista de campos a apagar

Uma lista de campos a apagar e uma aposta em conhecer o formato de terceiros. A
Meta acrescenta campos sem avisar — o `referral`, o `location`, o `order` foram
todos acrescentos —, e cada acrescento entra no registo **por omissao**. Uma
*allowlist* erra para o outro lado: um campo novo e descartado, e o pior que
acontece e faltar uma contagem na tabela.

## Segunda metade: a forma do **valor**, e nao o nome da chave

Uma guarda que verifique nomes de campo fica verde com uma mensagem inteira
guardada num campo chamado `nota`, `ref` ou `fase`. E o modo de falha desta
classe de ensaio, e foi apanhado numa revisao adversarial de outro ticket.

Por isso cada entrada de `PERMITIDOS` nao diz so «esta chave passa»: diz a
**forma exacta** que o valor tem de ter, e um valor que nao casa a forma faz
`ConteudoRecusado` — nao e aparado nem truncado. As formas sao estreitas de
proposito:

    tipo         ^[a-z_]{1,32}$              um nome de campo de webhook
    numero       ^N[1-3]$                    o rotulo do spike, nunca o numero
    id           ^m_[0-9a-f]{32}$            `id_opaco`, nunca um `wamid`
    evento       ^[A-Z_]{1,40}$              uma enumeracao da Meta
    carimbo      int                         segundos Unix
    contagens    int >= 0

Nenhuma delas admite um espaco, e nenhuma admite 50 caracteres. Um texto livre
nao casa nenhuma.

## Os telefones nao se resumem: descartam-se

`docs/logs.md` §2.1 e o ADR-010 dizem porque: um resumo sem chave de um espaco
pequeno inverte-se por enumeracao, e um movel angolano tem nove digitos — 10^8
hipoteses uteis, que um portatil percorre em segundos. Logo um telefone **nao**
passa por `id_opaco`: sai do registo e no lugar dele fica o rotulo `N1`, `N2` ou
`N3`, cuja correspondencia vive **fora do repositorio**, na folha do operador.

O `wamid` passa por `id_opaco` porque e de alta entropia — mas repare-se que em
claro ele leva o numero do interlocutor em base64 (`docs/logs.md` §2.1,
`divida 51` de `docs/dividas-documentais.md`), e e por isso que o registo guarda
o resumo e nunca o valor.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

# O `id_opaco` canonico, e nao uma segunda copia dele: `m_` mais 32 hexadecimais
# do SHA-256 (`docs/logs.md` §2.1). Precisa de `libs/py-core/src` no
# PYTHONPATH — ver o README deste spike. A falta e um `ImportError` a cabeca, de
# proposito: um receptor que caia para ids em claro por nao ter encontrado a
# biblioteca e pior do que um receptor que nao arranca.
from kamba_core.logger import id_opaco


class ConteudoRecusado(ValueError):
    """Um valor nao casa a forma declarada para a sua chave.

    A mensagem **nao leva o valor**: se o valor for conteudo de uma conversa, a
    excepcao punha-o no registo da execucao, que e exactamente o sitio de onde
    este modulo o quer tirar. Leva a chave e o comprimento.
    """


class Forma:
    """A forma exacta que o valor de uma chave tem de ter."""

    def __init__(self, nome: str, aceita: Callable[[Any], bool], descricao: str):
        self.nome = nome
        self.aceita = aceita
        self.descricao = descricao


def _texto(padrao: str) -> Callable[[Any], bool]:
    """Texto que casa o padrao **por inteiro**.

    `fullmatch` e nao `search`: com `search`, `^[a-z_]+$` ainda casaria a
    primeira linha de um texto de varias linhas, e um `re.search` sem `$` casa
    um prefixo de qualquer coisa. E a diferenca entre medir a forma do valor e
    medir se o valor **contem** algo com aquela forma.
    """
    compilado = re.compile(padrao, re.DOTALL)
    return lambda v: type(v) is str and compilado.fullmatch(v) is not None


def _inteiro(minimo: int, maximo: int) -> Callable[[Any], bool]:
    # `type(v) is int` e nao `isinstance`: um `bool` e um `int` em Python, e
    # `True` passaria por uma contagem.
    return lambda v: type(v) is int and minimo <= v <= maximo


#: Um carimbo Unix plausivel: de 2020-01-01 a 2100. Um valor fora disto e outra
#: coisa disfarcada de carimbo.
CARIMBO = Forma("carimbo", _inteiro(1_577_836_800, 4_102_444_800), "segundos Unix")

#: Um codigo de erro da Meta. O `error_code` e o `error_subcode` partilham a
#: forma; o 2593109 vive aqui.
CODIGO_DE_ERRO = Forma("error_code", _inteiro(0, 99_999_999), "codigo de erro da Meta")

#: As chaves do registo, cada uma com a forma do seu valor. **E uma allowlist:**
#: uma chave que nao esteja aqui e descartada, e um valor que nao case a forma
#: faz `ConteudoRecusado`.
PERMITIDOS: Mapping[str, Forma] = {
    # O campo de webhook que trouxe o evento: `messages`, `history`,
    # `smb_app_state_sync`, `smb_message_echoes`, `account_update`.
    "tipo": Forma("tipo", _texto(r"[a-z_]{1,32}"), "nome de campo de webhook"),
    # O rotulo do numero no spike. **Nunca o numero.**
    "numero": Forma("numero", _texto(r"N[1-3]"), "rotulo N1, N2 ou N3"),
    # Instante em que o receptor recebeu o pedido, em UTC e com `Z`.
    "recebido_em": Forma(
        "recebido_em",
        _texto(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z"),
        "ISO-8601 em UTC",
    ),
    # O carimbo do proprio evento, em segundos Unix.
    "carimbo": CARIMBO,
    # `id_opaco(wamid)`. A forma e a do resumo, pelo que um `wamid.` em claro
    # **nao passa** — e esse e o ponto.
    "id": Forma("id", _texto(r"m_[0-9a-f]{32}"), "id_opaco"),
    "contexto_id": Forma("contexto_id", _texto(r"m_[0-9a-f]{32}"), "id_opaco"),
    # De onde veio: `entrada` (cliente), `saida` (nos, pela API) ou `echo` (o
    # dono, na app).
    "direccao": Forma("direccao", _texto(r"entrada|saida|echo"), "entrada, saida ou echo"),
    # Se o `wamid` deste echo esta no conjunto dos que **nos** enviamos pela
    # API. E a medicao do item NAO VERIFICADO de `docs/tecnica/01` §10.3.
    "enviada_por_nos": Forma(
        "enviada_por_nos", lambda v: type(v) is bool, "booleano"
    ),
    # Codigos de erro. O 2593109 — «o cliente nao partilhou historico» — vive
    # aqui, e e um dos dois casos que distinguem «medido» de «nao aconteceu».
    "error_code": CODIGO_DE_ERRO,
    "error_subcode": CODIGO_DE_ERRO,
    # Contagens. Nunca listas de valores: so quantos.
    "contactos": Forma("contactos", _inteiro(0, 10_000_000), "contagem"),
    "mensagens": Forma("mensagens", _inteiro(0, 10_000_000), "contagem"),
    "threads": Forma("threads", _inteiro(0, 10_000_000), "contagem"),
    "chunk_order": Forma("chunk_order", _inteiro(0, 1_000_000), "ordem do pedaco"),
    "progresso": Forma("progresso", _inteiro(0, 100), "percentagem"),
    # Enumeracoes da Meta: `PARTNER_REMOVED`, `PRIMARY_INACTIVITY`, a fase do
    # `history` (`initial_sync`...), o `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING`.
    "evento": Forma("evento", _texto(r"[A-Z_]{1,48}"), "enumeracao da Meta"),
    "razao": Forma("razao", _texto(r"[A-Z_]{1,48}"), "enumeracao da Meta"),
    # A `phase` do `history` e do `state_sync`. Admite digitos porque a Meta
    # manda-a como numero e o `extrair._fase` escreve `fase_0`, `fase_1`: a
    # primeira versao desta forma era `[a-z_]{1,32}` e **recusava a saida do
    # proprio extractor** — apanhado pelo ensaio do ficheiro escrito, nao por
    # leitura.
    "fase": Forma("fase", _texto(r"[a-z][a-z0-9_]{0,31}"), "fase da sincronizacao"),
}

#: As chaves de um corpo da Meta cujo valor e um `wamid` — vao por `id_opaco`.
CHAVES_DE_WAMID = ("id", "message_id", "context_id")

#: As chaves cujo valor e um telefone. **Descartam-se**: nao se resumem.
CHAVES_DE_TELEFONE = (
    "display_phone_number",
    "wa_id",
    "recipient_id",
    "from",
    "phone_number",
    "to",
)


def opaco(valor: str) -> str:
    """`id_opaco` do canon, com a guarda que o canon exige.

    `docs/logs.md` §2.1: «`id_opaco` **nunca** recebe um telefone, um NIF ou
    outra coisa enumeravel». A guarda esta aqui e nao no sitio de chamada porque
    uma guarda que se possa esquecer num sitio de chamada nao e uma guarda.
    """
    if re.fullmatch(r"\+?\d{6,15}", valor.replace(" ", "")):
        raise ConteudoRecusado(
            "recusado: id_opaco sobre um valor que e so digitos. Um espaco "
            "pequeno inverte-se por enumeracao (ADR-010, docs/logs.md §2.1); um "
            "telefone descarta-se, nao se resume"
        )
    return id_opaco(valor)


def validar(linha: Mapping[str, Any]) -> dict[str, Any]:
    """A linha, validada chave a chave contra `PERMITIDOS`.

    Uma chave desconhecida levanta — e nao e descartada em silencio. A diferenca
    importa: o descarte em silencio pertence a `extrair`, que le corpos de
    terceiros e nao os controla; aqui a linha foi construida por nos, e uma
    chave que nao esteja na *allowlist* e um defeito do construtor.
    """
    saida: dict[str, Any] = {}
    for chave, valor in linha.items():
        forma = PERMITIDOS.get(chave)
        if forma is None:
            raise ConteudoRecusado(
                f"recusado: a chave {chave!r} nao esta na allowlist do registo "
                f"(valor de {type(valor).__name__}, {len(str(valor))} caractere(s))"
            )
        if not forma.aceita(valor):
            raise ConteudoRecusado(
                f"recusado: {chave!r} tem de ser {forma.descricao}; chegou um "
                f"{type(valor).__name__} de {len(str(valor))} caractere(s)"
            )
        saida[chave] = valor
    return saida


def escrever(destino: Path, linha: Mapping[str, Any]) -> str:
    """Valida e acrescenta uma linha ao JSON-lines. Devolve a linha escrita.

    `ensure_ascii=False` **nao** se usa: a saida fica em ASCII puro, o que torna
    um varrimento por telefone ou por texto livre uma busca de texto simples.
    `sort_keys` para duas execucoes darem o mesmo ficheiro.
    """
    validada = validar(linha)
    texto = json.dumps(validada, sort_keys=True, separators=(",", ":"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    # `newline=""` para o ficheiro ficar com `\n` tambem no Windows: o JSON-lines
    # e lido por `tabela.py` e por quem o varra, e um `\r` a solta no fim de cada
    # linha e um caractere a mais dentro do ultimo valor.
    with destino.open("a", encoding="ascii", newline="") as f:
        f.write(texto + "\n")
    return texto
