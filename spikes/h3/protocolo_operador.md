# Folha de protocolo do operador — spike H3 (KAM-100)

**Para quem conduz o spike com um dono de número.** Imprime-se ou abre-se no
portátil, e preenche-se **uma por número** (N1, N2, N3).

> **O que esta folha recolhe não entra no repositório.** O número, o nome do
> dono e o consentimento ficam no portátil do operador e apagam-se em ≤ 30 dias,
> com os JSON-lines. O repositório é público, e o que lá vai são os rótulos
> `N1`–`N3` e as contagens — nunca o número (ADR-010).

---

## 0. Antes de marcar com o dono

| # | Verificação | Feito |
|---|---|---|
| 0.1 | O **Passo 0** está respondido? Ver `../../docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md` §1. Hoje é `NÃO VERIFICADO`, e o spike está **bloqueado** nele | [ ] |
| 0.2 | **Consentimento escrito** do dono, arquivado fora do repositório, antes de qualquer ecrã | [ ] |
| 0.3 | O dono sabe que o bot **se cala na conversa** em que ele responder pela app (`../../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §10.2) | [ ] |
| 0.4 | O dono sabe que **perde** grupos, mensagens temporárias, *view once*, localização em tempo real, listas de difusão, chamadas na API, e as ferramentas de negócio da app — catálogo, pedidos, saudação, ausência, respostas rápidas, etiquetas e perfil (`../../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` §2) | [ ] |
| 0.5 | O dono sabe que os **dispositivos associados ficam desligados** no *onboarding* | [ ] |
| 0.6 | O dono sabe que **não abrir a app ~14 dias desliga a ligação** (`PRIMARY_INACTIVITY`) | [ ] |
| 0.7 | O dono indicou **20 conversas de controlo** e sabe que vai contar as mensagens delas (§4) | [ ] |

**Se 0.2 não estiver feito, para aqui.** O consentimento é do fundador, não do
operador, e nenhum passo seguinte se faz sem ele.

---

## 1. Pré-voo do número

A lista é a de `../../docs/tecnica/10_Onboarding_Governanca.md` §6.3, que é a
fonte. Não se reescreve aqui: anota-se o resultado.

| # | Verificação | Resultado | Se falhar |
|---|---|---|---|
| 1.1 | **Versão da app WhatsApp Business.** Abrir a app → Definições → Ajuda → Informações da aplicação. Anotar a versão **exacta** | `__________` | Abaixo de **2.24.17** não há coexistência (`E1` §2). Actualizar e repetir |
| 1.2 | A app foi **aberta nos últimos dias** | [ ] | Instruir o dono a mantê-la aberta |
| 1.3 | Tipo: **móvel** ou **fixo** | `__________` | Fixo exige verificação **por voz** |
| 1.4 | Operadora: **Unitel**, **Africell** ou **fixo** | `__________` | — |
| 1.5 | O número **não** está em WhatsApp pessoal (só Business) | [ ] | Tem de ser eliminado antes, salvo conversão para a app Business |
| 1.6 | *Display name* válido | [ ] | Corrigir |
| 1.7 | O **dono está presente** (é ele que autentica na Meta e confirma na app) | [ ] | Reagendar. O operador **não** age em nome do dono |

---

## 2. Arranque do harness

Tudo no portátil do operador. Os dois segredos vêm do cofre e **não** do
repositório.

```bash
export KAMBA_H3_APP_SECRET='<do cofre>'
export KAMBA_H3_VERIFY_TOKEN='<do cofre>'
export PYTHONPATH='spikes/h3;libs/py-core/src'
python spikes/h3/receptor.py --porta 8787 --destino eventos.jsonl
```

O receptor **recusa arrancar** sem os dois. Depois:

| # | Passo | Feito |
|---|---|---|
| 2.1 | Túnel HTTPS com **certificado válido** até à porta 8787. Auto-assinado **não** serve (`../../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` §5) | [ ] |
| 2.2 | No App Dashboard, pôr o URL do túnel e o `hub.verify_token`. A Meta faz um **GET** de verificação; o receptor devolve o `hub.challenge` e anota `token valido` | [ ] |
| 2.3 | Subscrever os **cinco** campos: `messages`, `history`, `smb_app_state_sync`, `smb_message_echoes`, `account_update` | [ ] |
| 2.4 | Escrever o `rotulos.json` no portátil, a mapear o `phone_number_id` deste número em `N1`, `N2` ou `N3`. **Sem ele a tabela recusa a linha** | [ ] |

O `rotulos.json` é um objecto só, por exemplo `{"<phone_number_id>": "N1"}`. O
`phone_number_id` é um identificador de canal que a Meta atribui, e não um
telefone — mas o ficheiro fica no portátil de qualquer maneira.

---

## 3. O Embedded Signup

Abrir a página com o App ID e o Configuration ID na *query string*:

```text
file:///<caminho>/spikes/h3/es_coexistencia.html?app=<APP_ID>&config=<CONFIGURATION_ID>
```

| # | Passo | Resultado | Anotar |
|---|---|---|---|
| 3.1 | O dono faz login no Facebook e aceita os termos | [ ] | |
| 3.2 | O dono introduz o número | [ ] | |
| 3.3 | **Método de verificação**: SMS ou voz | `__________` | A coluna «Verificação» da tabela |
| 3.4 | **O SMS chegou?** (só se o método foi SMS) | S / N | A coluna «Entrega do SMS». É um resultado do spike: a entrega internacional em Unitel e Africell é **NÃO VERIFICADA** |
| 3.5 | O dono recebe o código e confirma **na app** (mensagem do «Facebook Business Account», botão *Connect*) | [ ] | |
| 3.6 | O dono escolhe **partilhar histórico** — ou não | partilhou / recusou | **Decisivo.** Ver o §4.3 |
| 3.7 | O registo da página mostra `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` | [ ] | A hora exacta: **o prazo de 24 h começa aqui** |
| 3.8 | Copiar o `code` do registo da página para o portátil. **Não se troca na página** | [ ] | |

> **Em v4 não há registo do número** (já está registado na app do dono), e o
> «Phone Number First» entra em coexistência automaticamente se a coexistência
> estiver activada e o número estiver na app (`E1` §2).

---

## 4. As medições

### 4.1 Os 10 envios, para a mediana da latência do *echo*

O dono envia **10 mensagens pela app**, de preferência a 10 conversas
diferentes, com cerca de um minuto entre cada. Cada uma chega ao receptor como
`smb_message_echoes`.

| # | Hora do envio (pelo dono) | *Echo* no receptor | Feito |
|---|---|---|---|
| 1 | | | [ ] |
| 2 | | | [ ] |
| 3 | | | [ ] |
| 4 | | | [ ] |
| 5 | | | [ ] |
| 6 | | | [ ] |
| 7 | | | [ ] |
| 8 | | | [ ] |
| 9 | | | [ ] |
| 10 | | | [ ] |

**São dez, não «cerca de dez».** O script escreve o `n` ao lado da mediana, e
uma mediana de três apresentada como se fossem dez é o defeito que a coluna
existe para não ter.

### 4.2 O *echo* de uma mensagem enviada pela API

Isto responde ao item **NÃO VERIFICADO** de
`../../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §10.3.

| # | Passo | Feito |
|---|---|---|
| 4.2.1 | Enviar **uma** mensagem pela Cloud API, para uma conversa com janela aberta | [ ] |
| 4.2.2 | Escrever o `wamid` dela — o que a API devolveu — numa linha do `nossos.txt` | [ ] |
| 4.2.3 | Ver se chegou um `smb_message_echoes` com esse `wamid` | S / N |

O receptor lê o `nossos.txt` **ao arrancar**. Se o acrescentar depois, reiniciar
o receptor — senão a coluna sai `NÃO MEDIDO` com o *echo* gravado, que é pior do
que um `N`, porque parece que não houve *echo*.

### 4.3 A contagem das 20 conversas de controlo

É a metade que **o harness não mede**: os JSON-lines contam as mensagens que o
`history` entregou; quantas **deviam** estar lá conta-se na app do dono.

| Conversa | Mensagens nos últimos 6 meses (na app, pelo dono) | Presentes depois da sincronização |
|---|---|---|
| 1 | | |
| 2 | | |
| … | | |
| 20 | | |
| **Total** | | |

O limiar é **≥ 95%** por contagem
(`../../docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md` §3).

**Se o dono recusou partilhar histórico** (§3.6), não há contagem a fazer: chega
um `history` com o erro **2593109**, que é caso normal pela Meta — e **só conta
como êxito de H3 se a recusa foi do dono**. Escrever aqui, por palavras do
operador, que a recusa foi dele: `________________________________`

### 4.4 A janela de 24 h

| # | Passo | Resultado |
|---|---|---|
| 4.4.1 | Pedir a um cliente que escreva **depois** do *onboarding* | [ ] |
| 4.4.2 | A janela abriu (foi possível responder pela API sem template)? | S / N |

A janela **só abre quando o utilizador escreve depois do onboarding**; mensagens
enviadas pela app não abrem janela nem afectam o preço da Cloud API (`E1` §2).

### 4.5 A sincronização e as 24 h

| # | O que | Hora |
|---|---|---|
| 4.5.1 | `FINISH_...ONBOARDING` (do §3.7) | |
| 4.5.2 | Último `history` ou `smb_app_state_sync` no receptor | |
| 4.5.3 | Diferença | `_____ h` |

**O prazo é duro: 24 h, e cada passo executa-se uma só vez.** Passado isso o
cliente tem de ser *offboarded* e refazer o ES (`E1` §2). Manter a app do dono
aberta ajuda.

---

## 5. Fechar

| # | Passo | Feito |
|---|---|---|
| 5.1 | Gerar a tabela: `python spikes/h3/tabela.py eventos.jsonl` | [ ] |
| 5.2 | Copiar a tabela para `../../docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md` §2, e preencher **à mão** as cinco linhas da folha — operadora, tipo, versão da app, verificação e janela de 24 h | [ ] |
| 5.3 | Validar: `python scripts/validar_evidencia.py docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md` | [ ] |
| 5.4 | Anotar os `account_update` que chegaram, com o motivo | [ ] |
| 5.5 | **Apagar** os JSON-lines, o `rotulos.json` e o `nossos.txt` em ≤ 30 dias, e registar a data do apagamento no consentimento arquivado | [ ] |

**Não preencher a decisão H3.** Ela é do fundador, com dono e data, no §4 do
ficheiro de resultado e na linha H3 do
`../../docs/tecnica/evidencia/validacao/Registo_Hipoteses.md`.

---

## 6. O que fazer quando algo corre mal

| Sintoma | O que significa | Resposta |
|---|---|---|
| O receptor responde **401** | A assinatura não corresponde ao corpo. Ou o App Secret está errado, ou o pedido não é da Meta | Confirmar o segredo no cofre. **Não** desligar a verificação |
| O receptor anota «assinado mas ilegível» | Alguém com o App Secret mandou algo que não é JSON | Guardar a hora e avisar o fundador |
| O **GET** de verificação dá **403** | `hub.verify_token` diferente, `hub.mode` não é `subscribe`, ou falta o `hub.challenge` | Comparar o token com o do App Dashboard |
| A tabela recusa com «`numero` é None» | Falta o `rotulos.json`, ou o `phone_number_id` não está lá | Acrescentar e regerar. Os eventos **estão** gravados |
| Sincronização **> 24 h** | Caso marcado `desligado`; refazer o ES (`../../docs/tecnica/10_Onboarding_Governanca.md` §6.4) | Anotar como resultado — **é uma medição**, não uma falha do spike |
| `account_update` com `PARTNER_REMOVED` | O canal caiu. O motivo diz porquê | Anotar o motivo. Não é falha do harness |
| Zero *echoes* | **Não medido**, e não «não há *echo*» | Confirmar que `smb_message_echoes` está subscrito (§2.3) e repetir |
