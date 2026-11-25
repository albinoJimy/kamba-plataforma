"""As regras `nftables` do *host*, lidas do cloud-init do `host-base` e verificadas.

O criterio 4 do KAM-077 pede um *scan* externo com «so 443 e a porta UDP do
WireGuard; SSH por chave so via VPN». O *scan* precisa de um *host*, que precisa
da D1. **As regras que o *scan* vai medir nao precisam**, e a classe 3 de
`infra/PORTABILIDADE.md` diz qual e a forma portatil delas: `nftables` aplicado
pelo proprio *host*. Este modulo le essas regras do sitio onde vivem
(`infra/modules/host-base/cloud-init.yaml.tftpl`) e verifica as propriedades que
o criterio exige — nao e um *parser* de `nft`: a sintaxe verifica-a o proprio
`nft -c`, e isso esta medido no anexo da preparacao, nao aqui.

AS PROPRIEDADES, e a razao de cada uma:

1. **Nada de `flush ruleset`.** O Docker escreve as suas proprias tabelas
   (`iptables-nft`), e um `flush ruleset` ao recarregar as regras do *host*
   apagava-as — a rede dos contentores morria sem nenhum erro no arranque.
2. **Uma tabela `inet kamba_host` com a cadeia `input` em `policy drop`.**
   `inet` cobre IPv4 e IPv6 de uma vez; um *host* com IPv6 e regras so em `ip`
   ficava aberto pela outra familia.
3. **Nenhuma cadeia no gancho `forward`.** O *forward* e do Docker: e por ele
   que passa o 443 publicado pelo `proxy-tls`. Um `drop` aqui partia a pilha; um
   `accept` nao abria nada que o Docker nao abra. Por isso o 443 **nao** aparece
   nestas regras, e a outra metade do criterio e a regra `porta-publicada` do
   `compose_prod` (so o `proxy-tls` publica, e so 443).
4. **Aberto ao mundo, so o que esta em `ABERTURAS_SEM_INTERFACE`.** Uma regra
   de `accept` com `dport` e sem `iifname` e uma porta aberta a quem chegar: so
   a do WireGuard e as respostas de DHCP do fornecedor.
5. **SSH so pela interface do tunel.** Toda a regra que aceite `tcp dport 22`
   tem de dizer `iifname "wg0"`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Onde as regras ficam no *host*, e por isso a chave pela qual se encontram no cloud-init.
CAMINHO_NO_HOST = "/etc/kamba/firewall.nft"

#: O modelo do cloud-init, relativo a raiz do repositorio.
MODELO = Path("infra/modules/host-base/cloud-init.yaml.tftpl")

TABELA = "inet kamba_host"
INTERFACE_DO_TUNEL = "wg0"


def aberturas_sem_interface(porta_wireguard: int) -> set[str]:
    """As unicas regras de `accept` com `dport` que podem nao nomear interface."""
    return {
        f"udp dport {porta_wireguard} accept",
        # As respostas do DHCP do fornecedor (v4 e v6). Sao `sport` do servidor
        # para o `dport` do cliente: nao abrem servico nenhum do *host*.
        "udp sport 67 udp dport 68 accept",
        "udp sport 547 udp dport 546 accept",
    }


class RegrasAusentes(Exception):
    """O cloud-init nao tem o ficheiro de regras. Erro, nao achado."""


def extrair(texto_cloud_init: str) -> str:
    """O conteudo do `write_files` cujo `path` e `CAMINHO_NO_HOST`, sem a indentacao."""
    linhas = texto_cloud_init.splitlines()
    for indice, linha in enumerate(linhas):
        if linha.strip() == f"- path: {CAMINHO_NO_HOST}":
            break
    else:
        raise RegrasAusentes(f"nenhum write_files com path {CAMINHO_NO_HOST}")
    for indice in range(indice + 1, len(linhas)):
        if linhas[indice].strip() == "content: |":
            break
        if linhas[indice].lstrip().startswith("- path:"):
            raise RegrasAusentes(f"o write_files de {CAMINHO_NO_HOST} nao tem `content: |`")
    else:
        raise RegrasAusentes(f"o write_files de {CAMINHO_NO_HOST} nao tem `content: |`")
    base = len(linhas[indice]) - len(linhas[indice].lstrip())
    corpo = []
    for linha in linhas[indice + 1 :]:
        if linha.strip() and len(linha) - len(linha.lstrip()) <= base:
            break
        corpo.append(linha)
    margem = min((len(l) - len(l.lstrip()) for l in corpo if l.strip()), default=0)
    return "\n".join(l[margem:] for l in corpo).strip("\n") + "\n"


@dataclass(frozen=True)
class Achado:
    regra: str
    detalhe: str

    def __str__(self) -> str:
        return f"[{self.regra}] {self.detalhe}"


def _sem_comentarios(regras: str) -> list[str]:
    return [l.split("#", 1)[0].strip() for l in regras.splitlines() if l.split("#", 1)[0].strip()]


def _cadeias(linhas: list[str]) -> dict[str, list[str]]:
    """Cadeia -> linhas dela, dentro de `table inet kamba_host { ... }`."""
    cadeias: dict[str, list[str]] = {}
    actual = None
    dentro_da_tabela = False
    for linha in linhas:
        if re.fullmatch(rf"table {TABELA} \{{", linha):
            dentro_da_tabela = True
            continue
        if not dentro_da_tabela:
            continue
        casado = re.fullmatch(r"chain (\S+) \{", linha)
        if casado:
            actual = casado.group(1)
            cadeias[actual] = []
        elif linha == "}":
            if actual is None:
                dentro_da_tabela = False
            actual = None
        elif actual is not None:
            cadeias[actual].append(linha)
    return cadeias


def verificar(regras: str, porta_wireguard: int) -> list[Achado]:
    """Os achados das cinco propriedades do docstring do modulo. Vazia = conforme."""
    achados = []
    linhas = _sem_comentarios(regras)
    if any(re.match(r"flush\s+ruleset\b", l) for l in linhas):
        achados.append(Achado("flush-ruleset", "apagaria as tabelas do Docker ao recarregar"))
    cadeias = _cadeias(linhas)
    if not cadeias:
        achados.append(Achado("sem-tabela", f"nenhuma cadeia dentro de `table {TABELA} {{`"))
        return achados
    entrada = cadeias.get("input", [])
    if not any(re.fullmatch(r"type filter hook input priority \S+; policy drop;", l) for l in entrada):
        achados.append(Achado("input-sem-drop", "a cadeia `input` nao existe ou nao tem `policy drop`"))
    for nome, corpo in cadeias.items():
        if any("hook forward" in l for l in corpo):
            achados.append(Achado("forward", f"a cadeia `{nome}` pendura no `forward`, que e do Docker"))
        for linha in corpo:
            if not linha.endswith("accept") or "dport" not in linha:
                continue
            if re.search(r"\btcp dport (22|\{[^}]*\b22\b[^}]*\})", linha) and f'iifname "{INTERFACE_DO_TUNEL}"' not in linha:
                achados.append(Achado("ssh-fora-do-tunel", f"`{linha}` aceita SSH sem ser pelo {INTERFACE_DO_TUNEL}"))
            elif "iifname" not in linha and linha not in aberturas_sem_interface(porta_wireguard):
                achados.append(Achado("porta-aberta", f"`{linha}` abre uma porta a qualquer origem"))
    if not any(l == f"udp dport {porta_wireguard} accept" for l in entrada):
        achados.append(Achado("sem-wireguard", f"a porta UDP {porta_wireguard} do WireGuard nao abre"))
    return achados


def do_modelo(raiz: Path, porta_wireguard: int) -> str:
    """As regras do modelo do cloud-init, com a porta do WireGuard ja interpolada."""
    texto = (raiz / MODELO).read_text(encoding="utf-8")
    return extrair(texto).replace("${porta_wireguard}", str(porta_wireguard))
