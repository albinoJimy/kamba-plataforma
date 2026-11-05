# `spikes/factura-ai` — instrumento de medição do KAM-126

Instrumento de medição do *spike* **KAM-126 — Spike Factura AI: parceiro
certificado AGT, API e custo**. O relatório, com a ficha dos candidatos, a
matriz de adequação, o modelo de custo e a recomendação sobre a decisão aberta
**D7**, está em
[`docs/tecnica/evidencia/validacao/KAM-126_Factura_AI.md`](../../docs/tecnica/evidencia/validacao/KAM-126_Factura_AI.md).

**Isto não é código de produção, não é um portão, e é descartável.** O
`InvoiceProvider` é da Fase 2 e não existe (`../../specs/INDICE.md` §6). O que está
aqui é o mínimo que torna **mensuráveis** os sete predicados do critério 4 do
bloco do ticket — e nada mais entra na `main` por causa disto. Se D7 fechar num
parceiro, o adaptador de produção nasce no epic de Clusters, e esta pasta
apaga-se.

## Como se corre

Precisa de **Python 3.11+** e de nada mais: biblioteca padrão, sem dependências,
sem Docker, sem rede. Não precisa de `node` nem de `pnpm` — nesta máquina não
existem.

```bash
python spikes/factura-ai/sandbox.py
```

```bash
python spikes/factura-ai/sandbox.py --canario
```

```bash
python spikes/factura-ai/sandbox.py --base https://sandbox.exemplo.ao
```

A primeira forma é a que o ticket exige: **corre contra um *mock* antes de tocar
em fornecedor nenhum**.

> **A terceira forma não funciona contra um fornecedor como está, e é importante
> dizê-lo aqui.** O contrato que este cliente fala é o do `provedor_mock.py`,
> inventado para a medição: rotas `/v1/.../documents`, cabeçalho
> `X-Mock-Signature`, segredo entregue no corpo do registo, campos em português,
> e **nenhuma autenticação**. O `E2` §6.2 documenta, para a Vero,
> `POST /v1/organisations/{ORG_ID}/invoices`, `X-Vero-Signature` e um
> `Bearer vero_test_sk_...` obrigatório. Apontado ao *sandbox* de um fornecedor,
> este cliente **devolve 401 na primeira chamada e corre zero ensaios**.
>
> Faltam, portanto, duas coisas e não uma: as **chaves de teste**, que são acto
> do fundador, e **adaptar o cliente** ao contrato real — autenticação, rotas,
> nomes de campo, cabeçalho de assinatura. A segunda está devolvida ao Engenheiro
> de Plataforma no §5.3 do relatório. **Não é «correr e ler».**

## O que mede

| # | Predicado do critério 4 |
|---|---|
| 1 | Criar organização — **uma por PME**: NIFs distintos dão organizações distintas, e o mesmo NIF **não** cria uma segunda |
| 2 | Emitir factura, com numeração fiscal |
| 3 | Emitir proforma **sem** numeração fiscal e com rótulo que a declara **não fiscal** (o risco B10 do `E5`) |
| 4 | Emitir nota de crédito sobre a factura, e **recusar** uma sem documento de origem |
| 5 | Mesma `idempotencyKey` 2× → **um** documento; e a chave **não** é partilhada entre contribuintes |
| 6 | O *webhook* é assinado (HMAC-SHA256 do corpo) **e** notifica o documento que foi emitido, da organização certa |
| 7 | O provedor **declara** que o *sandbox* não submete à AGT |

**O predicado 7 é uma declaração, não uma medição**, e o ensaio di-lo na saída:
lê o campo `submetido_agt` que o próprio provedor devolve, pelo que um provedor
que submeta à AGT e minta no campo **passa**. O que o fecha é a garantia por
escrito do fornecedor, que é a pergunta 7 do §2.3 do relatório — não este ensaio.

