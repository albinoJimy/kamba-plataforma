# ADR-L002 — Mecanismo de injecção de segredos nos contentores

| Campo | Valor |
|---|---|
| Estado | Aceite |
| Data | 2026-10-11 |
| Ticket | KAM-010 — Gestão de segredos e chaves (Doppler no Piloto, interface OpenBao) |
| Âmbito | Local (ver [`README.md`](README.md)): como os segredos chegam ao processo, não que cofre se usa |
| Decisores | Executor do KAM-010 (a ratificar pelo Responsável de Segurança) |
| ADRs canónicos aplicáveis | ADR-008 (dados pessoais fora de Angola), ADR-010 (pepper no cofre), ADR-014 (licenças) |
| Substitui | — |

## Contexto

O KAM-010 manda escolher aqui uma coisa que `../tecnica/` não diz: **como é que o
valor de um segredo chega ao processo dentro do contentor**. O `../tecnica/08` §5
decide o *cofre* (Doppler no Piloto, OpenBao nos Clusters) e a *política*
(nenhum segredo em imagem, repositório, log ou *trace*; chaves por ambiente;
rotação por segredo). Não decide o mecanismo.

As duas opções que o ticket nomeia:

- **(A) variáveis de ambiente** injectadas no arranque do processo do contentor;
- **(B) ficheiros em `tmpfs`** montados no contentor e lidos pela aplicação.

A escolha não é de estilo. Decide quem pode ler um segredo depois de ele entrar
no contentor, o que acontece numa rotação, e quanta máquina é preciso operar
para que o arranque funcione. É herdada pelo KAM-013, KAM-016, KAM-030, KAM-056
e KAM-072, que o backlog mestre lista como bloqueados por este ticket.

### O que cada opção custa de verdade

| | (A) variáveis de ambiente | (B) ficheiros em `tmpfs` |
|---|---|---|
| Quem mais vê o valor | o ambiente do processo (`/proc/<pid>/environ`, legível pelo próprio UID e pelo root) e **todos os processos-filho**, que o herdam | só quem abre o ficheiro; permissões por segredo (`0400`, dono do processo) |
| `docker inspect` | mostra o que está no `environment:` do compose — por isso **nada** vai para lá (ver §4) | nunca mostra conteúdo de `tmpfs` |
| Despejo acidental | um *framework* que imprime o ambiente numa página de erro leva tudo | um `cat` deliberado leva um |
| Rotação sem reinício | **não** — o ambiente de um processo não muda depois do `exec` | sim: relê o ficheiro |
| Maquinaria para funcionar | um lançador (`doppler run -- …`) | um agente ou *sidecar* que escreva os ficheiros, e um ponto de montagem por serviço |
| Modo de falha novo | nenhum | montagem vazia ou tardia = serviço sem segredos, numa falha que se parece com «segredo ausente» sem o ser |
| Swap | não aplicável | `tmpfs` pode ir para *swap* sem `noswap` (Linux ≥ 6.4) ou sem *swap* desligado — NÃO VERIFICADO no anfitrião que ainda não existe (D1) |

## Decisão

**(A) Variáveis de ambiente injectadas no arranque do processo do contentor.**

Concretamente, nos três ambientes do Piloto:

1. O comando do contentor é embrulhado por um lançador que obtém os segredos do
   cofre e os põe no ambiente do processo filho — `doppler run -- <comando>` no
   Piloto. Em `dev`, o lançador é o próprio `.env` local.
2. Os nomes das variáveis são os que `packages/core-ts/src/secrets/env.ts` e
   `libs/py-core/src/kamba_core/secrets/env.py` definem: `KAMBA_SECRET_<ID>`,
   com `<ID>` o `id` do segredo em `ops/secrets-inventory.yaml`, e
   `KAMBA_SECRET_<ID>_ANTERIOR` para a segunda posição do anel.
3. **Nenhum valor de segredo entra num ficheiro de compose, num `Dockerfile`,
   numa imagem ou numa variável declarada no `environment:`.** O que o compose
   declara é o nome, nunca o valor; o valor nasce no lançador.
4. O **único** segredo que o anfitrião detém é a credencial de arranque do cofre
   (`doppler_service_token` no inventário). Chega ao lançador pelo mecanismo do
   anfitrião — um `EnvironmentFile` do systemd com modo `0600`, ou OIDC no CI
   (KAM-002) — e não por este mecanismo. É um segredo em vez de dezenove, e é
   essa a troca que torna (A) defensável.
