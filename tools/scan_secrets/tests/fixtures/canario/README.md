# Canário do gate 9

Esta pasta contém **um segredo com forma real**, de propósito. É o canário que
prova que o scanner funciona: o teste copia-o para fora desta pasta e exige que
seja detectado.

Os valores aqui **não são credenciais a sério** — são cadeias construídas para
baterem nos padrões de forma, e nunca foram emitidas por nenhum serviço. Mas têm
a forma exacta de credenciais reais, e é essa a questão: se o scanner não os
apanhar, não apanha os verdadeiros.

A pasta está declarada em `ci/secrets-allow.yaml` com as quatro classes reais
(`chave_api`, `chave_privada`, `credencial_em_url`, `atribuicao`) — não com uma
classe `canario`, que nunca existiu: a primeira versão desta linha nomeava-a, e
nomear uma classe inexistente é precisamente o que fazia a área não permitir
nada. É a
única área onde um valor com forma de segredo é permitido. Se essa entrada
desaparecer, este ficheiro faz o gate 9 ficar vermelho — e é isso que se quer.

---

## Antes de acrescentar um valor aqui, leia isto

Num repositório público o GitHub tem o seu **próprio** detector de segredos, e
ele também olha para esta pasta. Quando vê aqui uma coisa com forma de
credencial, a *push protection* **recusa o `push`**.

Foi o que aconteceu quando a cópia pública foi criada: o `push` foi recusado com
`GH013 — Repository rule violations`, a nomear duas linhas desta pasta — um
*Slack API Token* e uma *Stripe API Key* — e a oferecer um URL de desbloqueio
para cada uma. O fundador clicou «It's used in tests» nas duas, e foi assim que
a cópia pública ficou criada.

> **O texto acima é o que está registado no bloco do KAM-157, e não uma
> transcrição literal do que o GitHub escreveu.** A mensagem exacta não ficou
> guardada em lado nenhum, e não se inventa a saída de uma ferramenta num
> documento de segurança: quem a vier a ver outra vez deve colá-la aqui, por
> baixo desta nota, e apagar a nota.

### O que acontece hoje

**Nada.** Desde o KAM-157 existe um [`.github/secret_scanning.yml`](../../../../../.github/secret_scanning.yml)
que diz ao GitHub para não olhar para **esta pasta e só para esta pasta**. O
`push` passa.

Decisão do fundador, **2026-10-18**: via A. A alternativa era desbloquear à mão
de cada vez, que não deixa nada escrito no repositório e cria fricção repetida
com uma mensagem que não explica que é esperada.

### O que isso não muda

**O gate 9 continua a ver tudo o que está aqui.** São dois detectores:

| | Olha para esta pasta? |
|---|---|
| O do GitHub (*push protection*) | **não**, desde o KAM-157 |
| O nosso (`tools/scan_secrets`, gate 9) | **sim**, e o `make ci-9` copia estes ficheiros para fora da área permitida e exige nove achados ou mais. Hoje dá 17 |

E as duas listas não podem divergir: o
`tools/scan_secrets/tests/test_push_protection.py` fica vermelho se o
`paths-ignore` deixar de coincidir, exactamente, com a área que o
`ci/secrets-allow.yaml` declara. Uma área cega que ninguém declarou é o único
modo de falha sério desta via, e é esse teste que o fecha.

### E não baixe a forma dos valores

Já se tentou, e é o que torna o canário inútil. Ele prova que o scanner apanha a
**forma** de uma credencial; com valores de forma mais fraca, prova menos.
