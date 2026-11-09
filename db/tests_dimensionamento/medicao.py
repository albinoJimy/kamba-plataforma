"""A medicao do ensaio de carga (KAM-084): memoria, CPU, percentis e reconciliacao.

## A memoria e *working set*, e a definicao e a do `docs/tecnica/09` §1.4

O §1.4 define *working set* como «memoria residente tipica em carga, distinta
da reservada». A reservada e o `mem_limit` do compose; a residente e o que o
*cgroup* do contentor tem carregado. Mas o `memory.current` do cgroup v2 conta
tambem a *page cache* de ficheiros que o kernel pode largar sem custo nenhum —
um PostgreSQL que leu a tabela inteira uma vez fica com ela no
`memory.current`, e isso nao e memoria que o servico precise.

Por isso:

    working_set = memory.current - inactive_file

que e a mesma conta do `kubelet` e do `cAdvisor` (`container_memory_working_set_bytes`)
e a mesma que o `docker stats` faz em cgroup v2. Le-se **dos ficheiros do
cgroup**, e nao do `docker stats`, por uma razao que o criterio pede por
escrito («verificacao de que a medicao de memoria usa *working set* e nao
reservado»): com a conta aqui, a definicao esta num sitio que um teste le
(`test_medicao.py`), e nao no comportamento de uma versao do Docker CLI.

## A CPU e em nucleos, e a percentagem e sobre os nucleos do anfitriao

`cpu.stat` da `usage_usec` acumulado. Dois instantes dao nucleos usados no
intervalo: `delta(usage_usec) / delta(t_usec)`. **O instante e o `/proc/uptime`
da VM, lido no mesmo `cat`**, e nao o relogio de quem chama o `docker exec`: o
`exec` leva de 100 ms a segundos, e com o relogio do lado de fora o divisor
ficava errado pela diferenca entre dois `exec`. Foi um achado da revisao
adversarial, e a assinatura estava na corrida 2: quatro contentores com o
**mesmo** maximo de ~6,6 nucleos no mesmo cenario, incluindo dois processos de
um so fio. A percentagem do criterio
(«CPU <= 60%») e a soma dos nucleos dos contentores medidos sobre os nucleos
do anfitriao. **Mede so os contentores do ensaio**: o que mais corre na mesma
maquina nao entra na soma, e o relatorio diz quem mais estava a correr.
"""

from __future__ import annotations

import json
import math
import subprocess
import threading
import time
from dataclasses import dataclass, field

#: Os ficheiros, lidos num so `docker exec` por amostra. O `/proc/uptime` vem
#: primeiro e e o relogio da amostra (ver a docstring do modulo).
FICHEIROS_DO_CGROUP = (
    "/proc/uptime",
    "/sys/fs/cgroup/memory.current",
    "/sys/fs/cgroup/memory.stat",
    "/sys/fs/cgroup/cpu.stat",
)

MIB = 1024 * 1024


class CgroupIlegivel(ValueError):
    """A saida do `cat` nao tem a forma de um cgroup v2."""


@dataclass(frozen=True)
class Leitura:
    """Uma amostra de um contentor.

    `instante` e o `/proc/uptime` da VM no momento do `cat` (o que divide a
    CPU); `local` e o `time.monotonic()` de quem chamou (o que situa a amostra
    num degrau da rampa).
    """

    instante: float
    memory_current: int
    inactive_file: int
    usage_usec: int
    local: float = 0.0

    @property
    def working_set(self) -> int:
        return working_set(self.memory_current, self.inactive_file)


def working_set(memory_current: int, inactive_file: int) -> int:
    """`memory.current - inactive_file`, nunca negativo. Ver a docstring do modulo."""
    if memory_current < 0 or inactive_file < 0:
        raise CgroupIlegivel("contadores do cgroup negativos")
    return max(0, memory_current - inactive_file)


def ler_cgroup(texto: str, instante: float, local: float = 0.0) -> Leitura:
    """Interpreta a concatenacao de `memory.current`, `memory.stat` e `cpu.stat`.

    O `memory.current` e uma linha com um inteiro; os outros dois sao pares
    `chave valor`. As chaves nao colidem entre os dois ficheiros
    (`inactive_file` so existe no `memory.stat`, `usage_usec` so no `cpu.stat`).
    """
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    if not linhas or not linhas[0].isdigit():
        raise CgroupIlegivel("falta o memory.current na primeira linha")
    pares: dict[str, int] = {}
    for linha in linhas[1:]:
        partes = linha.split()
        if len(partes) == 2 and partes[1].lstrip("-").isdigit():
            pares[partes[0]] = int(partes[1])
    for chave in ("inactive_file", "usage_usec"):
        if chave not in pares:
            raise CgroupIlegivel(f"falta `{chave}`: o contentor nao esta em cgroup v2?")
    return Leitura(
        instante=instante,
        memory_current=int(linhas[0]),
        inactive_file=pares["inactive_file"],
        usage_usec=pares["usage_usec"],
        local=local,
    )


