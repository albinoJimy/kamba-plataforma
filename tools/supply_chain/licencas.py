"""O registo de licencas por versao (KAM-067, criterio 6).

`ci/licenses.yaml` (KAM-002) e a **politica**: que licencas entram. Este registo
e outra coisa — a mitigacao que o E4 §5 pede para o risco «a licenca desliza
para open-core mais restritivo»: *manter registo de licencas por versao*. Diz,
componente a componente, que versao foi lida, que licenca tinha nesse dia, e de
onde se leu.

Um registo que ninguem confronta com nada e um documento. Este e confrontado
com quatro coisas, e e isso que faz dele um controlo:

1. **a politica** — o estado declarado tem de ser o que `ci/licenses.yaml` da
   para aquela licenca: uma `BUSL-1.1` nao se regista como `permitido`;
2. **a lista de bloqueio** — o que se diz `bloqueado` tem de estar la;
3. **o repositorio** — o que se diz `nao_adoptado` nao pode estar nos
   manifestos nem nas imagens, e a versao em uso tem de ser a versao lida:
   subir de versao obriga a reler a licenca;
4. **o inventario de imagens** — cada componente de cada imagem tem registo.
"""

from __future__ import annotations

import dataclasses
import datetime as _datetime
import re
from pathlib import Path

from kamba_yaml import YamlSubsetError, exigir_chaves, load_file
from lint_arch import blocklist as blocklist_mod
from lint_arch import manifests, names, versions
from sbom import adr as adr_mod
from sbom import spdx
from sbom.cli import ConfiguracaoInvalida as PoliticaInvalida
from sbom.cli import ler_politica

from . import imagens as imagens_mod
from .base import Achado, ConfiguracaoInvalida

REGISTO = "ci/supply-chain/licencas.yaml"

PERMITIDO = "permitido"
PENDENTE = "pendente_de_decisao"
BLOQUEADO = "bloqueado"
EXCEPCAO = "excepcao"
NAO_ADOPTADO = "nao_adoptado"
ESTADOS = (PERMITIDO, PENDENTE, BLOQUEADO, EXCEPCAO, NAO_ADOPTADO)

ESTADOS_DE_VERIFICACAO = ("CONFIRMADO", "INDÍCIO", "NÃO VERIFICADO")

#: Estados que o veredicto da politica admite. `bloqueado` e `nao_adoptado`
#: servem a qualquer licenca: pode bloquear-se por outra razao que nao a licenca
#: (o LiteLLM antigo e MIT), e pode nao se adoptar o que e permitido.
ADMITIDOS = {
    spdx.PERMITIDA: (PERMITIDO, BLOQUEADO, NAO_ADOPTADO),
    spdx.PENDENTE: (PENDENTE,),
    spdx.NEGADA: (BLOQUEADO, EXCEPCAO, NAO_ADOPTADO),
    spdx.DESCONHECIDA: (BLOQUEADO, EXCEPCAO, NAO_ADOPTADO),
}

#: Componentes com edicao *Enterprise* no mesmo repositorio que o codigo livre
#: (E4 §1 e §2). O registo tem de dizer que partes sao — e o que tem de ficar
#: desligado. Vive no codigo: apagar o campo `ee` do YAML nao desliga a exigencia.
COM_EDICAO_ENTERPRISE = frozenset({"medusa", "chatwoot", "meilisearch", "litellm", "langfuse"})

#: Componentes que o registo **tem de ter**. Sem esta lista, apagar a linha do
#: Medusa apagava com ela a exigencia de registar a sua edicao Enterprise, e
#: apagar a do Redis apagava a marca de «pendente» que o ticket exige.
OBRIGATORIOS = COM_EDICAO_ENTERPRISE | {"redis", "valkey", "postgresql", "pgvector"}

_CHAVES_TOPO = {"version", "componentes"}
_CHAVES = {
    "componente", "versao", "licenca", "data_verificacao", "fonte",
    "estado_verificacao", "estado", "decisao", "excepcao_adr", "ee", "nota", "ligacoes",
}
_OBRIGATORIAS = (
    "componente", "versao", "licenca", "data_verificacao", "fonte",
    "estado_verificacao", "estado",
)
_COMPONENTE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_LIGACAO = re.compile(r"^(?P<tipo>npm|pypi|imagem):(?P<nome>[@a-z0-9][@a-z0-9._/-]*)$")
_ADR = re.compile(r"^ADR-L?[0-9]{3}$")
_DECISAO = re.compile(r"^D[0-9]{1,2}$")


