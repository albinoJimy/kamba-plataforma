# Protocolo do spike de voz PT-AO — gravação, anotação, envio e apagamento (KAM-107)

| Campo | Valor |
|---|---|
| Ticket | KAM-107 (EPIC-10) |
| Estado | Proposta — **não executado**: nenhum falante recrutado, nada gravado |
| Fonte | Bloco KAM-107 de `specs/EPIC-10_Spikes_Validacao_Gates.md` (critérios 1 a 3); `docs/tecnica/08_Seguranca_Conformidade.md` §7.5; `docs/tecnica/evidencia/E3_Regulatorio_Dados.md` req. 7 e 8; pergunta F-01 (X1) de `docs/tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md` |
| Dono | Responsável do spike (Engenharia de agentes/produto, o «responsável sugerido» do bloco); o **fundador** nos actos marcados como dele |

Este protocolo é a sequência que leva do roteiro ao relatório sem que um passo
fique sem dono e sem que áudio de uma pessoa fique onde não deve. **Nenhum passo
foi feito.** Os prazos que o bloco fixa estão à letra; os que o bloco não fixa
**não se inventam aqui** e estão no §9, devolvidos.

---

## 0. Papéis

| Papel | Quem | O que faz | O que não faz |
|---|---|---|---|
| Responsável do spike | Engenharia de agentes/produto | Conduz o protocolo, guarda o manifesto e os resultados fora do repositório, corre os *scripts*, preenche o relatório | Não fala pelo fundador; não decide o STT sozinho |
| Fundador | — | Aceita o risco da X1 por escrito, se essa for a via; guarda o arquivo dos consentimentos; assina a decisão do STT | — |
| Operador de gravação | Uma pessoa da equipa | Grava com o seu aparelho, transcodifica, apaga o original | Não grava com o telemóvel do falante; não envia nada pelo WhatsApp |
| Anotadores A e B | Duas pessoas, falantes de PT-AO, **nenhuma delas falante do corpus** | Transcrevem cada clip de forma independente | Não veem o roteiro enquanto anotam, nem a anotação do outro, nem a saída dos STT |
| Reconciliador | Uma terceira pessoa, ou A e B juntos | Fixa a referência quando A e B divergem | Não ouve a saída dos STT |

---

## 1. Pré-condições, e quando cada uma tem de estar cumprida

| # | Pré-condição | Fonte | Antes de |
|---|---|---|---|
| P1 | Consentimento escrito de cada falante, com o envio a **cada um** dos dois fornecedores nos EUA (`consentimento.md`) | Critério 2 | Gravar esse falante |
| P2 | A pergunta **X1** do KAM-104 respondida por parecer escrito **ou** o risco aceite por escrito pelo fundador, **e** dita como permitindo o envio (`permite_envio`) | Critério 2; F-01 do pacote | **Enviar** áudio (à letra); ver §9, item 1, sobre gravar |
| P3 | Retenção zero e não-treino de cada fornecedor verificados, com data e fonte | Critério 2; `E3` req. 8 | Enviar áudio a esse fornecedor |
| P4 | `limiares.json` com o limiar de confiança fixado e datado (`registado_em`), **num dia anterior** ao primeiro envio | Critério 4; «Testes Requeridos» | Enviar áudio |
| P5 | Preços relidos nas páginas dos fornecedores, com data, no `precos.json` | Critério 6 | Gerar o relatório |
| P6 | Lista de palavras de línguas nacionais do `roteiro.py` confirmada por um anotador falante | Critério 1 (≥ 20% com Kimbundu/Umbundu) | Imprimir as folhas |
| P7 | Parâmetros das notas de voz do WhatsApp confirmados por `ffprobe` (§4) | Critério 1 («como no WhatsApp») | Transcodificar |

**Estado hoje (2026-11-25):** nenhuma está cumprida. A X1 está **aberta** — o
registo de respostas do `Seleccao_e_Registo_Juridico.md` §3 nasce vazio e
continua vazio, porque o pacote não foi enviado. As duas linhas dos fornecedores
no `gov/subprocessadores.yaml` estão `pendente`, com `retencao_zero: false`,
`sem_treino: false` e `apd_ref: null`.

As pré-condições P1, P2 e P3 escrevem-se num ficheiro de autorização (forma no
cabeçalho do `autorizacao.py`) **por uma pessoa**, fora do repositório; o
*harness* recusa enviar sem ele completo.

---

## 2. Recrutamento

- **≥ 10 falantes**, cada um com uma folha de 22 enunciados (`python roteiro.py
  folha N`). Com 10 falantes saem 220 enunciados, acima dos 200 do critério, com
  folga para clips que se percam.
