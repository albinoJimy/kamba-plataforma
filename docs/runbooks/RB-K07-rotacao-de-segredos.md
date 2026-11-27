# Runbook RB-K07 — Rotação de segredos, planeada ou em incidente

| Campo | Valor |
|---|---|
| ID | **RB-K07** |
| Versão | 1.3 |
| Cenário | Um segredo do inventário chega ao fim do seu período de rotação, ou há suspeita de fuga |
| Severidade | **P3** (planeada); em incidente, **P1** pelo [RB-K10](RB-K10-incidente-de-seguranca.md) |
| Alertas que o activam | **Nenhum, hoje.** O cálculo existe desde o KAM-072 — `secret_age_days{segredo}` e `secret_rotation_period_days{segredo}` em `packages/core-ts/src/keyring/idade.ts`, com a idade lida do registo de rotação e o estado `a_expirar` a 80% do prazo —, mas **nenhum processo o expõe** e a regra do Prometheus está por escrever (o `obs_lint` recusa uma regra sobre uma métrica que ninguém serve). Credor: **o fundador** — nenhum ticket do *backlog* liga o rotador a um processo (`ops/metricas/catalogo.yaml`, `regras_por_escrever`) |
| Gatilho manual | O calendário de rotação (hoje de uma pessoa: não há agendador, KAM-071); o RB-K10 (suspeita de fuga); o RB-K02 §3.3 (*callbacks* inválidos depois de uma troca de chave) |
| Nível de degradação | — (uma rotação bem feita não degrada nada; mal feita, o consumidor recusa: 401 no GWY, falha de autenticação no facilitador) |
| Dono | Plataforma/SRE; executa com o `owner` da entrada no inventário (`eng_canais`, `eng_pagamentos`, `sre`…), e com o Responsável de Segurança em incidente |
| Última revisão | 2026-11-18 (KAM-205) |
| Último ensaio | **Nunca.** O critério 5 do bloco exige ensaio em *staging*; roteiro de mesa-redonda em [`folha-de-ensaio.md`](folha-de-ensaio.md) §3.3. Credor: o fundador; o *staging* com *host* é o KAM-077 |
| Linha canónica | [`../tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha RB-K07; [`../tecnica/08_Seguranca_Conformidade.md`](../tecnica/08_Seguranca_Conformidade.md) §5 |
| Estado | **Proposta**, não ensaiada |

> **O que esta página não substitui.** A rotação das chaves de LLM tem procedimento
> próprio em [`rotacao-de-chaves-de-llm.md`](rotacao-de-chaves-de-llm.md) (KAM-030), e a
> exportação e o restauro do cofre em
> [`../../ops/runbooks/secrets-export.md`](../../ops/runbooks/secrets-export.md) (KAM-010).
> Este runbook dá a **ordem** e as **janelas** entre segredos, e remete para eles.

---

## 0. Antes de começar

- **A rotação fica no `audit_log` só se correr pelo `Rotador` com a auditoria ligada**
  (KAM-072): a revisão `0066` acrescenta as duas acções ao domínio, e o
  `AuditoriaDeRotacaoSql` (`packages/core-ts/src/keyring/auditoria.ts`) escreve cada uma
  na cadeia de plataforma com o papel `kamba_batch` — identificador e versão, nunca o
  valor. **Uma rotação feita à mão no cofre não passa por lá**: essa regista-se na linha
  temporal (incidente) ou no registo de operações, com o identificador do segredo e a hora —
  **nunca o valor**. A exportação do cofre continua sem acção no domínio
  (`secrets-export.md` §4, `access.secrets_export`): credor **o fundador**.
- **A ferramenta é uma biblioteca, não um comando.** O `Rotador` de
  `packages/core-ts/src/keyring/rotacao.ts` (KAM-072) faz a rotação com janela, a
  revogação, a revogação no fim da janela e a rotação de emergência, sobre uma porta de
  cofre de anéis e uma de registo — mas **nenhum processo o corre** contra o cofre real:
  não há adaptador Doppler da porta de anéis, e a escrita no cofre não está na porta de
  leitura do KAM-010. Cada passo no cofre e no fornecedor continua manual, e a ordem é
  a que o `Rotador` segue: cofre primeiro, registo depois, e repetir repara.
- **Os segredos entram por variável de ambiente** (`KAMBA_SECRET_<ID>` e
  `KAMBA_SECRET_<ID>_ANTERIOR`, [`../adr/ADR-L002-injeccao-de-segredos.md`](../adr/ADR-L002-injeccao-de-segredos.md)),
  e **o ambiente de um processo não muda depois do arranque**: o laço de 60 s do GWY relê
  o anel, mas do mesmo ambiente. Um segredo novo só entra **recriando** o contentor — um
  `docker restart` (ou `docker compose restart`) **não** relê o ambiente.
  **Em `prod`, desde o KAM-260, é ao contrário:** o valor entra no contentor pelo
  ficheiro do serviço, que o lançador carrega em **cada** arranque (ADR-L002 §8,
  *proposta*). Escreve-se primeiro o ficheiro, com o valor novo —
  `cd tools && doppler run -- python -m compose_prod --root .. segredos --destino /run/kamba/segredos`
  (a pasta é a do `KAMBA_SEGREDOS_DIR` do compose; o gravador recusa um destino vazio ou
  dentro do repositório) —, e depois **reinicia-se** o serviço (`docker compose restart
  <serviço>`, ou `up -d --force-recreate <serviço>`). Um `up -d` sozinho **não** chega: o
  bloco `x-segredos` não entra no *hash* da configuração, e com só o ficheiro mudado o
  compose deixa o contentor como está (medido pela revisão adversarial do KAM-260).
- **O GWY do compose de produção não recebe os segredos da Meta** — o bloco `environment`
  não os passa (RB-K01 §0). A primeira rotação do `meta_app_secret` tem esse defeito por
  baixo.
- **O `proxypay_api_key` tem adaptador e não tem serviço.** O adaptador e o reconciliador
  existem desde o KAM-056 (`packages/core-ts/src/pagamentos/proxypay/`), e nenhum serviço
  do compose os corre contra o facilitador (o *sandbox* é o `ext:KAM-103`).

## 1. Cenário e gatilho

| Caminho | Gatilho | Ordem |
|---|---|---|
| **Planeado** (P3) | o calendário: `rotacao_dias` da entrada, menos 14 dias | um segredo de cada vez, com a janela do §3 |
| **Incidente** (P1, RB-K10 comanda) | suspeita de que alguém de fora tem o segredo | **LLM e fornecedores primeiro**, porque dão acesso a terceiros e custam dinheiro; depois os de âmbito de plataforma; por fim os de *tenant* |

## 2. Diagnóstico

```bash
# O inventário é válido? Sai 0 e diz «verde».
cd tools && python -m secrets_inventory --root .. esquema
```
`verificado` neste ramo a 2026-11-09: 41 entradas válidas, saída 0. (O alvo `all` sai 1
na `main` por erros do passo `uso` que não são deste runbook — achado em
[`../evidencia/KAM-083.md`](../evidencia/KAM-083.md) §5.)

**Para o segredo a rodar, ler no inventário**: `owner`, `rotacao_dias`,
`rotacao_gatilho`, `consumidores`, `instancias`, **`anel`** e `kid`. O `anel` decide a
janela: com `anel: true` o consumidor aceita `[actual, anterior]` e a rotação faz-se sem
corte; com `anel: false` há corte, e planeia-se.

```bash
# Depois de uma rotação de meta_app_secret: o GWY recusa assinaturas?
docker exec kamba-prod-prometheus-1 \
  promtool query instant http://127.0.0.1:9090 'increase(gwy_sig_fail[10m])'
```
`verificado` como no RB-K01 §2.

## 3. Mitigação — a ordem e as janelas, por segredo

### 3.1 `meta_app_secret` (anel: sim; consumidor: GWY)

1. **O GWY primeiro, a Meta depois.** No cofre: o valor actual passa para
   `meta_app_secret` *anterior* (`KAMBA_SECRET_META_APP_SECRET_ANTERIOR`) e o novo para o
   actual (`KAMBA_SECRET_META_APP_SECRET`).
2. Reescrever os ficheiros dos serviços (§0, KAM-260) e recriar o GWY:
   `doppler run -- docker compose -f infra/compose/docker-compose.prod.yml up -d --force-recreate gwy`.
   `não verificado`: o lançador `doppler run` está no ADR-L002 e não tem conta (NÃO
   VERIFICADO), e o compose ainda não passa a variável ao serviço (§0).
3. Só agora trocar o segredo no painel da aplicação Meta. O GWY aceita as duas
   assinaturas (`assinaturaValida`, `packages/core-ts/src/entrada/assinatura.ts`).
4. **Janela: 7 dias** (proposta) antes de retirar o *anterior* — a Meta re-entrega
   *webhooks* falhados até 7 dias, e não se sabe se os re-assina com o segredo novo (NÃO
   VERIFICADO). Retirar = apagar o *anterior* do cofre e recriar o GWY outra vez.
5. Confirmar `increase(gwy_sig_fail[10m])` a 0 depois de cada passo.

### 3.2 `proxypay_api_key` (a chave da API **é** a chave do HMAC)

1. O ProxyPay não tem janela dupla confirmada (`E2`); o anel é nosso. **O reconciliador
   tem de estar activo durante a troca**, para que os pagamentos cujos *callbacks* falhem a
   autenticação sejam apanhados por consulta. O adaptador aceita a chave corrente e a
   anterior da conta (`credenciais_ref` e `credenciais_ref` anterior), e a consulta
   `GET /payments` recupera um pagamento cujo *callback* chegou com a chave revogada —
   **ensaiado contra o servidor falso** do KAM-056 (`packages/core-ts/tests/keyring.pagamentos.test.ts`,
   KAM-072), não contra o *sandbox*. Enquanto nenhum serviço correr o reconciliador em
   produção, **este passo não se executa**: uma rotação agora perderia *callbacks* sem rede.
2. Quando houver: actual → anterior, novo → actual, recriar os consumidores (PAY, GWY),
   trocar no painel do ProxyPay, manter o anterior até a consulta do RB-K02 §2 (ponto 2)
   mostrar 0 falhas de autenticação durante 24 h (proposta).

### 3.3 Chaves de LLM (`litellm_master_key`, `llm_provider_key`, `litellm_virtual_key`)

O procedimento é o de [`rotacao-de-chaves-de-llm.md`](rotacao-de-chaves-de-llm.md), com a
ordem do §4 dele em incidente (parar o proxy, fornecedores, *master key*, chaves
virtuais). **Atenção:** as chaves virtuais não existem no compose actual — o LiteLLM não
tem base de dados (RB-K03 §0, ponto 3).

### 3.4 `backup_repo_cifra_passphrase` (anel: não)

Rodar esta passphrase **não re-cifra** os backups existentes: exige repositório novo e
completo novo, e os backups antigos continuam a precisar da passphrase **antiga** até
saírem da retenção (35 dias, `infra/backup/cobertura.yaml`). Logo:

1. guardar a passphrase antiga, com a sua cópia offline (§3.6), até ao fim da retenção;
2. criar a passphrase nova, a stanza num repositório novo e um completo novo;
3. só depois retirar a antiga. Hoje não há `repo1` (D1/KAM-105): nada a rodar.

### 3.5 `pepper_contact_hmac` (anel: sim; `kid`: sim)

O *job* de re-chaveamento existe desde o KAM-008 (`Identidade.rekeyLookup`, por tenant,
em lotes, retomável e idempotente), e o ensaio dele corre sobre 10 000 contactos
(`packages/core-ts/tests_bd/identity.bd.test.ts`). A ordem, que este runbook fixa
(**proposta**, não ensaiada fora do ensaio):

1. Gerar a versão nova com `gerarChaveVersionada(kid)` (`identity/chaves.ts`) — a forma
   é `<kid>:<base64>` — e pô-la como actual no cofre, com a anterior em `_ANTERIOR`.
2. `iniciarRotacao(kid)`: regista a versão nova em `platform.hmac_key_versions`. Daí em
   diante a pesquisa tenta as duas versões, e quem é visto sobe para a nova.
3. `rekeyLookup(tenant, kid)` para cada tenant, até `completo: true` em todos.
4. `concluirRotacao()`: a anterior passa a `retirada`.
5. Só agora retirar a anterior do cofre e recriar os consumidores.

Retirar a anterior do cofre antes do passo 4 deixa sem chave as linhas por re-chavear:
é o erro que esta ordem existe para evitar. Em incidente, o RB-K10 decide se se aceita
esse custo.

### 3.6 A cópia offline da `backup_repo_cifra_passphrase`

O `specs/EPIC-08` (bloco KAM-079, critério 6 e DoD 2) põe este procedimento no KAM-083.
É **proposta**, não ensaiada; o ensaio numa máquina limpa é da **D1/KAM-105**.

1. **Suporte:** dois suportes físicos, guardados em dois sítios distintos, nenhum deles no
   *host* nem no fornecedor do `repo1`.
2. **Cifra:** a passphrase sai do cofre já cifrada com uma passphrase de cópia que **não
   está no cofre** — a mesma regra do `secrets-export.md` §4.
3. **Dois detentores:** um guarda o suporte, o outro a passphrase de cópia; nenhum tem os
   dois. Os detentores são papéis (Plataforma/SRE e Responsável de Segurança), e a
   atribuição a pessoas fica fora deste repositório.
4. **Prova de que funciona**, a cada rotação e no simulacro trimestral: decifrar a cópia
   numa máquina sem acesso ao cofre e restaurar com ela (cenário C do KAM-085, anexo A do
   [RB-K08](RB-K08-base-de-dados-e-restauro.md), linha 4).
5. **Divergência por resolver**, que este runbook não decide: o
   `infra/backup/cobertura.yaml` escreve que o destino da exportação do cofre é o `repo1`,
   e o `secrets-export.md` §4 que é um volume offline com dois detentores (RB-K08, anexo A,
   linha 12). Credor: **o fundador** — era o KAM-072, que não a decide: é uma escolha
   sobre o destino da exportação do cofre, e não sobre a rotação de uma chave.

### 3.7 `kek_token_cliente` (anel: sim; `kid`: sim)

**Roda-se, desde o KAM-205, pela ordem abaixo — e só por ela.** Até ao KAM-205 o `kid`
gravado em cada criptograma era o rótulo **posicional** que o `EnvSecretProvider` dava
(`actual`), e uma rotação partia todos os *tokens* guardados (achado da revisão adversarial
do KAM-072). Agora:

- o valor da KEK leva o `kid`: **`<kid>:<base64 de 32 octetos>`**, a forma do
  `identity/chaves.ts`. O `kid` vai com o valor quando ele passa a `_ANTERIOR`, e é isso que
  o torna estável (`packages/core-ts/src/secrets/kid.ts`). Um `kid` novo gera-se com o
  `novoKid` do `keyring/anel.ts` (`AAAAMMDD.<base32>`); `actual` e `anterior` não são `kid`;
- o onboarding **recusa cifrar** com uma KEK sem `kid` no valor (`KekSemKidEstavelError`):
  enquanto a KEK de um ambiente estiver na forma antiga, um onboarding novo falha antes de
  guardar o *token*. A primeira rotação abaixo é o que o desbloqueia;
- os criptogramas gravados antes, com `kid` `actual`, abrem pela versão **sem** `kid` no
  valor, em qualquer posição (`KID_LEGADO`, no `onboarding/cifra.ts`). Duas versões sem `kid`
  ao mesmo tempo são recusadas: não se sabe com qual foi feito um criptograma antigo.

**Nunca acrescentar um prefixo `<kid>:` ao valor que já está no cofre.** Os criptogramas
antigos dizem `actual`, e uma KEK que passe a dizer outro `kid` deixa-os sem versão no anel.
A forma antiga sai do cofre **rodando**, como qualquer outra.

1. **Rodar.** Actual → `KAMBA_SECRET_KEK_TOKEN_CLIENTE_ANTERIOR`, nova (`<kid>:<base64>`) →
   `KAMBA_SECRET_KEK_TOKEN_CLIENTE`, no cofre, e recriar os consumidores (GWY, TEN). A
   leitura continua: cada criptograma escolhe a versão pelo `kid` que leva.
2. **Re-cifrar.** Correr o `recifrarTokensGuardados` (`packages/core-ts/src/keyring/tokens.ts`)
   com uma ligação **`kamba_batch`** — é o único papel com `BYPASSRLS`; com outro, a
   `tenant_channels` lê-se vazia, e o *job* recusa (`RecifraSemPapelDeLoteError`) em vez de
   dizer «zero por re-cifrar». Para cada canal: abre o criptograma, cifra-o com a actual, cunha
   uma referência nova, troca o `tenant_channels.token_ref` **só se ainda for a lida**, e
   revoga a antiga. O *token* não muda; o criptograma e a referência sim. Sem esquema.
3. **Confirmar.** Correr o *job* **outra vez**: tem de devolver `recifrados: 0` e
   `falhados: []`. Um `falhados` não vazio dá os `tenant_channels.id` dos canais que não
   abrem — **não se revoga** enquanto houver um; o *token* desse canal só volta com o dono a
   repetir o Embedded Signup (RB-K06).
4. **Revogar.** Só então retirar `KAMBA_SECRET_KEK_TOKEN_CLIENTE_ANTERIOR` e recriar os
   consumidores. Um criptograma que tenha ficado por re-cifrar deixa de abrir.

O *job* é idempotente e retomável: cair a meio deixa cada canal na referência antiga ou na
nova, e a passagem seguinte faz o resto. O que pode ficar é uma referência **órfã** no cofre
(a nova, se caiu entre cunhar e trocar; a antiga, se caiu entre trocar e revogar) — não dá o
*token* a ninguém sem a KEK, e a antiga deixa de abrir no passo 4. **A ligação tem de estar
em *autocommit*** — nunca dentro de `BEGIN … COMMIT`: a antiga revoga-se logo a seguir à troca,
e uma transacção revertida deixava canais a apontar para referências já revogadas. Corre-se uma
passagem de cada vez: duas ao mesmo tempo não perdem nenhum *token* (ensaiado); a que perde uma
troca conta o canal em `concorrentes`, ou em `falhados` se o leu depois de a outra ter revogado
a referência antiga — e o passo 3 resolve os dois.

**O que continua por fazer, e não é do KAM-205** (que o diz em «Fora deste ticket»): nenhum
processo corre o *job* contra o cofre real — o critério 7 do KAM-072 —, e a porta de escrita
do cofre (`cunhar`, `revogar`, em `secrets/escrita.ts`) só tem a implementação de ensaio do
`OpenBaoFakeProvider`: o `EnvSecretProvider` não escreve, e não há adaptador Doppler de
escrita. É a mesma lacuna que impede o onboarding de guardar um *token* fora dos ensaios. O
ensaio em *staging* (critério 5 do KAM-072) está por fazer.

## 4. Critério de recuperação

- o consumidor arrancou com o valor novo (logs sem `cofre_inacessivel_no_arranque`) e
  responde no `/healthz`;
- para o GWY: `increase(gwy_sig_fail[10m])` a 0;
- o *anterior* foi retirado no fim da janela, e o consumidor recriado outra vez;
- `python -m secrets_inventory --root .. esquema` continua verde (se a entrada mudou);
- a rotação ficou registada (identificador e hora) no registo de operações ou na linha
  temporal; no `audit_log` só se a rotação correu pelo `Rotador` com a auditoria ligada (§0).

## 5. Escalamento

O `owner` da entrada → Plataforma/SRE → Responsável de Segurança. Suspeita de fuga →
**RB-K10**, que comanda a partir daí.

## 6. Comunicação

Interna. Uma rotação bem feita não se comunica às PMEs; uma que corte o serviço é o
RB-K01 ou o RB-K02, e comunica-se por esses.

## 7. Factos de terceiros

| Facto | Estado | Fonte |
|---|---|---|
| A Meta re-entrega *webhooks* falhados até 7 dias | **CONFIRMADO** | `E1` |
| A Meta re-assina as re-entregas com o segredo novo | **NÃO VERIFICADO** | — |
| O ProxyPay não oferece janela dupla de chave | **NÃO VERIFICADO** (`E2`, pergunta 10) | `ops/secrets-inventory.yaml`, `proxypay_api_key` |

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.3 | Novembro 2026 | **KAM-260**: em `prod` o segredo entra no contentor pelo ficheiro do serviço que o lançador carrega (ADR-L002 §8, *proposta*); o §0 e o §3.1 passam a reescrever esse ficheiro antes de recriar. | Equipa KAMBÁ |
| 1.2 | Novembro 2026 | **KAM-205**: o §3.7 deixa de proibir a rotação da `kek_token_cliente` e escreve a ordem — rodar, re-cifrar, confirmar, revogar. O `kid` vai dentro do valor da KEK (`<kid>:<base64>`) e o `EnvSecretProvider` lê-o de lá; o onboarding recusa cifrar com uma KEK sem `kid`; os criptogramas antigos, com `kid` `actual`, abrem pela versão sem `kid`; a re-cifra é o `recifrarTokensGuardados`, com o `kamba_batch`, e só se revoga com `falhados` vazio. O que falta para correr contra o cofre real continua com o KAM-072 (critérios 5 e 7) | KAM-205 |
| 1.1 | Novembro 2026 | **KAM-072**: o §0 passa a nomear o `Rotador` do `packages/core-ts/src/keyring/` e o que lhe falta para correr contra o cofre real; o cabeçalho diz que a idade dos segredos já se calcula e que ninguém a expõe (credor: o fundador); o §3.5 ganha a ordem da rotação do *pepper* sobre o *job* do KAM-008; o §3.2 e o §0 deixam de dizer que o ProxyPay não tem adaptador (o KAM-056 fundiu) e citam o ensaio da rotação contra o servidor falso; o §3.7 novo manda **não** rodar a KEK dos *tokens* de cliente no Piloto, porque o `kid` do `EnvSecretProvider` é posicional e a rotação parte os *tokens* guardados (achado da revisão adversarial; credor o KAM-205); o credor da divergência do destino passa a ser o fundador; o §0 e o §4 dizem quando a rotação fica no `audit_log` (revisão `0066`) | KAM-072 |
| 1.0 | Novembro 2026 | O *stub* do KAM-080 passa a runbook no modelo comum (**KAM-083**): os dois caminhos e a ordem de incidente, a janela por segredo (com os 7 dias da Meta no `meta_app_secret`), o «recriar e não reiniciar», o procedimento proposto da cópia offline da passphrase do backup, e as faltas medidas no §0 — sem acção de rotação no `audit_log`, sem data de última rotação no inventário | KAM-083 |
