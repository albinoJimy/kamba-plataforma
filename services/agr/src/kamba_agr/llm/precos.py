"""O custo de uma chamada, em USD, a partir de `llm/precos.yaml` (KAM-030).

O criterio 5 fixa o numero que isto tem de dar: o exemplo do
`docs/tecnica/02` §13.3 — 3.000 tokens de entrada e 300 de saida a 0,10 / 0,50
USD por 1M — da **0,00045 USD**.

## `Decimal` e nao `float`, e isso nao e preferencia

A convencao do repositorio proibe virgula flutuante em dinheiro, e aqui morde a
serio: `3000 * 0.10 / 1e6 + 300 * 0.50 / 1e6` em `float` da
`0.00045000000000000004`, e a coluna e `numeric(12, 6)`. Somar um milhao destas
linhas em `float` desvia o custo por tenant do que o fornecedor cobrou. Com
`Decimal` e exacto, e o `quantize` para seis casas e o que a coluna guarda.

## Um modelo sem preco da custo **nulo**, nunca zero

Hoje **todos** os modelos sao `por_decidir` (o KAM-040 escolhe), pelo que nenhuma
chamada real tem preco. Escrever `0` dizia que a chamada foi gratuita e punha o
somatorio de custo a mentir por omissao; o nulo diz «nao se sabe», que e verdade,
e a metrica `agr_llm_sem_preco_total` conta-o para que a ausencia seja visivel
num painel em vez de silenciosa.

## O que esta funcao **nao** faz

**Nao aplica os +30% do tokenizador da Anthropic.** O `E4` §3.1 diz que os
modelos >= 4.7 produzem ~30% mais tokens para o mesmo texto, e o §13.3 usa isso
para avisar que a estimativa por turno e optimista. Mas o custo calcula-se dos
tokens que o fornecedor **contou**, e esses ja incluem os 30%: aplicar o factor
aqui contava-os duas vezes.

**Nao normaliza a contagem de cache.** Esta funcao recebe `tokens_in` como os
tokens cobrados a tarifa de entrada e `tokens_cache` como os cobrados a tarifa de
cache, e soma-os separadamente. Quem normaliza e o cliente, ao ler a resposta, e
**e por uma razao que esta NAO VERIFICADA**: a Anthropic reporta
`cache_read_input_tokens` **ao lado** de `input_tokens` e o OpenAI reporta
`cached_tokens` **dentro** de `prompt_tokens` — se os dois forem assim, somar o
campo cru dava contas diferentes por fornecedor. Nao se mediu contra nenhum
fornecedor real (nao ha chave nem modelo escolhido), e por isso a subtraccao do
cliente e defensiva: nunca produz um valor negativo. Fica declarado em
`docs/dividas-documentais.md`, com o KAM-040 como credor — e quem escolher o
modelo mede isto na mesma passagem.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Final

#: Os precos vem por 1M de tokens (`E4` §3).
POR: Final = Decimal(1_000_000)

#: As casas decimais de `dat.llm_call_log.custo_usd` (`numeric(12, 6)`).
CASAS: Final = Decimal("0.000001")

#: O ficheiro, dentro de `KAMBA_LLM_DIR`.
FICHEIRO: Final = "precos.yaml"


class PrecoInvalido(ValueError):
    """O `llm/precos.yaml` nao se pode usar. A mensagem diz porque."""


class PrecoExpirado(PrecoInvalido):
    """Uma linha com `valido_ate` no passado.

    Levanta em vez de calcular: o `gemini-3.8-flash` tem preco promocional ate
    2026-12-31 e **duplica** a 2027-01-01. Calcular com o preco antigo depois
    dessa data registava metade do custo real em todas as linhas, e o erro so
    aparecia na factura.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class Preco:
    fornecedor: str
    modelo: str
    entrada: Decimal
    cache: Decimal
    saida: Decimal
    estado: str
    fonte: str
    valido_ate: dt.date | None = None


def carregar(pasta: Path) -> dict[tuple[str, str], Preco]:
    """Le a tabela. A chave e `(fornecedor, modelo)`."""
    from kamba_yaml import load_file

    dados = load_file(pasta / FICHEIRO)
    if dados.get("version") != 1:
        raise PrecoInvalido(f"{FICHEIRO}: 'version' tem de ser 1")
    tabela: dict[tuple[str, str], Preco] = {}
    for linha in dados.get("precos") or ():
        chave = (str(linha.get("fornecedor", "")), str(linha.get("modelo", "")))
        if chave in tabela:
            raise PrecoInvalido(f"{FICHEIRO}: duas linhas para {chave}")
        validade = linha.get("valido_ate")
        try:
            tabela[chave] = Preco(
                fornecedor=chave[0],
                modelo=chave[1],
                entrada=Decimal(str(linha["entrada"])),
                cache=Decimal(str(linha["cache"])),
                saida=Decimal(str(linha["saida"])),
                estado=str(linha["estado"]),
                fonte=str(linha["fonte"]),
                valido_ate=dt.date.fromisoformat(str(validade)) if validade else None,
            )
        except (KeyError, ArithmeticError, ValueError) as excepcao:
            raise PrecoInvalido(f"{FICHEIRO}: linha {chave} invalida: {excepcao}") from excepcao
    if not tabela:
        raise PrecoInvalido(f"{FICHEIRO}: tabela vazia")
    return tabela


def custo(
    preco: Preco | None,
    tokens_in: int,
    tokens_out: int,
    tokens_cache: int = 0,
    hoje: dt.date | None = None,
) -> Decimal | None:
    """O custo em USD, com seis casas. `None` quando nao ha preco.

    `tokens_in` sao os cobrados a tarifa de entrada e `tokens_cache` os cobrados
    a tarifa de cache; a soma dos tres multiplica-se pelas tarifas e divide-se
    por 1M. Ver a nota do modulo sobre quem normaliza a contagem de cache.

        >>> from decimal import Decimal
        >>> p = Preco("anthropic", "x", Decimal("0.10"), Decimal("0.01"),
        ...           Decimal("0.50"), "CONFIRMADO", "E4 §3.1")
        >>> custo(p, 3000, 300)
        Decimal('0.000450')
    """
    if preco is None:
        return None
    if preco.valido_ate is not None:
        dia = hoje or dt.datetime.now(dt.UTC).date()
        if dia > preco.valido_ate:
            raise PrecoExpirado(
                f"o preco de {preco.fornecedor}/{preco.modelo} era valido ate "
                f"{preco.valido_ate.isoformat()} e hoje e {dia.isoformat()}: "
                "calcular com ele registava menos do que se paga. Releia a tarifa "
                f"({preco.fonte}) e actualize `{FICHEIRO}`"
            )
    for nome, valor in (
        ("tokens_in", tokens_in),
        ("tokens_out", tokens_out),
        ("tokens_cache", tokens_cache),
    ):
        if valor < 0:
            raise PrecoInvalido(f"{nome} nao pode ser negativo (lido {valor})")
    total = (
        Decimal(tokens_in) * preco.entrada
        + Decimal(tokens_cache) * preco.cache
        + Decimal(tokens_out) * preco.saida
    ) / POR
    return total.quantize(CASAS)
