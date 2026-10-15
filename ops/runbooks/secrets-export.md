# Runbook — exportação e restauro de segredos

| Campo | Valor |
|---|---|
| Ticket | KAM-010 |
| Âmbito | **Só** exportação e restauro do conteúdo do cofre. O runbook operacional completo é o **KAM-083**; a rotação é o **KAM-072** |
| Estado | **Procedimento escrito, nunca ensaiado.** Ver §7 |
| Cofre | Doppler no Piloto; OpenBao nos Clusters (`../../docs/tecnica/08` §5) |
| Alvo de restauro | ≤ 30 min em `staging` (**proposta** do critério de aceitação do KAM-010, não medida) |

---

## 1. Porque é que isto existe antes do KAM-083

Porque o `E4` §5 marca «Doppler SaaS» como risco de dependência e a mitigação
que ele próprio nomeia é *«OpenBao ou Doppler com export»*. Um cofre SaaS sem
procedimento de saída é um ponto de falha único com um contrato por cima. Este
documento é a parte da mitigação que não depende de ter conta: **o que se exporta,
onde se guarda, e como se volta a pôr lá dentro**.

Duas coisas que este runbook **não** é:

- não é a rotação de uma chave (KAM-072);
- não é o restauro da base de dados nem do serviço (KAM-083, `pgBackRest`).

---

## 2. O que se exporta, e o que não

**Exporta-se:** o conjunto de pares `KAMBA_SECRET_<ID>` → valor de **uma**
configuração (= um ambiente). Nada mais: o inventário
(`../secrets-inventory.yaml`) já está no repositório e é esse que diz que
segredos deviam existir.

**Não se exporta:**

- `doppler_service_token` — é a credencial de arranque do próprio cofre, vive no
  anfitrião (ADR-L002 §4) e não dentro do cofre;
- segredos de `prod` para fora de um destino aprovado (§4);
- nada de `prod` para `staging` ou `dev`. As chaves por ambiente **nunca são
  reutilizáveis** (`../../docs/tecnica/08` §5); um restauro cruzado não é um atalho,
  é um incidente.

> **Os segredos não são dados pessoais** (`../../docs/tecnica/08` §5), pelo que a
> exportação não é uma transferência internacional ao abrigo do ADR-008. Isto
> vale para o **conteúdo do cofre** e para mais nada: no momento em que alguém
> puser um identificador de pessoa num segredo, deixa de valer.

---

## 3. Pré-requisitos

| # | Requisito | Como se confirma |
|---|---|---|
| 1 | Acesso ao cofre do ambiente, com MFA | entrada na consola do cofre |
| 2 | Um segundo operador presente | é uma exportação de todos os segredos de um ambiente: ninguém a faz sozinho |
| 3 | Destino de escrita preparado (§4) | existe, está cifrado e tem espaço |
| 4 | Janela anunciada, se o ambiente é `prod` | o restauro reinicia serviços (ADR-L002: as variáveis entram no arranque) |
| 5 | Inventário na versão corrente | `cd tools && python -m secrets_inventory --root .. all` → verde |

---

## 4. Onde é que o ficheiro exportado pode ficar

Esta é a parte que torna o procedimento perigoso, e por isso é a que leva regras
em vez de conselhos.

1. **Nunca** no repositório, no disco de um portátil sem cifra, num anexo de
   email, num canal de conversa, nem num *bucket* sem cifra em repouso.
2. O destino aceite é **um só**: um volume cifrado offline detido por dois
   responsáveis distintos (chave do volume com um, volume com o outro), guardado
   fisicamente separado da infra-estrutura.
3. O ficheiro é cifrado **antes** de sair da máquina que o produziu, com uma
   passphrase que não vive no cofre que se está a exportar. Um backup cifrado
   com uma chave que está dentro do que se perdeu não é um backup.
4. O ficheiro tem prazo: **30 dias** (*proposta*, a calibrar com a frequência de
   rotação do inventário — o mais curto é 90 dias). Passado o prazo, destrói-se e
   faz-se outro, porque um export antigo é um conjunto de chaves já rodadas que
   continua a abrir o que não foi rodado.
5. Toda a exportação e todo o restauro entram no `audit_log` como
   `access.secrets_export` / `access.secrets_restore`, com quem, quando, que
   ambiente e quantos segredos — nunca quais os valores
   (`../../docs/tecnica/08` §6).

---

## 5. Exportação

