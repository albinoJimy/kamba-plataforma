# ADR-L003 — Onde vive o *token* que verifica o *ruleset* de `main`

| Campo | Valor |
|---|---|
| Estado | Aceite |
| Data | 2026-10-18 |
| Ticket | KAM-137 — Verificação do *ruleset* de `main` e onde vive o *token* de administração |
| Âmbito | Local (ver [`README.md`](README.md)): que poder tem a credencial que compara o *ruleset* com o espelho, e onde ela vive. Não decide que regras o *ruleset* tem — isso é governação |
| Decisores | O fundador, a 2026-10-18 (ratificação do Arquitecto de Plataforma e do Responsável de Segurança fica pendente de esses papéis existirem) |
| ADRs canónicos aplicáveis | ADR-008 (dados pessoais fora de Angola) |
| Documentos aplicáveis | [`../ci.md`](../ci.md) §6 e §7; [`../tecnica/08_Seguranca_Conformidade.md`](../tecnica/08_Seguranca_Conformidade.md) §4.8 e §5; [`../../.github/rulesets/README.md`](../../.github/rulesets/README.md) |
| Substitui | — |

## Contexto

O *ruleset* `main: gates fail-closed do KAM-002` é a peça de que toda a
propriedade *fail-closed* depende: sem ele os *gates* correm, reportam, e nada
impede o *merge*. Vive na API do GitHub, altera-se sem PR e sem revisor, e não
deixa rasto no repositório.

O KAM-002 espelhou-o em
[`../../.github/rulesets/main.json`](../../.github/rulesets/main.json). O
espelho não é aplicado por nada: editá-lo não altera o GitHub, e alterar o
GitHub não o actualiza. A volta está aberta nos dois sentidos, e um ficheiro que
parece ser a fonte e não é engana melhor do que a ausência dele.

Fechar a volta exige falar com a API, e a API dos *rulesets* exige a permissão
`Administration` do repositório. **É por isso que isto não se fecha de
passagem**: a permissão de escrita dessa família é a mais perigosa que existe
neste contexto — quem a tem desliga os *gates* todos, apaga o *ruleset*, e nada
no CI do repositório o detecta, porque o CI é precisamente o que ela desliga.

O KAM-002 tem como critério de aceitação «sem chaves estáticas» e o
`../tecnica/08` §4.8 exige OIDC. Um *token* de administração guardado nos
segredos do repositório contradiz os dois.

### As quatro opções, e o que cada uma custa

| Opção | O que resolve | O que custa |
|---|---|---|
| **A** — GitHub App própria, com `administration: write` e *token* de instalação de curta duração | Fecha a volta nos dois sentidos sem chave estática; auditável por instalação | Uma App para manter, e a sua chave privada passa a ser o segredo crítico. O poder concedido continua a ser o de desligar todos os *gates* |
| **B** — Verificação **fora** do CI do repositório, com poder de escrita | Não põe o *token* no CI que ele poderia desligar | Deixa de ser *gate* de PR; e o poder de escrita continua lá, só noutro sítio |
| **C** — Só detecção, com *token* de leitura (`administration: read`), que compara e nunca aplica | Apanha a divergência nos dois sentidos, com a permissão mínima que a API aceita | Não repõe o *ruleset*: alguém tem de agir sobre o alerta |
| **D** — Revisão humana periódica contra o `main.json`, sem *token* | Sem credencial nova | Depende de disciplina, que é o que o KAM-002 existe para não depender |

## Decisão

**(C) Só detecção, com um *token* de leitura (`Administration: Read-only`), que
compara e nunca aplica.** Decidida pelo fundador a 2026-10-18.

Concretamente:

1. A verificação é `tools/ruleset_check`, corrida por `make ruleset`. Lê o
   *ruleset* efectivo da API, normaliza-o, compara-o com o espelho versionado e
   devolve **1** quando divergem. **Não tem caminho de escrita**: não existe no
   módulo nenhuma chamada `POST`, `PUT`, `PATCH` ou `DELETE`, e há um teste que o
   exige.
2. A verificação **não corre no CI deste repositório** e não é *required check*
   de nenhum PR. Corre à mão, ou de um contexto fora destas Actions.
3. Quando divergem, o alerta é o que se vê na saída, e o que fazer com ele está
   escrito em [`../../.github/rulesets/README.md`](../../.github/rulesets/README.md).
   A reposição é **manual**, pelo fundador, na interface do GitHub.

### Porquê (C), e não cada uma das outras

