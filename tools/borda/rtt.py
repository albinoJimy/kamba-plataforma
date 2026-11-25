"""Sonda de RTT do KAM-077 (criterio 5) e o relatorio que so sai com numeros medidos.

O criterio pede o RTT «de uma sonda em Luanda ao *host*, p50/p95 em 24 h, e do
*host* a `graph.facebook.com`», numa tabela em `docs/tecnica/evidencia/` que
substitui os valores INDICIO do doc 09 §5.2. O 3.o Teste Requerido pede a
verificacao de que o relatorio «contem numeros medidos, nao estimados». As tres
partes deste modulo respondem a essas tres frases:

``medir``      corre na sonda (e no *host*), uma amostra por alvo a cada
               ``intervalo`` segundos, e escreve-as em JSON Lines;
``relatorio``  le as amostras e **recusa** a tabela se uma serie nao cobrir a
               janela com medicoes com sucesso, ou tiver entre duas delas uma
               lacuna maior do que a permitida;
``verificar``  recalcula a tabela a partir das amostras cujo ``sha256`` o
               relatorio declara, falha se um numero nao bater, e **volta a
               aplicar as recusas com os valores do criterio** (24 h, nao os que
               o relatorio diga) e a exigencia das duas medicoes do criterio:
               um alvo `graph.facebook.com` e pelo menos um outro (o *host*).

O QUE O ``verificar`` PROVA, E O QUE NAO PROVA. Prova que a tabela e a que os
ficheiros de amostras dao, e que esses ficheiros sao os declarados: um numero
escrito a mao **na tabela** nao sobrevive. **Nao prova que as amostras foram
medidas** — amostras inventadas com a forma certa passam, como passariam por
qualquer ferramenta. A garantia dessa metade e a cadeia de custodia: o ficheiro
fica no repositorio de provas privado, com o ``sha256`` e a data no indice
(`provas/alojamento/README.md`), escrito pela sonda e nao editado.

O QUE SE MEDE, E PORQUE NAO E ICMP. O RTT e o tempo do *handshake* TCP
(`connect` ate a ligacao ficar estabelecida) para a porta do alvo — 443 nos dois
casos do criterio. Um *handshake* e um SYN e um SYN-ACK, logo uma ida e volta;
mede o caminho que o HTTPS da Meta e do operador usam de facto, e nao precisa de
privilegios (um `ping` precisa de *socket* cru ou de `setuid`). A resolucao de
nomes faz-se **antes** do cronometro, para que um DNS lento nao entre no RTT.
Estado do metodo: o *handshake* inclui o tempo de o *kernel* do alvo responder
ao SYN, que e da ordem dos microssegundos — INDICIO (conhecimento geral), nao
medido aqui.

PERCENTIS POR POSTO MAIS PROXIMO (*nearest-rank*): o p95 de ``n`` valores e o
de posto ``ceil(0,95 * n)`` na lista ordenada. Nao interpola: todo o numero do
relatorio e um valor que foi medido, e e isso que o ``verificar`` exige.

O IP DO *HOST* NAO VAI PARA O RELATORIO. As amostras guardam o endereco (sao do
repositorio de provas, privado — `provas/alojamento/README.md`); o relatorio,
que e publico, so leva a etiqueta do alvo e o ``sha256`` do ficheiro de onde os
numeros sairam.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

#: Versao do formato de cada linha de amostra.
VERSAO = 1

#: 24 h: a janela que o criterio 5 nomeia.
JANELA_MINIMA_S = 24 * 60 * 60

#: A maior lacuna entre duas amostras seguidas de uma serie. *Proposta*: dez
#: minutos com o intervalo por omissao de 60 s tolera nove amostras perdidas
#: seguidas; mais do que isso e uma sonda que morreu e foi relancada, e uma
#: janela de 24 h com um buraco de horas nao e «24 h medidas».
LACUNA_MAXIMA_S = 600

#: Intervalo por omissao entre rondas, em segundos (1440 amostras por alvo em 24 h).
INTERVALO_S = 60

#: Tempo maximo de um `connect`. Acima disto conta como falha, nao como RTT.
TIMEOUT_S = 5.0

_NOME = re.compile(r"[a-z0-9][a-z0-9-]*")
_ALVO = re.compile(r"^(?P<nome>[a-z0-9][a-z0-9-]*)=(?P<endereco>[^\s=]+):(?P<porta>[0-9]{1,5})$")


class Recusa(Exception):
    """O relatorio nao sai: os dados nao chegam para afirmar o que o criterio pede."""


class AmostraInvalida(Exception):
    """Uma linha de amostras que nao se le. Distinta de `Recusa`: e erro, nao veredicto."""


@dataclass(frozen=True)
class Alvo:
    nome: str
    endereco: str
    porta: int

    @classmethod
    def ler(cls, texto: str) -> "Alvo":
        """``nome=endereco:porta``, por exemplo ``graph=graph.facebook.com:443``."""
        casado = _ALVO.match(texto)
        if not casado:
            raise ValueError(f"alvo invalido {texto!r}: a forma e nome=endereco:porta")
        porta = int(casado["porta"])
        if not 1 <= porta <= 65535:
            raise ValueError(f"alvo invalido {texto!r}: porta fora de 1..65535")
        return cls(casado["nome"], casado["endereco"], porta)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _instante(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ler_instante(texto: str) -> datetime:
    return datetime.strptime(texto, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def ligar(endereco: str, porta: int, timeout: float = TIMEOUT_S) -> float:
    """Um *handshake* TCP, em milissegundos. Resolve o nome antes de cronometrar."""
    familia, tipo, protocolo, _, destino = socket.getaddrinfo(
        endereco, porta, type=socket.SOCK_STREAM
    )[0]
    with socket.socket(familia, tipo, protocolo) as tomada:
        tomada.settimeout(timeout)
        inicio = time.perf_counter()
        tomada.connect(destino)
        return (time.perf_counter() - inicio) * 1000.0


def amostra(origem: str, alvo: Alvo, intervalo_s: int, ligacao: Callable, relogio: Callable) -> dict:
    """Uma medicao, ja na forma da linha que se escreve. Uma falha e amostra, nao excepcao."""
    momento = relogio()
    linha = {
        "v": VERSAO,
        "origem": origem,
        "alvo": alvo.nome,
        "endereco": f"{alvo.endereco}:{alvo.porta}",
        "instante": _instante(momento),
        "intervalo_s": intervalo_s,
        "rtt_ms": None,
        "erro": None,
    }
    try:
        linha["rtt_ms"] = round(float(ligacao(alvo.endereco, alvo.porta)), 3)
    except (OSError, socket.timeout) as erro:
        # Uma falha conta-se e mostra-se no relatorio; nao entra nos percentis,
        # e tambem nao se apaga: uma sonda que so guardasse os sucessos dava um
        # p95 bonito sobre um caminho que cai.
        linha["erro"] = type(erro).__name__
    return linha


def medir(
    origem: str,
    alvos: Iterable[Alvo],
    saida: Path,
    duracao_s: int = JANELA_MINIMA_S,
    intervalo_s: int = INTERVALO_S,
    ligacao: Callable = ligar,
    relogio: Callable = _agora,
    dormir: Callable = time.sleep,
    cronometro: Callable = time.monotonic,
) -> int:
    """Corre rondas ate ``duracao_s`` e acrescenta as amostras a ``saida``. Devolve quantas.

    As rondas marcam-se a partir do inicio (``inicio + k * intervalo``) e nao do
    fim da anterior: um `connect` lento nao empurra a ronda seguinte, e 24 h dao
    as mesmas rondas em qualquer rede (1442 em 24 h com 60 s, contando a extra).
    """
    alvos = list(alvos)
    if not alvos:
        raise ValueError("sem alvos: nada para medir")
    if not _NOME.fullmatch(origem):
        raise ValueError(f"origem invalida {origem!r}: minusculas, digitos e hifens")
    inicio = cronometro()
    escritas = 0
    ronda = 0
    with open(saida, "a", encoding="utf-8", newline="\n") as ficheiro:
        while True:
            for alvo in alvos:
                ficheiro.write(json.dumps(amostra(origem, alvo, intervalo_s, ligacao, relogio)) + "\n")
                escritas += 1
            # Cada ronda vai ao disco: uma sonda que morra a meio deixa as
            # amostras que tirou, e o relatorio diz que a janela nao chegou.
            ficheiro.flush()
            ronda += 1
            # UMA RONDA A MAIS do que a duracao pede. Dentro de uma ronda os
            # alvos medem-se um a seguir ao outro, e o segundo alvo da primeira
            # ronda espera pelo `connect` do primeiro (ate `TIMEOUT_S`): sem a
            # ronda extra, a serie dele cobria 24 h menos esse atraso, e o
            # relatorio recusava-a — com razao, mas por um defeito da sonda.
            if (ronda - 1) * intervalo_s >= duracao_s + intervalo_s:
                return escritas
            proxima = inicio + ronda * intervalo_s
            espera = proxima - cronometro()
            if espera > 0:
                dormir(espera)


def ler(caminho: Path) -> list[dict]:
    """As amostras de um ficheiro, validadas linha a linha."""
    amostras = []
    obrigatorias = {"v", "origem", "alvo", "endereco", "instante", "intervalo_s", "rtt_ms", "erro"}
    for numero, texto in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
        if not texto.strip():
            continue
        try:
            linha = json.loads(texto)
        except json.JSONDecodeError as erro:
            raise AmostraInvalida(f"{caminho.name}:{numero}: nao e JSON ({erro.msg})") from erro
        if not isinstance(linha, dict) or set(linha) != obrigatorias:
            raise AmostraInvalida(f"{caminho.name}:{numero}: campos {sorted(linha) if isinstance(linha, dict) else '?'}")
        if linha["v"] != VERSAO:
            raise AmostraInvalida(f"{caminho.name}:{numero}: versao {linha['v']!r}, esperava {VERSAO}")
        # A origem e o alvo vao para uma celula da tabela: um `|` partia-a.
        for campo in ("origem", "alvo"):
            if not isinstance(linha[campo], str) or not _NOME.fullmatch(linha[campo]):
                raise AmostraInvalida(f"{caminho.name}:{numero}: {campo} {linha[campo]!r}")
        rtt, erro = linha["rtt_ms"], linha["erro"]
        # Exactamente um dos dois: um RTT com erro, ou um erro sem RTT, e uma
        # linha que alguem escreveu a mao ou que a sonda nao escreveu.
        if (rtt is None) == (erro is None):
            raise AmostraInvalida(f"{caminho.name}:{numero}: tem de ter rtt_ms ou erro, e so um")
        if rtt is not None and (isinstance(rtt, bool) or not isinstance(rtt, (int, float)) or rtt <= 0 or not math.isfinite(rtt)):
            raise AmostraInvalida(f"{caminho.name}:{numero}: rtt_ms {rtt!r} nao e uma medicao")
        try:
            linha["_momento"] = _ler_instante(linha["instante"])
        except (TypeError, ValueError) as erro:
            raise AmostraInvalida(f"{caminho.name}:{numero}: instante {linha['instante']!r}") from erro
        amostras.append(linha)
    return amostras


def percentil(valores: list[float], p: float) -> float:
    """Posto mais proximo: o valor de posto ``ceil(p/100 * n)``. Nunca interpola."""
    if not valores:
        raise ValueError("percentil de uma lista vazia")
    ordenados = sorted(valores)
    posto = max(1, math.ceil(p / 100.0 * len(ordenados)))
    return ordenados[posto - 1]


@dataclass(frozen=True)
class Serie:
    origem: str
    alvo: str
    amostras: int
    falhas: int
    inicio: datetime
    fim: datetime
    maior_lacuna_s: float
    p50: float | None
    p95: float | None
    maximo: float | None

    @property
    def cobertura_s(self) -> float:
        return (self.fim - self.inicio).total_seconds()


def resumir(amostras: list[dict]) -> list[Serie]:
    """Uma serie por (origem, alvo), ordenadas, com os percentis so dos sucessos."""
    grupos: dict[tuple[str, str], list[dict]] = {}
    for linha in amostras:
        grupos.setdefault((linha["origem"], linha["alvo"]), []).append(linha)
    series = []
    for (origem, alvo), linhas in sorted(grupos.items()):
        linhas.sort(key=lambda linha: linha["_momento"])
        # A COBERTURA E AS LACUNAS CONTAM-SE ENTRE MEDICOES COM SUCESSO, nao
        # entre amostras. Uma falha e uma amostra mas nao e uma medicao: uma
        # serie com um sucesso e 1440 *timeouts* cobria 24 h de amostras e dava
        # p50 = p95 = o unico valor, que e o contrario de «p50/p95 em 24 h».
        # Assim, uma sequencia de falhas mais longa do que a lacuna maxima
        # recusa a serie, como uma sonda parada.
        medidas = [linha for linha in linhas if linha["rtt_ms"] is not None]
        momentos = [linha["_momento"] for linha in (medidas or linhas[:1])]
        lacunas = [(b - a).total_seconds() for a, b in zip(momentos, momentos[1:])]
        sucessos = [float(linha["rtt_ms"]) for linha in medidas]
        series.append(
            Serie(
                origem=origem,
                alvo=alvo,
                amostras=len(linhas),
                falhas=len(linhas) - len(sucessos),
                inicio=momentos[0],
                fim=momentos[-1],
                maior_lacuna_s=max(lacunas, default=0.0),
                p50=percentil(sucessos, 50) if sucessos else None,
                p95=percentil(sucessos, 95) if sucessos else None,
                maximo=max(sucessos) if sucessos else None,
            )
        )
    return series


def recusas(series: list[Serie], janela_minima_s: int, lacuna_maxima_s: int) -> list[str]:
    """As razoes pelas quais estas series nao sustentam o criterio 5. Vazia = sustentam."""
    razoes = []
    if not series:
        razoes.append("nenhuma amostra")
    for serie in series:
        nome = f"{serie.origem} -> {serie.alvo}"
        if serie.cobertura_s < janela_minima_s:
            razoes.append(
                f"{nome}: cobre {serie.cobertura_s:.0f} s, e a janela pedida e {janela_minima_s} s"
            )
        if serie.maior_lacuna_s > lacuna_maxima_s:
            razoes.append(
                f"{nome}: lacuna de {serie.maior_lacuna_s:.0f} s entre duas medicoes com sucesso "
                f"(maximo {lacuna_maxima_s} s)"
            )
        if serie.p50 is None:
            razoes.append(f"{nome}: {serie.amostras} amostras e nenhuma com sucesso")
    return razoes


#: O alvo do *host* para a Meta que o criterio 5 nomeia.
ALVO_DA_META = "graph.facebook.com"


def faltas_do_criterio(amostras: list[dict]) -> list[str]:
    """As duas medicoes que o criterio 5 pede, pelo endereco e nao pela etiqueta.

    A etiqueta escolhe-a quem corre a sonda; o endereco e o que foi medido. Um
    relatorio so com a sonda -> *host*, ou so com o *host* -> Meta, e metade do
    criterio, e nao sai.
    """
    if not amostras:
        return []
    para_a_meta = {(l["origem"], l["alvo"]) for l in amostras if l["endereco"].rsplit(":", 1)[0] == ALVO_DA_META}
    outras = {(l["origem"], l["alvo"]) for l in amostras} - para_a_meta
    faltas = []
    if not para_a_meta:
        faltas.append(f"nenhuma serie mede {ALVO_DA_META} (o host -> Meta do criterio 5)")
    if not outras:
        faltas.append("nenhuma serie mede outro alvo alem da Meta (a sonda -> host do criterio 5)")
    return faltas


def _ms(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:.1f}"


def tabela(series: list[Serie]) -> str:
    """A tabela do relatorio. E o texto que o ``verificar`` recalcula e compara."""
    linhas = [
        "| Origem | Alvo | Amostras | Falhas | 1.a medicao (UTC) | Ultima medicao (UTC) | Maior lacuna (s) | p50 (ms) | p95 (ms) | Max. (ms) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for serie in series:
        linhas.append(
            f"| {serie.origem} | {serie.alvo} | {serie.amostras} | {serie.falhas} | "
            f"{serie.inicio:%Y-%m-%d %H:%M} | {serie.fim:%Y-%m-%d %H:%M} | "
            f"{serie.maior_lacuna_s:.0f} | {_ms(serie.p50)} | {_ms(serie.p95)} | {_ms(serie.maximo)} |"
        )
    return "\n".join(linhas)


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


INICIO_TABELA = "<!-- borda-rtt:tabela -->"
FIM_TABELA = "<!-- /borda-rtt:tabela -->"


def relatorio(
    ficheiros: list[Path],
    janela_minima_s: int = JANELA_MINIMA_S,
    lacuna_maxima_s: int = LACUNA_MAXIMA_S,
) -> str:
    """O relatorio em Markdown, ou `Recusa` com todas as razoes."""
    amostras = [linha for caminho in ficheiros for linha in ler(caminho)]
    series = resumir(amostras)
    razoes = recusas(series, janela_minima_s, lacuna_maxima_s) + faltas_do_criterio(amostras)
    if razoes:
        raise Recusa("; ".join(razoes))
    fontes = "\n".join(f"- `{caminho.name}` — sha256 `{_sha256(caminho)}`" for caminho in ficheiros)
    return (
        "Gerado por `python -m borda rtt-relatorio` (KAM-077, criterio 5). Metodo: *handshake* TCP\n"
        "para a porta do alvo, percentis por posto mais proximo, falhas fora dos percentis e\n"
        f"contadas a parte. Janela minima {janela_minima_s} s; lacuna maxima {lacuna_maxima_s} s.\n"
        "`python -m borda rtt-verificar` recalcula esta tabela a partir dos ficheiros abaixo, falha se\n"
        "um so valor divergir e volta a aplicar as recusas com a janela de 24 h. Isso prova que a\n"
        "tabela e a das amostras; que as amostras foram medidas prova-o a cadeia de custodia delas.\n\n"
        f"{INICIO_TABELA}\n{tabela(series)}\n{FIM_TABELA}\n\n"
        f"Amostras (no repositorio de provas, privado):\n\n{fontes}\n"
    )


def verificar(texto_do_relatorio: str, ficheiros: list[Path]) -> list[str]:
    """Os desacordos entre o relatorio, as amostras e o criterio 5. Vazia = conforme."""
    problemas = []
    declarados = set(re.findall(r"sha256 `([0-9a-f]{64})`", texto_do_relatorio))
    presentes = {_sha256(caminho) for caminho in ficheiros}
    for falta in sorted(declarados - presentes):
        problemas.append(f"o relatorio declara o sha256 {falta} e nenhum ficheiro dado o tem")
    for sobra in sorted(presentes - declarados):
        problemas.append(f"um ficheiro dado (sha256 {sobra}) nao esta declarado no relatorio")
    casado = re.search(re.escape(INICIO_TABELA) + r"\n(.*?)\n" + re.escape(FIM_TABELA), texto_do_relatorio, re.S)
    if not casado:
        problemas.append("o relatorio nao tem a tabela entre os marcadores")
        return problemas
    amostras = [linha for caminho in ficheiros for linha in ler(caminho)]
    series = resumir(amostras)
    if casado.group(1).strip() != tabela(series).strip():
        problemas.append("a tabela do relatorio nao e a que as amostras dao")
    # As recusas outra vez, com os valores do CRITERIO e nao com os que o
    # `rtt-relatorio` tenha recebido: um relatorio gerado com
    # `--janela-minima 3600` bate com as amostras e nao e o criterio 5.
    problemas.extend(recusas(series, JANELA_MINIMA_S, LACUNA_MAXIMA_S))
    problemas.extend(faltas_do_criterio(amostras))
    return problemas
