"""A politica de «logs sem conteudo» (KAM-068, ADR-010, `docs/tecnica/08` §7.3).

Este ficheiro e a politica; `__init__.py` e quem escreve a linha. O espelho em
TypeScript e `packages/core-ts/src/logger/politica.ts`, e as duas implementacoes
tem de aceitar e recusar **as mesmas coisas**: a paridade confere-se com os
vectores de `packages/core-ts/tests/fixtures/logger_paridade.json`, lidos pelas
duas baterias, e com as 1 000 *fixtures* do X-11, cuja saida tem de ser igual
byte a byte nas duas linguagens (`make x11`).

**Nao ha redaccao parcial.** Um valor ou tem a forma fechada do seu campo, ou o
campo e retirado da linha. Nao existe campo de texto livre, pelo que nao existe
«texto com o telefone mascarado»: existe o campo, ou nao existe. A unica mascara
e `mascarar_referencia`, e o que ela devolve nao cabe em campo nenhum da
*allowlist* — ver `docs/logs.md` §6.

So depende da biblioteca padrao.
"""

from __future__ import annotations

import hashlib
import re

#: A *allowlist*, pela ordem em que os campos saem na linha. E **exactamente** a
#: de `docs/tecnica/08` §7.3; acrescentar um campo e um PR revisto pelo
#: Responsavel de Seguranca (`docs/logs.md` §5).
CAMPOS = (
    "ts",
    "level",
    "svc",
    "tenant_id",
    "contact_hmac_prefix",
    "turn_id",
    "msg_id",
    "wa_type",
    "latency_ms",
    "tool",
    "outcome",
    "error_code",
)

#: Campos que o *logger* preenche. Quem chama nao os pode dar.
CAMPOS_RESERVADOS = ("ts", "level", "svc")

#: Campos que quem chama pode dar.
CAMPOS_DE_CHAMADA = tuple(c for c in CAMPOS if c not in CAMPOS_RESERVADOS)

NIVEIS = ("debug", "info", "warn", "error")

#: Tecto de `latency_ms`: oito digitos (cerca de 27 horas). Um inteiro de nove
#: digitos comecado por 9 tem a forma de um telemovel angolano, e e por isso
#: que o tecto existe e nao e so um limite de sanidade.
LATENCIA_MAXIMA_MS = 99_999_999

#: Motivos de rejeicao. Sao o sufixo da metrica, e sao **fixos**: o nome do
#: campo recusado nunca entra na metrica, porque um dicionario espalhado em
#: argumentos (`**corpo_do_pedido`) traz conteudo nas chaves.
MOTIVO_DESCONHECIDO = "campo_desconhecido"
MOTIVO_RESERVADO = "campo_reservado"
MOTIVO_VALOR = "valor_invalido"
MOTIVO_MENSAGEM = "mensagem_livre"
MOTIVOS = (MOTIVO_DESCONHECIDO, MOTIVO_RESERVADO, MOTIVO_VALOR, MOTIVO_MENSAGEM)

#: Campos recusados; o sufixo e o motivo (`log_field_rejected_total:<motivo>`).
METRICA_REJEITADOS = "log_field_rejected_total"
#: Linhas que nao se conseguiram escrever no destino.
METRICA_ESCRITA_FALHADA = "log_write_failed_total"

#: Variavel de ambiente que liga o modo estrito (o «modo de teste» do ticket):
#: uma rejeicao levanta em vez de so contar. Nunca em `prod` — um *logger* que
#: levanta derruba o pedido que estava a registar.
VARIAVEL_ESTRITO = "KAMBA_LOG_ESTRITO"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_ID_OPACO = re.compile(r"m_[0-9a-f]{32}")
_HMAC_PREFIXO = re.compile(r"[0-9a-f]{8}")
_SVC = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")

# Um identificador nao e «letras, digitos e sublinhados em qualquer ordem»: isso
# e tambem a forma de um token e de um `provider_event_id`. E uma sequencia de
# **palavras** separadas por `_`, cada uma com letras e, no fim, ate tres
# digitos (`http_404`, `v2`, `sha256`); ou um numero ate seis digitos. Uma
# cadeia aleatoria com digitos pelo meio (`k3j9x2m1`) nao tem esta forma.
_PALAVRA = r"[a-z]+[0-9]{0,3}"
_NUMERO = r"[0-9]{1,6}"
_IDENTIFICADOR = re.compile(rf"{_PALAVRA}(?:_(?:{_PALAVRA}|{_NUMERO}))*")

# `error_code` admite tambem maiusculas (`CALLBACK_INVALIDO`), CamelCase
# (`TimeoutError`), o numero de um erro da Meta (`131049`) e o ponto — porque a
# ponte poe aqui o nome do *logger* de uma biblioteca (`uvicorn.error`).
_SEGMENTO = rf"(?:(?:[a-z]+|[A-Z]+|(?:[A-Z][a-z]+)+)[0-9]{{0,3}}|{_NUMERO})"
_CODIGO = re.compile(rf"_?{_SEGMENTO}(?:[_.]{{1,2}}{_SEGMENTO})*")

