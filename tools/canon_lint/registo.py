"""Superficie 3 — `registry/*.yaml`: verticais, entitlements, subscricoes e tools.

A forma dos ficheiros e a de `docs/tecnica/02` §5.1. O que se verifica:

* nivel 1 em **todas** as chaves e todos os textos do ficheiro;
* `id` — uma vertical do dicionario §3.2;
* `entitlements.modulo` e `entitlements.limites[]` — os do dicionario;
* `subscriptions[].tipo` — um tipo de evento do dicionario;
* `tools[]` e os seus parametros — tools do dicionario ou extensoes;
* **os dois eventos de pagamento** (§3.4): quem subscreve um e nao o outro esta
  a tratar os dois caminhos como um so, salvo se a politica o declarar como
  consumidor que os distingue;
* **o identificador de confirmacao** (§3.3): `confirm:{cart_id}` e do Vendedor,
  `confirm:{hold_id}` e de Servicos, `confirm:{item_id}` dos modulos de entrada.

As chaves de topo sao uma **lista fechada** — as de `docs/tecnica/02` §5.1. Uma
chave desconhecida falha: sem isso, `subscricoes:` ou `ferramentas:` (em vez de
`subscriptions:` e `tools:`) passavam o ficheiro inteiro ao lado das
verificacoes. O mesmo para as chaves de `entitlements` e de cada subscricao.
`persona`, `graph`, `models`, `guardrails` e `golden` nao tem nomes do
dicionario e so passam pelo nivel 1.

Limites ditos: nao se cruza o `id` com o `modulo` nem com os limites (um
`servicos` com `modulo: vendedor` passa — o dicionario nao escreve essa regra),
e os parametros de uma tool so sao lidos nas chaves `parametros`, `params`,
`args` e `argumentos`.
"""

from __future__ import annotations

import re

from .achados import ILEGIVEL, REGRA, Achado, aceita, fora, variante, variantes_em_texto
from .dicionario import POLITICA, Saber
from .yamlreg import YamlIlegivel, ler

#: Qualquer coisa que comece por `confirm:` — incluindo as formas erradas
#: (`confirm:{{cart_id}}`, `confirm:<cart_id>`, `confirm:cart_id`), que tem de
#: falhar e nao de passar por nao baterem no padrao certo.
_CONFIRMACAO = re.compile(r"""confirm:[^\s"',\]\)]+""")

#: As chaves de `docs/tecnica/02` §5.1.
CHAVES_DE_TOPO = {
    "id", "version", "phase", "persona", "graph", "tools", "entitlements",
    "subscriptions", "models", "guardrails", "golden",
}
CHAVES_DE_ENTITLEMENTS = {"modulo", "limites"}
CHAVES_DE_SUBSCRICAO = {"tipo", "versao"}

_CHAVES_DE_NOME = ("nome", "name", "id", "tool")
_CHAVES_DE_PARAMETROS = ("parametros", "params", "args", "argumentos")
CHAVES_DE_TOOL = set(_CHAVES_DE_NOME) | set(_CHAVES_DE_PARAMETROS) | {"descricao", "classe", "confirmacao"}


def _textos(no, acumulado: list[str]) -> None:
    """Todas as chaves e todos os escalares de texto, a qualquer profundidade."""
    if isinstance(no, dict):
        for chave, valor in no.items():
            acumulado.append(str(chave))
            _textos(valor, acumulado)
    elif isinstance(no, list):
        for item in no:
            _textos(item, acumulado)
    elif isinstance(no, str):
        acumulado.append(no)


def _linha_de(fonte: str, agulha: str) -> int:
    for numero, linha in enumerate(fonte.split("\n"), start=1):
        if agulha in linha:
            return numero
    return 0


