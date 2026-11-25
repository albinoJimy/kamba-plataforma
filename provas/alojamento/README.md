# `provas/alojamento/` — o que o *host* real tem de provar (KAM-077)

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Índice de provas do alojamento: o que cada critério do KAM-077 exige, o comando que o mede e onde a prova fica |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-077 (EPIC-08), preparação sem o mundo real |
| Documento-fonte | `../../specs/EPIC-08_Topologia_Operacao.md` (bloco KAM-077); `../../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` requisito 25; ADR-008, D1, D12 |

> **Esta pasta não guarda os documentos, e é de propósito.** O critério 1 do
> KAM-077 manda arquivar «em `provas/alojamento/`» o contrato, o SLA, a
> jurisdição do centro de dados e o 2.º local de *backups*, e o requisito 25 do
> E3 chama-lhe «pasta de provas». Mas o conjunto já fixou onde essa pasta vive:
> **no repositório de provas, privado — nunca este repositório**
> (`../../docs/runbooks/RB-K10-incidente-de-seguranca.md` passo 5;
> `../../docs/seguranca/contactos_incidentes.md`). Este repositório é público.
> O que fica **aqui** é o índice: que prova, de que critério, produzida por que
> comando, e o `sha256` e a data do ficheiro que está no repositório privado —
> para que a prova se possa citar e conferir sem ser publicada.

**Estado: nenhuma prova recolhida.** Não há *host*: a D1 está em aberto
(`../../docs/tecnica/evidencia/validacao/GoLive_Gate.md`, linha A1) e o KAM-105
não tem nenhuma cotação. Todas as linhas da §2 estão **por provar**.

---

## 1. Como se acrescenta uma prova

1. O ficheiro vai para o repositório de provas, na pasta `alojamento/`, com o
   nome da coluna «Ficheiro» da §2.
2. Calcula-se `sha256sum <ficheiro>` **lá**, depois de o ficheiro estar final.
3. Aqui preenchem-se as colunas «sha256», «Data (UTC)» e «Estado» dessa linha.
   O estado passa de **por provar** a **provado** só com as duas anteriores
   preenchidas; uma linha com estado e sem `sha256` é uma afirmação sem prova.
4. A caixa correspondente do bloco do KAM-077 marca-se com a evidência nomeada
   a apontar para esta linha — nunca antes.

**O que nunca entra aqui, nem nos nomes de ficheiro:** preços, números de
contrato, nomes e contactos de pessoas, o endereço IP do *host* de produção e
chaves de qualquer espécie. O relatório de RTT que a `borda` gera já sai sem o
endereço (só a etiqueta do alvo), e é o único artefacto desta lista pensado
para ser publicado inteiro — em `../../docs/tecnica/evidencia/`, como o
critério 5 pede.

---

## 2. As provas, por critério do KAM-077

