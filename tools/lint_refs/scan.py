"""Extraccao de referencias de um texto, com as armadilhas tratadas.

A ordem das operacoes importa e nao e arbitraria: expandem-se primeiro as formas
compostas (intervalos e listas unidas), porque sao as que escondem referencias, e
so depois se varre o que resta. Varrer primeiro e expandir depois perderia os
intervalos.
"""

from __future__ import annotations

import dataclasses
import re

#: `KAM-003`, `ADR-013`. Exige exactamente tres digitos e recusa `ADR-L001`
#: (sequencia local) pela fronteira a esquerda.
#: Hifen normal, nao-quebravel (U+2011) e meia-risca (U+2013): um editor
#: produz os dois ultimos sozinho, e `KAM‑999` e indistinguivel a vista de
#: `KAM-999`. Sem eles, a forma mais facil de citar um ticket inexistente sem
#: o gate dar por isso era carregar na tecla errada.
_HIFEN = "[-‑–]"

#: Aceita **tres ou mais** digitos de proposito. Com `[0-9]{3}(?![0-9])`, um
#: `KAM-0999` ou `KAM-1300` nao batia em padrao nenhum e passava invisivel; e
#: melhor apanha-lo e declara-lo invalido do que nao o ver. A validacao do
#: numero faz-se depois, contra o canon.
_SIMPLES = re.compile(
    r"(?<![A-Za-z0-9-])(?P<serie>KAM|ADR)" + _HIFEN + r"(?P<numero>[0-9]{3,4})(?![0-9])"
)

#: `D12`. A serie `D` e a mais perigosa: colide com prazos (`D+30`, `D0`),
#: com `D-01` (as divergencias do KAM-111) e com `D1–D9` do documento 05.
#: Exige-se fronteira de palavra dos dois lados e recusa-se `D-`.
_DECISAO = re.compile(r"(?<![A-Za-z0-9+_-])D(?P<numero>[0-9]{1,2})(?![0-9A-Za-z-])")

#: `KAM-007/008/009/022` — o prefixo aparece uma vez e os seguintes sao nus.
_UNIDOS = re.compile(
    r"(?<![A-Za-z0-9-])(?P<serie>KAM|ADR)-(?P<primeiro>[0-9]{3})"
    r"(?P<resto>(?:/[0-9]{3})+)(?![0-9])"
)

#: `KAM-001–012`, `ADR-001-019`, `KAM-013 – KAM-024`, `ADR-001 a ADR-019`.
#: Os separadores incluem o travessao (`–`), o hifen e a palavra «a».
_INTERVALO = re.compile(
    r"(?<![A-Za-z0-9-])(?P<serie>KAM|ADR)-(?P<de>[0-9]{3})"
    r"\s*(?:–|—|-|\sa\s)\s*"
    r"(?:(?P=serie)-)?(?P<ate>[0-9]{3})(?![0-9])"
)

#: `D1–D13`, `D1 a D9`.
_INTERVALO_D = re.compile(
    r"(?<![A-Za-z0-9+_-])D(?P<de>[0-9]{1,2})\s*(?:–|—|-|\sa\s)\s*D(?P<ate>[0-9]{1,2})"
    r"(?![0-9A-Za-z-])"
)

#: Contextos em que uma ocorrencia nao conta. Blocos de codigo cercados sao o
#: caso que importa: cada ticket tem um `” ```text ”` com o prompt de handoff,
#: e esse texto cita tickets a titulo de instrucao, nao de referencia.
_CERCA = re.compile(r"^\s*```")


@dataclasses.dataclass(frozen=True)
class Ocorrencia:
    serie: str
    identificador: str
    linha: int
    contexto: str
    #: `True` quando o token tem a forma da serie mas esta fora do intervalo
    #: canonico. Para `KAM` e `ADR` isso e um erro; para `D` e, medidamente, um
    #: prazo em dias — ver `ci/refs-allow.yaml`, seccao `serie_d`.
    fora_do_intervalo: bool = False

    @property
    def numero(self) -> int:
        return int(self.identificador.split("-")[-1].lstrip("D"))


