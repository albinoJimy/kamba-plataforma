"""A porta fechada antes de qualquer áudio sair para um fornecedor (KAM-107).

O critério 2 do bloco exige, **antes de enviar áudio**: consentimento escrito de
cada falante (incluindo o envio a um fornecedor nos EUA); a definição de
retenção e não-treino do fornecedor verificada e registada (`E3` req. 8); e a
pergunta **X1** do KAM-104 respondida, ou o risco aceite por escrito. O *handoff*
repete-o: «não envies áudio sem confirmação do consentimento e da resposta X1».

Este módulo é essa frase em código, e falha fechado: um ficheiro de autorização
que falte, que não se leia, ou a que falte uma linha recusa **todos** os envios,
e a recusa diz tudo o que falta de uma vez em vez de o ir revelando.

**Quem escreve o ficheiro é uma pessoa**, e ele vive fora do repositório, ao lado
do arquivo controlado dos consentimentos. Esta sessão não o escreveu e nenhuma o
deve escrever: o que ele afirma são actos humanos — assinaturas, um parecer, uma
aceitação de risco — e uma sessão que o preenchesse estaria a fabricar a prova
que ele existe para exigir.

Forma (JSON)::

    {
      "consentimentos": {"F01": {"data": "2026-12-01", "groq": true, "openai": true}, ...},
      "x1": {"via": "parecer" | "risco_aceite", "referencia": "...", "data": "AAAA-MM-DD",
             "permite_envio": true},
      "fornecedores": {
        "groq": {"retencao_zero": true, "sem_treino": true,
                 "verificado_em": "AAAA-MM-DD", "fonte": "..."},
        ...
      }
    }

O consentimento é **por fornecedor**, como no papel (`consentimento.md` tem uma
caixa para cada envio): um falante que só assinalou a Groq não segue para a
OpenAI. E a X1 leva `permite_envio`, escrito por quem leu o parecer ou aceitou
o risco: um parecer que responda «exige autorização do Art. 34.º» também é uma
X1 respondida, e não abre a porta.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

VIAS_X1 = ("parecer", "risco_aceite")
_FALANTE = re.compile(r"F\d{2}")


class EnvioRecusado(PermissionError):
    def __init__(self, faltas: list[str]) -> None:
        self.faltas = faltas
        super().__init__("envio de áudio recusado: " + "; ".join(faltas))


def _data(valor: object) -> date | None:
    if not isinstance(valor, str):
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return None


@dataclass(frozen=True)
class Autorizacao:
    bruto: Mapping[str, Any]

    @classmethod
    def ler(cls, caminho: Path | str) -> "Autorizacao":
        try:
            dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise EnvioRecusado([f"ficheiro de autorização ilegível ({type(exc).__name__})"]) from None
        if not isinstance(dados, dict):
            raise EnvioRecusado(["ficheiro de autorização sem objecto na raiz"])
        return cls(dados)

    def faltas(self, fornecedor: str, falantes: Iterable[str], hoje: date) -> list[str]:
        faltas: list[str] = []
        consentimentos = self.bruto.get("consentimentos")
        if not isinstance(consentimentos, dict):
            consentimentos = {}
            faltas.append("sem secção de consentimentos")
        for falante in sorted(set(falantes)):
            if not _FALANTE.fullmatch(falante):
                faltas.append(f"falante com identificador que não é pseudónimo: {falante!r}")
                continue
            ficha = consentimentos.get(falante)
            quando = _data(ficha.get("data")) if isinstance(ficha, dict) else None
            if quando is None:
                faltas.append(f"sem consentimento escrito datado para {falante}")
            elif quando > hoje:
                faltas.append(f"consentimento de {falante} com data futura")
            elif ficha.get(fornecedor) is not True:
                faltas.append(f"{falante} não consentiu o envio a {fornecedor}")
        x1 = self.bruto.get("x1")
        if not isinstance(x1, dict):
            faltas.append("X1 do KAM-104 sem resposta nem risco aceite por escrito")
        else:
            if x1.get("via") not in VIAS_X1:
                faltas.append(f"X1: via tem de ser uma de {VIAS_X1}")
            if not isinstance(x1.get("referencia"), str) or not x1["referencia"].strip():
                faltas.append("X1: sem referência do parecer ou do registo de aceitação")
            quando = _data(x1.get("data"))
            if quando is None or quando > hoje:
                faltas.append("X1: sem data válida")
            if x1.get("permite_envio") is not True:
                faltas.append("X1: a resposta ou a aceitação não diz que o envio é permitido")
        fornecedores = self.bruto.get("fornecedores")
        ficha = fornecedores.get(fornecedor) if isinstance(fornecedores, dict) else None
        if not isinstance(ficha, dict):
            faltas.append(f"{fornecedor}: retenção e não-treino por verificar (E3 req. 8)")
        else:
            if ficha.get("retencao_zero") is not True:
                faltas.append(f"{fornecedor}: retenção zero não verificada")
            if ficha.get("sem_treino") is not True:
                faltas.append(f"{fornecedor}: não-treino não verificado")
            quando = _data(ficha.get("verificado_em"))
            if quando is None or quando > hoje:
                faltas.append(f"{fornecedor}: verificação sem data válida")
            if not isinstance(ficha.get("fonte"), str) or not ficha["fonte"].strip():
                faltas.append(f"{fornecedor}: verificação sem fonte")
        return faltas

    def exigir(self, fornecedor: str, falantes: Iterable[str], hoje: date | None = None) -> None:
        lista = list(falantes)
        if not lista:
            raise EnvioRecusado(["nenhum falante no manifesto"])
        faltas = self.faltas(fornecedor, lista, hoje or date.today())
        if faltas:
            raise EnvioRecusado(faltas)
