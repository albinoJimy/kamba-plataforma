# `compose_prod` — o contrato do compose de produção (KAM-076)

Verifica que o Compose de produção do **conjunto reduzido** é o que o
`docs/tecnica/09` §3 desenha: exactamente os serviços previstos, imagens por
*digest*, quatro redes isoladas, contentores endurecidos com limites, réplicas
com `/healthz`, e as *flags* de edição paga inactivas.

```bash
cd tools && python -m compose_prod --root .. lint        # criterios 1, 2, 4, 5, 8
cd tools && python -m compose_prod --root .. canario     # a prova de que morde
cd tools && python -m compose_prod --root .. gerar       # a config do proxy de saida
cd tools && python -m compose_prod --root .. egress-dez  # criterio 3, com Docker
```

Pelo `make`: `make compose-prod-lint` (gate 2) e `make compose-prod-egress`
(gate 6).

---

## 1. Onde cada critério se prova, e porque não é tudo no mesmo sítio

| Critério | Onde | Porque ali |
|---|---|---|
| 1 — conjunto exacto e *denylist* | `lint` | é uma propriedade do ficheiro |
| 2 — imagens por `@sha256:` | `lint` **e** `supply_chain imagens` | ver §4 |
| 2 — perfil `staging-obs` só em *staging* | `lint` | lê os dois ficheiros e compara |
| 3 — redes isoladas, egress *default-deny* | `lint` (a forma) **e** `egress-dez` (o facto) | **uma rota não se lê num ficheiro** |
| 4 — endurecimento e limites | `lint` **e** `supply_chain runtime` | ver §4 |
| 5 — réplicas, `/healthz`, portas | `lint` | forma do ficheiro |
| 6 — compatibilidade da fila | [`../../docs/adr/ADR-L009-ensaio-da-valkey.md`](../../docs/adr/ADR-L009-ensaio-da-valkey.md) | exige a fila e os consumidores a correr |
| 7 — SeaweedFS (D6) | [`../../docs/evidencia/KAM-076.md`](../../docs/evidencia/KAM-076.md) §6 | a **D6 está aberta** e este ticket não a decide |
| 8 — *flags* de licença | `lint` (Chatwoot, Langfuse) e `lint_arch medusa` (Medusa) | o Medusa já tinha *lint* próprio (KAM-042) |

---

## 2. As três fontes, e a regra que as liga

```
infra/compose/conjunto-reduzido.yaml   o conjunto declarado: presente | pendente | proibido
infra/compose/docker-compose.prod.yml  o que corre
infra/egress/proxy-saida.yaml          a allowlist do proxy
        |
        +--> infra/compose/envoy/envoy.yaml   GERADO daqui (`gerar`)
```

O manifesto existe porque «exactamente» tem **dois sentidos**: um teste que só
leia o compose sabe o que *está* lá e não sabe o que *devia* estar. Um serviço
`pendente` tem de **não** estar no compose, e traz o ticket que o há de trazer —
assim o que falta é contado em voz alta em cada execução em vez de ser esquecido.

A allowlist liga-se nos dois sentidos às listas de saída por serviço
(`infra/egress/*.yaml`, `services/*/egress.yaml`):

* um destino declarado por um serviço de produção **tem** de estar na allowlist
  — senão o contrato diz «sai» e a rede recusa;
* um destino na allowlist **tem** de ser declarado por algum serviço de produção
  — senão é um destino aprovado **sem dono**, que é o contrário de negar por
  omissão.

---

## 3. O canário: por mutação, não por *fixtures*

As regras daqui são sobre **relações entre três ficheiros**. Uma *fixture* por
regra não seria um ficheiro, seria uma árvore — e trinta cópias da árvore
divergem da árvore real sem que nada avise, deixando o canário verde sobre uma
configuração que já não se parece com a que o *gate* verifica.

Por mutação parte-se da árvore **real**, muda-se uma coisa e exige-se o achado.
Quarenta e cinco casos, e cada um tem de:

1. **aplicar-se** — se o texto que troca já não existe, é falha (`NaoSeAplica`),
   nunca um verde. É a armadilha própria desta forma, e é esta a rede;
2. dar vermelho **pelas regras que declarou, e só por essas** — ser apanhado por
   outra regra é sorte, não cobertura.

