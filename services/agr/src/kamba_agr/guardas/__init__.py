"""Os guardrails de entrada e de saida do AGR (KAM-033, `docs/tecnica/02` §8.4).

O bloco propoe `kamba/guards/{rules,classifier,minimize,out_rules,counters}.py`;
fica em `services/agr/src/kamba_agr/guardas/` porque **a arvore deste repositorio
e portuguesa** — a mesma decisao, e a mesma linha em `docs/dividas-documentais.md`,
que o KAM-112 tomou para o `privacidade/`. E o `minimize` **nao** se repete aqui:
e o `privacidade/` do KAM-112, que e a unica via para o LLM e que este pacote usa.

| Modulo | O que tem |
|---|---|
| `politica.py` | os padroes e os limiares, com a versao SemVer e a impressao |
| `regras.py` | os seis veredictos de entrada, por regras; Luhn, *mod 97*, redaccao |
| `classificador.py` | o `kamba-router`, so quando as regras nao decidem |
| `saida.py` | os quatro veredictos de saida |
| `contadores.py` | injeccao por hora e abuso por conversa (criterio 5) |
| `entrada.py` | a mensagem do cliente, segura para persistir |
| `prompt.py` | dados nao fiaveis delimitados no *prompt* |

Os nos que os usam sao o `guard_in`, o `guard_out` e o `safe_reply` do
`verticais/vendedor/nos.py`, que a vertical Servicos importa (ADR-012).
"""

from __future__ import annotations

from .classificador import ClassificadorDeGuarda, interpretar
from .contadores import ACCAO_HANDOFF, ACCAO_PAUSAR
from .contadores import CHAVE as CHAVE_DOS_CONTADORES
from .entrada import mensagem_do_cliente, texto_seguro
from .politica import VERSAO_DA_POLITICA
from .regras import VEREDICTOS, normalizar, redigir_cartao, veredicto_por_regras
from .saida import VEREDICTOS_DE_SAIDA, veredicto_de_saida

__all__ = [
    "ACCAO_HANDOFF",
    "ACCAO_PAUSAR",
    "CHAVE_DOS_CONTADORES",
    "ClassificadorDeGuarda",
    "VEREDICTOS",
    "VEREDICTOS_DE_SAIDA",
    "VERSAO_DA_POLITICA",
    "interpretar",
    "mensagem_do_cliente",
    "normalizar",
    "redigir_cartao",
    "texto_seguro",
    "veredicto_de_saida",
    "veredicto_por_regras",
]
