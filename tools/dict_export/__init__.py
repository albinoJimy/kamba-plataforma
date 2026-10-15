"""dict_export — exporta o §3 do dicionario canonico para `canon/dicionario.yaml` (KAM-111).

A fonte da verdade e o Markdown: `specs/02_Dicionario_de_Dados_Canonico.md`. O
YAML e um **artefacto gerado**, versionado para que o `canon_lint` (gate 3b)
corra sem voltar a interpretar prosa, e para que uma alteracao ao dicionario
apareca no *diff* como aquilo que e: nomes que entram, nomes que saem.

    python -m dict_export            escreve canon/dicionario.yaml
    python -m dict_export --check    falha se o ficheiro divergir do Markdown

## O que se exporta, e o que nao se consegue exportar

As tabelas do §3 sao prosa com nomes entre crases. A exportacao e mecanica e
tem regras escritas (em `exportar.py`); nao ha julgamento caso a caso:

* **uma entrada por linha** de cada tabela do §3;
* os nomes canonicos sao os que estao entre crases nas colunas «Conceito» e
  «Nome»; os da coluna «Nota» ficam a parte (`nomes_nota`) e nunca salvam uma
  variante;
* uma **variante** e um nome entre crases na coluna «Substitui» que nao e
  canonico em sitio nenhum do §3. Um nome que esta nas duas colunas e uma
  contradicao do dicionario, e sai em `contradicoes` em vez de ser escolhido em
  silencio.

O que fica de fora, por nao ser um nome: expressoes (`p.stock>0`,
`msisdn_hash+tenant`), referencias a documentos, e tudo o que a coluna
«Substitui» diz sem crases («replay ±5 min», «persona»).
"""

__all__ = ["exportar", "markdown"]
