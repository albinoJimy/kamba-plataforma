"""CLI do gerador de configuracao do proxy (KAM-030).

    python -m llm_config --root . escrever    gera llm/litellm.config.yaml e o lock
    python -m llm_config --root . check       confirma que os dois estao em dia

O `check` e o que corre no *lint*: o passo `aliases` do `lint_arch` chama-o. O
`escrever` e o que uma pessoa corre depois de mexer nos aliases — e, por desenho,
**nao** sobe a versao sozinho: subir a versao e a decisao que o criterio 7
protege, e uma ferramenta que a tomasse tornava o *gate* um enfeite.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (
    ALIASES,
    CONFIG,
    LOCK,
    AliasesInvalidos,
    BumpEmFalta,
    impressao,
    ler,
    render,
)


def _escrever_lf(caminho: Path, texto: str) -> None:
    """Escreve com LF. O `pathlib.write_text` poe CRLF em Windows."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(texto.encode("utf-8").replace(b"\r\n", b"\n"))


def _texto_do_lock(versao: str, hash_: str) -> str:
    return (
        "# GERADO por `python -m llm_config --root . escrever`. NAO EDITAR A MAO.\n"
        "#\n"
        f"# Fixa o par (versao, hash do conteudo) de {ALIASES}. O hash **nao**\n"
        "# inclui a `versao`: e isso que torna «mudou o conteudo e nao a versao»\n"
        "# detectavel, que e o criterio 7 do KAM-030.\n"
        "#\n"
        "# Mudar o modelo atras de um alias e um *release*: sobe-se a `versao` em\n"
        f"# {ALIASES}, corre-se `escrever`, e os dois ficheiros gerados entram no\n"
        "# mesmo *commit*. O Gate 13 (eval golden PT-AO) e a outra metade do\n"
        "# criterio e nasce com o KAM-040.\n"
        "\n"
        "version: 1\n"
        f'versao: "{versao}"\n'
        f'sha256: "{hash_}"\n'
    )


def escrever(raiz: Path) -> int:
    """Gera a configuracao e o *lock*. **Recusa-se** se faltar o *bump*.

    **E aqui que o criterio 7 vive, e nao so no `check`.** A primeira versao
    desta funcao reescrevia o *lock* com a `versao` actual e o *hash* novo, pelo
    que o fluxo que a documentacao manda seguir — «mude o alias, corra
    `escrever`» — deixava o `check` conforme **sem *bump* nenhum**: o que o
    *lint* apanhava era «esqueceu-se de regenerar», que e outra coisa. Trocar
    `por_decidir` por um modelo a serio e correr `escrever` dava exit 0 com a
    versao em 1.0.0, e o proxy passava a servir um modelo que o artefacto
    versionado nunca nomeou. Encontrado pela revisao adversarial, medido.

    A guarda e simetrica a do `check` e **nao precisa do ramo base**: se existe
    um *lock* cuja `versao` e igual a dos aliases e cujo *hash* e **diferente**,
    entao o conteudo mudou depois de aquela versao ter sido fixada — e isso e
    exactamente o que o criterio proibe. Subir a versao e o que o autoriza.
    """
    from kamba_yaml import YamlSubsetError, load_file

    dados = ler(raiz)
    versao = str(dados["versao"])
    agora = impressao(dados)

    caminho_lock = raiz / LOCK
    if caminho_lock.is_file():
        try:
            lock = load_file(caminho_lock)
        except YamlSubsetError:
            lock = {}
        if str(lock.get("versao", "")) == versao and str(lock.get("sha256", "")) != agora:
            raise BumpEmFalta(
                f"o conteudo de {ALIASES} mudou e a `versao` continua em {versao}. "
                "Um alias e um artefacto comportamental: mudar o modelo atras dele "
                "exige *bump* SemVer (criterio 7 do KAM-030). Suba a `versao` em "
                f"{ALIASES} e volte a correr este comando"
            )

    _escrever_lf(raiz / CONFIG, render(dados))
    _escrever_lf(raiz / LOCK, _texto_do_lock(versao, agora))
    print(f"llm_config: {CONFIG} e {LOCK} escritos (versao {versao})")
    return 0


