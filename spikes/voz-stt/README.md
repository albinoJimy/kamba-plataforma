# `spikes/voz-stt` — preparação do spike de voz PT-AO (KAM-107)

**Descartável.** Mede o WER, a precisão numérica, a latência e o custo de dois
STT — Groq `whisper-large-v3-turbo` e OpenAI `gpt-4o-mini-transcribe` — com fala
real em português de Angola, para a decisão do STT primário. **Não é produto**: o
nó `stt` e a `SttProvider` de produção são o KAM-036.

**O que está aqui é a parte que a letra do bloco entrega ao executor.** Recrutar
falantes, obter os consentimentos, gravar, anotar e decidir são actos humanos, e
nenhum foi feito. Nenhuma chamada a um fornecedor foi feita, nenhuma chave existe
nesta árvore, e os ensaios não usam voz de ninguém: o áudio deles é um tom puro
gerado em memória.

| Ficheiro | O que é |
|---|---|
| `protocolo_gravacao.md` | O protocolo de gravação, anotação, envio e apagamento, passo a passo, com o dono de cada passo |
| `consentimento.md` | O texto do consentimento escrito de cada falante. A forma jurídica é **NÃO VERIFICADO** e depende da X1 |
| `roteiro.tsv` | **220** enunciados PT-AO, com as marcas de números e de línguas nacionais |
| `roteiro.py` | As 10 folhas por falante, estratificadas, com 6 em 22 para gravar em ruído |
| `manifesto.py` | O esquema do manifesto do corpus e o verificador das quotas do critério 1 |
| `transcodificar.sh` | ffmpeg: gravação → Opus/OGG mono; clips de 5, 15 e 30 s para a latência; duração |
| `normalizar.py` | O normalizador do WER, regras versionadas (versão 1) |
| `wer.py` | WER micro e precisão numérica |
| `porta.py` | A porta `SttProvider` do spike |
| `fornecedores.py` | Os dois adaptadores HTTP, que só se constroem depois da autorização |
| `autorizacao.py` | A porta fechada antes de qualquer envio: consentimentos, X1, retenção e não-treino |
| `falso.py` | O duplo determinístico da porta, para os ensaios |
| `harness.py` | Chama um STT por clip e escreve uma linha JSON por execução |
| `latencia.py` | p50 e p95 por tamanho, momentos do dia, taxa de erro ou *timeout* |
| `custo.py`, `precos.json` | USD por hora de áudio e por PME/mês, com o mínimo facturado |
| `limiares.json` | Os limiares pré-registados, com data |
| `relatorio.py` | As tabelas do `H7_Voz_STT.md`, com as guardas de privacidade e de data |
| `apagamento.py` | Verifica o prazo de 24 h e apaga o áudio do manifesto |
| `tests/` | **91** ensaios (1 salta sem `ffmpeg` no caminho). **Nenhum portão os corre** |

O relatório vive em
[`docs/tecnica/evidencia/validacao/H7_Voz_STT.md`](../../docs/tecnica/evidencia/validacao/H7_Voz_STT.md).

---

## Correr os ensaios

Python da biblioteca padrão, sem dependências:

```bash
python -m unittest discover -s spikes/voz-stt/tests -t spikes/voz-stt
```

O `tests/__init__.py` põe a pasta do spike no caminho, para não depender do
`PYTHONPATH`. O ensaio do `transcodificar.sh` salta sem `ffmpeg`, `ffprobe` e
`sh` no caminho; nesta máquina corre-se dentro do contentor (ver o cabeçalho do
script) e a medição está no bloco do ticket.

## A sequência do operador

Cada passo tem o seu dono no `protocolo_gravacao.md`. Os comandos:

```bash
python spikes/voz-stt/roteiro.py folha 1                       # imprimir a folha do falante 1
S=$PWD/spikes/voz-stt; cd /fora/audio                          # o áudio nunca na árvore
sh $S/transcodificar.sh opus gravacao.wav F01/C0001.ogg        # recusa (código 3) dentro de um repositório
sh $S/transcodificar.sh duracao F01/C0001.ogg                  # para a coluna duracao_s
sh $S/transcodificar.sh juntar F01/C9001.ogg 15 F01/C0001.ogg F01/C0002.ogg F01/C0003.ogg
cd -
python spikes/voz-stt/manifesto.py /fora/manifesto.csv         # 0 achados antes de enviar

export KAMBA_VOZ_CHAVE_GROQ='<do cofre>'
python spikes/voz-stt/harness.py correr --manifesto /fora/manifesto.csv --audio /fora/audio \
    --destino /fora/resultados.jsonl --fornecedor groq --autorizacao /fora/autorizacao.json
python spikes/voz-stt/harness.py correr ... --tipo latencia --repeticoes 10   # manhã, tarde e noite

python spikes/voz-stt/apagamento.py verificar --manifesto /fora/manifesto.csv --audio /fora/audio /fora/resultados.jsonl
python spikes/voz-stt/relatorio.py --manifesto /fora/manifesto.csv /fora/resultados.jsonl
python spikes/voz-stt/apagamento.py apagar --manifesto /fora/manifesto.csv --audio /fora/audio --confirmo
```

