# Mapa de tratamentos — KAMBÁ (gerado)

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Mapa de tratamentos por destino, **gerado** do inventário e de `platform.tenant_destinations` |
| Versão | 1.0+3a1ad9e07f3f |
| Classificação | Documento de Referência — Interno; base da submissão à APD |
| Ticket | KAM-069 (EPIC-07) |
| Documento-fonte | [`gov/subprocessadores.yaml`](../../gov/subprocessadores.yaml); `platform.tenant_destinations` (revisão [`0036`](../../db/migrations/versions/0036_destinos_de_transferencia.py)); `../tecnica/08_Seguranca_Conformidade.md` §7.1, §8.3, §8.6 |
| Relacionados | [`Mapa_Tratamentos_v1.md`](../tecnica/evidencia/validacao/Mapa_Tratamentos_v1.md) (o de KAM-105, escrito à mão antes de esta tabela existir); [`GoLive_Gate.md`](../tecnica/evidencia/validacao/GoLive_Gate.md) |

> **Este documento é gerado e não é aconselhamento jurídico.** Sai de
> [`gov/subprocessadores.yaml`](../../gov/subprocessadores.yaml) por
> `python -m subprocessadores`, e editá-lo à mão é uma alteração que o
> *gate* desfaz. Tudo o que toca à Lei 22/11, à APD e aos Termos da Meta
> leva *(a confirmar por parecer)*, e os estados **CONFIRMADO**,
> **INDÍCIO** e **NÃO VERIFICADO** têm o sentido da evidência de pesquisa
> da KAMBÁ — e **não são promovidos** aqui.

---

## 1. A versão, e porque é que ela é um `sha256`

`1.0+3a1ad9e07f3f` — a versão declarada do inventário, mais os doze primeiros dígitos do `sha256` das linhas que decidem (sem as `nota`, pela razão que o `ci/llm-aliases.lock` do KAM-030 já escreve: o que se *hasheia* é o conteúdo que decide, não o texto que o descreve).

O critério 9 do KAM-069 pede que **alterar uma linha altere a versão**, e um número escrito à mão não tem essa propriedade: esquece-se. Mudar um país, um estado, uma finalidade ou a *checklist* de qualquer linha muda estes doze dígitos; reescrever uma nota não.

## 2. O que esta versão leu

| Fonte | O que dá | Lido |
|---|---|---|
| [`gov/subprocessadores.yaml`](../../gov/subprocessadores.yaml) | os subprocessadores, a função, os dados e a *checklist* | **11** linhas |
| `platform.tenant_destinations` (revisão `0036`) | a configuração por tenant e destino, com o `apd_ref` e a janela de validade | **0** linhas |

> **Zero linhas de `platform.tenant_destinations`, e isto diz-se em vez de se omitir.** A tabela existe desde a revisão `0036` e **não tem linha nenhuma**: configurar um destino exige um `apd_ref`, e o `ext:KAM-105` fechou com **0 de 14** destinos com `apd_ref` (`../tecnica/evidencia/validacao/Seguimento_APD.md` §1 — zero submetidos, zero com número de protocolo).
>
> Logo este mapa descreve **o que a plataforma trataria**, pelo inventário, e não **o que ela trata**, que hoje é nada em produção. A segunda metade enche-se quando houver uma autorização; até lá, a ausência é o facto, e o `../tecnica/08` §8.6 pede que o mapa não divirja do sistema real — não que pareça completo.

## 3. Os tratamentos, por destino

