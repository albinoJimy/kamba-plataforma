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
2. Escrever no cofre e reiniciar o proxy. Em `prod`, antes de reiniciar, reescrever
   o ficheiro de segredos dos serviços (KAM-260, ADR-L002 §8, *proposta*):
   `cd tools && doppler run -- python -m compose_prod --root .. segredos --destino /run/kamba/segredos`,
   e só depois `docker compose restart litellm`. Sem isso o proxy volta a arrancar
   com a chave antiga, e o passo 4 põe os *aliases* a falhar.
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
| **Rodar o valor** da chave | **Apagar o segredo** `litellm_virtual_key/<tenant_id>` no projecto Doppler das chaves e correr o `provisionar` abaixo: com o cofre vazio, ele apaga a chave no proxy, grava um valor novo no cofre e cria a chave com ele (desfecho `reemitida`). **Não basta o `/key/delete`**: com o valor ainda no cofre, o `provisionar` seguinte recria a chave **com o mesmo valor**, e uma chave comprometida continua válida |

O `provisionar` do `infra/llm/chaves.py` **não** reemite a chave numa segunda
corrida: se o valor que está no cofre autentica a chave (o SHA-256 dele é o
`token` que o proxy lista), usa `/key/update`, de propósito. Desde o KAM-250 o
valor vive num projecto Doppler só das chaves virtuais, e o `chaves.py` grava-o
lá **antes** de criar a chave (`ADR-L002` §7, *proposta*); o AGR lê-o de lá, sem
reiniciar, até 10 s depois da escrita. Precisa do `KAMBA_ENV` e do
`doppler_llm_chaves_escrita` no ambiente, e recusa sem eles antes de falar com o
proxy. O `revogar` **não** apaga o segredo do cofre: para cortar um tenant de vez,
apaga-se também o segredo.

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
  `KAMBA_ENV=prod` o *gate* de destino recusa **todos** os fornecedores
  enquanto nenhuma linha de `platform.tenant_destinations` estiver
  `autorizado` com `apd_ref` (ADR-008). A tabela **existe** desde o KAM-069
  e nenhuma das onze linhas do inventário está autorizada — o `ext:KAM-105`
  fechou com **0 de 14** destinos com `apd_ref`. Uma chave nova não abre
  essa porta, e quem a abre é a APD.

---

## 6. O que a edição MIT permite, e o que fica manual (KAM-072, critério 9)

O critério pede que esta página diga o que a parte MIT do LiteLLM permite, e que o
resto fique como **passo manual com dono e data** — a data é o critério de saída do
NÃO VERIFICADO. A fonte é o `E4` §2.7, que herda o seu estado: a licença é
**CONFIRMADO**; a divisão de funcionalidades entre MIT e Enterprise é
**CONFIRMADO em resumo** (página de preços, não o código).

| Capacidade | Edição | Estado | O que se faz no Piloto |
|---|---|---|---|
| Criar, actualizar e listar chaves virtuais (`/key/generate`, `/key/update`, `/key/list`) | MIT | CONFIRMADO em resumo (`E4` §2.7: «virtual keys/users/teams»); os três foram **medidos** contra a imagem fixada (`../evidencia/KAM-030-litellm.md`, citado no `infra/llm/chaves.py`) | §3 desta página |
| Apagar uma chave virtual (`/key/delete`) | MIT, por inferência | **CONFIRMADO** contra a imagem fixada, com base: 200, e a chave deixa de autenticar; 404 numa repetição (`../evidencia/KAM-233.md` §3). O `chaves.py revogar` usa-o, e o KAM-247 mediu-o contra o proxy com a `kamba_litellm` (`../evidencia/KAM-247.md` §3) | §3, «rodar o valor» |
| Orçamentos e *rate limits* por chave | MIT | CONFIRMADO em resumo | §3 (corte por `max_budget: 0`) |
| **Rotação automática de chaves** (*key rotation*) | Enterprise | CONFIRMADO em resumo | **manual**: §1, §2 e §3 |
| ***Secret managers*** (ler as chaves de fornecedor de um cofre) | Enterprise | CONFIRMADO em resumo | **manual**: o valor entra por variável de ambiente no arranque (`ADR-L002`) e muda recriando o contentor |
| ***Audit logs*** do proxy | Enterprise | CONFIRMADO em resumo | **manual**: o `Rotador` do `packages/core-ts/src/keyring/` aceita as três famílias, incluindo as por instância (`litellm_virtual_key/<tenant_id>`), e grava identificador e hora, nunca o valor — mas nenhum processo o corre, e o registo no `audit_log` é a caixa devolvida do critério 7 do KAM-072 |

**Os passos manuais, com dono e data.** O dono é o `owner` das três entradas no
`ops/secrets-inventory.yaml` (`eng_runtime`). A data é **proposta**: a primeira
rotação de 90 dias a contar da data deste bloco, e é nela que os NÃO VERIFICADOS
da tabela se confirmam numa instância real ou se reescreve esta secção.

| Passo manual | Dono | Data (proposta) | Sai do NÃO VERIFICADO quando |
|---|---|---|---|
| Rodar a `litellm_master_key` (§1) | `eng_runtime` | 2027-02-14 | o passo 4 do §1 correr contra o proxy implantado (KAM-078) e devolver 0 |
| Rodar as `llm_provider_key/<fornecedor>` (§2) | `eng_runtime` | 2027-02-14 | a consola de cada fornecedor confirmar duas chaves vivas em simultâneo |
| Rodar as `litellm_virtual_key/<tenant_id>` (§3) | `eng_runtime` | 2027-02-14 | o `/key/delete` da segunda linha for medido contra o proxy implantado |

**A data não é compromisso de ninguém.** É a que esta página propõe, e quem a fixa
é o dono — uma data que ninguém aceitou é uma data que passa sem nada acontecer.
