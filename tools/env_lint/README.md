# `env_lint` — a matriz de ambientes bate com a configuração (KAM-075)

```bash
cd tools && python -m env_lint --root .. lint      # 0 limpo, 1 achados, 2 ilegível
cd tools && python -m env_lint --root .. canario   # prova que o lint morde
```

Corre no **gate 2** (`make env-lint`, chamado por `make ci-2`), ao lado do
`lint-arch`, do `log-lint` e do `money-lint`. Entra num gate que já existe e não
abre *job* novo, porque um *job* novo acrescenta um contexto exigido ao *ruleset*
de `main` — alteração de regra de bloqueio, que é decisão do fundador.

## 1. O que verifica, critério a critério

| Critério do KAM-075 | O que a máquina faz | Achados |
|---|---|---|
| 1 — a matriz é verificada contra a configuração real | Lê as 7 linhas da §2 e as 5 da §7 de `infra/ENVIRONMENTS.md` e compara cada token com `infra/envs/*/env.yaml` | `matriz-divergente`, `matriz-linha-em-falta`, `matriz-linha-a-mais`, `configuracao-sem-a-chave` |
| 3 — restaurar um *backup* de `prod` em `staging` falha por controlo | Nenhum ambiente além de `prod` pode ter `prod` em `dados.restauro_de` | `restauro-de-prod`, `restauro-desconhecido`, `restauro-mal-formado` |
| 4 — `real` exige decisão D1 e `apd_ref` | `dados.classe: real` sem `decisao_d1` ou sem `apd_refs` falha; as duas formas são validadas | `real-sem-d1`, `real-sem-apd-ref`, `d1-mal-formada`, `d1-sem-classe-real`, `apd-ref-mal-formada`, `classe-desconhecida`, `etiqueta-de-classe-divergente` |
| 5 — mapeamento ambiente → projecto, e um segredo de `prod` em `staging` falha | Os três projectos são distintos; uma referência `<projecto>/<ID>` dentro de `infra/envs/<e>/` tem de ser do projecto de `<e>` | `projecto-repetido`, `projecto-local-fora-de-dev`, `projecto-em-falta`, `chave-partilhada-entre-ambientes`, `segredo-de-outro-ambiente`, `segredo-fora-de-um-ambiente`, `segredo-fora-do-inventario`, `segredo-nao-existe-no-ambiente` |
| 6 — 0 recursos proprietários sem equivalente | Nenhum `.tf` fora de `infra/modules/provider-*/` declara `resource`, `data` ou `provider` | `recurso-fora-da-costura` |
| (Detalhes Técnicos) DNS com TTL baixo | `dns.ttl_segundos` presente e ≤ 300 (***proposta***, não medição) | `ttl-ausente`, `ttl-acima-do-proposto` |
| (transversal) Esquema e estrutura | Os três `env.yaml` existem, declaram o ambiente da sua pasta, e não têm chaves que o leitor não conheça. E **só existem três pastas** em `infra/envs/`: uma quarta era invisível a quatro das cinco verificações | `ambiente-em-falta`, `ambiente-mal-declarado`, `ambiente-desconhecido`, `chave-desconhecida`, `dados-ausente`, `segredo-nomeado-ausente-do-inventario`, `versao-desconhecida` |
| (transversal) Coerência interna — as folhas que a matriz **não** compara | O `env.yaml` tem 24 folhas e a matriz compara 12. As outras nove ficam amarradas a uma que a matriz vê: a `forma` deriva de `vcpu`+`memoria_gb`, o `proxypay_base` do `facilitador.modo`, o `budget` do `llm.modo`, o `cofre` do `segredos.projecto` | `forma-divergente-do-compute`, `compute-local-com-host`, `disco-sem-nvme`, `meta-sem-assinatura`, `facilitador-fora-da-sandbox`, `facilitador-com-endpoint-a-mais`, `facilitador-modo-desconhecido`, `appypay-com-estado-errado`, `budget-divergente-do-modo`, `llm-modo-desconhecido`, `cofre-divergente-do-projecto` |
| (transversal) Formas nativas do OpenTofu | O `.tf.json` conta como o `.tf` — é a segunda forma que o OpenTofu carrega —, e um `.tf.json` que não se interpreta também não passa | `configuracao-nativa-ilegivel` (e `recurso-fora-da-costura` na forma JSON) |

