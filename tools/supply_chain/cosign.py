"""`cosign verify` para as imagens que o inventario manda verificar (criterio 2).

**Estado, dito sem rodeios: este modulo nunca correu contra o `cosign` real.**
Nao ha binario `cosign` nesta maquina nem no *runner*, e nao ha registo de
contentores nosso. O que aqui esta e a metade que se consegue provar sem
infra-estrutura — a decisao, que e onde um gate destes costuma falhar aberto:

* nenhuma imagem a verificar: diz-se quantas ha e em que estado, e passa;
* uma imagem a verificar e **sem binario**: falha. Nao se salta;
* o binario devolve erro (assinatura ausente, chave errada, imagem adulterada):
  falha, com a saida dele.

**O KAM-030 ligou a primeira imagem assinada, e corrigiu a suposicao que estava
aqui.** A versao anterior desta nota dizia que a forma dos argumentos
(`--certificate-identity`, `--certificate-oidc-issuer`) era «da documentacao do
cosign 2.x lida de memoria: NAO VERIFICADO», e que «quem ligar a primeira imagem
confirma-a nessa altura». Confirmou-se, e estava errada para esta imagem: o
LiteLLM assina **com uma chave** (ECDSA P-256) e a sua assinatura nao tem
certificado, pelo que nao existe identidade OIDC nem emissor
(`docs/evidencia/KAM-030-litellm.md` §1). O comando passou a sair do material
que a entrada declara — `--key` ou os dois `--certificate-*` —, e o leitor do
inventario exige exactamente um dos dois.

O que continua **NAO VERIFICADO** e que o `cosign verify --key ... <digest>`
passa de facto: isso exige o binario, e falha fechada enquanto ele nao estiver la
(`cosign-sem-binario`).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
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


def comando_para(entrada: imagens_mod.Entrada, raiz: Path | None = None) -> list[str]:
    """Verifica **o digest**, nunca a etiqueta: a etiqueta e o que se move.

    A forma do comando sai do **material que a entrada declara**, e nao de uma
    suposicao sobre como o projecto assina:

    * `cosign_chave_publica` -> `--key <ficheiro>`, para uma assinatura por
      chave;
    * `cosign_identidade` + `cosign_emissor` -> os dois `--certificate-*`, para
      o fluxo *keyless* do Fulcio.

    O leitor do inventario garante que e uma e so uma (ver `imagens.py`).

    **A primeira versao disto assumia sempre o fluxo *keyless***, e a sua propria
    nota de modulo dizia que os argumentos eram «lidos de memoria: NAO
    VERIFICADO» e que «quem ligar a primeira imagem confirma-a nessa altura». O
    KAM-030 e essa altura, e a suposicao estava errada para esta imagem: o
    LiteLLM assina com chave e a assinatura nao tem certificado nenhum
    (`docs/evidencia/KAM-030-litellm.md` §1), pelo que
    `--certificate-identity` nao tinha valor possivel.
    """
    comando = ["cosign", "verify"]
    if entrada.cosign_chave_publica:
        caminho = entrada.cosign_chave_publica
        if raiz is not None:
            caminho = str(raiz / entrada.cosign_chave_publica)
        comando += ["--key", caminho]
    else:
        comando += [
            "--certificate-identity", entrada.cosign_identidade,
            "--certificate-oidc-issuer", entrada.cosign_emissor,
        ]
    return comando + [f"{entrada.nome}@{entrada.digest}"]


def verificar(
    inventario: imagens_mod.Inventario,
    executor: Executor | None = None,
    tem_binario: Callable[[], bool] | None = None,
    raiz: Path | None = None,
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
        codigo, saida = executor(comando_para(entrada, raiz))
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
