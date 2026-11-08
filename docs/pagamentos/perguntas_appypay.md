# Perguntas à AppyPay — redacção para envio

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Perguntas escritas à AppyPay, redigidas e **por enviar**, com o registo de envio vazio |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-057 (EPIC-05), critério 1 |
| Data de redacção | **2026-11-08** |
| Estado | **Redigidas, não enviadas.** Nenhuma contraparte foi contactada |
| Dono do envio | **o fundador** — contactar contrapartes é acto dele, e o canal escolhe-o ele |
| Documento-fonte | [`../tecnica/evidencia/E2_Pagamentos_Angola.md`](../tecnica/evidencia/E2_Pagamentos_Angola.md) §9, perguntas 11–15; [`../tecnica/evidencia/validacao/Pagamentos_Respostas.md`](../tecnica/evidencia/validacao/Pagamentos_Respostas.md) §2.5 (pergunta 11-a e o registo de resposta); [`matriz_facilitadores.md`](matriz_facilitadores.md) §3 |

> **Este ficheiro é o texto a enviar, não o registo de respostas.** O registo de resposta da AppyPay
> já existe em `../tecnica/evidencia/validacao/Pagamentos_Respostas.md` §2.5, com os campos
> `estado`, `data`, `remetente (papel)`, `classificação` e `resposta`, e a regra de classificação
> por origem do §2.1 desse documento. Duplicá-lo aqui era criar duas folhas que divergem na
> primeira resposta. O que este ficheiro acrescenta é a **redacção** — as perguntas do E2 afinadas
> pelo que a documentação pública passou a dizer a 2026-11-08 — e o **registo de envio**.

---

## 1. Numeração, e o que é acréscimo

A numeração é a de `../tecnica/evidencia/E2_Pagamentos_Angola.md` §9, que o resto do conjunto cita.
Um acréscimo leva o número da pergunta-mãe e uma letra, como o **11-a** do KAM-103 — e declara-se
como acréscimo, porque um acréscimo calado é alteração de sentido a passar por transcrição.

| # | Origem | Porque existe |
|---|---|---|
| 11, 12, 13, 14, 15 | E2 §9 | As cinco que o critério 1 do ticket nomeia |
| 11-a | KAM-103 (`../tecnica/evidencia/validacao/Pagamentos_Respostas.md` §2.5) | Prazo de *onboarding*: é H5 pela via AppyPay |
| **11-b** | **Acréscimo deste ticket** | O anexo de preços dos termos cobre GPO, REF e SDD e **não** o Unitel Money ([`matriz_facilitadores.md`](matriz_facilitadores.md) §3, linha 9) |
| **11-c** | **Acréscimo deste ticket** | A documentação só mostra o *endpoint* de *token* de um *tenant* de desenvolvimento (§3, linha 6) |
| **12-a** | **Acréscimo deste ticket** | O `POST /charges` lista um 409 que nenhuma página descreve, e o âmbito da unicidade do `merchantTransactionId` decide se o `numero_publico` chega (§3, linhas 4 e 7) |
| **12-b** | **Acréscimo deste ticket** | Nenhuma página dá *rate limit* nem lista de IPs de origem do *webhook* (§3, linha 15) |

As perguntas 12-a e 12-b separam-se da 12 de propósito: a 12 decide o portão do ADR-013 e tem de
poder ser respondida sozinha, sem esperar pelas outras.

---

## 2. O texto a enviar

O texto não leva nome de ninguém — nem do lado da KAMBÁ nem do lado da AppyPay —, porque este
repositório é público. Quem envia acrescenta a assinatura no acto do envio, fora do repositório.