**São 44 códigos, e todos estão nesta tabela** — não por disciplina, mas porque
`tests/test_cobertura_dos_achados.py` falha quando um não está.

### As quatro linhas transversais nasceram de uma revisão adversarial

Vale dizer de onde vêm, porque a lição é sobre **onde** estava o defeito. As
nove regras originais eram sólidas e o canário provava que mordiam; o que não
estava provado era que **a camada de leitura entregasse às regras tudo o que
conta**. Quatro decisões de recolha tinham furos, e o canário — que muta um
`Dados` já carregado — não podia tocar em nenhuma:

| Furo | Medido assim | Fechado por |
|---|---|---|
| O filtro `.tf` da regra de portabilidade | um `resource` de fornecedor num `infra/envs/prod/fornecedor.tf.json` dava **zero achados**, com `tofu validate` a confirmar que o ficheiro é configuração | `EXTENSOES_DE_CONFIGURACAO_NATIVA` |
| A lista de extensões varridas | `prod/META_APP_SECRET` num `infra/envs/staging/terraform.tfvars` (auto-carregado pelo OpenTofu) dava **zero achados** | `.tfvars` em `EXTENSOES_DE_CONFIGURACAO` |
| As 12 chaves comparadas com a matriz | `vcpu: 64` em `staging` dava zero achados, e o `tofu plan` imprimia `forma = "64vcpu-256gb"` com a matriz a dizer `4vcpu-16gb`. Pior: o `proxypay_base` trocado pelo *host* de **produção** passava | `_regra_coerencia_interna` |
| A lista fixa de três ambientes | `infra/envs/staging-dr/env.yaml` com `dados.classe: real` e `restauro_de: [prod]` dava zero achados e imprimia «3 ambientes» | `_regra_pastas_de_ambiente` |

As quatro mutações são hoje casos de canário, com as palavras da revisão. Um
escape vira portão.

**O critério 2 não está aqui**, e isso é a coisa mais importante desta página:
«um *host* novo em ≤ 30 min, mediana de 3 execuções» não se verifica a ler
ficheiros, e **não foi medido** — ver `infra/README.md` §5.

## 2. A derivação, que é o que faz o critério 5 ser verificável

Uma referência de segredo tem a forma `<projecto_de_segredos>/<ID_EM_MAIÚSCULAS>`.

- O **projecto** vem de `segredos.projecto` do `env.yaml` do ambiente.
- O **`ID`** é um `id` do inventário do KAM-010 (`ops/secrets-inventory.yaml`),
  em maiúsculas.

Nada disto se escreve duas vezes. A consequência é que «chaves Meta e do
facilitador **distintas** por ambiente» (doc 09 §6) passa a ser **consequência**
de três projectos distintos, e não disciplina de quem escreve. O lint não
confia nessa consequência: calcula as três referências de `meta_app_secret` e
de `proxypay_api_key` e exige que sejam diferentes duas a duas.

## 3. O que este verificador NÃO cobre

Dizer isto faz parte do resultado. Um número sozinho não é uma medição.

- **Não fala com o cofre nem com fornecedor nenhum.** Que o projecto Doppler
  `staging` exista é **NÃO VERIFICADO** — não há conta (`docs/evidencia/KAM-010.md`).
  Verifica-se o **mapeamento**, que é o que o critério 5 pede deste ticket.
- **Não valida que um `apd_ref` existe na APD.** Valida a forma. São **0 de 14**
  os destinos com protocolo (`GoLive_Gate.md` linha B2).
- **Nem que a D1 foi decidida.** Pela mesma razão, e dita com as mesmas
  palavras porque a omissão enganava: um `decisao_d1: "D1/2026-11-02/inventada"`
  passa. O que o gate recusa é a **ausência** de duas cadeias bem formadas, e
  isso vale contra a distracção — uma linha mudada sem ninguém ver, que é o modo
  de falha real — e não contra quem queira contorná-la. O que impede a entrada
  de dados reais é o `GoLive_Gate.md`, que é um acto humano com assinatura.
- **Não compara `infra/ENVIRONMENTS.md` com o doc 09 §6.** O critério 1 pede a
  matriz «com as 7 linhas do doc 09 §6» **e** um teste que a compare com a
  configuração; o segundo está feito, o primeiro é conferência humana. Se um
  valor da matriz se afastar do documento-fonte e o `env.yaml` for mudado a par,
  o gate fica verde. Não se automatizou porque as células do doc 09 §6 são prosa
  com estados (`CONFIRMADO`, `INDÍCIO`) e não tokens — fazer o lint lê-las era
  construir um segundo analisador de prosa sobre um documento que muda por
  outras razões. As sete linhas foram conferidas à mão, e a revisão adversarial
  conferiu-as outra vez.