def _expandir_intervalo(serie: str, de: int, ate: int) -> list[str]:
    """`KAM-001–012` da os doze. Um intervalo invertido ou enorme nao se expande.

    O limite de 200 e um travao de seguranca: `D1-9` num texto sobre prazos
    poderia pedir a expansao de milhares de identificadores inexistentes e
    encher o relatorio de ruido.
    """
    if ate < de or (ate - de) > 200:
        return []
    largura = 3 if serie in ("KAM", "ADR") else 0
    if largura:
        return [f"{serie}-{n:0{largura}d}" for n in range(de, ate + 1)]
    return [f"{serie}{n}" for n in range(de, ate + 1)]


def extrair(
    texto: str,
    ignorar_blocos_de_codigo: bool = True,
    maximo_d: int | None = None,
) -> list[Ocorrencia]:
    """Todas as referencias de um texto, com as formas compostas expandidas.

    `maximo_d` e o maior numero de decisao que o canon tem (hoje 13). Serve para
    **nao expandir intervalos de prazos**: `Prazos D0–D30` (`specs/EPIC-09:1054`)
    nao e um intervalo de decisoes, e expandi-lo inventava `D14`…`D29` — 32
    referencias fantasma que nao estao em sitio nenhum do texto. Sem este
    parametro o relatorio enche-se de tokens que ninguem escreveu.
    """
    ocorrencias: list[Ocorrencia] = []
    dentro_de_cerca = False

    # Uma cerca aberta e nunca fechada cegava o resto do ficheiro.
    #
    # `dentro_de_cerca` e um interruptor, pelo que um numero **impar** de ```
    # num ficheiro desligava o varrimento dali para a frente — e nao precisa de
    # ser malicia: um `.md` ou uma docstring com cercas desequilibradas produz
    # isto por acidente. Quando as cercas nao fecham, **nao** se aplica a
    # dispensa: varre-se tudo. Perde-se precisao nos blocos de codigo desse
    # ficheiro, e e o lado certo em que perder.
    linhas = texto.split("\n")
    if ignorar_blocos_de_codigo:
        cercas = sum(1 for linha in linhas if _CERCA.match(linha))
        if cercas % 2:
            ignorar_blocos_de_codigo = False

    for numero_linha, linha in enumerate(linhas, start=1):
        if _CERCA.match(linha):
            dentro_de_cerca = not dentro_de_cerca
            continue
        if dentro_de_cerca and ignorar_blocos_de_codigo:
            continue

        contexto = linha.strip()[:120]
        vistos: set[str] = set()

        def juntar(serie: str, identificador: str) -> None:
            if identificador in vistos:
                return
            vistos.add(identificador)
            ocorrencias.append(Ocorrencia(serie, identificador, numero_linha, contexto))

        # 1. Intervalos primeiro: sao os que escondem referencias.
        for correspondencia in _INTERVALO.finditer(linha):
            serie = correspondencia.group("serie")
            for identificador in _expandir_intervalo(
                serie, int(correspondencia.group("de")), int(correspondencia.group("ate"))
            ):
                juntar(serie, identificador)

        for correspondencia in _INTERVALO_D.finditer(linha):
            de, ate = int(correspondencia.group("de")), int(correspondencia.group("ate"))
            # Um intervalo da serie `D` so se expande se as **duas** pontas
            # estiverem dentro do intervalo canonico. `D1–D13` expande-se;
            # `D0–D30` e `D0–D7` nao, porque sao prazos. As pontas continuam a
            # aparecer pelas correspondencias simples, mais abaixo, e sao la que
            # recebem o aviso.
            if maximo_d is not None and not (1 <= de <= maximo_d and 1 <= ate <= maximo_d):
                continue
            for identificador in _expandir_intervalo("D", de, ate):
                juntar("D", identificador)

        # 2. Listas unidas por `/` sem repetir o prefixo.
        for correspondencia in _UNIDOS.finditer(linha):
            serie = correspondencia.group("serie")
            juntar(serie, f"{serie}-{correspondencia.group('primeiro')}")
            for numero in correspondencia.group("resto").strip("/").split("/"):
                juntar(serie, f"{serie}-{numero}")

        # 3. As formas simples.
        for correspondencia in _SIMPLES.finditer(linha):
            serie = correspondencia.group("serie")
            juntar(serie, f"{serie}-{correspondencia.group('numero')}")

        for correspondencia in _DECISAO.finditer(linha):
            juntar("D", f"D{correspondencia.group('numero')}")

    return ocorrencias
