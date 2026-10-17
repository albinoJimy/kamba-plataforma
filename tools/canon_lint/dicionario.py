"""O que o lint sabe: o dicionario exportado, as extensoes e a politica.

Tres ficheiros, tres naturezas:

* `canon/dicionario.yaml` — **gerado** do Markdown; so se le.
* `canon/extensoes.yaml` — nomes que o §3 nao cobre, um a um, com ticket e data.
* `ci/canon-lint.yaml` — a politica do gate: onde estao as superficies e as
  poucas regras que o Markdown nao da de forma legivel por maquina.

Qualquer defeito de forma levanta `ConfiguracaoInvalida` (saida 2). Chaves
desconhecidas sao **recusadas**: um ficheiro de politica que aceita uma chave
que ninguem le e um ficheiro que alguem edita a pensar que mudou a regra
(`docs/ci.md` §7, lacunas 12 e 13).

## Que nomes sao «conhecidos»

O §3 e prosa com nomes entre crases, e nem tudo o que esta entre crases e um
nome de dados. Depois da revisao adversarial (ANALISE-05, M2), um token so e
conhecido se:

* for todo em minusculas (`SELECT`, `HMAC`, `ManualProvider` nao sao nomes de
  tabela nem de coluna);
* nao for uma palavra de tipo SQL (`boolean`, `uuid`, `jsonb`, …);
* tiver tres ou mais caracteres, salvo se for ele proprio um *span* inteiro
  (`id`, `lg`) — `a`, `z0` e `_` vinham de uma expressao regular entre crases.

E quatro tipos tem conjunto **proprio**, em vez do saco comum: tipos de evento,
tools, papeis e esquemas. Um papel deixou de servir como tool, e a metade de um
evento (`payment`, `confirmed`) deixou de servir como coluna.

O que continua comum, e e limite medido e nao resolvido: tabelas, colunas,
valores, campos e parametros partilham um conjunto. `estado` e aceite como
coluna de qualquer tabela, e um valor de estado e aceite como nome de coluna.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file

DICIONARIO = "canon/dicionario.yaml"
EXTENSOES = "canon/extensoes.yaml"
POLITICA = "ci/canon-lint.yaml"

#: Os tipos de extensao. Cada um corresponde a uma verificacao de nivel 2.
TIPOS_DE_EXTENSAO = (
    "esquema",    # CREATE SCHEMA <nome>
    "tabela",     # <tabela>
    "coluna",     # <tabela>.<coluna>
    "valor",      # <tabela>.<coluna>=<valor>
    "papel",      # CREATE ROLE <nome>
    "tipo_sql",   # CREATE TYPE / CREATE DOMAIN <nome>
    "evento",     # tipo de evento
    "campo",      # campo do envelope ou do payload de um evento
    "vertical",   # `id` de um ficheiro do registo
    "modulo",     # entitlements.modulo
    "limite",     # entitlements.limites[]
    "tool",       # nome de uma tool
    "parametro",  # <tool>.<parametro>
)

SUPERFICIES = ("migracoes", "eventos", "registo", "documentos")

#: Sentinelas que a politica **tem** de conter. Estao no codigo, e nao so no
#: YAML, porque uma lista de sentinelas que se esvazia num ficheiro de
#: configuracao deixava de proteger sem ninguem ver um *diff* de codigo
#: (ANALISE-05, M9). A politica pode acrescentar; nao pode retirar.
SENTINELAS_MINIMAS = (
    ("migrations/*", "migracoes"),
    ("*/migrations/*", "migracoes"),
    ("*/versions/*.py", "migracoes"),
    ("*.sql", "migracoes"),
    ("*.schema.json", "eventos"),
    ("*/eventos/*", "eventos"),
    ("*/events/*", "eventos"),
    ("registry/*", "registo"),
    ("*/registry/*", "registo"),
    ("docs/tecnica/*.md", "documentos"),
)

#: Palavras de tipo SQL e de formato que aparecem entre crases no §3 e nao sao
#: nomes de dados.
_NAO_SAO_NOMES = {
    "boolean", "uuid", "jsonb", "json", "text", "integer", "int", "bigint", "smallint",
    "bytea", "timestamptz", "timestamp", "date", "numeric", "varchar", "char",
    "null", "true", "false", "yaml", "snake_case",
}

_TICKET = re.compile(r"^KAM-\d{3}$")
_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MINUSCULAS = re.compile(r"^[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*$")
_LINHA_DE_EVENTOS = re.compile(r"[Ee]vento|Tipos do Piloto|Gatilho")
_EVENTO = re.compile(r"^[a-z]+\.[a-z_]+$")
_TOOL = re.compile(r"\btool ([a-z_][a-z0-9_]*)")


class ConfiguracaoInvalida(ValueError):
    """Um dos ficheiros do gate 3b falta ou nao tem a forma esperada."""


def _exigir_chaves(dados: dict, permitidas: set[str], onde: str) -> None:
    if not isinstance(dados, dict):
        raise ConfiguracaoInvalida(f"{onde}: tem de ser um mapa")
    a_mais = sorted(set(dados) - permitidas)
    if a_mais:
        raise ConfiguracaoInvalida(
            f"{onde}: chave(s) desconhecida(s) {a_mais}. Nenhum codigo as le; "
            "retire-as ou implemente-as."
        )


def _lista(dados: dict, chave: str, onde: str) -> list:
    valor = dados.get(chave)
    if valor is None:
        raise ConfiguracaoInvalida(f"{onde}: falta a chave `{chave}`")
    if not isinstance(valor, list):
        raise ConfiguracaoInvalida(f"{onde}: `{chave}` tem de ser uma lista")
    return valor


def _razao(item: dict, onde: str) -> None:
    if len(str(item.get("razao") or "")) < 30:
        raise ConfiguracaoInvalida(
            f"{onde}: precisa de uma `razao` que sobreviva a saida de quem a escreveu (>= 30 caracteres)"
        )


def data_iso(texto: str, onde: str) -> datetime.date:
    """Uma data ISO **verificada**: `2026-13-45` nao passa por ter a forma certa."""
    if not _DATA.match(str(texto)):
        raise ConfiguracaoInvalida(f"{onde}: data {texto!r} fora do formato AAAA-MM-DD")
    try:
        return datetime.date.fromisoformat(str(texto))
    except ValueError as excepcao:
        raise ConfiguracaoInvalida(f"{onde}: data {texto!r} nao existe") from excepcao


@dataclass(frozen=True)
class Variante:
    nome: str
    tipo: str  # "nome" ou "valor"
    seccao: str
    conceito: str
    canonico: str

    def mensagem(self) -> str:
        """A forma que o criterio de aceitacao pede: «variante → canonico, §3.x»."""
        return f"`{self.nome}` → `{self.canonico}`, dicionário §{self.seccao}"


@dataclass
class Dicionario:
    versao: str
    entradas: list[dict]
    tabelas: dict[str, dict]
    dominios: dict[str, dict]
    variantes: list[Variante]
    contradicoes: list[dict]
    conhecidos: set[str] = field(default_factory=set)
    eventos: set[str] = field(default_factory=set)
    tools: set[str] = field(default_factory=set)
    papeis: set[str] = field(default_factory=set)
    esquemas: set[str] = field(default_factory=set)
    so_no_registo: set[str] = field(default_factory=set)
    variantes_nome: dict[str, Variante] = field(default_factory=dict)
    variantes_valor: dict[str, Variante] = field(default_factory=dict)

    def entrada(self, seccao: str, conceito: str) -> dict:
        for entrada in self.entradas:
            if entrada["seccao"] == seccao and entrada["conceito"] == conceito:
                return entrada
        raise ConfiguracaoInvalida(
            f"a politica cita o conceito {conceito!r} do §{seccao}, que nao existe em "
            f"{DICIONARIO}. O dicionario mudou; actualize {POLITICA}."
        )

    def dominio_de(self, tabela: str, coluna: str) -> dict | None:
        """O dominio fechado de uma coluna **de base de dados**.

        Primeiro o qualificado (`tenants.tipo`), depois pelo nome so
        (`authn_method`) — salvo os que **o proprio dicionario** declara que so
        valem no registo, escrevendo «No registo» antes do nome.

        Essa ultima parte vinha de `ci/canon-lint.yaml`, numa lista de
        excepcoes que desfazia em configuracao o que o §3.2 e o §3.7 ja diziam
        em prosa (KAM-141, linhas 6 e 9). O `so_no_registo` do dicionario
        continua a ser lido para que uma politica antiga nao rebente, e a
        politica deixou de precisar de o dizer.
        """
        qualificado = self.dominios.get(f"{tabela}.{coluna}")
        if qualificado:
            return qualificado
        if coluna in self.so_no_registo:
            return None
        dominio = self.dominios.get(coluna)
        if dominio and dominio.get("so_no_registo"):
            return None
        return dominio

    def dominio_qualificado(self, tabela: str, coluna: str) -> dict | None:
        return self.dominios.get(f"{tabela}.{coluna}")

    @classmethod
    def ler(cls, raiz: Path) -> "Dicionario":
        caminho = raiz / DICIONARIO
        if not caminho.is_file():
            raise ConfiguracaoInvalida(
                f"{DICIONARIO} nao existe. Gere-o: cd tools && python -m dict_export --root .."
            )
        try:
            dados = load_file(caminho)
        except YamlSubsetError as excepcao:
            raise ConfiguracaoInvalida(str(excepcao)) from excepcao
        if dados.get("version") != 1:
            raise ConfiguracaoInvalida(f"{DICIONARIO}: `version` tem de ser 1")
        for chave in ("entradas", "tabelas", "dominios", "variantes", "contradicoes"):
            _lista(dados, chave, DICIONARIO)

        variantes = [
            Variante(v["nome"], v["tipo"], v["seccao"], v["conceito"], v["canonico"])
            for v in dados["variantes"]
        ]
        if not variantes:
            raise ConfiguracaoInvalida(
                f"{DICIONARIO} nao tem variantes: o nivel 1 do gate ficaria vazio"
            )
        dicionario = cls(
            versao=str(dados.get("versao_dicionario", "")),
            entradas=dados["entradas"],
            # A primeira assinatura de cada tabela e a que a define. A emenda 1.5
            # escreve `tenants(id, tipo, estado)` na linha do papel do resolvedor —
            # as colunas que ele pode ler — e essa nao substitui `platform.tenants(id uuid)`.
            tabelas={t["nome"]: t for t in reversed(dados["tabelas"])},
            dominios={d["coluna"]: d for d in dados["dominios"]},
            variantes=variantes,
            contradicoes=dados["contradicoes"],
        )

        for entrada in dicionario.entradas:
            inteiros = set(entrada["literais"])
            de_eventos = bool(_LINHA_DE_EVENTOS.search(entrada["conceito"]))
            for nome in list(entrada["nomes"]) + list(entrada["nomes_nota"]):
                if not _MINUSCULAS.match(nome):
                    continue
                if "." in nome:
                    primeira = nome.split(".", 1)[0]
                    if (
                        de_eventos
                        and _EVENTO.match(nome)
                        and "_" not in primeira
                        and not set(nome.split(".")) & _NAO_SAO_NOMES
                    ):
                        dicionario.eventos.add(nome)
                        continue
                    # `platform.tenants` da `tenants`; `payment_events.authn_ok`
                    # da `authn_ok`. As partes passam pelos mesmos filtros.
                    partes = [nome] + nome.split(".")
                else:
                    partes = [nome]
                for parte in partes:
                    if parte in _NAO_SAO_NOMES:
                        continue
                    if len(parte) < 3 and parte not in inteiros:
                        continue
                    dicionario.conhecidos.add(parte)
            dicionario.tools.update(_TOOL.findall(entrada["canonico"]))

        for variante in variantes:
            if variante.tipo == "nome":
                dicionario.variantes_nome[variante.nome] = variante
                dicionario.conhecidos.discard(variante.nome)
            else:
                dicionario.variantes_valor[variante.nome] = variante
        return dicionario


@dataclass(frozen=True)
class Extensao:
    nome: str
    tipo: str
    ticket: str
    data: str


class Extensoes:
    """`canon/extensoes.yaml`: o que passa sem estar no §3."""

    def __init__(self, entradas: list[Extensao]) -> None:
        self.entradas = entradas
        self._indice = {(e.tipo, e.nome) for e in entradas}
        self.usadas: set[tuple[str, str]] = set()

    def tem(self, tipo: str, nome: str) -> bool:
        if (tipo, nome) in self._indice:
            self.usadas.add((tipo, nome))
            return True
        return False

    @classmethod
    def ler(cls, raiz: Path, dicionario: Dicionario, hoje: datetime.date) -> "Extensoes":
        caminho = raiz / EXTENSOES
        if not caminho.is_file():
            raise ConfiguracaoInvalida(f"{EXTENSOES} nao existe")
        try:
            dados = load_file(caminho)
        except YamlSubsetError as excepcao:
            raise ConfiguracaoInvalida(str(excepcao)) from excepcao
        _exigir_chaves(dados, {"version", "extensoes"}, EXTENSOES)
        if dados.get("version") != 1:
            raise ConfiguracaoInvalida(f"{EXTENSOES}: `version` tem de ser 1")

        entradas: list[Extensao] = []
        vistas: set[tuple[str, str]] = set()
        for indice, bruto in enumerate(_lista(dados, "extensoes", EXTENSOES), start=1):
            onde = f"{EXTENSOES}: extensao {indice}"
            _exigir_chaves(bruto, {"nome", "tipo", "ticket", "data", "nota"}, onde)
            faltam = [c for c in ("nome", "tipo", "ticket", "data") if not bruto.get(c)]
            if faltam:
                raise ConfiguracaoInvalida(f"{onde}: falta {', '.join(faltam)}")
            nome, tipo = str(bruto["nome"]), str(bruto["tipo"])
            onde = f"{onde} ({nome})"
            if tipo not in TIPOS_DE_EXTENSAO:
                raise ConfiguracaoInvalida(
                    f"{onde}: tipo {tipo!r} desconhecido; os tipos sao {', '.join(TIPOS_DE_EXTENSAO)}"
                )
            if not _TICKET.match(str(bruto["ticket"])):
                raise ConfiguracaoInvalida(f"{onde}: ticket {bruto['ticket']!r} nao e um KAM-NNN")
            data = data_iso(str(bruto["data"]), onde)
            if data > hoje:
                raise ConfiguracaoInvalida(
                    f"{onde}: a data {data} e futura. E o dia em que a extensao entrou, nao um prazo"
                )
            if (tipo, nome) in vistas:
                raise ConfiguracaoInvalida(f"{onde}: extensao repetida")
            vistas.add((tipo, nome))

            # Uma variante conhecida falha sempre: nao ha extensao que a salve.
            for parte in re.split(r"[.=]", nome):
                if parte in dicionario.variantes_nome or (
                    tipo == "valor" and parte in dicionario.variantes_valor
                ):
                    variante = dicionario.variantes_nome.get(parte) or dicionario.variantes_valor[parte]
                    raise ConfiguracaoInvalida(
                        f"{onde}: {parte!r} e uma variante que o dicionario substitui "
                        f"({variante.mensagem()}). Uma extensao nao a pode permitir."
                    )
            # Uma extensao para o que o dicionario ja cobre e ruido que esconde
            # as que importam.
            proprios = {
                "evento": dicionario.eventos,
                "tool": dicionario.tools,
                "papel": dicionario.papeis,
                "esquema": dicionario.esquemas,
            }
            if tipo in proprios:
                ja_coberto = nome in proprios[tipo]
                ultimo = nome
            else:
                ultimo = nome.rsplit(".", 1)[-1] if tipo in ("coluna", "parametro", "campo") else nome
                ja_coberto = tipo != "valor" and ultimo in dicionario.conhecidos
            if ja_coberto:
                raise ConfiguracaoInvalida(
                    f"{onde}: {ultimo!r} ja e um nome do dicionario §3; a extensao e redundante"
                )
            entradas.append(Extensao(nome, tipo, str(bruto["ticket"]), str(bruto["data"])))
        return cls(entradas)


@dataclass
class Politica:
    superficies: dict[str, list[str]]
    fora_de_ambito: list[str]
    sentinelas: list[tuple[str, str]]
    dominios_por_conceito: list[dict]
    unicidades_proibidas: list[dict]
    confirmacao: dict[str, str]
    confirmacao_origem: dict
    eventos_de_pagamento: dict
    envelope: dict
    limites: dict
    verticais: dict
    auxiliares: dict[str, str]
    eventos_partilhados: list[str]

    @classmethod
    def ler(cls, raiz: Path, dicionario: Dicionario) -> "Politica":
        caminho = raiz / POLITICA
        if not caminho.is_file():
            raise ConfiguracaoInvalida(f"{POLITICA} nao existe")
        try:
            dados = load_file(caminho)
        except YamlSubsetError as excepcao:
            raise ConfiguracaoInvalida(str(excepcao)) from excepcao
        _exigir_chaves(
            dados,
            {
                "version", "superficies", "fora_de_ambito", "sentinelas",
                "dominios_por_conceito", "dominios_so_no_registo", "unicidades_proibidas",
                "confirmacao", "eventos_de_pagamento", "envelope", "limites", "verticais",
                "papeis", "esquemas", "auxiliares_de_migracao", "eventos_partilhados",
            },
            POLITICA,
        )
        if dados.get("version") != 1:
            raise ConfiguracaoInvalida(f"{POLITICA}: `version` tem de ser 1")

        bruto_superficies = dados.get("superficies")
        if not isinstance(bruto_superficies, dict):
            raise ConfiguracaoInvalida(f"{POLITICA}: `superficies` tem de ser um mapa")
        if set(bruto_superficies) != set(SUPERFICIES):
            raise ConfiguracaoInvalida(
                f"{POLITICA}: `superficies` tem de ter exactamente {sorted(SUPERFICIES)}"
            )
        superficies = {}
        for nome, padroes in bruto_superficies.items():
            if not isinstance(padroes, list) or not padroes:
                raise ConfiguracaoInvalida(
                    f"{POLITICA}: a superficie `{nome}` precisa de pelo menos um padrao"
                )
            superficies[nome] = [str(p) for p in padroes]

        fora = []
        for indice, area in enumerate(_lista(dados, "fora_de_ambito", POLITICA), start=1):
            onde = f"{POLITICA}: fora_de_ambito {indice}"
            _exigir_chaves(area, {"caminho", "razao"}, onde)
            if not area.get("caminho"):
                raise ConfiguracaoInvalida(f"{onde}: falta `caminho`")
            _razao(area, onde)
            fora.append(str(area["caminho"]))

        sentinelas = []
        for indice, item in enumerate(_lista(dados, "sentinelas", POLITICA), start=1):
            onde = f"{POLITICA}: sentinela {indice}"
            _exigir_chaves(item, {"padrao", "superficie"}, onde)
            if item.get("superficie") not in SUPERFICIES or not item.get("padrao"):
                raise ConfiguracaoInvalida(f"{onde}: precisa de `padrao` e de uma superficie conhecida")
            sentinelas.append((str(item["padrao"]), str(item["superficie"])))
        em_falta = [s for s in SENTINELAS_MINIMAS if s not in sentinelas]
        if em_falta:
            raise ConfiguracaoInvalida(
                f"{POLITICA}: faltam sentinelas obrigatorias {em_falta}. A lista minima esta em "
                "tools/canon_lint/dicionario.py; a politica pode acrescentar, nao retirar"
            )

        # --- dominios que o Markdown da por conceito, e nao por `coluna ∈ {…}` ----
        dominios = []
        for indice, item in enumerate(_lista(dados, "dominios_por_conceito", POLITICA), start=1):
            onde = f"{POLITICA}: dominios_por_conceito {indice}"
            _exigir_chaves(item, {"coluna", "seccao", "conceito"}, onde)
            entrada = dicionario.entrada(str(item["seccao"]), str(item["conceito"]))
            coluna = str(item["coluna"])
            if coluna in dicionario.dominios:
                raise ConfiguracaoInvalida(
                    f"{onde}: `{coluna}` ja tem dominio no dicionario; a politica nao o redefine"
                )
            dicionario.dominios[coluna] = {
                "coluna": coluna,
                "valores": list(entrada["literais"]),
                "seccao": entrada["seccao"],
                "conceito": entrada["conceito"],
            }
            dominios.append(item)

        for indice, item in enumerate(_lista(dados, "dominios_so_no_registo", POLITICA), start=1):
            onde = f"{POLITICA}: dominios_so_no_registo {indice}"
            _exigir_chaves(item, {"coluna", "razao"}, onde)
            coluna = str(item.get("coluna") or "")
            if coluna not in dicionario.dominios or "." in coluna:
                raise ConfiguracaoInvalida(
                    f"{onde}: `{coluna}` nao e um dominio nao qualificado do dicionario"
                )
            _razao(item, onde)
            dicionario.so_no_registo.add(coluna)

        # --- unicidades que o dicionario proibe por extenso -------------------------
        unicidades = []
        for indice, item in enumerate(_lista(dados, "unicidades_proibidas", POLITICA), start=1):
            onde = f"{POLITICA}: unicidades_proibidas {indice}"
            _exigir_chaves(item, {"colunas", "seccao", "conceito"}, onde)
            entrada = dicionario.entrada(str(item["seccao"]), str(item["conceito"]))
            colunas = [str(c) for c in item.get("colunas") or []]
            forma = "UNIQUE(" + ",".join(colunas) + ")"
            literais = {re.sub(r"\s+", "", literal) for literal in entrada["literais"]}
            if forma not in literais:
                raise ConfiguracaoInvalida(
                    f"{onde}: o dicionario §{entrada['seccao']} ({entrada['conceito']}) nao "
                    f"escreve `{forma}`. A politica so pode proibir o que o dicionario proibe."
                )
            unicidades.append(
                {"colunas": colunas, "seccao": entrada["seccao"], "conceito": entrada["conceito"],
                 "canonico": entrada["canonico"]}
            )

        # --- identificador de confirmacao por vertical ------------------------------
        bruto_confirmacao = dados.get("confirmacao")
        _exigir_chaves(bruto_confirmacao, {"seccao", "conceito", "por_vertical"}, f"{POLITICA}: confirmacao")
        origem = dicionario.entrada(str(bruto_confirmacao["seccao"]), str(bruto_confirmacao["conceito"]))
        confirmacao = {}
        for item in bruto_confirmacao.get("por_vertical") or []:
            _exigir_chaves(item, {"vertical", "identificador"}, f"{POLITICA}: confirmacao.por_vertical")
            if item["identificador"] not in origem["literais"]:
                raise ConfiguracaoInvalida(
                    f"{POLITICA}: confirmacao: `{item['identificador']}` nao e um dos "
                    f"identificadores do dicionario §{origem['seccao']} ({origem['literais']})"
                )
            confirmacao[str(item["vertical"])] = str(item["identificador"])

        # --- os dois eventos de pagamento --------------------------------------------
        pagamento = dados.get("eventos_de_pagamento")
        _exigir_chaves(pagamento, {"seccao", "conceito", "distinguem_o_caminho"}, f"{POLITICA}: eventos_de_pagamento")
        origem_pagamento = dicionario.entrada(str(pagamento["seccao"]), str(pagamento["conceito"]))
        eventos = [n for n in origem_pagamento["nomes"] if n in dicionario.eventos]
        if len(eventos) != 2:
            raise ConfiguracaoInvalida(
                f"{POLITICA}: esperava dois eventos de pagamento no dicionario "
                f"§{origem_pagamento['seccao']}, encontrei {eventos}"
            )
        distinguem = pagamento.get("distinguem_o_caminho")
        if not isinstance(distinguem, list):
            raise ConfiguracaoInvalida(f"{POLITICA}: `distinguem_o_caminho` tem de ser uma lista")

        referencias = {}
        for chave in ("envelope", "limites", "verticais", "papeis", "esquemas"):
            item = dados.get(chave)
            _exigir_chaves(item, {"seccao", "conceito"}, f"{POLITICA}: {chave}")
            referencias[chave] = dicionario.entrada(str(item["seccao"]), str(item["conceito"]))
        for chave, destino in (("papeis", dicionario.papeis), ("esquemas", dicionario.esquemas)):
            destino.update(n for n in referencias[chave]["nomes"] if n in dicionario.conhecidos)
            if not destino:
                raise ConfiguracaoInvalida(
                    f"{POLITICA}: a linha citada em `{chave}` nao da nome nenhum; o dicionario mudou"
                )

        # --- modulos auxiliares que as revisoes podem chamar -------------------------
        auxiliares: dict[str, str] = {}
        for indice, item in enumerate(_lista(dados, "auxiliares_de_migracao", POLITICA), start=1):
            onde = f"{POLITICA}: auxiliares_de_migracao {indice}"
            _exigir_chaves(item, {"modulo", "ficheiro", "razao"}, onde)
            if not item.get("modulo") or not item.get("ficheiro"):
                raise ConfiguracaoInvalida(f"{onde}: precisa de `modulo` e de `ficheiro`")
            _razao(item, onde)
            auxiliares[str(item["modulo"])] = str(item["ficheiro"])

        partilhados = [str(p) for p in _lista(dados, "eventos_partilhados", POLITICA)]

        return cls(
            superficies=superficies,
            fora_de_ambito=fora,
            sentinelas=sentinelas,
            dominios_por_conceito=dominios,
            unicidades_proibidas=unicidades,
            confirmacao=confirmacao,
            confirmacao_origem=origem,
            eventos_de_pagamento={
                "eventos": eventos,
                "seccao": origem_pagamento["seccao"],
                "canonico": origem_pagamento["canonico"],
                "distinguem": [str(x) for x in distinguem],
            },
            envelope=referencias["envelope"],
            limites=referencias["limites"],
            verticais=referencias["verticais"],
            auxiliares=auxiliares,
            eventos_partilhados=partilhados,
        )


@dataclass
class Saber:
    """Tudo o que uma verificacao precisa, junto."""

    dicionario: Dicionario
    extensoes: Extensoes
    politica: Politica
    raiz: Path

    @classmethod
    def ler(cls, raiz: Path, hoje: datetime.date | None = None) -> "Saber":
        dicionario = Dicionario.ler(raiz)
        politica = Politica.ler(raiz, dicionario)
        extensoes = Extensoes.ler(raiz, dicionario, hoje or datetime.date.today())
        return cls(dicionario, extensoes, politica, raiz)

    def carregar(self, relativo: str) -> str | None:
        """O texto de um ficheiro do repositorio, ou `None` se nao se ler."""
        try:
            return (self.raiz / relativo).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def variante_de_nome(self, nome: str) -> Variante | None:
        return self.dicionario.variantes_nome.get(nome)

    def variante_de_valor(self, valor: str) -> Variante | None:
        return self.dicionario.variantes_valor.get(valor)

    def conhecido(self, nome: str, tipo: str = "") -> bool:
        """`True` se o §3 cobre `nome` para o tipo pedido."""
        proprios = {
            "evento": self.dicionario.eventos,
            "tool": self.dicionario.tools,
            "papel": self.dicionario.papeis,
            "esquema": self.dicionario.esquemas,
        }
        if tipo in proprios:
            return nome in proprios[tipo]
        return nome in self.dicionario.conhecidos
