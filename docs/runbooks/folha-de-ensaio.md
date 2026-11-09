# Ensaios dos runbooks — roteiros, folha de tempos e *game day*

| Campo | Valor |
|---|---|
| Ticket | **KAM-083**, critérios 2 e 7 (`specs/EPIC-08_Topologia_Operacao.md`) |
| Versão | 1.0 |
| Índice dos runbooks | [`README.md`](README.md) |
| Estado | **Roteiros escritos; nenhum ensaio feito.** Os ensaios são de pessoas — o critério 2 exige quem não seja o autor —, e o calendário precisa de *staging* com *host* |
| Quem conduz | Plataforma/SRE, com o Responsável de Segurança no K07 e no K10 |

> **Porque é que estes roteiros não se correm aqui.** O critério 2 pede que cada
> runbook seja ensaiado **por uma pessoa distinta do autor**. Quem escreveu os
> runbooks não os pode ensaiar sem anular o ensaio, e um agente não é «uma
> pessoa». O que este ficheiro entrega é o que a pessoa precisa para os ensaiar
> sem ter estado na conversa: o roteiro, o que medir, e onde escrever.

---

## 1. Como se conduz um ensaio

| Tipo | Para | Como |
|---|---|---|
| **Mesa-redonda** | K02, K04, K05, K06, K07, K08, K09, K10 | Um condutor lê o cenário e as «injecções» da secção 3 por ordem; a pessoa de serviço responde **só com o runbook aberto**, dizendo o comando que correria e o que espera ver. O condutor regista o tempo de cada passo e cada momento em que o runbook não chegou |
| **Injecção de falha em *staging*** | K01, K03 | A falha injecta-se de verdade no compose de *staging* (secção 3), e a pessoa de serviço corre os comandos. Precisa do *staging* com *host* (KAM-077) |
| **Simulacro completo** | K08 | É o KAM-085 ([`simulacro-de-dr.md`](simulacro-de-dr.md)); aqui só a mesa-redonda |

**Regras que fazem do ensaio uma medição e não uma leitura:**

1. quem ensaia **não** escreveu o runbook, e não o leu antes do ensaio;
2. o condutor não ajuda — uma pergunta da pessoa de serviço que o runbook não
   responde é uma **lacuna**, e regista-se como tal;
3. um comando marcado `não verificado` que falhe no ensaio é uma lacuna do
   runbook, não um erro de quem ensaia;
4. o ensaio fecha com **0 lacunas abertas** (critério 2): cada lacuna corrige-se
   no runbook, com linha no seu controlo de versões, e o passo volta a ensaiar-se.

---

## 2. A folha de tempos (modelo)

Copia-se por ensaio para `docs/evidencia/KAM-083/ensaio-RB-Kxx-<AAAA-MM-DD>.md`.
**Sem nomes de pessoas**: o repositório é público. Regista-se o papel.

```text
Runbook:            RB-K__        versao do runbook ensaiada: 1._
Tipo:               mesa-redonda | injeccao em staging
Data:               AAAA-MM-DD
Condutor:           <papel>
Pessoa de servico:  <papel>  (nao e o autor: sim/nao)

Marco                         Hora (UTC)   Desde T0    Nota
T0  injeccao / leitura        __:__        0 min
T1  primeiro comando          __:__        __ min
T2  diagnostico fechado       __:__        __ min      qual o ramo do runbook escolhido
T3  mitigacao iniciada        __:__        __ min
T4  criterio de recuperacao   __:__        __ min      qual comando o confirmou
T5  comunicacao enviada       __:__        __ min      interna / PME (rascunho)

Lacunas
#   Passo   O que faltou                         Corrigida em (versao)   Estado
1   __      __                                   1._                     aberta/fechada

Comandos nao verificados que o ensaio correu
Comando   Resultado   A marca passa a `verificado`? (sim/nao, porque)
```

Depois do ensaio, o cabeçalho do runbook passa a dizer a data e o tipo no campo
**Último ensaio**, e a linha nova do controlo de versões diz quantas lacunas se
abriram e fecharam.

---

## 3. Os roteiros

Cada roteiro dá a injecção, por ordem, e o que a pessoa de serviço **deve**
chegar a fazer. O condutor não lê a coluna da direita em voz alta.

