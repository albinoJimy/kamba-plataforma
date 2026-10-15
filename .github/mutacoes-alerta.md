A prova por mutação nocturna sobre `main` **não** ficou verde.

Começa por ver **qual** o job que falhou na execução ligada no fim deste texto:
se foi `mutacoes aplicaveis`, as fatias nem correram — alguém mudou código
mutado e não actualizou a lista. Se foram fatias, o nome da mutação está no
registo de cada uma (artefacto `mutacoes-fatia-N`).

**Isto não é um ticket do backlog.** O backlog vive em `specs/INDICE.md` §4, e é
quem ler isto que decide o que fazer. Três resultados, e não significam o mesmo:

- **Uma sobrevivente** é um teste em falta no código que a mutação altera — o
  defeito que esta prova existe para apanhar. Abre ticket `fix`, com o nome da
  mutação.
- **Uma `PROVA INVALIDA`** não é uma sobrevivente: é a *suite* a falhar por
  carga da máquina, por não carregar, ou por rebentar antes de chegar a um
  teste. Lê o detalhe na linha; se for carga, baixa
  `KAMBA_MUTACOES_PARALELO` em `.github/workflows/mutacoes.yaml`.
- **`MUTACAO NAO APLICAVEL`** é uma mutação cujo texto já não existe no ficheiro
  alvo: alguém mudou o código mutado e não actualizou a lista. A prova dessa
  mutação deixou de provar.

**O que isto não diz:** em que PR a mutação deixou de ser apanhada. A prova
corre sobre `main`, uma vez por noite — é o custo declarado da decisão de a
tirar do caminho dos PRs (`docs/ci.md` §3, gate 8, e o bloco do KAM-143). O `git log` desde
a última noite verde é onde se procura.

Enquanto este *issue* estiver aberto, as noites seguintes **não** abrem outro.
Fecha-o quando estiver tratado, senão a próxima sobrevivente passa calada.
