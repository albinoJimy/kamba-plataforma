"""Os nomes que sao *facts* do catalogo do *tenant* e **nao** se mascaram.

E o criterio 5 do KAM-112: «nomes que sao *facts* do catalogo do tenant (marcas,
produtos, recursos e profissionais de Servicos) nao se mascaram (lista lida da
porta `CommerceRegistry`); os restantes nomes proprios viram `PESSOA_n`».

## A porta que o criterio nomeia nao existe, e a que existir nao serve

Duas medicoes, as duas feitas antes de se escrever uma linha deste modulo:

1. **O `CommerceRegistry` nao esta implementado.** E o **KAM-042**, aberto, `L`,
   `P0`, com dependencias `KAM-041` e `KAM-003`. Em codigo ha **uma** ocorrencia
   do nome, num comentario de `services/com/src/app.ts`, onde esta escrito «aqui
   so a sonda». O contrato vive em `docs/tecnica/03` §3.2 e e TypeScript.

2. **O contrato proposto nao tem operacao que devolva uma lista de nomes.** Os
   onze metodos do §3.2 sao `upsertProductDraft`, `publishProduct`,
   `getOfferView(ctx, sku)`, `createOrder`, `requestOwnerConfirmation`,
   `reserveStock`, `extendReservation`, `commitReservation`,
   `releaseReservation`, `transition`, `getOrder`, `listOrders`. O `getOfferView`
   e **por `sku`**: pede o nome de um produto que ja se conhece. Nenhum devolve
   «os nomes deste *tenant*».

Logo o criterio 5 **nao se cumpre a letra hoje, e nao se cumpriria a letra no dia
em que o KAM-042 fundisse** sem lhe acrescentar um metodo. Isso e informacao para
quem escreveu o criterio, nao licenca para marcar a caixa.

## O que se faz, e porque e esta a saida e nao a outra

A escolha era entre deixar a caixa `parcial` sem codigo nenhum, ou definir a
costura. **Define-se a costura**, e a razao e uma medicao e nao uma preferencia:
tres das quatro classes de nome que o criterio enumera **ja existem em tabela
hoje**, com RLS por *tenant*, e o grafo ja le uma delas.

| Classe do criterio 5 | Fonte hoje | Estado |
|---|---|---|
| marcas | `platform.tenants.nome` | **existe**; o grafo ja a le por `get_store_info` (a unica tool `ligada`) |
| recursos e profissionais | `servicos.resources.nome` | **existe** desde o KAM-035 (revisao `0025`) |
| (servicos oferecidos) | `servicos.services.nome` | **existe** desde o KAM-035 |
| produtos | — | **nao existe**: sem tabela e sem porta. KAM-042, KAM-043 |

Deixar a caixa `parcial` sem codigo era deixar por mascarar o que ja se pode nao
mascarar — e o custo de nao ter isto nao e teorico: sem ele, «a Rosa esta
disponivel as 15h?» sobre uma `servicos.resources.nome = 'Rosa'` vira «a
`PESSOA_1` esta disponivel as 15h?», o modelo perde o *fact*, e o validador de
citacao (KAM-032) recusa a resposta. O criterio 5 existe exactamente para
impedir isso, e a parte dele que e possivel hoje e a maior parte.

**O que isto NAO e:** nao e o `CommerceRegistry`, nao se chama
`CommerceRegistry`, e nao decide o contrato dele. E uma porta **do lado do
consumidor**, no AGR, com uma pergunta so — «que nomes deste *tenant* sao
*facts*?» — que e a pergunta que o detector precisa de fazer e que nenhum dos
onze metodos do §3.2 responde. Quando o KAM-042 existir, esta porta passa a ter
um adaptador que fala com ele em vez de falar com as tabelas, e e por isso que
ela e um `Protocol` e nao uma funcao.

```text
HIPOTESE
- Hipotese: uma porta de consumo no AGR, com uma operacao `nomes(tenant_id)`,
  satisfaz a intencao do criterio 5 para marcas, servicos e recursos, e o
  `CommerceRegistry` do KAM-042 vem a substituir a implementacao sem lhe tocar
  na assinatura.
- Evidencia que a sustenta: as tres colunas existem e tem RLS por *tenant*
  (`0001_schema_platform.py`, `0025_servicos.py`); o padrao «porta com *fakes*
  ate ao adaptador real» e o que `EPIC-03` R7 escreve para a TLS e o
  `CommerceRegistry`; o §3.2 nao tem operacao de listagem, pelo que a assinatura
  nao copia nenhuma existente nem a contradiz.
- Estado: NAO VERIFICADO quanto a ser esta a forma que o KAM-042 vai querer —
  nao ha decisao escrita sobre isso em sitio nenhum, medido.
- Como validar: o KAM-042 implementa-a ou substitui-a; a decisao sobre o
  contrato do `CommerceRegistry` e dele e nao deste ticket. A caixa do criterio 5
  fica **parcial** entretanto, porque os **produtos** nao tem fonte.
```

## Zero chamadas a base de dados dentro do `minimise`

Os nomes entram no `minimise` pelo contexto, ja carregados, e nao por uma
consulta. Duas razoes, e a segunda e a que manda:

* o criterio 7 da **p95 <= 30 ms para 2.000 caracteres** (*proposta*), e uma ida
  a base de dados por mensagem nao cabe la;
* uma consulta dentro do `minimise` punha o detector a falhar quando a base
  falhasse — e o criterio 7 manda falhar **fechado**, isto e, sem chamar o LLM.
  Um detector que nao consegue ler o catalogo mascararia o nome da loja e
  **continuaria** a minimizar o resto, o que e correcto e nao e falha; fazer
  disso uma falha fechada parava turnos por uma razao errada.

Quem carrega e o chamador, uma vez por turno. O custo de um nome do catalogo
mascarado por engano quando a leitura falha e um *fact* perdido numa resposta —
que o validador apanha — e nao uma transferencia de dados pessoais.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Final, Protocol

from .dicionarios import dobrar

#: O comprimento minimo de um nome do catalogo para ele contar como protegido.
#:
#: **Um nome de uma ou duas letras nao protege: abre um buraco.** Um *tenant* com
#: um servico chamado «A» fazia qualquer «a» do texto cair na lista de nao
#: mascarar, e com ele os nomes proprios que o contivessem. Tres e o minimo que
#: ainda deixa passar nomes reais curtos («Ana», «Zia») sem transformar a lista
#: numa dispensa geral.
COMPRIMENTO_MINIMO: Final = 3

#: Quantos nomes se aceitam por *tenant*. Acima disto a lista trunca-se.
#:
#: **E uma barreira de custo e nao de correccao**: o detector percorre esta lista
#: por cada candidato, e um *tenant* com dez mil servicos punha o `minimise`
#: muito acima dos 30 ms do criterio 7. Truncar **mascara mais**, nao menos —
#: falha para o lado seguro.
#:
#: *Proposta*: calibra-se no Piloto (KAM-109), onde se sabe quantos servicos uma
#: PME tem de verdade.
#:
#: shortcut: tecto de 2.000 nomes por tenant, que trunca e mascara mais em vez de
#: exceder o tecto de latencia; revê-se no KAM-109 com catalogos reais.
MAXIMO_DE_NOMES: Final = 2_000


class PortaDeCatalogo(Protocol):
    """Os nomes que sao *facts* do catalogo de um *tenant*.

    Uma operacao, e e a que o criterio 5 precisa e que o `CommerceRegistry` do
    §3.2 nao tem. **Credor: KAM-042** — quem implementar a porta canonica
    substitui o adaptador desta, nao esta assinatura.
    """

    def nomes(self, tenant_id: str) -> frozenset[str]:
        """Os nomes, na forma **dobrada** (`dicionarios.dobrar`).

        Dobrada e nao crua porque a comparacao do detector e dobrada: devolver
        `'Salão da Rosa'` obrigava cada chamador a normalizar, e o primeiro que
        se esquecesse tinha um criterio 5 que nao morde.
        """
        ...


class CatalogoVazio:
    """Nenhum nome e *fact*. O objecto nulo, e e o que a omissao usa.

    E a forma do `SemDegradacao` do `degradacao.py` e do `SemMetricas` do TEN:
    um nulo com a mesma superficie, para que quem consome nao tenha de perguntar
    se a porta existe.

    **Com este catalogo o criterio 5 nao se cumpre, e e o estado por omissao.**
    Nao e um defeito: um *tenant* sem catalogo lido nao tem nomes a proteger, e o
    detector mascara nomes proprios como mascararia sem o criterio 5. O que se
    perde e um *fact*; o que **nao** se perde e um dado pessoal.
    """

    __slots__ = ()

    def nomes(self, tenant_id: str) -> frozenset[str]:  # noqa: ARG002
        return frozenset()


#: As tres consultas, uma por fonte. Separadas e nao unidas por `UNION` de
#: proposito: o esquema `servicos` nasceu no KAM-035 e um *tenant* de uma
#: instalacao sem essa revisao aplicada faz as duas ultimas falharem — e com um
#: `UNION` a falha levava tambem o nome da loja, que e a fonte que existe desde a
#: revisao `0001`. Cada uma falha por si.
#:
#: O `%s` e o estilo do `pg8000` que o resto do AGR usa (`tls/get_store_info.py`).
SQL_MARCA: Final = """
SELECT nome
  FROM platform.tenants
 WHERE id = %s
   AND deleted_at IS NULL
