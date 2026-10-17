"""Operacao da fila de mortos de eventos: listar, reprocessar e descartar (KAM-006).

    python db/dlq.py listar
    python db/dlq.py reprocessar <id> [--operador <nome>]
    python db/dlq.py descartar <id> --aprovador <nome>

**Porque e que isto existe como ferramenta, e nao como consulta a mao.** Uma
entrada de `platform.events_dlq` nao e um registo de erro: e um efeito de
negocio que ninguem aplicou. Se o `tipo` e `payment.*` ou `order.paid`, e
cliente que pagou sem confirmacao — Sev1 (`docs/tecnica/06` §6.4). Fechar uma
dessas com um `UPDATE` escrito na consola nao deixa rasto de quem o fez nem
impede fecha-la duas vezes, e **descartar** um `payment.*` tem de exigir duas
pessoas. As tres regras que se seguem sao por isso da ferramenta, e nao do
costume de quem opera:

1. **Reprocessar e descartar sao idempotentes pelo lado ruidoso.** Uma entrada
   ja fechada nao se fecha outra vez em silencio: recusa-se, com o estado que
   ela tem e quem a resolveu, e com codigo de saida diferente de zero. Um
   sucesso silencioso sobre uma entrada ja resolvida era um operador a pensar
   que tinha feito algo que outro ja tinha feito — e, num `payment.*`, a pensar
   que o dinheiro ja estava tratado.
2. **O descarte de `payment.*` exige dois aprovadores distintos.** A primeira
   chamada **registra** a aprovacao e **recusa** o descarte; a segunda, com um
   nome diferente, descarta. A chave primaria `(dlq_id, aprovador)` de
   `platform.evt_dlq_aprovacoes` torna a mesma pessoa a aprovar duas vezes
   impossivel na base; aqui faz-se o `ON CONFLICT DO NOTHING` que transforma
   isso numa mensagem legivel em vez de uma excepcao de SQL na cara de quem
   opera.
3. **Isto nao re-enfileira nada.** Marcar `reprocessada` fecha a entrada da DLQ;
   quem volta a por o evento na fila e o reconciliador. A mensagem di-lo por
   extenso, para que ninguem feche uma entrada a pensar que o evento voltou a
   ser entregue.

**Nota sobre a transaccao de uma recusa.** Uma recusa de `descartar` **confirma**
o que ja escreveu: a primeira aprovacao fica registada, e e precisamente isso
que faz a segunda chamada poder descartar. Reverter a transaccao de uma recusa
apagava a primeira aprovacao e a regra dos dois aprovadores nunca se cumpria. So
um erro inesperado reverte.

**Papel.** Corre como `kamba_batch`, que e quem a revisao 0005 autoriza: `SELECT`
e `DELETE` em `events_dlq`, `UPDATE` so de `(estado, resolvido_at,
resolvido_por)`, e `SELECT, INSERT, DELETE` em `evt_dlq_aprovacoes`. Tem
`BYPASSRLS` — ve a DLQ de todos os tenants, que e o que uma consola de operacao
precisa e a razao pela qual **nenhum** valor entra em SQL por interpolacao:
tudo parametrizado, sem excepcao.

Codigos de saida, com a mesma distincao de `tools/lint_handoff/cli.py` e de
`db/gate_bd.py`:

    0   fez o que foi pedido
    1   recusou por regra (falta um aprovador, entrada ja fechada, inexistente)
    2   erro de uso (argumento invalido) ou de ambiente (configuracao, base)
"""

from __future__ import annotations

import argparse
import dataclasses
import getpass
import os
import sys

import ligacao

#: Estados de uma entrada da DLQ. Os mesmos da revisao 0005 (§6.4); repetidos
#: aqui porque esta ferramenta nao importa a revisao, e `events_dlq_estado_ck`
#: recusa qualquer outro valor.
ESTADO_ABERTA = "aberta"
ESTADO_REPROCESSADA = "reprocessada"
ESTADO_DESCARTADA = "descartada"

#: O que faz uma entrada **Sev1** no alerta (§6.4, criterio 5 do KAM-006):
#: `payment.*` ou `order.paid`. E so para destacar na listagem.
PREFIXO_DE_PAGAMENTO = "payment."
TIPOS_SEV1 = ("order.paid",)