5. O código **nunca** lê `process.env` / `os.environ` à procura de um segredo:
   lê pela porta `SecretProvider`. A diferença importa porque é a porta que
   garante que um segredo ausente nomeia o segredo e não o valor, e que a troca
   para (B) nos Clusters é uma implementação nova e não uma busca por `env` em
   todo o repositório.

## Justificação

**Porque não (B), que é mais seguro na folha de cálculo.** O `tmpfs` ganha nas
duas colunas que mais interessam a longo prazo — isolamento dentro do contentor
e rotação sem reinício — e perde na que decide o Piloto: **precisa de um agente
que escreva os ficheiros**, e esse agente é infra-estrutura a instalar,
monitorizar, actualizar e depurar. O `../tecnica/08` §5 rejeita o OpenBao no
Piloto exactamente com este argumento («operar OpenBao é custo que o Piloto não
suporta») e seria incoerente aceitar o custo de um agente de injecção pela porta
do lado. Um mecanismo que a equipa não consegue operar na terça-feira a seguir é
menos seguro do que um mecanismo mais fraco que funciona.

**As duas fraquezas de (A), e o que as cobre.**

*Herança por processos-filho e `/proc/<pid>/environ`.* Vale dentro do contentor,
cuja fronteira é um serviço nosso e não uma zona partilhada: quem lê o ambiente
já executa código com o UID do serviço, e nesse ponto também consegue chamar a
porta. O que fica realmente exposto é o despejo acidental — e isso é coberto pelo
*logger* com *allowlist* de campos do `../tecnica/08` §7.3 (KAM-025) e por a porta
nunca pôr um valor numa mensagem de erro, que é uma regra com teste em
`packages/core-ts/tests/secrets.contrato.test.ts`.

*Rotação sem reinício não existe.* É o custo que se aceita, e é mensurável: uma
rotação do Meta App Secret obriga a um reinício dos consumidores. O anel
`[actual, anterior]` é o que torna esse reinício seguro em vez de uma janela de
falha — o GWY aceita as duas assinaturas, e a Meta re-entrega até sete dias
(`../tecnica/evidencia/E1`), pelo que uma rotação mal sincronizada recupera. A
rotação propriamente dita é o KAM-072; a janela de 15 minutos de último valor
conhecido (`TTL_ULTIMO_VALOR_S`, *proposta*) cobre uma indisponibilidade do
cofre, não uma rotação.

## Consequências

- Os consumidores (KAM-013, KAM-016, KAM-030, KAM-056) não lêem o ambiente:
  recebem um `SecretProvider` e, em `prod`, falham o arranque se o cofre não
  responder.
- O KAM-078 (deploy) tem de passar a receita do lançador aos serviços e garantir
  que `docker inspect` de um contentor de `prod` não mostra valores. É
  verificável: `grep` de `KAMBA_SECRET_` nos ficheiros de compose devolve nomes,
  nunca valores — e o gate 9 do KAM-002 varre a imagem.
- O KAM-072 herda o reinício como parte do procedimento de rotação. Se isso se
  tornar inaceitável para algum serviço, a saída está escrita em §6.
- O `EnvSecretProvider` deixa de ser «a implementação de `dev`» e passa a ser
  **o caminho de produção**: é tratado e testado como tal.

## §6 — Quando reverter, e o que falta nesta porta

**Gatilhos para passar a (B) `tmpfs`:**

1. Um segredo que tenha de rodar **sem reinício** do consumidor. O candidato
   natural é o `pepper_contact_hmac`, se o *job* de re-chaveamento do KAM-072 não
   puder parar o CHR.
2. Um contentor que passe a correr mais do que um processo com donos diferentes —
   o momento em que «quem lê o ambiente já executa com o UID do serviço» deixa
   de ser verdade.
3. A entrada do OpenBao nos Clusters, onde o agente de injecção já existe por
   outras razões e o custo marginal de (B) cai para perto de zero.

Reverter custa: uma implementação nova de `SecretProvider` (ficheiros), o agente,
e nada no código dos consumidores. É o valor de ter a porta.

**Lacunas declaradas desta porta, para que não sejam descobertas tarde:**

- **Não há caminho de escrita.** Cunhar uma referência nova — escrever um segredo
  no cofre e receber de volta a referência opaca que a base de dados guarda — é o
  que o **KAM-016** vai precisar na troca do *code* do Embedded Signup v4. Ficou
  deliberadamente fora: nenhum serviço do Piloto escreve no cofre hoje, e uma
  porta de escrita sem consumidor é desenho especulativo. O KAM-016 acrescenta-a.
  *(Actualização, KAM-250.)* O KAM-016 acrescentou a `SecretWriter` com o
  `cunhar` (`packages/core-ts/src/secrets/escrita.ts`), só com o `OpenBaoFakeProvider`
  a implementá-la. O KAM-250 acrescenta a escrita numa referência **fixa**
  (`gravar`) e a primeira implementação sobre o Doppler, só para as chaves
  virtuais do LiteLLM — ver o §7.
