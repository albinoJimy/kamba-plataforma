"""ISO-11..32 e o lado Medusa do AC-3 — corre `medusa exec` e le o que saiu.

Tudo o que interroga o Medusa corre **dentro** do contentor, por tres razoes que
nao sao preferencia:

1. o Medusa nao publica porta nenhuma no anfitriao, e o AC-2 exige-o;
2. o *query graph* e o Inventory Module nao sao superficies HTTP — vivem no
   processo, e `medusa exec` da acesso ao contentor de dependencias;
3. a prova de sobrevenda pelo caminho do Medusa tem de chamar o servico de
   inventario e o Locking Module, que sao JavaScript.

O guiao e `medusa/src/scripts/spike.ts`. Este ficheiro so o lanca e traduz o
JSON em casos da matriz. Nao duplica nenhuma decisao: se o guiao nao escreveu um
caso, o caso fica NAO VERIFICADO com a razao.
"""

from __future__ import annotations

import json
from pathlib import Path

import contentor
from iso import FALHA, NAO_VERIFICADO, PASSA, Caso

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI / "resultados"

#: Memoria da execucao do guiao: corre uma vez e serve os tres grupos de casos.
_CORRIDO: dict | None = None


def correr_guiao(contentor_medusa: str, tenants: dict, tentativas: int = 1000) -> dict:
    """Corre `medusa exec ./src/scripts/spike.ts` no contentor do Medusa.

    Devolve `{"iso": [...], "ac3": {...}, "erro": str | None}`.
    """
    global _CORRIDO
    if _CORRIDO is not None:
        return _CORRIDO

    SAIDA.mkdir(parents=True, exist_ok=True)
    for nome in ("medusa-iso.json", "medusa-ac3.json"):
        alvo = SAIDA / nome
        if alvo.exists():
            alvo.unlink()

    mapa = {
        rotulo: {"tenant_id": t.tenant_id, "merchant_id": t.merchant_id}
        for rotulo, t in tenants.items()
    }
    resultado = contentor.docker(
        "exec",
        "--env", f"KAMBA_SPIKE_TENANTS={json.dumps(mapa)}",
        "--env", f"KAMBA_SPIKE_TENTATIVAS={tentativas}",
        "--env", "KAMBA_SPIKE_SAIDA=/saida",
        contentor_medusa,
        "./node_modules/.bin/medusa", "exec", "./src/scripts/spike.ts",
        tempo=1200,
    )
    registo = (resultado.stdout or "") + (resultado.stderr or "")
    (SAIDA / "medusa-exec.log").write_text(registo, encoding="utf-8")

    iso = ac3 = None
    if (SAIDA / "medusa-iso.json").is_file():
        iso = json.loads((SAIDA / "medusa-iso.json").read_text(encoding="utf-8"))
    if (SAIDA / "medusa-ac3.json").is_file():
        ac3 = json.loads((SAIDA / "medusa-ac3.json").read_text(encoding="utf-8"))

    erro = None
    if iso is None:
        erro = (
            f"`medusa exec` saiu com {resultado.returncode} e nao escreveu "
            f"`medusa-iso.json`. Registo em {SAIDA / 'medusa-exec.log'}; "
            f"ultimas linhas: {registo.strip()[-600:]}"
        )
    _CORRIDO = {"iso": iso or [], "ac3": ac3, "erro": erro,
                "codigo": resultado.returncode}
    return _CORRIDO


def _casos(medidos: list[dict], cenarios: list[tuple[str, str]], superficie: str,
           esperado: str, erro: str | None) -> list[Caso]:
    """Traduz o que o guiao mediu em casos da matriz.

    **Confere que os dois lados falam do mesmo caso.** O cenario esta escrito
    duas vezes — em `iso.py`, que declara a matriz, e em `spike.ts`, que a mede
    — e sem esta conferencia o do TypeScript vencia em silencio: um caso podia
    passar a medir outra coisa e o relatorio imprimia o cenario novo como se
    fosse o da matriz do §4.4. Uma divergencia e um caso **nao verificado**,
    porque nao se sabe qual dos dois e a matriz.
    """
    por_id = {registo["id"]: registo for registo in medidos}
    saida: list[Caso] = []
    for identificador, cenario in cenarios:
        registo = por_id.get(identificador)
        if registo is None:
            saida.append(Caso(
                identificador, superficie, cenario, esperado, NAO_VERIFICADO,
                "nao medido",
                erro or "o guiao correu mas nao reportou este caso"))
            continue
        medido = (registo.get("cenario") or "").strip()
        if medido and _normalizar(medido) != _normalizar(cenario):
            saida.append(Caso(
                identificador, superficie, cenario, esperado, NAO_VERIFICADO,
                "cenario divergente entre a matriz e o guiao",
                f"`iso.py` declara {cenario!r} e `spike.ts` mediu {medido!r}. "
                "Nao se conta um caso cujo conteudo nao se sabe qual e."))
            continue
        saida.append(Caso(
            identificador, registo.get("superficie", superficie),
            cenario, registo.get("esperado", esperado),
            registo["estado"], registo["observado"], registo.get("evidencia", ""),
        ))
    return saida


def _normalizar(texto: str) -> str:
    """Compara cenarios sem tropecar em espacos nem em quebras de linha."""
    return " ".join(texto.split())


def iso_store(ambiente, tenants, cenarios, contentor_medusa=None) -> list[Caso]:
    dados = correr_guiao(contentor_medusa, tenants)
    return _casos(dados["iso"], cenarios, "API Store do Medusa",
                  "negado ou vazio", dados["erro"])


def iso_admin(ambiente, tenants, cenarios, contentor_medusa=None) -> list[Caso]:
    dados = correr_guiao(contentor_medusa, tenants)
    return _casos(dados["iso"], cenarios, "API Admin do Medusa",
                  "inacessivel (AC-2); com acesso operador, auditado",
                  dados["erro"])


def iso_query_graph(ambiente, tenants, cenarios, contentor_medusa=None) -> list[Caso]:
    dados = correr_guiao(contentor_medusa, tenants)
    return _casos(dados["iso"], cenarios, "query graph / modulos",
                  "filtro imposto pelo COM", dados["erro"])


def sobrevenda(tenants, contentor_medusa: str) -> dict:
    """O lado Medusa do AC-3: os numeros dos dois caminhos do Inventory Module."""
    dados = correr_guiao(contentor_medusa, tenants)
    if dados["ac3"] is None:
        return {
            "erro": dados["erro"] or (
                "o guiao nao escreveu `medusa-ac3.json`; a atomicidade da "
                "reserva do Inventory Module continua NAO VERIFICADA por "
                "execucao nesta corrida"
            )
        }
    return dados["ac3"]
