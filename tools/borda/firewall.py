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
4. **So aceita o que esta em `regras_permitidas`, e nada fora da tabela.** Toda
   a instrucao que aceite, salte ou va para outra cadeia tem de ser uma das da
   lista fechada; uma `add rule` fora do bloco tambem conta. Aberto ao mundo fica
   so a porta UDP do WireGuard (e as respostas DHCPv6 da ligacao local).
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


#: As linhas fora da tabela que se aceitam: o cabecalho do ficheiro.
CABECALHO = {f"table {TABELA}", f"delete table {TABELA}"}


def regras_permitidas(porta_wireguard: int) -> set[str]:
    """A LISTA FECHADA das instrucoes que aceitam na cadeia `input`.

    Fechada de proposito: a primeira versao deste verificador procurava as
    formas perigosas que conhecia (`dport` sem `iifname`) e deixava passar as que
    nao conhecia — `accept` sozinho, `ct state new accept`, `ip saddr 0.0.0.0/0
    accept`, `iifname "eth0" tcp dport 3306 accept`, um `jump` para uma cadeia
    que aceita. Uma regra nova que aceite tem de entrar aqui **e** no cloud-init,
    e as duas edicoes leem-se juntas na revisao.
    """
    return {
        "ct state { established, related } accept",
        'iifname "lo" accept',
        "ip protocol icmp icmp type { echo-request, destination-unreachable, time-exceeded } accept",
        "meta l4proto ipv6-icmp icmpv6 type { echo-request, destination-unreachable, packet-too-big, "
        "time-exceeded, parameter-problem, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert, "
        "mld-listener-query } accept",
        # As respostas do servidor DHCPv6, so da ligacao local: o pedido vai para
        # um endereco *multicast* e a resposta vem *unicast*, pelo que o
        # `conntrack` nao as liga. No DHCPv4 nao e preciso regra: o cliente
        # recebe a oferta por *socket* cru e a renovacao e `established`.
        "ip6 saddr fe80::/10 udp sport 547 udp dport 546 accept",
        f"udp dport {porta_wireguard} accept",
        f'iifname "{INTERFACE_DO_TUNEL}" tcp dport 22 accept',
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


def _cadeias(linhas: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Cadeia -> instrucoes dela, dentro de `table inet kamba_host { ... }`; e o que fica fora.

    Uma linha com varias instrucoes separadas por `;` parte-se em instrucoes:
    `tcp dport 22 accept; tcp dport 3306 accept` sao duas regras, e a segunda
    nao pode esconder-se atras da primeira.
    """
    cadeias: dict[str, list[str]] = {}
    fora: list[str] = []
    actual = None
    dentro_da_tabela = False
    for linha in linhas:
        if not dentro_da_tabela:
            if re.fullmatch(rf"table {TABELA} \{{", linha):
                dentro_da_tabela = True
            elif linha not in CABECALHO:
                fora.append(linha)
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
            cadeias[actual].extend(i.strip() for i in linha.split(";") if i.strip())
        else:
            fora.append(linha)
    return cadeias, fora


def verificar(regras: str, porta_wireguard: int) -> list[Achado]:
    """Os achados das propriedades do docstring do modulo. Vazia = conforme."""
    achados = []
    linhas = _sem_comentarios(regras)
    if any(re.match(r"flush\s+ruleset\b", l) for l in linhas):
        achados.append(Achado("flush-ruleset", "apagaria as tabelas do Docker ao recarregar"))
    cadeias, fora = _cadeias(linhas)
    for linha in fora:
        if not re.match(r"flush\s+ruleset\b", linha):
            achados.append(Achado("fora-da-tabela", f"`{linha}` nao esta dentro de `table {TABELA} {{`"))
    if not cadeias:
        achados.append(Achado("sem-tabela", f"nenhuma cadeia dentro de `table {TABELA} {{`"))
        return achados
    entrada = cadeias.get("input", [])
    if not ("type filter hook input priority filter" in entrada and "policy drop" in entrada):
        achados.append(Achado("input-sem-drop", "a cadeia `input` nao existe ou nao tem `policy drop`"))
    permitidas = regras_permitidas(porta_wireguard)
    for nome, corpo in cadeias.items():
        if any("hook forward" in i for i in corpo):
            achados.append(Achado("forward", f"a cadeia `{nome}` pendura no `forward`, que e do Docker"))
        for instrucao in corpo:
            if not re.search(r"\b(accept|jump|goto)\b", instrucao) or instrucao.startswith("policy "):
                continue
            if nome == "input" and instrucao in permitidas:
                continue
            if re.search(r"\btcp dport (22\b|\{[^}]*\b22\b[^}]*\})", instrucao):
                achados.append(Achado("ssh-fora-do-tunel", f"`{instrucao}` aceita SSH sem ser so pelo {INTERFACE_DO_TUNEL}"))
            else:
                achados.append(Achado("regra-nao-reconhecida", f"`{instrucao}` (cadeia `{nome}`) aceita ou salta e nao e uma das conhecidas"))
    if f"udp dport {porta_wireguard} accept" not in entrada:
        achados.append(Achado("sem-wireguard", f"a porta UDP {porta_wireguard} do WireGuard nao abre"))
    return achados


def do_modelo(raiz: Path, porta_wireguard: int) -> str:
    """As regras do modelo do cloud-init, com a porta do WireGuard ja interpolada."""
    texto = (raiz / MODELO).read_text(encoding="utf-8")
    return extrair(texto).replace("${porta_wireguard}", str(porta_wireguard))
