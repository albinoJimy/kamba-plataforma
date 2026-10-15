"""Amostragem de *logs*: N linhas aleatorias por servico, varridas pelo X-11.

`docs/tecnica/08` §7.3 pede, alem do varrimento no CI, «amostragem semanal em
`prod`»; o ticket fixa-a em 100 linhas aleatorias por servico. Este modulo e a
amostragem e o seu registo. **Nao e o agendamento**: correr isto todas as
semanas contra os *logs* de `prod` precisa de haver `prod` e de haver onde os
ir buscar (Loki, KAM-080) — ver `docs/logs.md` §4.

A entrada e uma pasta com um ficheiro por servico (`gwy.log`, `agr.log`, …),
que e a forma em que um `logcli query` ou um `docker logs` os entrega. A saida
e **uma linha JSON por execucao**, acrescentada ao ficheiro de registo: quando,
quantas linhas havia, quantas se amostraram e quantos achados houve, por
servico e por padrao. Nunca a linha nem o valor encontrado.

Um servico com o *log* vazio **nao da zero**: e erro, pela mesma razao que uma
pasta sem ficheiros — nao se mediu nada, e um servico que deixou de escrever
tem de se ver.

A amostra e aleatoria a serio (`random.SystemRandom`) salvo se for dada uma
semente — para os testes, e para repetir uma execucao que deu achados.
"""

from __future__ import annotations

import datetime
import json
import random
from pathlib import Path

from .x11 import (
    CAMPO_FORA,
    LINHA_FORA,
    Configuracao,
    ConfiguracaoInvalida,
    varrer_linha,
)

LINHAS_POR_SERVICO = 100

#: Achados que sao desvio de formato e nao identificador: contam a parte, porque
#: o alvo de `docs/tecnica/08` §14 e sobre identificadores.
DE_FORMATO = (CAMPO_FORA, LINHA_FORA)


def _linhas(caminho: Path) -> list[str]:
    try:
        conteudo = caminho.read_text(encoding="utf-8", errors="replace")
    except OSError as erro:
        raise ConfiguracaoInvalida(f"nao se le {caminho.name}: {erro.strerror}") from None
    return [linha for linha in conteudo.splitlines() if linha.strip()]


def amostrar(
    pasta: Path,
    configuracao: Configuracao,
    *,
    quantas: int = LINHAS_POR_SERVICO,
    semente: int | None = None,
    agora: datetime.datetime | None = None,
) -> dict:
    """Amostra e varre. Devolve o registo da execucao."""
    if quantas < 1:
        raise ConfiguracaoInvalida("a amostra tem de ter pelo menos uma linha por servico")
    ficheiros = sorted(pasta.glob("*.log")) if pasta.is_dir() else []
    if not ficheiros:
        raise ConfiguracaoInvalida(
            "nenhum `<servico>.log` na pasta dada: uma amostragem sem linhas "
            "nao mediu nada, e nao pode dizer que deu zero"
        )
    sorteio = random.Random(semente) if semente is not None else random.SystemRandom()
    instante = agora or datetime.datetime.now(datetime.timezone.utc)

    servicos: dict[str, dict] = {}
    total_identificadores = 0
    total_formato = 0
    for caminho in ficheiros:
        linhas = _linhas(caminho)
        if not linhas:
            raise ConfiguracaoInvalida(
                f"{caminho.name} nao tem linhas: zero achados em zero linhas nao e um "
                "resultado, e um servico que deixou de escrever tem de se ver"
            )
        amostra = linhas if len(linhas) <= quantas else sorteio.sample(linhas, quantas)
        por_padrao: dict[str, int] = {}
        for linha in amostra:
            for padrao, _campo in varrer_linha(linha, configuracao):
                por_padrao[padrao] = por_padrao.get(padrao, 0) + 1
        de_formato = sum(n for padrao, n in por_padrao.items() if padrao in DE_FORMATO)
        identificadores = sum(n for padrao, n in por_padrao.items() if padrao not in DE_FORMATO)
        total_identificadores += identificadores
        total_formato += de_formato
        servicos[caminho.stem] = {
            "linhas_disponiveis": len(linhas),
            "linhas_amostradas": len(amostra),
            "amostra_completa": len(amostra) >= quantas,
            "identificadores_directos": identificadores,
            "desvios_de_formato": de_formato,
            "por_padrao": dict(sorted(por_padrao.items())),
        }

    return {
        "quando": instante.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "linhas_por_servico": quantas,
        "nif_medido": bool(configuracao.nif_padroes),
        "servicos": servicos,
        "identificadores_directos": total_identificadores,
        "desvios_de_formato": total_formato,
    }


def registar(registo: dict, destino: Path) -> None:
    """Acrescenta a execucao ao ficheiro de registo (uma linha JSON cada)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("a", encoding="utf-8", newline="\n") as ficheiro:
        ficheiro.write(json.dumps(registo, ensure_ascii=False, sort_keys=True) + "\n")