E `MINIMO_POR_REGRA` fecha o terceiro lado: **toda** a regra de `REGRAS` tem de
ter caso. Uma regra nova sem canário falha o canário.

---

## 4. O que este módulo **não** verifica, e já está verificado

Duas coisas do critério 4 não têm regra aqui, e a ausência é deliberada:

* **`read_only: true`** — o `supply_chain runtime` já o exige em *todos* os
  serviços de *todos* os compose do repositório (`fs-so-de-leitura`), com
  canário próprio. Repetir dava duas mensagens para o mesmo defeito e duas
  regras a divergir com o tempo.
* **imagem no inventário, com o *digest* lido da fonte** — é o
  `supply_chain imagens`, que também apanha a entrada morta.

A regra `imagem-por-etiqueta` daqui **existe mesmo assim**, e é a única
duplicação consciente: o critério 2 pede «um teste de CI falha caso contrário»
**sobre o ficheiro de produção**, e um *gate* que varre o repositório inteiro
não diz, ao falhar, que foi o compose de produção que o quebrou.

---

## 5. A regra que não morde hoje, e está dito

`admin-sem-vpn` (critério 5: «Medusa admin e Grafana só por VPN») **vê zero
serviços**: nem o `medusa` nem o `grafana` estão no compose de produção — o
primeiro não tem imagem publicada (KAM-042), os dois últimos são AGPL-3.0, que
o `ci/licenses.yaml` nega (KAM-080). É uma **sentinela**: fica verde sobre nada
e dispara no dia em que um deles nascer com `ports:`. A forma é a mesma do
`_rotas_internas_do_com` em [`../lint_arch/medusa.py`](../lint_arch/medusa.py),
e o canário prova que morde — o caso `admin-sem-vpn` faz nascer um Grafana com
porta publicada.

---

## 6. O guião dos dez destinos mede a **política**, não a ligação

`egress-dez` levanta o `proxy-saida` do **próprio** `docker-compose.prod.yml`,
com as quatro redes de verdade, e põe duas sondas por `docker run`: uma em
`data`, outra em `app`. As sondas não são serviços de nenhum compose, de
propósito — um serviço de ensaio pediria lista de saídas própria e apareceria no
conjunto reduzido.

Exige-se que um destino permitido receba algo que **não** seja 403, e que um
recusado receba **exactamente** 403. Não se exige 200: um guião que o exigisse
dava vermelho em qualquer *runner* sem saída para a Internet, e seria desligado
pela primeira pessoa que o encontrasse vermelho sem ter nada quebrado.

E lê o `access_log` do proxy à procura de uma linha `veredicto: 403` por cada
recusa — a metade «**e registadas**» do critério 3, que é a que se esquece. O
Envoy escreve stdout com *buffer*: espera-se pelas linhas em vez de as ler uma
vez, porque uma primeira versão via **uma** das dez e um *gate* que falha ao
acaso é um *gate* que alguém desliga.

---

## 7. O que fica por cumprir, e está escrito e não escondido

Dois destinos que o critério 3 nomeia como **permitidos** estão hoje
**recusados**, e o guião testa-os assim:

| Destino | Porque está recusado |
|---|---|
| FQDN do facilitador (`api.proxypay.co.ao`) | CONFIRMADO em `E2` §1.2, mas **nenhum serviço do repositório o declara**: não há `services/pay/`, e o adaptador de pagamento é o KAM-056. Pô-lo na allowlist criava um destino aprovado sem dono, e seria transferência sem `apd_ref` (KAM-069) |
| FQDN de STT | nenhum provedor de *speech-to-text* está escolhido nem declarado em `llm/aliases.yaml`. Um FQDN de STT aqui era invenção |

O critério 3 fica **parcialmente satisfeito**. O mecanismo está inteiro — abrir
qualquer um dos dois é escrever duas linhas e correr `gerar` —, e o que falta é
o dono.

E os cinco serviços **nossos** (`gwy`, `worker-canal`, `agr`, `com`,
`onboarding-web`) vêm por `build:` e não por `image:` com *digest*: o
`release.lock` é produzido pelo **KAM-078**, que depende deste ticket. A
inversão está registada em [`../../docs/evidencia/KAM-076.md`](../../docs/evidencia/KAM-076.md)
§5, e o critério 2 **não** se marca como feito por isso.
