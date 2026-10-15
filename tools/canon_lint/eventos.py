"""Superficie 2 — schemas de evento (`contratos/eventos/**/*.schema.json`).

Verifica-se, em cada schema:

* **nivel 1 em todo o documento** — todas as chaves e todos os textos, a
  qualquer profundidade e debaixo de qualquer palavra-chave (`properties`,
  `required`, `patternProperties`, `propertyNames`, `dependentRequired`, `enum`,
  `$defs`…). Nao se enumeram as palavras-chave do JSON Schema: procura-se a
  variante em tudo, com fronteira de palavra;
* os campos de topo — sao os do envelope (dicionario §3.5) ou extensoes;
* os campos do `payload` — nomes do dicionario ou extensoes do tipo `campo`,
  seguindo os `$ref` **internos** (`#/$defs/corpo`) e contando tambem os nomes
  que so aparecem em `required`, `dependentRequired` e `propertyNames`;
* o nome do ficheiro: `v<N>.schema.json`, salvo os declarados em
  `eventos_partilhados` na politica;
* o `tipo` e fixo (`const`/`enum`) e e um tipo de evento do dicionario, e a
  `versao` e fixa e igual a `N`.

**A regra da versao e *proposta*.** O dicionario §3.5 diz que versoes
desconhecidas «falham de forma visivel (nunca ignoradas em silencio)» (D-12,
ADR-009). A forma mecanica dessa regra num schema e a `versao` ser `const`: um
consumidor que valide um evento `versao: 2` contra o schema `v1` **falha**, em
vez de o aceitar. Quem decidir que a regra deve viver noutro sitio (no
publicador, `docs/tecnica/06` §6.6) retira-a daqui.

Limites ditos: nao se seguem `$ref` **externos** (o ficheiro referido, se
estiver na superficie, e verificado por si); `patternProperties` no `payload` e
achado `ilegivel`, porque um padrao nao e um nome que se possa comparar com o
dicionario.
"""

from __future__ import annotations

import json
import re

from .achados import ILEGIVEL, REGRA, Achado, aceita, fora, variante, variantes_em_texto
from .dicionario import POLITICA, Saber

_VERSAO_NO_NOME = re.compile(r"(?:^|/)v([1-9]\d*)\.schema\.json$")
_COMBINADORES = ("allOf", "anyOf", "oneOf")
_SUBSCHEMAS = ("items", "additionalProperties", "unevaluatedProperties", "not", "if", "then", "else", "contains")


class _Duplicada(ValueError):
    pass


def _sem_duplicadas(pares):
    vistas: dict = {}
    for chave, valor in pares:
        if chave in vistas:
            raise _Duplicada(chave)
        vistas[chave] = valor
    return vistas


def _linha_de(fonte: str, nome: str) -> int:
    agulha = f'"{nome}"'
    for numero, linha in enumerate(fonte.split("\n"), start=1):
        if agulha in linha:
            return numero
    return 0


def _textos(no, acumulado: list[str]) -> None:
    """Todas as chaves e todos os textos do documento."""
    if isinstance(no, dict):
        for chave, valor in no.items():
            acumulado.append(str(chave))
            _textos(valor, acumulado)
    elif isinstance(no, list):
        for item in no:
            _textos(item, acumulado)
    elif isinstance(no, str):
        acumulado.append(no)