> Os comandos abaixo usam a CLI do Doppler. **NÃO VERIFICADO:** os nomes exactos
> dos comandos e das suas opções não foram executados neste ticket (não há conta
> nem CLI instalada). Confirmam-se em `docs.doppler.com`, referência da CLI,
> antes do primeiro ensaio. A **forma** do procedimento — um ficheiro por
> ambiente, cifrado à saída, com contagem conferida — não depende disso.

1. **Registar o início.** Hora, operadores, ambiente.

2. **Exportar a configuração do ambiente para um ficheiro, já cifrado.**

   ```sh
   # NÃO VERIFICADO: confirmar o subcomando e as opções em docs.doppler.com.
   doppler secrets download --no-file --format json \
       --project kamba --config staging \
     | gpg --symmetric --cipher-algo AES256 \
           --output "kamba-staging-$(date -u +%Y%m%dT%H%M%SZ).json.gpg"
   ```

   O `--no-file` e o *pipe* existem para que o JSON em claro **não toque o
   disco**. Se a versão da CLI não tiver um equivalente, o procedimento é
   escrever para um `tmpfs` e cifrar de lá — e não para o directório de trabalho.

3. **Conferir a contagem contra o inventário**, sem abrir os valores:

   ```sh
   gpg --decrypt kamba-staging-*.json.gpg \
     | python -c 'import json,sys; print(len(json.load(sys.stdin)))'
   ```

   O número tem de ser ≥ o número de segredos que o inventário declara com
   `staging` em `ambientes` e `instancias: nenhuma`. Mais do que isso é normal
   (instâncias por tenant); **menos é um export incompleto** e aborta o
   procedimento.

4. **Mover para o destino do §4 e apagar o original**, incluindo histórico de
   *shell* e ficheiros temporários.

5. **Fechar o registo** e abrir a entrada no `audit_log`.

---

## 6. Restauro

O relógio do critério de aceitação (≤ 30 min) conta **da decisão de restaurar até
o `make smoke` passar**.

| # | Passo | Verificação |
|---|---|---|
| 1 | Declarar o incidente e o ambiente. Confirmar, em voz alta, que o ficheiro é **do mesmo ambiente** | o nome do ficheiro e o `--config` coincidem |
| 2 | Criar o projecto e a configuração no cofre, se foi isso que se perdeu | a configuração existe e está vazia |
| 3 | Decifrar para `tmpfs` e carregar | `doppler secrets upload <ficheiro>` (**NÃO VERIFICADO**, confirmar o subcomando) |
| 4 | Conferir a contagem, como no §5.3 | igual ao export |
| 5 | Cunhar um `doppler_service_token` **novo** para o ambiente e entregá-lo ao anfitrião pelo mecanismo do ADR-L002 §4 | o token antigo é revogado; o novo não é o do ficheiro, porque o token não está no ficheiro |
| 6 | Reiniciar os consumidores | as variáveis entram no arranque (ADR-L002): sem reinício, nada muda |
| 7 | Arranque limpo | nenhum serviço aborta com `ArranqueAbortadoError`; a mensagem de um que abortasse nomeia o segredo em falta |
| 8 | Sonda | `make smoke` verde |
| 9 | Apagar a cópia decifrada; registar o fim e a duração | entrada no `audit_log` com a duração medida |

**Se o passo 7 abortar**, a mensagem diz exactamente que segredos faltam (a porta
nomeia todos de uma vez, não um por reinício). O caminho é acrescentá-los, não
arrancar o serviço sem eles.

---

## 7. O que este runbook ainda não provou

| Afirmação | Estado |
|---|---|
| Os comandos da CLI do Doppler são estes | **NÃO VERIFICADO** — sem conta e sem CLI; confirma-se em `docs.doppler.com` |
| O restauro cabe em 30 min | **NÃO MEDIDO** — é *proposta* do critério de aceitação. Não há `staging` (KAM-075), pelo que não houve ensaio nem cronómetro |
| A contagem do §5.3 detecta um export incompleto | **NÃO ENSAIADO** |
| O prazo de 30 dias do §4.4 é o certo | *proposta*; calibra-se contra a rotação mais curta do inventário (90 dias) |

**O que desbloqueia o ensaio:** o KAM-075 (ambiente de `staging`) e uma conta
Doppler. Até lá este documento é procedimento escrito e revisto, e não
procedimento ensaiado — e a diferença entre as duas coisas é a razão pela qual a
caixa do critério de aceitação fica vazia.