# O nome de uma classe vem do codigo e nao de quem chama, e os nomes reais tem
# digitos pelo meio (`OAuth2Error`, `ISO8601Error`). Fica a forma de
# identificador, com no maximo dois grupos de digitos de ate quatro cada.
_CLASSE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_GRUPO_DE_DIGITOS = re.compile(r"[0-9]+")
CLASSE_COMPRIMENTO_MAXIMO = 64
# So letras, com `_` ou `-` entre palavras, e **sem digitos**: e o que
# distingue `telefone` e `X-Signature` de um identificador de evento.
_NOME_LEGIVEL = re.compile(r"[A-Za-z]+(?:[_-][A-Za-z]+)*")
NOME_LEGIVEL_MAXIMO = 40
_BRANCOS = re.compile(r"[ \t\r\n]")
_SUBSTITUTO = re.compile("[\ud800-\udfff]")

# Todas as formas se aplicam com `fullmatch`, nunca com `match` e `$`: em Python
# o `$` aceita um salto de linha no fim, e um identificador seguido de um salto
# de linha passava — o que o `RegExp` do espelho em TypeScript recusa.

#: Um valor de texto leva no maximo seis digitos **no total**, estejam onde
#: estiverem. Sete ja recusam: apanha o telefone, o NIF, o IBAN e a referencia
#: de pagamento em qualquer arrumacao que caiba no alfabeto de um campo
#: (`923.456.789`, `923456__789`, `a923_b456_c789`), sem precisar de saber o
#: formato de nenhum deles — o do NIF nao esta definido em documento nenhum
#: (`docs/seguranca/lacunas.md`, Q-A). Os codigos de erro da Meta tem seis
#: digitos (`131049`) e passam. A primeira versao contava so digitos seguidos
#: com um separador entre eles, e a revisao adversarial passou-lhe um telefone
#: com dois (`docs/analises/ANALISE-11`, A5).
_DIGITO = re.compile(r"[0-9]")
DIGITOS_MAXIMOS = 6

#: Formas de segredo com prefixo publicado que cabem no alfabeto de um campo.
#: Token de acesso da Meta (`EAA…`) e JWT (`eyJ…`). O resto das formas do gate 9
#: leva `-` ou `.` em posicoes que os campos ja nao admitem.
_FORMA_DE_SEGREDO = re.compile(r"EAA[A-Za-z0-9]{16}|eyJ[A-Za-z0-9_]{8}")

COMPRIMENTO_MAXIMO = {
    "svc": 32,
    "wa_type": 32,
    "tool": 64,
    "outcome": 64,
    "error_code": 96,
}


def _sem_conteudo(texto: str) -> bool:
    """`True` se o texto nao tem digitos a mais nem forma de segredo."""
    if len(_DIGITO.findall(texto)) > DIGITOS_MAXIMOS:
        return False
    return not _FORMA_DE_SEGREDO.search(texto)


def _identificador(nome: str, valor: object, forma: re.Pattern[str]) -> str | None:
    if not type(valor) is str:
        return None
    if not 1 <= len(valor) <= COMPRIMENTO_MAXIMO[nome]:
        return None
    if not forma.fullmatch(valor) or not _sem_conteudo(valor):
        return None
    return valor


def _uuid(valor: object) -> str | None:
    if not type(valor) is str:
        return None
    minusculas = valor.lower()
    return minusculas if _UUID.fullmatch(minusculas) else None


def _referencia_de_mensagem(valor: object) -> str | None:
    """`turn_id` e `msg_id`: um UUID, ou o resultado de `id_opaco`.

    **Um `wamid` em claro e recusado.** `docs/tecnica/02` define
    `turn_id = wamid`, e o identificador de mensagem da Meta leva o numero do
    interlocutor codificado em base64 (INDICIO: observacao comum, sem fonte
    primaria no canon — `docs/logs.md` §2.1). Um varrimento por `9\\d{8}` nao o
    ve. Quem tem um `wamid` regista `id_opaco(wamid)`.
    """
    canonico = _uuid(valor)
    if canonico is not None:
        return canonico
    if type(valor) is str and _ID_OPACO.fullmatch(valor):
        return valor
    return None


def validar_svc(valor: object) -> str | None:
    """O nome do servico, ou `None` se nao tiver a forma de um."""
    return _identificador("svc", valor, _SVC)