#: Quantos aprovadores distintos o descarte exige.
#:
#: **Nao e a mesma pergunta que o Sev1**, e confundir as duas e o erro facil:
#: `order.paid` e Sev1 no alerta mas nao e `payment.*`, e o criterio 6 do
#: KAM-006 pede os dois aprovadores so para `payment.*` («descartar uma entrada
#: `payment.*` exige 2 aprovadores distintos»). Quem alargar a regra a
#: `order.paid` muda esta funcao e o teste que a exerce, nao o destaque da
#: listagem.
APROVADORES_DE_PAGAMENTO = 2
APROVADORES_NORMAIS = 1

SAIDA_OK = 0
SAIDA_RECUSA = 1
SAIDA_ERRO = 2

#: Quanto do `erro` cabe numa linha da listagem. O valor inteiro fica na
#: `Entrada`; so a apresentacao corta.
LARGURA_DO_ERRO = 60

#: Variavel de ambiente com o nome de quem opera, para o `reprocessar` de um
#: *job* nomeado que nao passa `--operador`.
VARIAVEL_DO_OPERADOR = "KAMBA_OPERADOR"


class Recusa(Exception):
    """O pedido esta bem formado e **nao** se faz: e uma regra de operacao.

    Sai com 1. A transaccao de uma recusa confirma-se (ver o docstring do
    modulo): a primeira aprovacao de um descarte tem de ficar escrita.
    """


class ErroDeUso(Exception):
    """O pedido nao esta bem formado, ou o ambiente nao da para o fazer. Sai com 2."""


def e_sev1(tipo: str) -> bool:
    """A entrada e Sev1 no alerta? `payment.*` ou `order.paid` (§6.4)."""
    return tipo.startswith(PREFIXO_DE_PAGAMENTO) or tipo in TIPOS_SEV1


def aprovadores_necessarios(tipo: str) -> int:
    """Quantos aprovadores distintos o descarte deste tipo exige."""
    if tipo.startswith(PREFIXO_DE_PAGAMENTO):
        return APROVADORES_DE_PAGAMENTO
    return APROVADORES_NORMAIS


@dataclasses.dataclass(frozen=True)
class Entrada:
    """Uma entrada aberta da DLQ, como a listagem a mostra."""

    id: int
    consumer: str
    tipo: str
    tenant_id: str
    tentativas: int
    erro: str
    idade_segundos: int

    @property
    def sev1(self) -> bool:
        return e_sev1(self.tipo)


def formatar_idade(segundos: int) -> str:
    """Idade legivel. Dias e horas, ou horas e minutos, ou minutos e segundos.

    A idade e o que decide se uma entrada ja passou da hora que o alerta
    tolera (§6.4: as nao-Sev1 alertam se `aberta` > 1 h), e um numero de
    segundos nao se le a essa pergunta.
    """
    segundos = max(int(segundos), 0)
    if segundos >= 86400:
        return f"{segundos // 86400}d{(segundos % 86400) // 3600:02d}h"
    if segundos >= 3600:
        return f"{segundos // 3600}h{(segundos % 3600) // 60:02d}m"
    return f"{segundos // 60}m{segundos % 60:02d}s"


def _numa_linha(texto: str, largura: int = LARGURA_DO_ERRO) -> str:
    """O `erro` numa linha so: um *traceback* de dez linhas desalinhava a tabela."""
    compacto = " ".join(texto.split())
    if len(compacto) <= largura:
        return compacto
    return compacto[: largura - 3] + "..."


# --------------------------------------------------------------------- listar


def listar(cursor) -> list[Entrada]:
    """As entradas **abertas** da DLQ, as Sev1 primeiro e dentro disso as mais velhas.

    A ordem faz-se aqui e nao no `ORDER BY` de proposito: a pergunta «isto e
    Sev1?» e um prefixo de `tipo`, e o unico sitio onde ela se responde e
    `e_sev1` — ter metade do criterio em SQL e metade em Python era ter duas
    definicoes de Sev1 a envelhecer em separado.
    """
    cursor.execute(
        "SELECT id, consumer, tipo, tenant_id::text, tentativas, erro, "
        "       EXTRACT(EPOCH FROM (now() - criado_at))::bigint "
        "  FROM platform.events_dlq "
        " WHERE estado = %s "
        " ORDER BY criado_at, id",
        (ESTADO_ABERTA,),
    )
    entradas = [
        Entrada(
            id=int(linha[0]),
            consumer=linha[1],
            tipo=linha[2],
            tenant_id=linha[3],
            tentativas=int(linha[4]),
            erro=linha[5],
            idade_segundos=int(linha[6]),
        )
        for linha in cursor.fetchall()
    ]
    # Estavel: a ordem de `criado_at` sobrevive dentro de cada grupo.
    entradas.sort(key=lambda entrada: not entrada.sev1)
    return entradas


