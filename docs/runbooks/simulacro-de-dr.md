# Simulacro de recuperação (DR) — folha de passos, cálculo e *post-mortem*

| Campo | Valor |
|---|---|
| Ticket | KAM-085 |
| Âmbito | Como se **conduz** e se **mede** o exercício trimestral de DR. O procedimento de restauro em si é o [RB-K08](RB-K08-base-de-dados-e-restauro.md); o simulacro existe para provar que ele basta |
| Estado | **Instrumentos entregues e ensaiados localmente; o simulacro humano nunca correu.** Os números do ensaio local estão em [`../evidencia/KAM-085.md`](../evidencia/KAM-085.md) |
| Alvos | RPO ≤ 5 min, RTO ≤ 2 h (`../tecnica/00_Arquitectura_Solucao.md` §9; `../tecnica/09_Topologia_Operacao_Escala.md` §8.2) |
| Dados | **Só sintéticos.** O simulacro nunca restaura dados reais fora do destino autorizado (ADR-008) |

---

## 1. Papéis

| Papel | Quem | O que faz |
|---|---|---|
| Executor | uma pessoa de *on-call* que **não escreveu** o RB-K08 | segue **só** o RB-K08, sem perguntar a ninguém, e carimba cada passo |
| Observador | outra pessoa | regista cada desvio — cada vez que o executor hesita, pergunta, salta um passo ou faz algo que o runbook não diz. Não ajuda |
| Dono do exercício | o responsável de Plataforma/SRE | fixa a data, prepara o ambiente de ensaio, escreve o *post-mortem* |

Um simulacro conduzido por quem escreveu o runbook prova que o autor sabe restaurar, e
não que o runbook basta. É esse o critério 5 do bloco do KAM-085, e é por isso que o
ensaio local deste ticket **não** o fecha.

## 2. O relógio comum e a folha de passos

Uma folha por cenário, em JSONL, carimbada no **mesmo terminal** do princípio ao fim:

```sh
cd tools
python -m dr_simulacro carimbar --folha ../folha-A.jsonl --cenario A --passo restauro inicio
python -m dr_simulacro carimbar --folha ../folha-A.jsonl --cenario A --passo restauro fim
python -m dr_simulacro carimbar --folha ../folha-A.jsonl --cenario A --passo dns nao_medido \
    --nota "sem TTL configurado"
```

Os sete passos são os do orçamento do `../tecnica/09_Topologia_Operacao_Escala.md` §8.2:

| Passo | Rubrica do orçamento | Orçado | Começa | Acaba |
|---|---|---|---|---|
| `deteccao` | deteccao | 10 min | a falha (instante registado pelo dono do exercício) | o alerta chega a quem está de *on-call* |
| `decisao` | decisao | 10 min | o alerta | o incidente declarado e o restauro escolhido |
| `iac` | iac | 30 min | `tofu apply` do *host* novo | o *host* responde por SSH |
| `restauro` | restauro | 30 min (≤ 20 GB) | `pgbackrest restore` | o comando devolve 0 |
| `replay` | replay | 10 min | arranque do PostgreSQL | `SELECT pg_is_in_recovery()` devolve `f` |
| `verificacao` | verificacao_e_dns | 15 min, **com o DNS** | contagens, cadeia, marcadores, *smoke* | todos verdes |
| `dns` | verificacao_e_dns | (idem) | mudança do registo | resolução nova vista de fora |
| `cofre` (só C) | cofre | **0** — o §8.2 não o orça | decifrar a exportação | a passphrase entregue ao restauro |

**Um passo que não se cronometrou escreve-se `nao_medido`, com a razão — nunca com o número
do orçamento.** O cálculo soma-o ao RTO **composto** e di-lo por extenso; nunca ao **medido**.

## 3. As linhas-marcador

Um escritor a 1/s, num *host* que **não** é o da base, grava cada marcador **depois** de a
base confirmar o *commit*, com o instante que a base devolveu:

```sh
python -m dr_simulacro.marcadores --host <primario> --base kamba_platform \
    --saida confirmados.csv --erros erros.csv --parar parar
```

Depois do restauro, exporta-se o que voltou:

```sql
COPY (SELECT seq, to_char(escrito_em AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
        FROM dr_simulacro.marcador ORDER BY seq) TO STDOUT WITH CSV;
```