- **Só maiores de idade** (*proposta*): o consentimento de um menor exige
  representante legal, e a forma disso é **NÃO VERIFICADO**.
- **Diversidade de pronúncia sem registo de dados demográficos.** Procura-se
  variedade (idade, sexo, província de origem, quem fale Kimbundu ou Umbundu em
  casa), mas **nada disso vai para o manifesto nem para o relatório**: com dez
  pessoas, cruzar dois atributos identifica uma. O WER por grupo do critério 3 é
  por números, línguas e ruído — grupos do **enunciado**, não da pessoa.
- Cada falante recebe um **pseudónimo** `F01`–`F10`. A correspondência entre nome
  e pseudónimo existe **só** no arquivo dos consentimentos (§8), nunca no
  manifesto, nos resultados ou no relatório.

---

## 3. Preparar o roteiro

1. Um anotador falante lê a lista `PALAVRAS_DE_LINGUAS_NACIONAIS` do `roteiro.py`
   e confirma ou corrige cada palavra. Uma linha do `roteiro.tsv` cuja única
   palavra marcada caia passa a `linguas = N`, e o ensaio
   `test_marca_de_linguas_bate_com_a_lista` obriga a mudar as duas coisas juntas.
   Se a proporção cair abaixo de 20%, acrescentam-se enunciados — por PR, para
   que o roteiro gravado seja o que está versionado.
2. Imprimem-se as 10 folhas. Os 6 enunciados marcados `[RUÍDO]` gravam-se no
   ambiente ruidoso.

---

## 4. Gravação

- **Aparelho do operador, não do falante**, com uma aplicação de gravação de som
  (WAV ou M4A). Assim não fica cópia no telemóvel de quem falou. **Não se grava
  nem se envia pelo WhatsApp**: uma nota de voz enviada passa pela plataforma, e
  áudio que passa pela plataforma é dado dela (`E1` §4, ADR-018). **A
  sincronização automática do aparelho com a nuvem desliga-se antes de gravar**
  (gravador, galeria, cópia de segurança do telemóvel): uma cópia que sobe
  sozinha é um envio a um terceiro que o consentimento não cobre.
- **Silêncio:** uma sala fechada. **Ruído** (6 de 22): ruído real de ambiente —
  trânsito, gerador, ventoinha, rádio ou música, cozinha. **Sem conversa
  inteligível de terceiros perto do microfone**: a voz de quem não consentiu não
  entra no corpus.
- O falante **lê com naturalidade e diz os números como os diria** («14h30» pode
  sair «catorze e trinta» ou «duas e meia»); os anotadores escrevem o que ouviram,
  não o que está na folha. **Pede-se que não diga o nome, o número de telefone nem
  nenhum dado seu** durante a gravação; se o disser, o clip grava-se outra vez e
  o anterior apaga-se.
- Um enunciado que saia com **menos de 5 s** lê-se outra vez, mais pausado; se
  continuar abaixo, fica fora (o `manifesto.py` recusa-o).
- Nomes de ficheiro: `F01/C0001.ogg` — pseudónimo e número de clip sequencial,
  nada mais.
- **Parâmetros do WhatsApp (P7):** um membro da equipa grava uma nota de voz da
  sua própria leitura, envia-a a si próprio, e corre-se `ffprobe` sobre o ficheiro
  — **só os metadados** (codec, canais, taxa do cabeçalho, *bitrate*). Se diferirem
  de 16 kHz e ~24 kbit/s, acertam-se as variáveis `KAMBA_VOZ_TAXA` e
  `KAMBA_VOZ_BITRATE`. A nota apaga-se a seguir.

No mesmo dia: `transcodificar.sh opus` sobre cada gravação, `transcodificar.sh
duracao` para a coluna `duracao_s`, e **o original apaga-se do aparelho do
operador**, com a contagem registada no §9 do relatório.

---

## 5. Anotação e reconciliação

- A e B ouvem cada clip **separadamente**, sem o roteiro, sem a anotação do outro
  e sem nenhuma saída de STT, e escrevem o que foi dito nas colunas `ref_a` e
  `ref_b` do manifesto.
- **Convenções:** grafia do conjunto documental (PT-AO, sem o Acordo de 1990:
  «factura», «acção»); números como foram ditos, por extenso ou em algarismos — o
  normalizador iguala as formas mais comuns; sem marcas de pontuação obrigatórias; uma
  palavra que não se perceba escreve-se como se ouviu, sem marcas tipo `[?]`.
  **O normalizador não iguala todas as formas** — as limitações estão no
  `H7_Voz_STT.md` §2 —, e por isso os dois anotadores escrevem as horas e os
  milhares da mesma maneira: «14h30» e «12.500», nunca «12 500».
