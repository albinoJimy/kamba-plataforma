# `gate_fase0` — instrumentos do gate da Fase 0 (KAM-108)

| Campo | Valor |
|---|---|
| Ticket | KAM-108 — Gate da Fase 0: demonstração do esqueleto andante |
| Fonte | `specs/EPIC-10_Spikes_Validacao_Gates.md` (bloco KAM-108), `docs/tecnica/00_Arquitectura_Solucao.md` §13.2 |
| Evidência | [`Gate_Fase0.md`](../../docs/tecnica/evidencia/validacao/Gate_Fase0.md), [`Gate_Fase0_Decisao.md`](../../docs/tecnica/evidencia/validacao/Gate_Fase0_Decisao.md) |
| Não está ligado a portão nenhum | Por desenho — ver a última secção |

> **A demonstração e o veredicto são humanos.** O bloco di-lo por extenso nos
> «Detalhes Técnicos». Este pacote prepara: o cenário, o traço, as consultas e a
> recolha. Não corre a demonstração, não observa a conversa real e não marca
> caixa nenhuma.

---

## Os seis comandos

Nesta máquina não há `make`, `node` nem `pnpm` (`docs/adr/ADR-L001` §1), e o
`PYTHONPATH` separa-se com `;`. A forma que corre:

```bash
cd tools && PYTHONPATH=. python -m gate_fase0 cenario
```

| Comando | O que faz |
|---|---|
| `cenario` | imprime o guião do operador, **gerado** do `cenario.py` |
| `consulta` | imprime as consultas de leitura que dão os três elos de baixo |
| `traco <ficheiros…>` | a cadeia mensagem → pedido → evento → consumo, por identificadores |
| `ci <corrida.json>` | o estado dos gates do §4 numa execução de CI |
| `reuso <artefacto.json>` | a métrica de reaproveitamento, com a proveniência verificada |
| `decisoes` | as sete linhas do G0-7, com as três invariantes verificadas |

Os códigos de saída são **três**, e separam-se pela razão do KAM-134: `0`
conforme, `1` há achados ou a cadeia tem elos em falta, `2` a entrada ou a
configuração não servem. Um `traceback` por uma entrada que falta sai
indistinguível de «o traço não fechou», e as duas conclusões são opostas.

---

## O traço, e porque é que ele lê duas fontes e não uma

A cadeia **não cabe nos *logs***, e isso mediu-se antes de se escrever código: o
ADR-010 e o `docs/logs.md` §2 fixam uma *allowlist* de doze campos, e
`order_id`, `event_id`, `booking_id` e `conversation_id` não são nenhum deles —
o §2.2 recusa o `contact_id` pelo nome. Dos quatro elos, os *logs* dão o
primeiro e mais nada.

Os outros três leem-se da base, por três consultas de leitura que projectam
**só** identificadores (`consulta.py`). O operador corre-as, guarda as linhas em
JSON-lines, e junta-as aos *logs*:

```bash
cd tools && PYTHONPATH=. python -m gate_fase0 traco ../logs.jsonl ../base.jsonl
```

Três barreiras impedem conteúdo e telefone de sair, e a terceira existe porque as
duas primeiras são código que alguém pode alargar sem reparar:

1. **lista fechada** — uma chave fora dela é descartada e **contada**;
2. **forma do valor** — não o nome da chave: uma guarda por nome fica verde com
   uma mensagem inteira num campo chamado `nota`, `ref` ou `fase` (foi um achado
   de revisão adversarial no KAM-100);
3. **guarda da saída** — os três detectores de telefone sobre o texto todo, e o
   alfabeto estrutural sobre os campos que vêm da entrada.

**Os carimbos não entram como inteiro**, e a razão é o telefone: nove dígitos são
um carimbo Unix **e** um móvel angolano, pelo que um campo `int` aceitaria um
telefone com a forma certa e nenhum detector o apanharia — já tinha passado a
guarda como número.

---

## O controlo negativo, e onde está o telefone que ele usa

O ensaio que vale é o **negativo**: alimenta-se o traço com um *log* que **tem**
conteúdo e telefone e prova-se que a saída não os leva. Um ensaio com entradas
limpas fica verde com todas as guardas apagadas.

O número de forma real **monta-se em execução** e não aparece como literal em
ficheiro nenhum. São duas consequências, as duas deliberadas:

- o detector é exercitado com um número de **forma real**, que é o que importa —
  o `tools/meta-sim/src/inventario.ts` diz por extenso que «um redactor testado
  só com números do `999` nunca prova que apanha um `+244 9…`»;
- a árvore não ganha um literal com forma de telefone, pelo que o varrimento do
  *gate* 7 não muda e o `INVENTARIO` não leva entrada nova. Medido antes e
  depois destes ficheiros: **35 ficheiros e 124 ocorrências**, idênticas ficheiro
  a ficheiro, e iguais ao par fixado do `tools/meta-sim/tests/inventario.test.ts`.

Isto **não** é fugir ao portão: o portão proíbe números reais na árvore, e aqui
não entra nenhum. A alternativa — escrever o número e declará-lo no inventário —
era legítima e tem precedente (KAM-100, cinco ocorrências num ficheiro); não se
tomou porque o inventário recusa entradas mortas, exige contagem exacta, e tem um
par de contagens fixado à mão num ensaio que `pnpm` não corre nesta máquina.

---

## Porque é que as consultas não vivem num ficheiro `.sql`

O `ci/canon-lint.yaml` tem uma **sentinela** para `*.sql` em qualquer sítio: um
`.sql` tem de ser superfície de DDL do *gate* 3b ou estar declarado fora de
âmbito. Estas consultas não são DDL — são leitura —, e declará-las fora de âmbito
era pedir uma dispensa a um portão para um ficheiro que não é do género que ele
verifica. Ficam como texto do `consulta.py`, com ensaio a exigir que nenhuma
projecte uma coluna que leve conteúdo, telefone ou um resumo invertível, nos
**dois** lados: a tupla declarada e o `SELECT` que corre.

---

## O que este pacote **não** faz, para não se contar com isso

- **Não está ligado a portão nenhum.** Ligá-lo a um *job* que trave fusões
  acrescenta um contexto exigido ao *ruleset* da `main`, e isso é alteração de
  regra de bloqueio — decisão do fundador. O KAM-180 e o KAM-039 deixaram o
  mesmo precedente escrito: o ticket entrega o instrumento e a medição, não a
  ligação.
- **Não decide o veredicto.** O `Gate_Fase0_Decisao.md` nasce por preencher, com
  as três assinaturas em branco.
- **Não vai à rede.** A entrada do `ci` é a saída de
  `gh run view <id> --json jobs,headSha,url,conclusion` guardada em ficheiro, para
  que a recolha corra offline, seja reproduzível, e a evidência fique com a
  execução que a produziu em vez de com o estado do painel no instante em que
  alguém olhou.
- **Não corre a demonstração.** Telemóvel → número de teste ou de coexistência,
  nunca simulador, e por quem não escreveu o código. É o passo P0 do cenário e é
  a única parte que não se pode automatizar sem deixar de a provar.
