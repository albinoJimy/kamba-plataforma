# Protocolo pré-registado do Piloto — H1, H6, H8 e H9

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — protocolo pré-registado da medição do Piloto concierge: coorte, definições, regras de estado, auditoria de catálogo, relatório semanal e congelamento dos dados |
| Versão | 1.0 |
| Data | 2026-11-25 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-109 (EPIC-10) |
| Estado | NÃO VERIFICADO — **por assinar**; nenhuma PME foi activada e nenhuma das quatro hipóteses foi medida |
| Fonte | `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2 (limiares), §3A Regra 4 (coorte e substituição), §6 (pivôs e paragem total); `../../../../specs/EPIC-10_Spikes_Validacao_Gates.md` (bloco do KAM-109: definições *propostas*, regra de H9 inconclusiva, regra de contagem de H6) |
| Dono | Fundador (assina o protocolo e decide cada hipótese, `../../../../specs/00_KAMBA_Carta.md` §4.2); a operação e a medição são do Responsável de Produto com Ops/Trust & Safety |
| Documento-fonte | `../../09_Topologia_Operacao_Escala.md` §14 (custos), §17 (alvos); `../../10_Onboarding_Governanca.md` §16; `../../../../specs/00_KAMBA_Carta.md` §5 |
| Relacionados | [`Registo_Hipoteses.md`](Registo_Hipoteses.md) (onde os resultados entram), [`GoLive_Gate.md`](GoLive_Gate.md) (pré-condição de dados reais), [`H10_H12_Modulos_Entrada.md`](H10_H12_Modulos_Entrada.md) (o pré-registo vizinho, do EPIC-11) |
| Instrumentos | `db/piloto_export.py` (`piloto-export`, *job* `ops_piloto_export`), `tools/piloto/` (`python -m piloto`), `db/h6_export.py` (`h6-export`, KAM-081) |

> **Este documento nasce antes da primeira activação, e é isso que o torna
> útil.** Fixa a coorte, o que conta como «activa», «usar», «pagar» e «catálogo
> correcto», a regra que transforma uma medição num estado, e a forma como os
> dados se congelam — tudo antes de haver um único número. Um limiar escolhido
> depois do resultado não é um limiar.
>
> **Está por assinar.** Os limiares são os de `14` §2, à letra «propostas
> minhas» do fundador; as definições marcadas *proposta* são do bloco do KAM-109
> ou deste documento, e só valem depois de assinadas. **Depois da assinatura,
> só mudam por emenda** (§12), e uma alteração depois de haver resultado é uma
> mudança de critério e não um ajuste.
>
> **O preço real da mensalidade não está aqui.** É decisão do fundador, e o
> campo do §4 fica em branco até ele o preencher.

---

## 1. O que este protocolo fixa, e o que não fixa

Fixa a medição de **H1, H6, H8 e H9** no Piloto de 10 PMEs com o Fluxo A em
produção. As outras cinco hipóteses do `Registo_Hipoteses.md` medem-se noutros
tickets (H2 no KAM-106, H3 no KAM-100, H4 no KAM-101 e KAM-102, H5 no KAM-103) e
H7 no golden do KAM-040, a que este Piloto só **fornece casos**: os T2
resolvidos entram pelas **três origens do KAM-040** — `sintetico`,
`t2_anonimizado` e `real_consentido`, e nenhum `real_consentido` sem registo de
consentimento (decisão do fundador de 2026-10-30, linha 1.6 do EPIC-10).
Conversas reais **não** treinam nem melhoram modelos.

**Não fixa:**

* **O preço real da mensalidade** (§4) — é do fundador.
* **A decisão** de cada hipótese, nem o pivô — são do fundador, no gate do
  KAM-110. Os instrumentos **propõem** um estado; quem o escreve no Registo é ele.
* **O modo «a IA rascunha e o humano aprova antes de enviar»** de `14` §3,
  ponto 3. Nenhum ticket o constrói; se o fundador o quiser, é ticket novo. Aqui
  «concierge» é apoio humano apertado (T2), cobrança manual com `ManualProvider`
  auditado e correcção de catálogo — a leitura que o bloco do KAM-109 adopta.

---

## 2. Coorte e calendário

| Item | Regra | Estado |
|---|---|---|
| Tamanho | **10 PMEs**, da lista de canais do KAM-106 (`14` §3A, Regra 4). O `medir` recusa uma coorte com mais de 10: «5 de 12» não é «5 de 10» | fixado pela fonte |
| Entrada | *Self-service* (ADR-019); a % de activações sem intervenção humana reporta-se (§3) | fixado pela fonte |
| Identificação fora da base | Só o **ordinal** `P01`…`P99`, pela ordem de entrada na coorte. O nome da PME, do dono e qualquer telefone **nunca** saem da base nos relatórios, nas exportações nem nos resultados. **A única excepção é operacional**: a lista de produtos e a folha de auditoria de H8 levam os nomes dos produtos (dados do negócio, escritos pelo dono, que podem trazer o nome comercial), porque quem audita precisa deles para os encontrar. Ficam fora do repositório, com a exportação, e o `medir` só lê delas contagens | *proposta* |
| Dia 0 | O dia (`Africa/Luanda`) da **primeira** entrada da PME no estado `ativo` (`tenant_state_log`, a mesma regra da `churn_dono_at` da `0063`) | *proposta* |
| Dia 1 do Piloto | A data em que o relatório semanal começa a contar semanas. **Por preencher**: ________ | por preencher |
| Gratuitidade | 30 dias gratuitos e, depois, pagamento ao preço real (Regra 4) — a leitura que o bloco do KAM-109 adopta para a inconsistência de `14` entre H1 e a Regra 4 | fixado pelo bloco |

### 2.1 Substituição

**Quem não usa na semana 2 sai e é substituída** (Regra 4). «Usar na semana 2»
(dias 7 a 13) é **≥ 1 conversa ou ≥ 1 acção do dono** nesses sete dias
(*proposta*). O instrumento lista, por PME, se usou (`detalhe.uso_semana_2` da
H1); **a saída é decisão humana**, registada no ficheiro da coorte com o dia e
um motivo de uma lista fechada:

| Motivo | Quando |
|---|---|
| `sem_uso_semana_2` | A regra acima |
| `desistiu` | A PME pediu para sair |
| `excluida_protocolo` | Violação de uma pré-condição (§3), com a razão no registo de desvios (§12) |

A PME substituída **sai do denominador** de H1, H8 e H9 e é reportada à parte; a
que entra no lugar dela tem o seu próprio dia 0. *Proposta*: incluir as
substituídas no denominador de H9 penalizava a retenção com PMEs que nunca
chegaram a usar; excluí-las favorece-a. A escolha fica escrita para quem assina.

### 2.2 Paragem

| Regra | Origem |
|---|---|
| **Paragem total** se, ao fim de 12 semanas, não houver ≥ 3 pagantes recorrentes e nenhum canal comercial repetível | `14` §6 |
| Nenhuma activação nova com dados reais enquanto uma linha obrigatória do `GoLive_Gate.md` estiver em branco ou `não` | bloco do KAM-109; `GoLive_Gate.md` |
| Uma fuga de dados pessoais ou um pagamento confirmado sem evento autenticado nem dupla aprovação **suspende as activações novas** até à decisão do fundador, e entra no registo de desvios | *proposta*; Carta §5 («0 fugas») |

---

## 3. Pré-condições, verificadas antes da 1.ª activação

| # | Condição | Como se verifica | Estado |
|---|---|---|---|
| PC-1 | Este protocolo **assinado** (§13) | Tabela de aprovação | por assinar |
| PC-2 | `GoLive_Gate.md` todo verde | A folha, linha a linha | **não** — nenhuma linha obrigatória está satisfeita |
| PC-3 | **0 PMEs** activadas com dados reais antes de PC-2 | `piloto-export`: nenhum `activada_em` anterior à data de PC-2 | por medir |
| PC-4 | DPA aceite em **100%** das activadas | `pre_condicoes.dpa_aceite` do `medir` (aceite de qualquer versão `dpa` em `contract_acceptance`, `0040`) | por medir |
| PC-5 | % de activações sem intervenção humana, contra os **≥ 80%** da Carta §5 | `pre_condicoes.self_service` (o contrário do `intervencao_humana` da `v_onboarding_kpis`, KAM-092) | por medir |

---

## 4. Preço real da mensalidade

| Campo | Valor |
|---|---|
| Mensalidade do Piloto (AOA, em unidade menor inteira) | **por preencher pelo fundador** |
| Plano no `price_book` | **por preencher** |

O bloco dá **30–60 mil Kz** como hipótese de referência (`../../09_Topologia_Operacao_Escala.md`
§14.1), e **não** é o preço. O valor deste campo, em unidade menor, é o
`--mensalidade-minor` do `medir`; o `--mensalidade-kz` do `h6-export` é o
**mesmo valor a dividir por 100**, porque o `h6-export` multiplica por 100. O
`medir` recusa um `h6_export.json` corrido com outra mensalidade.

---

## 5. Definições operacionais

| Termo | Definição | Fonte no sistema | Estado |
|---|---|---|---|
| **Conversa** | Mensagens do mesmo contacto, no mesmo tenant, sem pausa maior do que 24 h, na linha do tempo das mensagens de saída. Conta no dia em que **começa** | `outbound_messages`, pela regra do `h6-export` (KAM-081); as conversas de teste em produção (`conversations.is_test`, KAM-202) ficam de fora | fixado pelo KAM-081 |
| **Acção do dono** | Uma linha do `audit_log` com `actor_type = 'owner'` — painel e canal do dono | `audit_log` | *proposta* — conta por baixo (§11) |
| **Activa** | **≥ 1 acção do dono em cada uma das duas semanas** da janela de 14 dias que acaba no dia avaliado, **e ≥ 5 conversas** nessa janela | as duas acima | *proposta* do bloco; a leitura «em cada semana» é deste protocolo |
| **Pagante** (H1) | Um ciclo de mensalidade em `paga` com valor **igual** à mensalidade do §4, que **cubra tempo depois do dia 30** (o fim do período, exclusivo, depois do dia 30) e **pago até ao fecho da janela da conversão**, provado por `pagamento_confirmado` aceite **autenticado pelo facilitador** (`hmac` ou `consulta`) ou **confirmado por ops com dupla aprovação** (a conciliação do comprovativo bancário, `0055`). Um ciclo a outro preço não conta. O critério é o período coberto, e não o início do ciclo, porque os ciclos **não** abrem na activação: abrem no `periodo_dia` da subscrição (1 a 28, `0055`) | `billing_cycles` (período), `payment_events` (via e `recebido_at`) | *proposta* |
| **Janela da conversão** | Do dia 30 ao dia 30 + **41** — um período mensal (31 dias), porque o primeiro ciclo depois do dia 30 pode abrir até um mês depois, mais os **10 dias** da régua de cobrança (KAM-058). Com a janela aberta, uma PME sem pagamento é **pendente**; fechada, **não pagante**, e um pagamento que chegue depois **não conta** — é isso que torna final uma `refutada` | — | *proposta* |
| **Catálogo correcto** (H8) | **≥ 90%** dos itens da amostra certos; item certo se o **preço e** a disponibilidade coincidem com a verdade apurada com o dono ou em visita | folha de auditoria (§8) | *proposta* do bloco |
| **Disponível no sistema** | Oferta `publicado` e com stock (`stock_quantidade − stock_reservada > 0`) ou sem quantidade declarada | `offer_terms` | *proposta* |
| **Exposição de N dias** | O último dia exportado é pelo menos o dia N | — | *proposta* |

---

## 6. As quatro hipóteses, e a regra que dá o estado

Os estados são os três do Registo: `confirmada`, `refutada`, `inconclusiva`.
**Nas hipóteses de contagem (H1, H8) o estado decide-se pelo que já não pode
mudar:** `confirmada` se os sucessos já atingem o alvo; `refutada` se nem com
todos os pendentes a dar certo se atinge; `inconclusiva` no resto. Uma coorte
com menos de 10 conta as vagas por preencher como pendentes.

| H | Limiar | Amostra | Regra de estado | Pivô (`14` §6) |
|---|---|---|---|---|
| **H1** | ≥ 5 de 10 pagam após 30 dias | A coorte final | Contagem (acima), com «pendente» = janela da conversão aberta | Voltar às entrevistas: segmento ou produto |
| **H6** | Custo ≤ 15% da mensalidade | ≥ 500 conversas **da coorte**, nos meses contados | **Os meses e as conversas são os da coorte**: os meses de calendário **inteiros** entre a activação de cada PME e o último dia exportado, com o custo diário da vista do custo (`v_tenant_cost_daily`, a mesma que o `h6-export` lê) na exportação do Piloto. A amostra do `h6-export` **não decide**: são as últimas N conversas da plataforma, sem filtro de tenant, e o rácio dele só leva os meses que essa amostra toca. Do `h6-export` vêm o câmbio, a mensalidade (conferida) e os percentis por conversa, reportados. Abaixo de 500 conversas: `inconclusiva`. **Regra de contagem por omissão: a de `14` — LLM + voz + Meta.** Como não há registo de STT (KAM-036), LLM + Meta **acima** do tecto é `refutada` (o STT só soma) e **no tecto ou abaixo** é `inconclusiva` com o motivo `stt_nao_medido`. Estatística que decide: o **rácio agregado** — o custo de todos os meses-PME contados sobre as mensalidades desses meses (*proposta*); p50 e p90 por mês-PME e o LLM isolado reportam-se ao lado | Subir o preço, reduzir modelo ou voz, ou limitar volume por plano — com a tabela de cenários que o `medir` calcula |
| **H8** | ≥ 60% de catálogos correctos (≥ 6 de 10) | As PMEs da coorte auditadas na 4.ª semana | Contagem (acima); uma PME sem folha é pendente. **Uma folha só conta se os produtos forem exactamente os sorteados** com a semente do §8, pela mesma ordem: o `medir` refaz o sorteio e recusa a medição inteira se não forem. Uma auditoria fora da 4.ª semana conta e sai marcada (`fora_da_semana_4`), e é um desvio a registar (§12). A razão actualizações no sistema / mudanças reais declaradas reporta-se e não decide | **Nenhum.** O gate propõe uma acção de produto (p. ex. lembretes de actualização e painel mínimo, KAM-099) e regista-a |
| **H9** | ≥ 70% activas ao dia 60 | **Só** as PMEs com 60 dias de exposição **à data do gate** | Com **< 8** elegíveis: `inconclusiva`, com a data de seguimento em que a 8.ª activação faz 60 dias. Com ≥ 8: `confirmada` se activas/elegíveis ≥ 70%, senão `refutada`. **Ao contrário de H1 e H8, não é final antes do gate:** com 8 elegíveis pode mudar quando mais PMEs fazem 60 dias, e por isso lê-se na exportação congelada da data do gate. O indicador do dia 30 reporta-se à parte e **não** substitui o do dia 60 | **Nenhum.** Se `refutada`, aplica-se a regra de paragem total (§2.2) e o gate decide o pivô sobre retenção |

**Calendário de H9.** O `14` §2 escreve o limiar como «≥ 70% activos ao dia 60
(das PMEs activadas até à semana 4)», e o bloco do KAM-109 operacionaliza-o como
«apenas sobre PMEs com 60 dias de exposição à data do gate». **Este protocolo
segue o bloco**, que é a fonte mais específica: as duas coincidem quando o gate é
na semana 12, e quando não coincidem é o bloco que diz o que se mede. A Fase 1
vai da semana 7 à 12, e o dia 60 só é alcançável para PMEs activadas até cerca da
semana 4. É a razão da regra das 8 elegíveis: com o calendário apertado, H9 sai
`inconclusiva` com data, e não `refutada` por falta de tempo.

---

## 7. Tabela dos limiares

Cada linha tem o seu par, com o mesmo nome, em `tools/piloto/regras.py`, e o
`tools/piloto/tests/test_protocolo.py` lê as duas e recusa a divergência nos dois
sentidos: um número mudado num sítio e não no outro é um limiar escolhido depois
dos dados.

| Constante | Valor | O que é | Origem |
|---|---|---|---|
| `H1_ALVO` | 5 | pagantes para confirmar H1 | `14` §2 |
| `COORTE` | 10 | PMEs no Piloto | `14` §3A, Regra 4 |
| `H1_DIA_DA_CONVERSAO` | 30 | dias gratuitos | Regra 4 |
| `H1_JANELA_DE_PAGAMENTO_DIAS` | 41 | janela da conversão depois do dia 30 | *proposta* (um período mensal e a régua do KAM-058) |
| `H6_TECTO` | 15% | custo sobre a mensalidade | `14` §2 |
| `H6_AMOSTRA_MINIMA` | 500 | conversas | bloco do KAM-109 |
| `H8_ALVO` | 6 | catálogos correctos em 10 | `14` §2 (≥ 60%) |
| `H8_AMOSTRA_POR_PME` | 20 | produtos sorteados por PME | bloco do KAM-109 |
| `H8_ITENS_CORRECTOS` | 90% | itens certos para um catálogo correcto | *proposta* do bloco |
| `H8_SEMANA_DA_AUDITORIA` | 4 | semana da auditoria | bloco do KAM-109 |
| `H9_LIMIAR` | 70% | activas ao dia 60 | `14` §2 |
| `H9_DIA` | 60 | dia de H9 | `14` §2 |
| `H9_MINIMO_DE_PMES` | 8 | elegíveis abaixo dos quais H9 é inconclusiva | bloco do KAM-109 |
| `DIA_DO_INDICADOR` | 30 | indicador de retenção reportado à parte | bloco do KAM-109 |
| `ACTIVA_JANELA_DIAS` | 14 | janela de «activa» | *proposta* do bloco |
| `ACTIVA_ACCOES_POR_SEMANA` | 1 | acções do dono por semana | *proposta* do bloco |
| `ACTIVA_CONVERSAS` | 5 | conversas na janela | *proposta* do bloco |
| `SELF_SERVICE_MINIMO` | 80% | activações sem intervenção humana | Carta §5 |

---

## 8. Auditoria de catálogo (H8)

1. **A semente regista-se antes da auditoria**, aqui: ________ (um texto
   qualquer; quem audita não a escolhe depois de ver a amostra).
2. Na 4.ª semana de cada PME (dias 21 a 27), o catálogo exporta-se com
   `python db/piloto_export.py produtos --coorte coorte.csv --pme PNN --saida
   produtos_PNN.csv`, e a amostra sorteia-se com `python -m piloto sortear
   --semente <semente> --pme PNN --produtos produtos_PNN.csv --saida
   auditoria_PNN.csv`. **Os dois ficheiros guardam-se juntos**: o `medir` exige a
   lista de produtos no manifesto ao lado de cada folha.
3. **O sorteio é reprodutível por qualquer um sem o nosso código:** cada produto
   recebe `sha256("<semente>:<PNN>:<sku>")`, e a amostra são os 20 de chave mais
   baixa (todos, se houver menos). O `medir` refá-lo com a `--semente` e recusa
   uma folha cujos produtos não sejam exactamente esses.
4. Quem audita preenche, item a item, o preço e a disponibilidade **verdadeiros**
   e a fonte (`dono` ou `visita`), e as duas linhas de controlo: `mudancas` (as
   mudanças reais de preço ou de stock que o dono declara nas 4 semanas) e
   `auditado_em` (o dia da auditoria). Uma folha sem elas está por preencher.
5. **A folha não tem coluna de texto livre**, e o `sortear` recusa um nome de
   produto com forma de telefone, móvel ou fixo, com ou sem indicativo e com
   qualquer agrupamento. O que precisar de nota vai para o registo de desvios,
   sem dados pessoais.

---

## 9. Relatório semanal

`python -m piloto relatorio --exportacao piloto_export.json --horas horas.csv
--inicio <dia 1 do Piloto> --semana N`, uma vez por semana do Piloto, sobre a
exportação dessa semana. Modelo fixo, uma linha por PME da coorte, uma de
trabalho sem PME, uma do trabalho com PMEs que saíram da coorte (para as horas não
sumirem) e uma de total:

| PME | Dias desde a activação | Activa | Conversas | Handoffs | Pagamentos | Custo LLM + Meta (USD) | Incidentes | Horas de operador |
|---|---|---|---|---|---|---|---|---|

O relatório **nunca contém** conteúdo de conversas, telefones, `contact_id`,
`tenant_id` nem nomes: só lê números e ordinais, e o texto inteiro passa por uma
guarda que recusa qualquer `uuid`, qualquer forma de telefone angolano e o
`+244` antes de ser escrito. Um relatório de semana incompleta não se emite.
**Arquiva-se fora do repositório**, com a exportação que o gerou.

---

## 10. Exportação final, congelada

No fim do Piloto (e antes de qualquer leitura que alimente o KAM-110):

```text
python db/piloto_export.py exportar --coorte coorte.csv --real --saida piloto_export.json
python db/h6_export.py exportar --mensalidade-kz <§4 a dividir por 100> --saida h6_export.json
python -m piloto congelar piloto_export.json h6_export.json auditoria_P*.csv produtos_P*.csv \
    --saida piloto_congelado.json
