"""Superficie 3 — `registry/*.yaml`: verticais, planos, gates, entitlements e tools.

## Tres formas, e so tres

Um ficheiro desta superficie e uma de tres coisas, e a forma distingue-se por
uma **chave de topo propria**, nunca pelo nome do ficheiro:

1. **vertical** — a chave `id`. A forma e a de `docs/tecnica/02` §5.1;
2. **planos** — a chave `plans`. E o `registry/plans.yaml` do KAM-009:
   `plano` -> entitlements por omissao;
3. **gates** — a chave `gates`. E o `registry/gates.yaml` do KAM-027: o **modo**
   de cada validacao de arranque do §5.2, com o ticket que a desbloqueia.

Um ficheiro que nao tenha nenhuma das tres **falha**, e um que tenha mais do
que uma tambem: nao se adivinha qual das verificacoes se lhe aplica. Antes do
KAM-009 havia uma so forma, a lista fechada de chaves de topo era a dela, e o
`id` tinha de ser uma vertical — um `plans.yaml` falhava as duas coisas e nao
havia como o escrever.

## O que se verifica nas duas primeiras

* nivel 1 em **todas** as chaves e todos os textos do ficheiro;
* **os nomes de limite**, contra as dez chaves do dicionario §3.2 («Entitlement
  (chaves)», emenda 1.17). Na vertical `entitlements.limites` e uma **lista**
  de nomes; nos planos `…entitlements[].limites` e um **mapa** nome -> valor.
  E a mesma regra, e e ela que torna o `plans.yaml` util: sem este confronto o
  ficheiro era texto, e uma chave que o `platform.ten_consumir` nunca
  encontraria passava despercebida ate um tenant bater num tecto que nao
  existe;
* `modulo`, contra as verticais do §3.2 e os modulos do §3.7;
* **o identificador de confirmacao** (§3.3): `confirm:{cart_id}` e do Vendedor,
  `confirm:{hold_id}` e de Servicos, `confirm:{item_id}` dos modulos de entrada.

## So na vertical

* `id` — uma vertical do dicionario §3.2;
* `subscriptions[].tipo` — um tipo de evento do dicionario;
* `tools[]` e os seus parametros — tools do dicionario ou extensoes;
* **os dois eventos de pagamento** (§3.4): quem subscreve um e nao o outro esta
  a tratar os dois caminhos como um so, salvo se a politica o declarar como
  consumidor que os distingue.

## So nos gates

* o nome de cada entrada e uma **vertical** do dicionario §3.2;
* o nome de cada validacao esta na lista fechada do §5.2 (`tools`,
  `entitlements`, `grafo`, `subscriptions`, `fase`, `golden`) — um `tool` por
  `tools` desligava a validacao em silencio, que e o pior dos dois erros;
* `modo` ∈ {`aviso`, `bloqueio`}, e um `aviso` **exige** `credor` com a forma
  `KAM-NNN`: um atalho sem o ticket que o fecha nao e atalho. Que o ticket
  exista no backlog e do *gate* 3, que le os `KAM-NNN` deste ficheiro como os
  de qualquer outro.

## So nos planos

* cada plano declara `estado`, e o unico valor que o canon escreve e
  `hipotese_nao_validada` — dicionario §4, «Lista de planos e os seus limites»:
  «nasce com valores **de exemplo**, marcados `estado: hipotese_nao_validada`»,
  porque nenhum documento tem a tabela de planos. E o padrao que o
  `specs/EPIC-11` ja fixou para este caso exacto (KAM-124);
* os valores de limite sao inteiros **nao negativos** (`bigint`): o que esta do
  outro lado e `limites jsonb` e a aritmetica de `platform.ten_consumir`.

As chaves de topo de **cada** forma sao uma lista fechada, e as de cada plano e
de cada entitlement tambem. Uma chave desconhecida falha: sem isso,
`subscricoes:` ou `ferramentas:` (em vez de `subscriptions:` e `tools:`)
passavam o ficheiro inteiro ao lado das verificacoes, e um `limits:` em vez de
`limites:` dava um plano sem limite nenhum — que e um plano sem tecto.
`persona`, `graph`, `models`, `guardrails` e `golden` nao tem nomes do
dicionario e so passam pelo nivel 1.

Limites ditos: nao se cruza o `id` com o `modulo` nem com os limites (um
`servicos` com `modulo: vendedor` passa — o dicionario nao escreve essa regra),
nao se cruza a **categoria** de uma chave de limite com o sitio onde ela e
usada (isso e o `registry/entitlement_keys.schema.json`, e quem o faz cumprir e
a biblioteca TEN), nao ha lista fechada de **nomes de plano** (o dicionario
§3.2 da a `tenants.plano` um `CHECK` de forma e nao de dominio), e os
parametros de uma tool so sao lidos nas chaves `parametros`, `params`, `args` e
`argumentos`.
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

#: A forma de uma chave de limite: minusculas e `snake_case` (dicionario §2), e
#: literalmente o `CHECK (chave_limite ~ '^[a-z][a-z0-9_]*$')` de
#: `platform.tenant_usage` (revisao `0007`).
_FORMA_DE_CHAVE_DE_LIMITE = re.compile(r"^[a-z][a-z0-9_]*$")

#: As chaves de `docs/tecnica/02` §5.1.
CHAVES_DE_TOPO = {
    "id", "version", "phase", "persona", "graph", "tools", "entitlements",
    "subscriptions", "models", "guardrails", "golden",
}
CHAVES_DE_ENTITLEMENTS = {"modulo", "limites"}
CHAVES_DE_SUBSCRICAO = {"tipo", "versao"}

#: As chaves de topo que **declaram a forma**. Sao o discriminante, e e por
#: isso que nao podem aparecer duas no mesmo ficheiro.
CHAVE_DA_VERTICAL = "id"
CHAVE_DOS_PLANOS = "plans"
CHAVE_DOS_GATES = "gates"

#: A segunda forma (`registry/plans.yaml`, KAM-009). `version` e o SemVer que a
#: regra 1 do `registry/README.md` impoe a um ficheiro deste directorio.
CHAVES_DE_TOPO_DE_PLANOS = {"version", "plans"}
#: As chaves de um plano. O `nota` existe porque os valores sao hipoteses e a
#: razao de cada uma tem de caber ao lado dela.
CHAVES_DE_PLANO = {"estado", "nota", "entitlements"}
#: As chaves de um entitlement por omissao de um plano: as colunas de
#: `entitlements(tenant_id, modulo, limites jsonb, ativo boolean)` que nao sao
#: do tenant (dicionario §3.2, «Entitlement (tabela)»). O `ativo` nao esta em
#: `CHAVES_DE_ENTITLEMENTS` porque a forma da vertical nao o tem.
CHAVES_DE_ENTITLEMENT_DE_PLANO = {"modulo", "ativo", "limites"}

#: O unico `estado` que o canon escreve para uma entrada de `plans.yaml`
#: (dicionario §4, «Lista de planos e os seus limites»; `specs/EPIC-11`,
#: KAM-124). Esta no **codigo** e nao na politica pela razao das sentinelas
#: minimas: um plano deixa de ser hipotese quando alguem o decidir, e essa
#: decisao e uma alteracao de codigo com revisao — nao uma linha nova num
#: ficheiro de configuracao.
ESTADOS_DE_PLANO = {"hipotese_nao_validada"}

#: A terceira forma (`registry/gates.yaml`, KAM-027). O `version` e o mesmo
#: SemVer que a regra 1 do `registry/README.md` impoe a todo o directorio.
CHAVES_DE_TOPO_DE_GATES = {"version", "gates"}
#: As chaves de uma entrada de gate. O `golden` e o caminho do dataset — o
#: mesmo que a vertical declara em `golden.dataset`, e quem confronta os dois e
#: o `load_all` do AGR, nao este lint: aqui nao se le a vertical ao lado.
CHAVES_DE_GATE = {"golden", "validacoes"}
#: As chaves do modo de uma validacao.
CHAVES_DE_VALIDACAO = {"modo", "credor"}

#: Os nomes das seis validacoes de arranque, pela ordem de `docs/tecnica/02`
#: §5.2 (dicionario §3.26). Lista **fechada**, e no codigo e nao na politica
#: pela razao das sentinelas minimas: uma validacao nova e uma alteracao do
#: `load_all`, com revisao — nao uma linha nova num ficheiro de configuracao.
VALIDACOES_DO_ARRANQUE = (
    "tools", "entitlements", "grafo", "subscriptions", "fase", "golden",
)

#: `bloqueio` e a omissao: uma validacao que o ficheiro nao nomeie falha
#: fechada. So o `aviso` se escreve, e so ele exige `credor`.
MODO_DE_AVISO = "aviso"
MODOS_DE_VALIDACAO = {MODO_DE_AVISO, "bloqueio"}

#: A forma de um ticket, para o `credor`. A mesma de `dicionario.py`.
_TICKET = re.compile(r"^KAM-\d{3}$")

_CHAVES_DE_NOME = ("nome", "name", "id", "tool")
_CHAVES_DE_PARAMETROS = ("parametros", "params", "args", "argumentos")
CHAVES_DE_TOOL = set(_CHAVES_DE_NOME) | set(_CHAVES_DE_PARAMETROS) | {"descricao", "classe", "confirmacao"}


def chaves_de_limite(politica) -> set[str]:
    """As chaves de `limites` que a linha «Entitlement (chaves)» do §3.2 da.

    **Filtra pela forma, e isso nao e cosmetica.** O exportador colhe TODOS os
    nomes entre crases da linha, e essa linha escreve `ManualProvider` em prosa
    («limite do `ManualProvider`»): sem o filtro, um `limites: [ManualProvider]`
    passava o gate como se fosse uma chave de tecto, e do outro lado a coluna
    `tenant_usage.chave_limite` recusa-o pelo `CHECK` de forma. Um nome que o
    PostgreSQL nao aceita nao pode ser aceite aqui.
    """
    return {n for n in politica.limites["nomes"] if _FORMA_DE_CHAVE_DE_LIMITE.match(n)}


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

    def nivel2(tipo: str, nome, qualificado: str | None = None) -> None:
        if not isinstance(nome, str) or not nome:
            achados.append(Achado(ficheiro, 0, ILEGIVEL, f"{tipo} sem nome legivel: {nome!r}"))
            return
        if nome in ja:
            return  # variante, ja reportada
        if not aceita(saber, tipo, qualificado or nome, simples=nome):
            achados.append(fora(ficheiro, _linha_de(fonte, nome), tipo, qualificado or nome))

    verticais = dicionario.dominios.get("id", {}).get("valores", [])

    # --- o que as duas formas partilham ---------------------------------------------

    def modulo_de(modulo) -> None:
        """`modulo` — as verticais do §3.2 mais os modulos de entrada do §3.7."""
        modulos = verticais + dicionario.dominios.get("modulo", {}).get("valores", [])
        if modulo is not None and modulo not in modulos and not saber.extensoes.tem("modulo", str(modulo)):
            achados.append(
                fora(ficheiro, _linha_de(fonte, str(modulo)), "modulo", str(modulo),
                     f"`modulo` ∈ {{{', '.join(dict.fromkeys(modulos))}}}, dicionário §3.2 e §3.7")
            )

    def limite_de(limite) -> None:
        """Um nome de limite contra as dez chaves do dicionario §3.2.

        A **mesma** regra nas duas formas: na vertical `limites` e uma lista de
        nomes, num plano e um mapa nome -> valor, e os nomes confrontam-se com
        a mesma linha do dicionario. E este confronto que torna o `plans.yaml`
        util — sem ele o ficheiro era texto, e um `mensagens_mes` escrito em vez
        de `msgs_ai_mes` so dava sinal no dia em que um tenant batesse num tecto
        que nao existe.
        """
        if not isinstance(limite, str):
            achados.append(Achado(ficheiro, 0, ILEGIVEL, f"limite que nao e um nome: {limite!r}"))
        elif limite in ja:
            return  # variante, ja reportada
        elif limite not in chaves_de_limite(politica) and not saber.extensoes.tem("limite", limite):
            achados.append(
                fora(ficheiro, _linha_de(fonte, limite), "limite", limite,
                     f"`{politica.limites['canonico']}`, dicionário §{politica.limites['seccao']}")
            )

    # --- primeira forma: uma vertical (`docs/tecnica/02` §5.1) ----------------------

    def forma_de_vertical() -> str:
        """Verifica a forma da vertical. Devolve o `id`, ou `""` se nao o tiver."""
        chaves(documento, CHAVES_DE_TOPO, "no topo do ficheiro")

        # --- id -----------------------------------------------------------------
        vertical = documento.get("id")
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

        # --- entitlements -------------------------------------------------------
        entitlements = documento.get("entitlements")
        if isinstance(entitlements, dict):
            chaves(entitlements, CHAVES_DE_ENTITLEMENTS, "em `entitlements`")
            modulo_de(entitlements.get("modulo"))
            limites = entitlements.get("limites")
            if limites is not None and not isinstance(limites, list):
                achados.append(Achado(ficheiro, 0, ILEGIVEL, "`entitlements.limites` nao e uma lista"))
                limites = []
            for limite in limites or []:
                limite_de(limite)
        elif entitlements is not None:
            achados.append(Achado(ficheiro, 0, ILEGIVEL, "`entitlements` nao e um mapa"))

        # --- subscricoes --------------------------------------------------------
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

        # --- tools e parametros -------------------------------------------------
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
        return vertical

    # --- segunda forma: os planos (`registry/plans.yaml`, KAM-009) ------------------

    def forma_de_planos() -> None:
        """`plans: {<plano>: {estado, nota, entitlements: [{modulo, ativo, limites}]}}`.

        A forma e a da tabela que o provisionamento (KAM-091) vai escrever —
        `entitlements(tenant_id, modulo, limites jsonb, ativo boolean)`,
        dicionario §3.2 — menos o tenant, que e o que um plano por omissao nao
        tem. Um plano que nao diga o `modulo` nao se consegue provisionar, e um
        mapa plano -> limites sem modulo nenhum nao seria uma omissao desta
        tabela: seria outra coisa, sem sitio onde aterrar.
        """
        chaves(documento, CHAVES_DE_TOPO_DE_PLANOS, "no topo do ficheiro de planos")
        planos = documento.get(CHAVE_DOS_PLANOS)
        if not isinstance(planos, dict) or not planos:
            achados.append(
                Achado(ficheiro, _linha_de(fonte, CHAVE_DOS_PLANOS), ILEGIVEL,
                       f"`{CHAVE_DOS_PLANOS}` tem de ser um mapa com pelo menos um plano "
                       "(`<plano>:` com `estado` e `entitlements`)")
            )
            return
        for nome, plano in planos.items():
            onde = f"no plano `{nome}`"
            linha = _linha_de(fonte, str(nome))
            if not isinstance(plano, dict):
                achados.append(Achado(ficheiro, linha, ILEGIVEL, f"o plano `{nome}` nao e um mapa"))
                continue
            chaves(plano, CHAVES_DE_PLANO, onde)

            estado = plano.get("estado")
            if estado is None:
                achados.append(
                    Achado(ficheiro, linha, REGRA,
                           f"o plano `{nome}` nao declara `estado`. O dicionário §4 («Lista de planos e "
                           "os seus limites») diz que este ficheiro «nasce com valores **de exemplo**, "
                           "marcados `estado: hipotese_nao_validada`»: nenhum documento tem a tabela de "
                           "planos, e um valor sem essa marca passa a ser lido como decisão")
                )
            elif estado not in ESTADOS_DE_PLANO:
                achados.append(
                    Achado(ficheiro, _linha_de(fonte, str(estado)), REGRA,
                           f"`estado: {estado}` {onde}: o único valor que o canon escreve é "
                           f"`{sorted(ESTADOS_DE_PLANO)[0]}` (dicionário §4, «Lista de planos e os seus "
                           "limites»; `specs/EPIC-11`, KAM-124). Um plano deixa de ser hipótese quando "
                           "alguém o decidir, e essa decisão altera `ESTADOS_DE_PLANO` em "
                           "`tools/canon_lint/registo.py`, com revisão")
                )

            entitlements = plano.get("entitlements")
            if not isinstance(entitlements, list) or not entitlements:
                achados.append(
                    Achado(ficheiro, linha, ILEGIVEL,
                           f"o plano `{nome}` nao tem uma lista `entitlements` com pelo menos uma entrada; "
                           "um plano que nao mapeia modulo nenhum nao da entitlement nenhum")
                )
                continue
            for item in entitlements:
                if not isinstance(item, dict):
                    achados.append(
                        Achado(ficheiro, linha, ILEGIVEL, f"entitlement de forma desconhecida {onde}: {item!r}")
                    )
                    continue
                chaves(item, CHAVES_DE_ENTITLEMENT_DE_PLANO, f"num entitlement {onde}")

                modulo = item.get("modulo")
                if not isinstance(modulo, str) or not modulo:
                    achados.append(
                        Achado(ficheiro, linha, REGRA,
                               f"entitlement sem `modulo` {onde}: a chave de `entitlements` e "
                               "`(tenant_id, modulo)` (dicionário §3.2), e sem o módulo o "
                               "provisionamento (KAM-091) nao tem onde escrever esta linha")
                    )
                else:
                    modulo_de(modulo)

                ativo = item.get("ativo")
                if ativo is not None and not isinstance(ativo, bool):
                    achados.append(
                        Achado(ficheiro, _linha_de(fonte, "ativo"), ILEGIVEL,
                               f"`ativo` {onde} vale {ativo!r}: `entitlements.ativo` e `boolean` "
                               "(dicionário §3.2) e aqui so `true` ou `false` se leem")
                    )

                limites = item.get("limites")
                if not isinstance(limites, dict) or not limites:
                    achados.append(
                        Achado(ficheiro, linha, ILEGIVEL,
                               f"`limites` de um entitlement {onde} tem de ser um mapa `chave: valor` com "
                               "pelo menos uma chave; na forma da vertical e uma lista de nomes, aqui e um "
                               "mapa porque um plano da o **valor** por omissao")
                    )
                    continue
                for chave_limite, valor in limites.items():
                    limite_de(chave_limite)
                    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
                        achados.append(
                            Achado(ficheiro, _linha_de(fonte, str(chave_limite)), ILEGIVEL,
                                   f"o limite `{chave_limite}` {onde} vale {valor!r}: tem de ser um inteiro "
                                   "nao negativo. Do outro lado esta `limites jsonb` e a aritmética de "
                                   "`platform.ten_consumir` (revisão `0007`), que compara `bigint`")
                        )

    # --- terceira forma: os gates (`registry/gates.yaml`, KAM-027) ------------------

    def forma_de_gates() -> None:
        """`gates: {<vertical>: {golden, validacoes: {<validacao>: {modo, credor}}}}`.

        O que este ficheiro guarda e o **modo** de cada uma das seis validacoes
        de arranque do `docs/tecnica/02` §5.2: `bloqueio` (a omissao, que nao se
        escreve) ou `aviso` com o ticket que a desbloqueia. Tres validacoes
        nascem em `aviso` porque a fonte delas nao existe — o catalogo da
        ToolLayer (KAM-028), um grafo compilado (KAM-031/035) e o dataset
        *golden* (KAM-040) —, e e o critero 8 do bloco do KAM-027 que manda
        regista-lo aqui em vez de num interruptor de codigo.
        """
        chaves(documento, CHAVES_DE_TOPO_DE_GATES, "no topo do ficheiro de gates")
        gates = documento.get(CHAVE_DOS_GATES)
        if not isinstance(gates, dict) or not gates:
            achados.append(
                Achado(ficheiro, _linha_de(fonte, CHAVE_DOS_GATES), ILEGIVEL,
                       f"`{CHAVE_DOS_GATES}` tem de ser um mapa com pelo menos uma vertical "
                       "(`<vertical>:` com `validacoes`)")
            )
            return
        for nome, gate in gates.items():
            onde = f"no gate de `{nome}`"
            linha = _linha_de(fonte, str(nome))
            if nome not in verticais and not saber.extensoes.tem("vertical", str(nome)):
                achados.append(
                    fora(ficheiro, linha, "vertical", str(nome),
                         f"a chave de um gate e uma vertical ∈ {{{', '.join(verticais)}}}, "
                         f"dicionário §{politica.verticais['seccao']}")
                )
            if not isinstance(gate, dict):
                achados.append(Achado(ficheiro, linha, ILEGIVEL, f"o gate de `{nome}` nao e um mapa"))
                continue
            chaves(gate, CHAVES_DE_GATE, onde)

            # **O `golden` e obrigatorio, e nao era.** O `GateDaVertical` do AGR
            # exige-o (o `load_all` confronta-o com o `golden.dataset` da
            # vertical), e sem esta verificacao um `gates.yaml` sem ele passava
            # o *gate* 3b e o AGR saia com 5 em producao — o CI verde a dizer
            # que estava bem. Achado da revisao adversarial do KAM-027.
            if not isinstance(gate.get("golden"), str) or not gate["golden"]:
                achados.append(
                    Achado(ficheiro, linha, REGRA,
                           f"o gate de `{nome}` nao declara `golden` com o caminho do dataset. "
                           "O `load_all` do AGR exige que ele coincida com o `golden.dataset` "
                           "da vertical, e sem ele o arranque sai com 5 — este gate existe "
                           "para o CI dizer isso antes de producao")
                )

            validacoes = gate.get("validacoes")
            if not isinstance(validacoes, dict) or not validacoes:
                achados.append(
                    Achado(ficheiro, linha, ILEGIVEL,
                           f"o gate de `{nome}` nao tem um mapa `validacoes` com pelo menos uma entrada. "
                           "Um gate sem validacao nenhuma nao diz nada: `bloqueio` e a omissao, pelo que "
                           "quem nao tem nada a declarar nao escreve a vertical aqui")
                )
                continue
            for validacao, modo in validacoes.items():
                if validacao not in VALIDACOES_DO_ARRANQUE:
                    achados.append(
                        Achado(ficheiro, _linha_de(fonte, str(validacao)), REGRA,
                               f"`{validacao}` {onde} nao e uma das seis validacoes de arranque "
                               f"({', '.join(VALIDACOES_DO_ARRANQUE)}; `docs/tecnica/02` §5.2, dicionário "
                               "§3.26). Um nome a mais aqui e uma validacao que o `load_all` nunca ve: o "
                               "modo ficava por aplicar e a validacao corria em `bloqueio` sem ninguem "
                               "saber — ou, pior, o contrario, se o nome errado fosse o da que se queria "
                               "deixar em `aviso`")
                    )
                    continue
                if not isinstance(modo, dict):
                    achados.append(
                        Achado(ficheiro, linha, ILEGIVEL,
                               f"`{validacao}` {onde} nao e um mapa `{{modo, credor}}`: {modo!r}")
                    )
                    continue
                chaves(modo, CHAVES_DE_VALIDACAO, f"na validacao `{validacao}` {onde}")
                valor = modo.get("modo")
                if valor not in MODOS_DE_VALIDACAO:
                    achados.append(
                        Achado(ficheiro, _linha_de(fonte, str(valor)), REGRA,
                               f"`modo: {valor}` na validacao `{validacao}` {onde}: os modos sao "
                               f"{', '.join(sorted(MODOS_DE_VALIDACAO))} (dicionário §3.26). O "
                               "`docs/tecnica/02` §5.1 escreve `warn`, que e o nome antigo")
                    )
                    # E **nao** se julga o `credor` por cima disto: com um modo
                    # que o lint nao reconhece, a regra «o credor e de quem
                    # espera» daria um segundo achado para o mesmo defeito, e
                    # diria o contrario do que devia se o modo pretendido fosse
                    # `aviso` mal escrito. Um defeito, um achado.
                    continue
                credor = modo.get("credor")
                if valor == MODO_DE_AVISO and (not isinstance(credor, str) or not _TICKET.match(credor)):
                    achados.append(
                        Achado(ficheiro, linha, REGRA,
                               f"`modo: {MODO_DE_AVISO}` na validacao `{validacao}` {onde} sem `credor` com "
                               f"a forma `KAM-NNN` (recebido: {credor!r}). Um atalho sem o ticket que o "
                               "fecha nao e atalho: e uma validacao desligada para sempre com ar de "
                               "temporaria")
                    )
                elif valor != MODO_DE_AVISO and credor is not None:
                    achados.append(
                        Achado(ficheiro, linha, REGRA,
                               f"`credor: {credor}` na validacao `{validacao}` {onde} com "
                               f"`modo: {valor}`: o credor e de quem espera. Em `bloqueio` nao ha nada "
                               "por que esperar, e a linha so sobrevive a quem a devia ter apagado")
                    )

    # --- qual das tres formas e esta -------------------------------------------------
    #
    # Pela chave de topo, e nunca pelo nome do ficheiro: um `planos.yaml`, um
    # `plans-piloto.yaml` ou um `tarifas.yaml` sao o mesmo ficheiro, e adivinhar
    # pelo nome punha a verificacao a depender de como alguem lhe chamou.
    declaradas = [
        chave
        for chave in (CHAVE_DA_VERTICAL, CHAVE_DOS_PLANOS, CHAVE_DOS_GATES)
        if chave in documento
    ]
    vertical = ""
    if len(declaradas) > 1:
        achados.append(
            Achado(ficheiro, _linha_de(fonte, declaradas[1]), REGRA,
                   f"o ficheiro declara {' e '.join(f'`{c}`' for c in declaradas)}: sao chaves de forma "
                   "desta superficie e nao se misturam. O gate 3b nao escolhe por si qual das "
                   "verificacoes se aplica")
        )
    elif declaradas == [CHAVE_DOS_PLANOS]:
        forma_de_planos()
    elif declaradas == [CHAVE_DOS_GATES]:
        forma_de_gates()
    elif declaradas == [CHAVE_DA_VERTICAL]:
        vertical = forma_de_vertical()
    else:
        achados.append(
            Achado(ficheiro, 0, REGRA,
                   f"ficheiro do registo sem `{CHAVE_DA_VERTICAL}` (vertical, `docs/tecnica/02` §5.1), sem "
                   f"`{CHAVE_DOS_PLANOS}` (planos, `registry/plans.yaml`) e sem `{CHAVE_DOS_GATES}` "
                   "(gates, `registry/gates.yaml`): sao as tres unicas formas desta superficie, e um "
                   "ficheiro que nao e nenhuma delas nao passa por nao ter sido lido")
        )

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