@dataclasses.dataclass(frozen=True)
class Registo:
    componente: str
    versao: str
    licenca: str
    data_verificacao: str
    fonte: str
    estado_verificacao: str
    estado: str
    decisao: str
    excepcao_adr: str
    ee: str
    nota: str
    ligacoes: tuple[tuple[str, str], ...]


def ler_registo(raiz: Path, hoje: _datetime.date | None = None) -> list[Registo]:
    caminho = raiz / REGISTO
    if not caminho.is_file():
        raise ConfiguracaoInvalida(f"ficheiro em falta: {REGISTO}")
    try:
        dados = load_file(caminho)
    except YamlSubsetError as excepcao:
        raise ConfiguracaoInvalida(str(excepcao)) from excepcao
    # KAM-134: era a quarta implementacao da mesma ideia no repositorio, e a
    # unica que nem dizia o conjunto aceite.
    exigir_chaves(dados, _CHAVES_TOPO, REGISTO, erro=ConfiguracaoInvalida)
    if dados.get("version") != 1:
        raise ConfiguracaoInvalida(f"{REGISTO}: 'version' tem de ser 1")
    brutos = dados.get("componentes")
    if not isinstance(brutos, list) or not brutos:
        raise ConfiguracaoInvalida(
            f"{REGISTO}: `componentes` vazio — um registo sem linhas nao regista nada"
        )
    hoje = hoje or _datetime.date.today()

    registos: list[Registo] = []
    vistos: set[str] = set()
    for indice, bruto in enumerate(brutos, start=1):
        onde = f"{REGISTO}: componente {indice}"
        if not isinstance(bruto, dict):
            raise ConfiguracaoInvalida(f"{onde}: esperava um mapa")
        exigir_chaves(bruto, _CHAVES, onde, erro=ConfiguracaoInvalida)
        faltam = [c for c in _OBRIGATORIAS if bruto.get(c) in (None, "")]
        if faltam:
            raise ConfiguracaoInvalida(f"{onde}: campos em falta: {', '.join(faltam)}")
        componente = str(bruto["componente"])
        onde = f"{REGISTO}: {componente}"
        if not _COMPONENTE.match(componente):
            raise ConfiguracaoInvalida(f"{onde}: nome em minusculas, sem espacos")
        if componente in vistos:
            raise ConfiguracaoInvalida(f"{onde}: componente repetido")
        vistos.add(componente)
        try:
            data = _datetime.date.fromisoformat(str(bruto["data_verificacao"]))
        except ValueError as excepcao:
            raise ConfiguracaoInvalida(f"{onde}: `data_verificacao` tem de ser uma data ISO") from excepcao
        if data > hoje:
            raise ConfiguracaoInvalida(f"{onde}: `data_verificacao` esta no futuro ({data})")
        estado = str(bruto["estado"])
        if estado not in ESTADOS:
            raise ConfiguracaoInvalida(f"{onde}: `estado` tem de ser um de {', '.join(ESTADOS)}")
        verificacao = str(bruto["estado_verificacao"])
        if verificacao not in ESTADOS_DE_VERIFICACAO:
            raise ConfiguracaoInvalida(
                f"{onde}: `estado_verificacao` tem de ser um de "
                f"{', '.join(ESTADOS_DE_VERIFICACAO)}"
            )
        ligacoes: list[tuple[str, str]] = []
        brutas = bruto.get("ligacoes") or []
        if not isinstance(brutas, list):
            raise ConfiguracaoInvalida(f"{onde}: `ligacoes` tem de ser uma lista")
        for ligacao in brutas:
            correspondencia = _LIGACAO.match(str(ligacao))
            if not correspondencia:
                raise ConfiguracaoInvalida(
                    f"{onde}: ligacao {ligacao!r} ilegivel; use `npm:<pacote>`, "
                    "`pypi:<pacote>` ou `imagem:<repositorio>`"
                )
            ligacoes.append((correspondencia.group("tipo"), correspondencia.group("nome")))
        registos.append(
            Registo(
                componente=componente,
                versao=str(bruto["versao"]),
                licenca=str(bruto["licenca"]),
                data_verificacao=data.isoformat(),
                fonte=str(bruto["fonte"]),
                estado_verificacao=verificacao,
                estado=estado,
                decisao=str(bruto.get("decisao") or ""),
                excepcao_adr=str(bruto.get("excepcao_adr") or ""),
                ee=str(bruto.get("ee") or ""),
                nota=str(bruto.get("nota") or ""),
                ligacoes=tuple(ligacoes),
            )
        )
    return registos


