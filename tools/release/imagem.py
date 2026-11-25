"""Gate 14 — *image scan*: o que trava a publicacao de uma imagem nossa.

O criterio do bloco: «uma imagem sem *digest*, sem SBOM ou sem assinatura cosign
verificada falha o *pipeline*; vulnerabilidade critica sem excepcao registada
tambem falha (2 testes negativos)».

**So as imagens nossas** (`origem: build` no `release.lock`). As de terceiros
ja passam pelo gate 11 (`supply_chain`: *digest*, inventario, `cosign verify`
das que o inventario manda verificar); repetir aqui era ter duas regras para a
mesma pergunta, e a primeira a divergir era a que ninguem lia.

## Os artefactos, por servico

Numa pasta, com o nome do servico do lock:

    <servico>.sbom.json    SBOM CycloneDX da imagem (as camadas, nao o lockfile)
    <servico>.vulns.json   o varrimento, em CycloneDX com `vulnerabilities`

**CycloneDX e nao o formato de um *scanner***, de proposito: nenhum *scanner*
de imagens esta escolhido nem tem licenca registada em `ci/licenses.yaml`, e a
escolha nao e deste ficheiro. O que se le e o campo `vulnerabilities[]` da
especificacao (`id` e `ratings[].severity`), que e o que os *scanners* exportam
quando se lhes pede CycloneDX — **INDICIO**, lido da especificacao de memoria e
nao confirmado contra a saida de nenhum *scanner* concreto. Quem escolher o
*scanner* confirma-o com uma saida real e um ensaio.

## Fail-closed, regra a regra

| Regra | Quando |
|---|---|
| `sem-digest` | a referencia no lock nao e `@sha256:<64>` |
| `sem-sbom` | o ficheiro do SBOM nao existe ou nao e CycloneDX |
| `sbom-vazio` | CycloneDX sem `components` — um SBOM que nao lista nada nao descreve a imagem |
| `sem-varrimento` | o ficheiro do varrimento nao existe, nao e CycloneDX, ou nao tem a chave `vulnerabilities` (use `[]` para «nenhuma»: a ausencia e ambigua) |
| `critica-sem-excepcao` | uma vulnerabilidade com `severity: critical` sem *waiver* do gate 14 com `alvo` igual ao `id` |
| `cosign-sem-binario` | ha imagem a verificar e o `cosign` nao esta no `PATH` — nao se salta |
| `cosign-recusou` | o `cosign verify` saiu com codigo diferente de zero |

A excepcao e a de sempre: `ci/waivers.yaml`, lida e validada pelo
`ci_waivers` (prazo, autor, ADR ou aprovacao). O gate 14 ja estava em
`GATES_COM_WAIVER` desde o KAM-135, a espera deste consumidor.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .lock import REFERENCIA_POR_DIGEST, Lock

Executor = Callable[[list[str]], tuple[int, str]]

#: O emissor OIDC das Actions. Para uma assinatura *keyless* feita no CI, a
#: identidade e o *workflow* que assinou. **NAO VERIFICADO** contra uma
#: assinatura real nossa: nao ha registo nem imagem publicada.
EMISSOR_DAS_ACTIONS = "https://token.actions.githubusercontent.com"


@dataclasses.dataclass(frozen=True)
class Achado:
    servico: str
    regra: str
    mensagem: str

    def __str__(self) -> str:
        return f"{self.servico}: [{self.regra}] {self.mensagem}"


@dataclasses.dataclass(frozen=True)
class Assinatura:
    """O material do `cosign verify`: uma chave, **ou** identidade e emissor."""

    chave: str | None = None
    identidade: str | None = None
    emissor: str | None = None

    def __post_init__(self) -> None:
        com_chave = self.chave is not None
        com_identidade = self.identidade is not None or self.emissor is not None
        if com_chave == com_identidade or (com_identidade and not (self.identidade and self.emissor)):
            raise ValueError(
                "assinatura: exactamente uma forma — `chave`, ou `identidade` e `emissor`"
            )

    def comando(self, referencia: str) -> list[str]:
        if self.chave is not None:
            return ["cosign", "verify", "--key", self.chave, referencia]
        return [
            "cosign", "verify",
            "--certificate-identity", str(self.identidade),
            "--certificate-oidc-issuer", str(self.emissor),
            referencia,
        ]


def executar(comando: list[str]) -> tuple[int, str]:
    if shutil.which(comando[0]) is None:
        return 127, f"{comando[0]}: binario ausente"
    try:
        resultado = subprocess.run(comando, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as excepcao:
        return 1, str(excepcao)
    return resultado.returncode, (resultado.stderr or resultado.stdout).strip()


def _cyclonedx(caminho: Path) -> dict | None:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(dados, dict) or dados.get("bomFormat") != "CycloneDX":
        return None
    return dados


def criticas(varrimento: dict) -> list[str]:
    """Os `id` das vulnerabilidades com alguma `severity` critica."""
    saida: list[str] = []
    for vuln in varrimento.get("vulnerabilities") or []:
        if not isinstance(vuln, dict):
            continue
        severidades = {
            str(r.get("severity", "")).lower()
            for r in vuln.get("ratings") or []
            if isinstance(r, dict)
        }
        if "critical" in severidades:
            saida.append(str(vuln.get("id") or "<sem id>"))
    return sorted(set(saida))


def verificar(
    lock: Lock,
    artefactos: Path,
    assinatura: Assinatura,
    dispensadas: set[str],
    executor: Executor = executar,
    construidos_no_compose: set[str] | None = None,
) -> list[Achado]:
    """Os achados do gate 14 sobre as imagens nossas do lock. Vazio = passa.

    `construidos_no_compose` fecha a porta de um lock editado a mao: um servico
    que o compose constroi e que o lock da como `terceiros` sairia do gate sem
    verificacao nenhuma. Quando se passa, os dois conjuntos tem de ser iguais.
    """
    achados: list[Achado] = []
    if construidos_no_compose is not None:
        do_lock = set(lock.construidos())
        for servico in sorted(construidos_no_compose - do_lock):
            achados.append(Achado(
                servico, "origem-trocada",
                "o compose constroi-o e o lock nao o marca `build`: escapava ao gate 14",
            ))
        for servico in sorted(do_lock - construidos_no_compose):
            achados.append(Achado(
                servico, "origem-trocada", "o lock marca-o `build` e o compose nao o constroi",
            ))
    for servico, entrada in sorted(lock.construidos().items()):
        if not REFERENCIA_POR_DIGEST.match(entrada.imagem):
            achados.append(Achado(servico, "sem-digest", f"{entrada.imagem!r} nao e por @sha256"))
            # Sem digest nao ha o que assinar nem o que varrer: o resto mentia.
            continue

        sbom = _cyclonedx(artefactos / f"{servico}.sbom.json")
        if sbom is None:
            achados.append(Achado(servico, "sem-sbom", "SBOM CycloneDX em falta ou ilegivel"))
        elif not sbom.get("components"):
            achados.append(Achado(servico, "sbom-vazio", "o SBOM nao lista componente nenhum"))

        varrimento = _cyclonedx(artefactos / f"{servico}.vulns.json")
        if varrimento is None or not isinstance(varrimento.get("vulnerabilities"), list):
            achados.append(Achado(
                servico, "sem-varrimento",
                "varrimento CycloneDX em falta, ilegivel ou sem a chave `vulnerabilities`",
            ))
        else:
            for vid in criticas(varrimento):
                if vid not in dispensadas:
                    achados.append(Achado(
                        servico, "critica-sem-excepcao",
                        f"{vid} e critica e nao tem waiver do gate 14 em ci/waivers.yaml",
                    ))

        codigo, saida = executor(assinatura.comando(entrada.imagem))
        if codigo == 127:
            achados.append(Achado(servico, "cosign-sem-binario", saida or "cosign ausente"))
        elif codigo != 0:
            achados.append(Achado(servico, "cosign-recusou", saida or f"codigo {codigo}"))
    return achados


def dispensadas_do_gate_14(raiz: Path) -> set[str]:
    """Os `alvo` com *waiver* valido do gate 14. Um ficheiro invalido levanta."""
    from ci_waivers import ler

    return {str(w["alvo"]) for w in ler(raiz) if str(w["gate"]) == "14"}
