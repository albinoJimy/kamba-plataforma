"""O lexicon de marcadores pt-BR e a politica de alegacoes (KAM-121, criterios 3 e 6).

Dois ficheiros de `policy/`, *policy-as-code* versionada como a de categorias
do KAM-088: `policy/lexico/marcadores_pt_br.yaml` e
`policy/alegacoes/politica.yaml`. Cada um tem `versao` SemVer e o conteudo
selado em `versoes.lock` da sua pasta (`selo`); um ensaio do gate 4 recusa um
conteudo que mude sem a versao subir.

    Lexico.carregar(pasta)        -> Lexico
    lexico.corrigir(texto)        -> texto com as correccoes automaticas
    lexico.marcadores(texto)      -> os `id` dos marcadores que ficaram
    Alegacoes.carregar(pasta)     -> Alegacoes
    alegacoes.avaliar(texto, factos) -> a regra que recusa, ou `None`

## Onde vivem

`KAMBA_POLICY_DIR`, e por omissao a pasta `policy` do directorio corrente — a
mesma regra do `KAMBA_REGISTRY_DIR`, e o AGR corre da raiz. A imagem leva as
duas pastas (`services/agr/Dockerfile`). **Le-se quando se gera uma legenda, e
nao no arranque**: o gerador esta por ligar (credor no bloco), e um ficheiro
em falta recusa a legenda (`politica_indisponivel`) em vez de impedir o AGR de
arrancar.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

VARIAVEL_DA_PASTA: Final = "KAMBA_POLICY_DIR"
FICHEIRO_DO_LEXICO: Final = Path("lexico") / "marcadores_pt_br.yaml"
FICHEIRO_DAS_ALEGACOES: Final = Path("alegacoes") / "politica.yaml"
SEMVER: Final = re.compile(r"^\d+\.\d+\.\d+$")


class PoliticaIndisponivelError(RuntimeError):
    """Um ficheiro de politica em falta ou fora da forma. Sem o texto na mensagem."""


def pasta_das_politicas() -> Path:
    return Path(os.environ.get(VARIAVEL_DA_PASTA) or "policy")


def normalizar(texto: str) -> str:
    """Minusculas, sem acentos e espacos colapsados — o texto que as regras leem."""
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    sem = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem.replace("º", "o").split())


def selo(conteudo: Any) -> str:
    """O sha256 do conteudo **sem a `versao`**, em JSON canonico: o que o `versoes.lock` guarda."""
    sem_versao = {k: v for k, v in conteudo.items() if k != "versao"}
    canonico = json.dumps(sem_versao, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def ler_yaml(caminho: Path) -> dict[str, Any]:
    try:
        conteudo = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise PoliticaIndisponivelError(f"nao consegui ler {caminho.name}") from None
    if not isinstance(conteudo, dict) or not SEMVER.match(str(conteudo.get("versao", ""))):
        raise PoliticaIndisponivelError(f"{caminho.name} sem versao SemVer")
    return conteudo


# ------------------------------------------------------------------ o lexicon


def _infinitivo(radical: str, vogal: str) -> str:
    return f"{radical}{vogal}r"


def _com_maiuscula_de(original: str, novo: str) -> str:
    return novo[:1].upper() + novo[1:] if original[:1].isupper() else novo


@dataclass(frozen=True)
class Marcador:
    id: str
    tipo: str
    padrao: re.Pattern[str]
    correccao: str | None


@dataclass(frozen=True)
class Lexico:
    versao: str
    marcadores: tuple[Marcador, ...]

    @classmethod
    def carregar(cls, pasta: Path | None = None) -> Lexico:
        conteudo = ler_yaml((pasta or pasta_das_politicas()) / FICHEIRO_DO_LEXICO)
        entradas = conteudo.get("marcadores")
        if not isinstance(entradas, list) or not entradas:
            raise PoliticaIndisponivelError("lexicon sem marcadores")
        lidos: list[Marcador] = []
        for entrada in entradas:
            try:
                padrao = re.compile(rf"\b(?:{entrada['padrao']})\b", re.IGNORECASE)
                lidos.append(Marcador(str(entrada["id"]), str(entrada["tipo"]), padrao, entrada.get("correccao")))
            except (KeyError, TypeError, re.error):
                raise PoliticaIndisponivelError("marcador fora da forma") from None
        return cls(versao=str(conteudo["versao"]), marcadores=tuple(lidos))

    def corrigir(self, texto: str) -> str:
        """O texto com as correccoes automaticas. Os marcadores sem correccao ficam."""
        corrigido = texto
        for marcador in self.marcadores:
            if marcador.tipo == "gerundio":
                corrigido = marcador.padrao.sub(
                    lambda m: f"{m.group(1)} a {_infinitivo(m.group(2), m.group(3))}", corrigido
                )
            elif marcador.correccao is not None:
                substituto = marcador.correccao
                corrigido = marcador.padrao.sub(lambda m, s=substituto: _com_maiuscula_de(m.group(0), s), corrigido)
        return corrigido

    def marcadores_em(self, texto: str) -> tuple[str, ...]:
        """Os `id` dos marcadores presentes no texto, pela ordem do ficheiro."""
        return tuple(m.id for m in self.marcadores if m.padrao.search(texto))


# ------------------------------------------------------------------ as alegacoes


@dataclass(frozen=True)
class Regra:
    id: str
    padroes: tuple[re.Pattern[str], ...]
    permitido_se_nos_factos: bool
    estado: str


@dataclass(frozen=True)
class Alegacoes:
    versao: str
    regras: tuple[Regra, ...]

    @classmethod
    def carregar(cls, pasta: Path | None = None) -> Alegacoes:
        conteudo = ler_yaml((pasta or pasta_das_politicas()) / FICHEIRO_DAS_ALEGACOES)
        entradas = conteudo.get("regras")
        if not isinstance(entradas, list) or not entradas:
            raise PoliticaIndisponivelError("politica sem regras")
        regras: list[Regra] = []
        for entrada in entradas:
            try:
                regras.append(
                    Regra(
                        id=str(entrada["id"]),
                        padroes=tuple(re.compile(p) for p in entrada["padroes"]),
                        permitido_se_nos_factos=bool(entrada["permitido_se_nos_factos"]),
                        estado=str(entrada["estado"]),
                    )
                )
            except (KeyError, TypeError, re.error):
                raise PoliticaIndisponivelError("regra fora da forma") from None
        return cls(versao=str(conteudo["versao"]), regras=tuple(regras))

    def avaliar(self, texto: str, factos: Iterable[str] = ()) -> str | None:
        """O `id` da primeira regra que recusa o texto, ou `None` se passa.

        Uma regra com `permitido_se_nos_factos` deixa passar o pedaco que casou
        **se esse pedaco** estiver, normalizado, num dos factos do dono.
        """
        limpo = normalizar(texto)
        dos_factos: Sequence[str] = [normalizar(f) for f in factos]
        for regra in self.regras:
            for padrao in regra.padroes:
                for casado in padrao.finditer(limpo):
                    pedaco = casado.group(0).strip()
                    if regra.permitido_se_nos_factos and any(pedaco in f for f in dos_factos):
                        continue
                    return regra.id
        return None