class _Schema:
    def __init__(self, raiz: dict) -> None:
        self.raiz = raiz
        self.ilegiveis: list[str] = []

    def resolver(self, no, vistos: frozenset = frozenset()):
        """Segue um `$ref` interno. Devolve o no referido (ou o proprio)."""
        while isinstance(no, dict) and isinstance(no.get("$ref"), str):
            referencia = no["$ref"]
            if not referencia.startswith("#"):
                return no  # externo: limite dito
            if referencia in vistos:
                return {}
            vistos = vistos | {referencia}
            alvo = self.raiz
            for parte in [p for p in referencia[1:].split("/") if p]:
                parte = parte.replace("~1", "/").replace("~0", "~")
                if isinstance(alvo, dict) and parte in alvo:
                    alvo = alvo[parte]
                else:
                    self.ilegiveis.append(f"`$ref` {referencia!r} nao aponta para nada no documento")
                    return {}
            # as chaves ao lado do `$ref` continuam a valer
            irmas = {k: v for k, v in no.items() if k != "$ref"}
            no = {**alvo, **irmas} if isinstance(alvo, dict) and irmas else alvo
        return no

    def nomes(self, no, acumulado: dict[str, dict], vistos: frozenset = frozenset(), fundo: int = 0) -> None:
        """Os nomes de campo de um (sub)schema, a qualquer profundidade."""
        no = self.resolver(no)
        if not isinstance(no, dict) or fundo > 40 or id(no) in vistos:
            return
        vistos = vistos | {id(no)}
        propriedades = no.get("properties")
        if isinstance(propriedades, dict):
            for nome, sub in propriedades.items():
                acumulado.setdefault(nome, sub if isinstance(sub, dict) else {})
                self.nomes(sub, acumulado, vistos, fundo + 1)
        for nome in no.get("required") or []:
            if isinstance(nome, str):
                acumulado.setdefault(nome, {})
        dependentes = no.get("dependentRequired")
        if isinstance(dependentes, dict):
            for nome, outros in dependentes.items():
                acumulado.setdefault(nome, {})
                for outro in outros if isinstance(outros, list) else []:
                    if isinstance(outro, str):
                        acumulado.setdefault(outro, {})
        nomes_permitidos = self.resolver(no.get("propertyNames"))
        if isinstance(nomes_permitidos, dict):
            for nome in _fixos(nomes_permitidos) or []:
                if isinstance(nome, str):
                    acumulado.setdefault(nome, {})
        if isinstance(no.get("patternProperties"), dict) and no["patternProperties"]:
            self.ilegiveis.append(
                "`patternProperties`: um padrao nao e um nome que se possa comparar com o dicionario; "
                "enumere os campos em `properties`"
            )
        for chave in ("dependentSchemas", "dependencies"):
            if isinstance(no.get(chave), dict):
                for nome, sub in no[chave].items():
                    acumulado.setdefault(nome, {})
                    self.nomes(sub, acumulado, vistos, fundo + 1)
        for chave in _SUBSCHEMAS:
            self.nomes(no.get(chave), acumulado, vistos, fundo + 1)
        for chave in _COMBINADORES + ("prefixItems",):
            for parte in no.get(chave) or []:
                self.nomes(parte, acumulado, vistos, fundo + 1)

    def de_topo(self, no, vistos: frozenset = frozenset()) -> dict[str, dict]:
        """As propriedades de topo, incluindo as que venham por `allOf` e por `$ref`."""
        no = self.resolver(no)
        resultado: dict[str, dict] = {}
        if not isinstance(no, dict) or id(no) in vistos:
            return resultado
        vistos = vistos | {id(no)}
        if isinstance(no.get("properties"), dict):
            for nome, sub in no["properties"].items():
                resultado[nome] = sub if isinstance(sub, dict) else {}
        for nome in no.get("required") or []:
            if isinstance(nome, str):
                resultado.setdefault(nome, {})
        for chave in _COMBINADORES:
            for parte in no.get(chave) or []:
                for nome, sub in self.de_topo(parte, vistos).items():
                    if nome not in resultado or not resultado[nome]:
                        resultado[nome] = sub
        return resultado


def _fixos(sub: dict) -> list | None:
    """Os valores a que um sub-schema esta fixo, ou `None` se nao estiver."""
    if "const" in sub:
        return [sub["const"]]
    if isinstance(sub.get("enum"), list) and sub["enum"]:
        return list(sub["enum"])
    return None


