# KAM-030 — o que se mediu contra a imagem fixada do LiteLLM

Medido a **2026-10-26**, nesta máquina, contra a imagem por digest e **sem rede**
(`docker run --network none`) excepto onde se diz o contrário. O ticket manda
validar estes nomes «na versão fixada (L5)», e é isto.

| Campo | Valor |
|---|---|
| Imagem | `ghcr.io/berriai/litellm:v1.104.2` |
| Digest | `sha256:3d88bd757134a00e8c00237b85a021ab1f6d54abb9c1df750f411dbe7256a500` |
| Lido de | `docker buildx imagetools inspect ghcr.io/berriai/litellm:v1.104.2` (índice OCI multi-arquitectura) |
| Versão do pacote dentro da imagem | **1.104.2** (`importlib.metadata.version("litellm")`) |
| Estado | **CONFIRMADO** |

O mesmo digest sai de `docker.io/litellm/litellm:v1.104.2` e de
`ghcr.io/berriai/litellm:1.104.2`: é o mesmo índice. A versão é a que o
`ci/supply-chain/licencas.yaml` já tinha escrito (lida a 2026-10-08), e está
acima do piso `1.83.0` de `tools/blocklist.yaml` e fora de {1.82.7, 1.82.8}.

---

## 1. A assinatura cosign existe, e **não é *keyless*** — CONFIRMADO

O `ci/supply-chain/imagens.yaml` diz que o LiteLLM «não pode vir com `n/a` nem
com `por_apurar`: a assinatura está publicada desde a v1.83.0». Está:

```
docker buildx imagetools inspect \
  ghcr.io/berriai/litellm:sha256-3d88bd...a500.sig
→ Digest: sha256:076e5aeab0f2ed3dfc69406fafc6e055042f583632fcc4b949a817e59d405344
```

A etiqueta `.sig` do esquema antigo do cosign **resolve** para um manifesto real
(ao contrário das quatro imagens que o KAM-067 deixou em `por_apurar`, onde dava
`not found`). A entrada do Rekor está no `bundle`: `logIndex` **3144616019**,
`integratedTime` **1791448609**.

**E aqui está o que ninguém tinha medido.** O manifesto da assinatura tem uma
camada com duas anotações — `dev.cosignproject.cosign/signature` e
`dev.sigstore.cosign/bundle` — e **nenhum certificado**. O corpo do Rekor é um
`hashedrekord` cujo `publicKey.content` é:

```
-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEKi4ivqGpE231OGH50PKbqy1Y1Kkb
POJC8+i2Wko82gBOUCe3M0Vw86H/4rhUhfoYEti4gdJ9wZbYmK0I2EE96g==
-----END PUBLIC KEY-----
```

uma chave **ECDSA P-256** (`prime256v1`), não um certificado X.509. Ou seja: o
LiteLLM assina **com uma chave**, não pelo fluxo *keyless* do Fulcio.

### 1.1 A chave que se fixa é a **publicada**, e não esta — e as duas diferem

A primeira versão deste ticket fixou a chave acima, extraída do *bundle*. **A
revisão adversarial reprovou-a, e com razão:** numa verificação por chave, a
chave é a raiz de confiança, e tirá-la do artefacto que ela vai verificar torna
o `cosign verify --key` tautológico — confirma que a assinatura é internamente
consistente, não **quem** assinou. No dia em que alguém suba o digest para uma
imagem adulterada (o cenário do incidente de 2026-03-24), repetir a extracção
extraía a chave do atacante.

O projecto **publica** a chave — e aqui começa a parte que só se soube medindo.
A que está em `main` é:

```
curl -sSfL https://raw.githubusercontent.com/BerriAI/litellm/main/cosign.pub
-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEG06dpKM+vEDnmp2zcjyXgVCXxzRg
JA5H2LnmwBKQafZGka6OOrWujCEWATQewiAgyD4WQdJ0pvU9RC4mvNAjvQ==
-----END PUBLIC KEY-----
```

**E ela não verifica este digest.** Medido no *gate* 11, com o `cosign` 3.1.4
instalado no *runner*:

```
[cosign-falhou] `cosign verify` falhou para ghcr.io/berriai/litellm@sha256:3d88bd…:
Error: no matching signatures: error verifying bundle:
comparing public key PEMs, expected -----BEGIN PUBLIC KEY-----
```

**A razão é uma rotação, e é o que torna esta secção útil para o futuro.** O
histórico de `cosign.pub` tem dois *commits*:

| *commit* | Data | Mensagem |
|---|---|---|
| `0112e53046` | 2026-03-31 | «[Infra] Add release workflow and cosign public key» |
| `e82a3c6469` | **2026-10-23** | «Rotate the cosign image-signing public key» |

