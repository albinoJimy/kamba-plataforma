# Checklist de portabilidade

| Campo | Valor |
|---|---|
| Documento | Infraestrutura — checklist de portabilidade |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-075 (EPIC-08), critério 6 |
| Documento-fonte | `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (requisito 24), `../docs/tecnica/09_Topologia_Operacao_Escala.md` §5.3 |
| Relacionados | [`ENVIRONMENTS.md`](ENVIRONMENTS.md), [`modules/README.md`](modules/README.md), [`../docs/adr/ADR-L007-ferramenta-de-iac.md`](../docs/adr/ADR-L007-ferramenta-de-iac.md) |

> **O critério 6 pede «0 recursos geridos proprietários sem equivalente
> documentado».** O número é **0**, e esta página existe para dizer o que esse
> zero vale e o que não vale — porque um zero obtido por não haver nada é
> diferente de um zero obtido por haver equivalentes.

---

## 1. Como se lê este zero, e porque é honesto dizê-lo

Há duas razões para o zero, e só uma é mérito:

| | |
|---|---|
| **A razão fraca** | Não há fornecedor escolhido (**D1**), logo não há nenhum recurso gerido de fornecedor nenhum. Contar zero aqui é contar um conjunto vazio, e um conjunto vazio satisfaz qualquer afirmação |
| **A razão forte** | Há uma **regra verificada por máquina** que mantém o zero quando o conjunto deixar de ser vazio: nenhum `.tf` fora de `infra/modules/provider-*/` pode declarar `resource`, `data` ou `provider`, e o `tools/env_lint` falha com `recurso-fora-da-costura` |

A segunda é a que vale, e é a diferença entre esta *checklist* e uma intenção.
Mas nenhuma das duas é uma medição de portabilidade **demonstrada**: ver §4.

---

## 2. As classes de recurso que o desenho precisa

Uma linha por classe. A coluna «forma portátil» é o que a costura promete; a
coluna «equivalente documentado» é o que se usa se o fornecedor escolhido não
tiver a forma portátil.

| # | Classe | Para quê | Forma portátil | Equivalente documentado se o fornecedor não a tiver | Gerido proprietário? |
|---|---|---|---|---|---|
| 1 | **Compute** | O *host* do Compose reduzido (doc 09 §4.4: 8 vCPU/32 GB em `prod`, 4/16 em `staging`) | VM ou *bare metal* com imagem Linux e cloud-init | Instalação manual pelo procedimento de `README.md` §5 (mais lenta, mesmo resultado) | **Não** |
| 2 | **Disco de blocos** | O volume do Postgres e do WAL (NVMe ≥ 200 GB) | Disco anexo, montado por **etiqueta** de sistema de ficheiros e não por nome de dispositivo | Disco local do *host* | **Não** |
| 3 | **Rede e firewall** | Só 443 e a porta UDP do WireGuard abertas (doc 09 §3.2 regra 5) | Regras de *firewall* do *host* (`nftables`), aplicadas pelo próprio *host* | `nftables` é o caminho por omissão; um grupo de segurança do fornecedor é um reforço, nunca a única barreira. **Não entregue aqui: é o KAM-077** — ver §3.1 | **Não** |
| 4 | **DNS** | O passo «DNS» do orçamento de RTO, com TTL baixo (*proposta*: 300 s) | Zona com registos A/AAAA e TTL configurável — o que qualquer servidor de DNS faz | Qualquer operador de DNS; a zona é um ficheiro | **Não** |
| 5 | **Identidade para o CI** | Autenticação sem chave estática (ADR-L007 §4a) | OIDC do GitHub trocado por credenciais de curta duração | **Nenhum equivalente portátil.** Ver §3.2 | **Não, mas ver §3.2** |
| 6 | **Armazenamento de objectos** | Imagens de catálogo e anexos | API compatível com S3, atrás da porta `StorageProvider` | SeaweedFS no próprio *host* (`compose/docker-compose.storage.yml`) — já existe e já corre | **Não** |
| 7 | **Base de dados** | Postgres 18.6 com pgvector | Contentor no *host*, sem acoplamento a região | É já a forma por omissão; um Postgres gerido seria a excepção, não a regra | **Não** |
| 8 | **Repositório de cópias de segurança** | pgBackRest noutro domínio de falha | Qualquer destino compatível com S3 ou SFTP | **Fora de âmbito deste ticket** — é o KAM-079 | — |

**Contagem: 0 recursos geridos proprietários.** Oito classes, e nenhuma depende
de um serviço gerido de um fornecedor específico. Sete têm equivalente escrito;
a oitava é de outro ticket.

**E duas das sete têm o equivalente escrito e não entregue**, o que é diferente
de o ter: a classe 3 (ver §3.1) e a classe 5 (ver §3.2).

---

## 3. As linhas que não fecham

### 3.1 A classe 3 tem forma portátil escrita e **não implementada**

A coluna «forma portátil» da classe 3 diz `nftables` no próprio *host*. **Não há
uma linha de `nftables` em `infra/`**, e nada neste ticket fecha a porta 22 nem
toca no `sshd`. A revisão adversarial mediu-o:
`grep -rniE "nftables|iptables|ufw|firewall|sshd|port 22" infra/` devolve **uma
única** linha, que é a desta tabela.

Isto não é um furo a tapar aqui: as regras de *firewall* e o ***scan* externo
que as prova** são critérios do **KAM-077**, que é quem tem o *edge*. O que
mudou com a revisão foi a honestidade do registo — o `/etc/kamba/LEIA-ME` que o
*host* escreve dizia «Acesso: só por WireGuard», que era uma **afirmação sem
mecanismo**, e passou a dizer o que o *host* não faz e de quem é. Vale notar a
consequência que estava escondida: o `users: [default, …]` do cloud-init mantém
o utilizador por omissão da imagem, que nas imagens dos fornecedores **traz a
chave que o fornecedor injecta**.

### 3.2 A classe 5 não tem equivalente portátil nenhum

A linha 5 — **identidade para o CI** — não tem equivalente portátil, e isso
escreve-se em vez de se arredondar.

O OIDC do GitHub depende de o fornecedor aceitar um emissor de identidade
federada. Um fornecedor que só ofereça chaves de API de longa duração põe este
ticket em conflito consigo mesmo: ou se usa uma chave estática (que o critério
do ADR-L007 proíbe) ou não se automatiza o provisionamento.

**Isto não é um defeito a corrigir aqui: é um critério de aceitação da D1.**
Fica escrito para quem a decidir:

> Um fornecedor que não suporte identidade federada (OIDC) obriga a uma de três
> coisas: uma chave estática num cofre com rotação curta, provisionamento
> manual, ou um fornecedor diferente. A escolha é do fundador, e a primeira
> opção contradiz o ADR-L007 §4a — pelo que exigiria emendá-lo.

Estado: **NÃO VERIFICADO**, e verifica-se lendo a documentação do fornecedor que
a D1 escolher.

---

## 4. O que esta checklist não prova

| Afirmação | Estado |
|---|---|
| «Mudar de região não exige reescrita» (E3 req. 24; doc 09 §5.3 ponto 1) | **NÃO VERIFICADO.** Nunca se mudou de região, porque nunca houve uma. O que se verifica é a **estrutura** que o permitiria: um módulo de fornecedor, uma interface, e nenhum recurso fora dela |
| «Trocar de fornecedor são duas linhas de `source`» | **NÃO VERIFICADO.** Nunca existiu um segundo `provider-<nome>`. Verifica-se no dia em que o primeiro real existir |
| As oito classes acima são as que o Piloto precisa | **INDÍCIO.** Derivadas do doc 09 §3 e §4.4 e do que o KAM-076 e o KAM-077 vão pedir. Uma nona classe aparece quando um desses tickets a trouxer, e entra aqui |
| Custo por classe | **NÃO VERIFICADO** — nenhuma cotação pedida (`ENVIRONMENTS.md` §6) |

---

## 5. Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-075. Oito classes de recurso com forma portátil e equivalente documentado; contagem de recursos geridos proprietários a **0**, com a distinção escrita entre o zero de um conjunto vazio e o zero mantido pela regra verificada por máquina (§1). A linha 5 (identidade federada para o CI) fica **sem** equivalente portátil e é devolvida como critério de aceitação da D1 (§3.2). O que esta página não prova, com estado, em §4. **Depois da revisão adversarial:** a §3.1 passa a registar que a forma portátil da classe 3 (`nftables`) está escrita e **não implementada** — é do KAM-077 —, e que o `users: default` do cloud-init mantém o utilizador por omissão da imagem do fornecedor, com a chave que ele injecta. A afirmação «Acesso: só por WireGuard» que o *host* escrevia era afirmação sem mecanismo, e foi corrigida no próprio `LEIA-ME`. | Equipa KAMBÁ |
