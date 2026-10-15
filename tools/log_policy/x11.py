"""X-11: varrimento de *logs* por identificadores directos (KAM-068).

`docs/tecnica/08` §7.3 e §14 pedem o alvo «identificadores directos em logs =
0», medido por um varrimento com os padroes `+244`, `9\\d{8}` e NIF. Este
modulo e esse varrimento, e serve dois usos: o gate (sobre os *logs* gerados
por 1 000 *fixtures*) e a amostragem de `prod` (`amostra.py`).

## Porque e que o varrimento conhece a forma da linha

Um `tenant_id` e um UUID, e um UUID tem digitos. Em cerca de 0,6% dos UUID
aleatorios ha nove digitos seguidos comecados por 9 — a forma exacta de um
telemovel angolano. Um varrimento cego dava dezenas de falsos positivos por dia
em `prod`, e um varrimento que da falsos positivos e desligado.

Por isso cada linha e lida como JSON, e os campos **de forma fechada** sao
conferidos pela forma em vez de varridos: `tenant_id`, `turn_id`, `msg_id`,
`contact_hmac_prefix` e `ts`. Se o valor **nao** tiver a forma exacta, e
varrido como texto — um telefone posto em `tenant_id` e apanhado. Todos os
outros campos, as chaves, e qualquer linha que nao seja um objecto JSON sao
varridos por inteiro.

O limite que isto deixa esta em `docs/logs.md` §7: um telefone escondido
**dentro** de um UUID valido nao e visto, aqui nem em lado nenhum.

## O padrao do NIF

Nenhum documento define o formato do NIF (`docs/seguranca/lacunas.md`, Q-A), e
o ticket manda nao o inventar. E um parametro (`nif_padroes`); sem ele o NIF
**nao e medido por padrao proprio**, e a saida di-lo. O que o apanha na mesma e
o padrao `sequencia_de_digitos`: nove ou mais digitos, em qualquer formato.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import json
import re
import unicodedata
from pathlib import Path

# As formas de segredo sao as do gate 9: uma lista so, e nao duas a divergir.
from scan_secrets.patterns import PADROES as PADROES_DE_SEGREDO

#: Os doze campos de `docs/tecnica/08` §7.3. Escritos aqui e nao importados do
#: *logger*: `tests/test_x11.py` confere que as tres listas (esta, a de Python e
#: a de TypeScript) sao a mesma.
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

#: O que pode estar entre dois digitos de um numero: ate dois caracteres que
#: nao sejam letra nem digito (`923 456 789`, `923/456/789`, `923456__789`,
#: `923,  456`). A primeira versao so conhecia espaco, ponto, hifen e
#: parenteses, um de cada vez (`docs/analises/ANALISE-11`, A9).
_SEP = r"[^0-9A-Za-z]"
_ENTRE = rf"{_SEP}{{0,2}}"

TELEFONE_INTERNACIONAL = "telefone_ao_internacional"
TELEFONE_NACIONAL = "telefone_ao_nacional"
SEQUENCIA_DE_DIGITOS = "sequencia_de_digitos"
EMAIL = "email"
IBAN_AO = "iban_ao"
NIF = "nif"
SEGREDO = "segredo"
BASE64_COM_IDENTIFICADOR = "identificador_em_base64"
CANARIO = "canario"
CAMPO_FORA = "campo_fora_da_allowlist"
LINHA_FORA = "linha_fora_do_formato"

#: Os padroes fixos. Os tres primeiros sao os do criterio de aceitacao
#: (`+244 9XX XXX XXX`, `244 9…`, `9\d{8}`), tolerantes a separadores.
PADROES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        TELEFONE_INTERNACIONAL,
        re.compile(rf"(?:\+|00)?244{_SEP}{{0,3}}9(?:{_ENTRE}[0-9]){{8}}"),
    ),
    (TELEFONE_NACIONAL, re.compile(rf"9(?:{_ENTRE}[0-9]){{8}}")),
    (SEQUENCIA_DE_DIGITOS, re.compile(rf"[0-9](?:{_ENTRE}[0-9]){{8}}")),
    (EMAIL, re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")),
    # Forma do IBAN angolano: `AO`, dois digitos de controlo e 21 digitos
    # (INDICIO; nenhum documento do canon a fixa).
    (IBAN_AO, re.compile(rf"AO[0-9]{{2}}(?:{_ENTRE}[0-9]){{21}}")),
)

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_ID_OPACO = re.compile(r"m_[0-9a-f]{32}")
_HMAC_PREFIXO = re.compile(r"[0-9a-f]{8}")
_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")

#: Campos conferidos pela forma. Um valor com a forma exacta nao e varrido.
FORMAS_FECHADAS: dict[str, tuple[re.Pattern[str], ...]] = {
    "ts": (_TS,),
    "tenant_id": (_UUID,),
    "turn_id": (_UUID, _ID_OPACO),
    "msg_id": (_UUID, _ID_OPACO),
    "contact_hmac_prefix": (_HMAC_PREFIXO,),
}

#: Pedacos com cara de base64 suficientemente longos para levar um telefone.
_BASE64 = re.compile(r"[A-Za-z0-9+/_\-]{16,}={0,2}")

_CHAVE_LEGIVEL = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,40}")


class ConfiguracaoInvalida(ValueError):
    """Um padrao de NIF que nao compila, ou um ficheiro que nao se le."""


@dataclasses.dataclass(frozen=True)
class Achado:
    """Onde e o que. **Nunca** o valor encontrado."""

    ficheiro: str
    linha: int
    padrao: str
    campo: str

    def __str__(self) -> str:
        return f"{self.ficheiro}:{self.linha}: {self.padrao} em {self.campo}"


@dataclasses.dataclass(frozen=True)
class Configuracao:
    nif_padroes: tuple[re.Pattern[str], ...] = ()
    canarios: tuple[str, ...] = ()

    @staticmethod
    def criar(nif_padroes=(), canarios=()) -> "Configuracao":
        compilados = []
        for texto in nif_padroes:
            try:
                compilados.append(re.compile(texto))
            except re.error as erro:
                raise ConfiguracaoInvalida(
                    f"padrao de NIF que nao compila ({erro.msg})"
                ) from None
        return Configuracao(tuple(compilados), tuple(c for c in canarios if c))


def _descodificacoes(texto: str):
    """O que os pedacos com cara de base64 dizem depois de descodificados."""
    for pedaco in _BASE64.findall(texto):
        limpo = pedaco.rstrip("=")
        # Um identificador da Meta comeca por um prefixo e um ponto; o que vem
        # a seguir e que e base64. Tenta-se cada alinhamento possivel, porque o
        # pedaco apanhado pode ter trazido caracteres do prefixo.
        for inicio in range(0, 4):
            corpo = limpo[inicio:]
            corpo += "=" * (-len(corpo) % 4)
            for alfabeto in (None, b"-_"):
                try:
                    bruto = base64.b64decode(corpo, altchars=alfabeto, validate=True)
                except (binascii.Error, ValueError):
                    continue
                yield bruto.decode("latin-1")


#: Caracteres que nao se veem e que partem um numero ao meio.
_INVISIVEIS = dict.fromkeys(
    [0x00AD, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF], None
)


def normalizar(texto: str) -> str:
    """O texto como uma pessoa o le: sem invisiveis, com os digitos em ASCII.

    `９２３…` (largura total), os digitos arabe-indicos e um espaco de largura
    zero entre dois digitos sao o mesmo telefone para quem le o *log*.
    """
    limpo = unicodedata.normalize("NFKC", texto).translate(_INVISIVEIS)
    return "".join(
        str(unicodedata.digit(c)) if c.isdigit() and not c.isascii() else c for c in limpo
    )


def padroes_no_texto(texto: str, configuracao: Configuracao) -> list[str]:
    """Os nomes dos padroes que batem no texto, sem repeticoes, por ordem."""
    texto = normalizar(texto)
    nomes: list[str] = []

    def acrescentar(nome: str) -> None:
        if nome not in nomes:
            nomes.append(nome)

    for nome, expressao in PADROES:
        if expressao.search(texto):
            acrescentar(nome)
    for expressao in configuracao.nif_padroes:
        if expressao.search(texto):
            acrescentar(NIF)
    for padrao in PADROES_DE_SEGREDO:
        if padrao.classe in ("chave_api", "chave_privada") and padrao.expressao.search(texto):
            acrescentar(SEGREDO)
    for canario in configuracao.canarios:
        if canario in texto:
            acrescentar(CANARIO)
    if TELEFONE_INTERNACIONAL not in nomes and TELEFONE_NACIONAL not in nomes:
        for descodificado in _descodificacoes(texto):
            if PADROES[0][1].search(descodificado) or PADROES[1][1].search(descodificado):
                acrescentar(BASE64_COM_IDENTIFICADOR)
                break
    return nomes


class _Pares(list):
    """Os pares `(chave, valor)` de um objecto JSON, com as repeticoes."""


def _em_json(valor: object) -> object:
    if isinstance(valor, _Pares):
        return [[chave, _em_json(v)] for chave, v in valor]
    if isinstance(valor, list):
        return [_em_json(v) for v in valor]
    return valor


def _chave_legivel(chave: str) -> str:
    return chave if _CHAVE_LEGIVEL.fullmatch(chave) else "<chave ilegivel>"


def varrer_linha(texto: str, configuracao: Configuracao) -> list[tuple[str, str]]:
    """Os achados de uma linha, como pares `(padrao, campo)`."""
    # Por pares, e nao por dicionario: numa linha com a mesma chave duas vezes
    # (`"outcome":"923…","outcome":"ok"`) um dicionario so guardava a ultima.
    try:
        objecto = json.loads(texto, object_pairs_hook=_Pares)
    except ValueError:
        objecto = None
    if not isinstance(objecto, _Pares):
        achados = [(LINHA_FORA, "<linha>")]
        achados += [(nome, "<linha>") for nome in padroes_no_texto(texto, configuracao)]
        return achados

    achados = []
    for chave, valor in objecto:
        legivel = _chave_legivel(chave)
        if chave not in CAMPOS:
            achados.append((CAMPO_FORA, legivel))
            for nome in padroes_no_texto(chave, configuracao):
                achados.append((nome, "<chave>"))
        formas = FORMAS_FECHADAS.get(chave)
        if formas and isinstance(valor, str) and any(f.fullmatch(valor) for f in formas):
            continue
        como_texto = (
            valor if isinstance(valor, str) else json.dumps(_em_json(valor), ensure_ascii=False)
        )
        for nome in padroes_no_texto(como_texto, configuracao):
            achados.append((nome, legivel))
    return achados


def varrer_texto(nome: str, conteudo: str, configuracao: Configuracao) -> tuple[list[Achado], int]:
    """Varre um registo inteiro. Devolve os achados e o numero de linhas lidas."""
    achados: list[Achado] = []
    linhas = 0
    for numero, linha in enumerate(conteudo.splitlines(), start=1):
        if not linha.strip():
            continue
        linhas += 1
        for padrao, campo in varrer_linha(linha, configuracao):
            achados.append(Achado(nome, numero, padrao, campo))
    return achados, linhas


def varrer_ficheiro(caminho: Path, configuracao: Configuracao) -> tuple[list[Achado], int]:
    try:
        conteudo = caminho.read_text(encoding="utf-8", errors="replace")
    except OSError as erro:
        raise ConfiguracaoInvalida(f"nao se le {caminho.name}: {erro.strerror}") from None
    return varrer_texto(caminho.name, conteudo, configuracao)
