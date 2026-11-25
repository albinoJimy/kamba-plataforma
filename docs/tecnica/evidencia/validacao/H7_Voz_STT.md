# H7 — voz PT-AO: WER, latência e custo de dois STT

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — resultado do spike de voz PT-AO (KAM-107) |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-107 (EPIC-10) |
| Estado | NÃO VERIFICADO — o spike **não correu**: nenhum falante gravado, nenhum áudio enviado |
| Fonte | `../E4_Stack_Licencas.md` §3.2, §3.4, §3.5; `../E3_Regulatorio_Dados.md` req. 7 e 8; `../../08_Seguranca_Conformidade.md` §7.5; `../../09_Topologia_Operacao_Escala.md` §14.2, §14.3; F-01 (X1) de [`Pacote_Parecer_Juridico.md`](Pacote_Parecer_Juridico.md) |
| Dono | Responsável do spike (Engenharia de agentes/produto); a aceitação do risco da X1 e a assinatura da decisão são do **fundador** |
| Documento-fonte | `../../../../specs/EPIC-10_Spikes_Validacao_Gates.md`, bloco KAM-107 |
| Relacionados | [`Registo_Hipoteses.md`](Registo_Hipoteses.md) (linha H7), [`Seleccao_e_Registo_Juridico.md`](Seleccao_e_Registo_Juridico.md) (registo da X1), `../../../../spikes/voz-stt/` (o instrumento), `../../../../gov/subprocessadores.yaml` |

> **Este ficheiro nasce vazio de medições, e é isso que a preparação entrega.** O
> instrumento está feito e ensaiado com áudio sintético e um duplo determinístico
> — protocolo, roteiro, manifesto, transcodificação, *harness*, WER, latência,
> custo e o gerador das tabelas deste relatório. O que falta é o que **só pessoas
> podem fazer**: obter consentimentos, resolver a X1, gravar, anotar e decidir.
>
> Os **limiares** (§2) e a **regra de decisão** (§3) estão escritos e datados
> **antes** de qualquer medição, que é o que os «Testes Requeridos» pedem. As
> tabelas dos §4 a §6 geram-se com `spikes/voz-stt/relatorio.py` e colam-se aqui;
> **não se escrevem à mão**. Onde está `NÃO MEDIDO`, nada foi medido.

---

## 1. Pré-condições do envio

À letra do critério 2, nenhuma está cumprida a 2026-11-25. O *harness* recusa
enviar áudio sem as três primeiras (`spikes/voz-stt/autorizacao.py`).

| # | Pré-condição | Estado | Evidência a preencher |
|---|---|---|---|
| 1 | Consentimento escrito de cada falante, com o envio aos EUA | **por obter** — 0 falantes | Número de consentimentos e onde estão arquivados, pelo papel |
| 2 | X1 do KAM-104 respondida, **ou** risco aceite por escrito | **aberta** — o registo de respostas está vazio | Referência do parecer, ou do registo de aceitação, com data |
| 3 | Retenção e não-treino de cada fornecedor verificados e registados (`E3` req. 8) | **por verificar** — `retencao_zero: false` e `sem_treino: false` nas duas linhas do `gov/subprocessadores.yaml` | Por fornecedor: o que garante, fonte, data |
| 4 | Limiar de confiança fixado antes da primeira medição | **por fixar** — `null` no `limiares.json` | Valor por fornecedor e `registado_em` |
| 5 | Preços relidos nas páginas dos fornecedores, com data (critério 6) | **por reler** — o `precos.json` tem os de E4, de 2026-10-08 | Data e URL da releitura |

---

## 2. Limiares pré-registados, e as leituras que os tornam mensuráveis

**Registados a 2026-11-25** em `spikes/voz-stt/limiares.json`, transcritos à letra
do critério 4 do bloco, onde estão como *proposta* desde a versão 1.0 do epic
(Outubro de 2026). O `relatorio.py` **recusa** gerar tabelas se a data de registo
não for anterior à da primeira medição.

| Limiar (*proposta*) | Valor |
|---|---|
| WER global | ≤ 20% |
| Precisão numérica | ≥ 95% |
| Latência p95 do STT, clips ≤ 30 s | ≤ 3 s (fatia do orçamento de 12 s da voz) |
| Sinal de confiança | assinala ≥ 70% dos enunciados com WER > 40% |
| Valor de confiança abaixo do qual um enunciado está «assinalado» | **por fixar**, por fornecedor, antes de medir — o bloco não o dá |

**Leituras propostas.** A letra não diz como se calcula cada número; estas são as
escolhas do instrumento, escritas antes de medir para que não se escolham depois
de ver o resultado. Quem discordar muda-as **antes** do primeiro envio.

