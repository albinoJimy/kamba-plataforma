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

#: Os sete nomes do §7.3, que sao a letra da fonte.
PROIBIDOS = ("telefone", "msisdn", "bsuid", "nome", "morada", "texto", "email")

#: O resto do vocabulario com que o mesmo dado pessoal entra num payload.
#:
#: **A primeira versao deste lint tinha so os sete, comparados por segmento
#: exacto, e isso quase nao apanhava nada**: `nomes`, `telefones`, `emails` e
#: `moradas` passavam — o plural do proprio nome proibido — e todo o ingles
#: passava (`phone`, `mail`, `address`, `name`, `full_name`), e as abreviaturas
#: tambem (`msg`, `wa_id`). Apanhado pela revisao adversarial deste ticket
#: (achado C1), que demonstrou vinte e tal nomes a passar.
#:
#: O §7.3 nomeia sete porque esta a dar o exemplo da regra, nao a lista
#: fechada; a regra e a do §7.1, «sem PII crua em eventos». Cumprir a letra
#: dos sete e deixar a regra aberta de par em par, pelo que se acrescentam
#: estes — e a lista aprovada de `ci/contratos-allow.yaml` existe para o dia
#: em que um deles for falso positivo.
TAMBEM_PROIBIDOS = (
    # ingles, que e como metade dos campos de software se chamam
    "phone", "telephone", "mobile", "mail", "address", "name", "firstname",
    "lastname", "fullname", "surname", "username", "birthdate", "dob",
    # portugues que o §7.3 nao nomeia
    "endereco", "telemovel", "contacto", "mensagem", "conteudo", "observacao",
    # O plural de «-cao» e «-coes» e a regra do «s» nao o apanha; escreve-se.
    "observacoes", "observacao", "descricao", "descricoes",
    "destinatario", "remetente", "titular", "apelido", "nascimento", "bilhete",
    # o que o WhatsApp e o canal trazem
    "msg", "waid",
)

#: Nomes **inteiros** proibidos, para o que a divisao por segmentos parte em
#: pedacos inocentes: `wa_id` da `wa` + `id`, e `id` nao se pode proibir.
PROIBIDOS_INTEIROS = ("wa_id", "wa_ids", "e_mail", "nr_telefone", "no_telefone")

#: Raizes que casam com o plural: `nomes` e `nome`, `emails` e `email`. Nao se
#: usa `startswith`, que apanhava `nomeacao`; usa-se a raiz e a raiz mais «s»,
#: que e a flexao que estes nomes tem em portugues e em ingles.
RAIZES = PROIBIDOS + TAMBEM_PROIBIDOS

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
    """A raiz proibida que este nome de campo contem, se contiver alguma.

    Compara-se por **segmento** e nao por subcadeia: procurar `nome` dentro de
    `numero_publico` fazia o lint gritar sobre o que nao e PII, e um lint que
    grita por tudo e um lint que alguem desliga. E compara-se o segmento com a
    raiz **e com a raiz mais «s»**, que e o buraco do C1: sem isso, `nomes`
    passava e `nome` nao.
    """
    inteiro = nome.lower()
    if inteiro in PROIBIDOS_INTEIROS:
        return inteiro
    partes = set(segmentos(nome))
    # A juncao dos segmentos apanha `full_name` -> `fullname`, que e a forma
    # como o mesmo campo se escreve nas duas convencoes.
    partes.add("".join(segmentos(nome)))
    for raiz in RAIZES:
        if raiz in partes or raiz + "s" in partes:
            return raiz
    return None


#: As chaves que o percurso le por nome proprio. Todas as outras sao visitadas
#: na mesma, pelo ramo generico do fim — ver o docstring de `_nomes_de_campo`.
_LIDAS_POR_NOME = ("properties", "required", "dependentRequired", "propertyNames", "items")


def _nomes_de_campo(no, prefixo: str = ""):
    """Todos os nomes de campo de um schema, com o caminho ate cada um.

    Le `properties`, `required`, `dependentRequired` e `propertyNames.enum` —
    os quatro sitios onde um nome de campo aparece. Sem o `required`, um campo
    declarado la e **ausente** de `properties` escapava; e um schema mal
    formado, mas escapar em silencio e pior.

    **E depois visita tudo o resto.** A primeira versao visitava so aquelas
    cinco chaves, e calava-se perante `$defs`, `oneOf`, `allOf`, `anyOf`,
    `patternProperties` e `additionalProperties`-como-schema: nenhum contrato
    os usa hoje, e no dia em que um usasse o lint de PII deixava de ver metade
    do documento **sem dizer nada** (achado m4 da revisao adversarial). Em vez
    de se enumerar o que falta — que e a forma de voltar a falhar quando o
    JSON Schema crescer — desce-se por qualquer dicionario ou lista que nao
    tenha sido ja lido acima. Um nome de campo so sai dos sitios onde um nome
    de campo vive; o percurso e que passa a ser total.
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
        for chave, filho in no.items():
            if chave in _LIDAS_POR_NOME or not isinstance(filho, (dict, list)):
                continue
            yield from _nomes_de_campo(filho, f"{prefixo}/{chave}" if prefixo else chave)
    elif isinstance(no, list):
        for filho in no:
            yield from _nomes_de_campo(filho, prefixo)


class AllowlistInvalida(ValueError):
    """`ci/contratos-allow.yaml` esta malformado.

    Excepcao propria, e nao o `YamlSubsetError` por omissao (KAM-134): o
    `cli.py` tem de a distinguir para devolver `SAIDA_ERRO` (2) e nao
    `SAIDA_ACHADOS` (1). Com a de omissao, uma chave inventada na *allowlist*
    saia como *traceback* e o gate 7 ficava indistinguivel de ter encontrado
    PII.
    """


#: As chaves de `ci/contratos-allow.yaml` que este leitor conhece (KAM-134).
_CHAVES = {"version", "aprovados"}
_CHAVES_DE_APROVADO = {"campo", "ticket", "razao", "data"}


def ler_allowlist(raiz: Path) -> set[str]:
    """Os nomes de campo com excepcao declarada. Sem ficheiro, conjunto vazio."""
    caminho = raiz / ALLOWLIST
    if not caminho.is_file():
        return set()
    import kamba_yaml

    documento = kamba_yaml.load_file(caminho)
    # KAM-134. O `ticket`, a `razao` e a `data` nunca sao lidos aqui — o gate
    # so precisa do nome do campo —, mas estao declarados: a lista `aprovados`
    # esta **vazia** hoje, e um conjunto aceite so com `campo` punha este
    # ficheiro vermelho no dia em que alguem aprovasse o primeiro. Verde por
    # acidente e a unica coisa pior do que vermelho.
    kamba_yaml.exigir_chaves(
        documento, _CHAVES, str(caminho), erro=AllowlistInvalida
    )
    aprovados = documento.get("aprovados") or []
    for indice, entrada in enumerate(aprovados, start=1):
        kamba_yaml.exigir_chaves(
            entrada, _CHAVES_DE_APROVADO, f"{caminho}: aprovado {indice}",
            erro=AllowlistInvalida,
        )
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