`/fora` é qualquer pasta **fora de um repositório git**. Recusam caminhos com um
`.git` acima — deste repositório, do *checkout* principal, de um *worktree* irmão
ou de outro qualquer —: o `transcodificar.sh` para a saída; o *harness* para a
pasta do áudio, o destino, o manifesto e a autorização; o apagamento para a pasta
e o manifesto; e o relatório para o manifesto e os resultados. O *harness* recusa
também, antes do primeiro envio, um `ficheiro` do manifesto que não esteja em
`<audio>/<falante_id>/`.

---

## As propriedades que isto tem de ter certas

### 1. Nenhum áudio sai sem as três coisas que o critério 2 pede

O `fornecedores.construir` chama a `Autorizacao.exigir` **antes** de ler a chave,
e a autorização falha fechada: sem consentimento datado de **cada** falante do
manifesto **para aquele fornecedor** (o papel tem uma caixa por envio), sem a X1
respondida ou o risco aceite por escrito **com `permite_envio: true`** — um parecer
que responda «exige autorização do Art. 34.º» também é uma resposta, e não abre a
porta —, e sem retenção zero e não-treino verificados para **aquele** fornecedor,
não há STT real para construir. A recusa diz tudo o que falta de uma vez.
`tests/test_harness.py::TestAutorizacao::test_cada_condicao_morde` estraga
**dezassete** condições, uma de cada vez. O adaptador **não segue
redireccionamentos**: o `urllib` refazia o POST noutro *host* com o cabeçalho
`Authorization`. **O ficheiro de autorização escreve-o uma pessoa** e
vive fora do repositório; nenhuma sessão o deve escrever.

### 2. O áudio, as transcrições e os falantes ficam fora do repositório

O *harness* recusa uma pasta de áudio ou um destino dentro da árvore; a linha de
resultado não leva o `falante_id` nem o caminho do ficheiro; o manifesto só aceita
pseudónimos `F00`. O relatório recusa sair com um pseudónimo, um `clip_id`, um nome
de ficheiro de áudio, uma sequência de nove ou mais algarismos ou um bloco com
forma de base64 — e nunca escreve hipóteses nem referências, só contagens.

### 3. Os limiares estão datados antes da primeira medição

O `relatorio.py` recusa gerar se o `registado_em` do `limiares.json` não for um
dia **anterior** ao da primeira execução registada. O limiar de confiança, que o
bloco não fixa, tem data própria e está `null`: quem o fixar fá-lo antes de medir.
A prova forte é o histórico do `git` deste ficheiro.

### 4. O WER de números escritos e ditos compara-se

«mil e quinhentos kwanzas» e «1.500 Kz» dão o mesmo — `1500 kz` — pela regra 6 do
`normalizar.py`; «um», «uma» e «cento» sozinhos ficam palavras, para que o artigo
e o «por cento» não entrem na precisão numérica. As limitações da versão 1 estão
fixadas em `tests/test_normalizar.py::TestLimitacoes` e no `H7_Voz_STT.md` §2 —
entre elas «catorze e trinta» contra «14h30», «nove e meia» contra «9h30»,
milhares com espaço, «1 saco» contra «um saco», e grafias PT-BR.

---

## O que está NÃO VERIFICADO, e onde se resolve

| Item | Estado | Onde se resolve |
|---|---|---|
| *Endpoints*, campos e forma das respostas dos dois fornecedores (`fornecedores.py`) | NÃO VERIFICADO | Releitura da documentação com data, antes da primeira chamada |
| Os campos de confiança (`avg_logprob`, `logprobs`) | NÃO VERIFICADO | A primeira chamada real; sem eles, `confianca = None` é a resposta «N» |
| Parâmetros das notas de voz do WhatsApp (16 kHz, ~24 kbit/s) | NÃO VERIFICADO | `ffprobe` sobre uma nota de voz da própria equipa, só metadados |
| Origem Kimbundu/Umbundu das palavras marcadas no roteiro | NÃO VERIFICADO | Um anotador falante, antes de gravar (`protocolo_gravacao.md` §3) |
| Preços (`precos.json`) | Os de E4 a 2026-10-08 | Releitura nas páginas dos fornecedores, com data (critério 6) |
| Mínimo facturado da OpenAI | NÃO VERIFICADO | A mesma releitura |
| Forma jurídica do consentimento | NÃO VERIFICADO | A X1 do KAM-104 |

Uma nota de leitura do `ffprobe`: um ficheiro Opus reporta **48000 Hz** de taxa
de amostragem em qualquer caso, porque o descodificador Opus trabalha sempre a
48 kHz; a taxa de entrada (16 kHz) é a que o cabeçalho guarda.