| Grandeza | Leitura | Onde está |
|---|---|---|
| WER de um conjunto | **Micro**: soma dos erros sobre a soma das palavras de referência, e não a média dos WER por clip | `wer.py` |
| Execução falhada no WER | Conta como **hipótese vazia** (todas as palavras omitidas): um STT que não responde não transcreveu bem | `relatorio.py` |
| Repetições do mesmo clip no WER | Conta a **primeira** execução de cada clip por fornecedor | `relatorio.py` |
| Precisão numérica | Dos *tokens* numéricos da referência, os que o alinhamento dá como acerto. Um número **inventado** pela hipótese não entra no denominador e conta-se à parte | `wer.py` |
| Normalização | Regras **versão 1**: minúsculas, sem pontuação, numerais e moeda iguais nas duas formas («mil e quinhentos kwanzas» = «1.500 Kz»), horas «14:30» = «14h30». **Os acentos ficam** | `normalizar.py` |
| Percentil | **Posto mais próximo**: o p95 de 30 valores é o 29.º | `latencia.py` |
| *Timeout* na latência | **Entra**, com o tempo que demorou; um erro HTTP não entra e conta só na taxa | `latencia.py` |
| Três momentos do dia | Manhã 06h–12h, tarde 12h–18h, noite 18h–24h, **hora de Luanda** (UTC+1); ≥ 30 execuções por tamanho e por fornecedor, com execuções nos três | `latencia.py` |
| Divergência entre anotadores | WER micro de A contra B **antes** de reconciliar, ≤ 3%; depois disso, todos os clips com referência reconciliada | `manifesto.py` |
| Custo por PME/mês | 300 min (doc 09 §14.3) com a distribuição de durações **do corpus** e o mínimo facturado por clip | `custo.py` |

**Duas limitações da normalização v1, escritas para não se descobrirem no
resultado:** uma hora dita «catorze e trinta» não iguala «14h30» e conta uma
substituição; e uma grafia PT-BR («fato», «fatura») conta como erro contra uma
referência PT-AO — o que pesa contra um STT treinado sobretudo em português do
Brasil. Tratar a segunda seria uma tabela de equivalências ortográficas, e isso
muda a pergunta que o WER responde: fica para o dono, antes de medir.

---

## 3. Regra de decisão

Transcrita **à letra** do critério 5 do bloco, e não resumida:

> ambos passam → o de menor custo é primário e o outro *fallback*; só um passa →
> esse é primário; nenhum passa → a voz fica só em *handoff* a humano no Piloto e
> remove-se da promessa comercial; falha apenas nos números → voz activa só com
> eco e confirmação dos números (alinhado com KAM-036). Decisão com dono e data.

O `relatorio.py` escreve a **indicação mecânica** do ramo que os números dão.
**Não é a decisão.** A decisão escreve-a uma pessoa no §7.

---

## 4. Corpus

As quotas são as do critério 1, à letra e como *proposta*. **Nada gravado.**

| Quota | Mínimo | Medido |
|---|---|---|
| Falantes | 10 | NÃO MEDIDO |
| Enunciados de 5 a 30 s | 200 | NÃO MEDIDO |
| Com números, preços, quantidades ou horas | 40% | NÃO MEDIDO |
| Com Kimbundu, Umbundu ou mistura de línguas | 20% | NÃO MEDIDO |
| Em ambiente ruidoso | 20% | NÃO MEDIDO |
| Transcodificado para Opus/OGG como no WhatsApp | todos | NÃO MEDIDO |
| Divergência entre anotadores antes de reconciliar | ≤ 3% | NÃO MEDIDO |

O roteiro tem **220** enunciados, com **155 (70%)** marcados com números e **60
(27%)** com palavras de línguas nacionais; as folhas por falante dão 6 de 22
(27%) em ruído. São proporções **do roteiro**, e não do corpus: o corpus mede-se
depois de gravar, porque um clip pode perder-se.

---

## 5. Resultados por STT

**NÃO MEDIDO.** Cola-se aqui a saída do `relatorio.py`, sem editar. Por STT, e
pela ordem do critério 3:

- WER global e por grupo (números, línguas, ruído, silêncio);
- precisão de *tokens* numéricos, e números inventados;
- latência p50 e p95 para clips de 5, 15 e 30 s, com as execuções por momento do
  dia;
- taxa de erro ou *timeout*;
- se a API devolve sinal de confiança (**S/N — NÃO VERIFICADO até testar**), e a
  fracção dos enunciados de WER alto que esse sinal assinala;
- a avaliação contra cada limiar e a indicação mecânica da regra.

---

## 6. Custo

