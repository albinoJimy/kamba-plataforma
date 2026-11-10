"""O ensaio de carga do KAM-084 no segmento de entrada, com os processos de producao.

    python db/carga.py

Corre os **processos de producao** — duas replicas de `services/gwy/src/server.ts`
e uma de `services/worker-canal/src/entrada.ts`, que monta o CHR — contra um
PostgreSQL 18.6 e um Valkey reais, com 100 tenants e 100 canais sinteticos. Os
corpos sao assinados em Python (segunda implementacao, como no KAM-013).

## O que este ensaio mede, e o que nao mede

**Mede o segmento que existe a correr:** a entrada do webhook ate ao *job* do
AGR na fila `agr-inbound`. Ack, idade na fila, reconciliacao de ids, debito da
fila de entrada (*jobs*/min) e *working set* e CPU de cada contentor.

**Nao mede o AGR a correr turnos**, e nao por escolha: o `__main__.py` do AGR
passa `grafos=sem_grafos` ao `ExecutorDeTurnos`, e o `/internal/turn` responde
503 a todos os turnos (`turno.py`, `grafo_nao_registado`). Sem turno nao ha LLM,
nem degradacao N1/N2, nem *handoff* por *flood*. Os *jobs* do AGR acumulam-se na
`agr-inbound` sem consumidor — e o ensaio **conta-os**, o que prova que o CHR os
entregou sem duplicar, mas a memoria do Valkey inclui esse acumulado.

## Os contentores correm com os limites do compose de producao

Os quatro servicos medidos levam o `mem_limit` e o `cpus` que o
`infra/compose/docker-compose.prod.yml` lhes da (`docker update` depois do
arranque): `gwy` nas duas replicas, `worker-canal` no *worker* de entrada,
`postgres` e `queue`. **Sem isto, a primeira versao deste ensaio media processos
sem tecto** — o *worker* chegou a 0,89 nucleo, e o compose da-lhe 0,5 —, e a
fronteira da rampa saia mais alta do que a de producao. Achado da revisao
adversarial. Os valores leem-se do compose, e nao de uma copia aqui: se o
compose mudar, o ensaio segue-o.

## A escala e a de uma estacao de trabalho, e diz-se

O relatorio JSON leva os recursos do Docker em que correu (`docker info`) e os
contentores que **nao** eram do ensaio e estavam a correr ao mesmo tempo. Nada
aqui e medicao do *host* de producao de 8 vCPU / 32 GB: o que passar disso no
relatorio e extrapolacao, escrita como tal.

## O relatorio

Cada cenario escreve o seu bloco num JSON. O caminho e `KAMBA_CARGA_RELATORIO`,
ou um ficheiro novo na pasta temporaria; imprime-se no fim. **Os numeros que o
relatorio do ticket cita saem daqui**: o anexo de evidencia
(`docs/tecnica/evidencia/Carga_Dimensionamento.md`) transcreve-os, com a corrida
e a hora UTC de cada uma. O JSON nao se versiona — tem os nomes efemeros dos
contentores e nada que o anexo nao diga.

## Escolher cenarios

`KAMBA_CARGA_CENARIOS=s1,rajada` corre so esses; os outros **saltam**, e o
`correr_suite.py` faz de um salto uma falha. Uma corrida parcial nao e uma
corrida completa, e o codigo de saida di-lo.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path

import ligacao
from tests_dimensionamento import gerador, medicao
from tests_entrada import test_entrada as _entrada
from tests_entrada.test_entrada import (
    APP_SECRET_ACTUAL,
    ComEntrada,
    esperar_por,
)

#: A espera pelo arranque dos processos Node, **so nesta suite**: 600 s em vez
#: dos 180 do `tests_entrada`. A razao e a do proprio `ARRANQUE` de la —
#: «tolerancia de ambiente, nao alvo de latencia» —, agravada aqui: os processos
#: arrancam com o `cpus` do compose (1,0 no GWY, 0,5 no *worker*), e numa VM
#: partilhada o GWY nao respondeu em 180 s (corrida 7, com o KAM-187 e o KAM-083
#: no mesmo Docker). Le-se pelo nome do modulo porque e assim que o
#: `_lancar_gwy` o le.
_entrada.ARRANQUE = max(_entrada.ARRANQUE, 600.0)

#: --- O perfil (doc 09 §14.1), e a leitura dele ------------------------------
#:
#: 10 PMEs x 300 conversas x 8 turnos = 24 000 mensagens de cliente por mes, e
#: cada resposta do bot da tres estados. Por mes: ~24 000 corpos de mensagem e
#: ~86 400 de estado, ~110 000 *webhooks*. Em 22 dias de 10 horas uteis isso e
#: **0,14 *webhooks*/s** em media. O factor de hora de ponta e uma hipotese a
#: medir com trafego real e nao a assumir (bloco do ticket), e por isso o S1 e
#: escolhido **pessimista**: 5/s, isto e, ~36x a media das horas uteis. *Proposta*.
TAXA_S1 = 5.0
#: O S2 e o S1 x10 (o perfil Clusters inicial, ~100 PMEs).
TAXA_S2 = 50.0
#: `KAMBA_CARGA_DURACAO_S` encurta o S1 e o S2 para corridas de desenvolvimento.
#: O valor usado vai no relatorio de cada cenario: uma corrida curta nao passa
#: por uma corrida do criterio.
DURACAO_S = float(os.environ.get("KAMBA_CARGA_DURACAO_S") or 300.0)
#: `KAMBA_CARGA_PARALELISMO` fixa as *threads* do gerador, para medir o efeito
#: do *keep-alive* (ver `gerador.py`). Sem ele, `gerador.paralelismo_para`.
PARALELISMO_FORCADO = int(os.environ["KAMBA_CARGA_PARALELISMO"]) if os.environ.get(
    "KAMBA_CARGA_PARALELISMO"
) else None
#: Canais (= tenants) de cada perfil.
CANAIS_S1 = 10
CANAIS_S2 = 100
CONTACTOS_POR_CANAL = 50

#: Rajada: uma hora de *backlog* do ritmo do S1, reentregue a 20x. E mais 10%
#: dos corpos **repetidos** 30 s depois com os mesmos bytes — a reentrega da Meta
#: nao garante que o que ja chegou nao volte.
BACKLOG_S = 3600.0
FACTOR_DA_RAJADA = 20.0
FRACCAO_REPETIDA = 0.10
ATRASO_DA_REPETICAO_S = 30.0

#: Rampa: degraus contiguos ate um falhar. A duracao e curta porque cada degrau
#: acumula na fila o que o *worker* nao consumir.
DEGRAUS = (100.0, 200.0, 400.0, 800.0, 1200.0)
DURACAO_DO_DEGRAU_S = 45.0

#: --- Os limiares do criterio 2 ----------------------------------------------
ACK_LIMIAR_MS = 500.0
ACK_FRACCAO_MINIMA = 0.999
IDADE_MAXIMA_S = 120.0
#: Um gerador atrasado mais do que isto no p99 nao esta a impor a taxa.
ATRASO_DO_GERADOR_MAXIMO_MS = 100.0

#: Segundos a esperar que a fila de entrada drene depois de um cenario.
DRENAGEM_S = 900.0
#: Intervalo do amostrador de memoria e CPU.
INTERVALO_DA_AMOSTRA_S = 2.0

FILA_ENTRADA = "wa-inbound"
FILA_AGR = "agr-inbound"

#: O compose de producao, de onde se leem os limites de cada contentor medido.
COMPOSE_DE_PRODUCAO = Path(__file__).resolve().parents[2] / "infra" / "compose" / "docker-compose.prod.yml"
#: rotulo do contentor no ensaio -> servico do compose cujos limites leva.
SERVICO_DO_COMPOSE = {
    "gwy_a": "gwy",
    "gwy_b": "gwy",
    "worker_entrada": "worker-canal",
    "postgres": "postgres",
    "valkey": "queue",
}


def limites_do_compose(texto: str, servico: str) -> tuple[str, str]:
    """`(mem_limit, cpus)` de um servico, lidos do bloco dele no compose.

    Por expressao regular e nao pelo `tools/kamba_yaml.py`, que recusa ancoras
    (`&node`) e o compose de producao usa-as. O bloco de um servico e o que esta
    entre `  <servico>:` e o proximo nome com dois espacos de indentacao; as
    duas chaves estao sempre la por regra do `tools/compose_prod`.
    """
    import re

    achado = re.search(rf"(?m)^  {re.escape(servico)}:\n(.*?)(?=^  \S|\Z)", texto, re.S)
    if achado is None:
        raise AssertionError(f"servico {servico} nao esta no compose de producao")
    bloco = achado.group(1)
    memoria = re.search(r"(?m)^    mem_limit:\s*(\S+)", bloco)
    cpus = re.search(r"(?m)^    cpus:\s*(\S+)", bloco)
    if memoria is None or cpus is None:
        raise AssertionError(f"o servico {servico} nao tem mem_limit e cpus no compose")
    return memoria.group(1), cpus.group(1)


def _cenarios_escolhidos() -> set[str] | None:
    bruto = os.environ.get("KAMBA_CARGA_CENARIOS", "").strip()
    return {c.strip() for c in bruto.split(",") if c.strip()} or None


def _degrau_falhou(degrau: dict) -> bool:
    """O degrau falha o criterio 2, ou o gerador nao impos a taxa."""
    return (
        set(degrau["codigos"]) != {"200"}
        or degrau["ack_fraccao_abaixo_500ms"] < ACK_FRACCAO_MINIMA
        or degrau["atraso_do_gerador_ms_p99"] > ATRASO_DO_GERADOR_MAXIMO_MS
    )


class TestDimensionamento(ComEntrada):
    """Os cenarios do KAM-084 que tem sujeito: repouso, S1, S2, rajada e rampa."""

    PROCESSOS = ()

    @classmethod
    def _arrancar_processos(cls) -> None:
        # Os processos Node **arrancam** com os limites do compose, e nao os
        # recebem depois: o V8 dimensiona o *heap* pela memoria que ve ao
        # arrancar (2 240 MiB sem limite contra 259 MiB com `--memory 256m`,
        # medido). A corrida 5 aplicava-os com `docker update` e o *worker*
        # morreu a 251,7 MiB de 256 — artefacto do ensaio, achado N3 da
        # revisao adversarial.
        texto = COMPOSE_DE_PRODUCAO.read_text(encoding="utf-8")
        cls.processos = []
        cls.gwy_a = cls._lancar_gwy(limites=limites_do_compose(texto, "gwy"))
        cls.gwy_b = cls._lancar_gwy(limites=limites_do_compose(texto, "gwy"))
        cls.worker = cls._lancar_worker(limites=limites_do_compose(texto, "worker-canal"))

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.canais = cls._semear(CANAIS_S2)
        cls.fabrica = gerador.Fabrica(
            APP_SECRET_ACTUAL, cls.canais, CONTACTOS_POR_CANAL, semente=84
        )
        cls.contentores = {
            "gwy_a": cls.gwy_a.contentor,
            "gwy_b": cls.gwy_b.contentor,
            "worker_entrada": cls.worker.contentor,
            "postgres": os.environ.get("KAMBA_GATE_CONTENTOR"),
            "valkey": os.environ.get("KAMBA_GATE_FILA"),
        }
        cls.relatorio = {
            "ticket": "KAM-084",
            "inicio_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "maquina": medicao.recursos_do_docker(),
            "contentores": {r: n for r, n in cls.contentores.items()},
            "limites": cls._aplicar_limites(),
            "cenarios": {},
        }
        cls.eventos_docker = []
        cls._vigiar_docker()

    @classmethod
    def _vigiar_docker(cls) -> None:
        """Guarda os `oom` e `die` que o Docker emitir para os contentores do ensaio.

        **E, com o codigo de saida, a unica prova directa de uma morte por
        memoria.** O `oom_kill` do cgroup so se le enquanto o contentor existe, e
        um *worker* morto pelo kernel leva o contentor com ele (`--rm`), pelo que
        o ensaio nao o le (achado N7). O registo do Docker e circular e as
        amostras do `docker exec` enchem-no em minutos — na corrida 5, quando se
        foi procurar, o `die` do *worker* ja la nao estava.
        """
        import subprocess

        comando = ["docker", "events", "--format", "{{.Action}} {{.Actor.Attributes.name}} {{.Actor.Attributes.exitCode}}"]
        for nome in cls.contentores.values():
            if nome:
                comando += ["--filter", f"container={nome}"]
        comando += ["--filter", "event=oom", "--filter", "event=die"]
        cls._eventos = subprocess.Popen(
            comando, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )

        def ler() -> None:
            for linha in cls._eventos.stdout:
                cls.eventos_docker.append(f"{time.strftime('%H:%M:%SZ', time.gmtime())} {linha.strip()}")

        threading.Thread(target=ler, daemon=True).start()

    @classmethod
    def _aplicar_limites(cls) -> dict:
        """Poe em cada contentor o `mem_limit` e o `cpus` do servico no compose.

        Os tres processos Node ja arrancaram com eles (`_arrancar_processos`);
        aqui so se poem no PostgreSQL e no Valkey, que o `gate_bd.py` levanta e
        que nao dimensionam memoria pelo cgroup no arranque (o
        `shared_buffers` e o `maxmemory` sao configuracao, nao deteccao).
        """
        import subprocess

        texto = COMPOSE_DE_PRODUCAO.read_text(encoding="utf-8")
        aplicados = {}
        for rotulo, servico in SERVICO_DO_COMPOSE.items():
            nome = cls.contentores.get(rotulo)
            memoria, cpus = limites_do_compose(texto, servico)
            if not nome:
                aplicados[rotulo] = "sem contentor (node no PATH): limites por aplicar"
                continue
            if rotulo in ("gwy_a", "gwy_b", "worker_entrada"):
                aplicados[rotulo] = {
                    "servico": servico, "mem_limit": memoria, "cpus": cpus, "quando": "no arranque",
                }
                continue
            feito = subprocess.run(
                ["docker", "update", "--cpus", cpus, "--memory", memoria,
                 "--memory-swap", memoria, nome],
                capture_output=True, text=True,
            )
            if feito.returncode != 0:
                raise AssertionError(f"limites de {rotulo}: {feito.stderr.strip()[:300]}")
            aplicados[rotulo] = {"servico": servico, "mem_limit": memoria, "cpus": cpus, "quando": "docker update"}
        return aplicados

    def _guardar(self) -> None:
        """Escreve o relatorio **depois de cada cenario**.

        Um `TimeoutExpired` no `gate_bd.py` mata a suite de fora e salta o
        `tearDownClass` — e e quando o sistema falha que o relatorio faz falta.
        """
        self.relatorio["fim_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        Path(self._destino()).write_text(
            json.dumps(self.relatorio, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
        )

    @classmethod
    def _destino(cls) -> str:
        if not getattr(cls, "_caminho", None):
            cls._caminho = os.environ.get("KAMBA_CARGA_RELATORIO") or str(
                Path(tempfile.gettempdir()) / f"kamba-carga-{time.strftime('%Y%m%dT%H%M%S')}.json"
            )
        return cls._caminho

    @classmethod
    def tearDownClass(cls) -> None:
        destino = cls._destino()
        relatorio = getattr(cls, "relatorio", None)
        if getattr(cls, "_eventos", None) is not None:
            cls._eventos.terminate()
        if relatorio is not None:
            relatorio["eventos_docker"] = list(getattr(cls, "eventos_docker", []))
            relatorio["fim_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            Path(destino).write_text(
                json.dumps(relatorio, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
            )
            print(f"\n--- relatorio do KAM-084: {destino} ---")
        super().tearDownClass()

    # --- preparacao --------------------------------------------------------

    @classmethod
    def _semear(cls, quantos: int) -> list[gerador.Canal]:
        """`quantos` tenants `ativo`, cada um com um canal `ativo` em coexistencia (vendedor).

        O tenant nasce `onboarding` por omissao, e o CHR recusa-o pela matriz de
        estados (`chr_estado_recusou`, `estado_pendente`) depois de registar a
        conversa: medido na segunda corrida, 150 de 150 mensagens. Um ensaio de
        carga sobre tenants que nao estao a vender mede o caminho errado.
        """
        cursor = cls._admin.cursor()
        # **A versao actual da chave de pesquisa, registada.** Sem ela o CHR
        # falha cada mensagem com `SemChaveActualError` e o *job* repete — e a
        # primeira corrida deste ensaio mediu exactamente isso sem dar por ela:
        # as 4 500 mensagens da rajada ficaram em `inbound_events` (que se
        # escreve **antes** do CHR) e **nenhuma** chegou ao AGR. O `kid` e o que
        # `node.chaves_de_identidade()` poe no ambiente do *worker*; em producao
        # quem o regista e a rotacao (`iniciarRotacao`).
        cursor.execute(
            "INSERT INTO platform.hmac_key_versions (kid, estado) VALUES ('k-entrada', 'actual') "
            "ON CONFLICT DO NOTHING"
        )
        canais = []
        for indice in range(quantos):
            tenant = str(uuid.uuid4())
            waba = f"1090000000{indice:05d}"
            pnid = f"1230000000{indice:05d}"
            cursor.execute(
                "INSERT INTO platform.tenants (id, tipo, nome, estado) VALUES (%s, 'pme', %s, 'ativo')",
                (tenant, f"Loja sintetica {indice:03d}"),
            )
            cursor.execute(
                "INSERT INTO platform.tenant_channels "
                "(tenant_id, waba_id, phone_number_id, channel_mode, vertical, origem, estado, token_ref) "
                "VALUES (%s, %s, %s, 'coexistencia', 'vendedor', 'pme', 'ativo', %s)",
                (tenant, waba, pnid, f"ref-opaca/kam084-{indice:03d}"),
            )
            canais.append(gerador.Canal(tenant, waba, pnid, indice))
        return canais

    def setUp(self) -> None:
        super().setUp()
        escolhidos = _cenarios_escolhidos()
        nome = self._testMethodName.split("_", 2)[-1]
        if escolhidos is not None and nome not in escolhidos:
            self.skipTest(f"cenario {nome} fora de KAMBA_CARGA_CENARIOS")

    # --- medicao comum -----------------------------------------------------

    def _desvio_do_relogio(self) -> float:
        """`relogio_da_base - relogio_do_anfitriao`, em segundos, pelo menor RTT.

        A idade na fila compara o `recebido_at` (relogio da base, dentro da VM
        do Docker) com o instante de envio (relogio do Windows). Sem corrigir o
        desvio, a idade media o desvio entre relogios. O erro desta estimativa e
        no maximo metade do RTT da amostra escolhida, e vai no relatorio.
        """
        melhor = None
        for _ in range(7):
            antes = time.time()
            self.cursor.execute("SELECT extract(epoch FROM clock_timestamp())::float8")
            base = float(self.cursor.fetchone()[0])
            depois = time.time()
            rtt = depois - antes
            if melhor is None or rtt < melhor[0]:
                melhor = (rtt, base - (antes + depois) / 2)
        self._erro_do_desvio_s = melhor[0] / 2
        return melhor[1]

    def _profundidades(self, parar: threading.Event, saida: list[tuple[float, int, int]]) -> None:
        from tests_eventos import fila as fila_mod

        fila = fila_mod.Fila()
        fila.ligar()
        try:
            while not parar.is_set():
                saida.append((time.monotonic(), fila.pendentes(FILA_ENTRADA), fila.pendentes(FILA_AGR)))
                parar.wait(1.0)
        finally:
            fila.fechar()

    @staticmethod
    def _llen(chave: str) -> int:
        from tests_eventos import fila as fila_mod

        fila = fila_mod.Fila()
        fila.ligar()
        try:
            return int(fila.comando("LLEN", chave) or 0)
        finally:
            fila.fechar()

    def _entrada_vazia(self) -> bool:
        return (
            self._llen(f"bull:{FILA_ENTRADA}:wait") == 0
            and self._llen(f"bull:{FILA_ENTRADA}:active") == 0
        )

    def _registadas(self) -> list[tuple[str, str, float]]:
        self.cursor.execute(
            "SELECT kind, event_key, extract(epoch FROM recebido_at)::float8 "
            "FROM platform.inbound_events"
        )
        return [(k, e, float(t)) for k, e, t in self.cursor.fetchall()]

    def _contar(self) -> int:
        self.cursor.execute("SELECT count(*) FROM platform.inbound_events")
        return int(self.cursor.fetchone()[0])

    def _correr(
        self,
        nome: str,
        planos: list[tuple[str, list[gerador.Pedido]]],
        *,
        repetidas: dict | None = None,
        parar_se=None,
        extra: dict | None = None,
    ) -> dict:
        """Dispara os planos em sequencia (sem drenar entre eles), drena e mede."""
        desvio = self._desvio_do_relogio()
        outros = medicao.outros_contentores({n for n in self.contentores.values() if n})
        amostrador = medicao.Amostrador(
            {r: n for r, n in self.contentores.items() if n},
            INTERVALO_DA_AMOSTRA_S,
            sonda=self.contentores["valkey"],
        ).comecar()
        parar = threading.Event()
        profundidades: list[tuple[float, int, int]] = []
        vigia = threading.Thread(target=self._profundidades, args=(parar, profundidades), daemon=True)
        vigia.start()

        linhas_antes = len(self.worker.linhas())
        enviados: dict[tuple[str, str], float] = {}
        jobs_esperados: set[str] = set()
        degraus = []
        janelas: list[tuple[float, float]] = []
        inicio_monotonico = time.monotonic()
        for rotulo, plano in planos:
            antes = time.monotonic()
            linhas_gwy = (len(self.gwy_a.linhas()), len(self.gwy_b.linhas()))
            resultados = gerador.disparar(
                plano, [self.gwy_a.porta, self.gwy_b.porta], paralelismo=PARALELISMO_FORCADO
            )
            depois = time.monotonic()
            for pedido, resultado in zip(plano, resultados):
                enviados.setdefault(pedido.chave, resultado.enviado_epoch)
                if pedido.chave[0] == "message":
                    jobs_esperados.add(gerador.job_do_agr(pedido.tenant_id, pedido.chave[1]))
            degrau = self._resumo_do_disparo(rotulo, plano, resultados, depois - antes, profundidades)
            degrau["ack_no_servidor_ms"] = self._latencia_no_servidor(linhas_gwy)
            degraus.append(degrau)
            janelas.append((antes, depois))
            if parar_se is not None and parar_se(degrau):
                degrau["parou_aqui"] = True
                break
        fim_do_envio = time.monotonic()

        esperadas = {f"{k}|{e}" for k, e in enviados}
        drenou = esperar_por(lambda: self._contar() >= len(esperadas), DRENAGEM_S, 2.0)
        # O `inbound_events` escreve-se **antes** do CHR, pelo que a contagem
        # da base chega ao fim antes do ultimo *job* do AGR. Espera-se tambem
        # que a fila de entrada fique vazia e assente.
        drenou = drenou and esperar_por(self._entrada_vazia, DRENAGEM_S, 2.0)
        drenagem_s = time.monotonic() - fim_do_envio
        # Mais duas amostras depois de drenar, para o pico nao ficar de fora.
        time.sleep(2 * INTERVALO_DA_AMOSTRA_S)
        parar.set()
        vigia.join(timeout=10)
        recursos = amostrador.parar()
        # Os recursos **por degrau**: a CPU e a memoria de cada contentor nas
        # amostras do intervalo de envio desse degrau. Sem isto, a rampa so tinha
        # o resumo do cenario inteiro, e nada isolava o que satura em cada degrau.
        for degrau, (antes, depois) in zip(degraus, janelas):
            degrau["recursos"] = {
                r: serie.entre(antes, depois).resumo() for r, serie in amostrador.series.items()
            }
            degrau["anfitriao"] = amostrador.anfitriao.entre(antes, depois).resumo()
        outros = sorted(
            set(outros)
            | set(medicao.outros_contentores({n for n in self.contentores.values() if n}))
        )
        jobs_na_fila = self._lrange(f"bull:{FILA_AGR}:wait")

        registadas = self._registadas()
        diagnostico = self._diagnostico(linhas_antes)
        reconciliacao = medicao.reconciliar(esperadas, [f"{k}|{e}" for k, e, _ in registadas])
        idades = []
        for kind, chave, recebido in registadas:
            envio = enviados.get((kind, chave))
            if envio is not None:
                idades.append(recebido - (envio + desvio))
        mensagens_unicas = sum(1 for k, _ in enviados if k == "message")
        bloco = {
            **(extra or {}),
            "paralelismo_forcado": PARALELISMO_FORCADO,
            "degraus": degraus,
            "drenou": drenou,
            "drenagem_s": round(drenagem_s, 1),
            "duracao_total_s": round(fim_do_envio - inicio_monotonico, 1),
            "repetidas_enviadas": repetidas or {},
            "reconciliacao": reconciliacao.__dict__,
            "mensagens_unicas": mensagens_unicas,
            # Lido agora, depois de drenar, e nao da ultima amostra da vigia.
            "jobs_agr_inbound_no_fim": len(jobs_na_fila),
            # **Por identidade e nao por contagem**: o conjunto de `jobId` na
            # fila contra o que o plano da (`sha256(tenant:wamid)`). Uma troca —
            # o job de uma mensagem em falta e o de outra em dobro — passava na
            # contagem. Achado da revisao adversarial.
            "jobs_agr_em_falta": len(jobs_esperados - set(jobs_na_fila)),
            "jobs_agr_a_mais": len(set(jobs_na_fila) - jobs_esperados)
            + (len(jobs_na_fila) - len(set(jobs_na_fila))),
            "fila_entrada_max": max((p[1] for p in profundidades), default=None),
            "idade_na_fila_s": self._estatisticas(idades),
            "desvio_do_relogio_s": round(desvio, 4),
            "erro_do_desvio_s": round(self._erro_do_desvio_s, 4),
            "debito_de_consumo_por_s": self._debito([t for _, _, t in registadas]),
            "recursos": recursos,
            "soma_ws_mib_p95": medicao.soma_dos_p95(recursos, "ws_mib_p95"),
            "soma_nucleos_p95": medicao.soma_dos_p95(recursos, "nucleos_p95"),
            # A VM inteira: o ensaio **e** o que mais la estiver (ver `medicao.py`).
            "anfitriao": amostrador.resumo_do_anfitriao(),
            "outros_contentores": outros,
            "destino": diagnostico,
            # O estado dos tres processos no fim: `None` vivo, ou o codigo de
            # saida do `docker run` (137 e SIGKILL — o do OOM). Entrou com a
            # corrida 5, em que a fila deixou de drenar sem nada o dizer.
            "processos": {
                "gwy_a": self.gwy_a.popen.poll(),
                "gwy_b": self.gwy_b.popen.poll(),
                "worker_entrada": self.worker.popen.poll(),
            },
            "eventos_docker": list(self.eventos_docker),
        }
        self.relatorio["cenarios"][nome] = bloco
        self._guardar()
        print(f"\n--- {nome} ---\n{json.dumps(bloco, indent=2, ensure_ascii=False)}")
        return bloco

    def _latencia_no_servidor(self, linhas_antes: tuple[int, int]) -> dict | None:
        """A latencia que o **GWY** mediu (`latency_ms` do `webhook_enfileirado`).

        E o que separa o servidor do resto: a latencia do cliente soma-lhe a fila
        do gerador e o encaminhamento de portas do Docker Desktop.
        """
        valores = []
        for processo, antes in zip((self.gwy_a, self.gwy_b), linhas_antes):
            for linha in processo.linhas()[antes:]:
                if linha.get("outcome") == "webhook_enfileirado" and "latency_ms" in linha:
                    valores.append(float(linha["latency_ms"]))
        return self._estatisticas(valores)

    @staticmethod
    def _lrange(chave: str) -> list[str]:
        from tests_eventos import fila as fila_mod

        fila = fila_mod.Fila()
        fila.ligar()
        try:
            return [str(x) for x in (fila.comando("LRANGE", chave, "0", "-1") or [])]
        finally:
            fila.fechar()

    def _diagnostico(self, linhas_antes: int) -> dict:
        """Para onde foram as mensagens: o que o CHR fez com elas.

        A fila `agr-inbound` diz quantas chegaram ao AGR; isto diz o resto — os
        `outcome` que o *worker* registou neste cenario, o que ficou em
        `unrouted_events` e quantas conversas e contactos existem.
        """
        desfechos: dict[str, int] = {}
        for linha in self.worker.linhas()[linhas_antes:]:
            chave = f"{linha.get('outcome')}|{linha.get('error_code') or ''}"
            desfechos[chave] = desfechos.get(chave, 0) + 1
        self.cursor.execute(
            "SELECT kind, motivo, count(*) FROM platform.unrouted_events GROUP BY 1, 2"
        )
        nao_encaminhados = {f"{k}|{m}": int(n) for k, m, n in self.cursor.fetchall()}
        contagens = {}
        for tabela in ("conversations", "contacts"):
            self.cursor.execute(f"SELECT count(*) FROM platform.{tabela}")
            contagens[tabela] = int(self.cursor.fetchone()[0])
        return {
            "desfechos_do_worker": dict(sorted(desfechos.items())),
            "unrouted_events": nao_encaminhados,
            **contagens,
        }

    @staticmethod
    def _estatisticas(valores: list[float]) -> dict | None:
        if not valores:
            return None
        return {
            "n": len(valores),
            "p50": round(medicao.percentil(valores, 50), 3),
            "p95": round(medicao.percentil(valores, 95), 3),
            "p99": round(medicao.percentil(valores, 99), 3),
            "max": round(max(valores), 3),
        }

    @staticmethod
    def _debito(instantes: list[float]) -> dict | None:
        """Eventos registados por segundo, pelo `recebido_at`: o debito do *worker*."""
        if not instantes:
            return None
        por_segundo: dict[int, int] = {}
        for t in instantes:
            por_segundo[int(t)] = por_segundo.get(int(t), 0) + 1
        janela = max(por_segundo) - min(por_segundo) + 1
        # O maximo sustentado: a melhor media em 10 s consecutivos.
        segundos = range(min(por_segundo), max(por_segundo) + 1)
        serie = [por_segundo.get(s, 0) for s in segundos]
        melhor_10s = max(
            (sum(serie[i : i + 10]) / min(10, len(serie)) for i in range(max(1, len(serie) - 9))),
            default=0,
        )
        return {
            "media": round(len(instantes) / janela, 1),
            "max_10s": round(melhor_10s, 1),
            "max_10s_por_min": round(melhor_10s * 60),
        }

    def _resumo_do_disparo(self, rotulo, plano, resultados, duracao, profundidades) -> dict:
        latencias = [r.latencia_ms for r in resultados]
        atrasos = [r.atraso_ms for r in resultados]
        codigos: dict[int, int] = {}
        for r in resultados:
            codigos[r.codigo] = codigos.get(r.codigo, 0) + 1
        alvo = len(plano) / max(plano[-1].alvo - plano[0].alvo, 1e-9) if len(plano) > 1 else None
        return {
            "rotulo": rotulo,
            "pedidos": len(resultados),
            "taxa_alvo_por_s": round(alvo, 1) if alvo else None,
            "taxa_conseguida_por_s": round(len(resultados) / duracao, 1),
            "codigos": {str(k): v for k, v in sorted(codigos.items())},
            "ack_ms": self._estatisticas(latencias)
            | {"p999": round(medicao.percentil(latencias, 99.9), 1)},
            "ack_fraccao_abaixo_500ms": round(medicao.fraccao_abaixo(latencias, ACK_LIMIAR_MS), 5),
            "atraso_do_gerador_ms_p99": round(medicao.percentil(atrasos, 99), 1),
            "reconexoes": sum(1 for r in resultados if r.reconectou),
            "reconexoes_por_erro": {
                erro: sum(1 for r in resultados if r.erro == erro)
                for erro in sorted({r.erro for r in resultados if r.erro})
            },
            "fila_entrada_no_fim": profundidades[-1][1] if profundidades else None,
        }

    def _afirmar_sem_perdas(self, bloco: dict) -> None:
        rec = bloco["reconciliacao"]
        self.assertTrue(
            bloco["drenou"],
            f"a fila nao drenou em {DRENAGEM_S}s; processos {bloco['processos']}"
            f"{self.worker.diagnostico()}",
        )
        self.assertEqual(rec["em_falta"], 0, "ha eventos aceites que a base nao tem")
        self.assertEqual(rec["a_mais"], 0, "ha eventos na base que nao foram enviados, ou repetidos")
        # **E a jusante, por identidade e nao por `<=`.** Cada mensagem unica e
        # o seu *job* na `agr-inbound`, e nenhuma repetida da outro. Com `<=`,
        # zero *jobs* passava — e passou, na primeira corrida, com o CHR a falhar
        # todas as mensagens; e com `==` sobre a contagem, uma troca passava.
        self.assertEqual(bloco["jobs_agr_em_falta"], 0, bloco["destino"])
        self.assertEqual(bloco["jobs_agr_a_mais"], 0, bloco["destino"])
        self.assertEqual(
            bloco["jobs_agr_inbound_no_fim"], bloco["mensagens_unicas"], bloco["destino"]
        )

    def _afirmar_criterio_2(self, bloco: dict) -> None:
        for degrau in bloco["degraus"]:
            self.assertEqual(set(degrau["codigos"]), {"200"}, degrau)
            self.assertGreaterEqual(degrau["ack_fraccao_abaixo_500ms"], ACK_FRACCAO_MINIMA, degrau)
        self.assertLess(bloco["idade_na_fila_s"]["max"], IDADE_MAXIMA_S, bloco["idade_na_fila_s"])

    # --- os cenarios -------------------------------------------------------

    def test_1_repouso(self) -> None:
        """60 s sem trafego: a referencia para o KAM-076 §9."""
        amostrador = medicao.Amostrador(
            {r: n for r, n in self.contentores.items() if n},
            INTERVALO_DA_AMOSTRA_S,
            sonda=self.contentores["valkey"],
        ).comecar()
        time.sleep(60)
        recursos = amostrador.parar()
        self.relatorio["cenarios"]["repouso"] = {
            "recursos": recursos,
            "anfitriao": amostrador.resumo_do_anfitriao(),
            "soma_ws_mib_p95": medicao.soma_dos_p95(recursos, "ws_mib_p95"),
            "outros_contentores": medicao.outros_contentores(
                {n for n in self.contentores.values() if n}
            ),
        }
        self._guardar()
        print(f"\n--- repouso ---\n{json.dumps(recursos, indent=2)}")
        self.assertTrue(all(r.get("amostras", 0) > 0 for r in recursos.values()), recursos)

    def test_2_s1(self) -> None:
        plano = self.fabrica.plano(TAXA_S1, DURACAO_S, canais=self.canais[:CANAIS_S1])
        bloco = self._correr("s1", [("s1", plano)], extra={"duracao_pedida_s": DURACAO_S})
        self._afirmar_sem_perdas(bloco)
        self._afirmar_criterio_2(bloco)

    def test_3_s2(self) -> None:
        plano = self.fabrica.plano(TAXA_S2, DURACAO_S, canais=self.canais[:CANAIS_S2])
        bloco = self._correr("s2", [("s2", plano)], extra={"duracao_pedida_s": DURACAO_S})
        # «Se S2 falhar, regista-se o limite como fronteira do perfil P0»: o
        # criterio 2 regista-se e nao se afirma. A perda afirma-se sempre.
        self._afirmar_sem_perdas(bloco)

    def test_4_rajada(self) -> None:
        unicos = int(TAXA_S1 * BACKLOG_S)
        taxa = TAXA_S1 * FACTOR_DA_RAJADA
        plano = self.fabrica.plano(taxa, unicos / taxa, canais=self.canais[:CANAIS_S1])
        # **Duas formas de repeticao, metade cada**, porque sao dois niveis de
        # deduplicacao diferentes, e a primeira versao so media o primeiro:
        # - os **mesmos bytes**, que o GWY reconhece pelo `jobId = sha256(corpo)`
        #   enquanto o *job* estiver na retencao da fila (10 000 concluidos);
        # - o **mesmo JSON com outros bytes**, que passa o GWY, chega ao *worker*
        #   e so a `UNIQUE (kind, event_key)` de `inbound_events` apanha — e e o
        #   caminho de uma reentrega da Meta depois de a retencao a ter esquecido.
        # E **cada grupo e metade mensagens e metade estados** (achado N1): so
        # uma mensagem diz se o CHR deixa de criar o *job* do AGR.
        por_grupo = int(round(len(plano) * FRACCAO_REPETIDA / 2))
        base_iguais, base_outros = gerador.escolher_repetidas(plano, por_grupo)
        iguais = [
            gerador.Pedido(p.alvo + ATRASO_DA_REPETICAO_S, p.corpo, p.assinatura, p.chave, p.tenant_id)
            for p in base_iguais
        ]
        outros_bytes = [
            gerador.reserializado(
                gerador.Pedido(p.alvo + ATRASO_DA_REPETICAO_S, p.corpo, p.assinatura, p.chave, p.tenant_id),
                APP_SECRET_ACTUAL,
            )
            for p in base_outros
        ]
        completo = sorted(plano + iguais + outros_bytes, key=lambda p: p.alvo)
        linhas_do_worker = len(self.worker.linhas())
        bloco = self._correr(
            "rajada",
            [("rajada", completo)],
            repetidas={
                "mesmos_bytes": len(iguais),
                "outros_bytes": len(outros_bytes),
                "mensagens_com_outros_bytes": sum(1 for p in outros_bytes if p.chave[0] == "message"),
                "estados_com_outros_bytes": sum(1 for p in outros_bytes if p.chave[0] == "statuses"),
            },
        )
        self._afirmar_sem_perdas(bloco)
        # O segundo nivel **mordeu, e por identidade**: cada repetida com outros
        # bytes aparece no registo do *worker* como `entrada_duplicado` com o
        # seu `msg_id`, nenhuma das com os mesmos bytes la aparece (o GWY
        # apanhou-as), e o excesso esta preso a causa medida
        # (`medicao.duplicados_explicados`). E o `_afirmar_sem_perdas` acima ja
        # exigiu que nenhuma mensagem repetida desse *job* do AGR a mais.
        vistos = [
            linha["msg_id"]
            for linha in self.worker.linhas()[linhas_do_worker:]
            if linha.get("outcome") == "entrada_duplicado" and "msg_id" in linha
        ]
        desfechos = bloco["destino"]["desfechos_do_worker"]
        veredicto = medicao.duplicados_explicados(
            vistos=vistos,
            esperados={medicao.id_opaco(p.chave[1]) for p in outros_bytes},
            proibidos={medicao.id_opaco(p.chave[1]) for p in iguais},
            falhas=medicao.falhas_de_entrada(desfechos),
            eventos_por_job=gerador.EVENTOS_POR_CORPO,
        )
        mensagens_esperadas = {
            medicao.id_opaco(p.chave[1]) for p in outros_bytes if p.chave[0] == "message"
        }
        veredicto["mensagens_que_passaram_pelo_segundo_nivel"] = len(
            mensagens_esperadas & set(vistos)
        )
        bloco["destino"]["duplicados_explicados"] = veredicto
        self._guardar()
        self.assertTrue(veredicto["explicado"], veredicto)
        self.assertEqual(
            veredicto["mensagens_que_passaram_pelo_segundo_nivel"], len(mensagens_esperadas), veredicto
        )

    def test_5_rampa(self) -> None:
        # Os planos tem alvos relativos ao seu proprio inicio: cada `disparar`
        # comeca o relogio dele. Os degraus sao contiguos porque nao se drena
        # entre eles, e a rampa **para no primeiro degrau que falhe** — subir
        # depois disso so acumulava fila para drenar.
        planos = [
            (f"{int(taxa)}/s", self.fabrica.plano(taxa, DURACAO_DO_DEGRAU_S, canais=self.canais))
            for taxa in DEGRAUS
        ]
        bloco = self._correr("rampa", planos, parar_se=_degrau_falhou)
        self._afirmar_sem_perdas(bloco)


if __name__ == "__main__":
    import unittest

    unittest.main()
