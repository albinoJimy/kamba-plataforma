"""Uma suite nao pode passar por causa da ordem em que o `unittest` a carrega.

O `unittest` carrega tudo por ordem alfabetica: os modulos porque o
`TestLoader._find_tests` faz `sorted(os.listdir(start_dir))`, e as classes e os
metodos dentro de cada modulo porque o `dir()` vem ordenado. (A primeira versao
desta pagina dizia «os modulos pela ordem do disco», e a revisao adversarial
mostrou o `sorted` no `unittest` — era a frase de abertura do modulo em que todo
o portao assenta.) **Nada promete essa ordem** — e nenhum teste deste
repositorio a pede de proposito. Um teste que so passa nela passa por acidente,
e o acidente desfaz-se sozinho: basta renomear uma classe, acrescentar um
ficheiro ou mudar de versao do interpretador.

Aconteceu, medido, no **KAM-163**: o ensaio que provava a troca da chave do
`tenant_guard` forcava a reutilizacao de um endereco de objecto, e passava
porque o `obmalloc` devolve o bloco libertado a cabeca da *pool* (LIFO) — as
cem tentativas valiam uma. Bastava o `unittest` carregar uma classe antes da
outra, e nada mais do que a ordem alfabetica o impedia, para ficar vermelho dez
vezes em dez. O ensaio foi corrigido nesse ticket; **a classe nao**, e e esta a
metade que falta: nada impedia o proximo ensaio desta familia de passar pela
mesma razao.

O portao corre cada suite **outra vez**, na ordem mais distante da de omissao
que continua deterministica, e exige que fique verde (ver `corredor`). Nao
prova independencia de ordem — prova que esta ordem tambem passa, que e o que
se consegue por uma execucao a mais. O que nao cobre esta dito no `cli`.

E tem canario: duas *fixtures* em `tests/fixtures/`, uma que **tem** de ficar
vermelha na ordem inversa e uma que **tem** de ficar verde nas duas. Sem a
segunda, um verificador que declarasse tudo dependente da ordem passava o
canario e nao servia para nada.

Nao ha re-exports aqui de proposito: os submodulos importam-se pelo nome
(`from ordem_dos_ensaios import canario, corredor`), e duas linhas de `__all__`
sem consumidor eram duas linhas para manter sincronizadas com nada — achado da
revisao adversarial.
"""