| | Groq `whisper-large-v3-turbo` | OpenAI `gpt-4o-mini-transcribe` |
|---|---|---|
| Preço | $0,04/hora (INDÍCIO-forte, E4 §3.4) | $0,003/min (CONFIRMADO, E4 §3.2) |
| Mínimo facturado | 10 s (INDÍCIO-forte, E4 §3.4) | NÃO VERIFICADO |
| Lido em | 2026-10-08 (E4) — **por reler** | 2026-10-08 (E4) — **por reler** |
| ESTIMATIVA por PME/mês, 300 min (doc 09 §14.3) | ≈ $0,2 | ≈ $0,9 |
| Medido, por hora de áudio | NÃO MEDIDO | NÃO MEDIDO |
| Medido, por PME/mês | NÃO MEDIDO | NÃO MEDIDO |

**O mínimo de 10 s pesa**, e já se vê sem medir: com clips de 8 s o Groq paga 10
s por clip, e a hora de áudio sai a $0,05 em vez de $0,04 — o ensaio
`test_gera_sem_identificacao` fixa-o. A estimativa do doc 09 não tem mínimo
nenhum, e fica **abaixo** do que um corpus de notas curtas vai custar.

---

## 7. Decisão

**Por tomar.** O bloco exige «decisão com dono e data», e o DoD manda registá-la
e informar o KAM-036 (STT e regra de eco e confiança).

| Campo | Valor |
|---|---|
| Ramo da regra (§3) | |
| STT primário | |
| *Fallback* | |
| Regra de eco e confiança para o KAM-036 | |
| Razões, se a decisão se afastar da indicação mecânica | |
| Dono | |
| Data | |

---

## 8. Subprocessadores, H7 e o que mais depende disto

- **Inventário (KAM-069).** As duas linhas **já existem** no
  `gov/subprocessadores.yaml` — `groq` (transcrição) e `openai` (LLM e
  transcrição) —, ambas `pendente`, com `apd_ref: null`, `retencao_zero: false` e
  `sem_treino: false`. O critério 7 pede que «os fornecedores usados» entrem com o
  estado do `apd_ref`; **quais são os usados decide-o o spike**, e actualizar as
  duas flags com a verificação do §1 é acto de quem a fez.
- **H7.** A parte de voz de H7 («≥ 85% sem *handoff* errado», `14` §2) fica
  **dependente desta decisão e do golden (KAM-040)**, à letra do critério 7. A
  linha H7 do `Registo_Hipoteses.md` não muda com esta preparação.
- **`E4` §3.5.** O item NÃO VERIFICADO «qualidade em português de Angola» fica com
  estado final quando este relatório tiver medições (DoD).

---

## 9. Privacidade e apagamento

| Registo | Valor |
|---|---|
| Consentimentos arquivados (quantos, e onde, pelo papel) | |
| Data do primeiro envio | |
| Data do apagamento pelo `apagamento.py apagar` | |
| Ficheiros apagados / já ausentes / no manifesto | |
| `apagamento.py verificar` depois de apagar | |
| Originais apagados do aparelho do operador (contagem e data) | |
| Outras cópias apagadas (anotadores, cópias de segurança) | |

**Este relatório não tem, nem pode ter, áudio nem identificação de falantes.** O
`relatorio.py` recusa gerar texto com um pseudónimo, um `clip_id`, um nome de
ficheiro de áudio, uma sequência de nove ou mais algarismos ou um bloco com forma
de base64, e não escreve hipóteses nem referências.

---

## 10. Itens devolvidos

| # | Item | Credor |
|---|---|---|
| 1 | **Resolver a X1**: parecer escrito, ou risco aceite por escrito | **Fundador** (via KAM-104) |
| 2 | Gravar antes da X1, ou só depois — a letra só fala de enviar | **Fundador** |
| 3 | Prazo entre gravar e transcrever, e retenção das transcrições | **Fundador** |
| 4 | Verificar retenção zero e não-treino dos dois fornecedores, e actualizar o inventário | Responsável do spike |
| 5 | Fixar o limiar de confiança por fornecedor, com data, antes de medir | Responsável do spike |
| 6 | Reler os preços e o mínimo facturado da OpenAI, com data | Responsável do spike |
| 7 | Confirmar os *endpoints* e a forma das respostas (NÃO VERIFICADO no `fornecedores.py`) | Responsável do spike |
| 8 | Confirmar a lista de palavras de línguas nacionais com um anotador falante | Responsável do spike |
| 9 | Equivalências ortográficas PT-BR/PT-AO no WER — sim ou não, antes de medir | Responsável do spike |
| 10 | Recrutar, gravar, anotar, medir, decidir e apagar | Responsável do spike e **fundador** |

---

## Tabela de aprovação

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Responsável do spike |  |  |  |
| Fundador |  |  |  |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, preparação do KAM-107 no lote 24: modelo do relatório com as pré-condições do envio, os limiares pré-registados a 2026-11-25 e as leituras que os tornam mensuráveis, a regra de decisão transcrita, e as tabelas de corpus, resultados, custo, decisão e apagamento por preencher. Nada medido. | Coordenação do lote 24 |