def nucleos(antes: Leitura, depois: Leitura) -> float:
    """Nucleos usados entre duas leituras do mesmo contentor."""
    intervalo = depois.instante - antes.instante
    if intervalo <= 0:
        raise ValueError("as leituras nao estao por ordem")
    return max(0, depois.usage_usec - antes.usage_usec) / (intervalo * 1_000_000)


def percentil(valores: list[float], p: float) -> float:
    """Percentil por **posicao mais proxima** (*nearest rank*), sem interpolar.

    A regra e a de quem le um criterio como «< 500 ms em >= 99,9%»: o p99,9 e
    um valor que **foi observado**, e nao uma media de dois vizinhos. Com 1 000
    amostras o p99,9 e a 999.a (a segunda pior), e com 999 e a pior: a posicao
    arredonda para cima. O `round` antes do `ceil` nao e enfeite: `99.9 / 100 *
    1000` da `999.0000000000001` em virgula flutuante, e sem ele o p99,9 de mil
    amostras saia a pior.
    """
    if not valores:
        raise ValueError("percentil de uma lista vazia")
    if not 0 < p <= 100:
        raise ValueError("p fora de ]0, 100]")
    ordenados = sorted(valores)
    posicao = math.ceil(round(p / 100 * len(ordenados), 9))
    return float(ordenados[posicao - 1])


def fraccao_abaixo(valores: list[float], limiar: float) -> float:
    """Fraccao dos valores **estritamente** abaixo do limiar (o «< 500 ms»)."""
    if not valores:
        raise ValueError("fraccao de uma lista vazia")
    return sum(1 for v in valores if v < limiar) / len(valores)


@dataclass(frozen=True)
class Reconciliacao:
    """O que se enviou contra o que a base tem, por `event_key`."""

    esperadas: int
    registadas: int
    em_falta: int
    a_mais: int


def reconciliar(enviadas: set[str], registadas: list[str]) -> Reconciliacao:
    """Compara conjuntos de chaves. `registadas` e lista para apanhar repetidas.

    A base tem `UNIQUE (kind, event_key)`, pelo que uma repetida aqui nunca
    acontece — **e por isso e que se conta**: se a restricao desaparecer, este
    numero e o que o diz, em vez de a reconciliacao passar por contar conjuntos.
    """
    unicas = set(registadas)
    return Reconciliacao(
        esperadas=len(enviadas),
        registadas=len(registadas),
        em_falta=len(enviadas - unicas),
        a_mais=len(unicas - enviadas) + (len(registadas) - len(unicas)),
    )


@dataclass(frozen=True)
class LeituraDoAnfitriao:
    """A VM do Docker inteira: `/proc/stat` e `/proc/meminfo`, que nao tem namespace.

    Lidos de dentro de **um** contentor do ensaio, dao a maquina toda — os
    contentores do ensaio **e** o que mais la estiver a correr. E o numero que o
    criterio pede («CPU <= 60%» e «memoria <= 65%» sao do *host*), e e tambem o
    que separa «o sistema esta lento» de «a maquina esta ocupada por outra
    coisa»: a diferenca entre este total e a soma dos contentores do ensaio e a
    contencao, medida.
    """

    instante: float
    ocupado: int
    total: int
    mem_total_kib: int
    mem_disponivel_kib: int

    @property
    def memoria_usada_mib(self) -> float:
        return (self.mem_total_kib - self.mem_disponivel_kib) / 1024