def formatar_listagem(entradas: list[Entrada]) -> list[str]:
    """As linhas que o `listar` imprime, incluindo o caso de a DLQ estar limpa."""
    if not entradas:
        return [
            "a DLQ nao tem entradas abertas.",
            "    (uma DLQ saudavel e exactamente isto: zero linhas)",
        ]
    linhas = [
        f"{'SEV':<4} {'ID':>8} {'IDADE':>8} {'TENT':>4} "
        f"{'TIPO':<24} {'CONSUMER':<24} {'TENANT':<36} ERRO"
    ]
    for entrada in entradas:
        linhas.append(
            f"{'SEV1' if entrada.sev1 else '':<4} "
            f"{entrada.id:>8} "
            f"{formatar_idade(entrada.idade_segundos):>8} "
            f"{entrada.tentativas:>4} "
            f"{entrada.tipo:<24} "
            f"{entrada.consumer:<24} "
            f"{entrada.tenant_id:<36} "
            f"{_numa_linha(entrada.erro)}"
        )
    sev1 = sum(1 for entrada in entradas if entrada.sev1)
    linhas.append(
        f"{len(entradas)} entrada(s) aberta(s), {sev1} Sev1 "
        f"(payment.* ou order.paid: cliente que pagou sem confirmacao)"
    )
    return linhas


# ------------------------------------------------------- estado de uma entrada


def _entrada_para_resolver(cursor, dlq_id: int) -> tuple[str, str]:
    """`(tipo, estado)` da entrada, com a linha trancada. Recusa se nao der.

    `FOR UPDATE` porque duas consolas a fechar a mesma entrada ao mesmo tempo
    nao podem as duas ler `aberta` e as duas achar que a fecharam. O
    `kamba_batch` tem `DELETE` de tabela, que e o privilegio que o `FOR UPDATE`
    pede.
    """
    cursor.execute(
        "SELECT tipo, estado, resolvido_por FROM platform.events_dlq "
        " WHERE id = %s FOR UPDATE",
        (dlq_id,),
    )
    linha = cursor.fetchone()
    if linha is None:
        raise Recusa(
            f"nao existe entrada {dlq_id} na DLQ. "
            "`python db/dlq.py listar` mostra as abertas."
        )
    tipo, estado, resolvido_por = linha[0], linha[1], linha[2]
    if estado != ESTADO_ABERTA:
        raise Recusa(
            f"a entrada {dlq_id} ({tipo}) ja esta {estado}"
            f"{f', resolvida por {resolvido_por}' if resolvido_por else ''}: "
            "uma entrada fechada nao se fecha outra vez."
        )
    return tipo, estado


def _fechar(cursor, dlq_id: int, estado: str, resolvido_por: str) -> None:
    """Fecha a entrada. As tres unicas colunas que o `kamba_batch` pode mudar.

    O `AND estado = 'aberta'` e redundante depois do `FOR UPDATE` e fica: faz
    desta instrucao uma que nao pode fechar o que ja estava fechado, mesmo que
    alguem a copie para outro contexto.
    """
    cursor.execute(
        "UPDATE platform.events_dlq "
        "   SET estado = %s, resolvido_at = now(), resolvido_por = %s "
        " WHERE id = %s AND estado = %s",
        (estado, resolvido_por, dlq_id, ESTADO_ABERTA),
    )
    if cursor.rowcount != 1:
        # Nao devia acontecer com a linha trancada; se acontecer, nao se finge
        # que aconteceu o que se pediu.
        raise Recusa(
            f"a entrada {dlq_id} nao foi fechada (o estado mudou entretanto); "
            "volte a listar."
        )


# ----------------------------------------------------------------- reprocessar


