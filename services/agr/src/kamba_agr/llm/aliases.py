"""Os aliases, lidos pelo servico (KAM-030).

## Porque e que ha codigo aqui e nao se importa o `tools/llm_config`

O `tools/llm_config` valida `llm/aliases.yaml` e gera a configuracao do proxy. O
AGR precisa das mesmas listas — os papeis, os fornecedores aprovados, o
mapeamento para o prefixo do LiteLLM, a regra do nome do grupo — e **nao pode
importar de `tools/`**: o `tools/` nao e um pacote instalado e nao esta no
caminho de importacao de um servico (a imagem do AGR leva `services/agr/src` e
`libs/py-core/src`, e nada mais).

E exactamente a situacao que o `ligacao.py` deste servico ja descreveu para o
`db/ligacao.py`, e a resposta e a mesma: **o que impede as duas copias de
divergirem e uma maquina, nao uma intencao.** O
`TestParidadeComOLlmConfig` de `tests/test_llm_aliases.py` carrega o
`tools/llm_config` **pelo caminho** e compara as quatro superficies, uma a uma.
Sem esse teste isto era duplicacao; com ele e uma copia verificada.

O que **nao** se duplica e a validacao: o servico le o ficheiro e confia na forma
porque o *lint* do *gate* 2 ja a recusou se estivesse errada. O que se valida
aqui e so o que o servico precisa para nao rebentar a meio de um turno — um papel
que falte, um alias sem fornecedor.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Final

#: Os papeis que o cliente expoe. Lista fechada (dicionario §3.29).
PAPEIS: Final = ("router", "chat", "vision", "embed")

#: Os fornecedores de LLM do inventario de subprocessadores (`docs/tecnica/08`
#: §8.3.2). Lista fechada: um fornecedor fora dela e um destino de
#: transferencia que ninguem registou (ADR-008).
FORNECEDORES_APROVADOS: Final = ("anthropic", "openai", "google")

#: Nome do subprocessador -> prefixo do LiteLLM. **Nao sao o mesmo espaco de
#: nomes**: medido na imagem fixada, `google/` e recusado e o prefixo do Gemini
#: e `gemini/` (`docs/evidencia/KAM-030-litellm.md` §3).
PREFIXO_LITELLM: Final = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "gemini",
}

#: A pasta com `aliases.yaml` e `precos.yaml`, como o `KAMBA_REGISTRY_DIR` do
#: KAM-027.
VARIAVEL_DA_PASTA: Final = "KAMBA_LLM_DIR"

FICHEIRO: Final = "aliases.yaml"


class AliasesIndisponiveis(RuntimeError):
    """Nao se conseguiu ler `llm/aliases.yaml`. Codigo de saida 7."""


@dataclasses.dataclass(frozen=True, slots=True)
class Alias:
    nome: str
    papel: str
    timeout: int
    #: Os fornecedores que este alias pode alcancar, por `ordem`. O *gate* de
    #: destino e consultado para **todos** — ver `cliente.py`.
    fornecedores: tuple[str, ...]
    modelos: tuple[str, ...]


def nome_do_grupo(alias: str, ordem: int) -> str:
    """O `model_name` de uma linha de fornecedor. A `ordem: 1` **e** o alias.

    A mesma regra do `tools/llm_config.nome_do_grupo`, e o teste de paridade
    confronta-as com varios argumentos — nao so com um.
    """
    return alias if ordem == 1 else f"{alias}-fallback{ordem}"


def prefixo_de(fornecedor: str) -> str:
    """O prefixo do LiteLLM de um fornecedor."""
    return PREFIXO_LITELLM.get(fornecedor, fornecedor)


def ler(pasta: Path) -> dict[str, Alias]:
    """Os aliases **por papel**. Levanta `AliasesIndisponiveis` se nao servirem."""
    from kamba_yaml import YamlSubsetError, load_file

    try:
        dados = load_file(pasta / FICHEIRO)
    except (YamlSubsetError, OSError) as excepcao:
        raise AliasesIndisponiveis(f"{pasta / FICHEIRO}: {excepcao}") from excepcao

    por_alias: dict[str, list[tuple[int, str, str]]] = {}
    for linha in dados.get("fornecedores") or ():
        por_alias.setdefault(str(linha["alias"]), []).append(
            (int(linha["ordem"]), str(linha["fornecedor"]), str(linha["modelo"]))
        )

    saida: dict[str, Alias] = {}
    for bruto in dados.get("aliases") or ():
        papel = str(bruto.get("papel", ""))
        nome = str(bruto.get("nome", ""))
        if papel not in PAPEIS:
            raise AliasesIndisponiveis(f"{nome}: papel `{papel}` fora de {PAPEIS}")
        linhas = sorted(por_alias.get(nome, ()))
        if not linhas or linhas[0][0] != 1:
            raise AliasesIndisponiveis(
                f"{nome}: sem linha `ordem: 1`. E ela que fica com o nome do alias"
            )
        fora = [f for _, f, _ in linhas if f not in FORNECEDORES_APROVADOS]
        if fora:
            # Falha fechada no **arranque** e nao na primeira chamada: um
            # fornecedor fora do inventario e um destino nao registado, e
            # descobri-lo a meio de um turno era descobri-lo depois de os dados
            # saírem.
            raise AliasesIndisponiveis(
                f"{nome}: fornecedor(es) fora do inventario de subprocessadores: "
                f"{fora} (ADR-008, KAM-069)"
            )
        saida[papel] = Alias(
            nome=nome,
            papel=papel,
            timeout=int(bruto["timeout"]),
            fornecedores=tuple(f for _, f, _ in linhas),
            modelos=tuple(m for _, _, m in linhas),
        )

    faltam = sorted(set(PAPEIS) - set(saida))
    if faltam:
        raise AliasesIndisponiveis(
            f"papel(eis) sem alias: {', '.join(faltam)}. O cliente expoe os quatro"
        )
    return saida