| Destino | Designação | Função | Dados pessoais | Finalidades | País (hipótese) | País verificado | Estado | Contrato | Retenção zero | Não-treino | `apd_ref` | Credor |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| meta | Meta (WhatsApp Cloud API) | Canal | conteúdo das mensagens, telefone e BSUID | `canal` | EUA ou UE | **não** | `pendente` | **não há** | **não** | **não** | **não há** | KAM-104 |
| openai | OpenAI | LLM e transcrição | texto minimizado, áudio | `conversa`, `transcricao` | EUA | **não** | `pendente` | **não há** | **não** | **não** | **não há** | KAM-104 |
| google | Google (Gemini) | LLM | texto minimizado | `conversa`, `visao` | EUA ou UE | **não** | `pendente` | **não há** | **não** | **não** | **não há** | KAM-104 |
| anthropic | Anthropic | LLM | texto minimizado | `conversa`, `visao` | EUA | **não** | `pendente` | **não há** | **não** | **não** | **não há** | KAM-104 |
| groq | Groq | Transcrição | áudio | `transcricao` | EUA | **não** | `pendente` | **não há** | **não** | **não** | **não há** | KAM-036 |
| alojamento | Alojamento (Luanda ou JNB/CPT) | Computação, base de dados e cópias de segurança | todas as classes do docs/tecnica/08 §7.1 | `alojamento`, `copias_de_seguranca` | Angola ou África do Sul | **não** | `pendente` | **não há** | **não** | **não** | **não há** | D1 |
| cdn_waf | CDN e firewall aplicacional (Cloudflare) | Termina TLS e vê tráfego em claro | conteúdo em trânsito | `entrega_de_conteudo` | global | **não** | `pendente` | **não há** | **não** | **não** | **não há** | D12 |
| facilitador_de_pagamentos | Facilitador de pagamentos (ProxyPay ou AppyPay) | Pagamentos | valor, referência e contacto de Express | `pagamentos` | AO | **não** | `pendente` | **não há** | **não** | **não** | **não há** | D4 |
| facturacao_agt | Software de facturação certificado pela AGT (Vero ou Cacimbo) | Facturas | dados do cliente na factura | `facturacao` | AO | **não** | `pendente` | **não há** | **não** | **não** | **não há** | D7 |
| doppler | Doppler | Cofre de segredos | nenhum | `segredos` | EUA | **não** | `pendente` | **não há** | **não** | **não** | **não há** | KAM-104 |
| email_sms | Correio ou SMS transaccional | Notificações ao dono | endereço de correio e telefone do dono da PME | `otp_e_avisos_de_servico` | por decidir | **não** | `pendente` | **não há** | **não** | **não** | **não há** | KAM-104 |

**11 de 11 destinos estão `pendente`.** Enquanto um destino não estiver `autorizado` com `apd_ref`, o *gate* de transferência (`libs/py-core/src/kamba_core/destinos/`) nega-o: nenhum dado pessoal de produção sai para lá (ADR-008).

## 4. O que este mapa não decide, e a quem fica

| Item | Estado | Credor |
|---|---|---|
| Qual é cada subprocessador | **nenhum está escolhido** — escolher um num ficheiro de código é o que o ADR-008 existe para impedir | o fundador, com o parecer de KAM-104 |
| Lista de países «adequados» (Arts. 33.º–34.º) | **NÃO VERIFICADO**: não encontrada publicamente; a UE e a África do Sul são hipóteses e os EUA provavelmente exigem autorização (INDÍCIO) | KAM-104 |
| Papel da KAMBÁ: responsável ou subcontratada | **D9**, aberta; a omissão é `subcontratada` (`../tecnica/08` §8.2, «até parecer») | KAM-104 |
| Local do alojamento e das cópias | **D1**, aberta; depende de ≥ 3 cotações, nenhuma pedida | o fundador |
| O CDN que termina TLS é subprocessador | **D12**, aberta; há um caminho que a dispensa (não pôr os webhooks atrás do proxy) | o fundador |
| Contrato de subcontratação (DPA) com cada PME | **não está redigido** | KAM-090 |
| Submissão, taxas e número de protocolo | **nenhuma submissão feita** | KAM-105 |
| Observabilidade como destino | o `purpose` existe no domínio e **nenhum subprocessador o declara**: o §8.3.2 não tem linha de observabilidade | KAM-080 e KAM-105 |
| Reconciliar as 11 linhas do §8.3.2 com os 14 destinos da folha de seguimento | o §8.3.2 junta alojamento e cópias numa linha, e não tem a sonda sintética nem o melhoramento de imagem | KAM-105 |
| Registo das mudanças deste mapa no `audit_log` | **por ligar**: não há processo de plataforma que o gere em execução | KAM-071 |
