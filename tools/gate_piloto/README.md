# `gate_piloto` — gerador do pacote de evidência do gate do Piloto (KAM-110)

| Campo | Valor |
|---|---|
| Ticket | KAM-110 — Gate do Piloto: decisão continuar, pivô ou parar |
| Fonte | `specs/EPIC-10_Spikes_Validacao_Gates.md` (bloco KAM-110), `docs/exploracao/14-tese-minima-e-plano-de-validacao.md` §2, §5 e §6, `specs/00_KAMBA_Carta.md` §5 |
| Saídas | [`Gate_Piloto.md`](../../docs/tecnica/evidencia/validacao/Gate_Piloto.md) (gerado); o memorando [`Gate_Piloto_Decisao.md`](../../docs/tecnica/evidencia/validacao/Gate_Piloto_Decisao.md) é escrito à mão |
| Não está ligado a portão nenhum | Por desenho: ligar um gerador a um portão é regra de bloqueio, e isso é do fundador |

> **A decisão é humana.** O bloco di-lo nos «Detalhes Técnicos»: o Claude Code
> «não escolhe nem recomenda a decisão». Este pacote aplica as regras e mostra o
> que elas dão; não escreve `CONTINUAR`, `PIVÔ` nem `PARAR` em lado nenhum.

---

## O comando

Nesta máquina não há `make`; corre-se de dentro de `tools/`:

```bash
cd tools && python -m gate_piloto pacote \
  --registo ../docs/tecnica/evidencia/validacao/Registo_Hipoteses.md \
  --resumo <resumo do piloto>.json \
  --data "<dia do gate>" \
  --saida ../docs/tecnica/evidencia/validacao/Gate_Piloto.md
```

Sem `--resumo`, sai a pré-visualização: só o Registo, os itens declaráveis da
Carta §5 todos `por verificar` e a paragem total não avaliável. É essa a versão
que está na árvore hoje, e reproduz-se com `--data "Novembro de 2026"` — sem
`--data`, o cabeçalho diz «por preencher» e o `--check` dá 1. `--check
<ficheiro>` compara em vez de escrever.

| Código | Quando |
|---|---|
| `0` | escrito, ou `--check` conforme |
| `1` | `--check`: o ficheiro já não é o que o gerador escreve |
| `2` | o Registo ou o resumo não servem, ou o SHA-256 não confere |

---

## As regras, cada uma com a fonte

| Regra | O que faz | Fonte |
|---|---|---|
| Estado efectivo | `confirmada` e `refutada` só sobrevivem com amostra n positiva, um resultado com número (e sem «NÃO MEDIDO») e uma coluna fonte que nomeie um ficheiro que exista na árvore; sem isso, `inconclusiva` | Critério A: «uma hipótese sem dados é `inconclusiva`, nunca `confirmada`»; `Registo_Hipoteses.md` §2, regras 2 e 3 |
| Amostras mínimas | H6 < 500 conversas e H9 < 8 PMEs com 60 dias dão `inconclusiva` | As duas amostras que um **critério** escreve: a Carta §5 e o KAM-109 (H6, «medido em ≥ 500 conversas reais»), e o KAM-109 (H9, «com < 8 PMEs nessa condição, H9 fica `inconclusiva`»). Os métodos de `14` §2 nomeiam tamanhos para H1, H2 e H7 que nenhum critério fixa como mínimo, e o gerador não os impõe |
| Limiar | **não se confere**: o resultado é texto no Registo, com unidades que variam por hipótese. Confere-o a verificação cruzada do memorando (§9) | «Detalhes Técnicos»: «`confirmada` só com dados que cumpram o limiar» |
| Exportação congelada | H1, H6, H8 e H9 ficam `inconclusiva` sem a exportação do KAM-109 nomeada no resumo, com *hash*. Se o ficheiro estiver na árvore, o *hash* confere-se, e um *hash* errado sai com 2; se não estiver, o pacote diz **«SHA-256 conferido: não»** e confere-se à mão | *Handoff* do KAM-109: «Não declares nenhuma hipótese confirmada sem dados exportados e congelados» |
| Matriz | cada `refutada` acciona a linha de `14` §6 que lhe cabe, palavra a palavra — o ensaio lê do `14` a coluna «Se acontecer…» ligada à «Então…»; H3 e H4 dão uma linha só; H7, H8 e H9 não têm linha e ficam «o gate decide e regista»; `canal_comercial_repetivel: false` acciona a linha da distribuição | `14` §6; critério C; KAM-106, «Se nenhum canal for repetível à semana 6: decisão escrita de resolver a distribuição» |
| Paragem total | `verificada`, `não verificada` ou `não avaliável` — e nunca «não verificada» por falta de um dado | `14` §6, última frase |
| Carta §5 | dezoito itens; P2, P3 e F3 derivam das hipóteses e não se declaram; os outros só ficam `satisfeito` com um ficheiro de evidência que exista na árvore | Carta §5; critério B |
| Pista | não entra: o resumo recusa qualquer chave fora do esquema | Critério D; *handoff* do KAM-110 |