def _em_uso(raiz: Path, inventario: imagens_mod.Inventario) -> dict[tuple[str, str], set[str]]:
    """(tipo, nome) -> versoes fixadas no repositorio. Conjunto vazio = presente sem pin."""
    em_uso: dict[tuple[str, str], set[str]] = {}
    for declaracao in manifests.collect(raiz):
        if declaracao.ecosystem == manifests.NPM:
            chave = ("npm", declaracao.name.lower())
        elif declaracao.ecosystem == manifests.PYPI:
            chave = ("pypi", names.canonical_pypi(declaracao.name))
        else:
            continue
        fixada = versions.exact_pin(declaracao.spec)
        em_uso.setdefault(chave, set())
        if fixada:
            em_uso[chave].add(fixada)
    for entrada in inventario.entradas:
        canonico = imagens_mod.nome_canonico(entrada.nome)
        versao = names.version_in_tag(entrada.etiqueta)
        segmentos = canonico.split("/")
        for inicio in range(len(segmentos)):
            chave = ("imagem", "/".join(segmentos[inicio:]))
            em_uso.setdefault(chave, set())
            if versao:
                em_uso[chave].add(versao)
    return em_uso


def _mesma_versao(tipo: str, em_uso: str, registada: str) -> bool:
    if em_uso == registada:
        return True
    # A etiqueta de uma imagem pode ser menos precisa do que a versao lida
    # (`3.12-slim` contra `3.12.15`): o que conta e nao a contradizer.
    return tipo == "imagem" and registada.startswith(em_uso + ".")


