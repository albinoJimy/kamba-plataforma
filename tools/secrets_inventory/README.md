# `secrets_inventory` — verificador do inventário de segredos (KAM-010)

Verifica `ops/secrets-inventory.yaml` em três eixos, todos *fail-closed*.

```sh
cd tools && python -m secrets_inventory --root .. all
```

Sem dependências externas: lê o YAML com `yamlsubset`, que aceita exactamente a
forma do inventário e recusa o resto. A razão é a do KAM-001 — as ferramentas
que correm nos *hooks* e no CI têm de funcionar num clone antes de qualquer
instalação.

## 1. `esquema`

Toda a entrada tem os quatro campos que o critério de aceitação do KAM-010 pede
(`owner`, `rotacao_dias`, `ambientes`, `consumidores`) e os que este ticket
acrescentou, com valores dentro dos domínios permitidos. Devolve **todos** os
erros e não o primeiro: quem escreve dezenove entradas corrige uma lista.

As regras com aresta, e porquê:

- `rotacao_dias: null` exige `rotacao_gatilho`. Dois segredos do doc 08 §5 rodam
  por evento e não por calendário (o token de cliente, no *offboard*; o PIN 2FA,
  quando a Meta o descontinuar). Pôr lá um número inventado seria pior do que
  `null`; `null` sem o evento escrito seria igualmente pior.
- `obrigatorio_em ⊆ ambientes`. Um segredo não pode ser obrigatório onde não
  existe — essa combinação produziria um serviço que nunca arranca.
- `consumidores` vazio exige `nota`. Três entradas têm lista vazia de propósito
  (o `kamba_migrator`, o WireGuard, o próprio *service token* do cofre), e em
  cada caso a propriedade que interessa é «nenhum serviço em execução o usa».
- `fonte_08_5: "-"` exige `introduzido_por`. Uma entrada que não vem do canon
  tem de dizer de que ticket vem.

## 2. `cobertura`

100% das linhas da tabela de `docs/tecnica/08` §5 estão cobertas por ao menos
uma entrada.

A tabela é **lida do documento**, não copiada para o código. Se alguém
acrescentar um segredo ao doc 08 §5, esta verificação falha no dia seguinte — que
é o ponto. A comparação normaliza acentos, *backticks* e negrito, para que a
cobertura não falhe por «número» contra «numero»; falhar por um acento é o tipo
de falha que ensina as pessoas a desligar a verificação.

Há também a verificação inversa (`orfas`): uma entrada que reclama uma linha que
não existe — tipicamente uma gralha na cópia do rótulo — é um erro. Sem ela, uma
gralha fazia a cobertura descer sem ninguém saber onde.

## 3. `uso` — «o código pede um segredo ausente do inventário»

Três coisas contam como pedir um segredo:

| Forma | Exemplo |
|---|---|
| Método próprio da porta | `.getRing("meta_app_secret")`, `.get_ring(…)`, `.versions(…)` |
| `get` com receptor conhecido | `secrets.get("meta_app_secret")`, `cofre.get(…)` |
| Nome de variável de ambiente | `KAMBA_SECRET_META_APP_SECRET` em compose, `Dockerfile`, `.env` |
| Lista de obrigatórios | `obrigatorios: ["meta_app_secret"]` / `obrigatorios=[…]` |

E uma quarta que não é um pedido mas falha de qualquer modo: **o pedido
dinâmico** (`secrets.get(nome)`). Não se consegue comparar com o inventário, pelo
que fica proibido; a saída é escrever o literal ou marcar a linha com

```
kamba:secrets-inventory dinamico <razao>
```

Uma marca sem razão não conta — uma excepção sem razão escrita é uma excepção que
ninguém revoga. O caso legítimo previsto é o do KAM-003: a referência vem de
`tenant_channels.token_ref` e por desenho não é um literal.

> **`get` sozinho não conta, e isso foi uma correcção.** A primeira versão deste
> verificador apanhava qualquer `.get("x")` e marcou 27 acessos a dicionário do
> `tools/` como segredos em falta. Um verificador que grita em
> `dados.get("version")` é um verificador que alguém desliga. Os nomes de
> receptor que qualificam um `get` estão em `RECEPTORES`, em `uso.py`.

As raízes analisadas e as excepções vivem no próprio inventário
(`analise_raizes`, `analise_excluir`), e cada excepção leva `razao`. Uma raiz
pode ser um **ficheiro** e não só um directório — é como o `.env.example` da raiz
do repositório entra na análise sem que declarar `.` varresse tudo. As excepções
de hoje são os ficheiros da própria porta e os seus testes: servem segredos ou
montam cenários, não os pedem.

**Consequência honesta:** sobre o repositório de hoje, `uso` encontra **5**
pedidos, todos no `.env.example`, porque nenhum serviço consome segredos ainda
(KAM-013, KAM-030 e KAM-056 é que vão). A prova de que a ferramenta funciona são
os casos de `tests/test_uso.py` — positivos e negativos — e não essa execução.

> **O que ela já apanhou de verdade.** Ao analisar o `.env.example` pela primeira
> vez, marcou `KAMBA_SECRET_X=`, que estava num comentário a explicar a regra do
> valor vazio, e marcou `KAMBA_SECRET_META_APP_SECRET_ANTERIOR` como um segredo
> chamado `meta_app_secret_anterior`. A primeira ficou como está — a ferramenta
> não distingue comentário de declaração num `.env`, e o comentário passou a usar
> `KAMBA_SECRET_<ID>=`, que lê melhor. A segunda era um defeito: `_ANTERIOR` é a
> segunda posição do anel do mesmo segredo, e sem o corte todo o `.env` com um
> anel definido falharia a verificação.

## 4. Ligar ao CI — **o que fica para o KAM-002**

Este ticket **não toca** no `Makefile`, em `.github/`, em `ci/` nem em
`docs/ci.md`: esses ficheiros são do KAM-002, que vive no ramo
`feature/KAM-002-pipeline-ci-gates` e ainda não fundiu. Quando fundir, o que
falta é:

| O que | Onde | Conteúdo |
|---|---|---|
| Alvo `make` | `Makefile` | `ci-secrets-inventory: @cd tools && $(PYTHON) -m secrets_inventory --root $(ROOT) all` |
| Entrada no `check` | `Makefile`, alvo `check` | acrescentar `ci-secrets-inventory` à lista de pré-requisitos |
| *Job* de CI | `.github/workflows/ci.yaml` | *job* `gate-9b-secrets-inventory`, a correr o alvo acima; é vizinho do gate 9 (segredos) e **não** o substitui: o gate 9 varre valores, este verifica nomes |
| *Required check* | `.github/rulesets/main.json` | acrescentar o contexto do *job* aos exigidos |
| Documentação | `docs/ci.md` | linha na tabela gate → alvo → dono |
| Testes desta ferramenta | `Makefile`, alvo `test-py` | **feito** — as suites de `tools/` descobrem-se pelo disco desde o KAM-142 |

Até lá, as duas ordens que correm tudo:

```sh
cd tools && python -m secrets_inventory --root .. all
cd tools && python -m unittest discover -s secrets_inventory/tests -t .
```