def verificar(ficheiro: str, fonte: str, saber: Saber) -> list[Achado]:
    try:
        documento = ler(fonte)
    except YamlIlegivel as excepcao:
        return [Achado(ficheiro, 0, ILEGIVEL, f"YAML que o gate 3b nao consegue ler: {excepcao}")]
    if not isinstance(documento, dict):
        return [Achado(ficheiro, 0, ILEGIVEL, "o ficheiro do registo nao e um mapa de topo")]

    achados: list[Achado] = []
    dicionario, politica = saber.dicionario, saber.politica

    # --- nivel 1 ------------------------------------------------------------------
    textos: list[str] = []
    _textos(documento, textos)
    ja: set[str] = set()
    for texto in textos:
        encontradas = list(variantes_em_texto(saber, texto))
        de_valor = dicionario.variantes_valor.get(texto)
        if de_valor is not None:
            encontradas.append(de_valor)
        for v in encontradas:
            if v.nome not in ja:
                ja.add(v.nome)
                achados.append(variante(ficheiro, _linha_de(fonte, v.nome), v))

    def chaves(mapa: dict, permitidas: set[str], onde: str) -> None:
        for chave in mapa:
            if chave not in permitidas:
                achados.append(
                    Achado(
                        ficheiro,
                        _linha_de(fonte, str(chave)),
                        ILEGIVEL,
                        f"chave `{chave}` desconhecida {onde}; as chaves sao "
                        f"{', '.join(sorted(permitidas))}. O gate 3b nao le o que esta debaixo de "
                        "uma chave que nao conhece",
                    )
                )

    chaves(documento, CHAVES_DE_TOPO, "no topo do ficheiro")

    def nivel2(tipo: str, nome, qualificado: str | None = None) -> None:
        if not isinstance(nome, str) or not nome:
            achados.append(Achado(ficheiro, 0, ILEGIVEL, f"{tipo} sem nome legivel: {nome!r}"))
            return
        if nome in ja:
            return  # variante, ja reportada
        if not aceita(saber, tipo, qualificado or nome, simples=nome):
            achados.append(fora(ficheiro, _linha_de(fonte, nome), tipo, qualificado or nome))

    # --- id ---------------------------------------------------------------------------
    vertical = documento.get("id")
    verticais = dicionario.dominios.get("id", {}).get("valores", [])
    if not isinstance(vertical, str) or not vertical:
        achados.append(Achado(ficheiro, 0, REGRA, "ficheiro do registo sem `id`"))
        vertical = ""
    elif vertical not in verticais and not saber.extensoes.tem("vertical", vertical):
        achados.append(
            fora(
                ficheiro,
                _linha_de(fonte, vertical),
                "vertical",
                vertical,
                f"`id` ∈ {{{', '.join(verticais)}}}, dicionário §{politica.verticais['seccao']}",
            )
        )

    # --- entitlements -------------------------------------------------------------
    entitlements = documento.get("entitlements")
    if isinstance(entitlements, dict):
        chaves(entitlements, CHAVES_DE_ENTITLEMENTS, "em `entitlements`")
        modulo = entitlements.get("modulo")
        modulos = verticais + dicionario.dominios.get("modulo", {}).get("valores", [])
        if modulo is not None and modulo not in modulos and not saber.extensoes.tem("modulo", str(modulo)):
            achados.append(
                fora(ficheiro, _linha_de(fonte, str(modulo)), "modulo", str(modulo),
                     f"`modulo` ∈ {{{', '.join(dict.fromkeys(modulos))}}}, dicionário §3.2 e §3.7")
            )
        chaves_de_limite = set(politica.limites["nomes"])
        limites = entitlements.get("limites")
        if limites is not None and not isinstance(limites, list):
            achados.append(Achado(ficheiro, 0, ILEGIVEL, "`entitlements.limites` nao e uma lista"))
            limites = []
        for limite in limites or []:
            if not isinstance(limite, str):
                achados.append(Achado(ficheiro, 0, ILEGIVEL, f"limite que nao e um nome: {limite!r}"))
            elif limite in ja:
                continue
            elif limite not in chaves_de_limite and not saber.extensoes.tem("limite", limite):
                achados.append(
                    fora(ficheiro, _linha_de(fonte, limite), "limite", limite,
                         f"`{politica.limites['canonico']}`, dicionário §{politica.limites['seccao']}")
                )
    elif entitlements is not None:
        achados.append(Achado(ficheiro, 0, ILEGIVEL, "`entitlements` nao e um mapa"))

    # --- subscricoes ----------------------------------------------------------------
    subscritos: list[str] = []
    subscricoes = documento.get("subscriptions")
    if subscricoes is not None and not isinstance(subscricoes, list):
        achados.append(Achado(ficheiro, 0, ILEGIVEL, "`subscriptions` nao e uma lista"))
        subscricoes = []
    for item in subscricoes or []:
        if isinstance(item, dict):
            chaves(item, CHAVES_DE_SUBSCRICAO, "numa subscricao")
        tipo = item.get("tipo") if isinstance(item, dict) else item
        if not isinstance(tipo, str):
            achados.append(Achado(ficheiro, 0, ILEGIVEL, f"subscricao sem `tipo`: {item!r}"))
            continue
        subscritos.append(tipo)
        nivel2("evento", tipo)

    par = politica.eventos_de_pagamento
    tem = [evento in subscritos for evento in par["eventos"]]
    if any(tem) and not all(tem) and vertical not in par["distinguem"]:
        presente = par["eventos"][tem.index(True)]
        ausente = par["eventos"][tem.index(False)]
        achados.append(
            Achado(
                ficheiro,
                _linha_de(fonte, presente),
                REGRA,
                f"`{presente}` sem `{ausente}` → `{par['canonico']}`, dicionário §{par['seccao']} "
                "(quem nao distingue os dois caminhos subscreve os dois; se este consumidor os "
                f"distingue, declare-o em {POLITICA}, `eventos_de_pagamento.distinguem_o_caminho`)",
            )
        )

    # --- tools e parametros ---------------------------------------------------------
    ferramentas = documento.get("tools")
    if ferramentas is not None and not isinstance(ferramentas, list):
        achados.append(Achado(ficheiro, 0, ILEGIVEL, "`tools` nao e uma lista"))
        ferramentas = []
    for item in ferramentas or []:
        if isinstance(item, str):
            nivel2("tool", item)
            continue
        if not isinstance(item, dict):
            achados.append(Achado(ficheiro, 0, ILEGIVEL, f"tool de forma desconhecida: {item!r}"))
            continue
        nome = next((item[c] for c in _CHAVES_DE_NOME if isinstance(item.get(c), str)), None)
        if nome is None:
            achados.append(
                Achado(ficheiro, 0, ILEGIVEL,
                       f"tool sem nome (esperava uma de {', '.join(_CHAVES_DE_NOME)}): {sorted(item)}")
            )
            continue
        nivel2("tool", nome)
        # r11, r12: os parametros sob `input_schema.properties` ou `parameters`
        # nao eram lidos. A forma de uma tool em mapa nao esta no desenho; o que
        # o lint nao conhece, recusa.
        chaves(item, CHAVES_DE_TOOL, f"na tool `{nome}`")
        parametros = next((item[c] for c in _CHAVES_DE_PARAMETROS if c in item), None)
        if isinstance(parametros, dict):
            nomes = list(parametros)
        elif isinstance(parametros, list):
            nomes = [
                p if isinstance(p, str)
                else next((p[c] for c in _CHAVES_DE_NOME if isinstance(p, dict) and isinstance(p.get(c), str)), None)
                for p in parametros
            ]
        elif parametros is None:
            nomes = []
        else:
            achados.append(Achado(ficheiro, 0, ILEGIVEL, f"parametros de `{nome}` de forma desconhecida"))
            nomes = []
        for parametro in nomes:
            nivel2("parametro", parametro, f"{nome}.{parametro}")

    # --- identificador de confirmacao -----------------------------------------------
    origem = politica.confirmacao_origem
    esperado = politica.confirmacao.get(vertical)
    vistos: set[str] = set()
    for texto in textos:
        for identificador in _CONFIRMACAO.findall(texto):
            if identificador in vistos:
                continue
            vistos.add(identificador)
            if esperado and identificador != esperado:
                achados.append(
                    Achado(
                        ficheiro,
                        _linha_de(fonte, identificador),
                        REGRA,
                        f"`{identificador}` em `{vertical}` → `{esperado}`, dicionário "
                        f"§{origem['seccao']} ({origem['canonico']})",
                    )
                )
            elif not esperado and identificador not in origem["literais"]:
                achados.append(
                    fora(ficheiro, _linha_de(fonte, identificador), "identificador de confirmacao",
                         identificador, f"`{origem['canonico']}`, dicionário §{origem['seccao']}")
                )
    return achados