python -m piloto medir --exportacao piloto_export.json --manifesto piloto_congelado.json \
    --mensalidade-minor <§4> --h6-export h6_export.json --auditorias . --semente <§8> \
    --saida piloto_resultados.json
```

**O `medir` recusa** (código 2, sem escrever nada) qualquer entrada que não
conste do manifesto com o mesmo `sha256`. Os nomes dos ficheiros são contrato
com o KAM-110. O `sha256` do manifesto entra na coluna `fonte` do
Registo de Hipóteses, e o conjunto arquiva-se em armazenamento controlado, fora
do repositório. A exportação não tem dados pessoais (lista fechada de campos),
mas tem `tenant_id`: é dado do sistema e não se publica.

Uma exportação de ensaio sai com `--sintetico`, e o `sintetico: true` passa para
o relatório («DADOS SINTÉTICOS») e para os resultados. **Nenhum resultado
sintético entra no Registo.**

---

## 11. Registo de horas do operador

Um CSV `horas.csv` com quatro colunas e nenhuma outra: `dia`, `pme` (o ordinal,
ou `-` para trabalho que não é de uma PME), `minutos` (1 a 720) e `categoria`
(`onboarding`, `t2`, `catalogo`, `cobranca`, `auditoria`, `incidente`,
`outro`). **Sem notas**: o operador fala com donos e clientes, e uma nota livre
era o sítio onde um nome ou um telefone ficavam guardados fora do sistema de
produção. Valida-se com `python -m piloto horas --registo horas.csv`. Um
incidente é uma linha da categoria `incidente`.

---

## 12. Desvios e emendas

* **Emenda**: qualquer alteração a este documento depois de assinado leva linha
  nova em «Controlo de versões» com o motivo, e as constantes do §7 mudam no
  mesmo *commit* que o código (o ensaio recusa o contrário).
* **Desvio**: um acontecimento que foge ao protocolo (uma substituição, uma
  auditoria fora da 4.ª semana, uma activação com intervenção humana, uma
  paragem) regista-se na tabela abaixo, com data e motivo, **sem dados
  pessoais**.

| Data | PME | Desvio | Motivo | Quem registou |
|---|---|---|---|---|
| | | | | |

---

## 13. Limites conhecidos, e o que fica devolvido

| # | Limite | Consequência | Credor |
|---|---|---|---|
| 1 | **«Acção do dono» conta por baixo.** O *echo* da app do dono só guarda o último instante por canal (`channel_coexistence.ultimo_echo_em`, `0018`), e o `owner_actions` não se lê pelo papel de lote (`0086`). Uma PME que só responde na app conta zero acções | «Activa» e «usar na semana 2» podem dar não a uma PME activa. Medir o *echo* por dia exige esquema novo, que esta preparação não cria | **Fundador**, ao assinar: aceitar a definição com este limite, ou pedir o esquema antes da 1.ª activação |
| 2 | **Não há registo de STT** (KAM-036) | H6 não sai `confirmada` (§6) | **KAM-036** |
| 3 | **As conversas são as da linha do tempo de saída**, como no `h6-export`: uma conversa sem resposta não aparece | «Activa» conta por baixo quando o bot não responde | Limite herdado do KAM-081 |
| 4 | **O preço real e o dia 1 do Piloto** estão em branco (§2, §4), e a semente de H8 também (§8) | O protocolo não se assina sem eles | **Fundador** |
| 5 | **A escolha do denominador de H9** quanto às substituídas (§2.1) | Muda o denominador de H9; o instrumento segue a coorte final | **Fundador**, ao assinar |

---

## 14. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Fundador (assina o protocolo e decide as hipóteses) | | | |
| Responsável de Produto | | | |
| Ops/Trust & Safety | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | 2026-11-25 | Emissão inicial, preparação do KAM-109 (lote 24), **por assinar**. Coorte, dia 0, substituição e paragem; cinco pré-condições; definições operacionais com fonte no sistema e estado; a regra de estado de H1, H6, H8 e H9; a tabela das dezoito constantes cruzada por ensaio com `tools/piloto/regras.py`; a auditoria de H8 com sorteio por `sha256` reprodutível sem o nosso código; o relatório semanal de modelo fixo com guarda de dados pessoais; a exportação congelada e os nomes de ficheiro que o KAM-110 consome; o registo de horas sem notas. **Em branco, por serem do fundador:** o preço real, o dia 1 do Piloto, a semente de H8 e as assinaturas. Cinco limites devolvidos com credor. | Coordenação do lote 24 |