```text
Assunto: Integração de plataforma multi-comerciante com a AppyPay Payment Gateway v2.0 — pedido de
esclarecimentos técnicos e comerciais por escrito

Estamos a avaliar a AppyPay como facilitador de pagamentos para uma plataforma de software que
gera cobranças em nome de comerciantes angolanos (PME com NIF), em que cada comerciante tem o seu
próprio contrato com a AppyPay, o seu Banco de Apoio e os seus serviços EMIS, e em que a liquidação
é feita directamente na conta de cada comerciante. A plataforma não recebe, não retém e não
transfere fundos de terceiros.

Lemos a documentação publicada em appypay.stoplight.io (versão 2.0) e os Termos de Utilização.
Pedimos resposta escrita às questões seguintes, com a indicação de que documento ou cláusula a
sustenta quando exista.

11. Documentação e ambiente de testes
    a) Existe especificação OpenAPI exportável da versão 2.0, e é a que está publicada na Stoplight?
    b) Como se obtém acesso ao ambiente de testes (gwy-api-tst.appypay.co.ao) e que dados de teste
       existem para simular os resultados de cada método (GPO, REF, UMM)?

11-a. Prazo de activação (acréscimo)
    Qual o prazo, em dias úteis, entre o pedido e as credenciais AppyPay activas para um
    comerciante, e que documentos exigem? O "onboarding automático só com o NIF" aplica-se à conta
    AppyPay ou também às credenciais EMIS (POSID, Entidade, IEC)?

11-b. Preço do Unitel Money (acréscimo)
    O anexo "Preçário geral" dos Termos cobre GPO, REF e SDD. Qual o preço por transacção do
    Unitel Money (UMM), e aplica-se o mesmo mínimo e máximo?

11-c. Autenticação em produção (acréscimo)
    A documentação mostra a obtenção do token num tenant Azure AD de desenvolvimento. Qual o
    endpoint de token e o "resource" a usar em produção, e com que periodicidade se rodam as
    credenciais (client secret)?

12. Webhook transaccional
    a) As notificações do webhook são assinadas? Se sim, com que algoritmo, sobre que bytes do
       pedido, em que cabeçalho e com que segredo, e esse segredo é distinto das credenciais OAuth?
    b) As notificações incluem um carimbo temporal assinado que permita recusar repetições?
    c) Se o nosso servidor não responder 2xx, a AppyPay reenvia? Quantas vezes, com que intervalos
       e durante quanto tempo? A mesma notificação pode chegar mais de uma vez?
    d) O que significa o campo responseStatus.sourceDetails.attempt?
    e) O GET /charges/{id} devolve o estado final de um pagamento por referência feito mais tarde
       num ATM ou no Multicaixa Express, e é a fonte que recomendam para confirmar um pagamento
       quando o webhook falha?

12-a. Unicidade e idempotência (acréscimo)
    a) Qual é o âmbito da unicidade do merchantTransactionId — por comerciante, por aplicação ou
       global? Pode repetir-se depois de uma cobrança expirar ou falhar?
    b) O que significa a resposta HTTP 409 do POST /charges? Repetir o mesmo pedido com o mesmo
       merchantTransactionId depois de uma resposta perdida devolve a cobrança original, ou recusa?

12-b. Limites e origem (acréscimo)
    Existe limite de pedidos por minuto (e com que resposta HTTP)? Publicam a lista de endereços
    IP de origem das notificações do webhook?

13. Certificação
    Podem enviar a carta ou certificado da EMIS (data e âmbito) que sustenta a declaração de
    "serviço de facilitação certificado pela EMIS", e confirmar por escrito que a AppyPay não
    necessita de licença do BNA para o serviço que presta?

14. Transferências de fundos (FTBAI)
    A documentação descreve transferências de fundos FTBAI (BAI, em BETA). Para que servem, quem
    pode usá-las, e a partir de que conta? Perguntamos para garantir que não as usamos: a nossa
    plataforma não executa pagamentos a terceiros.

15. Modelo de parceiro
    Existe modelo "partner/ISV" em que uma plataforma integra vários comerciantes por API? Se sim,
    confirmem por escrito que cada comerciante mantém o seu próprio contrato, a sua Entidade/POSID
    e a liquidação na sua própria conta, e que a plataforma não é parte no fluxo de fundos.
```

**A pergunta 15 leva a desambiguação do KAM-103 por escrito.** O
`../tecnica/evidencia/validacao/Pagamentos_Respostas.md` §7.2 mostrou que «conta-mestre» e
«modelo ISV» têm duas leituras, e uma delas é o desenho B — a plataforma como comerciante único,
actividade regulada. O texto acima pede a confirmação das **duas metades**: a integração por API
**e** a entidade e a liquidação por comerciante. Um «sim» que confirme só a primeira não preenche
a célula.

---

## 3. Registo de envio

Nasce vazio. **A data de redacção não é a data de envio**: a do envio é o dia 0 da regra de
seguimento do `../tecnica/evidencia/validacao/Pagamentos_Respostas.md` §2.8, e ainda não existe.

| # | Redigida em | Enviada em | Canal | Por | Resposta |
|---|---|---|---|---|---|
| 11 | 2026-11-08 | — | — | — | registar em `Pagamentos_Respostas.md` §2.5 |
| 11-a | 2026-11-08 | — | — | — | idem |
| 11-b | 2026-11-08 | — | — | — | idem, linha nova |
| 11-c | 2026-11-08 | — | — | — | idem, linha nova |
| 12 | 2026-11-08 | — | — | — | idem |
| 12-a | 2026-11-08 | — | — | — | idem, linha nova |
| 12-b | 2026-11-08 | — | — | — | idem, linha nova |
| 13 | 2026-11-08 | — | — | — | idem |
| 14 | 2026-11-08 | — | — | — | idem |
| 15 | 2026-11-08 | — | — | — | idem |

**As linhas novas no registo de resposta do KAM-103** (11-b, 11-c, 12-a, 12-b) entram quando
houver resposta a registar, e não antes: uma linha `por enviar` acrescentada agora àquela tabela
era editar o produto de outro ticket para dizer o que este ficheiro já diz.

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-057): as perguntas 11 a 15 do E2, a 11-a do KAM-103 e quatro acréscimos declarados (11-b, 11-c, 12-a, 12-b), redigidas a 2026-11-08 a partir da documentação pública lida nesse dia. Nenhuma enviada. | Equipa KAMBÁ |