- **Não lê `services/`, `libs/`, `packages/` nem `ops/`.** O varrimento é sobre
  `infra/`. O uso de segredos em código tem o seu verificador, que é o
  `secrets_inventory` do KAM-010 (eixo `uso`).
- **Não valida HCL.** Isso é `tofu validate`, e corre-se à mão (ver
  `infra/README.md` §7) — não está em gate nenhum, porque meter o OpenTofu no CI
  era acrescentar uma ferramenta a um *job* para verificar ficheiros que ainda
  não criam nada.
- **Não lê a §3 de `infra/ENVIRONMENTS.md`**, que é a linha deliberadamente
  fora do conjunto verificado (Factura AGT, ligada à D7).

## 4. O canário é por mutação, e não por *fixtures*

O `log_policy` e o `money_lint` provam que mordem com *fixtures* — um ficheiro
por regra. Aqui não funcionaria, e a razão está por extenso em
[`canario.py`](canario.py): as regras são sobre **relações entre três ambientes
e uma tabela**, pelo que uma *fixture* por regra é uma cópia da árvore inteira,
e dezenove cópias divergem da árvore real sem que nada avise.

Por mutação parte-se da árvore **real**, muda-se uma coisa, e exige-se o achado.
Cada caso declara a sua **precondição**: se o campo já não estiver no estado de
que o caso parte, o caso **falha** em vez de passar — que é o que fecha o modo
de falha desta forma (uma mutação que não muda nada passaria sempre).

### A linha de saída diz o que mediu, e isso levou duas correcções

Hoje imprime:

```
env_lint canario: 25 de 25 casos a morder (23 achados distintos), a exercitar 11 de 11 regras
```

Os três números são medidos, e nenhum deles era antes. A primeira versão dizia
«19 de 19 casos a morder, **sobre 9 regras**», onde o 9 era `len(REGRAS)` — não
uma medição — e **uma das nove não tinha caso nenhum**. O segundo número passou
a sair de correr cada regra isoladamente por cada caso, e há um teste
(`test_cada_regra_e_exercitada_por_um_caso`) que exige que seja igual ao total.

A segunda correcção foi contar **casos** e não códigos distintos: dois códigos
têm dois casos cada de propósito (o `.tf` e o `.tf.json`; o `.tf` e o
`.tfvars`), e um contador de códigos imprimia «23 de 25» com zero falhas — um
número que parece dizer «dois casos falharam» quando nenhum falhou.

### Cobertura: o canário não chega, e o que o completa

O canário tem **25** casos e o lint produz **44** códigos. A divisão é esta:

- **canário** — as regras que os critérios de aceitação nomeiam, provadas
  contra a árvore **real**, que é a que o gate verifica;
- **testes unitários** — as regras de esquema e de estrutura, provadas contra um
  `Dados` construído à mão, porque mutá-las na árvore real exigia uma árvore
  inválida.

O que fecha o buraco não é a divisão escrita: é
`tests/test_cobertura_dos_achados.py`, que lê os códigos da fonte do `lint.py` e
**falha** quando um deles não tem prova no canário nem num teste — e também
quando um deles não está na tabela da §1. Um achado sem prova de que morde é um
achado que pode nascer morto.

## 5. Domínios partilhados

`AMBIENTES = ("dev", "staging", "prod")` vive aqui **e** em
`tools/secrets_inventory/inventario.py`, porque os dois módulos correm sozinhos.
O que impede os dois de divergirem é um teste
(`tests/test_arvore_real.py::TestDominiosPartilhados`): um quarto ambiente entra
nos dois sítios ou em nenhum.

O inventário de segredos lê-se pelo **leitor do KAM-010** e não por um nosso: o
`ops/secrets-inventory.yaml` usa listas em estilo de fluxo, que o `kamba_yaml`
recusa de propósito (corre no `pre-commit`, e ali um *parser* mais permissivo é
risco que não compensa). Reutilizar o leitor de quem é dono do ficheiro poupa um
terceiro subconjunto de YAML neste repositório — e poupa a divergência entre dois.
