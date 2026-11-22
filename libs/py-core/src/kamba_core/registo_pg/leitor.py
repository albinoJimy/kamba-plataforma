"""A leitura do registo do PostgreSQL: seguir os ficheiros e reconhecer a recusa.

**O formato e o `jsonlog` do PostgreSQL 15+**, uma linha JSON por entrada, que o
servidor escreve em `log_directory` quando o `logging_collector` esta ligado (o
`command:` do `postgres` no compose de producao). Medido no PostgreSQL 18.6 da
imagem do compose (`docs/evidencia/KAM-225.md`): a recusa de um `UPDATE` do
`kamba_app` sobre o tecto sai assim, com os campos por esta ordem —

    {"timestamp":..., "user":"kamba_app", "dbname":..., "pid":..., ...,
     "error_severity":"ERROR", "state_code":"42501",
     "message":"permission denied for table trust_level",
     "statement":"update platform.trust_level set ...", ...}

**So se leem tres campos**: `user`, `state_code` e `message`. O `statement` traz o
texto da consulta, com literais — o compose desliga-o (`log_min_error_statement=panic`),
mas o leitor nao conta com isso —, e o `detail` de alguns erros traz valores da
entrada; nada disso sai deste processo, vai para uma serie ou se regista (Detalhes
Tecnicos do KAM-225).

**O predicado** e o do `packages/core-ts/src/tenant_guard/metricas.ts`, mais o
papel: `state_code == "42501"`, a mensagem a nomear `trust_level` (o nome da
tabela nao se traduz com o `lc_messages`, a frase sim), e um `user` que nao e o
`kamba_batch` — o criterio 1 pede a recusa «por um papel que nao e o
`kamba_batch`». O `user` do `jsonlog` e o **utilizador da sessao**: um
`SET ROLE` depois de ligar nao o muda.

**Uma linha comprida nao esconde a recusa.** Quem tem a credencial do
`kamba_app` escolhe o tamanho do `statement`, e um tecto de memoria que
descartasse a linha inteira era uma forma de passar sem contar. Por isso uma
linha acima de `LINHA_MAXIMA` nao se descarta: guarda-se a cabeca e le-se por
expressao regular, porque o PostgreSQL escreve o `user`, o `state_code` e a
`message` **antes** do `statement` (a ordem fixa do `write_jsonlog`, medida).

**Comeca no fim.** Ao arrancar, cada ficheiro que ja existe fica na posicao em
que esta, e so conta o que se escrever depois: um reinicio do processo nao
reconta as recusas das ultimas 24 h (o contador volta a zero, e o `increase`
le-o como reinicio, sem disparar). O preco e dito no bloco do KAM-225: uma
recusa escrita enquanto o processo esta em baixo nao conta. Um ficheiro que
aparece depois do arranque le-se desde o inicio.

**A rotacao trunca e reescreve o mesmo nome** (`log_truncate_on_rotation`,
`postgresql-%H.json`): um ficheiro que encolheu, ou cuja cabeca mudou, volta a
ler-se do zero.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: O SQLSTATE da recusa por privilegio (`insufficient_privilege`).
SQLSTATE_PRIVILEGIO: Final = "42501"

#: O unico papel que escreve o tecto (KAM-096). A recusa dele nao conta aqui.
PAPEL_DO_LOTE: Final = "kamba_batch"

#: O nome da tabela, como o PostgreSQL o escreve na mensagem.
TABELA_DO_TECTO: Final = re.compile(r"\btrust_level\b")

#: O sufixo dos ficheiros do `jsonlog`. O `.log` ao lado e o `stderr` do
#: arranque, antes de o colector tomar conta, e nao se le.
SUFIXO: Final = ".json"

#: Bytes. Uma linha ate aqui le-se com `json.loads`; acima, so a cabeca.
LINHA_MAXIMA: Final = 64 * 1024

#: Bytes do inicio de cada ficheiro que o identificam: se mudarem, foi reescrito.
ASSINATURA: Final = 256

#: Bytes lidos de cada vez.
BLOCO: Final = 64 * 1024

#: Os tres campos que se leem, e nenhum outro.
CAMPOS: Final = ("user", "state_code", "message")

#: Um campo de cadeia no JSON cru. As aspas dentro de um valor vem escapadas
#: (`\"`), pelo que `"user":"` so casa a chave.
_CAMPO_CRU: Final = {
    nome: re.compile(rb'"' + nome.encode("ascii") + rb'":"((?:[^"\\]|\\.)*)"') for nome in CAMPOS
}


def campos(linha: bytes, truncada: bool = False) -> dict[str, str]:
    """Os tres campos de uma linha, os que existirem. `{}` se ela nao se le.

    `truncada` diz que a linha e so a cabeca de uma linha maior que
    `LINHA_MAXIMA`: nao e JSON valido, e os campos leem-se por expressao.
    """
    if not truncada:
        try:
            registo = json.loads(linha)
        except ValueError:
            return {}
        if not isinstance(registo, dict):
            return {}
        return {nome: registo[nome] for nome in CAMPOS if isinstance(registo.get(nome), str)}
    achados: dict[str, str] = {}
    for nome, padrao in _CAMPO_CRU.items():
        casou = padrao.search(linha)
        if casou is None:
            continue
        try:
            valor = json.loads(b'"' + casou.group(1) + b'"')
        except ValueError:
            continue
        achados[nome] = valor
    return achados


def e_recusa_no_tecto(registo: dict[str, str]) -> bool:
    """Um `42501` que nomeia `trust_level`, a um papel que nao e o `kamba_batch`."""
    return (
        registo.get("state_code") == SQLSTATE_PRIVILEGIO
        and TABELA_DO_TECTO.search(registo.get("message", "")) is not None
        and registo.get("user") != PAPEL_DO_LOTE
    )


@dataclass
class _Ficheiro:
    posicao: int
    assinatura: bytes
    resto: bytes = b""
    #: Verdadeiro enquanto se descarta o fim de uma linha acima do tecto (ou o
    #: fim da linha a meio no arranque).
    a_descartar: bool = False


class Seguidor:
    """Segue os `*.json` de uma pasta, e devolve as linhas completas novas.

    Levanta se a pasta nao se le: um recolector que nao ve o registo tem de
    falhar alto, e nao ficar a servir zero.
    """

    def __init__(self, pasta: Path) -> None:
        self._pasta = Path(pasta)
        self._ficheiros: dict[str, _Ficheiro] = {}
        for nome in self.nomes():
            caminho = self._pasta / nome
            try:
                with open(caminho, "rb") as f:
                    tamanho = os.fstat(f.fileno()).st_size
                    assinatura = f.read(ASSINATURA)
                    ultimo = b"\n"
                    if tamanho > 0:
                        f.seek(tamanho - 1)
                        ultimo = f.read(1)
            except FileNotFoundError:
                continue
            # A meio de uma linha, o fim dela descarta-se: le-la como linha
            # inteira dava um fragmento.
            self._ficheiros[nome] = _Ficheiro(tamanho, assinatura, a_descartar=ultimo != b"\n")

    def nomes(self) -> list[str]:
        """Os ficheiros do `jsonlog` da pasta, por ordem de nome."""
        return sorted(n for n in os.listdir(self._pasta) if n.endswith(SUFIXO))

    def idade(self, agora: float) -> float:
        """Segundos desde a ultima modificacao do `*.json` mais novo; `inf` sem nenhum."""
        mais_novo = None
        for nome in self.nomes():
            try:
                instante = os.stat(self._pasta / nome).st_mtime
            except FileNotFoundError:
                continue
            mais_novo = instante if mais_novo is None else max(mais_novo, instante)
        return math.inf if mais_novo is None else agora - mais_novo

    def linhas(self) -> Iterator[tuple[bytes, bool]]:
        """`(linha, truncada)` de cada linha completa escrita desde a ultima chamada."""
        for nome in self.nomes():
            try:
                f = open(self._pasta / nome, "rb")
            except FileNotFoundError:
                self._ficheiros.pop(nome, None)
                continue
            with f:
                tamanho = os.fstat(f.fileno()).st_size
                cabeca = f.read(ASSINATURA)
                estado = self._ficheiros.get(nome)
                if (
                    estado is None
                    or tamanho < estado.posicao
                    or not cabeca.startswith(estado.assinatura)
                ):
                    estado = _Ficheiro(0, cabeca)
                    self._ficheiros[nome] = estado
                elif len(cabeca) > len(estado.assinatura):
                    estado.assinatura = cabeca
                f.seek(estado.posicao)
                while True:
                    dados = f.read(BLOCO)
                    if not dados:
                        break
                    estado.posicao += len(dados)
                    yield from _consumir(estado, dados)


def _consumir(estado: _Ficheiro, dados: bytes) -> Iterator[tuple[bytes, bool]]:
    while dados:
        fim = dados.find(b"\n")
        if estado.a_descartar:
            if fim < 0:
                return
            estado.a_descartar = False
            dados = dados[fim + 1 :]
            continue
        if fim < 0:
            estado.resto += dados
            if len(estado.resto) > LINHA_MAXIMA:
                # Acima do tecto: a cabeca le-se uma vez, e o resto da linha
                # descarta-se sem o guardar.
                yield estado.resto[:LINHA_MAXIMA], True
                estado.resto = b""
                estado.a_descartar = True
            return
        linha = estado.resto + dados[:fim]
        estado.resto = b""
        dados = dados[fim + 1 :]
        if len(linha) > LINHA_MAXIMA:
            yield linha[:LINHA_MAXIMA], True
        elif linha:
            yield linha, False