"""

SQL_SERVICOS: Final = """
SELECT nome
  FROM servicos.services
 WHERE tenant_id = %s
   AND ativo
"""

SQL_RECURSOS: Final = """
SELECT nome
  FROM servicos.resources
 WHERE tenant_id = %s
   AND ativo
"""

CONSULTAS: Final = (
    ("marca", SQL_MARCA),
    ("servicos", SQL_SERVICOS),
    ("recursos", SQL_RECURSOS),
)


@dataclasses.dataclass(frozen=True, slots=True)
class CatalogoDoTenant:
    """Le os nomes das tres tabelas que existem hoje. **Implementacao minima.**

    `abrir_ligacao` e a mesma costura do `llm/cliente.py`: uma funcao sem
    argumentos que devolve uma ligacao, para que a bateria possa dar um duplo
    sem levantar um PostgreSQL.

    **Os produtos nao estao aqui porque nao ha de onde os ler** — sem tabela e
    sem porta (KAM-042, KAM-043). E a razao exacta por que a caixa do criterio 5
    fica `parcial`, e nao se finge com um `SELECT` a uma tabela que nao existe.

    **Uma fonte que falhe nao leva as outras**, e nao leva o turno: o que se
    devolve e o que se conseguiu ler. Ver a nota do modulo — um nome do catalogo
    por mascarar e um *fact* perdido, nao uma transferencia.
    """

    abrir_ligacao: Any

    def nomes(self, tenant_id: str) -> frozenset[str]:
        recolhidos: set[str] = set()
        ligacao = None
        try:
            ligacao = self.abrir_ligacao()
            for _fonte, consulta in CONSULTAS:
                try:
                    cursor = ligacao.cursor()
                    cursor.execute(consulta, (tenant_id,))
                    for linha in cursor.fetchall():
                        if not linha:
                            continue
                        dobrado = dobrar(str(linha[0])).strip()
                        if len(dobrado) >= COMPRIMENTO_MINIMO:
                            recolhidos.add(dobrado)
                except Exception:  # noqa: BLE001 — ver a nota da classe
                    # Uma fonte que falha (esquema `servicos` ausente, RLS a
                    # recusar, tabela por criar) nao leva as outras duas. Nao se
                    # conta metrica: o que ficaria visivel era «o catalogo tem
                    # menos nomes», e isso le-se do proprio recall do criterio 3.
                    continue
        except Exception:  # noqa: BLE001 — nao ter ligacao e lista vazia
            return frozenset()
        finally:
            if ligacao is not None:
                try:
                    ligacao.close()
                except Exception:  # noqa: BLE001 — fechar nao pode levantar
                    pass
        if len(recolhidos) > MAXIMO_DE_NOMES:
            # Trunca pelos **mais longos**, que sao os que mais custa perder: um
            # nome longo e mais especifico e menos provavel de colidir com um
            # nome proprio comum. Ordem estavel para que duas chamadas dem o
            # mesmo conjunto.
            ordenados = sorted(recolhidos, key=lambda nome: (-len(nome), nome))
            return frozenset(ordenados[:MAXIMO_DE_NOMES])
        return frozenset(recolhidos)
