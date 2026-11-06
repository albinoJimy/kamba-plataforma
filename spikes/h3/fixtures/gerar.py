"""Gera as *fixtures* de JSON-lines do spike H3 (KAM-100).

As *fixtures* sao um **artefacto** (`n1_n3.jsonl`) e nao codigo, mas nascem daqui
para serem reproduziveis: um `.jsonl` escrito a mao nao diz que cenario
representa, e um ensaio que falhe sobre ele deixa quem o ler sem saber se o
defeito e do codigo ou da *fixture*.

Tres cenarios, um por numero, escolhidos porque sao os tres que o criterio 2 e o
limiar H3 distinguem:

    N1   nominal        FINISH, `history` com 214 mensagens em 20 conversas,
                        contactos sincronizados, 10 ecos, sincronizacao em 2,0 h
    N2   **erro 2593109**  o dono recusou partilhar historico. Caso **normal**
                        pela Meta (`E1` §2), e so conta como exito de H3 se a
                        folha do operador registar que a recusa foi do dono
    N3   **> 24 h**     a sincronizacao fecha as 26,5 h, fora do prazo duro da
                        Meta. Passado o prazo o cliente tem de ser offboarded e
                        refazer o ES (`E1` §2), e um `account_update` de
                        `PARTNER_REMOVED` com `PRIMARY_INACTIVITY` segue-se

Os dois de baixo sao a razao de haver *fixtures*: sem eles a tabela so se exercita
no caminho feliz, e e exactamente nestes dois que «nao medido» e «nao aconteceu»
se confundem.

## As *fixtures* passam pela `allowlist`, e nao por fora dela

Escrevem-se com `registo.escrever`, o mesmo caminho do receptor. Uma *fixture*
construida a mao podia conter um campo que o receptor nunca produziria, e ai o
ensaio da tabela media uma entrada que nao existe.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registo import escrever  # noqa: E402

#: O inicio do spike, em UTC. Fixo, para que duas geracoes dem o mesmo ficheiro.
INICIO = dt.datetime(2026, 11, 10, 8, 0, 0, tzinfo=dt.timezone.utc)

#: O nome do ficheiro gerado.
DESTINO = Path(__file__).resolve().parent / "n1_n3.jsonl"


def instante(segundos: float) -> str:
    """Um `recebido_em` a tantos segundos do inicio."""
    quando = INICIO + dt.timedelta(seconds=segundos)
    return quando.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def carimbo(segundos: float) -> int:
    """O carimbo Unix do evento, inteiro."""
    return int((INICIO + dt.timedelta(seconds=segundos)).timestamp())


def resumo(semente: str) -> str:
    """Um `id_opaco` estavel para a *fixture*.

    Nao passa por `registo.opaco` com um `wamid` real: as *fixtures* nao tem
    `wamid` nenhum, nem em claro nem resumido de um real. A semente e texto.
    """
    import hashlib

    return "m_" + hashlib.sha256(semente.encode("utf-8")).hexdigest()[:32]


#: Quantos ecos o criterio pede, para a mediana da latencia.
ECOS = 10

#: A latencia de cada eco, em segundos. Constante de proposito: a mediana de dez
#: valores iguais e esse valor, pelo que o ensaio da tabela tem um numero
#: esperado sem ter de replicar a aritmetica da mediana.
LATENCIA_S = 3


def linhas_de_n1() -> list[dict]:
    """O caminho nominal."""
    saida: list[dict] = [
        {
            "tipo": "account_update",
            "numero": "N1",
            "recebido_em": instante(0),
            "evento": "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
        },
        {
            "tipo": "smb_app_state_sync",
            "numero": "N1",
            "recebido_em": instante(1800),
            "fase": "fase_1",
            "contactos": 143,
        },
        {
            "tipo": "history",
            "numero": "N1",
            "recebido_em": instante(5400),
            "fase": "fase_0",
            "chunk_order": 1,
            "progresso": 60,
            "threads": 12,
            "mensagens": 131,
        },
        {
            "tipo": "history",
            "numero": "N1",
            "recebido_em": instante(7200),
            "fase": "fase_0",
            "chunk_order": 2,
            "progresso": 100,
            "threads": 8,
            "mensagens": 83,
        },
    ]
    for k in range(ECOS):
        quando = 10_000 + k * 60
        saida.append(
            {
                "tipo": "smb_message_echoes",
                "numero": "N1",
                "recebido_em": instante(quando + LATENCIA_S),
                "carimbo": carimbo(quando),
                "id": resumo(f"n1-eco-{k}"),
                "direccao": "echo",
                # Nenhum destes e nosso: o eco e do dono, na app. E o `N` medido
                # da coluna do eco da API — ver `tabela._eco_da_api`.
                "enviada_por_nos": False,
            }
        )
    saida.append(
        {
            "tipo": "messages",
            "numero": "N1",
            "recebido_em": instante(11_000),
            "carimbo": carimbo(10_995),
            "id": resumo("n1-entrada-1"),
            "direccao": "entrada",
        }
    )
    return saida


def linhas_de_n2() -> list[dict]:
    """O erro 2593109: o dono recusou partilhar historico."""
    return [
        {
            "tipo": "account_update",
            "numero": "N2",
            "recebido_em": instante(60),
            "evento": "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
        },
        {
            "tipo": "smb_app_state_sync",
            "numero": "N2",
            "recebido_em": instante(900),
            "fase": "fase_1",
            "contactos": 56,
        },
        {
            "tipo": "history",
            "numero": "N2",
            "recebido_em": instante(1200),
            "fase": "fase_0",
            "chunk_order": 1,
            "progresso": 100,
            "threads": 0,
            "mensagens": 0,
            "error_code": 2_593_109,
        },
        # Um eco so: a mediana existe, mas com n = 1. A tabela tem de o dizer, e
        # nao apresentar «3,0 s» como se fossem os dez envios pedidos.
        {
            "tipo": "smb_message_echoes",
            "numero": "N2",
            "recebido_em": instante(5000 + LATENCIA_S),
            "carimbo": carimbo(5000),
            "id": resumo("n2-eco-0"),
            "direccao": "echo",
            "enviada_por_nos": False,
        },
    ]


def linhas_de_n3() -> list[dict]:
    """A sincronizacao fora do prazo de 24 h, e o desligamento que se segue."""
    tarde = 26.5 * 3600
    return [
        {
            "tipo": "account_update",
            "numero": "N3",
            "recebido_em": instante(120),
            "evento": "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING",
        },
        {
            "tipo": "smb_app_state_sync",
            "numero": "N3",
            "recebido_em": instante(3600),
            "fase": "fase_1",
            "contactos": 9,
        },
        {
            "tipo": "history",
            "numero": "N3",
            "recebido_em": instante(tarde),
            "fase": "fase_0",
            "chunk_order": 1,
            # **Progresso parcial**, e nao 100: o pedaco chegou tarde e a
            # sincronizacao nao fechou. Um 100 aqui dizia que terminou.
            "progresso": 40,
            "threads": 3,
            "mensagens": 18,
        },
        {
            "tipo": "account_update",
            "numero": "N3",
            "recebido_em": instante(tarde + 600),
            "evento": "PARTNER_REMOVED",
            "razao": "PRIMARY_INACTIVITY",
        },
        # **Zero ecos** de proposito: a coluna da latencia tem de sair
        # `NAO MEDIDO (0 ecos)` e nao um `0,0 s` que parecia instantaneo.
    ]


def main() -> int:
    if DESTINO.exists():
        DESTINO.unlink()
    total = 0
    for linha in linhas_de_n1() + linhas_de_n2() + linhas_de_n3():
        escrever(DESTINO, linha)
        total += 1
    print(f"{DESTINO.name}: {total} linha(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
