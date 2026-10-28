"""Modo concierge: a IA rascunha e o humano aprova (KAM-114).

O concierge **nao** e um quinto modo de conversa. O KAM-018 recusa transicoes
fora da tabela de `docs/tecnica/01` §10.2, e os quatro modos (`bot`, `dono`,
`humano`, `pausada`) ficam como estao. E uma **politica por tenant** aplicada a
conversa em modo `bot`: o no de envio e substituido por um pedido de aprovacao.

```text
guard_out --(politica ligada)--> draft_prepare --> draft_wait --> draft_close
                                      |                              |
                               (grava a linha,              (aprovado/editado)
                                publica no HND)                      |
                                                                    send
```

O padrao e o do KAM-034: um no idempotente cria o rascunho e outro **so** faz
`interrupt()`, sem efeitos antes dele.

## A barreira, que e o produto

**Sem decisao humana registada (`aprovado` ou `editado`) nao sai mensagem.** O
rascunho expira as 24 h. Nao se simplifica, e as tres consequencias estao
escritas onde doem:

* o HND em baixo nao faz sair uma mensagem de degradacao — seria uma mensagem
  sem aprovacao (`portas.py`);
* a varredura nao pode escrever `aprovado` — os dominios das duas vias sao
  disjuntos (`servico.py`, `DecisaoDoSistemaInvalidaError`);
* a politica que nao se consegue ler nao vira «desligada» — a excepcao sobe e o
  turno falha, sem enviar nada (`politica.py`).

## Privacidade

`platform.draft_decisions` guarda **hashes, numeros e um booleano**; o texto do
rascunho vive so no checkpointer (`lg`) e no HND. A medida da edicao calcula-se
no `servico.py`, onde o texto entra e **nao sai**: para a tabela atravessa um
`numeric(4, 3)`.

A exportacao `golden-candidates` leva so metadados, e o criterio 7 pede um teste
de esquema que prove **0** campos de texto livre ou de identificador. Os Termos
da Meta §4.7 proibem treinar ou melhorar ML com dados do WhatsApp (ADR-018): o
*golden* recebe reescritas sinteticas, nunca copias.

## Os modulos

| Modulo | O que tem |
|---|---|
| `maquina` | dominios, `draft_id`, a distancia da edicao e o numero livre. Funcoes puras |
| `politica` | a politica por *tenant*, sobre `platform.entitlements` |
| `portas` | `PortaDeRascunho` e `RascunhoIndisponivel` |
| `consultas` | o SQL |
| `rascunho` | abre o rascunho: a linha e a publicacao |
| `servico` | o CAS da decisao, a medida e o `Command(resume=...)` |
| `prazos` | a varredura: o prazo das 24 h e a politica desligada |

**Nada se reexporta daqui**, e isso tem razao medida. O ciclo que o
`metricas.py` contorna com `lru_cache` e *import* tardio e

```text
metricas -> concierge.maquina -> validador.veredicto -> metricas
```

porque a `maquina` usa o `validar` do KAM-032 (o sinal `edicao_numero_livre`
**e** o veredicto de citacao) e o `veredicto.py` conta metricas. Um
`__init__.py` que reexportasse acrescentava um segundo caminho para o mesmo
ciclo e punha-o a disparar em quem importasse o pacote por qualquer razao. Quem
precisa de um nome importa-o do modulo que o define.
"""

from __future__ import annotations

__all__: list[str] = []