**Porque não (A), a GitHub App.** É a opção tecnicamente mais limpa e a que
resolve mais — e resolve coisa nenhuma que este ticket precise. O que falta hoje
é **detectar** a divergência; repor o *ruleset* automaticamente é conveniência, e
paga-se com uma credencial que desliga todos os *gates*. Trocar «o fundador
corrige à mão uma vez por ano» por «existe no mundo uma chave privada que apaga o
*ruleset*» é um mau negócio num repositório com um contribuidor. A App fica como
caminho de evolução, não como desenho rejeitado por princípio: o gatilho está
no §6.

**Porque não (B).** (B) e (C) não são alternativas no mesmo eixo: (B) decide
*onde corre*, (C) decide *quanto poder tem*. A decisão toma de (B) a parte
boa — a verificação não corre dentro do CI que a credencial poderia desligar — e
recusa a parte má, que é manter o poder de escrita. O que fica é (C) corrida
fora do CI.

**Porque não (D).** É a situação actual, e é o que o KAM-002 existe para não
depender. Uma comparação de `required_status_checks` feita a olho contra um JSON
de sessenta linhas falha exactamente no caso que interessa: um `bypass_actor`
acrescentado, que é uma entrada numa lista que normalmente está vazia e que
ninguém relê.

### E há uma razão medida para não ser *gate* de PR

A verificação **não pode** correr no CI deste repositório sem contrariar o
critério «sem chaves estáticas», e isto não é preferência:

- O `GITHUB_TOKEN` das Actions **não tem** a família `administration` entre as
  permissões que o bloco `permissions:` de um *workflow* aceita. Logo não lê
  *rulesets* — **NÃO VERIFICADO por execução neste ticket**; valida-se
  acrescentando `permissions: {administration: read}` a um *workflow* de
  teste e vendo o GitHub recusar o ficheiro, ou correndo
  `gh api repos/albinoJimy/kamba/rulesets` dentro de um *job* com o
  `GITHUB_TOKEN` e lendo o `403`.
- Qualquer outro *token* teria de vir do cofre de segredos do GitHub, e uma
  referência `secrets.*` num *workflow* é exactamente o que a regra
  `chave-estatica-no-ci` do *gate* 11 recusa
  (`tools/supply_chain/ci_chaves.py`). O `grep` do `../ci.md` §6 continua a
  devolver zero depois deste ticket, e continua a devolvê-lo **porque nenhum
  ficheiro de `.github/workflows/` foi tocado**.

O custo desta posição está dito e não é pequeno: **a divergência é detectada
quando alguém corre a verificação, e não no momento em que acontece.** Isso é
uma degradação face a um *gate*, e é a troca que (C) assume.

## A credencial

| Pergunta | Resposta |
|---|---|
| **O quê** | Um *fine-grained personal access token* do GitHub, sobre os repositórios `albinoJimy/kamba` e `albinoJimy/kamba-plataforma` |
| **Que permissões** | **Uma só: `Administration: Read-only`.** Nenhuma de escrita, em lado nenhum. Sem `Contents`, sem `Actions`, sem `Workflows`, sem `Secrets`, sem `Webhooks` |
| **Onde vive** | **Nunca no repositório, nunca nos segredos do GitHub, nunca num ficheiro de `.github/workflows/`.** Dois sítios sancionados: (1) o porta-chaves do `gh` na máquina de quem opera (`gh auth login`), que é o caminho por omissão — o `make ruleset` chama `gh api`, e o valor não passa pelo nosso código nem pelo ambiente; (2) a variável `KAMBA_RULESET_TOKEN` no contexto fora destas Actions, se e quando a verificação periódica for montada, guardada no cofre desse contexto |
| **Quem a pode usar** | Quem tem administração do repositório: hoje o fundador; amanhã o Arquitecto de Plataforma e o Responsável de Segurança. **Um *token* por pessoa, nunca partilhado** — um *token* partilhado não se revoga sem parar toda a gente, e deixa de dizer quem o usou |
| **Como se roda** | Validade de **90 dias**, fixada na criação. Rodar é criar o novo, confirmar com `make ruleset`, e revogar o antigo em `github.com/settings/tokens`. Não há cofre pelo meio, não há reinício de serviço nenhum, e por isso não há anel `[actual, anterior]`: a rotação é de um minuto e falha ruidosamente (o `gh` devolve `401` e a verificação sai **2**) |
| **Se for comprometida** | O raio de acção é **divulgação, não alteração**: quem tenha o *token* lê a configuração de administração do `kamba` (privado) e do `kamba-plataforma` (público) e **não pode mudar nada** — nem o *ruleset*, nem os *gates*, nem um segredo. Resposta: revogar em `github.com/settings/tokens`, criar outro, e correr `make ruleset` para confirmar que o *ruleset* não foi alterado entretanto. **É esta linha que decide o ADR**: com `administration: write` esta célula diria «o atacante desliga todos os *gates* e apaga o `main`» |