def check(raiz: Path) -> list[str]:
    """Os achados. Lista vazia significa conforme."""
    from kamba_yaml import YamlSubsetError, load_file

    achados: list[str] = []
    dados = ler(raiz)
    versao = str(dados["versao"])

    caminho_config = raiz / CONFIG
    esperado = render(dados)
    if not caminho_config.is_file():
        achados.append(
            f"{CONFIG} nao existe. Corra `python -m llm_config --root . escrever`"
        )
    elif caminho_config.read_text(encoding="utf-8") != esperado:
        achados.append(
            f"{CONFIG} nao corresponde a {ALIASES}: o proxy serviria um modelo que o "
            "artefacto versionado nao nomeia. Corra "
            "`python -m llm_config --root . escrever`"
        )

    caminho_lock = raiz / LOCK
    if not caminho_lock.is_file():
        achados.append(f"{LOCK} nao existe. Corra `python -m llm_config --root . escrever`")
        return achados
    try:
        lock = load_file(caminho_lock)
    except YamlSubsetError as excepcao:
        achados.append(f"{LOCK}: ilegivel: {excepcao}")
        return achados

    achados += _achados_dos_precos(raiz)

    agora = impressao(dados)
    guardado = str(lock.get("sha256", ""))
    versao_guardada = str(lock.get("versao", ""))
    if guardado != agora:
        if versao_guardada == versao:
            achados.append(
                f"o conteudo de {ALIASES} mudou e a `versao` continua em {versao}. "
                "Um alias e um artefacto comportamental: mudar o modelo atras dele "
                "exige *bump* SemVer (criterio 7 do KAM-030). Suba a versao e corra "
                "`python -m llm_config --root . escrever`"
            )
        else:
            achados.append(
                f"{LOCK} fixa a versao {versao_guardada} e {ALIASES} diz {versao}: "
                "o *lock* ficou atras. Corra `python -m llm_config --root . escrever`"
            )
    elif versao_guardada != versao:
        achados.append(
            f"{LOCK} e {ALIASES} discordam na versao ({versao_guardada} contra "
            f"{versao}) com o mesmo conteudo: uma das duas foi editada a mao"
        )
    return achados


def _achados_dos_precos(raiz: Path) -> list[str]:
    """O `llm/precos.yaml` tambem passa por maquina antes do arranque.

    **Nao passava, e e o ficheiro que decide o `custo_usd` de toda a linha de
    `dat.llm_call_log`** (achado 14 da revisao adversarial). Duas consequencias
    reais: um `entrada: "O.10"` com a letra O passava todos os *gates* e punha o
    AGR a sair com **7** no arranque seguinte, em producao; e baixar uma tarifa
    reescrevia o custo registado de todas as chamadas futuras sem *bump*, sem
    *lock* e sem rasto — e o DoD de custo apoia-se nesse numero.

    O ficheiro **nao** entra no *lock*: ele e um catalogo de candidatos (KAM-040)
    e muda quando um fornecedor muda a tarifa, que nao e um *release* do produto.
    O que se verifica e que se le, que as linhas estao completas, e que nenhuma
    tarifa **que um alias usa** esta expirada.
    """
    import sys as _sys

    # A partir da arvore onde **esta ferramenta** vive, e nao da arvore que ela
    # linta. O calculo de precos e codigo do projecto (`kamba_agr.llm.precos`,
    # a mesma implementacao que o AGR usa, de proposito); o `llm/precos.yaml` e
    # dado da arvore-alvo. Confundir os dois fazia o `raiz` de um teste — que e
    # uma arvore temporaria com `llm/` e mais nada — nao ter onde achar o
    # modulo: tres baterias so passavam onde o `services/agr/src` estivesse no
    # `sys.path` por outra via, e nesta maquina estava, por um `kamba.pth` do
    # `.venv` feito a mao. No *runner* nao estava.
    servicos = str(Path(__file__).resolve().parents[2] / "services" / "agr" / "src")
    if servicos not in _sys.path:
        _sys.path.insert(0, servicos)
    try:
        from kamba_agr.llm import precos as precos_mod
    except ImportError as excepcao:  # pragma: no cover — arvore incompleta
        return [f"nao se conseguiu ler o calculo de precos: {excepcao}"]

    pasta = raiz / "llm"
    if not (pasta / precos_mod.FICHEIRO).is_file():
        return [f"llm/{precos_mod.FICHEIRO} nao existe"]
    try:
        tabela = precos_mod.carregar(pasta)
    except Exception as excepcao:  # noqa: BLE001 — a razao vai na mensagem
        return [f"llm/{precos_mod.FICHEIRO}: {excepcao}"]

    dados = ler(raiz)
    em_uso = {
        (str(f["fornecedor"]), str(f["modelo"])) for f in dados["fornecedores"]
    }
    try:
        precos_mod.sem_expirados(tabela, em_uso)
    except Exception as excepcao:  # noqa: BLE001 — a razao vai na mensagem
        return [str(excepcao)]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="llm_config", description="Gerador da configuracao do proxy LiteLLM"
    )
    parser.add_argument("--root", type=Path, default=Path("."), help="raiz do repositorio")
    parser.add_argument("comando", choices=("escrever", "check"))
    args = parser.parse_args(argv)
    raiz = args.root.resolve()

    try:
        if args.comando == "escrever":
            return escrever(raiz)
        achados = check(raiz)
    except BumpEmFalta as excepcao:
        print(f"llm_config: {excepcao}", file=sys.stderr)
        return 1
    except AliasesInvalidos as excepcao:
        print(f"llm_config: {ALIASES} invalido: {excepcao}", file=sys.stderr)
        return 2
    except OSError as excepcao:
        print(f"llm_config: erro de ficheiro: {excepcao}", file=sys.stderr)
        return 2

    if not achados:
        print("llm_config: aliases: conforme")
        return 0
    print(f"llm_config: aliases: {len(achados)} achado(s)", file=sys.stderr)
    for achado in achados:
        print(f"  - {achado}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
