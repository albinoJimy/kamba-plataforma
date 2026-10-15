"""Varrimento de vulnerabilidades do gate 11, contra a OSV.

O criterio de aceitacao do KAM-002 diz, por escrito, que o gate 11 «falha com
vulnerabilidade critica sem excepcao registada». Essa metade do gate nao
existia: havia SBOM e havia licencas, e nao havia varrimento nenhum — nem
`pnpm audit`, nem `pip-audit`, nem consulta a nenhuma base. Pior do que faltar,
nao estava declarado em sitio nenhum: o `ci/waivers.yaml` dizia ao leitor que
`alvo` podia ser «uma CVE», o que afirmava uma capacidade inexistente.

Escolheu-se a **OSV** (<https://osv.dev>) e nao o `pnpm audit`/`pip-audit` por
tres razoes:

1. Uma so fonte para os dois ecossistemas, consultada por `purl` — que e
   exactamente o que o SBOM ja produz. Nao ha traducao nossa pelo meio.
2. Nao precisa de gestor de pacotes instalado nem de rede do registo privado:
   e HTTP sobre uma API publica, sem credenciais. Encaixa no CA «sem chaves
   estaticas».
3. Devolve o intervalo afectado por versao, pelo que a decisao e sobre a
   versao que esta no *lockfile* e nao sobre o pacote em abstracto.

**Fail-closed inclui a rede.** Se a OSV nao responder, o gate falha: um gate de
seguranca que passa quando nao consegue verificar e um gate que mente. Para
trabalho local sem rede existe `KAMBA_SEM_REDE=1`, que **salta** o varrimento
dizendo-o em voz alta — e que o CI nunca define.
"""

from __future__ import annotations

import dataclasses
import json
import os
import urllib.error
import urllib.request

from .collect import Componente

#: Lote da API. A OSV aceita varias consultas num pedido; 100 e conservador e
#: mantem o numero de pedidos baixo sem produzir corpos enormes.
TAMANHO_DO_LOTE = 100

#: Segundos. Generoso, porque falhar por *timeout* custa um PR vermelho.
ESPERA = 30

URL_LOTE = "https://api.osv.dev/v1/querybatch"
URL_VULN = "https://api.osv.dev/v1/vulns/"

#: A severidade que o CA nomeia. `CRITICAL` e so o topo; o KAM-002 diz
#: «vulnerabilidade critica», e e isso que bloqueia. As outras entram no
#: relatorio sem falhar — informam sem parar o trabalho de todos.
SEVERIDADE_QUE_BLOQUEIA = "CRITICAL"


class RedeIndisponivel(RuntimeError):
    """A OSV nao respondeu. Falha o gate, nao o deixa passar."""


@dataclasses.dataclass(frozen=True)
class Vulnerabilidade:
    purl: str
    identificador: str
    severidade: str
    resumo: str

    @property
    def bloqueia(self) -> bool:
        return self.severidade == SEVERIDADE_QUE_BLOQUEIA

    def __str__(self) -> str:
        return (
            f"{self.purl}: {self.identificador} ({self.severidade or 'sem severidade'})"
            f"\n    {self.resumo}"
        )


def _pedir(url: str, corpo: bytes | None = None) -> dict:
    pedido = urllib.request.Request(
        url,
        data=corpo,
        headers={"Content-Type": "application/json", "User-Agent": "kamba-gate-11/1"},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=ESPERA) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as erro:
        raise RedeIndisponivel(f"OSV inacessivel ({url}): {erro}") from erro


def _severidade(detalhe: dict) -> str:
    """A severidade declarada, pela ordem em que a OSV a oferece.

    Prefere-se o `database_specific.severity` do GHSA (texto: `CRITICAL`,
    `HIGH`) e, na sua falta, deriva-se do CVSS v3 em `severity[].score`. Sem
    nenhum dos dois, devolve-se vazio — e um vazio **nao** bloqueia, porque
    bloquear por ausencia de dado transformaria cada aviso sem metadados num PR
    parado.
    """
    especifico = (detalhe.get("database_specific") or {}).get("severity")
    if isinstance(especifico, str) and especifico:
        return especifico.upper()
    for entrada in detalhe.get("severity") or []:
        pontuacao = str(entrada.get("score") or "")
        # Vector CVSS v3: `CVSS:3.1/AV:N/.../A:H`. A OSV nem sempre da o numero,
        # e traduzir o vector a mao aqui seria inventar; o que se faz e ler o
        # numero quando ele vem isolado.
        try:
            valor = float(pontuacao)
        except ValueError:
            continue
        if valor >= 9.0:
            return "CRITICAL"
        if valor >= 7.0:
            return "HIGH"
        if valor >= 4.0:
            return "MODERATE"
        return "LOW"
    return ""


def consultar(componentes: list[Componente]) -> list[Vulnerabilidade]:
    """Consulta a OSV pelos `purl` dos componentes de terceiros.

    Os pacotes do proprio monorepo nao se consultam: nao estao em base de dados
    de vulnerabilidades nenhuma, e consulta-los gastaria pedidos para obter
    listas vazias.
    """
    alvos = [c for c in componentes if not c.proprio]
    if not alvos:
        return []

    por_purl: dict[str, list[str]] = {}
    for inicio in range(0, len(alvos), TAMANHO_DO_LOTE):
        lote = alvos[inicio : inicio + TAMANHO_DO_LOTE]
        corpo = json.dumps(
            {"queries": [{"package": {"purl": c.purl}} for c in lote]}
        ).encode("utf-8")
        resposta = _pedir(URL_LOTE, corpo)
        resultados = resposta.get("results") or []
        if len(resultados) != len(lote):
            raise RedeIndisponivel(
                f"OSV devolveu {len(resultados)} resultados para {len(lote)} consultas"
            )
        for componente, resultado in zip(lote, resultados):
            ids = [v.get("id") for v in (resultado.get("vulns") or []) if v.get("id")]
            if ids:
                por_purl[componente.purl] = ids

    # A severidade nao vem no lote: pede-se o detalhe de cada identificador.
    # Sao poucos — o caso normal e nenhum.
    detalhados: dict[str, dict] = {}
    vulnerabilidades: list[Vulnerabilidade] = []
    for purl, ids in sorted(por_purl.items()):
        for identificador in ids:
            if identificador not in detalhados:
                detalhados[identificador] = _pedir(URL_VULN + identificador)
            detalhe = detalhados[identificador]
            vulnerabilidades.append(
                Vulnerabilidade(
                    purl=purl,
                    identificador=identificador,
                    severidade=_severidade(detalhe),
                    resumo=(detalhe.get("summary") or detalhe.get("details") or "")[
                        :200
                    ].replace("\n", " "),
                )
            )
    return vulnerabilidades


def sem_rede() -> bool:
    """`KAMBA_SEM_REDE=1` salta o varrimento, em voz alta.

    Existe para `make ci-11` correr numa maquina sem rede. O CI nunca a define,
    e o `docs/ci.md` diz que um PR validado com ela nao conta.
    """
    return os.environ.get("KAMBA_SEM_REDE") == "1"
