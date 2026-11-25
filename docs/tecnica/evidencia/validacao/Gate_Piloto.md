# Gate do Piloto — pacote de evidência

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — pacote de evidência do gate do Piloto (checklist) |
| Versão | 1.1 |
| Data | Novembro de 2026 |
| Estado | NÃO VERIFICADO — pacote gerado; a verificação cruzada e a decisão são humanas |
| Fonte | `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2 e §6; `../../../../specs/00_KAMBA_Carta.md` §5; `../../../../specs/EPIC-10_Spikes_Validacao_Gates.md` (bloco KAM-110) |
| Dono | Fundador, com o Arquitecto de Plataforma, o Responsável de Segurança e o de Produto |
| Ticket | KAM-110 (EPIC-10) |
| Gerado por | `tools/gate_piloto` — não se edita à mão; regenera-se |
| Relacionados | [`Gate_Piloto_Decisao.md`](Gate_Piloto_Decisao.md), [`Registo_Hipoteses.md`](Registo_Hipoteses.md) |

> **Pré-visualização sem resumo do piloto.** Gerado só sobre o Registo de
> Hipóteses; os itens da Carta §5 que se declaram por evidência ficam todos
> `por verificar`, e a paragem total não é avaliável. O pacote do gate
> gera-se no dia do gate, sobre o manifesto congelado do KAM-109.

> **Este pacote não decide.** Aplica as regras do bloco KAM-110 e mostra o
> que elas dão; a decisão — `CONTINUAR`, `PIVÔ` ou `PARAR` — escreve-se no
> [`Gate_Piloto_Decisao.md`](Gate_Piloto_Decisao.md), pelo fundador e pelos
> três papéis.

---

## 1. Hipóteses H1–H9 (critério A)

O **estado efectivo** é o declarado no Registo **só** se a linha tiver dados:
amostra n positiva, um resultado com número, uma coluna fonte que nomeie um
ficheiro que exista na árvore — ou, em H1, H6, H8 e H9, o SHA-256 do manifesto
congelado do KAM-109 —, a amostra mínima que um critério escreve (H6 e H9) e,
nessas quatro, o manifesto nomeado no resumo. Sem isso é
`inconclusiva` — também quando o declarado é `refutada`, porque uma refutação
sem dados accionava um pivô por nada.

**O gerador não confronta o resultado com o limiar.** O resultado é texto no
Registo, com unidades que variam por hipótese; que cada `confirmada` cumpre o
seu limiar confere-o a verificação cruzada do memorando (§9).

| H | limiar | amostra n | resultado | declarado | **efectivo** | evidência | porque difere |
|---|---|---|---|---|---|---|---|
| H1 | ≥ 5 pagam após 30 dias de piloto | — | — | — | **inconclusiva** | — | sem o manifesto congelado do KAM-109 no resumo; amostra n vazia ou zero; resultado sem número medido; a coluna fonte não nomeia um ficheiro que exista nem o SHA-256 do manifesto; estado por decidir |
| H2 | ≥ 50% aceitam para ≥ 70% do catálogo | — | — | — | **inconclusiva** | — | amostra n vazia ou zero; resultado sem número medido; a coluna fonte não nomeia um ficheiro que exista; estado por decidir |
| H3 | 3/3 ligados sem perda de histórico, operacionalizado em [`H3_Coexistencia_244.md`](H3_Coexistencia_244.md) §3 | — | — | — | **inconclusiva** | — | amostra n vazia ou zero; resultado sem número medido; a coluna fonte não nomeia um ficheiro que exista; estado por decidir |
| H4 | Resposta escrita da Meta ou aprovação de Tech Provider | — | — | — | **inconclusiva** | — | amostra n vazia ou zero; resultado sem número medido; a coluna fonte não nomeia um ficheiro que exista; estado por decidir |
| H5 | Prazo e custo por PME conhecidos e ≤ 6 semanas | — | — | — | **inconclusiva** | — | amostra n vazia ou zero; resultado sem número medido; a coluna fonte não nomeia um ficheiro que exista; estado por decidir |
| H6 | Custo ≤ 15% da mensalidade | — | — | — | **inconclusiva** | — | sem o manifesto congelado do KAM-109 no resumo; amostra n vazia ou zero; resultado sem número medido; a coluna fonte não nomeia um ficheiro que exista nem o SHA-256 do manifesto; estado por decidir |
| H7 | ≥ 85% resolvidas sem *handoff* errado | — | — | — | **inconclusiva** | — | amostra n vazia ou zero; resultado sem número medido; a coluna fonte não nomeia um ficheiro que exista; estado por decidir |
| H8 | ≥ 60% de catálogos correctos em auditoria | — | — | — | **inconclusiva** | — | sem o manifesto congelado do KAM-109 no resumo; amostra n vazia ou zero; resultado sem número medido; a coluna fonte não nomeia um ficheiro que exista nem o SHA-256 do manifesto; estado por decidir |
| H9 | ≥ 70% activos ao dia 60, das PMEs activadas até à semana 4 | — | — | — | **inconclusiva** | — | sem o manifesto congelado do KAM-109 no resumo; amostra n vazia ou zero; resultado sem número medido; a coluna fonte não nomeia um ficheiro que exista nem o SHA-256 do manifesto; estado por decidir |

| Contagem | |
|---|---|
| `confirmada` | 0 |
| `refutada` | 0 |
| `inconclusiva` | 9 |
| Declaradas no Registo e rebaixadas aqui | 0 |

### 1.1 Inconclusivas, e o plano datado que cada uma exige

«Uma hipótese inconclusiva não permite `CONTINUAR` sem um plano datado para a
fechar» (bloco KAM-110, «Detalhes Técnicos»). O plano e a data preenchem-se no
memorando, à mão.

Inconclusivas: H1, H2, H3, H4, H5, H6, H7, H8, H9.

## 2. Definition-of-Done do Piloto, item a item (critério B)

P2, P3 e F3 **derivam do §1** e não se declaram: só ficam `satisfeito` com
todas as hipóteses deles `confirmada`. Os outros declaram-se no resumo, e
`satisfeito` exige um ficheiro de evidência que exista na árvore.

| # | Item (Carta §5) | Credor | Estado | Evidência | Nota |
|---|---|---|---|---|---|
| P1 | Fluxo A em produção com ≥ 10 PMEs activas, onboardadas por self-service automático; ≥ 80% das activações sem intervenção humana (ADR-019) | KAM-109 | por verificar | — | não declarado |
| P2 | H1: ≥ 5 PMEs convertem a pago no fim do piloto gratuito de 30 dias. H9: ≥ 70% activas ao dia 60, das PMEs activadas até à semana 4 | KAM-109 | por verificar | §1 deste pacote | H1 inconclusiva; H9 inconclusiva |
| P3 | H6: custo de IA por conversa ≤ 15% da mensalidade, medido em ≥ 500 conversas reais. H8: ≥ 60% de catálogos correctos em auditoria | KAM-109 | por verificar | §1 deste pacote | H6 inconclusiva; H8 inconclusiva |
| F1 | Esqueleto andante provado: uma conversa real cria um pedido, o evento de pagamento é consumido pela outra vertical, sem excepções no core | KAM-108 | por verificar | — | não declarado |
| F2 | 0 fugas entre tenants ou contactos, 0 pedidos duplicados e 0 números divergentes no conjunto adversarial | KAM-040, KAM-073 | por verificar | — | não declarado |
| F3 | H7 ≥ 85% de handoff correcto | KAM-040 | por verificar | §1 deste pacote | H7 inconclusiva |
| F4 | 100% das confirmações de pagamento por evento autenticado (facilitador ou `ManualProvider` auditado e limitado) | KAM-103, KAM-109 | por verificar | — | não declarado |
| F5 | Gates de CI fail-closed verdes e revisão de segurança independente concluída | KAM-074 | por verificar | — | não declarado |
| C1 | Procedimento APD concluído para todos os destinos de dados pessoais em produção (D1, D9) | KAM-105, KAM-069 | por verificar | — | não declarado |
| C2 | DPA aceite em 100% dos tenants activos | KAM-090, KAM-109 | por verificar | — | não declarado |
| C3 | Parecer jurídico recebido sobre D8 | KAM-104 | por verificar | — | não declarado |
| C4 | Resposta escrita da Meta (ou decisão registada de operar sem ela) sobre D2 | KAM-101 | por verificar | — | não declarado |
| C5 | Tech Provider activo (D5) | KAM-102 | por verificar | — | não declarado |
| C6 | Backups com restauro testado e RTO medido (critério B: e RPO medido) | KAM-085 | por verificar | — | não declarado |
| C7 | Runbooks e SLOs em vigor (EPIC-08) (critério B: com o relatório de SLO de 30 dias) | KAM-082, KAM-083 | por verificar | — | não declarado |
| N1 | Nenhuma PME do piloto onboardada à mão pela equipa | KAM-109 | por verificar | — | não declarado |
| N2 | Nenhum pagamento confirmado por comprovativo em imagem | KAM-109 | por verificar | — | não declarado |
| N3 | Nenhum dado pessoal enviado a subprocessador fora de Angola sem registo | KAM-069, KAM-105 | por verificar | — | não declarado |

**0 de 18 satisfeitos.** O Piloto está *feito* só com
todos (Carta §5: «Nenhum item é substituível por documentação»). H10–H12, dos
módulos de entrada, **não bloqueiam** o gate (Carta §5; ADR-020) e ficam fora
desta tabela.

## 3. Matriz de `14` §6 (critério C)

Nenhuma hipótese está `refutada` no estado efectivo, e nenhum canal está
medido como não repetível: a matriz **não acciona** linha nenhuma. Isto
**não é** um verde — as inconclusivas do §1.1 continuam por fechar.

Há canal repetível (KAM-106, «≥ 6 PMEs-alvo em ≥ 2 rondas»): por medir.

**Paragem total** — «se ao fim de 12 semanas não houver ≥ 3 pagantes recorrentes e nenhum canal comercial repetível» (`14` §6): não avaliável (falta semana_do_gate, pagantes_recorrentes, canal_comercial_repetivel).

## 4. Economia real (critério D)

| Campo | Valor | Fonte |
|---|---|---|
| Custo por PME, medido | por medir (KAM-081) | KAM-081 (`h6-export`) |
| Custo por PME, estimado | 49 – 80 USD por PME e por mês, no Piloto (≈ 10 PMEs) — ESTIMATIVA | `../../09_Topologia_Operacao_Escala.md` §14.4 |
| Ponto de equilíbrio, hipótese | ≈ 8 a 28 PMEs | `../../09_Topologia_Operacao_Escala.md` §14.5 |
| Ponto de equilíbrio, actualizado | *por preencher no memorando* | |
| Meses de pista restantes | *por preencher pelo fundador* | `14` §5 |
| Ponto em que se pára ou se muda | *por preencher pelo fundador* | `14` §5 |

**Os números de pista não passam por este gerador.** O resumo tem esquema
fechado e recusa qualquer chave que não conheça; a pista escreve-se no
memorando, pelo fundador, e nunca é estimada pelo executor (critério D).

## 5. Origem

| Campo | Valor |
|---|---|
| Registo de Hipóteses | `docs/tecnica/evidencia/validacao/Registo_Hipoteses.md` |
| Resumo do piloto | nenhum |
| Manifesto congelado do KAM-109 | nenhum — sem ele nenhuma hipótese do KAM-109 se dá por medida |
| Resumo sintético | não |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Forma do pacote, KAM-110 (preparação): hipóteses com estado efectivo, Carta §5 item a item, matriz de `14` §6, paragem total, economia sem números de pista, e origem. O texto é do gerador `tools/gate_piloto`; uma alteração de forma é uma alteração do gerador e acrescenta linha aqui. | Equipa KAMBÁ |
| 1.1 | Novembro de 2026 | KAM-110, interface com o KAM-109 fundido: o resumo nomeia o manifesto `piloto_congelado.json` em vez da exportação, e a coluna fonte de H1, H6, H8 e H9 aceita o SHA-256 dele, como manda o protocolo do Piloto (§10). | Equipa KAMBÁ |
