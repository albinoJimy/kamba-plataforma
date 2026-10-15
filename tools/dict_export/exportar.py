"""Das linhas do §3 ao modelo exportado, e do modelo ao YAML.

As regras estao aqui, por extenso, porque sao elas que decidem o que o gate 3b
recusa. Mudar uma regra muda `canon/dicionario.yaml`, e isso aparece no *diff*.

1. **Tokens.** So conta o que esta entre crases. Um *span* e uma **referencia**
   (e e ignorado) se contiver `/` ou `§` — caminhos e citacoes de documento.
2. **Nomes canonicos** de uma linha: os identificadores dos *spans* das colunas
   «Conceito» e «Nome». `contacts(contact_id, tenant_id, …)` da `contacts`,
   `contact_id`, `tenant_id`; `payment_events.authn_ok boolean` da
   `payment_events.authn_ok` e `boolean`.
3. **Assinaturas.** Um *span* `nome(a, b, …)` em minusculas e uma tabela com as
   suas colunas; `…` marca-a como aberta. `UNIQUE(a, b)` nao e tabela.
4. **Dominios.** `` `x` ∈ {`a`, `b`} `` da o dominio fechado de `x`.
5. **Variantes.** Um *span* da coluna «Substitui» que seja um identificador
   simples (ou `'valor'` entre plicas) e que **nao** seja canonico em linha
   nenhuma do §3. Um identificador pontuado (`tenants.estado`) so e variante se
   nem ele nem a sua ultima parte forem canonicos: «`tenants.estado` sem
   `restrito`» descreve um defeito, nao proibe o nome da coluna. Um *span* todo
   em maiusculas (`SET`) e uma palavra-chave SQL, nao um nome: nao e variante.
6. **Contradicoes.** Um nome que esta em «Nome» e tambem em «Substitui» **na
   mesma linha**, quando a celula «Substitui» e uma lista pura de nomes (so
   crases e separadores). Nao se escolhe: fica canonico (proibi-lo partiria o
   DDL que o usa) e sai em `contradicoes`, que o lint imprime em cada execucao.
   Numa celula em prosa («`tenants.estado` sem `restrito`») o nome canonico esta
   a ser citado para descrever o defeito, e nao conta.
7. **Notas.** Os identificadores da coluna «Nota» ficam em `nomes_nota`: contam
   como nomes conhecidos (os campos de `consent_event` so existem ai), mas
   nunca tiram um nome da lista de variantes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from kamba_yaml import load

from .markdown import DicionarioIlegivel, Linha, ler_linhas, ultima_versao

FONTE = "specs/02_Dicionario_de_Dados_Canonico.md"
DESTINO = "canon/dicionario.yaml"

_SPAN = re.compile(r"`([^`]+)`")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_IDENT_SIMPLES = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IDENT_PONTUADO = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
_ASSINATURA = re.compile(r"^([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?)\((.*)\)$")
_DOMINIO = re.compile(r"`([^`]+)`\s*∈\s*\{([^}]*)\}")
_ENTRE_PLICAS = re.compile(r"^'([^']*)'$")
_SO_SEPARADORES = re.compile(r"^[\s,;…]*$")


def _e_referencia(span: str) -> bool:
    return "/" in span or "§" in span


def _spans(celula: str) -> list[str]:
    return [s for s in _SPAN.findall(celula) if not _e_referencia(s)]


def _identificadores(spans: list[str]) -> list[str]:
    vistos: list[str] = []
    for span in spans:
        for nome in _IDENT.findall(span):
            if nome not in vistos:
                vistos.append(nome)
    return vistos


def _e_lista_pura(celula: str) -> bool:
    """`True` se a celula so tem nomes entre crases e separadores entre eles."""
    return bool(_SO_SEPARADORES.match(_SPAN.sub("", celula)))


def _sem_marcacao(celula: str) -> str:
    """O texto de uma celula sem crases nem negrito, para citar numa mensagem."""
    return celula.replace("`", "").replace("**", "").replace("*", "").strip()


@dataclass
class Entrada:
    seccao: str
    conceito: str
    canonico: str
    literais: list[str]
    nomes: list[str]
    nomes_nota: list[str]
    variantes_literais: list[str]
    linha: int
    substitui_e_lista: bool = False


@dataclass
class Modelo:
    versao_dicionario: str
    entradas: list[Entrada] = field(default_factory=list)
    tabelas: list[dict] = field(default_factory=list)
    dominios: list[dict] = field(default_factory=list)
    variantes: list[dict] = field(default_factory=list)
    contradicoes: list[dict] = field(default_factory=list)

    def como_dados(self) -> dict:
        """A estrutura que vai para o YAML (e que o `--check` compara)."""
        return {
            "version": 1,
            "fonte": FONTE,
            "versao_dicionario": self.versao_dicionario,
            "entradas": [
                {
                    "seccao": e.seccao,
                    "conceito": e.conceito,
                    "canonico": e.canonico,
                    "literais": list(e.literais),
                    "nomes": list(e.nomes),
                    "nomes_nota": list(e.nomes_nota),
                    "variantes_literais": list(e.variantes_literais),
                }
                for e in self.entradas
            ],
            "tabelas": self.tabelas,
            "dominios": self.dominios,
            "variantes": self.variantes,
            "contradicoes": self.contradicoes,
        }


def _entrada(linha: Linha) -> Entrada:
    conceito = linha.celulas["conceito"]
    nome = linha.celulas["nome"]
    literais = _spans(nome)
    return Entrada(
        seccao=linha.seccao,
        conceito=_sem_marcacao(conceito),
        canonico=_sem_marcacao(nome),
        literais=literais,
        nomes=_identificadores(_spans(conceito) + literais),
        nomes_nota=_identificadores(_spans(linha.celulas.get("nota", ""))),
        variantes_literais=_spans(linha.celulas.get("substitui", "")),
        linha=linha.numero,
        substitui_e_lista=_e_lista_pura(linha.celulas.get("substitui", "")),
    )


def construir(texto: str) -> Modelo:
    """Constroi o modelo a partir do Markdown do dicionario."""
    linhas = ler_linhas(texto)
    modelo = Modelo(versao_dicionario=ultima_versao(texto))
    modelo.entradas = [_entrada(linha) for linha in linhas]

    vistos: set[tuple[str, str]] = set()
    for entrada in modelo.entradas:
        chave = (entrada.seccao, entrada.conceito)
        if chave in vistos:
            raise DicionarioIlegivel(
                f"linha {entrada.linha}: o conceito {entrada.conceito!r} aparece duas "
                f"vezes no §{entrada.seccao}"
            )
        vistos.add(chave)

    canonicos: set[str] = set()
    for entrada in modelo.entradas:
        canonicos.update(entrada.nomes)

    # --- tabelas e dominios, das celulas de nome --------------------------------
    for entrada, linha in zip(modelo.entradas, linhas):
        for literal in entrada.literais:
            assinatura = _ASSINATURA.match(literal)
            if not assinatura:
                continue
            qualificado, corpo = assinatura.group(1), assinatura.group(2)
            esquema, _, tabela = qualificado.rpartition(".")
            colunas: list[str] = []
            for parte in corpo.split(","):
                achado = _IDENT.match(parte.strip())
                if achado:
                    colunas.append(achado.group(0))
            modelo.tabelas.append(
                {
                    "nome": tabela,
                    "esquema": esquema,
                    "colunas": colunas,
                    "aberta": "…" in corpo or "..." in corpo,
                    "assinatura": literal,
                    "seccao": entrada.seccao,
                    "conceito": entrada.conceito,
                }
            )
        for alvo, corpo in _DOMINIO.findall(linha.celulas["nome"]):
            nomes_alvo = _IDENT.findall(alvo)
            if not nomes_alvo:
                continue
            valores = [v for v in _SPAN.findall(corpo)]
            if not valores:
                continue
            modelo.dominios.append(
                {
                    "coluna": nomes_alvo[0],
                    "valores": valores,
                    "seccao": entrada.seccao,
                    "conceito": entrada.conceito,
                }
            )

    # --- variantes e contradicoes, das celulas «Substitui» ----------------------
    ja: set[tuple[str, str]] = set()
    for entrada in modelo.entradas:
        for literal in entrada.variantes_literais:
            plicas = _ENTRE_PLICAS.match(literal)
            if plicas:
                nome, tipo = plicas.group(1), "valor"
            elif literal.isupper():
                # «`SET` de sessao» (emenda 1.5): uma palavra-chave SQL, nao um
                # nome de dados. Proibi-la como nome reprovava todo o `SET` de
                # todos os documentos. O que a linha substitui e uma pratica, e
                # isso o lint de nomes nao ve.
                continue
            elif _IDENT_SIMPLES.match(literal):
                nome, tipo = literal, "nome"
            elif _IDENT_PONTUADO.match(literal):
                nome, tipo = literal, "nome"
                if literal in canonicos or literal.rsplit(".", 1)[1] in canonicos:
                    continue
            else:
                continue  # expressao: nao e um nome que se possa proibir

            if tipo == "nome" and nome in canonicos:
                if entrada.substitui_e_lista:
                    # Numa lista pura de variantes, um nome que e canonico — nesta
                    # linha ou noutra — nao pode ser descartado em silencio: o
                    # dicionario diz ao mesmo tempo que e o nome e que foi substituido.
                    na_mesma = nome in entrada.nomes
                    modelo.contradicoes.append(
                        {
                            "nome": nome,
                            "seccao": entrada.seccao,
                            "conceito": entrada.conceito,
                            "razao": (
                                "esta na coluna do nome canonico e na coluna "
                                "«Substitui» da mesma linha; tratado como canonico"
                                if na_mesma
                                else "esta na coluna «Substitui» desta linha e e nome canonico "
                                "noutra linha do §3; tratado como canonico"
                            ),
                        }
                    )
                continue
            if (nome, tipo) in ja:
                continue
            ja.add((nome, tipo))
            modelo.variantes.append(
                {
                    "nome": nome,
                    "tipo": tipo,
                    "seccao": entrada.seccao,
                    "conceito": entrada.conceito,
                    "canonico": entrada.canonico,
                }
            )

    # Uma variante nunca e um nome conhecido, mesmo que uma nota a cite.
    proibidos = {v["nome"] for v in modelo.variantes if v["tipo"] == "nome"}
    for entrada in modelo.entradas:
        entrada.nomes_nota = [n for n in entrada.nomes_nota if n not in proibidos]

    if not modelo.variantes:
        raise DicionarioIlegivel(
            "a exportacao nao encontrou variante nenhuma na coluna «Substitui»: "
            "ou o dicionario mudou de forma, ou a leitura partiu-se"
        )
    return modelo


# ------------------------------------------------------------------ YAML


def _texto(valor: str) -> str:
    """Um escalar de texto, sempre entre aspas.

    O leitor do repositorio (`kamba_yaml`) nao interpreta escapes: tira a
    primeira e a ultima aspa e fica com o meio. Por isso escolhe-se a aspa que o
    texto nao contem, e recusa-se o que contenha as duas. Tudo o resto que o
    leitor possa interpretar de outra maneira e apanhado pela verificacao de
    ida-e-volta em `render`.
    """
    if "\n" in valor:
        raise DicionarioIlegivel(f"texto com quebra de linha nao se exporta: {valor!r}")
    if '"' not in valor:
        return f'"{valor}"'
    if "'" not in valor:
        return f"'{valor}'"
    raise DicionarioIlegivel(f"texto com os dois tipos de aspas nao se exporta: {valor!r}")


def _emitir(valor, indentacao: int, linhas: list[str], chave: str | None = None) -> None:
    prefixo = " " * indentacao
    cabeca = f"{prefixo}{chave}:" if chave is not None else None
    if isinstance(valor, bool):
        linhas.append(f"{cabeca} {'true' if valor else 'false'}")
    elif isinstance(valor, int):
        linhas.append(f"{cabeca} {valor}")
    elif isinstance(valor, str):
        linhas.append(f"{cabeca} {_texto(valor)}")
    elif isinstance(valor, list):
        if not valor:
            linhas.append(f"{cabeca} []")
            return
        linhas.append(cabeca)
        for item in valor:
            if isinstance(item, dict):
                primeira = True
                for sub_chave, sub_valor in item.items():
                    if primeira:
                        bloco: list[str] = []
                        _emitir(sub_valor, indentacao + 4, bloco, sub_chave)
                        bloco[0] = f"{prefixo}  - {bloco[0].lstrip()}"
                        linhas.extend(bloco)
                        primeira = False
                    else:
                        _emitir(sub_valor, indentacao + 4, linhas, sub_chave)
            else:
                linhas.append(f"{prefixo}  - {_texto(str(item))}")
    else:
        raise DicionarioIlegivel(f"tipo que a exportacao nao sabe escrever: {type(valor)}")


CABECALHO = """\
# GERADO — nao editar a mao.
#
# Exportacao do §3 de specs/02_Dicionario_de_Dados_Canonico.md (KAM-111).
# A fonte da verdade e o Markdown. Para regenerar:
#
#     cd tools && python -m dict_export --root ..
#
# O gate 3b (`make ci-3b`) falha se este ficheiro divergir do Markdown, pelo que
# uma alteracao feita aqui a mao nao sobrevive ao CI. As regras da exportacao
# estao em tools/dict_export/exportar.py; o que cada bloco significa esta em
# docs/nomes-canonicos.md.
"""


def render(modelo: Modelo) -> str:
    """O YAML, com verificacao de ida-e-volta pelo leitor do repositorio."""
    dados = modelo.como_dados()
    linhas: list[str] = []
    for chave, valor in dados.items():
        _emitir(valor, 0, linhas, chave)
        if isinstance(valor, list):
            linhas.append("")
    texto = CABECALHO + "\n" + "\n".join(linhas).rstrip("\n") + "\n"
    relido = load(texto)
    if relido != dados:
        raise DicionarioIlegivel(
            "o YAML gerado nao se le de volta igual ao modelo: ha um texto que o "
            "leitor do repositorio interpreta de outra maneira"
        )
    return texto


def exportar(raiz: Path) -> str:
    caminho = raiz / FONTE
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError as excepcao:
        raise DicionarioIlegivel(f"nao consegui ler {caminho}: {excepcao}") from excepcao
    return render(construir(texto))