**Porque é que não entra em `ops/secrets-inventory.yaml`.** O inventário do
KAM-010 é de segredos de execução: têm um cofre (Doppler no Piloto, OpenBao nos
Clusters), `consumidores` que são códigos de serviço do `../tecnica/00` §4, e
chegam ao processo pelo mecanismo do
[`ADR-L002`](ADR-L002-injeccao-de-segredos.md). Este *token* não tem nenhuma
dessas três coisas: não vive no cofre, nenhum serviço o consome, e nenhum
processo do produto o recebe. É uma credencial de **operação do repositório**,
detida por uma pessoa. Forçá-la para dentro do inventário obrigaria a inventar
um consumidor e um cofre que não existem. Fica aqui, com rotação definida, e
esta é a linha a contrariar se o fundador preferir o contrário.

## Consequências

- O espelho deixa de poder envelhecer em silêncio **quando a verificação corre**.
  Entre execuções, pode.
- A reposição é manual e tem procedimento escrito. Sem isso, a resposta ao
  alerta seria inventada no momento, que é o que o ticket pede para evitar.
- A comparação é sobre política, e a lista do que entra e do que fica de fora
  está em `tools/ruleset_check/comparador.py` e repetida no
  [`README.md`](../../.github/rulesets/README.md) do *ruleset*. Um campo que a
  API passe a devolver e que não esteja em nenhuma das duas listas **falha** a
  verificação em vez de passar despercebido.
- Não há dependência nova: só biblioteca padrão, e o `gh` que o repositório já
  usa. Nada entra no `pnpm-lock.yaml` nem no SBOM, e portanto nada no veredicto
  de licenças do *gate* 11.
- O `../ci.md` §6 não muda: continua a não haver chaves estáticas nos
  *workflows*, porque nenhum *workflow* foi tocado.

## §6 — Quando reverter, e o que falta

**Gatilhos para subir a (A), a GitHub App com escrita:**

1. Uma divergência real detectada que tenha ficado por repor tempo de mais —
   isto é, quando o custo medido de «alguém tem de agir sobre o alerta» passar a
   ser maior do que o risco de ter a chave. Até hoje, zero divergências
   detectadas.
2. Um segundo repositório sob o mesmo *ruleset*, ou um segundo *ruleset*, onde a
   reposição à mão deixe de ser um minuto.
3. Equipa com mais do que um administrador, em que «o fundador corrige» deixe de
   nomear uma pessoa.

Reverter custa: a App, a chave privada no cofre, e o caminho de escrita no
módulo — que hoje não existe de propósito e tem um teste a garanti-lo.

**Lacunas declaradas desta decisão, para não serem descobertas tarde:**

- **A verificação só corre quando alguém a corre.** Não há agendamento. Montá-lo
  exige um contexto fora destas Actions, que não existe, e inventá-lo aqui seria
  desenho especulativo. É a diferença entre esta decisão e um *gate*, e está
  escrita no §6 do [`README.md`](../../.github/rulesets/README.md).
- **O `kamba-plataforma` não tem *ruleset* nenhum.** Medido a 2026-10-18:
  `gh api repos/albinoJimy/kamba-plataforma/rules/branches/main` devolve `[]`,
  enquanto o mesmo comando no `kamba` devolve as quatro regras. O repositório
  público, que é onde os PR são abertos hoje, não tem nenhuma das protecções que
  este ADR existe para vigiar. **Criar lá um *ruleset* é governação e não é deste
  ticket**; o que este ticket faz é dar o instrumento que o diz em voz alta, e
  deixar a medição escrita em [`../evidencia/KAM-137.md`](../evidencia/KAM-137.md).
- **O `GITHUB_TOKEN` não ter `administration`** é a razão medida por que isto não
  é um *gate*, e está **NÃO VERIFICADO** por execução (ver acima como se valida).
- **A permissão mínima pode não ser mínima.** `Administration: Read-only` dá
  também leitura de outras definições do repositório além do *ruleset*. O GitHub
  não oferece hoje uma permissão só para *rulesets*. Se vier a oferecer, esta
  decisão desce mais um degrau sem mudar de forma.
