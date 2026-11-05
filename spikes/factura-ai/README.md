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
em fornecedor nenhum**. A terceira é a que se corre quando as chaves de teste
existirem — e obter essas chaves é acto do fundador, não desta pasta.

## O que mede

| # | Predicado do critério 4 |
|---|---|
| 1 | Criar organização — uma por PME, com identificadores distintos |
| 2 | Emitir factura, com numeração fiscal |
| 3 | Emitir proforma **sem** numeração fiscal e com o rótulo que o `E5` B10 exige |
| 4 | Emitir nota de crédito sobre a factura, e **recusar** uma sem documento de origem |
| 5 | Repetir com a mesma `idempotencyKey` 2× e obter **um** documento |
| 6 | Verificar a assinatura HMAC-SHA256 do *webhook*, e **recusar** um corpo adulterado |
| 7 | O *sandbox* **não** submete à AGT |

Quatro dos sete têm **metade negativa** — a nota órfã, o corpo adulterado, a
proforma numerada, a segunda chamada com a mesma chave. Sem ela, um provedor que
dissesse sempre «sim» passava no ensaio, e o ensaio não media nada.

## O canário, e porque existe

`provedor_mock.py` guarda de facto a chave de idempotência e assina de facto
sobre o corpo que viaja. **Um falso que decidisse pelo nome do ensaio ficava
verde com a implementação apagada** — e o relatório teria uma linha de evidência
que não media predicado nenhum.

O `--canario` estraga o *mock* de seis maneiras e **exige que o ensaio
correspondente fique vermelho** em cada uma:

| Defeito injectado | Ensaio que tem de avermelhar |
|---|---|
| `idempotencia-ignorada` | 5 |
| `assinatura-de-outro-corpo` | 6 |
| `segredo-errado` | 6 |
| `proforma-numerada` | 3 |
| `nota-sem-origem` | 4 |
| `sandbox-submete` | 7 |

A assinatura tem **dois** defeitos e não um de propósito: assinar outro corpo e
assinar com outro segredo são falhas distintas, e um único defeito podia cobrir
só uma delas.

## Fronteiras

- **Sem NIF reais.** Os NIFs têm a forma `SINTETICO-<n>`, que não é a de um NIF angolano. O próprio *mock* recusa com `422` um NIF que não comece por `SINTETICO-`: a fronteira está no instrumento e não só na intenção de quem o corre.
- **Sem dados pessoais.** Nenhum nome, telefone, morada ou `contact_id` de pessoa real entra aqui. Os nomes de loja são inventados.
- **Sem chaves em ficheiro.** O segredo do *webhook* é gerado pelo provedor em cada arranque (`secrets.token_hex`) e entregue na resposta ao registo. Não há nenhuma chave neste repositório para apagar — e quando houver chaves de teste de um fornecedor, vivem no cofre e apagam-se no fim do *spike*, como o DoD do ticket manda.
- **Nenhuma chamada a fornecedor.** O `--base` existe para quem tiver as chaves; esta sessão nunca o usou.

## Ficheiros

| Ficheiro | O que é |
|---|---|
| `provedor_mock.py` | O *mock*: servidor HTTP com organizações, documentos, idempotência e *webhook* assinado; aceita os seis defeitos do canário |
| `sandbox.py` | O cliente: os sete ensaios, o receptor de *webhook*, e o canário |