def verificar(raiz: Path, hoje: _datetime.date | None = None) -> tuple[list[Achado], dict]:
    registos = ler_registo(raiz, hoje)
    try:
        politica, _proprios = ler_politica(raiz)
    except PoliticaInvalida as excepcao:
        raise ConfiguracaoInvalida(str(excepcao)) from excepcao
    try:
        bloqueio = blocklist_mod.load_entries(raiz / "tools" / "blocklist.yaml")
    except (ValueError, OSError) as excepcao:
        raise ConfiguracaoInvalida(str(excepcao)) from excepcao
    inventario = imagens_mod.ler_inventario(raiz, hoje)
    em_uso = _em_uso(raiz, inventario)

    achados: list[Achado] = []

    def achado(regra: str, mensagem: str) -> None:
        achados.append(Achado(regra, REGISTO, 0, mensagem))

    adrs = adr_mod.existentes(raiz)
    for em_falta in sorted(OBRIGATORIOS - {registo.componente for registo in registos}):
        achado(
            "componente-obrigatorio-em-falta",
            f"`{em_falta}` tem de ter linha no registo (edicao Enterprise a registar, "
            "decisao aberta, ou componente de uma imagem em uso). Apagar a linha "
            "nao apaga a exigencia.",
        )

    for registo in registos:
        nome = registo.componente
        # A decisao aberta trava o componente **e o que ele liga**: rebaptizar o
        # Redis de `kv-fila` e manter `imagem:redis` nao o destrava.
        identidade = " ".join([nome] + [alvo for _, alvo in registo.ligacoes])
        veredicto, razao = spdx.classificar_pacote(identidade, registo.licenca, politica)
        if registo.estado not in ADMITIDOS[veredicto]:
            achado(
                "licenca-estado-incoerente",
                f"`{nome}`: a licenca `{registo.licenca}` e **{veredicto}** pela "
                f"politica de ci/licenses.yaml ({razao}), e o registo diz "
                f"`{registo.estado}`. Estados admitidos: {', '.join(ADMITIDOS[veredicto])}.",
            )
        if registo.estado == PENDENTE:
            decisoes = {d for p, d, _ in politica.pendentes if p in identidade.lower()}
            if not _DECISAO.match(registo.decisao) or (decisoes and registo.decisao not in decisoes):
                achado(
                    "licenca-estado-incoerente",
                    f"`{nome}`: `pendente_de_decisao` exige `decisao` com a decisao "
                    f"aberta que o trava ({', '.join(sorted(decisoes)) or 'D#'}).",
                )
        if registo.estado == EXCEPCAO and (
            not _ADR.match(registo.excepcao_adr)
            or registo.excepcao_adr not in adrs
            or len(registo.nota) < 40
        ):
            achado(
                "licenca-sem-excepcao",
                f"`{nome}`: `excepcao` exige `excepcao_adr` com um ADR **que exista** "
                f"({adr_mod.ARQUITECTURA} §8 ou {adr_mod.LOCAIS}/; lido "
                f"{registo.excepcao_adr!r}) e uma `nota` com a leitura que o ADR faz. "
                "Uma aprovacao datada nao chega: o criterio pede excepcao registada em ADR.",
            )
        if registo.estado == NAO_ADOPTADO and not registo.ligacoes:
            achado(
                "nao-adoptado-sem-ligacoes",
                f"`{nome}` esta `nao_adoptado` e nao diz como apareceria no repositorio "
                "(`ligacoes`). Sem isso, a sua ausencia nao se verifica.",
            )
        if registo.estado == BLOQUEADO:
            candidatos = [nome] + [alvo for _, alvo in registo.ligacoes]
            if not any(
                entrada.matches_name(candidato, "any")
                for entrada in bloqueio for candidato in candidatos
            ):
                achado(
                    "bloqueado-fora-da-lista",
                    f"`{nome}` esta registado como `bloqueado` e tools/blocklist.yaml "
                    "nao o bloqueia. O registo descreve o controlo; nao o substitui.",
                )
        if nome in COM_EDICAO_ENTERPRISE and len(registo.ee) < 20:
            achado(
                "ee-sem-registo",
                f"`{nome}` tem edicao Enterprise no mesmo repositorio (E4 §1): o "
                "campo `ee` tem de dizer que partes sao e ficam desligadas.",
            )
        for tipo, alvo in registo.ligacoes:
            chave = (tipo, names.canonical_pypi(alvo) if tipo == "pypi" else alvo.lower())
            if chave not in em_uso:
                continue
            if registo.estado in (BLOQUEADO, NAO_ADOPTADO):
                achado(
                    "componente-presente-sem-aprovacao",
                    f"`{nome}` esta registado como `{registo.estado}` e `{tipo}:{alvo}` "
                    "esta no repositorio. Ou sai, ou o registo passa a dizer com que "
                    "licenca e com que decisao entrou.",
                )
                continue
            diferentes = sorted(
                v for v in em_uso[chave] if not _mesma_versao(tipo, v, registo.versao)
            )
            if diferentes:
                achado(
                    "licenca-versao-diferente",
                    f"`{nome}`: a licenca foi lida para a versao {registo.versao} e o "
                    f"repositorio usa {', '.join(diferentes)} (`{tipo}:{alvo}`). Releia "
                    "a licenca dessa versao e actualize `versao` e `data_verificacao`.",
                )

    conhecidos = {registo.componente for registo in registos}
    for entrada in inventario.entradas:
        for componente in entrada.componentes:
            if componente not in conhecidos:
                achados.append(
                    Achado(
                        "componente-sem-licenca", imagens_mod.INVENTARIO, 0,
                        f"a imagem `{entrada.nome}` declara o componente `{componente}`, "
                        f"que nao tem linha em {REGISTO}.",
                    )
                )

    contagem = {estado: sum(1 for r in registos if r.estado == estado) for estado in ESTADOS}
    return achados, {"componentes": len(registos), "estados": contagem}
