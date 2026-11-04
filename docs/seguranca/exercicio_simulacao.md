# Exercício de simulação de incidente (*tabletop*) — guião e acta

| Campo | Valor |
|---|---|
| Ticket | KAM-113 |
| Runbook | [`resposta_incidentes.md`](resposta_incidentes.md) §12 |
| **Estado** | **NÃO REALIZADO.** O guião e a acta-modelo estão prontos; o exercício exige pessoas e uma sessão de 2 h. Credor: o Responsável de Segurança (SEG), que reúne a equipa |
| Quando | **Antes do primeiro tenant com dados reais** (critério do ticket); depois, todos os anos |

> **Este documento não regista nenhum resultado.** Cada quadro «a preencher» fica vazio até a
> sessão acontecer. Marcar uma linha sem a ter corrido é o defeito que o ticket quer evitar.

## 1. Objectivo

Medir se a equipa, **só com o runbook**, consegue cumprir os três marcos de um incidente P1 —
triagem (PRZ-1), rascunho às PMEs (PRZ-3), rascunho à APD (PRZ-4) — e encontrar o que falha.
Todos os prazos são os do runbook §2 e **levam a sua marca**: *boa prática; obrigação a confirmar
por parecer*. Cumprir PRZ-1 num exercício não prova que se cumpre um prazo legal; prova que o
procedimento se executa.

## 2. Participantes

| Papel | Quem | Presente? |
|---|---|---|
| Facilitador (**não** é o SEG; conduz o relógio e os *injects*) | *(por nomear)* | ☐ |
| Escriba (linha temporal, §5) | *(por nomear)* | ☐ |
| SEG, PRIV, OPS, AP (comandam e decidem) | *(os titulares)* | ☐ |
| ADV | Observador, se já estiver contratado; senão, o papel é lido por alguém e o exercício regista que **não houve revisão jurídica real** | ☐ |

## 3. Preparação (≥ 1 semana antes)

- [ ] Reservadas 2 h seguidas; participantes avisados do **cenário geral, não dos *injects***.
- [ ] Os três [modelos](modelos/) impressos ou abertos, **em branco**.
- [ ] O [runbook](resposta_incidentes.md) na versão que vai ser testada, anotada no cabeçalho da acta.
- [ ] A [lista de contactos](contactos_incidentes.md): confirmado quais entradas se vão **verificar de facto** durante a sessão (§7).
- [ ] **Dados sintéticos.** Em `staging`, só dados sintéticos (`08` §7.3; `09` §9). Os *injects* usam
      `tenant-A` e `tenant-B` e identificadores inventados. **Nenhum dado real, nenhum número
      real, nenhum nome real** em ecrã, papel ou acta.
- [ ] Um cronómetro visível para o relógio **simulado**.

## 4. Cenário

**P1 — fuga cruzada entre tenants.** Em `staging`, com dados sintéticos, tratada **como se fosse
`prod`**. Resultado esperado da árvore do §5 do runbook: **P1** (0a não → 0b não → 1 sim → 2 sim
→ 3: 2 tenants). Se a equipa chegar a outra classe, é o primeiro achado do exercício.

O facilitador lê o *inject* de cada linha na hora simulada indicada; **não adianta nada**.

| Hora simulada | *Inject* | O que testa |
|---|---|---|
| T0 | O T2 de suporte recebe a mensagem de uma PME (`tenant-A`): viu no painel uma encomenda que não é da loja dela | Abertura do registo (§4); escriba; chamada ao SEG |
| T0 + 20 min | O OPS encontra nos logs a mesma consulta devolvendo linhas de `tenant-B` a pedidos de `tenant-A`, repetida em 3 dias | Perguntas 1 e 2 da árvore; a prova pedida |
| T0 + 40 min | A verificação da cadeia do `audit_log` de `tenant-B` sai com código `2` e um achado de «cabeça errada» | O §7.1 (um achado é incidente); a regra «responde-se sim» |
| T0 + 1 h | **Marco:** o SEG tem de ter atribuído a classe | PRZ-1 (boa prática; obrigação a confirmar por parecer) |
| T0 + 2 h | A PME A diz que vai avisar os seus clientes por WhatsApp se não houver resposta | Canal alternativo; texto da PME (§7.2); o que **não** se diz |
| T0 + 6 h | O ADV não atende | §9.4: quem autoriza o envio sem advogado |
| T0 + 12 h | Um fornecedor de LLM informa que registou *payloads* do período | Segunda origem (fornecedor); a lista de transferências |
| T0 + 20 h | O OPS tem de ter exportado e selado a evidência | PRZ-7 (proposta de engenharia) |
| T0 + 24 h | **Marco:** rascunho às PMEs pronto | PRZ-3 (boa prática; obrigação a confirmar por parecer) |
| T0 + 30 h | A APD telefona a pedir informação | PRZ-6; quem atende, o que diz |
| T0 + 48 h | O titular de uma encomenda escreve a perguntar se os seus dados foram expostos | Modelo do titular; a decisão aberta D9 de quem avisa |
| T0 + 72 h | **Marco:** rascunho à APD pronto | PRZ-4 (boa prática; obrigação a confirmar por parecer) |

