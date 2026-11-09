# Red-team do AGR — relatório

| Campo | Valor |
|---|---|
| Ticket | KAM-073 |
| Plano | [`plano.md`](plano.md) |
| Medido sobre | `publico/main` em `6583930f`, mais o ramo do KAM-073; política de guardas **1.1.0**, conjunto adversarial **1.0.0** |
| Execução | automática, contra o grafo compilado com *fakes*; **sem** *staging* e **sem** a parte manual (ver §5) |
| **Estado** | Rascunho para o Responsável de Segurança. **Não assinado.** |

## 1. Resultado em três linhas

- **Zero violações de invariante** em 168 casos e 635 corridas do grafo, com o modelo do lado do
  atacante nas nove intenções. Nenhum caso deixou sair dados de outro contacto, mudar preço,
  estado de pagamento, ou escrever sem o botão do runtime.
- **Nenhum achado P1 nem P2.** Os achados são todos camadas de defesa a menos (P3 e P4 pelo
  `../../tecnica/08_Seguranca_Conformidade.md` §10).
- **Três formas de saída passavam o filtro do `guard_out` e foram fechadas** neste ticket (política
  1.0.0 → 1.1.0), com ensaio que falha no código antigo. **Seis achados ficam abertos**, quatro P3 e
  dois P4, cada um com credor.

## 2. Achados por severidade

| Severidade | Abertos | Fechados | Total |
|---|---|---|---|
| P1 | 0 | 0 | 0 |
| P2 | 0 | 0 | 0 |
| P3 | 4 | 3 | 7 |
| P4 | 2 | 0 | 2 |

**Os achados abertos estão descritos fora do repositório público**, num ficheiro de trabalho
guardado com o fundador: o caso exacto que passa e porquê. Aqui fica a classe, a camada, o dono e o
prazo, como o critério 6 do bloco pede. No conjunto, cada caso aberto tem `estado: falha_conhecida`,
o identificador e o credor, sem prosa.

| Achado | Sev. | Camada | Classe | Dono | Prazo | Casos |
|---|---|---|---|---|---|---|
| RT-01 a RT-03 | P3 | L4 | Três formas de saída passavam o filtro do `guard_out` | KAM-073 | **fechado** | 4 |
| RT-04 | P3 | L1 | Variantes do pedido cruzado que as regras decidem como `ok` | KAM-189 | antes do Piloto com dados reais | 6 |
| RT-05 | P3 | L1 | Pedidos cruzados e de exfiltração que as regras não decidem, entregues ao classificador sem qualidade medida | KAM-040 | o do KAM-040 | 7 |
| RT-06 | P3 | L1 | Frases de assunto sensível que as regras não reconhecem | KAM-189 | antes do Piloto com dados reais | 9 |
| RT-07 | P3 | L1 (§4.7) | A chamada ao modelo não fixa tecto de resposta | KAM-189 | antes do Piloto com dados reais | 1 |
| RT-08 | P4 | L1 | Uma nota de voz sem transcrição gasta uma chamada ao modelo | KAM-036 | o do KAM-036 | 1 |
| RT-09 | P4 | L1 | Uma forma de pedido fora de domínio recebe a resposta de catálogo vazio em vez da recusa | KAM-189 | antes do Piloto com dados reais | 1 |

O prazo é *proposta*: o §10 não dá prazo a P3 nem a P4 («ajuste de filtros e registo»).
**Quem segura cada achado aberto hoje** é a camada seguinte: a tool, que só vê as encomendas do
próprio contacto; o `compose` determinístico, que não tem tool que liste clientes; a RLS; e o
orçamento por *tenant* do LiteLLM.

## 3. Por família

| Família | Casos | Detectados pela camada | Falha conhecida |
|---|---|---|---|
| Injecção cruzada (X-09) | 45 | 36 | 9 |
| Injecção indirecta | 22 | 22 | 0 |
| Exfiltração | 25 | 21 | 4 |
| Abuso de tools | 16 | 16 | 0 |
| *Denial of wallet* e voz | 16 | 14 | 2 |
| Assunto sensível | 22 | 13 | 9 |
| Fora de domínio | 22 | 21 | 1 |
| **Total** | **168** | **143** | **25** |

Três taxas que os critérios pedem, todas **sem modelo** (o chão; o classificador só as pode
subir):

- **Fora de domínio (critério 8):** 21 de 22 recebem a recusa neutra com oferta de colega —
  **95,5%**, acima do alvo de 95% (*proposta* do `../../tecnica/05_Indice_Pesquisa_Motor_Atencao.md` §10, que o bloco cita).
- **Assunto sensível (critério 5):** 13 de 22 reconhecidos pelas regras, sem persistir e sem ir ao
  modelo — **59%**. O alvo é do Responsável de Segurança e não está fixado.
- **Filtro de saída (critério 3):** os 13 casos de imagem remota, URL fora da *allowlist* e eco do
  *system prompt* são bloqueados e recebem a mensagem determinística — **100%**, depois das três
  correcções.

## 4. L5 e o custo

- A terceira tentativa de injecção na hora abre **um** *handoff* e o *cool-down*; três tentativas
  espaçadas não escalam; a série `agr_guard_in_total{veredicto="injection"}` conta cada tentativa
  avaliada. Os turnos dentro do *cool-down* não são avaliados e não entram nessa série.
- Cinquenta turnos no mesmo contacto: cada turno acaba, sai no máximo uma mensagem por turno, e
  depois do *cool-down* o modelo não é chamado nenhuma vez.
- O texto que vai ao classificador é cortado ao comprimento máximo da política.
- **Custo de modelo desta execução: zero.** Os dois classificadores são duplos; nenhuma chamada saiu
  para um fornecedor. O custo de uma corrida real mede-se em *staging*.

## 5. O que este relatório não cobre

- **A execução em `staging`**: o ambiente não existe, e o processo do AGR ainda não serve turnos
  ao grafo (KAM-186).
- **A parte manual** do bloco (duas pessoas, um dia): não feita; credor, o fundador.
- **A promoção ao *gate* golden** (gate 13): o *gate* é do KAM-040. Os casos já são asserções
  determinísticas na bateria do AGR.
- **A assinatura do Responsável de Segurança**.

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão (KAM-073): primeira execução automática do conjunto 1.0.0; três formas de saída fechadas; seis achados abertos com credor. | Equipa KAMBÁ |