def reprocessar(cursor, dlq_id: int, operador: str) -> str:
    """Marca a entrada como `reprocessada`. Devolve a mensagem para quem opera.

    Nao re-enfileira o evento: isso e do reconciliador. Aqui fecha-se a entrada
    e diz-se isso por extenso.
    """
    operador = _nome(operador, "operador")
    tipo, _ = _entrada_para_resolver(cursor, dlq_id)
    _fechar(cursor, dlq_id, ESTADO_REPROCESSADA, operador)
    aviso = (
        "    atencao: isto fecha a entrada da DLQ e **nao** volta a por o evento "
        "na fila: quem o re-enfileira e o reconciliador."
    )
    destaque = "    esta entrada era Sev1: confirme o efeito no agregado.\n" if e_sev1(tipo) else ""
    return (
        f"entrada {dlq_id} ({tipo}) marcada como {ESTADO_REPROCESSADA} "
        f"por {operador}.\n{destaque}{aviso}"
    )


# ------------------------------------------------------------------- descartar


def aprovacoes(cursor, dlq_id: int) -> list[str]:
    """Quem ja aprovou o descarte desta entrada, pela ordem em que aprovou."""
    cursor.execute(
        "SELECT aprovador FROM platform.evt_dlq_aprovacoes "
        " WHERE dlq_id = %s ORDER BY criado_at, aprovador",
        (dlq_id,),
    )
    return [linha[0] for linha in cursor.fetchall()]


def descartar(cursor, dlq_id: int, aprovador: str) -> str:
    """Registra a aprovacao e descarta a entrada **se** houver aprovadores bastantes.

    Para `payment.*` sao dois nomes distintos: a primeira chamada registra e
    recusa. A recusa nao e um erro a reverter — a aprovacao que ela acabou de
    escrever e o que torna a segunda chamada possivel.
    """
    aprovador = _nome(aprovador, "aprovador")
    tipo, _ = _entrada_para_resolver(cursor, dlq_id)
    necessarios = aprovadores_necessarios(tipo)

    # `ON CONFLICT DO NOTHING` e nao um `INSERT` seco: a chave primaria
    # `(dlq_id, aprovador)` ja impede a repeticao, e sem isto a segunda
    # aprovacao do mesmo nome chegava a quem opera como um SQLSTATE 23505.
    cursor.execute(
        "INSERT INTO platform.evt_dlq_aprovacoes (dlq_id, aprovador) "
        "VALUES (%s, %s) ON CONFLICT (dlq_id, aprovador) DO NOTHING",
        (dlq_id, aprovador),
    )
    repetida = cursor.rowcount == 0

    ja_aprovaram = aprovacoes(cursor, dlq_id)
    if len(ja_aprovaram) < necessarios:
        nomes = ", ".join(ja_aprovaram)
        if repetida:
            raise Recusa(
                f"{aprovador} ja tinha aprovado o descarte da entrada {dlq_id} "
                f"({tipo}): a mesma pessoa nao conta duas vezes. O descarte de "
                f"{PREFIXO_DE_PAGAMENTO}* exige {necessarios} aprovadores "
                f"distintos e so ha {len(ja_aprovaram)} ({nomes}); falta um nome "
                "diferente."
            )
        raise Recusa(
            f"aprovacao de {aprovador} registada na entrada {dlq_id} ({tipo}), "
            f"e o descarte **nao** foi feito: {PREFIXO_DE_PAGAMENTO}* exige "
            f"{necessarios} aprovadores distintos e ja aprovaram {nomes}. "
            "Falta um segundo aprovador: repita o comando com outro nome."
        )

    # `resolvido_por` leva os nomes todos, e nao so quem chamou por ultimo: a
    # fonte de verdade de quem aprovou e `evt_dlq_aprovacoes` (e a chave
    # primaria e que torna a repeticao impossivel), mas quem le a linha da DLQ
    # tem de ver as duas pessoas sem ter de fazer uma segunda consulta.
    _fechar(cursor, dlq_id, ESTADO_DESCARTADA, ", ".join(ja_aprovaram))
    return (
        f"entrada {dlq_id} ({tipo}) {ESTADO_DESCARTADA} com "
        f"{len(ja_aprovaram)} aprovador(es): {', '.join(ja_aprovaram)}.\n"
        "    o evento nao sera aplicado. A entrada fica para a retencao de 30 "
        "dias apos resolucao."
    )


# ------------------------------------------------------------- linha de comando


def _nome(valor: str | None, papel: str) -> str:
    """Um nome de pessoa que a base aceita: nao vazio depois de `trim`.

    `evt_dlq_aprovacoes_aprovador_ck` recusa a cadeia vazia; recusar aqui da
    uma mensagem de uso em vez de um SQLSTATE 23514.
    """
    limpo = (valor or "").strip()
    if not limpo:
        raise ErroDeUso(f"o nome do {papel} nao pode ser vazio")
    return limpo