## 5. Guião da sessão (2 h)

| Min. | Fase |
|---|---|
| 0–10 | Regras: é um exercício, o tempo é simulado, o objectivo é achar o que falha, **ninguém é avaliado**. O facilitador não ajuda |
| 10–25 | Até ao marco de PRZ-1: detecção, registo, triagem |
| 25–50 | Contenção e preservação de evidência (§6 e §7 do runbook) |
| 50–60 | Pausa |
| 60–95 | Avaliação e **preencher os três modelos**, com o relógio a correr: mede-se o tempo de cada um (alvo ≤ 30 min, *proposta*) |
| 95–110 | *Injects* depois do marco de PRZ-3: APD, titular, advogado |
| 110–120 | Fecho: o que atrasou, o que falhou, os tickets |

## 6. Linha temporal — **a preencher na sessão**

O escriba regista **cada facto e cada decisão** com a hora real e a hora simulada.

| Hora real | Hora simulada | Quem | Facto / decisão | Prova |
|---|---|---|---|---|
| | | | | |

## 7. Medidas — **a preencher**

| Marco | Alvo (com a marca do runbook §2) | Conseguido | Margem |
|---|---|---|---|
| Triagem concluída e classe atribuída (PRZ-1) | ≤ 1 h simulada — *boa prática; obrigação a confirmar por parecer* | | |
| Evidência exportada e selada (PRZ-7) | ≤ 24 h simulada — proposta de engenharia | | |
| Rascunho às PMEs (PRZ-3) | ≤ 24 h simulada — *boa prática; obrigação a confirmar por parecer* | | |
| Rascunho à APD (PRZ-4) | ≤ 72 h simulada — *boa prática; obrigação a confirmar por parecer* | | |
| Tempo de preencher cada modelo | ≤ 30 min — *proposta* | APD: | PME: | titular: |
| Classe atribuída pela árvore | P1 | | |
| Entradas da lista de contactos verificadas de facto | todas as que forem verificáveis | | |

## 8. Falhas → tickets

Cada falha vira ticket **`fix`**, com dono e prazo. Uma falha sem ticket não foi tratada.

| # | Falha observada | Ticket `fix` | Dono |
|---|---|---|---|
| | | | |

## 9. Acta-modelo

| Campo | Valor |
|---|---|
| Data e hora | |
| Versão do runbook testada | |
| Facilitador / escriba | |
| Presentes, por papel | |
| ADV presente ou simulado | |
| Classe atribuída e caminho da árvore | |
| Limiar **L** (runbook §5): mantém-se, ou muda? | |
| Marcos cumpridos (§7) | |
| Tickets abertos (§8) | |
| Decisão sobre repetir antes de dados reais | |

| Aprovação | Nome | Data |
|---|---|---|
| Responsável de Segurança | | |

**A acta preenchida guarda-se no repositório de provas** (privado), não neste repositório: pode
descrever fraquezas reais do procedimento. Fica aqui apenas o modelo.

## 10. Depois

- Repetição **anual** (`E3` requisito 12), e sempre que o runbook mude de forma material.
- As alterações ao runbook decorrentes entram com linha de versão.

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 0.1 | Novembro 2026 | Emissão (KAM-113): guião, *injects*, quadros de medida e acta-modelo. **Exercício não realizado** | Equipa KAMBÁ |
