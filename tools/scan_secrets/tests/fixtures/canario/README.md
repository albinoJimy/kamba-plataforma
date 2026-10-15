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