def ler_anfitriao(texto: str, instante: float) -> LeituraDoAnfitriao:
    """Interpreta `cat /proc/stat /proc/meminfo`.

    Ocupado e tudo menos `idle` e `iowait` (as colunas 4 e 5 da linha `cpu`);
    o `steal` conta como ocupado, porque e tempo que a VM nao teve.
    """
    cpu = None
    memoria: dict[str, int] = {}
    for linha in texto.splitlines():
        partes = linha.split()
        if not partes:
            continue
        if partes[0] == "cpu":
            valores = [int(v) for v in partes[1:]]
            if len(valores) < 5:
                raise CgroupIlegivel("linha `cpu` de /proc/stat curta")
            total = sum(valores[:8])
            cpu = (total - valores[3] - valores[4], total)
        elif partes[0] in ("MemTotal:", "MemAvailable:") and len(partes) >= 2:
            memoria[partes[0][:-1]] = int(partes[1])
    if cpu is None or set(memoria) != {"MemTotal", "MemAvailable"}:
        raise CgroupIlegivel("falta a linha `cpu` ou o MemTotal/MemAvailable")
    return LeituraDoAnfitriao(instante, cpu[0], cpu[1], memoria["MemTotal"], memoria["MemAvailable"])


def utilizacao(antes: LeituraDoAnfitriao, depois: LeituraDoAnfitriao) -> float:
    """Fraccao da CPU da VM ocupada entre duas leituras, em [0, 1]."""
    total = depois.total - antes.total
    if total <= 0:
        raise ValueError("as leituras nao estao por ordem")
    return max(0.0, min(1.0, (depois.ocupado - antes.ocupado) / total))


def separar_uptime(texto: str) -> tuple[float, str]:
    """`(segundos desde o arranque da VM, o resto)`. A primeira linha e o `/proc/uptime`."""
    primeira, _, resto = texto.partition("\n")
    partes = primeira.split()
    try:
        return float(partes[0]), resto
    except (IndexError, ValueError) as erro:
        raise CgroupIlegivel("a primeira linha nao e o /proc/uptime") from erro