- **A porta é assíncrona em TypeScript e síncrona em Python.** Do lado Node não
  há alternativa; do lado Python, torná-la assíncrona obrigava a arrastar um
  cliente HTTP para dentro de `libs/py-core`, que não tem dependências por
  decisão do ADR-L001. O AGR lê segredos ao arranque, onde bloquear é o que se
  quer, e relê com `asyncio.to_thread`.
- **A forma da API do Doppler é NÃO VERIFICADO.** Não há conta neste ticket; o
  adaptador está testado contra um transporte falso e tudo o que depende da forma
  da resposta está atrás de uma função injectável. O que falta confirmar, e onde,
  está na constante `A_CONFIRMAR` de `packages/core-ts/src/secrets/doppler.ts`.
- **A recusa de um *service token* de `staging` contra `prod` é, hoje, só do lado
  do cliente.** O provedor recusa-se a construir quando a configuração não bate
  com o ambiente. A metade que importa — o servidor recusar — exige três
  projectos reais e fica por satisfazer.

## §7 — Emenda *proposta* (KAM-250): as chaves virtuais do LiteLLM vivem num projecto Doppler próprio, e o AGR lê-as pela API

**Estado: proposta**, até o fundador a ratificar, como as outras emendas. A
escolha que ela regista já foi feita por ele, a 2026-11-24, no bloco do KAM-250
(`specs/EPIC-03_Agent_Runtime_Verticais.md`, «Decisões do fundador»): a opção 1;
recusadas a 2 (só o operador grava, e a saga do KAM-091 falha fechada em `prod`)
e a 3 (um *token* de escrita na configuração do ambiente).

**O que a (A) não consegue servir.** A chave virtual de um tenant lê-se como
`litellm_virtual_key/<tenant_id>`, que o §2 desta decisão transforma na variável
`KAMBA_SECRET_LITELLM_VIRTUAL_KEY__<tenant_id>`. Em `staging` e `prod` os
segredos chegam por interpolação do *compose*, que declara uma lista fixa de nomes
por serviço: **um nome que depende do tenant não se declara**. Até ao KAM-250 o
AGR não lia a chave de tenant nenhum, nem depois de reiniciar. E o valor não
chegava ao cofre: ninguém o escrevia.

**A excepção, e o seu tamanho.**

1. As duas famílias que o proxy emite — `litellm_virtual_key` (por tenant) e
   `litellm_screening_key` — vivem num **projecto Doppler só delas**
   (`kamba-llm-chaves`, *proposta*, com as configurações `staging` e `prod`), e não
   na configuração do ambiente.
2. Escreve-as o provisionamento (`infra/llm/chaves.py` e o passo `chave_llm` da
   saga do KAM-091), pela porta `GravadorDeSegredo.gravar(ref, valor)`, com o
   `doppler_llm_chaves_escrita`: um *token* limitado a esse projecto. Quem o
   roubar reescreve chaves de LLM, e mais nada. O gravador recusa, do lado do
   cliente, qualquer família fora das duas.
3. Lê-as o AGR **pela API**, pelo `DopplerSecretProvider`, com o
   `doppler_llm_chaves_leitura`: só leitura, só esse projecto. É o **único** sítio
   onde um serviço lê um segredo pela API e não do ambiente. Um tenant novo não
   pede reinício; o AGR não ganha acesso a mais nenhum segredo; e a saída para
   `api.doppler.com` passa pelo `proxy-saida`, declarada em `services/agr/egress.yaml`.
4. Em `staging` e `prod`, sem o *token* de leitura, as chaves **não** se lêem do
   ambiente: o `chamar` falha e o turno degrada. Fecha, e não abre.

**O que a emenda não muda.** Todos os outros segredos continuam na (A). A regra 5
continua: o AGR lê pela porta, e o que muda é a implementação que serve estas duas
famílias. A janela de último valor conhecido (`TTL_ULTIMO_VALOR_S`) cobre o Doppler
em baixo e não uma chave apagada. A rotação das chaves virtuais continua fora
(o *runbook* de rotação).

**O que fica NÃO VERIFICADO.** A forma da API de escrita do Doppler
(`A_CONFIRMAR_ESCRITA`, nos dois lados) e que um *service token* fica limitado ao
projecto e à configuração para que foi emitido (`E4` §2.14, em resumo). A medição
do KAM-250 usou um Doppler falso com essa forma (`docs/evidencia/KAM-250.md`).
