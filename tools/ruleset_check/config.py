"""Leitura do `ci/ruleset.yaml`: que ruleset se verifica, e contra que ficheiro.

Tres valores, e nenhum deles esta no codigo: o repositorio, o `id` do ruleset e
o caminho do espelho. Ficam em configuracao porque o `README.md` do ruleset
reproduz a exportacao com os mesmos tres, e duas copias do mesmo numero em
sitios diferentes e a classe de defeito que este ticket fecha noutro sitio.

As chaves que este leitor conhece estao em `CHAVES`, e uma chave que nao esteja
la e **recusada** (KAM-134, `kamba_yaml.exigir_chaves`): uma chave que ninguem
le e uma promessa que o ficheiro faz e o codigo nao cumpre.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from kamba_yaml import YamlSubsetError, exigir_chaves, load_file

#: Onde vive a configuracao, relativo a raiz do repositorio.
CAMINHO = "ci/ruleset.yaml"

#: As chaves de topo de `ci/ruleset.yaml`. **Todas lidas.** Declarar uma e nao a
#: ler era o defeito que o KAM-134 fechou nos outros catorze leitores.
CHAVES = {"version", "repositorio", "ruleset_id", "espelho"}


class ConfiguracaoInvalida(RuntimeError):
    """O `ci/ruleset.yaml` falta, nao se le, ou diz o que nao devia.

    Nao e um achado: e saida 2. Uma configuracao ilegivel nao pode parecer um
    ruleset conforme.
    """


@dataclasses.dataclass(frozen=True)
class Configuracao:
    #: `dono/repositorio`, como o GitHub o escreve.
    repositorio: str
    #: O `id` numerico do ruleset. Nao e o nome: o nome muda sem aviso e o `id`
    #: e o que a API aceita.
    ruleset_id: int
    #: Caminho do espelho, relativo a raiz.
    espelho: str

    @property
    def caminho_da_api(self) -> str:
        return f"repos/{self.repositorio}/rulesets/{self.ruleset_id}"


def ler(raiz: Path) -> Configuracao:
    ficheiro = raiz / CAMINHO
    if not ficheiro.is_file():
        raise ConfiguracaoInvalida(f"{CAMINHO}: nao existe")
    try:
        dados = load_file(ficheiro)
    except YamlSubsetError as erro:
        raise ConfiguracaoInvalida(f"{CAMINHO}: {erro}") from erro
    exigir_chaves(dados, CHAVES, CAMINHO, ConfiguracaoInvalida)

    em_falta = sorted({"repositorio", "ruleset_id", "espelho"} - set(dados))
    if em_falta:
        raise ConfiguracaoInvalida(f"{CAMINHO}: chave(s) obrigatoria(s) em falta {em_falta}")

    repositorio = dados["repositorio"]
    if not isinstance(repositorio, str) or repositorio.count("/") != 1:
        raise ConfiguracaoInvalida(
            f"{CAMINHO}: `repositorio` tem de ser `dono/repositorio`, esta {repositorio!r}"
        )
    ruleset_id = dados["ruleset_id"]
    if not isinstance(ruleset_id, int) or isinstance(ruleset_id, bool) or ruleset_id <= 0:
        raise ConfiguracaoInvalida(
            f"{CAMINHO}: `ruleset_id` tem de ser um inteiro positivo, esta {ruleset_id!r}"
        )
    espelho = dados["espelho"]
    if not isinstance(espelho, str) or not espelho:
        raise ConfiguracaoInvalida(f"{CAMINHO}: `espelho` tem de ser um caminho")

    return Configuracao(repositorio=repositorio, ruleset_id=ruleset_id, espelho=espelho)