A assinatura da `v1.104.2` é de **2026-10-08** (`integratedTime 1791448609`), ou
seja **quinze dias antes da rotação**. A chave que o projecto publicava nessa
data — lida de `…/BerriAI/litellm/0112e53046/cosign.pub` — é:

```
-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEKi4ivqGpE231OGH50PKbqy1Y1Kkb
POJC8+i2Wko82gBOUCe3M0Vw86H/4rhUhfoYEti4gdJ9wZbYmK0I2EE96g==
-----END PUBLIC KEY-----
```

**que é exactamente a do *bundle*.** É essa que está fixada.

Três coisas se seguem, e as três importam a quem vier depois:

1. **A chave do *bundle* era a chave de assinatura genuína** — mas isso não se
   podia saber *do bundle*. A objecção da revisão adversarial mantém-se de pé
   por inteiro: tirá-la de lá não prova **quem** assinou. O que a provou foi uma
   segunda fonte, independente do artefacto.
2. **Fixa-se um *commit*, nunca `main`.** Um `cosign.pub` buscado a `main` dá a
   chave de hoje, que não verifica uma imagem assinada antes da rotação — e o
   *gate* fica vermelho sem nada estar comprometido. A entrada do inventário
   nomeia o *commit* e a data.
3. **Uma rotação de chave do fornecedor é um evento a seguir.** Quando o digest
   subir para uma versão assinada depois de 2026-10-23, a chave fixada tem de
   passar a ser a de `e82a3c6469`. Isso está na linha **117** de
   `../dividas-documentais.md`, que é o que resta deste achado.

**Consequência para o CI, e é uma correcção a código já fundido.** O
`tools/supply_chain/cosign.py` monta o comando com `--certificate-identity` e
`--certificate-oidc-issuer`, e o `imagens.yaml` exige os campos
`cosign_identidade` e `cosign_emissor` para o estado `verificar`. Numa assinatura
por chave **não existe identidade OIDC nem emissor**: esses dois argumentos não
têm valor possível, e `cosign verify` com eles falharia. O próprio módulo
avisava: «a forma exacta dos argumentos … é a da documentação do cosign 2.x
**lida de memória**: NÃO VERIFICADO. Quem ligar a primeira imagem confirma-a
nessa altura.» Esta é a primeira imagem, e confirmou-se que estava errada para
este caso.

O que o KAM-030 faz: acrescenta o campo `cosign_chave_publica` ao inventário e
faz o `cosign.py` escolher a forma do comando pelo material que a entrada
declara — `--key` para uma chave, os dois `--certificate-*` para uma identidade.
Uma entrada com os dois, ou com nenhum, é recusada.

**O que continua NÃO VERIFICADO:** que `cosign verify --key <ficheiro>
<nome>@<digest>` passa de facto — e, depois do §1.1, isso deixou de ser uma
formalidade: há duas chaves candidatas e a medição é que decide. O binário não
existe nesta máquina; o *job* do *gate* 11 passou a instalá-lo (fixado por
versão, com `sha256` lido da *release*), pelo que a primeira execução a sério é o
CI. O `cosign.py` **falha fechado** sem binário (`cosign-sem-binario`), que é o
comportamento certo e já era o dele.

---

## 2. Os três `router_settings` do §13.1 — CONFIRMADO

O bloco do ticket dá-os como «nomes a validar na versão fixada, L5».

```python
Router(model_list=..., num_retries=1, allowed_fails=3, cooldown_time=30)
→ r.num_retries == 1 ; r.allowed_fails == 3 ; r.cooldown_time == 30
```

Os três são aceites e ficam efectivos. **Uma armadilha pelo caminho:** o tipo
`litellm.types.router.RouterConfig` (20 campos) **não tem** `cooldown_time` —
quem validasse por ele concluía que o nome está errado. O que o proxy usa é
`Router.__init__`, que o aceita (ao lado de `disable_cooldowns`,
`retry_policy`, `allowed_fails_policy`). O `RouterConfig` não é o caminho de
validação.

`litellm.turn_off_message_logging` existe, e é o que mantém o corpo das
mensagens fora dos *logs* do proxy (DoD de privacidade).

---

## 3. O prefixo de fornecedor não é o nome do subprocessador — CONFIRMADO

```
anthropic/modelo-x   → ACEITA (provider=anthropic)
openai/modelo-x      → ACEITA (provider=openai)
google/modelo-x      → RECUSA (BadRequestError: LLM Provider NOT provided)
gemini/modelo-x      → ACEITA (provider=gemini)
vertex_ai/modelo-x   → ACEITA (provider=vertex_ai)
```

Dos **162** prefixos que esta versão reconhece, nenhum se chama `google`. O
subprocessador do `docs/tecnica/08` §8.3.2 chama-se **Google**; o prefixo é
`gemini`. O `tools/llm_config` mapeia um no outro e **levanta** se um fornecedor
aprovado não tiver prefixo — a primeira configuração que gerei tinha
`google/por_decidir` e o `Router` recusou-a no arranque.

