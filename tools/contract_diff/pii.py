"""O *lint* de PII dos contratos: nomes de campo e fixtures (§7.3).

A frase do `docs/tecnica/06` §7.3 e esta:

    «os *schemas* de evento sao fechados; um teste rejeita nomes de campo
    `telefone|msisdn|bsuid|nome|morada|texto|email` fora de uma lista
    aprovada, e corre os *fixtures* contra padroes `\\+?244\\d{9}`.»

Duas coisas a dizer sobre ela, porque as duas custaram decisao.

## A «lista aprovada» nao existia

O §7.3 fala dela e nenhum documento a enumera. Nasce aqui, em
`ci/contratos-allow.yaml`, e nasce **vazia**: hoje nenhum contrato precisa de
uma excepcao, e uma lista com entradas «por precaucao» e uma lista que ninguem
revê. Cada entrada futura leva ticket, razao e data — a mesma forma das outras
listas de excepcao do repositorio.

## Os tres padroes de telefone, e qual se usa

O §7.3 escreve `\\+?244\\d{9}`. O `platform.evt_emitir` e o `pii.ts` implementam
`\\+?244 ?9[0-9]{8}` **e** `"\\+[0-9]{9,15}"`. Sao tres padroes diferentes, e a
diferenca nao e cosmetica: o do §7.3 aceita qualquer nono digito, o do codigo
exige movel, e nenhum aceita o espaco do outro.

Aqui usam-se **os do codigo**, e a razao e a paridade: o `evt_emitir` recusa o
evento em producao, dentro da transaccao de negocio, e um exemplo que este
*lint* aprovasse e a base recusasse seria um contrato que nao se pode emitir. O
padrao do §7.3 fica registado como divergencia por fechar (`docs/contratos.md`).
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

from contract_diff import catalogo

#: Os sete nomes do §7.3. A comparacao e por **segmento** do nome do campo,
#: sem distincao de caixa: `nome_do_cliente` e `telefone` batem; `numero_publico`
#: nao. Procurar por subcadeia apanhava `nome` dentro de `numero_publico` e
#: fazia o *lint* gritar sobre o que nao e PII.
PROIBIDOS = ("telefone", "msisdn", "bsuid", "nome", "morada", "texto", "email")

#: Os padroes de telefone, iguais aos de `packages/core-ts/src/eventos/pii.ts`
#: e aos do `platform.evt_emitir`, e pela ordem em que o SQL os avalia.
TELEFONE_AO = re.compile(r"\+?244 ?9[0-9]{8}")
E164_ENTRE_ASPAS = re.compile(r'"\+[0-9]{9,15}"')
PADROES_DE_TELEFONE = (TELEFONE_AO, E164_ENTRE_ASPAS)

#: Onde vive a lista aprovada.
ALLOWLIST = Path("ci") / "contratos-allow.yaml"

_SEGMENTOS = re.compile(r"[^a-z0-9]+")


@dataclasses.dataclass(frozen=True)
class Achado:
    ficheiro: str
    onde: str
    porque: str

    def __str__(self) -> str:
        return f"{self.ficheiro}:{self.onde}: {self.porque}"


def segmentos(nome: str) -> list[str]:
    """`contact_id` -> ['contact','id']. Minusculas, sem pontuacao."""
    return [s for s in _SEGMENTOS.split(nome.lower()) if s]


def proibido_em(nome: str) -> str | None:
    """O nome proibido que este nome de campo contem, se contiver algum."""
    partes = set(segmentos(nome))
    for mau in PROIBIDOS:
        if mau in partes:
            return mau
    return None


def _nomes_de_campo(no, prefixo: str = ""):
    """Todos os nomes de campo de um schema, com o caminho ate cada um.

    Le `properties`, `required`, `dependentRequired` e `propertyNames.enum` —
    os quatro sitios onde um nome de campo aparece. Sem o `required`, um campo
    declarado la e **ausente** de `properties` escapava; e um schema mal
    formado, mas escapar em silencio e pior.
    """
    if isinstance(no, dict):
        for nome, filho in (no.get("properties") or {}).items():
            caminho = f"{prefixo}.{nome}" if prefixo else nome
            yield caminho, nome
            yield from _nomes_de_campo(filho, caminho)
        for nome in no.get("required") or []:
            if isinstance(nome, str):
                yield (f"{prefixo}.{nome}" if prefixo else nome), nome
        for nome in (no.get("dependentRequired") or {}):
            yield (f"{prefixo}.{nome}" if prefixo else nome), nome
        nomes = (no.get("propertyNames") or {}).get("enum") or []
        for nome in nomes:
            if isinstance(nome, str):
                yield (f"{prefixo}.{nome}" if prefixo else nome), nome
        if "items" in no:
            yield from _nomes_de_campo(no["items"], f"{prefixo}[]")
    elif isinstance(no, list):
        for filho in no:
            yield from _nomes_de_campo(filho, prefixo)


def ler_allowlist(raiz: Path) -> set[str]:
    """Os nomes de campo com excepcao declarada. Sem ficheiro, conjunto vazio."""
    caminho = raiz / ALLOWLIST
    if not caminho.is_file():
        return set()
    import kamba_yaml

    documento = kamba_yaml.load_file(caminho)
    aprovados = documento.get("aprovados") or []
    return {str(entrada["campo"]) for entrada in aprovados}


def nomes(raiz: Path) -> list[Achado]:
    """Nenhum contrato tem um nome de campo de PII fora da lista aprovada."""
    aprovados = ler_allowlist(raiz)
    achados: list[Achado] = []
    for contrato in catalogo.todos(raiz):
        vistos = set()
        for caminho, nome in _nomes_de_campo(contrato.documento):
            if caminho in vistos:
                continue
            vistos.add(caminho)
            mau = proibido_em(nome)
            if mau is None or caminho in aprovados:
                continue
            achados.append(
                Achado(
                    contrato.relativo, caminho,
                    f"o nome contem «{mau}», que o §7.3 proibe em evento. Um evento "
                    "leva referencias (contact_id), nunca o dado pessoal",
                )
            )
    return achados


def fixtures(raiz: Path) -> list[Achado]:
    """Nenhum exemplo contem um telefone.

    Corre sobre o **texto** do ficheiro e nao sobre os valores, porque e assim
    que o `evt_emitir` o faz (`p_payload::text ~ padrao`): um telefone partido
    por duas chaves continua a aparecer no texto, e um que so exista numa chave
    tambem.
    """
    achados: list[Achado] = []
    for contrato in catalogo.todos(raiz):
        for caminho in (contrato.caminho, catalogo.exemplo_de(contrato)):
            if not caminho.is_file():
                continue
            texto = caminho.read_text(encoding="utf-8")
            casados = [p.pattern for p in PADROES_DE_TELEFONE if p.search(texto)]
            if casados:
                # **Um** achado por ficheiro, com todos os padroes que casaram:
                # um numero angolano casa os dois, e dois achados sobre o mesmo
                # telefone sao ruido que faz alguem desligar o lint.
                achados.append(
                    Achado(
                        caminho.relative_to(raiz).as_posix(), "(texto)",
                        f"casa {len(casados)} padrao(oes) de telefone: {casados}. "
                        "Os mesmos padroes fazem o evt_emitir recusar o evento, "
                        "dentro da transaccao de negocio",
                    )
                )
    return achados
