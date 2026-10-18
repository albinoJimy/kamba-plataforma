"""Passa os diagramas Mermaid do conjunto por um *parser* a serio.

**Porque existe.** A regra do repositorio diz que «diagramas Mermaid passam por
um parser antes de se dizer que estao certos — escreve-los sem acentos nos IDs
nao prova que compilam». Ate ao KAM-140 nao havia forma de o fazer: o unico
*parse* real alguma vez corrido esta registado no `specs/EPIC-07` §, e foi feito
**a mao, num navegador**, com a nota de que «o script nao reproduz».

**O que faz.** Duas metades, e a divisao e deliberada:

* `extrair.py` — Python puro, sem dependencias, com testes. Le ficheiros
  Markdown e devolve cada bloco ```` ```mermaid ```` com o ficheiro e a linha.
  E a parte que pode errar em silencio (uma cerca mal fechada, um bloco dentro
  de outro), e por isso e a parte que tem bateria propria.
* `verificar.mjs` — corre `mermaid.parse` sobre cada bloco. Nao tem testes
  proprios: e uma chamada a biblioteca, e o que ela decide **e** o resultado.

**Porque nao e uma dependencia do repositorio.** O `mermaid` traz uma arvore
grande de terceiros, e po-la no `pnpm-lock.yaml` punha-a no SBOM e no veredicto
de licencas do gate 11 — para uma ferramenta que nao vai para producao nem e
importada por codigo nenhum. Corre num contentor descartavel, com a imagem do
`.node-version` fixada por digest, que e o padrao que o `db/tests_eventos/node.py`
ja usa pela mesma razao: nao ha Node no *host* Windows.

**O DOM nao e detalhe.** O `mermaid.parse` sanitiza os rotulos com o DOMPurify,
que precisa de um DOM. Sem ele falha **tudo o que nao seja `sequenceDiagram`** —
na primeira medicao, nove de doze blocos — com «DOMPurify.addHook is not a
function», um erro de ambiente que se le como erro de diagrama. Era um falso
vermelho a dizer-se verificacao. Dai o `jsdom`.

**O que nao e.** Nao e *gate*. Corre-se com `make mermaid`, e esta registado em
`docs/ci.md` §7 como lacuna: enquanto nao houver *job*, um diagrama partido
entra em `main` na mesma.
"""