def _operador(dado: str | None, ambiente=None) -> str:
    """Quem reprocessa: `--operador`, ou `KAMBA_OPERADOR`, ou o utilizador da sessao.

    O `reprocessar` fecha uma entrada e `resolvido_por` fica com este nome, pelo
    que ele nao pode ficar vazio: sem nenhuma das tres fontes, isto e erro de
    ambiente (2) e nao uma linha com `resolvido_por` em branco.

    Um `--operador` **dado** e vazio nao cai para as outras fontes: quem o
    escreveu queria nomear alguem e nao nomeou, e silenciar isso punha na
    auditoria um nome que nao foi o pedido.
    """
    if dado is not None:
        return _nome(dado, "operador")
    ambiente = os.environ if ambiente is None else ambiente
    do_ambiente = ambiente.get(VARIAVEL_DO_OPERADOR, "")
    if do_ambiente.strip():
        return do_ambiente.strip()
    try:
        da_sessao = getpass.getuser()
    except (OSError, KeyError):
        da_sessao = ""
    if da_sessao.strip():
        return da_sessao.strip()
    raise ErroDeUso(
        "nao foi possivel saber quem opera: passe --operador, ou defina "
        f"{VARIAVEL_DO_OPERADOR}. `resolvido_por` nao pode ficar em branco."
    )


def _analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(
        prog="dlq", description=__doc__.split("\n")[0]
    )
    comandos = analisador.add_subparsers(dest="comando", required=True)

    comandos.add_parser("listar", help="as entradas abertas, as Sev1 em destaque")

    reprocessa = comandos.add_parser(
        "reprocessar",
        help="fecha a entrada como reprocessada (nao re-enfileira o evento)",
    )
    reprocessa.add_argument("id", type=int, help="o `id` da entrada em events_dlq")
    reprocessa.add_argument(
        "--operador",
        default=None,
        help=f"quem opera (omissao: {VARIAVEL_DO_OPERADOR} ou o utilizador da sessao)",
    )

    descarta = comandos.add_parser(
        "descartar",
        help="descarta a entrada; payment.* exige dois aprovadores distintos",
    )
    descarta.add_argument("id", type=int, help="o `id` da entrada em events_dlq")
    descarta.add_argument(
        "--aprovador", required=True, help="quem aprova o descarte, pelo nome"
    )
    return analisador


def main(argv: list[str] | None = None) -> int:
    import pg8000.dbapi

    argumentos = _analisador().parse_args(argv)
    try:
        operador = (
            _operador(getattr(argumentos, "operador", None))
            if argumentos.comando == "reprocessar"
            else ""
        )
        conexao = ligacao.ligar("batch")
    except ligacao.ConfiguracaoEmFalta as erro:
        print(f"dlq: {erro}", file=sys.stderr)
        return SAIDA_ERRO
    except ErroDeUso as erro:
        print(f"dlq: {erro}", file=sys.stderr)
        return SAIDA_ERRO

    try:
        cursor = conexao.cursor()
        try:
            if argumentos.comando == "listar":
                for linha in formatar_listagem(listar(cursor)):
                    print(linha)
            elif argumentos.comando == "reprocessar":
                print(reprocessar(cursor, argumentos.id, operador))
            else:
                print(descartar(cursor, argumentos.id, argumentos.aprovador))
        except Recusa as recusa:
            # Confirma-se, e e deliberado: a aprovacao que a recusa acabou de
            # registar tem de sobreviver, ou a regra dos dois aprovadores nunca
            # se cumpre (ver o docstring do modulo).
            conexao.commit()
            print(f"dlq: {recusa}", file=sys.stderr)
            return SAIDA_RECUSA
        except ErroDeUso as erro:
            conexao.rollback()
            print(f"dlq: {erro}", file=sys.stderr)
            return SAIDA_ERRO
        except pg8000.dbapi.DatabaseError as erro:
            conexao.rollback()
            print(f"dlq: a base recusou a operacao: {erro}", file=sys.stderr)
            return SAIDA_ERRO
        conexao.commit()
        return SAIDA_OK
    finally:
        conexao.close()


if __name__ == "__main__":
    sys.exit(main())
