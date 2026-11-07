"""Os predicados de backup — um por funcao, com o relogio por parametro (KAM-079).

**PORQUE E QUE ISTO SAO FUNCOES E NAO UM AGENDADOR.**

Nao ha agendador neste repositorio. Medido: nao ha `cron`, nem `repeat:`, nem
`delay:` em sitio nenhum, e o agendador nasce com o KAM-071/KAM-078. O bloco do
KAM-079 pede «restauro mensal **automatico**», e as duas metades daquela frase
tem donos diferentes: o *mensal* e um predicado, que se escreve e testa hoje; o
*automatico* e um agendador, que nao existe.

Por isso cada coisa que o ticket precisa de decidir e **uma funcao idempotente
sobre um predicado**, testavel agora e chamavel depois. A regra que as une:

    O RELOGIO ENTRA POR PARAMETRO. SEMPRE.

Um `now()` por dentro de uma funcao (ou de uma consulta) nao se consegue
acelerar num ensaio: para provar que o restauro de ha 31 dias esta em divida,
teria de se esperar 31 dias ou mentir ao relogio do sistema. Com o `agora` por
parametro, o ensaio e uma linha. O mesmo vale para o prazo, que vive **em
coluna** (`periodo_dias` no `cobertura.yaml`) e nao em constante: mudar a
cadencia e mudar um dado.

## O FUNIL

O `pode_enviar` e o **unico** sitio onde se decide se um dado pode sair para um
destino de backup. Nao ha um segundo caminho, nem um «modo rapido» que o salte,
e ha um ensaio estrutural que o prende (`test_o_funil_e_um_so`): a guarda que
vive num dos dois caminhos de saida nao e uma guarda. Qualquer superficie que
escreva, imprima ou envie passa por aqui primeiro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# O gate do criterio 7: nada de dados reais sem `apd_ref`
# ---------------------------------------------------------------------------

#: As classes de dados do repositorio (`kamba_data_class`). `synthetic` e a
#: omissao do compose de producao, e e isso que faz deste gate uma guarda e nao
#: um bloqueio: hoje recusa **tudo** o que seja real, porque nao ha destino
#: nenhum com `apd_ref`.
CLASSES_DE_DADOS = ("synthetic", "real")

#: A forma de uma referencia de autorizacao da APD. Nao se valida o **conteudo**
#: — isso e acto do regulador e nao desta funcao —, valida-se que nao e um
#: espaco em branco nem um marcador como `TODO` ou `n/a` a fazer-se passar por
#: autorizacao. A lista de marcadores existe porque um `apd_ref: "pendente"`
#: num ficheiro de configuracao abriria o gate inteiro.
_FORMA_DA_APD_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{3,63}$")

#: Valores que **parecem** uma referencia e nao sao. Em minusculas; a comparacao
#: e insensivel a caixa.
_NAO_SAO_REFERENCIA = frozenset(
    {
        "todo",
        "tbd",
        "n/a",
        "na",
        "none",
        "null",
        "nenhum",
        "nenhuma",
        "pendente",
        "por_decidir",
        "por-decidir",
        "aguarda",
        "aguarda_parecer",
        "false",
        "0",
        "-",
    }
)


@dataclass(frozen=True)
class Veredicto:
    """A resposta do funil: pode ou nao, e **porque**.

    A razao nao e decoracao. Um booleano obriga quem o le a reconstruir o
    motivo, e quem reconstroi erra: a diferenca entre «este destino nao tem
    `apd_ref`» e «este destino nao existe» decide se se abre um ticket ou se se
    espera por um parecer.
    """

    permitido: bool
    razao: str

    def __bool__(self) -> bool:  # pragma: no cover - acucar, nao logica
        return self.permitido


def normalizar_apd_ref(valor: object) -> str | None:
    """A `apd_ref` quando ela e uma referencia, `None` quando nao e.

    Um `None`, um vazio, um espaco em branco ou um marcador (`TODO`, `pendente`,
    `n/a`) devolvem `None` — e o `pode_enviar` trata os quatro casos como «nao
    ha autorizacao», que e o que eles sao.
    """
    if valor is None or valor is False:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    if texto.lower() in _NAO_SAO_REFERENCIA:
        return None
    if not _FORMA_DA_APD_REF.match(texto):
        return None
    return texto


def pode_enviar(
    *,
    classe_de_dados: str,
    apd_ref: object = None,
    destino: str | None = None,
) -> Veredicto:
    """**O funil.** Este dado pode sair para este destino de backup?

    A regra do criterio 7, em codigo: «enquanto nao houver `apd_ref`, `prod` com
    dados reais nao envia para ele». E a do ADR-008 e do `docs/tecnica/08` §13
    N2: um repositorio de backup fora de Angola e uma transferencia, e uma
    transferencia sem autorizacao nao se faz.

    Tres respostas, e a terceira e a que existe hoje:

    * `synthetic` sai sempre — nao ha titular de dados numa base sintetica, e
      recusa-la impedia o proprio ensaio de restauro de `staging`;
    * `real` com `apd_ref` valida sai;
    * `real` sem `apd_ref` **nao sai**, e a razao nomeia qual das duas coisas
      falta: a autorizacao ou o destino.

    Uma classe de dados que nao seja nenhuma das duas tambem nao sai. Negar por
    omissao e a regra da casa, e um valor desconhecido num campo de
    classificacao e exactamente o caso em que ela vale: `kamba_data_klass=rael`
    nao e `synthetic`.
    """
    onde = f" para `{destino}`" if destino else ""
    if classe_de_dados not in CLASSES_DE_DADOS:
        return Veredicto(
            False,
            f"classe de dados `{classe_de_dados}` desconhecida{onde}: as unicas "
            f"sao {', '.join(CLASSES_DE_DADOS)}, e nega-se por omissao",
        )
    if classe_de_dados == "synthetic":
        return Veredicto(
            True,
            f"dados sinteticos{onde}: nao ha titular, e sem isto o proprio "
            "ensaio de restauro de `staging` era impossivel",
        )
    referencia = normalizar_apd_ref(apd_ref)
    if referencia is None:
        if destino is None:
            return Veredicto(
                False,
                "dados reais sem destino: nao ha `repo1` decidido (D1/KAM-105), "
                "e um destino inventado e uma transferencia para uma jurisdicao "
                "que ninguem escolheu (ADR-008)",
            )
        return Veredicto(
            False,
            f"dados reais{onde} sem `apd_ref`: o `docs/tecnica/08` §13 N2 esta "
            "em aberto e o ADR-008 exige a autorizacao antes do primeiro byte",
        )
    return Veredicto(
        True,
        f"dados reais{onde} cobertos por `apd_ref={referencia}`",
    )


# ---------------------------------------------------------------------------
# O predicado do restauro mensal
# ---------------------------------------------------------------------------


def restauro_devido(
    *,
    agora: datetime,
    ultimo_em: datetime | None,
    periodo_dias: int,
) -> bool:
    """O restauro esta em divida a `agora`?

    `ultimo_em = None` quer dizer «nunca correu», e devolve `True`: a rede de
    seguranca que nunca se ensaiou e a que mais precisa do ensaio. A alternativa
    — tratar «nunca» como «ainda nao e tempo» — deixava um repositorio recem-
    criado sem prova de restauro indefinidamente.

    **Idempotente:** chamar duas vezes com o mesmo `agora` da a mesma resposta,
    porque a funcao nao escreve nada e nao le relogio nenhum. E o que permite ao
    agendador (quando existir) chamar isto a cada hora sem produzir dois
    restauros no mesmo dia.

    Os dois instantes tem de ser conscientes de fuso. Um `datetime` ingenuo
    compara-se com um consciente levantando `TypeError` em Python, e apanhar
    isso aqui com uma mensagem propria vale mais do que o `TypeError` cru vindo
    de dentro de uma subtraccao.
    """
    if periodo_dias <= 0:
        raise ValueError(
            f"periodo_dias={periodo_dias}: um periodo nao positivo faz o "
            "restauro estar sempre em divida, o que e o mesmo que nao ter "
            "cadencia nenhuma"
        )
    _exigir_consciente(agora, "agora")
    if ultimo_em is None:
        return True
    _exigir_consciente(ultimo_em, "ultimo_em")
    if ultimo_em > agora:
        raise ValueError(
            f"ultimo_em ({ultimo_em.isoformat()}) e depois de agora "
            f"({agora.isoformat()}): um restauro no futuro e um relogio errado, "
            "e tratar isso como «em dia» esconderia o relogio errado"
        )
    return agora - ultimo_em >= timedelta(days=periodo_dias)


def proximo_restauro(
    *,
    ultimo_em: datetime | None,
    periodo_dias: int,
    agora: datetime,
) -> datetime:
    """Quando e que o proximo restauro vence. Util para o painel e para a razao."""
    if periodo_dias <= 0:
        raise ValueError(f"periodo_dias={periodo_dias}: nao positivo")
    _exigir_consciente(agora, "agora")
    if ultimo_em is None:
        return agora
    _exigir_consciente(ultimo_em, "ultimo_em")
    return ultimo_em + timedelta(days=periodo_dias)


def _exigir_consciente(instante: datetime, nome: str) -> None:
    if instante.tzinfo is None or instante.tzinfo.utcoffset(instante) is None:
        raise ValueError(
            f"{nome} e um `datetime` ingenuo. Os instantes deste modulo levam "
            "fuso, pela razao do `criado_at timestamptz` do dicionario: um "
            "instante sem fuso compara-se com o de outra maquina e da a "
            "diferenca errada sem avisar"
        )


# ---------------------------------------------------------------------------
# A idade do WAL, e o alerta que ela dispara
# ---------------------------------------------------------------------------


def idade_do_wal_segundos(*, agora: datetime, ultimo_wal_em: datetime | None) -> float:
    """Segundos desde o ultimo segmento de WAL arquivado.

    `None` — nenhum WAL arquivado alguma vez — devolve `inf` e **nao** zero. Um
    zero aqui era o pior valor possivel: «idade zero» le-se como «acabou de
    arquivar», e e exactamente o estado em que o arquivo nunca funcionou. O
    `inf` dispara o alerta, que e o que um arquivo que nunca correu merece.
    """
    _exigir_consciente(agora, "agora")
    if ultimo_wal_em is None:
        return float("inf")
    _exigir_consciente(ultimo_wal_em, "ultimo_wal_em")
    return (agora - ultimo_wal_em).total_seconds()


def wal_em_alerta(
    *,
    agora: datetime,
    ultimo_wal_em: datetime | None,
    limite_segundos: int,
) -> bool:
    """A idade do WAL passou o limite?

    O limite entra por parametro e vem do `cobertura.yaml` (`300`), que e o
    mesmo numero do RPO: o alerta dispara exactamente quando o RPO deixa de
    estar garantido. **Estritamente maior**, e nao «maior ou igual»: o §9.2
    escreve «> 5 min», e a fronteira exacta nao e um incidente.
    """
    if limite_segundos <= 0:
        raise ValueError(
            f"limite_segundos={limite_segundos}: um limite nao positivo poe o "
            "alerta a disparar sempre, e um alerta que dispara sempre ensina a "
            "equipa a ignorar o painel"
        )
    return idade_do_wal_segundos(agora=agora, ultimo_wal_em=ultimo_wal_em) > limite_segundos


# ---------------------------------------------------------------------------
# O debito do restauro, e o orcamento do doc 09 §8.2
# ---------------------------------------------------------------------------

#: Bits num megabit. O debito do §8.2 esta em **Mbps**, que e megabits por
#: segundo — nao megabytes. A constante esta aqui com o nome por extenso porque
#: confundir os dois da um factor de 8, e um factor de 8 num orcamento de RTO e
#: a diferenca entre 30 minutos e 4 horas.
BITS_POR_MEGABIT = 1_000_000


def debito_mbps(*, bytes_lidos: int, segundos: float) -> float:
    """Debito efectivo em megabits por segundo."""
    if bytes_lidos < 0:
        raise ValueError(f"bytes_lidos={bytes_lidos}: negativo")
    if segundos <= 0:
        raise ValueError(
            f"segundos={segundos}: um restauro em zero segundos nao e um debito "
            "infinito, e uma medicao que nao se fez"
        )
    return (bytes_lidos * 8) / BITS_POR_MEGABIT / segundos


def divergencia_do_orcamento_pct(*, medido: float, orcamentado: float) -> float:
    """Quanto o medido se afasta do orcamentado, em percentagem do orcamentado.

    Com sinal: positivo quer dizer **pior** do que o orcamento quando a grandeza
    e tempo, e **melhor** quando e debito. O sinal fica para quem compara, e e
    por isso que a funcao nao o interpreta — o criterio 4 do bloco fala de
    «divergir > 20%» sem dizer em que sentido, e corrigir o orcamento vale nos
    dois.
    """
    if orcamentado <= 0:
        raise ValueError(
            f"orcamentado={orcamentado}: nao ha divergencia percentual contra "
            "zero, e devolver `inf` faria o criterio dos 20% disparar sempre"
        )
    return (medido - orcamentado) / orcamentado * 100.0


def orcamento_a_corrigir(
    *, medido: float, orcamentado: float, divergencia_maxima_pct: float
) -> bool:
    """O criterio 4: «corrige-se o orcamento se divergir > 20%».

    Em **valor absoluto**: um restauro que seja 40% mais **rapido** do que o
    orcamento tambem o invalida, e um orcamento folgado por 40% faz planear um
    RTO que nao se vai cumprir quando a base crescer.
    """
    if divergencia_maxima_pct <= 0:
        raise ValueError(f"divergencia_maxima_pct={divergencia_maxima_pct}: nao positiva")
    return abs(divergencia_do_orcamento_pct(medido=medido, orcamentado=orcamentado)) > (
        divergencia_maxima_pct
    )


# ---------------------------------------------------------------------------
# O *hook* do *erasure ledger*
# ---------------------------------------------------------------------------

#: A consulta da ancora diaria do `audit_log` (`docs/tecnica/08` §6: «ancora
#: diaria do ultimo `row_hash` exportada para o *repo* de backup fora do host»).
#:
#: **Nao ha `now()` aqui, e e a mesma razao do relogio por parametro**: a janela
#: entra por `$1` e `$2`. Uma consulta com `now()` por dentro nao se consegue
#: ensaiar sobre uma fixture com datas fixas, e um ensaio que nao se consegue
#: acelerar nao se corre.
#:
#: O encadeamento e **por tenant** (`docs/tecnica/08` §6), pelo que a ancora
#: tambem e: uma ancora global nao prova cadeia nenhuma.
SQL_ANCORA_DO_AUDIT_LOG = """
SELECT tenant_id,
       max(criado_at) AS ancorado_at,
       (array_agg(row_hash ORDER BY criado_at DESC, id DESC))[1] AS row_hash
  FROM audit_log
 WHERE criado_at >= $1
   AND criado_at <  $2
 GROUP BY tenant_id