O predicado 3 (rótulo) usa um **predicado de texto próprio do cliente**, e não a
constante do *mock*: comparar o rótulo devolvido com a constante do provedor
punha alvo e oráculo no mesmo literal, e trocar o literal deixava o ensaio verde
com a proforma a declarar-se factura fiscal.

## O canário, e porque existe

`provedor_mock.py` guarda de facto a chave de idempotência e assina de facto
sobre o corpo que viaja. **Um falso que decidisse pelo nome do ensaio ficava
verde com a implementação apagada** — e o relatório teria uma linha de evidência
que não media predicado nenhum.

O `--canario` estraga o *mock* de dez maneiras e **exige que o ensaio
correspondente fique vermelho** em cada uma:

| Defeito injectado | Ensaio que tem de avermelhar | Veio de |
|---|---|---|
| `idempotencia-ignorada` | 5 | desenho inicial |
| `idempotencia-global` | 5 | **revisão adversarial** |
| `assinatura-de-outro-corpo` | 6 | desenho inicial |
| `segredo-errado` | 6 | desenho inicial |
| `webhook-de-outra-org` | 6 | **revisão adversarial** |
| `proforma-numerada` | 3 | desenho inicial |
| `rotulo-errado` | 3 | **revisão adversarial** |
| `nota-sem-origem` | 4 | desenho inicial |
| `nif-duplicado` | 1 | **revisão adversarial** |
| `sandbox-submete` | 7 | desenho inicial |

A assinatura tem **três** defeitos e não um de propósito: assinar outro corpo,
assinar com outro segredo e notificar o documento errado são falhas distintas, e
um único defeito podia cobrir só uma delas.

**Os quatro defeitos que a revisão adversarial acrescentou valem por si**, porque
cada um era um predicado que ficava verde sem estar a ser medido:

- `rotulo-errado` — o oráculo do rótulo era a constante do próprio *mock*. Trocar o literal por «Factura fiscal — documento válido para a AGT» dava **7/7 verdes** com a proforma a declarar-se documento fiscal, que é o risco B10 por inteiro.
- `idempotencia-global` — com a chave de idempotência partilhada entre contribuintes, a PME B pedia uma factura e recebia o documento da PME A. **7/7 verdes.**
- `webhook-de-outra-org` — um *webhook* **bem assinado** a notificar um documento que não foi o emitido, e de outra organização. **7/7 verdes**: a assinatura conferia e mais nada era verificado.
- `nif-duplicado` — dois pedidos com o mesmo NIF criavam duas organizações. «Uma organização por PME», que é o predicado 1 da matriz e aquele de que a condição (b) da regra depende, não estava medido.

**E o que o canário não prova:** que esta lista esgota as maneiras de quebrar o
contrato. Prova que cada ensaio reprova quando o seu predicado desaparece, o que
é menos — e é o que o *script* imprime no fim.

## Fronteiras

- **Sem NIF reais.** Os NIFs têm a forma `SINTETICO-<n>`, que não é a de um NIF angolano. O próprio *mock* recusa com `422` um NIF que não comece por `SINTETICO-`: a fronteira está no instrumento e não só na intenção de quem o corre.
- **Sem dados pessoais.** Nenhum nome, telefone, morada ou `contact_id` de pessoa real entra aqui. Os nomes de loja são inventados.
- **Sem chaves em ficheiro.** O segredo do *webhook* é gerado pelo provedor em cada arranque (`secrets.token_hex`) e entregue na resposta ao registo. Não há nenhuma chave neste repositório para apagar — e quando houver chaves de teste de um fornecedor, vivem no cofre e apagam-se no fim do *spike*, como o DoD do ticket manda.
- **Nenhuma chamada a fornecedor.** O `--base` existe para quem tiver as chaves; esta sessão nunca o usou.

## Ficheiros

| Ficheiro | O que é |
|---|---|
| `provedor_mock.py` | O *mock*: servidor HTTP com organizações, documentos, idempotência e *webhook* assinado; aceita os dez defeitos do canário |
| `sandbox.py` | O cliente: os sete ensaios, o receptor de *webhook*, e o canário |