### 3.1 RB-K01 — injecção em *staging*

| # | Injecção | Esperado |
|---|---|---|
| 1 | Parar o GWY: `docker stop kamba-staging-gwy-1 kamba-staging-gwy-2` | `alvo_em_baixo` (2 min) e `ingress_parado` (até ~15 min, por causa dos 5 min de obsolescência antes do `absent()`); a pessoa separa «ingestão parada do nosso lado» de «Meta em baixo» pelo §2 do runbook |
| 2 | Repor o GWY e cortar a saída para a Graph API no `proxy-saida` | erro de envio, não de ingestão; ramo «envio» do runbook |
| 3 | Repor tudo | critério de recuperação do §4, com o comando que o confirma |

### 3.2 RB-K03 — injecção em *staging*

| # | Injecção | Esperado |
|---|---|---|
| 1 | Parar o LiteLLM: `docker stop kamba-staging-litellm-1` | o AGR degrada (`degradacao-do-agr.md`); a pessoa distingue «indisponível» de «sem *budget*» |
| 2 | Repor e dar à chave virtual de um *tenant* de ensaio um *budget* esgotado | `llm_sem_budget`; ramo «sem *budget*», com a decisão humana de subir o limite |
| 3 | Repor | critério de recuperação |

### 3.3 Mesas-redondas

| Runbook | Cenário a ler | Injecções, por ordem |
|---|---|---|
| RB-K02 | A criação de referências começa a falhar às 10:00 de um sábado | (1) as referências falham com 5xx; (2) uma PME diz que o cliente pagou e a encomenda não confirmou; (3) o cliente envia a imagem do comprovativo |
| RB-K04 | Chega um `phone_number_quality_update` com o número em vermelho | (1) o *tenant* fez uma difusão de marketing ontem; (2) dois *templates* ficam pausados; (3) persiste 48 h |
| RB-K05 | Um número passa as 800 *service messages* a dia 18 | (1) a PME não tem método de pagamento no Billing Hub; (2) passa as 1.000 a dia 24 |
| RB-K06 | Chega um `account_update` com `PARTNER_REMOVED` | (1) a PME diz que não desligou nada; (2) reconecta 30 h depois |
| RB-K07 | (a) rotação planeada do segredo do *webhook* da Meta; (b) suspeita de fuga da chave do facilitador | (a) o GWY tem de aceitar as duas assinaturas durante a janela; (b) a ordem muda e o RB-K10 abre |
| RB-K08 | Uma migração apagou linhas às 14:02 e alguém o notou às 14:40 | (1) PITR; (2) o *outbox* posterior a T; (3) a âncora do `audit_log` |
| RB-K09 | Um contacto envia 400 mensagens numa hora a um *tenant* | (1) o custo de LLM do *tenant* triplica; (2) são 40 contactos do mesmo IP |
| RB-K10 | Um prestador avisa de uma violação nos seus sistemas | segue os cenários do anexo A de [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md) |

---

## 4. Calendário do *game day* semestral

O doc 09 §13 manda um *game day* semestral que **injecta K01, K03 e K08**.

| Edição | Data | Injecta | Condição para acontecer | Estado |
|---|---|---|---|---|
| 1.ª | **por fixar** | K01, K03 (em *staging*), K08 (simulacro do KAM-085) | *staging* com *host* (KAM-077); escala de *on-call* com pessoas (`ops/on-call.md`); os oito ensaios de mesa-redonda feitos | **por fixar** — credor: **o fundador** |
| seguintes | + 6 meses da anterior | idem | — | — |

**A primeira data não se fixa aqui**, e não é por cautela de forma: fixá-la é
comprometer pessoas que não existem na escala, num ambiente que ainda não existe.
Uma data escrita sem essas duas coisas seria uma data que passa sem ninguém dar
por ela — que é o mesmo defeito do alerta que nunca dispara. O critério 7 fica
por cumprir, com o credor.

---

## 5. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Criado pelo **KAM-083**: as regras do ensaio, a folha de tempos, os roteiros dos dez runbooks e o calendário do *game day* com a primeira data por fixar | KAM-083 |