| # | Critério | Prova | Comando ou origem | Ficheiro (no repositório privado) | sha256 | Data (UTC) | Estado |
|---|---|---|---|---|---|---|---|
| 1.1 | 1 | Contrato com o fornecedor decidido em D1 | Assinatura (acto humano) | `alojamento/contrato.pdf` | | | por provar |
| 1.2 | 1 | SLA do fornecedor | Anexo do contrato | `alojamento/sla.pdf` | | | por provar |
| 1.3 | 1 | Jurisdição do centro de dados | Declaração escrita do fornecedor | `alojamento/jurisdicao-dc.pdf` | | | por provar |
| 1.4 | 1 | 2.º local para *backups* (com o KAM-079) | Contrato ou declaração do 2.º local | `alojamento/segundo-local.pdf` | | | por provar |
| 2.1 | 2 | O GET de verificação devolve o *challenge* por HTTPS | `curl -sS "https://<dominio>/webhooks/whatsapp?hub.mode=subscribe&hub.challenge=<aleatorio>&hub.verify_token=<do cofre>"` a partir do exterior, com a saída a ser igual ao *challenge* | `alojamento/webhook-get.txt` | | | por provar |
| 2.2 | 2 | A cadeia valida e o TLS é ≥ 1.2 | `openssl s_client -connect <dominio>:443 -servername <dominio> -verify_return_error </dev/null` (código 0) **e** `openssl s_client ... -tls1_1` a falhar | `alojamento/tls-cadeia.txt` | | | por provar |
| 2.3 | 2 | Renovação automática testada | Em *staging*, um certificado de validade encurtada renovado sem intervenção; registo antes e depois (`notAfter`) | `alojamento/tls-renovacao.txt` | | | por provar |
| 3.1 | 3 | D12 registada com dono e data | [`../../docs/tecnica/evidencia/validacao/D12_CDN_WAF.md`](../../docs/tecnica/evidencia/validacao/D12_CDN_WAF.md) §3, com as duas células preenchidas | (público) | — | | por provar |
| 4.1 | 4 | *Scan* externo: só 443/tcp e a porta UDP do WireGuard | `nmap -Pn -sS -p- <host>` e `nmap -Pn -sU -p 1-1024,51820 <host>` a partir de uma rede fora do fornecedor | `alojamento/scan-externo.txt` | | | por provar |
| 4.2 | 4 | SSH por chave só via VPN | `ssh -o PasswordAuthentication=no admin@<host>` de fora (falha por *timeout*) e pelo túnel (entra) | `alojamento/ssh-so-por-vpn.txt` | | | por provar |
| 4.3 | 4 | MFA no painel do fornecedor | Captura da configuração da conta, sem dados pessoais | `alojamento/mfa-painel.png` | | | por provar |
| 4.4 | 4 | Acesso *break-glass* auditado | Um acesso de ensaio e a sua linha no registo (KAM-080) | `alojamento/break-glass.txt` | | | por provar |
| 5.1 | 5 | RTT sonda em Luanda → *host*, p50/p95 em 24 h | `python -m borda rtt-medir --origem luanda-1 --alvo host=<host>:443 --saida sonda.jsonl` na sonda | `alojamento/rtt-sonda.jsonl` | | | por provar |
| 5.2 | 5 | RTT *host* → `graph.facebook.com` | `python -m borda rtt-medir --origem host-prod --alvo graph=graph.facebook.com:443 --saida host.jsonl` no *host* | `alojamento/rtt-host.jsonl` | | | por provar |
| 5.3 | 5 | A tabela, com números medidos | `python -m borda rtt-relatorio sonda.jsonl host.jsonl --saida <tabela>` e depois `python -m borda rtt-verificar <tabela> sonda.jsonl host.jsonl` (código 0) | (público, em `../../docs/tecnica/evidencia/`) | — | | por provar |
| 6.1 | 6 | `prod` continua `kamba_data_class=synthetic` | `infra/envs/prod/env.yaml` e as etiquetas do recurso no painel do fornecedor | `alojamento/etiquetas-prod.txt` | | | por provar |
| 6.2 | 6 | Gate de go-live com estado e data da última verificação | [`../../docs/tecnica/evidencia/validacao/GoLive_Gate.md`](../../docs/tecnica/evidencia/validacao/GoLive_Gate.md) | (público) | — | | por provar |

**O que as linhas 2.2, 4.1 e 5.x já não precisam de inventar** quando o *host*
existir: as regras `nftables` que o *scan* 4.1 vai medir estão escritas e
verificadas (`../../infra/modules/host-base/cloud-init.yaml.tftpl`;
`python -m borda firewall`), e a sonda e o relatório da 5.x estão escritos e
testados (`../../tools/borda/`). Nenhum dos dois correu contra um *host*.

---

## 3. O que este índice não prova

- **Que as regras do *host* fecham o que dizem.** Foram aceites pelo `nft -c`
  num contentor e carregadas duas vezes sem apagar uma tabela alheia, o que
  prova a sintaxe e a recarga; o que fica aberto de fora só o *scan* 4.1 mede.
- **Que o RTT medido por *handshake* TCP é o que a Meta vê.** É o caminho do
  HTTPS, mas é uma ida e volta da sonda escolhida, num dia; o doc 09 §5.2 fica
  substituído para esse percurso e essa data, e não para todos.
- **Que o comando 2.1 serve tal como está.** O caminho exacto do *webhook* e o
  nome do segredo do `verify_token` vêm do GWY no dia da medição; aqui estão
  como forma, não como contrato.

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, preparação do KAM-077 sem a D1. Dezassete provas em seis critérios, todas **por provar**, cada uma com o comando que a produz e o ficheiro que a guarda no repositório de provas **privado** — que é onde o conjunto já fixou que as provas vivem; aqui fica só o índice, com `sha256` e data. | Coordenação do lote 24 |
