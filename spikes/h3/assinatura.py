"""Validacao do `X-Hub-Signature-256` sobre o corpo **bruto** (KAM-100).

E1 §5 diz, de fonte primaria: `X-Hub-Signature-256: sha256=<HMAC-SHA256 do corpo
bruto com o App Secret>`; validar e responder 200, senao 4xx. A palavra que faz
o trabalho e **bruto**, e este modulo existe para que ela seja verificavel.

## Porque e que re-serializar e um *fail-open*, e nao um detalhe de estilo

A tentacao e `hmac(json.dumps(json.loads(corpo)))`. Parece equivalente e nao e,
por uma razao que nao depende de nenhuma fragilidade do JSON:

    uma assinatura passa a autenticar uma **familia** de cadeias de bytes, e
    nao a cadeia que chegou.

Quem capture um `(corpo, assinatura)` legitimo pode reordenar chaves, mudar
espacos, trocar `\\u00e1` por `a` acentuado, duplicar uma chave ou acrescentar
lixo que o descodificador tolere, e a assinatura **continua a validar** — porque
a arvore nao mudou. O receptor passa a aceitar bytes que a Meta nunca assinou. E
silencioso: nao ha erro, nao ha registo, o 200 sai igual.

Por isso a funcao abaixo recebe `bytes` e **nao tem** caminho que aceite um
objecto ja descodificado. Nao e uma convencao: `verificar` com um `str` levanta,
e o ensaio `test_recusa_str` prende-o. Quem quiser passar uma arvore tem de a
serializar primeiro, e ai a escolha dos bytes e dele e esta a vista.

## A ordem tambem e o produto

`json.loads` so corre **depois** de a assinatura validar, e essa ordem e um
ensaio (`test_corpo_invalido_mas_assinado_valida`): um corpo correctamente
assinado que nao seja JSON valido tem de passar a verificacao e falhar depois, no
descodificador. Um receptor que descodifique primeiro gasta o descodificador em
bytes de qualquer pessoa — e e o descodificador a superficie de ataque maior.

## O segredo nao vive aqui

O App Secret vem do ambiente (`KAMBA_H3_APP_SECRET`) e **nunca** do repositorio,
que e publico. Sem ele o receptor recusa arrancar: um receptor que valide com um
segredo vazio aceita o que um atacante assinar com um segredo vazio.
"""

from __future__ import annotations

import hashlib
import hmac
import os

#: O prefixo que a Meta poe no cabecalho. Fica nomeado porque a comparacao e
#: sobre o valor **depois** dele, e um prefixo diferente e um cabecalho de outra
#: coisa — nao um erro de digitacao a tolerar.
PREFIXO = "sha256="

#: O nome do cabecalho, na forma em que a Meta o envia.
CABECALHO = "X-Hub-Signature-256"

#: A variavel de ambiente onde o App Secret vive. Nunca um ficheiro do
#: repositorio: `docs/tecnica/08` §5 e o DoD deste ticket.
VARIAVEL_DO_SEGREDO = "KAMBA_H3_APP_SECRET"


class SegredoEmFalta(RuntimeError):
    """Nao ha App Secret no ambiente, logo nao se pode verificar nada."""


class AssinaturaInvalida(ValueError):
    """O cabecalho nao corresponde ao corpo bruto que chegou.

    A mensagem **nao leva** a assinatura esperada nem o corpo: um erro vai para o
    registo da execucao, e imprimir o HMAC esperado da a quem o leia metade do
    trabalho de forjar o proximo. Leva so o motivo.
    """


def segredo() -> bytes:
    """O App Secret do ambiente, em bytes.

    Levanta se nao existir ou estiver vazio. A alternativa — devolver `b""` —
    fazia o receptor aceitar tudo o que fosse assinado com um segredo vazio, que
    e qualquer pessoa.
    """
    valor = os.environ.get(VARIAVEL_DO_SEGREDO, "")
    if not valor:
        raise SegredoEmFalta(
            f"{VARIAVEL_DO_SEGREDO} nao esta definida ou esta vazia. O App Secret "
            "vive no cofre e entra por ambiente; o repositorio e publico."
        )
    return valor.encode("utf-8")


def calcular(corpo: bytes, chave: bytes) -> str:
    """O valor do cabecalho para este corpo bruto: `sha256=<hex>`.

    Exige `bytes`. Um `str` aqui seria uma decisao de codificacao escondida — e
    a codificacao decide os bytes, que e precisamente o que se esta a assinar.
    """
    if not isinstance(corpo, bytes):
        raise TypeError(
            "calcular exige o corpo em bytes: um `str` obriga a escolher uma "
            "codificacao, e sao os bytes que se assinam"
        )
    resumo = hmac.new(chave, corpo, hashlib.sha256).hexdigest()
    return f"{PREFIXO}{resumo}"


def verificar(corpo: bytes, cabecalho: str | None, chave: bytes | None = None) -> None:
    """Valida o cabecalho contra o corpo **bruto**. Nao devolve nada; levanta.

    Nao ha valor de retorno de proposito: um `bool` convida a `if not
    verificar(...)` esquecido, e um esquecimento desses e aceitar tudo. Quem
    chama tem de apanhar `AssinaturaInvalida` ou deixar subir.
    """
    if not isinstance(corpo, bytes):
        raise TypeError(
            "verificar exige o corpo em bytes, exactamente como chegou ao "
            "transporte. Re-serializar faz a assinatura autenticar uma familia "
            "de corpos em vez do corpo que chegou (ver a nota do modulo)"
        )
    if chave is None:
        chave = segredo()
    if not cabecalho:
        raise AssinaturaInvalida(f"pedido sem {CABECALHO}")
    if not cabecalho.startswith(PREFIXO):
        raise AssinaturaInvalida(f"{CABECALHO} sem o prefixo {PREFIXO!r}")
    esperado = calcular(corpo, chave)
    # `compare_digest` e nao `==`: a comparacao de cadeias sai no primeiro byte
    # diferente, e o tempo que leva diz quantos bytes acertaram. E1 §5 pede
    # comparacao em tempo constante.
    if not hmac.compare_digest(cabecalho, esperado):
        raise AssinaturaInvalida(
            f"{CABECALHO} nao corresponde ao corpo bruto recebido "
            f"({len(corpo)} byte(s))"
        )