---

## A interface com o KAM-109 e o KAM-106 (declarada aqui, por proposta)

Os ficheiros de saída do KAM-109 não estavam na `main` quando este pacote se
escreveu. A interface declara-se em vez de se adivinhar, e são **duas** peças:

### 1. O `Registo_Hipoteses.md`

É a interface que **já existe** (esquema do KAM-100, doze colunas), e é por ela
que passam todos os estados. Duas leituras da coluna `amostra n` são o que este
gerador assume, e o KAM-109 tem de as respeitar:

- **H6**: `amostra n` conta **conversas reais** medidas;
- **H9**: `amostra n` conta **PMEs com 60 dias de exposição** à data do gate, e não a coorte inteira.

O número lê-se à cabeça da célula: `512 conversas` lê 512; `cerca de 600` não lê
nada e dá `inconclusiva`.

### 2. O resumo do piloto (JSON, `forma: 1`)

Esquema **fechado**: uma chave que não esteja aqui recusa o ficheiro inteiro. Não
há campo de texto livre, e não há campo de pista. Tudo é opcional menos `forma`
e `sintetico`; o que falta sai «por medir», e nunca como conclusão positiva.

| Chave | Tipo | Quem a produz |
|---|---|---|
| `forma` | `1` | — |
| `sintetico` | booleano; `true` põe a marca «SINTÉTICO — não é evidência» no pacote | quem gera o resumo |
| `exportacao` | caminho relativo à raiz | KAM-109 (exportação final congelada) |
| `exportacao_sha256` | 64 hexadecimais minúsculos; vem sempre com `exportacao` | KAM-109 |
| `semana_do_gate` | inteiro | KAM-109 |
| `pagantes_recorrentes` | inteiro | KAM-109 |
| `canal_comercial_repetivel` | booleano: há pelo menos um canal **repetível** na definição do KAM-106 («≥ 6 PMEs-alvo em ≥ 2 rondas», *proposta*). Serve à matriz e à paragem total | KAM-106 |
| `custo_por_pme_minor`, `moeda` | inteiro em unidade menor e código ISO 4217, sempre juntos | KAM-081 (`h6-export`) |
| `carta5` | `{ "<item>": { "estado": "satisfeito" \| "nao_satisfeito", "evidencia": "<caminho>" } }`, itens P1, F1, F2, F4, F5, C1–C7, N1–N3 | o dono de cada item (§2 do pacote) |

```json
{
  "forma": 1,
  "sintetico": true,
  "exportacao": "docs/exemplo/exportacao.csv",
  "exportacao_sha256": "abababababababababababababababababababababababababababababababab",
  "semana_do_gate": 12,
  "pagantes_recorrentes": 4,
  "canal_comercial_repetivel": true,
  "custo_por_pme_minor": 5150,
  "moeda": "USD",
  "carta5": { "F1": { "estado": "satisfeito", "evidencia": "docs/tecnica/evidencia/validacao/Gate_Fase0_Decisao.md" } }
}
```

**Quando o KAM-109 fundir, os nomes conferem-se com os dele.** Se divergirem,
muda-se este esquema — que é um ficheiro, `entradas.py`, e uma tabela aqui —, e
não o dele.

---

## Ensaios

```bash
python -m unittest discover -s tools/gate_piloto/tests -t tools
```

Todas as entradas dos ensaios são **sintéticas** e marcadas como tal
(`tests/sintetico.py`). Os dois ensaios que os «Testes Requeridos» do bloco
nomeiam estão em `tests/test_regras.py`: os nove estados misturados
(`test_nove_estados_misturados_nenhum_sem_dados_sai_confirmada`, e o exaustivo
`test_toda_a_combinacao_de_dados_em_falta`) e a matriz
(`test_cada_falha_simulada_da_a_linha_que_a_fonte_lhe_da`), com o oráculo lido
do `14` e não da constante do gerador.