""".strip()


@dataclass(frozen=True)
class Sujeito:
    """Uma linha do `erasure_ledger` (`subject_ref`, `erased_at`).

    O contrato e propriedade do **KAM-070**; aqui existe so o *hook* e a
    fixture, como os «Detalhes Tecnicos» do bloco escrevem. O `subject_ref` e um
    BSUID/HMAC e **nunca** um telefone: por isso e `str` opaca e nenhuma funcao
    deste modulo a interpreta.
    """

    subject_ref: str
    erased_at: datetime


def sujeitos_a_reaplicar(
    *, ledger: list[Sujeito], restaurado_de: datetime
) -> list[Sujeito]:
    """Quem foi apagado **depois** do instante de que o backup e copia.

    E o criterio 8: «com um sujeito apagado e um backup anterior ao apagamento,
    o *script* de reaplicacao remove o sujeito». A pergunta que o predicado
    responde e exactamente essa, e a comparacao e a que importa:

        o backup e de T. Quem foi apagado em T' > T **volta** com o restauro,
        porque no instante T ainda estava la. Esses tem de ser reaplicados.

    Quem foi apagado em T' <= T **nao** esta no backup, e reaplicar-lhe o
    apagamento e trabalho inutil — mas nao e inofensivo: um *script* que
    reaplicasse o ledger inteiro a cada restauro faria `DELETE` sobre linhas que
    nao existem e, num ledger grande, isso e o que transforma um restauro de 30
    minutos num de horas. Filtrar e o ponto.

    Devolve-os ordenados pelo instante de apagamento, do mais antigo para o mais
    recente: reaplicar por ordem cronologica e o que mantem o `audit_log` do
    restauro a contar a mesma historia que o original.

    **Idempotente:** nao escreve nada e nao le relogio. Chamar duas vezes da a
    mesma lista, que e o que permite re-executar um restauro interrompido.
    """
    _exigir_consciente(restaurado_de, "restaurado_de")
    for sujeito in ledger:
        _exigir_consciente(sujeito.erased_at, f"erased_at de {sujeito.subject_ref}")
    return sorted(
        (s for s in ledger if s.erased_at > restaurado_de),
        key=lambda s: (s.erased_at, s.subject_ref),
    )


def ler_instante(texto: str) -> datetime:
    """Um instante ISO-8601 com fuso, da forma que as fixtures usam.

    `Z` aceita-se porque e a forma que o `pgbackrest info --output=json` usa, e
    o `fromisoformat` do Python so a aceita desde a 3.11. Normaliza-se para
    UTC — nao por preferencia, mas porque dois instantes com fusos diferentes
    comparam-se bem e **imprimem-se** de forma que engana quem le o relatorio.
    """
    bruto = texto.strip()
    if bruto.endswith(("Z", "z")):
        bruto = bruto[:-1] + "+00:00"
    instante = datetime.fromisoformat(bruto)
    _exigir_consciente(instante, f"instante `{texto}`")
    return instante.astimezone(timezone.utc)