def verificar(ficheiro: str, fonte: str, saber: Saber) -> list[Achado]:
    try:
        documento = json.loads(fonte, object_pairs_hook=_sem_duplicadas)
    except _Duplicada as excepcao:
        return [
            Achado(ficheiro, _linha_de(fonte, str(excepcao)), ILEGIVEL,
                   f"chave `{excepcao}` repetida no mesmo objecto: o JSON fica com a ultima e a "
                   "primeira deixa de ser lida")
        ]
    except json.JSONDecodeError as excepcao:
        return [Achado(ficheiro, excepcao.lineno, ILEGIVEL, f"JSON invalido: {excepcao.msg}")]
    if not isinstance(documento, dict):
        return [Achado(ficheiro, 0, ILEGIVEL, "o schema nao e um objecto JSON")]

    achados: list[Achado] = []
    politica = saber.politica
    schema = _Schema(documento)

    # --- nivel 1: tudo o que e texto no documento --------------------------------
    textos: list[str] = []
    _textos(documento, textos)
    variantes_vistas: set[str] = set()
    for texto in textos:
        encontradas = list(variantes_em_texto(saber, texto))
        de_valor = saber.variante_de_valor(texto)
        if de_valor is not None:
            encontradas.append(de_valor)
        for v in encontradas:
            if v.nome not in variantes_vistas:
                variantes_vistas.add(v.nome)
                achados.append(variante(ficheiro, _linha_de(fonte, texto), v))

    topo = schema.de_topo(documento)

    # --- o nome do ficheiro, o tipo e a versao ------------------------------------
    caminho = ficheiro.replace("\\", "/")
    tipo_do_evento = ""
    versao_no_nome = _VERSAO_NO_NOME.search(caminho)
    partilhado = caminho in politica.eventos_partilhados
    if not versao_no_nome and not partilhado:
        achados.append(
            Achado(
                ficheiro,
                0,
                REGRA,
                "um schema de evento chama-se `v<N>.schema.json` (N sem zeros a esquerda), para "
                "que a versao do ficheiro se possa comparar com a `versao` que ele fixa. Se e um "
                f"schema partilhado, declare-o em {POLITICA} (`eventos_partilhados`)",
            )
        )
    if versao_no_nome:
        tipos = _fixos(schema.resolver(topo.get("tipo", {})) or {})
        if not tipos:
            achados.append(
                Achado(ficheiro, _linha_de(fonte, "tipo"), REGRA,
                       "schema de evento sem `tipo` fixo (`const` ou `enum`): nao se sabe que evento descreve")
            )
        else:
            for tipo in tipos:
                if not isinstance(tipo, str):
                    achados.append(Achado(ficheiro, 0, ILEGIVEL, f"`tipo` que nao e texto: {tipo!r}"))
                elif tipo not in variantes_vistas and not aceita(saber, "evento", tipo):
                    achados.append(fora(ficheiro, _linha_de(fonte, tipo), "evento", tipo))
            if len(tipos) == 1 and isinstance(tipos[0], str):
                tipo_do_evento = tipos[0]

        esperada = int(versao_no_nome.group(1))
        envelope = politica.envelope
        versoes = _fixos(schema.resolver(topo.get("versao", {})) or {})
        # `type(v) is int`: em Python `True == 1`, e `versao: {"const": true}`
        # passava por versao 1.
        certa = versoes is not None and len(versoes) == 1 and type(versoes[0]) is int and versoes[0] == esperada
        if not certa:
            lido = "livre" if versoes is None else f"fixa em {versoes}"
            achados.append(
                Achado(
                    ficheiro,
                    _linha_de(fonte, "versao"),
                    REGRA,
                    f"`versao` {lido} em `v{esperada}.schema.json` → `versao` com `const: {esperada}`, "
                    f"dicionário §{envelope['seccao']} (versoes desconhecidas falham de forma "
                    "visivel, nunca ignoradas em silencio; um schema que aceita qualquer versao "
                    "deixa o consumidor ignora-las)",
                )
            )

    # --- nivel 2: envelope e payload ------------------------------------------------
    campos_do_envelope = set(politica.envelope["nomes"])
    for nome in topo:
        if nome in variantes_vistas:
            continue
        if nome not in campos_do_envelope and not saber.extensoes.tem("campo", f"envelope.{nome}"):
            achados.append(
                fora(ficheiro, _linha_de(fonte, nome), "campo", f"envelope.{nome}",
                     f"`{politica.envelope['canonico']}`, dicionário §{politica.envelope['seccao']}")
            )

    do_payload: dict[str, dict] = {}
    schema.nomes(topo.get("payload"), do_payload)
    for nome in do_payload:
        if nome in variantes_vistas:
            continue
        qualificado = f"{tipo_do_evento}.{nome}" if tipo_do_evento else nome
        if not aceita(saber, "campo", qualificado, simples=nome):
            achados.append(fora(ficheiro, _linha_de(fonte, nome), "campo", qualificado))

    for mensagem in dict.fromkeys(schema.ilegiveis):
        achados.append(Achado(ficheiro, 0, ILEGIVEL, mensagem))
    return achados
