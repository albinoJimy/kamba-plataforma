"""Gate 18 — *tag* SemVer, `release.lock` e SBOM arquivados.

O criterio: «*tag* SemVer + `release.lock` + SBOM arquivados apos verificacao
pos-deploy verde». A ordem e a resolucao do Contexto do bloco: o lock existe
**antes** do deploy (e o que se implanta), e a *tag* so **depois** de a
verificacao pos-deploy dar verde. Uma *tag* posta antes marcava como release
uma versao que podia estar a ser revertida nesse minuto.

## A verificacao pos-deploy

Os quatro sinais dos Detalhes Tecnicos: `/healthz`, taxa de erro do *ingress*,
idade da fila < 2 min, sonda externa. Chegam num JSON com quatro chaves; **uma
chave em falta e vermelho**, e nao «nao medido, logo passa». Os dois limiares
de taxa e idade sao *proposta* do bloco e do doc 09 §7.

## O arquivo

Uma pasta `<destino>/v<versao>/` com o `release.lock`, um SBOM por servico
construido, e um `MANIFESTO.json` com o `sha256` de cada ficheiro, a versao, o
*commit* e a verificacao que a autorizou. **Nao escreve sobre uma versao que ja
existe**: arquivar duas vezes a mesma versao com conteudo diferente e reescrever
historia.

O `git tag` e o `git push` da *tag* ficam ao *pipeline*: este modulo decide se
se pode e qual e o nome, e nao fala com o remoto. **A unicidade que ele garante e
a da pasta de destino**; num *runner* efemero e o `git tag` (que recusa uma
*tag* que ja existe) quem a garante entre execucoes. Por isso a linha de comandos
exige `--anterior` (ou `--primeira`): sem ela, toda a release seria a 0.1.0.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
from pathlib import Path

from .lock import Lock

SEMVER = re.compile(r"^v?(?P<maior>0|[1-9]\d*)\.(?P<menor>0|[1-9]\d*)\.(?P<correccao>0|[1-9]\d*)$")
TIPOS = ("maior", "menor", "correccao")

#: Taxa de erro do *ingress* acima da qual a release nao se etiqueta.
#: **Proposta deste ficheiro, sem fonte no canon**: o bloco nomeia o sinal e nao
#: o limiar. Calibra-se no Piloto, com o orcamento de erro do KAM-082.
TAXA_DE_ERRO_MAXIMA = 0.01

#: «idade da fila < 2 min», dos Detalhes Tecnicos do bloco.
IDADE_DA_FILA_MAXIMA_S = 120.0


class TagRecusada(RuntimeError):
    """Nao se etiqueta: a verificacao nao esta verde, ou o arquivo ja existe."""


def proxima_versao(anterior: str | None, tipo: str) -> str:
    """`0.3.1` + `menor` -> `0.4.0`. Sem anterior, a primeira e `0.1.0`."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo {tipo!r} (aceites: {', '.join(TIPOS)})")
    if anterior is None:
        return "0.1.0"
    casou = SEMVER.match(anterior)
    if not casou:
        raise ValueError(f"{anterior!r} nao e SemVer X.Y.Z")
    maior, menor, correccao = (int(casou[g]) for g in ("maior", "menor", "correccao"))
    if tipo == "maior":
        return f"{maior + 1}.0.0"
    if tipo == "menor":
        return f"{maior}.{menor + 1}.0"
    return f"{maior}.{menor}.{correccao + 1}"


@dataclasses.dataclass(frozen=True)
class VerificacaoPosDeploy:
    healthz: bool
    taxa_de_erro_do_ingress: float
    idade_da_fila_s: float
    sonda_externa: bool

    @classmethod
    def de_json(cls, dados: dict) -> "VerificacaoPosDeploy":
        faltam = [
            c for c in ("healthz", "taxa_de_erro_do_ingress", "idade_da_fila_s", "sonda_externa")
            if c not in dados
        ]
        if faltam:
            raise TagRecusada(f"verificacao pos-deploy sem: {', '.join(faltam)}")
        return cls(
            healthz=dados["healthz"] is True,
            taxa_de_erro_do_ingress=float(dados["taxa_de_erro_do_ingress"]),
            idade_da_fila_s=float(dados["idade_da_fila_s"]),
            sonda_externa=dados["sonda_externa"] is True,
        )

    def falhas(self) -> list[str]:
        saida = []
        if not self.healthz:
            saida.append("/healthz")
        if not 0 <= self.taxa_de_erro_do_ingress <= TAXA_DE_ERRO_MAXIMA:
            saida.append(f"taxa de erro {self.taxa_de_erro_do_ingress:.2%} > {TAXA_DE_ERRO_MAXIMA:.0%}")
        if not 0 <= self.idade_da_fila_s < IDADE_DA_FILA_MAXIMA_S:
            saida.append(f"idade da fila {self.idade_da_fila_s:g} s >= {IDADE_DA_FILA_MAXIMA_S:g} s")
        if not self.sonda_externa:
            saida.append("sonda externa")
        return saida


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def arquivar(
    versao: str,
    lock: Lock,
    lock_caminho: Path,
    sboms: Path,
    verificacao: VerificacaoPosDeploy,
    destino: Path,
) -> Path:
    """Arquiva e devolve a pasta. Levanta `TagRecusada` sem escrever nada."""
    if not SEMVER.match(versao):
        raise TagRecusada(f"{versao!r} nao e SemVer")
    falhas = verificacao.falhas()
    if falhas:
        raise TagRecusada("verificacao pos-deploy vermelha: " + "; ".join(falhas))
    nome = f"v{versao.lstrip('v')}"
    pasta = destino / nome
    if pasta.exists():
        raise TagRecusada(f"{pasta} ja existe: uma versao arquiva-se uma vez")
    em_falta = [s for s in sorted(lock.construidos()) if not (sboms / f"{s}.sbom.json").is_file()]
    if em_falta:
        raise TagRecusada("SBOM em falta para: " + ", ".join(em_falta))

    pasta.mkdir(parents=True)
    shutil.copyfile(lock_caminho, pasta / "release.lock")
    for servico in sorted(lock.construidos()):
        shutil.copyfile(sboms / f"{servico}.sbom.json", pasta / f"{servico}.sbom.json")
    ficheiros = {p.name: _sha256(p) for p in sorted(pasta.iterdir())}
    manifesto = {
        "commit": lock.commit,
        "ficheiros": ficheiros,
        "tag": nome,
        "verificacao": dataclasses.asdict(verificacao),
    }
    (pasta / "MANIFESTO.json").write_text(
        json.dumps(manifesto, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return pasta