def ler_contentor(nome: str) -> Leitura:
    """Um `docker exec` que le os ficheiros. Levanta se o contentor nao responder."""
    local = time.monotonic()
    resultado = subprocess.run(
        ["docker", "exec", nome, "cat", *FICHEIROS_DO_CGROUP],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if resultado.returncode != 0:
        raise CgroupIlegivel(f"docker exec {nome}: {resultado.stderr.strip()[:200]}")
    instante, resto = separar_uptime(resultado.stdout)
    return ler_cgroup(resto, instante, local)


@dataclass
class Serie:
    """As amostras de um contentor ao longo de um cenario."""

    leituras: list[Leitura] = field(default_factory=list)
    falhas: int = 0

    def working_sets_mib(self) -> list[float]:
        return [l.working_set / MIB for l in self.leituras]

    def nucleos(self) -> list[float]:
        return [
            nucleos(a, b)
            for a, b in zip(self.leituras, self.leituras[1:])
            if b.instante > a.instante
        ]

    def entre(self, inicio: float, fim: float) -> "Serie":
        """As leituras com `local` em `[inicio, fim]` — um degrau da rampa."""
        return Serie([l for l in self.leituras if inicio <= l.local <= fim], 0)

    def resumo(self) -> dict:
        ws = self.working_sets_mib()
        cpu = self.nucleos()
        if not ws:
            return {"amostras": 0, "falhas": self.falhas}
        return {
            "amostras": len(ws),
            "falhas": self.falhas,
            "ws_mib_p50": round(percentil(ws, 50), 1),
            "ws_mib_p95": round(percentil(ws, 95), 1),
            "ws_mib_max": round(max(ws), 1),
            "nucleos_p50": round(percentil(cpu, 50), 3) if cpu else None,
            "nucleos_p95": round(percentil(cpu, 95), 3) if cpu else None,
            "nucleos_max": round(max(cpu), 3) if cpu else None,
        }


def ler_anfitriao_por(nome: str) -> LeituraDoAnfitriao:
    instante = time.monotonic()
    resultado = subprocess.run(
        ["docker", "exec", nome, "cat", "/proc/stat", "/proc/meminfo"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if resultado.returncode != 0:
        raise CgroupIlegivel(f"docker exec {nome}: {resultado.stderr.strip()[:200]}")
    return ler_anfitriao(resultado.stdout, instante)


@dataclass
class SerieDoAnfitriao:
    leituras: list[LeituraDoAnfitriao] = field(default_factory=list)
    falhas: int = 0

    def entre(self, inicio: float, fim: float) -> "SerieDoAnfitriao":
        """As leituras com `instante` em `[inicio, fim]` (relogio de quem chama)."""
        return SerieDoAnfitriao([l for l in self.leituras if inicio <= l.instante <= fim], 0)

    def resumo(self) -> dict:
        if len(self.leituras) < 2:
            return {"amostras": len(self.leituras), "falhas": self.falhas}
        cpu = [utilizacao(a, b) * 100 for a, b in zip(self.leituras, self.leituras[1:])]
        mem = [l.memoria_usada_mib for l in self.leituras]
        return {
            "amostras": len(self.leituras),
            "falhas": self.falhas,
            "cpu_pct_p50": round(percentil(cpu, 50), 1),
            "cpu_pct_p95": round(percentil(cpu, 95), 1),
            "cpu_pct_max": round(max(cpu), 1),
            "mem_usada_mib_p95": round(percentil(mem, 95)),
            "mem_total_mib": round(self.leituras[-1].mem_total_kib / 1024),
        }


class Amostrador:
    """Le os contentores em ciclo, numa *thread*, ate `parar()`.

    Os contentores leem-se **em paralelo** dentro de cada ciclo (um `docker
    exec` leva 100 a 400 ms em Docker Desktop), para que a amostra de um nao
    atrase a dos outros e o intervalo seja de facto o pedido.
    """

    def __init__(
        self, contentores: dict[str, str], intervalo: float = 2.0, sonda: str | None = None
    ) -> None:
        #: rotulo -> nome do contentor
        self.contentores = dict(contentores)
        self.intervalo = intervalo
        self.series: dict[str, Serie] = {r: Serie() for r in contentores}
        #: O contentor por onde se le a VM inteira (`/proc/stat`). Nenhum se nao houver.
        self.sonda = sonda
        self.anfitriao = SerieDoAnfitriao()
        self._parar = threading.Event()
        self._fio: threading.Thread | None = None

    def _ler(self, rotulo: str, nome: str) -> None:
        try:
            self.series[rotulo].leituras.append(ler_contentor(nome))
        except (CgroupIlegivel, subprocess.TimeoutExpired, OSError):
            self.series[rotulo].falhas += 1

    def _ler_anfitriao(self) -> None:
        try:
            self.anfitriao.leituras.append(ler_anfitriao_por(self.sonda))
        except (CgroupIlegivel, subprocess.TimeoutExpired, OSError, ValueError):
            self.anfitriao.falhas += 1

    def _ciclo(self) -> None:
        while not self._parar.is_set():
            inicio = time.monotonic()
            fios = [
                threading.Thread(target=self._ler, args=(r, n), daemon=True)
                for r, n in self.contentores.items()
            ]
            if self.sonda:
                fios.append(threading.Thread(target=self._ler_anfitriao, daemon=True))
            for fio in fios:
                fio.start()
            for fio in fios:
                fio.join(timeout=30)
            resto = self.intervalo - (time.monotonic() - inicio)
            if resto > 0:
                self._parar.wait(resto)

    def comecar(self) -> "Amostrador":
        self._fio = threading.Thread(target=self._ciclo, daemon=True)
        self._fio.start()
        return self

    def parar(self) -> dict:
        self._parar.set()
        if self._fio is not None:
            self._fio.join(timeout=60)
        return {rotulo: serie.resumo() for rotulo, serie in self.series.items()}

    def resumo_do_anfitriao(self) -> dict:
        return self.anfitriao.resumo()


def soma_dos_p95(resumos: dict[str, dict], chave: str) -> float:
    """Soma de uma estatistica por contentor. **E um majorante**, e diz-se.

    Somar o p95 de cada contentor da um numero maior ou igual ao p95 da soma,
    porque os picos nao coincidem. Para «memoria <= 65%» e o lado seguro.
    """
    return round(sum(r.get(chave) or 0 for r in resumos.values()), 3)


def outros_contentores(nossos: set[str]) -> list[str]:
    """Os nomes do que mais esta a correr no mesmo Docker: a contencao, dita."""
    resultado = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True
    )
    if resultado.returncode != 0:
        return ["(docker ps falhou)"]
    return sorted(n for n in resultado.stdout.split() if n not in nossos)


def recursos_do_docker() -> dict:
    """Nucleos e memoria que o Docker ve — a escala real da maquina do ensaio."""
    resultado = subprocess.run(
        ["docker", "info", "--format", "{{json .}}"], capture_output=True, text=True
    )
    if resultado.returncode != 0:
        return {}
    dados = json.loads(resultado.stdout)
    return {
        "ncpu": dados.get("NCPU"),
        "mem_total_mib": round((dados.get("MemTotal") or 0) / MIB),
        "versao": dados.get("ServerVersion"),
        "cgroup": dados.get("CgroupVersion"),
    }