## 4. O cálculo

```sh
python -m dr_simulacro calcular --folha ../folha-A.jsonl --cenario A \
    --confirmados confirmados.csv --restaurados restaurados.csv --json
python -m dr_simulacro extrapolar --bytes <restaurados> --segundos <restauro> --para-gb 50 \
    --rto-composto-min <composto> --bd-prevista-gb <previsão>
```

Código de saída 1 é falha de objectivo, e **falha de objectivo é incidente P2** (critério 8):
RTO composto > 2 h, RPO > 5 min, um buraco nos marcadores, ou réplica de espera necessária.
Com o RTO composto entre 100 e 120 min, **repete-se o cenário A** (Testes Requeridos).

## 5. Os cenários

| Cenário | O que se injecta | O que conta como êxito |
|---|---|---|
| **A** — perda do *host* | o primário morre (SIGKILL) e o disco vai com ele | RTO ≤ 2 h, RPO ≤ 5 min, contagens iguais, cadeia íntegra, marcadores sem buraco |
| **B** — corrupção lógica | uma migração defeituosa (**só no ambiente de ensaio**; nunca em `db/migrations/versions/`) | PITR para antes do erro; 0 efeitos duplicados **e 0 efeitos externos órfãos** |
| **C** — cofre indisponível | sem acesso ao Doppler | o restauro corre com a exportação cifrada; o RTO adicional fica registado |
| **Ransomware** — mesa-redonda | credenciais de produção comprometidas | §6 |

O B tem uma segunda condição que o bloco não escreve e que o ensaio local mostrou necessária:
um consumidor cujo efeito sai da base (uma mensagem à Meta, um pedido ao facilitador) **não**
volta atrás com o PITR, e o evento que o causou volta. A medição está em
[`../evidencia/KAM-085.md`](../evidencia/KAM-085.md) §4.

## 6. Mesa-redonda: credenciais comprometidas / *ransomware*

Cartão para a sessão (60 min; a execução completa pode exceder 2 h, e isso é aceite):

1. **O facto injectado:** às 03:10 o `repo1` mostra um `expire` que ninguém agendou e o
   primário tem ficheiros cifrados por terceiros.
2. **Perguntas, por ordem:** quem detém a credencial de escrita do `repo1`, e onde vive?
   Com o desenho de hoje (`push`, `infra/backup/pgbackrest.conf`), produção comprometida
   apaga backups — que backups sobrevivem? Que credencial se usa no restauro, e prova-se
   que não escreve? Qual é o último backup em que se confia, e como se sabe? Quem roda o
   quê (RB-K07), e por que ordem?
3. **O que se regista:** cada pergunta sem resposta no runbook é uma lacuna aberta, com dono
   e data.

## 7. Modelo de *post-mortem* (sem culpa, em ≤ 5 dias)

```text
SIMULACRO DE DR — <data UTC> — cenário <A|B|C>
Executor: <papel, não nome>      Observador: <papel>      Dono: <papel>
Ambiente: <staging/clone>         Dados: sintéticos        BD: <GB medidos>

1. Resultado
   RTO medido: <min>   RTO composto: <min> (orçamento em: <rubricas>)
   RPO: <s> (<n> marcadores perdidos, <n> buracos)
   Dentro do objectivo: <sim/não> — se não, incidente P2 <ref>

2. Passo a passo (da folha)
   <passo> | orçado | medido | divergência | nota

3. Desvios registados pelo observador
   <n.º> | passo | o que o runbook dizia | o que foi preciso fazer | correcção ao runbook

4. Acções (cada uma com dono e data)
   <n.º> | acção | dono | data | estado

5. Decisão sobre a réplica de espera
   Regra: RTO extrapolado a 50 GB > 2 h, ou BD prevista > 40 GB.
   Extrapolado: <min>   Prevista: <GB, com a fonte>   Decisão: <...>   Dono: <...>   Data: <...>

6. Próximo simulacro trimestral: <data>
```

O *post-mortem* arquiva-se em `docs/evidencia/` com a folha e os dois CSV de marcadores.
Nenhum segredo entra nos registos do exercício: a folha leva passos e instantes, os CSV
levam números e instantes, e o modelo acima não tem campo para valores.
