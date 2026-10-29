"""Minimizacao de PII antes do LLM e do STT (KAM-112).

O bloco propoe o modulo em `kamba/privacy/minimise.py`; fica em
`services/agr/src/kamba_agr/privacidade/` porque **a arvore deste repositorio e
portuguesa** e porque o AGR e o unico processo que minimiza e o unico que
re-identifica (criterio 6: «re-identificacao so no AGR»). A discrepancia de
caminho esta registada numa linha em `docs/dividas-documentais.md`, como as
outras quatro do mesmo dia.

O nome de contrato fica em ingles — `MinimisedText`, `minimise` —, que e a regra
que deixou `Verdict`, `Policy` e `handoff_wait` em ingles: o criterio nomeia-os
assim e renomea-los era divergir do dicionario §3.37.

| Modulo | O que tem |
|---|---|
| `minimizacao.py` | `minimise`, `MinimisedText`, `Mapa`, `reidentificar` — a barreira |
| `detector.py` | as regras por tipo: telefone, BSUID, e-mail, NIF, morada, pessoa |
| `negocio.py` | os intervalos de numeros de negocio, que o detector **nao** ve |
| `catalogo.py` | a porta dos nomes que sao *facts* do *tenant* (criterio 5) |
| `dicionarios.py` | locais de Luanda, nomes proprios, digitos por extenso, `dobrar` |

A ordem de leitura e a de cima para baixo: o `minimizacao.py` diz o que isto
garante, e os outros quatro dizem como.
"""

from __future__ import annotations

from .catalogo import CatalogoDoTenant, CatalogoVazio, PortaDeCatalogo
from .detector import (
    BSUID,
    EMAIL,
    MORADA,
    NIF,
    PESSOA,
    TELEFONE,
    TIPOS,
    TIPOS_DE_DICIONARIO,
    TIPOS_DE_FORMA,
    Achado,
    detectar,
)
from .dicionarios import dobrar
from .minimizacao import (
    ALVO_P95_MS,
    CHAVE_DO_MAPA,
    COMPRIMENTO_DE_REFERENCIA,
    TECTO_MS,
    ContextoDeMinimizacao,
    Mapa,
    MensagemMinimizada,
    MinimisedText,
    TextoNaoMinimizado,
    contexto_de,
    do_estado,
    mensagem,
    minimise,
    nomes_dobrados,
    reidentificar,
    tokens_desconhecidos,
)
from .negocio import Intervalo, ReclamouDemais, reclamar

__all__ = [
    "ALVO_P95_MS",
    "BSUID",
    "CHAVE_DO_MAPA",
    "COMPRIMENTO_DE_REFERENCIA",
    "EMAIL",
    "MORADA",
    "NIF",
    "PESSOA",
    "TECTO_MS",
    "TELEFONE",
    "TIPOS",
    "TIPOS_DE_DICIONARIO",
    "TIPOS_DE_FORMA",
    "Achado",
    "CatalogoDoTenant",
    "CatalogoVazio",
    "ContextoDeMinimizacao",
    "Intervalo",
    "Mapa",
    "MensagemMinimizada",
    "MinimisedText",
    "PortaDeCatalogo",
    "ReclamouDemais",
    "TextoNaoMinimizado",
    "contexto_de",
    "detectar",
    "do_estado",
    "dobrar",
    "mensagem",
    "minimise",
    "nomes_dobrados",
    "reclamar",
    "reidentificar",
    "tokens_desconhecidos",
]
