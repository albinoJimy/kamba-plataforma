"""O classificador de diferencas entre duas versoes do mesmo contrato.

A regra e o `docs/tecnica/06` §6.6, e sao duas frases:

    «Campo novo **opcional** ⇒ mesma versao»
    «qualquer mudanca de significado, remocao ou tipo ⇒ versao + 1»

O que este modulo faz e decidir em qual das duas cai cada diferenca, e o que o
gate faz com isso e simples: uma diferenca **quebrante** no mesmo `v<N>` falha.
Quem quer quebrar escreve `v<N+1>` e deixa o `v<N>` como estava.

## Falha fechada: o que nao se reconhece e quebrante

Uma diferenca que este classificador nao saiba ler e classificada **quebrante**,
e isso e deliberado. A alternativa — «nao sei, deixa passar» — faz o gate
aprovar exactamente as mudancas que ninguem previu, que sao as que precisam de
olhos. Um falso quebrante custa uma versao a mais; um falso aditivo custa
consumidores partidos em producao.

## Porque e que acrescentar um valor a um `enum` e quebrante

Parece aditivo e nao e. Um consumidor que trate os valores de forma exaustiva
— um `switch` sem ramo por omissao, uma tabela de conversao — deixa de saber o
que fazer com o valor novo no dia em que ele aparece. O §6.6 chama-lhe
«mudanca de significado». Alargar o dominio e uma promessa nova ao consumidor,
e promessas novas levam versao nova.
"""

from __future__ import annotations

import dataclasses
from typing import Any

#: As duas classes do §6.6.
ADITIVO = "aditivo_opcional"
QUEBRANTE = "quebrante"


@dataclasses.dataclass(frozen=True)
class Diferenca:
    """Uma diferenca, onde esta e o que e."""

    classe: str
    caminho: str
    porque: str

    @property
    def quebra(self) -> bool:
        return self.classe == QUEBRANTE

    def __str__(self) -> str:
        return f"{self.classe}  {self.caminho}: {self.porque}"


def _propriedades(no: Any) -> dict:
    corpo = no.get("properties") if isinstance(no, dict) else None
    return corpo if isinstance(corpo, dict) else {}


def _obrigatorios(no: Any) -> set[str]:
    corpo = no.get("required") if isinstance(no, dict) else None
    return set(corpo) if isinstance(corpo, list) else set()


def _tipo(no: Any) -> Any:
    """O `type` normalizado: uma lista ordenada, para `["string","null"]` comparar."""
    if not isinstance(no, dict):
        return None
    bruto = no.get("type")
    if isinstance(bruto, list):
        return sorted(str(t) for t in bruto)
    return [str(bruto)] if bruto is not None else None


#: As palavras-chave que este classificador sabe comparar. Uma que apareca e
#: nao esteja aqui da `quebrante`, pela regra da falha fechada.
#:
#: As quatro de prosa — `description`, `title`, `$schema`, `$id` — estao aqui
#: para **nao** serem achado: mudar uma descricao nao muda o que o consumidor
#: recebe, e nenhuma comparacao abaixo lhes toca.
CONHECIDAS = frozenset(
    {
        "type", "properties", "required", "additionalProperties", "enum", "const",
        "items", "minimum", "maximum", "minItems", "maxItems", "uniqueItems",
        "format", "description", "title", "$schema", "$id", "minLength", "maxLength",
        "pattern",
    }
)


def comparar(base: dict, actual: dict, caminho: str = "") -> list[Diferenca]:
    """Todas as diferencas entre dois nos de schema, classificadas."""
    achados: list[Diferenca] = []
    onde = caminho or "(raiz)"

    desconhecidas = (set(base) | set(actual)) - CONHECIDAS
    for chave in sorted(desconhecidas):
        if base.get(chave) != actual.get(chave):
            achados.append(
                Diferenca(
                    QUEBRANTE, f"{onde}.{chave}",
                    "palavra-chave que o classificador nao sabe ler mudou; o que nao "
                    "se reconhece conta como quebrante (falha fechada)",
                )
            )

    if _tipo(base) != _tipo(actual):
        achados.append(
            Diferenca(QUEBRANTE, onde, f"o tipo mudou de {_tipo(base)} para {_tipo(actual)}")
        )

    for chave in ("const", "format", "pattern", "minLength", "maxLength",
                  "minimum", "maximum", "minItems", "maxItems", "uniqueItems"):
        if base.get(chave) != actual.get(chave):
            achados.append(
                Diferenca(
                    QUEBRANTE, f"{onde}.{chave}",
                    f"{chave} mudou de {base.get(chave)!r} para {actual.get(chave)!r}",
                )
            )

    antes, depois = base.get("enum"), actual.get("enum")
    if antes != depois:
        a, d = set(antes or []), set(depois or [])
        if d - a:
            achados.append(
                Diferenca(
                    QUEBRANTE, f"{onde}.enum",
                    f"o dominio ganhou {sorted(d - a)}: um consumidor que trate os valores "
                    "de forma exaustiva nao sabe o que fazer com o valor novo",
                )
            )
        if a - d:
            achados.append(
                Diferenca(QUEBRANTE, f"{onde}.enum", f"o dominio perdeu {sorted(a - d)}")
            )

    if base.get("additionalProperties") != actual.get("additionalProperties"):
        achados.append(
            Diferenca(
                QUEBRANTE, f"{onde}.additionalProperties",
                f"mudou de {base.get('additionalProperties')!r} para "
                f"{actual.get('additionalProperties')!r}: fechar ou abrir um objecto muda "
                "o que o consumidor pode receber",
            )
        )

    props_base, props_actual = _propriedades(base), _propriedades(actual)
    obrig_base, obrig_actual = _obrigatorios(base), _obrigatorios(actual)

    for nome in sorted(set(props_base) - set(props_actual)):
        achados.append(
            Diferenca(QUEBRANTE, f"{onde}.{nome}", "o campo desapareceu")
        )
    for nome in sorted(set(props_actual) - set(props_base)):
        if nome in obrig_actual:
            achados.append(
                Diferenca(
                    QUEBRANTE, f"{onde}.{nome}",
                    "campo novo e **obrigatorio**: o produtor antigo nao o envia",
                )
            )
        else:
            achados.append(
                Diferenca(ADITIVO, f"{onde}.{nome}", "campo novo e opcional")
            )
    for nome in sorted(set(props_base) & set(props_actual)):
        achados.extend(comparar(props_base[nome], props_actual[nome], f"{onde}.{nome}"))

    for nome in sorted((obrig_actual - obrig_base) & set(props_base)):
        achados.append(
            Diferenca(
                QUEBRANTE, f"{onde}.{nome}",
                "um campo que era opcional passou a obrigatorio",
            )
        )
    for nome in sorted(obrig_base - obrig_actual):
        achados.append(
            Diferenca(
                QUEBRANTE, f"{onde}.{nome}",
                "um campo que era obrigatorio deixou de o ser: quem o lia sem o "
                "verificar passa a ler nada",
            )
        )

    if "items" in base or "items" in actual:
        achados.extend(
            comparar(base.get("items") or {}, actual.get("items") or {}, f"{onde}[]")
        )

    return achados


def quebra(diferencas: list[Diferenca]) -> list[Diferenca]:
    """So as que quebram. E o que o gate conta."""
    return [d for d in diferencas if d.quebra]
