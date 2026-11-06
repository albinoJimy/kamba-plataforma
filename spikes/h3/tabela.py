"""A tabela N1-N3 a partir dos JSON-lines (KAM-100).

O criterio 2 do ticket pede doze colunas por numero. **Sete sao mensuraveis a
partir dos eventos; cinco nao sao**, e a distincao e o que este modulo entrega:

| Coluna | De onde vem |
|---|---|
| `FINISH_..._ONBOARDING` recebido | `account_update` com esse `evento` |
| `history` recebido ou erro 2593109 | linhas `history`, e o `error_code` delas |
| n.o de contactos em `smb_app_state_sync` | soma dos `contactos` |
| tempo de sincronizacao (< 24 h) | do `FINISH` a ultima linha de sincronizacao |
| latencia do eco (mediana de 10 envios) | mediana de `recebido_em - carimbo` nos ecos |
| uma mensagem da API gera eco | `enviada_por_nos` em algum eco |
| eventos `account_update` | as linhas desse tipo, por `evento` |
| operadora (Unitel, Africell, fixo) | **a folha do operador** |
| tipo (movel ou fixo) | **a folha do operador** |
| versao da app (>= 2.24.17) | **a folha do operador** |
| janela de 24 h aberta apos resposta do cliente | **a folha do operador** |
| metodo de verificacao (SMS ou voz) | **a folha do operador** |

As cinco de baixo sairiam de uma pessoa a olhar para um telefone, e nenhum
webhook as traz. Este modulo escreve-as como `NAO MEDIDO` — nunca em branco e
nunca com um valor plausivel. Um «Unitel» inventado na coluna da operadora
passava por medicao e nao era.

## Um zero nao e um «nao»

A regra que esta tabela obedece, e que custou achados noutro ticket: **zero
eventos de um tipo escreve-se `NAO MEDIDO`, e nao `N`**. «Nao recebi o `FINISH`»
e «nao liguei o receptor a tempo» produzem os mesmos zero eventos e tem
conclusoes opostas — a primeira refuta H3 para aquele numero, a segunda nao diz
nada. `S` afirma-se; `N` so se escreve quando ha prova de ausencia, que neste
spike nao existe para nenhuma destas colunas.

A excepcao e a coluna do eco da API, que tem prova de ausencia disponivel: se
houve ecos **e** nenhum deles e nosso, isso e um `N` medido.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

#: O evento final do ES v4 de coexistencia (`E1` §2, CONFIRMADO).
FINISH = "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"

#: «O cliente nao partilhou historico» (`E1` §2, CONFIRMADO). Caso **normal**, e
#: nao falha — mas so conta como exito de H3 se o dono recusou partilhar, o que
#: e uma afirmacao da folha do operador e nao destes eventos.
SEM_HISTORICO = 2593109

#: O prazo duro da Meta: contactos e historico em 24 h apos o onboarding (`E1`
#: §2, CONFIRMADO). Passado isso o cliente tem de ser offboarded e refazer o ES.
PRAZO_DE_SINCRONIZACAO_S = 24 * 60 * 60

#: Os rotulos esperados. Tres numeros, pelo criterio da amostra.
ROTULOS = ("N1", "N2", "N3")

#: O que se escreve onde nao houve medicao. Em maiusculas e por extenso, para
#: que ninguem o leia como um valor.
NAO_MEDIDO = "NAO MEDIDO"

#: As linhas de sincronizacao, para o calculo do prazo de 24 h.
TIPOS_DE_SINCRONIZACAO = ("history", "smb_app_state_sync")

#: Quantos envios o criterio pede para a mediana da latencia do eco.
ENVIOS_PEDIDOS = 10


class RegistoInvalido(ValueError):
    """Uma linha do JSON-lines nao se pode ler, ou nao tem rotulo de numero."""


def ler(caminho: Path) -> list[dict[str, Any]]:
    """As linhas do JSON-lines. Uma linha ilegivel levanta, nao se salta.

    Saltar uma linha ilegivel faz a tabela sair com menos eventos e sem o dizer,
    o que e a forma de erro que esta tabela existe para nao ter: uma contagem
    mais baixa muda a conclusao de H3.
    """
    saida: list[dict[str, Any]] = []
    with caminho.open(encoding="utf-8") as f:
        for numero, texto in enumerate(f, start=1):
            texto = texto.strip()
            if not texto:
                continue
            try:
                linha = json.loads(texto)
            except json.JSONDecodeError as e:
                raise RegistoInvalido(f"{caminho}:{numero}: nao e JSON ({e.msg})") from e
            if not isinstance(linha, dict):
                raise RegistoInvalido(f"{caminho}:{numero}: nao e um objecto")
            saida.append(linha)
    return saida


def _instante(valor: Any) -> dt.datetime | None:
    """Um `recebido_em` como instante, ou `None`."""
    if type(valor) is not str:
        return None
    try:
        return dt.datetime.strptime(valor, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError:
        pass
    try:
        return dt.datetime.strptime(valor, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError:
        return None


def _por_numero(linhas: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """As linhas agrupadas por rotulo. Uma linha sem rotulo levanta.

    Uma linha sem `numero` nao se pode atribuir a nenhum dos tres, e atribui-la
    ao primeiro, ou descarta-la, era inventar a amostra.
    """
    grupos: dict[str, list[Mapping[str, Any]]] = {r: [] for r in ROTULOS}
    for i, linha in enumerate(linhas, start=1):
        rotulo = linha.get("numero")
        if rotulo not in grupos:
            raise RegistoInvalido(
                f"linha {i}: `numero` e {rotulo!r} e nao um de {ROTULOS}. Sem "
                "rotulo o evento nao se atribui a nenhum numero da amostra — "
                "confirme o `rotulos.json` do receptor"
            )
        grupos[rotulo].append(linha)
    return grupos


def _sim_ou_nao_medido(houve: bool) -> str:
    """`S` quando se viu; `NAO MEDIDO` quando nao — nunca `N`. Ver a nota."""
    return "S" if houve else NAO_MEDIDO


def _finish(linhas: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for l in linhas:
        if l.get("tipo") == "account_update" and l.get("evento") == FINISH:
            return l
    return None


def _sincronizacao(linhas: list[Mapping[str, Any]]) -> tuple[str, bool | None]:
    """O tempo do `FINISH` a ultima linha de sincronizacao, e se cumpre as 24 h.

    Devolve `(texto, cumpre)`. `cumpre` e `None` quando nao se mediu — o que e
    diferente de `False`, e a tabela mostra a diferenca.
    """
    inicio = _finish(linhas)
    if inicio is None:
        return (NAO_MEDIDO + " (sem FINISH)", None)
    arranque = _instante(inicio.get("recebido_em"))
    if arranque is None:
        return (NAO_MEDIDO + " (FINISH sem carimbo legivel)", None)
    fins = [
        i
        for l in linhas
        if l.get("tipo") in TIPOS_DE_SINCRONIZACAO
        and (i := _instante(l.get("recebido_em"))) is not None
    ]
    if not fins:
        return (NAO_MEDIDO + " (nenhum history nem state_sync)", None)
    segundos = (max(fins) - arranque).total_seconds()
    horas = segundos / 3600
    cumpre = segundos <= PRAZO_DE_SINCRONIZACAO_S
    marca = "< 24 h" if cumpre else "**> 24 h**"
    return (f"{horas:.1f} h ({marca})", cumpre)


def _latencia_do_eco(linhas: list[Mapping[str, Any]]) -> str:
    """A mediana de `recebido_em - carimbo` nos ecos, com o n medido.

    O criterio pede «mediana de 10 envios». O n **escreve-se sempre**, porque
    uma mediana de tres envios apresentada como se fosse de dez e o defeito que
    a skill desta casa chama cumprir em espirito e nao a letra.
    """
    atrasos: list[float] = []
    for l in linhas:
        if l.get("tipo") != "smb_message_echoes":
            continue
        recebido = _instante(l.get("recebido_em"))
        carimbo = l.get("carimbo")
        if recebido is None or type(carimbo) is not int:
            continue
        atrasos.append(recebido.timestamp() - carimbo)
    if not atrasos:
        return NAO_MEDIDO + " (0 ecos)"
    mediana = statistics.median(atrasos)
    nota = "" if len(atrasos) >= ENVIOS_PEDIDOS else f", **menos de {ENVIOS_PEDIDOS}**"
    return f"{mediana:.1f} s (n = {len(atrasos)}{nota})"


def _eco_da_api(linhas: list[Mapping[str, Any]]) -> str:
    """Se uma mensagem enviada pela API gera eco (`docs/tecnica/01` §10.3).

    A unica coluna com prova de ausencia: se houve ecos e **nenhum** deles tem
    `wamid` nosso, o `N` e medido. Sem ecos nenhuns, nao se mediu.
    """
    ecos = [l for l in linhas if l.get("tipo") == "smb_message_echoes"]
    if not ecos:
        return NAO_MEDIDO + " (0 ecos)"
    com_marca = [l for l in ecos if type(l.get("enviada_por_nos")) is bool]
    if not com_marca:
        return NAO_MEDIDO + f" ({len(ecos)} eco(s) sem wamid)"
    nossos = sum(1 for l in com_marca if l["enviada_por_nos"])
    if nossos:
        return f"S ({nossos} de {len(com_marca)})"
    return f"N (0 de {len(com_marca)})"


def _historico(linhas: list[Mapping[str, Any]]) -> str:
    """`history` recebido, ou o 2593109, ou nao medido."""
    historias = [l for l in linhas if l.get("tipo") == "history"]
    if not historias:
        return NAO_MEDIDO + " (0 linhas history)"
    sem = [l for l in historias if l.get("error_code") == SEM_HISTORICO]
    mensagens = sum(l.get("mensagens", 0) for l in historias)
    threads = sum(l.get("threads", 0) for l in historias)
    if sem:
        return (
            f"erro {SEM_HISTORICO} ({len(sem)} de {len(historias)} pedaco(s)); "
            f"{mensagens} mensagem(ns) em {threads} conversa(s)"
        )
    return f"S — {mensagens} mensagem(ns) em {threads} conversa(s)"


def _account_update(linhas: list[Mapping[str, Any]]) -> str:
    eventos = [l for l in linhas if l.get("tipo") == "account_update"]
    if not eventos:
        return NAO_MEDIDO + " (0 eventos)"
    partes: list[str] = []
    for l in eventos:
        evento = l.get("evento", "?")
        razao = l.get("razao")
        partes.append(f"`{evento}`" + (f" ({razao})" if razao else ""))
    return ", ".join(partes)


def medir(linhas: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    """As sete colunas mensuraveis, por rotulo, mais as cinco da folha."""
    grupos = _por_numero(linhas)
    saida: dict[str, dict[str, str]] = {}
    for rotulo in ROTULOS:
        suas = grupos[rotulo]
        tempo, _ = _sincronizacao(suas)
        saida[rotulo] = {
            "operadora": NAO_MEDIDO + " (folha)",
            "tipo": NAO_MEDIDO + " (folha)",
            "versao_da_app": NAO_MEDIDO + " (folha)",
            "finish": _sim_ou_nao_medido(_finish(suas) is not None),
            "historico": _historico(suas),
            "contactos": _contactos(suas),
            "sincronizacao": tempo,
            "latencia_do_eco": _latencia_do_eco(suas),
            "eco_da_api": _eco_da_api(suas),
            "janela_de_24h": NAO_MEDIDO + " (folha)",
            "account_update": _account_update(suas),
            "verificacao": NAO_MEDIDO + " (folha)",
            "eventos": str(len(suas)),
        }
    return saida


def _contactos(linhas: list[Mapping[str, Any]]) -> str:
    sincronias = [l for l in linhas if l.get("tipo") == "smb_app_state_sync"]
    if not sincronias:
        return NAO_MEDIDO + " (0 linhas state_sync)"
    return str(sum(l.get("contactos", 0) for l in sincronias))


#: O cabecalho da tabela, pela ordem do criterio 2 do ticket.
COLUNAS = (
    ("operadora", "Operadora"),
    ("tipo", "Tipo"),
    ("versao_da_app", "Versao da app (>= 2.24.17)"),
    ("verificacao", "Verificacao"),
    ("finish", "FINISH recebido"),
    ("historico", "`history` ou 2593109"),
    ("contactos", "Contactos em `smb_app_state_sync`"),
    ("sincronizacao", "Tempo de sincronizacao"),
    ("latencia_do_eco", "Latencia do eco (mediana)"),
    ("eco_da_api", "Mensagem da API gera eco"),
    ("janela_de_24h", "Janela de 24 h"),
    ("account_update", "`account_update`"),
    ("eventos", "Eventos no registo"),
)


def em_markdown(medicao: Mapping[str, Mapping[str, str]]) -> str:
    """A tabela em Markdown, uma coluna por numero.

    Transposta de proposito — uma linha por propriedade e nao por numero: sao
    treze propriedades e tres numeros, e a forma larga nao cabe numa linha de
    texto de 100 colunas.
    """
    linhas = ["| Propriedade | " + " | ".join(ROTULOS) + " |", "|---|" + "---|" * len(ROTULOS)]
    for chave, titulo in COLUNAS:
        celulas = [medicao.get(r, {}).get(chave, NAO_MEDIDO) for r in ROTULOS]
        linhas.append(f"| {titulo} | " + " | ".join(celulas) + " |")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tabela",
        description="A tabela N1-N3 do spike H3 a partir dos JSON-lines (KAM-100).",
    )
    p.add_argument("jsonl", help="o ficheiro de eventos")
    p.add_argument("--json", action="store_true", help="saida em JSON em vez de Markdown")
    a = p.parse_args(argv)

    caminho = Path(a.jsonl)
    if not caminho.is_file():
        print(f"ERRO: {caminho} nao existe", file=sys.stderr)
        return 2
    try:
        medicao = medir(ler(caminho))
    except RegistoInvalido as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1

    if a.json:
        print(json.dumps(medicao, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(em_markdown(medicao))
        vazias = sum(
            1
            for r in ROTULOS
            for chave, _ in COLUNAS
            if medicao[r][chave].startswith(NAO_MEDIDO)
        )
        print(
            f"\n{vazias} celula(s) em `{NAO_MEDIDO}` de "
            f"{len(ROTULOS) * len(COLUNAS)}. As da folha do operador preenchem-se "
            "a mao; as outras significam que o evento nao chegou."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
