# Runbook RB-K07 — Rotação de segredos, planeada ou em incidente

| Campo | Valor |
|---|---|
| ID | **RB-K07** |
| Versão | 1.0 |
| Cenário | Um segredo do inventário chega ao fim do seu período de rotação, ou há suspeita de fuga |
| Severidade | **P3** (planeada); em incidente, **P1** pelo [RB-K10](RB-K10-incidente-de-seguranca.md) |
| Alertas que o activam | **Nenhum, hoje.** A regra «segredo a expirar < 14 dias» está por escrever: o `ops/secrets-inventory.yaml` tem o `rotacao_dias` e **não tem a data da última rotação**, e nada publica a idade de um segredo. Credor: **KAM-072** (`ops/metricas/catalogo.yaml`, `regras_por_escrever`) |
| Gatilho manual | O calendário de rotação (hoje de uma pessoa: não há agendador, KAM-071); o RB-K10 (suspeita de fuga); o RB-K02 §3.3 (*callbacks* inválidos depois de uma troca de chave) |
| Nível de degradação | — (uma rotação bem feita não degrada nada; mal feita, o consumidor recusa: 401 no GWY, falha de autenticação no facilitador) |
| Dono | O `owner` da entrada no inventário (`eng_canais`, `eng_pagamentos`, `sre`…), com o Responsável de Segurança em incidente |
| Última revisão | 2026-11-09 (KAM-083) |
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

- **A rotação não fica registada no `audit_log`.** O critério 5 do bloco e o doc 09 §13
  pedem-no, e o domínio de `action` tem nove valores e **nenhum** de rotação (revisões
  0006 e 0038; dicionário §3). Um `INSERT` com uma acção nova seria recusado pela
  restrição `audit_log_action`. **Regista-se na linha temporal** (incidente) ou no registo
  de operações, com o identificador do segredo e a hora — **nunca o valor**. A acção nova é
  emenda ao dicionário e migração: credor **o fundador** (o `secrets-export.md` §4 tem a
  mesma falta para `access.secrets_export`).
- **Não há ferramenta de rotação.** Cada passo é manual, no cofre e no fornecedor.
- **Os segredos entram por variável de ambiente** (`KAMBA_SECRET_<ID>` e
  `KAMBA_SECRET_<ID>_ANTERIOR`, [`../adr/ADR-L002-injeccao-de-segredos.md`](../adr/ADR-L002-injeccao-de-segredos.md)),
  e **o ambiente de um processo não muda depois do arranque**: o laço de 60 s do GWY relê
  o anel, mas do mesmo ambiente. Um segredo novo só entra **recriando** o contentor — um
  `docker compose restart` **não** relê o ambiente.
- **O GWY do compose de produção não recebe os segredos da Meta** — o bloco `environment`
  não os passa (RB-K01 §0). A primeira rotação do `meta_app_secret` tem esse defeito por
  baixo.
- **O `proxypay_api_key` não tem consumidor** no código (não há adaptador, RB-K02 §0).

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
docker compose -f infra/compose/docker-compose.prod.yml exec prometheus \
  promtool query instant http://127.0.0.1:9090 'increase(gwy_sig_fail[10m])'
```
`verificado` como no RB-K01 §2.

## 3. Mitigação — a ordem e as janelas, por segredo

### 3.1 `meta_app_secret` (anel: sim; consumidor: GWY)

1. **O GWY primeiro, a Meta depois.** No cofre: o valor actual passa para
   `meta_app_secret` *anterior* (`KAMBA_SECRET_META_APP_SECRET_ANTERIOR`) e o novo para o
   actual (`KAMBA_SECRET_META_APP_SECRET`).
2. Recriar o GWY com o ambiente novo:
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
   autenticação sejam apanhados por consulta. Hoje não há reconciliador (KAM-056) nem
   adaptador: **este passo não se executa**, e uma rotação agora perderia *callbacks* sem
   rede.
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

Não se roda sem o *job* de re-chaveamento, que é do **KAM-072**. Em incidente, o RB-K10
decide; o procedimento fica por escrever com o *job*.

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
   linha 12). Credor: **KAM-072**.

## 4. Critério de recuperação

- o consumidor arrancou com o valor novo (logs sem `cofre_inacessivel_no_arranque`) e
  responde no `/healthz`;
- para o GWY: `increase(gwy_sig_fail[10m])` a 0;
- o *anterior* foi retirado no fim da janela, e o consumidor recriado outra vez;
- `python -m secrets_inventory --root .. esquema` continua verde (se a entrada mudou);
- a rotação ficou registada (identificador e hora) no registo de operações ou na linha
  temporal — não no `audit_log`, pelo §0.

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
| 1.0 | Novembro 2026 | O *stub* do KAM-080 passa a runbook no modelo comum (**KAM-083**): os dois caminhos e a ordem de incidente, a janela por segredo (com os 7 dias da Meta no `meta_app_secret`), o «recriar e não reiniciar», o procedimento proposto da cópia offline da passphrase do backup, e as faltas medidas no §0 — sem acção de rotação no `audit_log`, sem data de última rotação no inventário | KAM-083 |