def validar(nome: str, valor: object) -> str | int | None:
    """O valor na forma em que sai na linha, ou `None` se for recusado.

    Nunca chama `str()` nem `repr()` sobre o que recebe, e so aceita `str` e
    `int` **exactos** (`type(valor) is str`): uma subclasse pode redefinir
    `partition`, `__len__` ou as comparacoes, e a validacao passava a correr o
    codigo de quem chamou.
    """
    if nome == "tenant_id":
        return _uuid(valor)
    if nome == "contact_hmac_prefix":
        if type(valor) is str and _HMAC_PREFIXO.fullmatch(valor):
            return valor
        return None
    if nome in ("turn_id", "msg_id"):
        return _referencia_de_mensagem(valor)
    if nome in ("wa_type", "tool", "outcome"):
        return _identificador(nome, valor, _IDENTIFICADOR)
    if nome == "latency_ms":
        # `type(...) is int`, e nao `isinstance`: deixa de fora o `bool` e
        # qualquer subclasse que minta nas comparacoes.
        if type(valor) is int:
            if 0 <= valor <= LATENCIA_MAXIMA_MS:
                return valor
        return None
    if nome == "error_code":
        return _error_code(valor)
    return None


def _classe_valida(classe: object) -> bool:
    if not type(classe) is str or not 1 <= len(classe) <= CLASSE_COMPRIMENTO_MAXIMO:
        return False
    if not _CLASSE.fullmatch(classe) or not _sem_conteudo(classe):
        return False
    grupos = _GRUPO_DE_DIGITOS.findall(classe)
    return len(grupos) <= 2 and all(len(g) <= 4 for g in grupos)


def _error_code(valor: object) -> str | None:
    """`<codigo>` ou `<codigo>:<Classe>`, cada parte com a sua forma."""
    if not type(valor) is str:
        return None
    if not 1 <= len(valor) <= COMPRIMENTO_MAXIMO["error_code"]:
        return None
    codigo, separador, classe = valor.partition(":")
    if not _CODIGO.fullmatch(codigo) or not _sem_conteudo(codigo):
        return None
    if separador and not _classe_valida(classe):
        return None
    return valor


def codigo_com_classe(codigo: object, classe: object) -> object:
    """`<codigo>:<Classe>`, ou so o codigo se a classe nao tiver forma de nome.

    E assim que um erro se regista «por `error_code` e classe» sem haver campo
    para a classe: a *allowlist* e exacta e nao o tem.
    """
    if not type(codigo) is str:
        return codigo
    if _classe_valida(classe):
        return f"{codigo}:{classe}"
    return codigo


def nome_legivel(nome: object) -> str:
    """O nome de um campo recusado, para a mensagem do modo estrito.

    So se devolve o que e curto e feito de palavras: uma chave que nao o seja
    pode ser conteudo, e a mensagem de uma excepcao acaba num relatorio de
    testes.
    """
    if (
        type(nome) is str
        and len(nome) <= NOME_LEGIVEL_MAXIMO
        and _NOME_LEGIVEL.fullmatch(nome)
    ):
        return nome
    return "<nome ilegivel>"


def id_opaco(identificador: str) -> str:
    """Um identificador externo (um `wamid`, um `event_id`) em forma registavel.

    `m_` mais os primeiros 32 caracteres hexadecimais do SHA-256. Serve para
    **correlacionar** — quem tem o identificador recalcula o valor — e nao e um
    segredo. **Nunca** se lhe da um telefone, um NIF ou outra coisa enumeravel:
    um resumo sem chave de um espaco pequeno inverte-se por enumeracao (ADR-010).
    """
    if not type(identificador) is str or identificador == "":
        raise TypeError("id_opaco exige texto nao vazio")
    # Um substituto isolado nao tem UTF-8; o Node troca-o por U+FFFD, e aqui
    # faz-se o mesmo para as duas linguagens darem o mesmo resumo (e para um
    # identificador hostil nao levantar).
    limpo = _SUBSTITUTO.sub("\ufffd", identificador)
    resumo = hashlib.sha256(limpo.encode("utf-8")).hexdigest()
    return f"m_{resumo[:32]}"


#: Quantos caracteres do fim de uma referencia ficam visiveis.
REFERENCIA_VISIVEIS = 3
#: Abaixo deste comprimento a mascara e total: mostrar 3 de 5 e mostrar a maior
#: parte.
REFERENCIA_MINIMO = 8
_MASCARA = "***"


def mascarar_referencia(referencia: object) -> str:
    """Uma referencia de pagamento com so os ultimos 3 caracteres visiveis.

    A mascara tem comprimento fixo, para nao revelar o da referencia. O que nao
    e texto, ou e curto demais, sai todo mascarado.
    """
    if not type(referencia) is str:
        return _MASCARA
    compacta = _BRANCOS.sub("", referencia)
    if len(compacta) < REFERENCIA_MINIMO:
        return _MASCARA
    return _MASCARA + compacta[-REFERENCIA_VISIVEIS:]