- `python manifesto.py manifesto.csv` calcula a divergência entre A e B **antes
  de reconciliar** (WER micro de A contra B). O critério pede **≤ 3%**; acima disso
  não se reconcilia por cima — reveem-se as convenções com os dois e anota-se de
  novo.
- O reconciliador preenche `ref` em todos os clips. O verificador exige as três
  colunas preenchidas e 0 achados antes de qualquer envio.

---

## 6. Clips de latência

- Para cada tamanho — 5, 15 e 30 s —, montam-se clips de **um só falante** com
  `transcodificar.sh juntar SAIDA ALVO ENTRADAS...`, que concatena e corta no
  alvo. Vão para o manifesto com `tipo = latencia` e os enunciados juntos com `+`.
- Corre-se `harness.py correr --tipo latencia --repeticoes 10` para cada
  fornecedor **de manhã, à tarde e à noite** (hora de Luanda, `latencia.py`): 30
  execuções por tamanho e por fornecedor, nos três momentos.

---

## 7. Envio — dentro de 24 horas

O relógio das 24 h do critério 2 começa na **primeira transcrição** de cada clip.
Por isso a anotação (§5) acaba **antes** do primeiro envio, e o dia do envio
organiza-se assim:

1. `manifesto.py` → 0 achados. Ficheiro de autorização completo (P1–P3). P4 com
   data anterior.
2. A chave de cada fornecedor passa do cofre para `KAMBA_VOZ_CHAVE_GROQ` ou
   `KAMBA_VOZ_CHAVE_OPENAI`, só na sessão de terminal do operador.
3. Manhã: passagem de WER (`--tipo enunciado`) nos dois fornecedores, e a
   primeira ronda de latência. Tarde e noite: as outras duas rondas.
4. `apagamento.py verificar` no fim do dia, e `apagamento.py apagar --confirmo`
   **antes** das 24 h, depois da última ronda.

O primeiro envio real é também a primeira leitura das respostas reais: se os
campos de confiança não vierem como o `fornecedores.py` espera, a resposta ao
critério 3 é «N» para esse fornecedor e o *harness* continua — não é falha.

---

## 8. Apagamento e arquivo

- `apagamento.py apagar` apaga os ficheiros que o manifesto nomeia; `verificar`
  confirma que nenhum sobra. O que o *script* não vê apaga-se à mão e regista-se:
  o original no aparelho do operador (§4), qualquer cópia feita para os
  anotadores, e qualquer cópia de segurança automática do computador **e do
  telemóvel** do operador, incluindo a que tenha subido para a nuvem.
- **Os consentimentos assinados** vão para um arquivo controlado escolhido pelo
  fundador, fora do repositório; o relatório diz quantos são e onde estão
  **pelo papel**, nunca por nome.
- O relatório (`H7_Voz_STT.md` §9) regista a data e as contagens do apagamento.

---

## 9. Devolvido — o que o bloco não fixa e este protocolo não decide

| # | Item | Porque não se decide aqui | Credor |
|---|---|---|---|
| 1 | **Gravar antes da X1?** A letra exige a X1 antes de **enviar**; mas a alínea (i) da X1 pergunta se o **tratamento** é lícito antes do procedimento da APD, e gravar já é tratamento | Ler a pré-condição como «antes de gravar» é mais conservador do que a letra, e escolher entre as duas leituras é decisão de risco regulatório | **Fundador** |
| 2 | **Prazo entre gravar e transcrever.** O bloco fixa ≤ 24 h depois de transcrever e no fim do spike; não fixa quanto tempo o áudio pode esperar pela anotação | É regra de retenção | **Fundador** |
| 3 | **Retenção das transcrições** (manifesto e resultados, que são texto do que as pessoas disseram) | Idem | **Fundador** |
| 4 | Quem são os anotadores e o reconciliador, e se os falantes são compensados | Recrutamento e orçamento | Responsável do spike, com o fundador |
| 5 | O limiar de confiança por fornecedor (P4) | O bloco fixa a fracção (≥ 70%) e o corte de WER (> 40%), não o valor de confiança abaixo do qual um enunciado se dá por assinalado | Responsável do spike, **antes** de medir |
| 6 | A forma jurídica do consentimento | É a alínea (iii) da X1 | Parecer do KAM-104, ou o fundador |
| 7 | **Um STT cuja API não devolve sinal de confiança: o limiar de confiança «falha» ou «não se mede»?** O instrumento lê «não medido», e com isso a regra de decisão fica «não aplicável» aos dois STT | A letra põe o sinal como limiar e diz que a confiança é «NÃO VERIFICADO até testar»; ler a ausência como falha ou como não medição muda o ramo da regra | **Fundador**, antes de medir |
