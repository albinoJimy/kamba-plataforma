"""`cosign verify` para as imagens que o inventario manda verificar (criterio 2).

**Estado, dito sem rodeios: este modulo nunca correu contra o `cosign` real.**
Nao ha no repositorio nenhuma imagem com assinatura publicada (o LiteLLM entra
com o KAM-030), nao ha registo de contentores, e o *runner* nao tem o binario.
O que aqui esta e a metade que se consegue provar sem infra-estrutura — a
decisao, que e onde um gate destes costuma falhar aberto:

* nenhuma imagem a verificar: diz-se quantas ha e em que estado, e passa;
* uma imagem a verificar e **sem binario**: falha. Nao se salta;
* o binario devolve erro (assinatura ausente, identidade errada, imagem
  adulterada): falha, com a saida dele.

A forma exacta dos argumentos (`--certificate-identity`,
`--certificate-oidc-issuer`) e a da documentacao do cosign 2.x **lida de
memoria**: NAO VERIFICADO. Quem ligar a primeira imagem confirma-a nessa altura.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable

from . import imagens as imagens_mod
from .base import Achado

Executor = Callable[[list[str]], tuple[int, str]]


def _executar(comando: list[str]) -> tuple[int, str]:
    try:
        resultado = subprocess.run(comando, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as excepcao:
        return 1, str(excepcao)
    return resultado.returncode, (resultado.stderr or resultado.stdout).strip()


def comando_para(entrada: imagens_mod.Entrada) -> list[str]:
    """Verifica **o digest**, nunca a etiqueta: a etiqueta e o que se move."""
    return [
        "cosign", "verify",
        "--certificate-identity", entrada.cosign_identidade,
        "--certificate-oidc-issuer", entrada.cosign_emissor,
        f"{entrada.nome}@{entrada.digest}",
    ]


def verificar(
    inventario: imagens_mod.Inventario,
    executor: Executor | None = None,
    tem_binario: Callable[[], bool] | None = None,
) -> tuple[list[Achado], dict]:
    a_verificar = [e for e in inventario.entradas if e.cosign == imagens_mod.COSIGN_VERIFICAR]
    resumo = {"a_verificar": len(a_verificar), "verificadas": 0}
    if not a_verificar:
        return [], resumo

    existe = tem_binario() if tem_binario else shutil.which("cosign") is not None
    if not existe:
        return [
            Achado(
                "cosign-sem-binario", imagens_mod.INVENTARIO, 0,
                f"{len(a_verificar)} imagem(ns) com `cosign: verificar` e o binario "
                "`cosign` nao esta instalado. Uma verificacao que nao corre nao "
                "passa: instale-o no runner (por digest) antes de ligar a imagem.",
            )
        ], resumo

    achados: list[Achado] = []
    executor = executor or _executar
    for entrada in a_verificar:
        codigo, saida = executor(comando_para(entrada))
        if codigo != 0:
            achados.append(
                Achado(
                    "cosign-falhou", imagens_mod.INVENTARIO, 0,
                    f"`cosign verify` falhou para {entrada.nome}@{entrada.digest[:19]}…: "
                    f"{saida[:300] or 'sem saida'}",
                )
            )
        else:
            resumo["verificadas"] += 1
    return achados, resumo
