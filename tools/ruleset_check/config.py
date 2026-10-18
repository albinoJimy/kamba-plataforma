"""Leitura do `ci/ruleset.yaml`: que rulesets se verificam, e contra que ficheiro.

**Uma lista de alvos, e nao um repositorio so.** A razao esta escrita no proprio
`ci/ruleset.yaml` e vale repeti-la aqui, porque foi um defeito a serio: o
espelho `.github/rulesets/main.json` viaja na arvore que vai para os dois
repositorios, e com um alvo so a verificacao corrida do publico lia o ruleset do
privado e dizia «conforme» dentro de um repositorio sem protecao nenhuma.

O `ruleset_id` e **opcional**: o ruleset resolve-se pelo `name` do espelho. Isso
permite declarar um alvo cujo ruleset ainda nao existe — e, enquanto nao
existir, a verificacao desse alvo e vermelha, que e o que se quer.

As chaves que este leitor conhece estao em `CHAVES` e `CHAVES_DE_ALVO`, e uma
chave que nao esteja la e **recusada** (KAM-134, `kamba_yaml.exigir_chaves`):
uma chave que ninguem le e uma promessa que o ficheiro faz e o codigo nao
cumpre.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from kamba_yaml import YamlSubsetError, exigir_chaves, load_file

#: Onde vive a configuracao, relativo a raiz do repositorio.
CAMINHO = "ci/ruleset.yaml"

#: As chaves de topo. **Todas lidas.**
CHAVES = {"version", "alvos"}

#: As chaves de cada alvo. **Todas lidas**, a `razao` incluida: e impressa na
#: mensagem quando o alvo da vermelho, porque quem le o vermelho precisa de
#: saber porque e que aquele repositorio esta na lista.
CHAVES_DE_ALVO = {"repositorio", "espelho", "ruleset_id", "razao"}


class ConfiguracaoInvalida(RuntimeError):
    """O `ci/ruleset.yaml` falta, nao se le, ou diz o que nao devia.

    Nao e um achado: e saida 2. Uma configuracao ilegivel nao pode parecer um
    ruleset conforme.
    """


@dataclasses.dataclass(frozen=True)
class Alvo:
    #: `dono/repositorio`, como o GitHub o escreve.
    repositorio: str
    #: Caminho do espelho, relativo a raiz. Dois alvos podem partilhar o mesmo:
    #: a politica e uma, os repositorios que a tem de aplicar sao dois.
    espelho: str
    #: O `id` numerico, quando ja se conhece. `None` enquanto o ruleset nao
    #: existir, ou enquanto ninguem o tiver escrito aqui.
    ruleset_id: int | None = None
    #: Porque e que este repositorio esta na lista.
    razao: str = ""

    @property
    def caminho_da_lista(self) -> str:
        return f"repos/{self.repositorio}/rulesets"

    def caminho_do_ruleset(self, ruleset_id: int) -> str:
        return f"repos/{self.repositorio}/rulesets/{ruleset_id}"


def ler(raiz: Path) -> list[Alvo]:
    ficheiro = raiz / CAMINHO
    if not ficheiro.is_file():
        raise ConfiguracaoInvalida(f"{CAMINHO}: nao existe")
    try:
        dados = load_file(ficheiro)
    except YamlSubsetError as erro:
        raise ConfiguracaoInvalida(f"{CAMINHO}: {erro}") from erro
    exigir_chaves(dados, CHAVES, CAMINHO, ConfiguracaoInvalida)

    crus = dados.get("alvos")
    if not isinstance(crus, list) or not crus:
        raise ConfiguracaoInvalida(
            f"{CAMINHO}: `alvos` tem de ser uma lista com pelo menos um alvo. Uma "
            "lista vazia faria a verificacao sair 0 sem verificar nada"
        )

    alvos = [_alvo(cru, i) for i, cru in enumerate(crus)]
    repetidos = sorted({a.repositorio for a in alvos if
                        [x.repositorio for x in alvos].count(a.repositorio) > 1})
    if repetidos:
        raise ConfiguracaoInvalida(f"{CAMINHO}: repositorio(s) repetido(s) {repetidos}")
    return alvos


def _alvo(cru: object, indice: int) -> Alvo:
    onde = f"{CAMINHO}: alvos[{indice}]"
    exigir_chaves(cru, CHAVES_DE_ALVO, onde, ConfiguracaoInvalida)
    assert isinstance(cru, dict)  # garantido por `exigir_chaves`

    em_falta = sorted({"repositorio", "espelho"} - set(cru))
    if em_falta:
        raise ConfiguracaoInvalida(f"{onde}: chave(s) obrigatoria(s) em falta {em_falta}")

    repositorio = cru["repositorio"]
    if not isinstance(repositorio, str) or repositorio.count("/") != 1:
        raise ConfiguracaoInvalida(
            f"{onde}: `repositorio` tem de ser `dono/repositorio`, esta {repositorio!r}"
        )
    espelho = cru["espelho"]
    if not isinstance(espelho, str) or not espelho:
        raise ConfiguracaoInvalida(f"{onde}: `espelho` tem de ser um caminho")

    ruleset_id = cru.get("ruleset_id")
    if ruleset_id is not None:
        if not isinstance(ruleset_id, int) or isinstance(ruleset_id, bool) or ruleset_id <= 0:
            raise ConfiguracaoInvalida(
                f"{onde}: `ruleset_id` tem de ser um inteiro positivo ou ficar "
                f"por declarar, esta {ruleset_id!r}"
            )

    razao = cru.get("razao", "")
    if not isinstance(razao, str):
        raise ConfiguracaoInvalida(f"{onde}: `razao` tem de ser texto")

    return Alvo(
        repositorio=repositorio, espelho=espelho, ruleset_id=ruleset_id, razao=razao
    )
