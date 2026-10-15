"""Interface de linha de comando do `lint_refs` (gate 3).

    python -m lint_refs check [--root .]     varre a arvore seguida pelo git
    python -m lint_refs sets  [--root .]     imprime os conjuntos validos
    python -m lint_refs file  <ficheiro>     varre um ficheiro (para depurar)

Codigo de saida 0 = conforme, 1 = achados, 2 = erro de configuracao. A distincao
importa: uma fonte canonica em falta nao pode parecer um repositorio limpo.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file

from . import scan
from .sets import Conjuntos, FonteCanonicaAusente, ler

#: Extensoes **nao** varridas: binarios e artefactos. A lista e de exclusao, e
#: nao de inclusao, e isso e a correccao de um defeito real.
#:
#: A primeira versao tinha uma lista de extensoes permitidas
#: (`{".md", ".py", ".ts", ...}`) mais uma lista de nomes sem extensao. O
#: resultado era que 21 dos 231 ficheiros seguidos pelo git nunca eram varridos
#: — `.txt`, `.in`, `.editorconfig`, `.gitattributes`, `.node-version`,
#: `.nvmrc`, e os tres hooks de `tools/githooks/`, que **ja citavam** `KAM-002`.
#: E `.tsx` e `.mdx` nao estavam la, com um `services/onboarding-web` a espera
#: de os ter. O gate dizia "passa em 100% das referencias" e passava em 100%
#: das que via.
#:
#: Invertida, a fronteira e explicita: varre-se tudo o que o git segue e que
#: descodifique como UTF-8, excepto o que esta aqui. Um tipo de ficheiro novo
#: entra no varrimento sem ninguem se lembrar de o acrescentar.
BINARIOS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".tar", ".whl", ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".mp3", ".pyc",
    ".lock",
}


def _ficheiros_do_git(raiz: Path) -> list[Path]:
    """Os ficheiros seguidos pelo git.

    Usa-se o git em vez de `os.walk` porque `.claude/worktrees/*` sao copias
    completas do repositorio — ignoradas pelo git, visiveis a qualquer
    varrimento do sistema de ficheiros — e cada uma traz o seu `KAM-999`.
    """
    try:
        resultado = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=raiz,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as excepcao:
        raise FonteCanonicaAusente(
            f"nao foi possivel listar os ficheiros do git em {raiz}: {excepcao}"
        ) from excepcao

    caminhos = []
    for bruto in resultado.stdout.decode("utf-8", errors="replace").split("\0"):
        if not bruto:
            continue
        caminho = raiz / bruto
        if not caminho.is_file():
            continue
        if caminho.suffix.lower() in BINARIOS:
            continue
        caminhos.append(caminho)
    return sorted(caminhos)


class Excepcoes:
    """As excepcoes declaradas em `ci/refs-allow.yaml`."""

    def __init__(
        self,
        placeholders: set[str],
        por_ficheiro: dict[str, set[str]],
        areas: tuple[str, ...] = (),
    ) -> None:
        self.placeholders = placeholders
        self.por_ficheiro = por_ficheiro
        #: Ficheiros cujo **tema** sao referencias: a implementacao do gate 3,
        #: os seus testes, e o proprio ficheiro de excepcoes. Nao se declara uma
        #: excepcao para `ADR-021` sem escrever `ADR-021`.
        self.areas = areas

    @classmethod
    def ler(cls, raiz: Path) -> "Excepcoes":
        caminho = raiz / "ci" / "refs-allow.yaml"
        if not caminho.is_file():
            raise FonteCanonicaAusente(f"ficheiro de excepcoes em falta: {caminho}")
        dados = load_file(caminho)
        if dados.get("version") != 1:
            raise FonteCanonicaAusente(f"{caminho}: 'version' tem de ser 1")

        por_ficheiro: dict[str, set[str]] = {}
        for indice, entrada in enumerate(dados.get("excepcoes") or [], start=1):
            faltam = [c for c in ("ficheiro", "token", "razao") if not entrada.get(c)]
            if faltam:
                raise FonteCanonicaAusente(
                    f"{caminho}: excepcao {indice} sem {', '.join(faltam)}"
                )
            if len(str(entrada["razao"])) < 30:
                raise FonteCanonicaAusente(
                    f"{caminho}: excepcao {indice} ({entrada['token']}) tem uma razao "
                    "demasiado curta para alguem a compreender daqui a seis meses"
                )
            por_ficheiro.setdefault(str(entrada["ficheiro"]), set()).add(
                str(entrada["token"])
            )
        areas: list[str] = []
        for indice, area in enumerate(dados.get("areas") or [], start=1):
            if not area.get("caminho") or not area.get("razao"):
                raise FonteCanonicaAusente(
                    f"{caminho}: area {indice} sem caminho ou razao"
                )
            if len(str(area["razao"])) < 30:
                raise FonteCanonicaAusente(
                    f"{caminho}: area {indice} ({area['caminho']}) tem uma razao "
                    "demasiado curta"
                )
            areas.append(str(area["caminho"]))

        return cls(
            placeholders=set(str(p) for p in (dados.get("placeholders") or [])),
            por_ficheiro=por_ficheiro,
            areas=tuple(areas),
        )

    def permite(self, ficheiro: str, identificador: str) -> bool:
        if identificador in self.placeholders:
            return True
        if any(
            fnmatch.fnmatch(ficheiro, padrao) or ficheiro == padrao
            for padrao in self.areas
        ):
            return True
        return identificador in self.por_ficheiro.get(ficheiro, set())


def verificar(raiz: Path) -> tuple[list[str], dict]:
    """Varre a arvore e devolve (achados, estatisticas)."""
    conjuntos = ler(raiz)
    excepcoes = Excepcoes.ler(raiz)
    ficheiros = _ficheiros_do_git(raiz)

    achados: list[str] = []
    avisos: list[str] = []
    total_ocorrencias = 0
    por_serie = {"KAM": 0, "ADR": 0, "D": 0}

    # Intervalo canonico da serie `D`, lido do canon e nao escrito a mao.
    maximo_d = max((int(x[1:]) for x in conjuntos.d), default=0)

    for caminho in ficheiros:
        relativo = caminho.relative_to(raiz).as_posix()
        try:
            texto = caminho.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for ocorrencia in scan.extrair(texto, maximo_d=maximo_d):
            total_ocorrencias += 1
            por_serie[ocorrencia.serie] += 1
            if conjuntos.contem(ocorrencia.serie, ocorrencia.identificador):
                continue
            if excepcoes.permite(relativo, ocorrencia.identificador):
                continue

            # A serie `D` esta sobrecarregada no canon: significa decisao aberta
            # (§13.3) **e** prazo em dias nas tabelas de off-boarding. Um `D`
            # fora do intervalo canonico nao pode ser uma decisao, e a medicao
            # diz que e sempre um prazo (`D0`, `D30`, `D60`). Reporta-se como
            # aviso, nao como falha — ver ci/refs-allow.yaml, seccao `serie_d`.
            if ocorrencia.serie == "D" and not 1 <= ocorrencia.numero <= maximo_d:
                avisos.append(
                    f"{relativo}:{ocorrencia.linha}: {ocorrencia.identificador} esta fora "
                    f"de D1–D{maximo_d}; lido como prazo em dias, nao como decisao"
                )
                continue

            achados.append(
                f"{relativo}:{ocorrencia.linha}: {ocorrencia.identificador} nao existe "
                f"em {conjuntos.origens[ocorrencia.serie]}.\n"
                f"    {ocorrencia.contexto}\n"
                f"    Se a referencia e deliberadamente invalida, declare-a em "
                f"ci/refs-allow.yaml com a razao."
            )

    return achados, {
        "ficheiros": len(ficheiros),
        "ocorrencias": total_ocorrencias,
        "por_serie": por_serie,
        "conjuntos": conjuntos,
        "avisos": avisos,
    }


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="lint_refs", description="Gate 3: lint de referencias cruzadas"
    )
    analisador.add_argument("--root", type=Path, default=None)
    sub = analisador.add_subparsers(dest="comando", required=True)
    sub.add_parser("check", help="varre a arvore seguida pelo git")
    sub.add_parser("sets", help="imprime os conjuntos validos e as suas origens")
    ficheiro = sub.add_parser("file", help="varre um ficheiro (para depurar)")
    ficheiro.add_argument("caminho", type=Path)

    argumentos = analisador.parse_args(argv)
    raiz = (argumentos.root or Path(__file__).resolve().parents[2]).resolve()

    try:
        if argumentos.comando == "sets":
            conjuntos = ler(raiz)
            print(f"lint_refs: {conjuntos.resumo()}")
            for serie, origem in conjuntos.origens.items():
                print(f"  {serie}: {origem}")
            return 0

        if argumentos.comando == "file":
            conjuntos = ler(raiz)
            excepcoes = Excepcoes.ler(raiz)
            texto = argumentos.caminho.read_text(encoding="utf-8")
            try:
                relativo = argumentos.caminho.resolve().relative_to(raiz).as_posix()
            except ValueError:
                relativo = argumentos.caminho.name
            invalidas = 0
            maximo_d = max((int(x[1:]) for x in conjuntos.d), default=0)
            for ocorrencia in scan.extrair(texto, maximo_d=maximo_d):
                valida = conjuntos.contem(ocorrencia.serie, ocorrencia.identificador)
                permitida = excepcoes.permite(relativo, ocorrencia.identificador)
                estado = "ok" if valida else ("permitida" if permitida else "INVALIDA")
                if estado == "INVALIDA":
                    invalidas += 1
                print(f"  {estado:<9} linha {ocorrencia.linha:>4}  {ocorrencia.identificador}")
            print(f"lint_refs: {invalidas} invalida(s)")
            return 1 if invalidas else 0

        achados, estatisticas = verificar(raiz)
        conjuntos: Conjuntos = estatisticas["conjuntos"]
        if achados:
            print(
                f"lint_refs: {len(achados)} referencia(s) invalida(s) "
                f"em {estatisticas['ficheiros']} ficheiros",
                file=sys.stderr,
            )
            for achado in achados:
                print(f"  - {achado}", file=sys.stderr)
            return 1
        if estatisticas["avisos"]:
            print(
                f"lint_refs: {len(estatisticas['avisos'])} aviso(s) — tokens `D#` fora "
                "do intervalo canonico, lidos como prazos:"
            )
            for aviso in estatisticas["avisos"][:5]:
                print(f"  . {aviso}")
            if len(estatisticas["avisos"]) > 5:
                print(f"  . (e mais {len(estatisticas['avisos']) - 5})")

        print(
            f"lint_refs: conforme — {estatisticas['ocorrencias']} referencias em "
            f"{estatisticas['ficheiros']} ficheiros "
            f"(KAM {estatisticas['por_serie']['KAM']}, "
            f"ADR {estatisticas['por_serie']['ADR']}, "
            f"D {estatisticas['por_serie']['D']}); {conjuntos.resumo()}"
        )
        return 0

    except (FonteCanonicaAusente, YamlSubsetError, OSError) as excepcao:
        print(f"lint_refs: erro de configuracao: {excepcao}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