Os dois espaços de nomes ficam separados: o nome do subprocessador é o que o
ADR-008 e o `tenant_destinations` (KAM-069) usam para autorizar uma
transferência, e não se renomeia para acompanhar uma biblioteca.

---

## 4. A configuração do §13.1, à letra, **não cumpre o critério 6** — CONFIRMADO

É o achado que mudou o desenho, e saiu de medir, não de ler.

O `docs/tecnica/02` §13.1 escreve duas entradas de `model_list` com o **mesmo**
`model_name` (`kamba-chat`) e conta com `num_retries: 1` para comutar. Montei
exactamente isso, pus o fornecedor de `ordem: 1` a falhar **sempre**
(`InternalServerError`), e corri 20 vezes, cada uma com um `Router` novo para não
herdar *cooldown*:

| Medida | Grupo único (§13.1 à letra) | Dois grupos + `fallbacks` |
|---|---|---|
| Corridas com sucesso | **17 de 20** | **20 de 20** |
| Corridas que falharam por completo | **3** | **0** |
| Começaram no fornecedor de `ordem: 1` | 9 de 20 | **20 de 20** |
| Dessas, comutaram para o segundo | 6 de 9 | 20 de 20 |
| Tentativas por corrida | 1 a 2 | 3, sempre |

A causa: a estratégia por omissão é **`simple-shuffle`** — aleatória. Num grupo de
dois *deployments* **não existe «fornecedor primário»**, e a `ordem` do
`llm/aliases.yaml` não teria efeito nenhum; pior, o único *retry* pode reescolher
o mesmo *deployment* avariado, e foi o que aconteceu em 3 das 20.

Com a `ordem: 1` num grupo com o nome do alias, as seguintes em
`<alias>-fallback<ordem>`, e um `fallbacks` nomeado a ligá-los, a sequência é
sempre a mesma: `anthropic`, 1 *retry* de `anthropic`, `openai`.

**A leitura de «≤ 1 retry», escrita porque a letra admite duas.** A sequência tem
**três** tentativas, não duas. As duas leituras possíveis de «comuta para o
segundo aprovado em ≤ 1 retry» são «no máximo um *retry* do primário antes de
comutar» (satisfeita: é exactamente um) e «no máximo duas tentativas até ao
sucesso» (não satisfeita). A segunda é **impossível** de satisfazer ao mesmo
tempo que o critério 3, que manda `num_retries: 1` — com um *retry* configurado,
o primário é tentado duas vezes por desenho. Fica a primeira, que é a única
leitura em que os dois critérios do mesmo bloco podem valer juntos.

---

## 5. O LiteLLM sai para a Internet no `import` — CONFIRMADO

Com rede, `import litellm` tenta descarregar
`https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`
— **três vezes**, com recuo, antes de cair para a cópia local:

```
LiteLLM:WARNING: get_model_cost_map.py:315 - model cost map fetch attempt 1/3 failed …
LiteLLM:WARNING: get_model_cost_map.py:672 - … Falling back to local backup.
```

`raw.githubusercontent.com` **não está** em `infra/egress/litellm.yaml` e não vai
entrar: é a mesma classe de achado do `beacon.langchain.com` que o critério 7 do
KAM-025 existe para fechar, e fecha-se do mesmo modo — desligar a saída, não
declarar o destino. `LITELLM_LOCAL_MODEL_COST_MAP=True` no compose fá-lo, e com
ele os avisos desaparecem.

**Porque é que isto importa mais aqui do que parece:** o mapa de preços é o que o
LiteLLM usa para calcular custo. Descarregá-lo de um repositório público em cada
arranque fazia o custo registado em `dat.llm_call_log` depender de um ficheiro de
terceiros que muda sem aviso — e o cálculo de custo é um critério de aceitação
deste ticket. É também a razão pela qual o custo se calcula do **nosso** tabelário
(`llm/precos.yaml`, do `E4` §3) e não do mapa do LiteLLM.

---

## 6. Como se repete

```bash
docker buildx imagetools inspect ghcr.io/berriai/litellm:v1.104.2
docker buildx imagetools inspect ghcr.io/berriai/litellm:sha256-<digest>.sig
docker run --rm --network none -e LITELLM_LOCAL_MODEL_COST_MAP=True \
  --entrypoint python ghcr.io/berriai/litellm@sha256:<digest> -c "…"
```

As três medições das secções 2 a 4 estão nas baterias de
`tools/llm_config/tests/` e `services/agr/tests/test_llm_*.py` como asserções
sobre a configuração **gerada**; a secção 4 não corre no CI, porque exige a
imagem do proxy e o *gate* 5 está reservado.
