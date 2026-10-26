"""Gera a configuracao do proxy LiteLLM a partir de `llm/aliases.yaml` (KAM-030).

**Porque e que ha um gerador e nao dois ficheiros a mao.** O `llm/aliases.yaml` e
o artefacto comportamental: tem `versao` em SemVer, esta fixado por *hash* e e
ele que o criterio 7 protege. O proxy, por seu lado, quer o seu proprio esquema
(`model_list`, `router_settings`, `general_settings`). Escrever os dois a mao
punha o produto a servir um modelo que o artefacto versionado nao nomeia — que e
exactamente a falha que o criterio 7 existe para fechar. Gera-se um do outro, e
o *lint* confirma que o gerado esta em dia.

E o mesmo desenho do `canon/dicionario.yaml`, que e gerado de
`specs/02_Dicionario_de_Dados_Canonico.md` por `tools/dict_export` e **e**
versionado: o ficheiro gerado entra no repositorio para que um diff o mostre, e
uma ferramenta confirma que nao divergiu.

## O que o gerador decide, e o que recusa decidir

Escreve uma entrada de `model_list` por linha de `fornecedores`. A de `ordem: 1`
leva o nome do alias; as seguintes levam `<alias>-fallback<ordem>`, e ligam-se a
primeira por um `fallbacks` explicito.

**Isto diverge da amostra de configuracao do `docs/tecnica/02` §13.1, e a
divergencia saiu de uma medicao.** O §13.1 escreve duas entradas com o **mesmo**
`model_name` (um *grupo* de dois *deployments*) e conta com o `num_retries: 1`
para comutar. Medido na imagem fixada, 20 corridas com o primario a falhar
sempre: a estrategia por omissao e `simple-shuffle` — **aleatoria** —, e das 9
corridas que comecaram no fornecedor avariado so 6 passaram para o outro. **Tres
das 20 falharam por completo**, porque o unico *retry* reescolheu o mesmo
*deployment* avariado.

Ou seja: a amostra do §13.1, a letra, **nao cumpre o criterio 6** («comuta para o
segundo aprovado em <= 1 retry»), e num grupo aleatorio nao existe «fornecedor
primario» nenhum — a `ordem` do `llm/aliases.yaml` nao teria efeito. Com dois
grupos e um `fallbacks` nomeado, a ordem e deterministica e uma falha do primeiro
cai sempre no segundo. O `docs/tecnica/02` §13.1 fica corrigido por esta medicao,
e a divergencia esta registada na emenda 1.38 e em `docs/dividas-documentais.md`.

**O `api_key` e `os.environ/<nome>` e o nome e derivado, nunca escrito.** Vem de
`kamba_core.secrets.env.nome_da_variavel("llm_provider_key/<fornecedor>")`, que
e a referencia que `ops/secrets-inventory.yaml` declara («a referencia e
`llm_provider_key/<provedor>`»). Derivar em vez de escrever e a licao que o
KAM-027 pagou: «uma lista literal transforma uma invariante num numero» — e aqui
um nome escrito a mao era um segredo que o `tools/secrets_inventory` nao
encontrava no inventario, ou pior, encontrava com outro nome.

**Nao escreve `api_base`.** Um ensaio contra fornecedores falsos aponta-os pelas
variaveis do proprio fornecedor (`ANTHROPIC_API_BASE`, `OPENAI_API_BASE`), que o
LiteLLM le; po-las aqui era meter o endereco de um duplo de teste no ficheiro
que descreve producao.

**Nao escolhe modelos.** O `modelo` sai de `llm/aliases.yaml` como esta — hoje
`por_decidir` em todas as linhas, com o credor KAM-040 ao lado.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Final

from kamba_yaml import load_file

#: A fonte: o artefacto comportamental versionado.
ALIASES: Final = "llm/aliases.yaml"

#: O gerado, que o compose monta `:ro`.
CONFIG: Final = "llm/litellm.config.yaml"

#: O *lock* que fixa o par (versao, hash do conteudo). Criterio 7.
LOCK: Final = "ci/llm-aliases.lock"

#: A referencia de segredo da *master key*, do `ops/secrets-inventory.yaml`.
REF_MASTER_KEY: Final = "litellm_master_key"

#: A familia das chaves de fornecedor. A instancia e o nome do fornecedor:
#: `llm_provider_key/anthropic`. O inventario di-lo por extenso.
FAMILIA_DA_CHAVE: Final = "llm_provider_key"

#: Os fornecedores de LLM do inventario de subprocessadores (`docs/tecnica/08`
#: §8.3.2). Lista **fechada**: um `fornecedor` fora dela e um destino de
#: transferencia que ninguem registou, e o *lint* recusa-o.
#:
#: Sao tres dos onze: os outros oito do inventario (Meta, alojamento, CDN/WAF,
#: facilitador, software AGT, Doppler, e-mail/SMS, Groq) nao servem modelos de
#: linguagem. O Groq e STT e entra com o KAM-036.
FORNECEDORES_APROVADOS: Final = ("anthropic", "openai", "google")

#: **O nome do subprocessador nao e o prefixo do proxy**, e confundi-los faz o
#: proxy recusar a configuracao no arranque.
#:
#: Medido na imagem fixada (`litellm.get_llm_provider`, 2026-10-26, CONFIRMADO):
#: `anthropic/` e `openai/` sao aceites, `google/` e **recusado** com
#: `BadRequestError: LLM Provider NOT provided`, e o prefixo do Gemini e
#: `gemini/` (ha tambem `vertex_ai/`, que e outra via de acesso). Dos 162
#: prefixos que a versao reconhece, nenhum se chama `google`.
#:
#: Os dois espacos de nomes ficam separados de proposito e **nao se harmonizam**:
#: o `fornecedor` e o nome do subprocessador do `docs/tecnica/08` §8.3.2, que e o
#: que o ADR-008 e o `tenant_destinations` do KAM-069 usam para autorizar uma
#: transferencia; o prefixo e vocabulario do LiteLLM. Renomear o subprocessador
#: para `gemini` punha o inventario de conformidade a falar a lingua de uma
#: biblioteca, e no dia em que o prefixo mudasse o registo da APD ficava errado.
#:
#: Um fornecedor aprovado sem entrada aqui faz o gerador **levantar**: e melhor
#: do que escrever uma configuracao que o proxy recusa no arranque.
PREFIXO_LITELLM: Final = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "gemini",
}

#: Os papeis que o cliente do AGR expoe. Lista fechada (dicionario §3.29).
PAPEIS: Final = ("router", "chat", "vision", "embed")

#: Estados de um alias, no vocabulario do KAM-027 (dicionario §3.26).
ESTADO_LIGADA: Final = "ligada"
ESTADO_DECLARADA: Final = "declarada"
ESTADOS: Final = (ESTADO_LIGADA, ESTADO_DECLARADA)

#: O lugar vazio de um modelo que o KAM-040 ainda nao escolheu.
POR_DECIDIR: Final = "por_decidir"


class AliasesInvalidos(ValueError):
    """O `llm/aliases.yaml` nao se pode usar. A mensagem diz porque."""


def ler(raiz: Path) -> dict[str, Any]:
    """Le e **valida** os aliases. Levanta `AliasesInvalidos` se nao servirem."""
    dados = load_file(raiz / ALIASES)

    esperadas = {"version", "versao", "router_settings", "aliases", "fornecedores"}
    estranhas = sorted(set(dados) - esperadas)
    if estranhas:
        raise AliasesInvalidos(f"chave(s) que nenhum codigo le: {', '.join(estranhas)}")
    faltam = sorted(esperadas - set(dados))
    if faltam:
        raise AliasesInvalidos(f"chave(s) em falta: {', '.join(faltam)}")
    if dados["version"] != 1:
        raise AliasesInvalidos("'version' tem de ser 1")
    _validar_semver(str(dados["versao"]))

    nomes: list[str] = []
    for alias in dados["aliases"]:
        nome = str(alias.get("nome", ""))
        papel = str(alias.get("papel", ""))
        if papel not in PAPEIS:
            raise AliasesInvalidos(f"{nome}: `papel` fora de {PAPEIS} (lido {papel!r})")
        if alias.get("estado") not in ESTADOS:
            raise AliasesInvalidos(f"{nome}: `estado` fora de {ESTADOS}")
        # Um `declarada` sem credor e um atalho sem o ticket que o fecha, que e a
        # regra que o `registry/gates.yaml` do KAM-027 ja impoe.
        if alias["estado"] == ESTADO_DECLARADA and not _e_ticket(alias.get("credor")):
            raise AliasesInvalidos(
                f"{nome}: `estado: declarada` exige `credor` com a forma KAM-NNN"
            )
        if not isinstance(alias.get("timeout"), int) or alias["timeout"] <= 0:
            raise AliasesInvalidos(f"{nome}: `timeout` tem de ser um inteiro de segundos")
        nomes.append(nome)
    if len(set(nomes)) != len(nomes):
        raise AliasesInvalidos("dois aliases com o mesmo `nome`")

    vistos: set[tuple[str, int]] = set()
    por_alias: dict[str, int] = {}
    for linha in dados["fornecedores"]:
        alias = str(linha.get("alias", ""))
        if alias not in nomes:
            raise AliasesInvalidos(f"fornecedor de um alias que nao existe: {alias!r}")
        fornecedor = str(linha.get("fornecedor", ""))
        if fornecedor not in FORNECEDORES_APROVADOS:
            raise AliasesInvalidos(
                f"{alias}: `{fornecedor}` nao esta nos fornecedores aprovados "
                f"{FORNECEDORES_APROVADOS}. Um fornecedor fora do inventario de "
                "subprocessadores (docs/tecnica/08 §8.3.2) e um destino de "
                "transferencia que ninguem registou (ADR-008, KAM-069)"
            )
        ordem = linha.get("ordem")
        if not isinstance(ordem, int) or ordem < 1:
            raise AliasesInvalidos(f"{alias}: `ordem` tem de ser >= 1")
        if (alias, ordem) in vistos:
            raise AliasesInvalidos(f"{alias}: duas linhas com `ordem: {ordem}`")
        vistos.add((alias, ordem))
        por_alias[alias] = por_alias.get(alias, 0) + 1
        if not str(linha.get("modelo", "")):
            raise AliasesInvalidos(f"{alias}: `modelo` nao pode ser vazio")

    sem_fornecedor = sorted(set(nomes) - set(por_alias))
    if sem_fornecedor:
        raise AliasesInvalidos(
            f"alias sem fornecedor nenhum: {', '.join(sem_fornecedor)}. O proxy "
            "recusa um `model_name` sem entrada em `model_list`"
        )
    # **Todo o alias tem de ter a `ordem: 1`.** E ela que fica com o nome do
    # alias (`nome_do_grupo`), que e o unico nome que o cliente do AGR chama:
    # um alias cujas linhas comecassem na `ordem: 2` gerava `model_list` sem
    # entrada nenhuma chamada `<alias>`, e o proxy respondia 400 a toda a
    # chamada daquele papel. Falha aqui, no gerador, e nao em producao.
    sem_primeira = sorted(
        nome for nome in nomes if (nome, 1) not in vistos
    )
    if sem_primeira:
        raise AliasesInvalidos(
            f"alias sem linha `ordem: 1`: {', '.join(sem_primeira)}. A `ordem: 1` e "
            "a que fica com o nome do alias, que e o que o cliente chama"
        )
    return dados


def _validar_semver(versao: str) -> None:
    partes = versao.split(".")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        raise AliasesInvalidos(f"`versao` tem de ser SemVer MAJOR.MINOR.PATCH: {versao!r}")


def _e_ticket(valor: object) -> bool:
    texto = str(valor or "")
    return (
        len(texto) == 7
        and texto.startswith("KAM-")
        and texto[4:].isdigit()
    )


def nome_do_grupo(alias: str, ordem: int) -> str:
    """O `model_name` de uma linha de fornecedor.

    A `ordem: 1` **e** o alias: e o nome que o cliente do AGR chama e o unico que
    ele conhece. As seguintes ganham sufixo e existem so para o `fallbacks` as
    nomear — ver a nota do modulo sobre porque nao podem partilhar o nome.
    """
    return alias if ordem == 1 else f"{alias}-fallback{ordem}"


def _prefixo(fornecedor: str) -> str:
    """O prefixo do LiteLLM para um subprocessador. Levanta se nao o conhecer."""
    try:
        return PREFIXO_LITELLM[fornecedor]
    except KeyError:
        raise AliasesInvalidos(
            f"`{fornecedor}` e um fornecedor aprovado sem prefixo de LiteLLM em "
            "`PREFIXO_LITELLM`. Sem ele a configuracao gerada e recusada pelo "
            "proxy no arranque (medido: `google/` da `BadRequestError`)"
        ) from None


def nome_da_chave(fornecedor: str) -> str:
    """O nome da variavel da chave do fornecedor. **Derivado**, nunca escrito.

    Importa-se aqui dentro e nao no topo do modulo porque o `lint_arch` corre
    antes de qualquer instalacao e o `libs/py-core` pode nao estar no caminho;
    nesse caso deriva-se pela mesma regra, que esta escrita no `env.py` e e
    confrontada por um teste.
    """
    ref = f"{FAMILIA_DA_CHAVE}/{fornecedor}"
    try:
        from kamba_core.secrets.env import nome_da_variavel
    except ImportError:
        return f"KAMBA_SECRET_{FAMILIA_DA_CHAVE.upper()}__{fornecedor}"
    return nome_da_variavel(ref)


def render(dados: dict[str, Any]) -> str:
    """O texto da configuracao do proxy. Determinista: a mesma entrada, o mesmo texto."""
    aliases = {str(a["nome"]): a for a in dados["aliases"]}
    linhas: list[str] = [
        "# GERADO por `python -m llm_config --root . escrever`. NAO EDITAR A MAO.",
        "#",
        f"# Fonte: {ALIASES} versao {dados['versao']}. Quem muda o comportamento e a",
        "# fonte; este ficheiro e a traducao dela para o esquema do proxy LiteLLM.",
        "# O passo `aliases` do `lint_arch` falha se este ficheiro nao estiver em dia.",
        "",
        "model_list:",
    ]
    fornecedores = sorted(
        dados["fornecedores"], key=lambda f: (str(f["alias"]), int(f["ordem"]))
    )
    for linha in fornecedores:
        alias = aliases[str(linha["alias"])]
        fornecedor = str(linha["fornecedor"])
        linhas += [
            f"  - model_name: {nome_do_grupo(str(linha['alias']), int(linha['ordem']))}",
            "    litellm_params:",
            f"      model: {_prefixo(fornecedor)}/{linha['modelo']}",
            f"      api_key: os.environ/{nome_da_chave(fornecedor)}",
            f"      timeout: {alias['timeout']}",
            "    model_info:",
            # O `papel` e a `ordem` vao no `model_info` porque e o unico sitio
            # do esquema do proxy que aceita campos nossos, e porque e o que o
            # `/model/info` devolve: sem isto, confirmar que o proxy carregou os
            # aliases certos exigia ler o ficheiro em vez de perguntar ao proxy.
            f"      papel: {alias['papel']}",
            f"      ordem: {linha['ordem']}",
            f"      fornecedor: {fornecedor}",
        ]
    linhas += ["", "router_settings:"]
    for chave in sorted(dados["router_settings"]):
        linhas.append(f"  {chave}: {dados['router_settings'][chave]}")
    # O *fallback* e do router e nao do cliente, e e **entre grupos nomeados**:
    # ver a nota do modulo sobre a medicao que obrigou a isto. O cliente chama o
    # alias e e o router que comuta, porque e ele que conhece os dois grupos.
    ordens: dict[str, list[int]] = {}
    for linha in dados["fornecedores"]:
        ordens.setdefault(str(linha["alias"]), []).append(int(linha["ordem"]))
    com_mais = {nome: sorted(o) for nome, o in ordens.items() if len(o) > 1}
    if com_mais:
        linhas.append("  fallbacks:")
        for nome in sorted(com_mais):
            seguintes = ", ".join(
                nome_do_grupo(nome, ordem) for ordem in com_mais[nome][1:]
            )
            linhas.append(f"    - {nome}: [{seguintes}]")
    linhas += [
        "",
        "general_settings:",
        f"  master_key: os.environ/{_nome_master_key()}",
        "",
        "litellm_settings:",
        # **Sem isto o proxy sai para `raw.githubusercontent.com` no arranque**,
        # para descarregar o mapa de precos — um destino que nenhuma lista de
        # saidas declara e que o `infra/egress/litellm.yaml` nao tem. Medido na
        # imagem fixada: o `import litellm` tenta tres vezes e cai para a copia
        # local. E a mesma classe de achado do `beacon.langchain.com` do
        # KAM-025, e fecha-se do mesmo modo: desligar, nao declarar o destino.
        "  turn_off_message_logging: true",
        "",
    ]
    return "\n".join(linhas)


def _nome_master_key() -> str:
    try:
        from kamba_core.secrets.env import nome_da_variavel
    except ImportError:
        return f"KAMBA_SECRET_{REF_MASTER_KEY.upper()}"
    return nome_da_variavel(REF_MASTER_KEY)


def impressao(dados: dict[str, Any]) -> str:
    """`sha256` do conteudo que **nao** e a versao.

    Exclui a `versao` de proposito: e isso que faz «mudou o conteudo e nao a
    versao» ser detectavel. Com a versao dentro do hash, qualquer alteracao
    mudava o hash e o *lock* nunca distinguia as duas situacoes.

    A forma canonica e o texto gerado **sem os comentarios**, e nao os dados
    lidos: o texto e o que o proxy le e e determinista por construcao, e o
    cabecalho gerado nomeia a `versao` — hashear o texto inteiro punha a versao
    dentro do hash e desfazia a propriedade do paragrafo acima. Um comentario
    nao e comportamento, e este ficheiro e gerado: nao ha comentario para
    proteger.
    """
    corpo = "\n".join(
        linha
        for linha in render(dados).splitlines()
        if not linha.lstrip().startswith("#")
    )
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()
