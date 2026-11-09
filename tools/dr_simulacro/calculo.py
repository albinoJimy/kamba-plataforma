"""RPO pelos marcadores, RTO por passo, extrapolacao e decisao (KAM-085).

Funcoes puras: recebem o que o ensaio mediu e devolvem numeros. Nenhuma le
relogio, disco ou base — e por isso que se ensaiam com a fronteira exacta.

## O RPO e uma diferenca entre dois marcadores, e so isso

O bloco escreve-o por extenso: «RPO como diferenca entre o ultimo marcador
restaurado e o ultimo marcador confirmado antes da falha». Os dois instantes
vem do **mesmo relogio** — o da base, pelo `clock_timestamp()` que o escritor
le de volta no `RETURNING` —, pelo que a subtraccao nao mede o desvio entre o
relogio do ensaio e o do servidor.

Um marcador restaurado que **nao** esta na lista dos confirmados e possivel e
nao e defeito: e uma escrita que fez *commit* e cuja confirmacao nao chegou ao
cliente antes de o *host* morrer. Conta-se a parte (`sem_confirmacao`), e nao
reduz o RPO abaixo de zero.

## O RTO tem duas somas, e nunca se confundem

- **medido** — a soma dos passos com `inicio` e `fim` na folha;
- **composto** — o medido mais, por cada rubrica com passos `nao_medido`, o que
  sobra do orcamento dessa rubrica. E o numero que se compara com as 2 h, e
  diz-se sempre como composto, com a lista do que nele e orcamento.

Um RTO composto de 105 min em que 60 min sao orcamento nao prova as 2 h: prova
que os passos medidos cabem no que sobra. E isso que o relatorio escreve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backup_lint import politica

from .folha import FORA_DO_RTO, ORCAMENTO_MIN, PASSOS, PASSOS_OPCIONAIS, Carimbo, FolhaInvalida

#: O alvo do `docs/tecnica/00` §9 e do `infra/backup/cobertura.yaml`.
RTO_ALVO_SEGUNDOS = 7200
RPO_ALVO_SEGUNDOS = 300

#: «Repeticao do cenario A se o resultado ficar entre 100 e 120 min» (Testes
#: Requeridos do bloco). Fechado nas duas pontas, como a frase.
REPETIR_ENTRE_MIN = (100, 120)

#: «Com BD > 40 GB o RTO de 2 h deixa de ser seguro» (doc 09 §8.2).
BD_LIMITE_SEM_REPLICA_GB = 40


@dataclass(frozen=True)
class Duracao:
    passo: str
    rubrica: str
    segundos: float | None
    razao: str = ""
    inicio: datetime | None = None

    @property
    def medido(self) -> bool:
        return self.segundos is not None


def duracoes(carimbos: list[Carimbo], cenario: str) -> list[Duracao]:
    """Uma `Duracao` por passo, pela ordem do criterio 1.

    Recusa a folha em vez de adivinhar: um passo que falta, um `inicio` sem
    `fim`, dois `inicio`, um `fim` antes do `inicio`, ou um passo medido **e**
    declarado `nao_medido`. Cada uma destas e uma folha que nao diz o que
    aconteceu, e um RTO calculado sobre ela seria um numero sem origem.
    """
    do_cenario = [c for c in carimbos if c.cenario == cenario]
    if not do_cenario:
        raise FolhaInvalida(f"nenhum carimbo do cenario {cenario}")
    resultado = []
    presentes = {c.passo for c in do_cenario}
    opcionais = tuple(par for par in PASSOS_OPCIONAIS if par[0] in presentes)
    for passo, rubrica in PASSOS + opcionais:
        deste = [c for c in do_cenario if c.passo == passo]
        eventos = [c.evento for c in deste]
        if not deste:
            raise FolhaInvalida(
                f"cenario {cenario}: o passo `{passo}` nao esta na folha; um passo "
                "que nao se mediu escreve-se `nao_medido`, com a razao"
            )
        if "nao_medido" in eventos:
            if len(deste) != 1:
                raise FolhaInvalida(
                    f"cenario {cenario}: `{passo}` esta medido e declarado nao medido"
                )
            resultado.append(Duracao(passo, rubrica, None, deste[0].nota))
            continue
        if eventos.count("inicio") != 1 or eventos.count("fim") != 1:
            raise FolhaInvalida(
                f"cenario {cenario}: `{passo}` precisa de exactamente um `inicio` e "
                f"um `fim`, e tem {eventos}"
            )
        inicio = next(c.em for c in deste if c.evento == "inicio")
        fim = next(c.em for c in deste if c.evento == "fim")
        segundos = (fim - inicio).total_seconds()
        if segundos < 0:
            raise FolhaInvalida(f"cenario {cenario}: `{passo}` acaba antes de comecar")
        resultado.append(Duracao(passo, rubrica, segundos, inicio=inicio))
    return resultado


def lacunas_segundos(lista: list[Duracao]) -> float:
    """O tempo de relogio entre os passos medidos, que nenhum passo cobre.

    **O relogio nao para entre passos.** A primeira versao somava a duracao de
    cada passo e mais nada: oitenta minutos de hesitacao entre o IaC e o
    restauro — exactamente o que o simulacro humano existe para apanhar —
    davam um RTO de 4,5 min e um codigo de saida 0. Achado da revisao
    adversarial. Mede-se o intervalo do primeiro inicio ao ultimo fim dos
    passos medidos (fora do `fora_do_rto`) e tira-se a uniao dos passos; dois
    passos sobrepostos contam uma vez.
    """
    intervalos = sorted(
        (d.inicio, d.inicio + timedelta(seconds=d.segundos))
        for d in lista
        if d.medido and d.inicio is not None and d.rubrica != FORA_DO_RTO
    )
    if not intervalos:
        return 0.0
    cobertos = 0.0
    corrente_inicio, corrente_fim = intervalos[0]
    for inicio, fim in intervalos[1:]:
        if inicio > corrente_fim:
            cobertos += (corrente_fim - corrente_inicio).total_seconds()
            corrente_inicio, corrente_fim = inicio, fim
        else:
            corrente_fim = max(corrente_fim, fim)
    cobertos += (corrente_fim - corrente_inicio).total_seconds()
    vao = (max(f for _, f in intervalos) - intervalos[0][0]).total_seconds()
    return max(0.0, vao - cobertos)


@dataclass(frozen=True)
class Rubrica:
    nome: str
    orcado_segundos: float
    medido_segundos: float | None
    por_medir: tuple[str, ...]

    @property
    def divergencia_pct(self) -> float | None:
        """Contra o orcamento, so quando **todos** os passos da rubrica se mediram."""
        if self.medido_segundos is None or self.por_medir or self.orcado_segundos <= 0:
            return None
        return politica.divergencia_do_orcamento_pct(
            medido=self.medido_segundos, orcamentado=self.orcado_segundos
        )


@dataclass(frozen=True)
class Rto:
    medido_segundos: float
    composto_segundos: float
    rubricas: tuple[Rubrica, ...]
    orcamento_no_composto: tuple[str, ...] = field(default=())
    lacunas_segundos: float = 0.0

    @property
    def dentro_do_alvo(self) -> bool:
        return self.composto_segundos <= RTO_ALVO_SEGUNDOS

    @property
    def repetir_cenario_a(self) -> bool:
        minimo, maximo = REPETIR_ENTRE_MIN
        return minimo * 60 <= self.composto_segundos <= maximo * 60


def rto(lista: list[Duracao], orcamento: dict[str, float] | None = None) -> Rto:
    """O RTO medido e o composto, e a comparacao por rubrica com o §8.2.

    O composto acrescenta, por rubrica, o orcamento que **sobra** depois do que
    nela se mediu — nunca abaixo de zero. Na rubrica `verificacao_e_dns`, que o
    §8.2 orca junta, uma verificacao medida em 4 min e um DNS por medir somam
    os 4 min medidos e os 11 que sobram; um DNS orcado em 15 inteiros contava
    a verificacao duas vezes.
    """
    orcamento = ORCAMENTO_MIN if orcamento is None else orcamento
    lacunas = lacunas_segundos(lista)
    medido = sum(d.segundos for d in lista if d.medido and d.rubrica != FORA_DO_RTO) + lacunas
    composto = medido
    rubricas = []
    no_composto = []
    for nome in dict.fromkeys(d.rubrica for d in lista):
        desta = [d for d in lista if d.rubrica == nome]
        orcado = orcamento[nome] * 60
        medidos = [d.segundos for d in desta if d.medido]
        por_medir = tuple(d.passo for d in desta if not d.medido)
        soma = sum(medidos) if medidos else None
        if por_medir:
            sobra = max(0.0, orcado - (soma or 0.0))
            composto += sobra
            no_composto.append(f"{nome}: {sobra / 60:.1f} min de orcamento ({', '.join(por_medir)})")
        rubricas.append(Rubrica(nome, orcado, soma, por_medir))
    return Rto(medido, composto, tuple(rubricas), tuple(no_composto), lacunas)


@dataclass(frozen=True)
class Rpo:
    ultimo_confirmado: tuple[int, datetime]
    ultimo_restaurado: tuple[int, datetime]
    segundos: float
    perdidos: int
    sem_confirmacao: int
    buracos: tuple[int, ...]

    @property
    def dentro_do_alvo(self) -> bool:
        return self.segundos <= RPO_ALVO_SEGUNDOS and not self.buracos


def rpo(confirmados: list[tuple[int, datetime]],
        restaurados: list[tuple[int, datetime]]) -> Rpo:
    """O RPO dos marcadores, e os dois defeitos que a diferenca sozinha esconde.

    `buracos` sao numeros em falta **dentro** do intervalo restaurado: um
    restauro que devolve 1..100 sem o 57 nao perdeu dados no fim, perdeu-os a
    meio, e um RPO calculado so pelas pontas dava-o por bom. Um buraco poe o
    RPO fora do alvo seja qual for a diferenca.
    """
    if not confirmados:
        raise ValueError("sem marcadores confirmados: o escritor nao chegou a escrever")
    if not restaurados:
        raise ValueError(
            "o restauro nao tem marcador nenhum: ou nao restaurou o que se escreveu, "
            "ou a tabela nao foi criada antes do backup base"
        )
    confirmados = sorted(confirmados)
    restaurados = sorted(restaurados)
    ultimo_c = confirmados[-1]
    ultimo_r = restaurados[-1]
    numeros = {n for n, _ in restaurados}
    # Os buracos contam-se desde o primeiro **confirmado**, e nao desde o
    # primeiro restaurado: um restauro que devolve 50..100 de 1..100 perdeu o
    # principio da serie, e contar a partir do 50 dava RPO 0 sem buraco nenhum.
    # Achado da revisao adversarial.
    primeiro = min(confirmados[0][0], restaurados[0][0])
    buracos = tuple(n for n in range(primeiro, ultimo_r[0] + 1) if n not in numeros)
    confirmados_numeros = {n for n, _ in confirmados}
    perdidos = sum(1 for n, _ in confirmados if n not in numeros)
    sem_confirmacao = sum(1 for n, _ in restaurados if n not in confirmados_numeros)
    segundos = max(0.0, (ultimo_c[1] - ultimo_r[1]).total_seconds())
    return Rpo(ultimo_c, ultimo_r, segundos, perdidos, sem_confirmacao, buracos)


@dataclass(frozen=True)
class ProvaPitr:
    alvo: datetime
    anteriores_em_falta: tuple[int, ...]
    posteriores_presentes: tuple[int, ...]
    na_fronteira: tuple[int, ...]

    @property
    def provado(self) -> bool:
        return not self.anteriores_em_falta and not self.posteriores_presentes


def prova_pitr(confirmados: list[tuple[int, datetime]],
               restaurados: list[tuple[int, datetime]],
               alvo: datetime, fronteira_segundos: float = 0.5) -> ProvaPitr:
    """Os marcadores anteriores a T todos presentes, e nenhum posterior.

    A recuperacao para um instante compara o instante de *commit*; o marcador
    leva o instante do `INSERT`, que e anterior por milissegundos. Um marcador
    escrito a menos de `fronteira_segundos` antes de T pode ter feito *commit*
    depois dele, e a sua ausencia nao prova nada contra o PITR: conta-se a
    parte, em `na_fronteira`, e nao entra em nenhum dos dois defeitos. Um
    marcador **posterior** a T que esteja presente e sempre defeito.
    """
    presentes = {n for n, _ in restaurados}
    em_falta, fronteira = [], []
    for numero, instante in sorted(confirmados):
        if instante >= alvo:
            continue
        if numero in presentes:
            continue
        if (alvo - instante).total_seconds() < fronteira_segundos:
            fronteira.append(numero)
        else:
            em_falta.append(numero)
    posteriores = tuple(n for n, instante in sorted(restaurados) if instante >= alvo)
    return ProvaPitr(alvo, tuple(em_falta), posteriores, tuple(fronteira))


@dataclass(frozen=True)
class Extrapolacao:
    bytes_medidos: int
    segundos_medidos: float
    debito_mbps: float
    bytes_alvo: int
    segundos_extrapolados: float


def extrapolar(*, bytes_medidos: int, segundos_medidos: float, bytes_alvo: int) -> Extrapolacao:
    """Linear no tamanho, com o debito medido. **E uma extrapolacao**, e diz-se.

    Linear e a hipotese mais simples e e a que o §8.2 faz (20 GB em 30 min, 50
    GB em 70 min sao 0,67 e 0,71 GB/min). Nao e conservadora nem optimista por
    construcao: um restauro com muitos ficheiros pequenos e dominado por
    latencia e nao por debito. Quem a usar para decidir a replica le-a assim.
    """
    debito = politica.debito_mbps(bytes_lidos=bytes_medidos, segundos=segundos_medidos)
    segundos = segundos_medidos * (bytes_alvo / bytes_medidos)
    return Extrapolacao(bytes_medidos, segundos_medidos, debito, bytes_alvo, segundos)


def restauro_em_rede_segundos(*, bytes_no_repositorio: int, mbps: float) -> float:
    """O tempo que a **rede** impoe, sem contar disco nem CPU: bytes x 8 / debito.

    O ensaio local le o repositorio de um volume no mesmo disco, pelo que o
    debito que mede e de disco e de CPU (descompressao e decifra), e nao de
    rede. O restauro real e limitado pelo maior dos dois; este e o outro.
    """
    if mbps <= 0:
        raise ValueError("o debito tem de ser positivo")
    return bytes_no_repositorio * 8 / (mbps * politica.BITS_POR_MEGABIT)


@dataclass(frozen=True)
class DecisaoReplica:
    estado: str  # necessaria | nao_necessaria | por_decidir
    razoes: tuple[str, ...]


def decisao_replica(*, rto_extrapolado_segundos: float,
                    bd_prevista_gb: float | None) -> DecisaoReplica:
    """A regra do criterio 6, as duas metades: RTO extrapolado ou BD prevista.

    Sem previsao de tamanho a resposta e `por_decidir` e nao `nao_necessaria`:
    a regra tem duas condicoes e so uma se mediu, e «a outra nao se sabe» nao
    e «a outra e falsa».
    """
    razoes = []
    if rto_extrapolado_segundos > RTO_ALVO_SEGUNDOS:
        razoes.append(
            f"RTO extrapolado {rto_extrapolado_segundos / 60:.1f} min > "
            f"{RTO_ALVO_SEGUNDOS // 60} min"
        )
    if bd_prevista_gb is not None and bd_prevista_gb > BD_LIMITE_SEM_REPLICA_GB:
        razoes.append(f"BD prevista {bd_prevista_gb} GB > {BD_LIMITE_SEM_REPLICA_GB} GB")
    if razoes:
        return DecisaoReplica("necessaria", tuple(razoes))
    if bd_prevista_gb is None:
        return DecisaoReplica(
            "por_decidir",
            ("o RTO extrapolado cabe nas 2 h, e nao ha previsao do tamanho da BD: "
             "a segunda metade da regra nao se mediu",),
        )
    return DecisaoReplica("nao_necessaria", ("as duas metades da regra mediram-se e cabem",))


def duplicados(efeitos: list[str]) -> dict[str, int]:
    """Os `event_id` que produziram mais do que um efeito, com quantos."""
    contagem: dict[str, int] = {}
    for evento in efeitos:
        contagem[evento] = contagem.get(evento, 0) + 1
    return {evento: n for evento, n in sorted(contagem.items()) if n > 1}
