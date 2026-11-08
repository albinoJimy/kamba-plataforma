# Subprocessadores — KAMBÁ

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Lista pública de subprocessadores (requisito 4 de `E3`) |
| Versão | 1.0+3a1ad9e07f3f |
| Classificação | **Público** |
| Ticket | KAM-069 (EPIC-07) |
| Documento-fonte | [`gov/subprocessadores.yaml`](../../gov/subprocessadores.yaml); `../tecnica/08_Seguranca_Conformidade.md` §8.3.2 |

> **Este documento é gerado e não é aconselhamento jurídico.** Sai de
> [`gov/subprocessadores.yaml`](../../gov/subprocessadores.yaml) por
> `python -m subprocessadores`, e editá-lo à mão é uma alteração que o
> *gate* desfaz. Tudo o que toca à Lei 22/11, à APD e aos Termos da Meta
> leva *(a confirmar por parecer)*, e os estados **CONFIRMADO**,
> **INDÍCIO** e **NÃO VERIFICADO** têm o sentido da evidência de pesquisa
> da KAMBÁ — e **não são promovidos** aqui.

---

## 1. Quem trata dados em nome da sua loja

Cada PME que usa a KAMBÁ é a responsável pelos dados dos seus clientes, e a KAMBÁ é subcontratada (`../tecnica/08` §8.2; o papel definitivo é a decisão **D9**, ainda aberta). Para prestar o serviço, a KAMBÁ recorre aos subprocessadores abaixo.

**11 subprocessadores. 0 com procedimento concluído junto da APD.**

| Subprocessador | Função | Dados pessoais tratados | Destino (hipótese) | Estado do procedimento |
|---|---|---|---|---|
| Meta (WhatsApp Cloud API) | Canal | conteúdo das mensagens, telefone e BSUID | EUA ou UE | pendente |
| OpenAI | LLM e transcrição | texto minimizado, áudio | EUA | pendente |
| Google (Gemini) | LLM | texto minimizado | EUA ou UE | pendente |
| Anthropic | LLM | texto minimizado | EUA | pendente |
| Groq | Transcrição | áudio | EUA | pendente |
| Alojamento (Luanda ou JNB/CPT) | Computação, base de dados e cópias de segurança | todas as classes do docs/tecnica/08 §7.1 | Angola ou África do Sul | pendente |
| CDN e firewall aplicacional (Cloudflare) | Termina TLS e vê tráfego em claro | conteúdo em trânsito | global | pendente |
| Facilitador de pagamentos (ProxyPay ou AppyPay) | Pagamentos | valor, referência e contacto de Express | AO | pendente |
| Software de facturação certificado pela AGT (Vero ou Cacimbo) | Facturas | dados do cliente na factura | AO | pendente |
| Doppler | Cofre de segredos | nenhum | EUA | pendente |
| Correio ou SMS transaccional | Notificações ao dono | endereço de correio e telefone do dono da PME | por decidir | pendente |

## 2. O que «estado do procedimento» quer dizer

| Estado | Significado |
|---|---|
| `pendente` | O procedimento junto da APD não está concluído. **Nenhum dado pessoal de produção sai para este destino** (ADR-008): o *gate* de transferência nega por omissão, e o que corre são dados sintéticos |
| `autorizado` | A APD respondeu e permite, e há contrato, retenção zero e não-treino arquivados |
| `revogado` | Esteve autorizado e deixou de estar |
| `negado` | A APD respondeu e não permite |

**O destino é uma hipótese e não uma afirmação.** Os países confirmam-se contratualmente, e a lista de países «adequados» para efeito dos Arts. 33.º e 34.º da Lei 22/11 não foi encontrada publicamente (**NÃO VERIFICADO**). A KAMBÁ não infere adequação a partir do país: o que liberta uma transferência é a autorização ou a notificação à APD, por destino.

## 3. Direitos do titular

Pedidos de acesso, correcção, eliminação e oposição fazem-se pelo mesmo canal por onde a conversa começou (`../tecnica/08` §8.4). O prazo interno é de 30 dias.
