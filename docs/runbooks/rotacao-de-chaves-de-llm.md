# Runbook — rotação de chaves do *gateway* de LLM

**Esboço** (KAM-030, DoD «runbook de rotação esboçado»). Não é procedimento
ratificado: o *deploy* é o KAM-078 e o cofre em produção é o OpenBao (KAM-010),
e nenhum dos dois existe. O que está aqui é o que se consegue escrever hoje, com
os passos que dependem de infra-estrutura marcados.

| Segredo | `ops/secrets-inventory.yaml` | Rotação | Gatilho |
|---|---|---|---|
| `litellm_master_key` | `rotacao_dias: 90` | manual | `imagem_litellm_comprometida` |
| `llm_provider_key/<fornecedor>` | — | manual | suspeita de fuga, ou rotação do fornecedor |
| `litellm_virtual_key/<tenant_id>` | — | manual | `suspensao_de_tenant` |

**A rotação automática é Enterprise e não se usa** (`E4` §2.7: *secret managers*
e *key rotation* estão na pasta `enterprise/`, que exige subscrição). Daí tudo
nesta página ser manual, por desenho e não por atraso.

---

## 1. `litellm_master_key` — a chave de administração do proxy

Quem a tem cria chaves virtuais, lê orçamentos e vê os *spend logs* de todos os
*tenants*. É o segredo mais sensível do componente que o `E4` chama «o de maior
superfície de ataque do stack».

1. Gerar um valor novo (32 octetos aleatórios, prefixo `sk-`).
2. Escrever no cofre em `litellm_master_key`, **sem apagar o anterior**: o
   `EnvSecretProvider` do KAM-010 lê o anel por `_ANTERIOR`, e a janela de
   `TTL_ULTIMO_VALOR_S` (15 min) cobre a indisponibilidade mas **não** a
   revogação — um `SecretAusenteError` propaga-se sempre.
3. Reiniciar o proxy (`LITELLM_MASTER_KEY` vem do ambiente, e o compose
   recusa-se a arrancar sem ela).
4. Confirmar com `python infra/llm/chaves.py orcamentos`: ele usa a *master key*
   e devolve 0 ou 1; um erro de credencial aparece como
   `/key/list respondeu 401`.
5. Só depois apagar o valor anterior.

**As chaves virtuais sobrevivem à rotação da *master key*** — vivem na base de
dados do proxy e não são derivadas dela. Não há que reprovisionar nada.

**Em falta (KAM-078):** reiniciar o proxy sem janela de indisponibilidade. Hoje
o passo 3 interrompe as chamadas a modelos durante o reinício, e o AGR degrada —
excepto que a degradação é o KAM-037 e também não existe, pelo que os turnos
falham e os *jobs* voltam à fila. Não é perda de mensagens; é latência.

---

## 2. `llm_provider_key/<fornecedor>` — as chaves dos fornecedores

Uma por fornecedor aprovado (`anthropic`, `openai`, `google`). O nome da
variável é derivado e não escrito:
`nome_da_variavel("llm_provider_key/anthropic")` →
`KAMBA_SECRET_LLM_PROVIDER_KEY__anthropic`.

1. Emitir a chave nova **na consola do fornecedor**, sem revogar a antiga.
2. Escrever no cofre e reiniciar o proxy.
3. Fazer uma chamada de ensaio pelo alias afectado, em `staging`, com dados
   sintéticos.
4. Revogar a antiga na consola do fornecedor.

**A ordem importa**: revogar antes de o proxy reiniciar põe o alias a falhar, e
no `kamba-chat` isso consome o *fallback* por uma razão que não é a do critério
6 — o `allowed_fails: 3` e o `cooldown_time: 30` começam a contar, e o grupo
fica em *cooldown* durante 30 s depois de três falhas.

---

## 3. `litellm_virtual_key/<tenant_id>` — a chave de um *tenant*

O gatilho do inventário é `suspensao_de_tenant`. Há **duas** acções diferentes, e
confundi-las é a armadilha desta página:

| Quer-se | Faz-se |
|---|---|
| **Cortar o acesso** de um *tenant* | `POST /key/update` com `max_budget: 0` — o proxy passa a responder **422** `budget_exceeded` e o cliente devolve `OrcamentoEsgotado`. A chave continua a existir e o histórico de `dat.llm_call_log` fica intacto |
| **Rodar o valor** da chave | `POST /key/delete` e novo `/key/generate`; escrever o valor novo no cofre em `litellm_virtual_key/<tenant_id>` |

O `provisionar` do `infra/llm/chaves.py` **não** reemite a chave numa segunda
corrida: usa `/key/update`, de propósito. Reemitir a cada corrida obrigava a
reescrever o segredo de todos os *tenants* por causa de um — e a escrita no
cofre não está na porta do KAM-010 (`ADR-L002` §6, lacuna que o KAM-016 nomeia).

```bash
python infra/llm/chaves.py provisionar <tenant_id> <plano>
```

Exige `KAMBA_LLM_MENSALIDADE_USD_<PLANO>` e **recusa-se a correr sem ela**: o
orçamento é 15% da mensalidade, a mensalidade por plano não está fixada em
documento nenhum, e um tecto de custo inventado não se escreve.

---

## 4. Se a imagem do proxy for comprometida

É o gatilho `imagem_litellm_comprometida`, e o precedente é real: as versões PyPI
1.82.7 e 1.82.8 foram publicadas com *malware* que recolhia credenciais —
chaves SSH, de *cloud*, de Kubernetes e variáveis de ambiente — e estiveram
acessíveis cerca de 40 minutos (`E4` §2.7, CONFIRMADO).

Nesse caso **todas** as chaves que o proxy conhecia são suspeitas, por esta
ordem:

1. parar o proxy;
2. rodar as chaves de **fornecedor** (§2) — são as que dão acesso a terceiros e
   custam dinheiro;
3. rodar a *master key* (§1);
4. rodar as chaves virtuais (§3), que só valem dentro do proxy;
5. fixar a imagem numa versão auditada (`ci/supply-chain/imagens.yaml`, por
   digest, com `cosign: verificar`) e confirmar a assinatura **antes** de
   levantar.

O passo 5 é o que o KAM-030 entrega: o inventário recusa esta imagem com
`cosign: n/a` ou `por_apurar`, e o `tools/blocklist.yaml` recusa qualquer versão
abaixo de 1.83.0 — em manifestos, em imagens, e (desde o KAM-030) num
`RUN pip install` de um Dockerfile.

---

## 5. O que esta página não cobre

- **Agendar a rotação de 90 dias.** Não há agendador (KAM-071); hoje é uma
  entrada de calendário de uma pessoa.
- **O procedimento no OpenBao.** O cofre em produção é o KAM-010 com
  `OpenBaoFakeProvider` e o Doppler no Piloto; o OpenBao a sério ainda não está
  implantado, e o estado do Doppler é **NÃO VERIFICADO** (não há conta).
- **A autorização da transferência.** Rodar uma chave não autoriza nada: em
  `KAMBA_ENV=prod` o *gate* de destino recusa **todos** os fornecedores enquanto
  o `tenant_destinations` do KAM-069 não existir (ADR-008). Uma chave nova não
  abre essa porta.
