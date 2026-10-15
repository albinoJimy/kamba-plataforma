# Ferramentas

| Ferramenta | O que faz | Dependências |
|---|---|---|
| [`lint_arch/`](lint_arch/) | Lista de bloqueio, convenções de commit e de ramo, estrutura da árvore | **Apenas biblioteca padrão do Python** |
| [`pip_lock.py`](pip_lock.py) | Gera `requirements/*.txt` com `--hash=sha256:` a partir dos `.in`, e verifica que o fecho está completo | Apenas biblioteca padrão |
| [`healthz_check.py`](healthz_check.py) | Sonda `/healthz` de cada serviço e valida contra o contrato | `jsonschema` (de `requirements/tools.txt`) |
| [`supply_chain/`](supply_chain/) | Imagens por *digest*, instalação só do *lockfile*, lista de saídas por serviço, registo de licenças por versão, quarentena do Renovate — e o canário que prova que cada uma morde (KAM-067; [`docs/supply-chain.md`](../docs/supply-chain.md)) | Apenas biblioteca padrão |
| [`blocklist.yaml`](blocklist.yaml) | A lista de bloqueio, com ADR e evidência por entrada | — |
| [`conventions.json`](conventions.json) | As convenções do §5 do Engineering Standards, numa só definição | — |
| [`githooks/`](githooks/) | `commit-msg` e `pre-push` | Apenas Python |

## Porque é que o `lint_arch` não usa bibliotecas

A verificação da lista de bloqueio tem de poder correr **antes** de qualquer
`pnpm install` ou `pip install`. Um linter que precisasse de dependências
instaladas para dizer que uma dependência é proibida chegaria sempre tarde para o
caso que interessa: o pacote malicioso que corre no `postinstall`
(`docs/tecnica/08` §4.8; E4 §2.7). Por isso `make bootstrap` corre `make lint-arch`
como primeiro passo.

O custo é [`lint_arch/yamlmini.py`](lint_arch/yamlmini.py): um leitor de um
subconjunto estrito de YAML, que recusa em voz alta tudo o que não seja a forma
exacta do ficheiro de bloqueio. Está justificado em
[`docs/adr/ADR-L001-toolchain.md`](../docs/adr/ADR-L001-toolchain.md) §6.

## Correr à mão

```bash
python -m lint_arch all                 # lista de bloqueio + estrutura
python -m lint_arch deps                # só a lista de bloqueio
python -m lint_arch branch              # nome do ramo actual
python -m lint_arch commit-msg FICHEIRO # uma mensagem de commit

python tools/pip_lock.py --check services/agr/requirements/runtime.in
python tools/healthz_check.py gwy=3000 agr=8000
```

Precisa de `tools/` no `PYTHONPATH` (o `Makefile` põe-no lá; os hooks também).

Códigos de saída: `0` conforme, `1` achados, `2` erro de configuração. A
distinção importa — um ficheiro de bloqueio malformado não pode parecer um
repositório limpo.

## Testes

```bash
make test-py
```

44 casos, dos quais as nove *fixtures* que o KAM-001 exige: sete de bloqueio (uma
por entrada da lista) e duas de passagem. As de passagem valem tanto como as
outras — um linter que bloqueia tudo satisfaz as sete primeiras e não serve para
nada.
