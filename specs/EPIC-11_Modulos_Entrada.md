# EPIC-11 — Módulos de Entrada (captação e suporte)

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Módulos de Entrada |
| Versão | 1.11 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Documento-fonte | `../docs/tecnica/00_Arquitectura_Solucao.md` (ADR-020, §13.3 D13), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§21), `../docs/exploracao/14-tese-minima-e-plano-de-validacao.md` (H10–H12) |
| Documentos relacionados | `../docs/tecnica/03_Core_Comercio_Medusa.md` (§17), `../docs/tecnica/08_Seguranca_Conformidade.md` (§18), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§21), `../docs/tecnica/10_Onboarding_Governanca.md` (§21), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md`, `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md`, `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md`, `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md`, `../docs/exploracao/01-modelo-negocios-angola-ai-first.md` (negócios Nº 3, 4, 5, 8), `specs/INDICE.md`, `specs/01_Engineering_Standards_e_Handoff.md`, `specs/02_Dicionario_de_Dados_Canonico.md` (§3.7), `specs/EPIC-03_Agent_Runtime_Verticais.md`, `specs/EPIC-04_Core_Comercio.md`, `specs/EPIC-09_Onboarding_Governanca.md` |

---

## 1. Visão do Epic

Por decisão do fundador (**ADR-020**), o Piloto inclui até **quatro módulos de entrada** *owner-facing*, finos e com o dono no circuito: **Catálogo AI conversacional** (`catalogo`), **Foto de produtos AI** (`foto`, ferramenta), **Social AI** (`social`, calendário, legendas e artes para **publicação manual**) e **Orçamento expresso** (`orcamento`). Servem para captar a PME com valor imediato, antes e fora do atendimento a clientes (que continua a ser Vendedor e Serviços, regra de dois, ADR-012), e correm sobre o mesmo AGR/REG/TLS, com o requisito de **reaproveitamento ≥ 70% do core**. O epic concretiza o componente **ENT** (`../docs/tecnica/00` §4) e a hipótese de produto H10–H12 (`14` §2). Fase 1. ADRs: 020 (núcleo), 005, 007, 008, 010, 012, 015, 018, 019. Decisões abertas tocadas: D1, D9, D10, **D13** (publicação automática, Diferida).

Regras que atravessam todos os tickets: (1) **aprovação do dono** antes de qualquer saída a terceiros (cliente ou rede social) e **nenhuma tool publica ou envia por si** (o `send` continua a ser o único caminho ao cliente); (2) **sem publicação automática** em Instagram/Facebook: só a interface `SocialPublisher` fica como gancho, com a implementação `ManualDelivery`; **sem tokens de redes no Piloto**; (3) preços e totais só como *facts* (ADR-007): o dono fixa o preço, o modelo nunca o calcula nem o inventa; (4) conteúdo para terceiros marcado como gerado por IA e filtrado pelo screening de categorias (KAM-088); (5) dados pessoais em imagens (rostos, matrículas, EXIF) nunca saem de Angola sem filtro local e destino registado com `apd_ref` (ADR-008); (6) os módulos **não bloqueiam o gate da Fase 0 (KAM-108) nem o do Piloto (KAM-110)** e cortam-se primeiro se a Fase 0 derrapar (excepto o Catálogo AI, pré-requisito do onboarding); (7) **máximo de 4 módulos**; mais exige emenda ao ADR-020.

O canal do dono (KAM-118) é a peça habilitadora: o dono fala com o **número da própria loja**, a partir do telemóvel verificado por OTP no onboarding, e o CHR encaminha-o para a persona `dono`; quando o WhatsApp ainda não está ligado (Embedded Signup por concluir, limite de 10 clientes/7 dias, E1), os mesmos módulos correm no **painel web** do onboarding-web. Não exige número da KAMBÁ (ADR-011/D10). As mensagens proactivas ao dono são desenhadas para que **o dono inicie** (janela de 24 h, *service messages* gratuitas até 1.000/mês/número); o *push* é opcional, por *template*, classificado como marketing (≈ 0,0225 USD; 4/mês ≈ 0,09 USD por PME, E5).

Estado da evidência (E5): **CONFIRMADO** — preços e termos publicados dos fornecedores (a reconferir antes de contratar), requisitos de Advanced Access para publicação em redes, tarifas Meta, `is_ai_generated` na API do Instagram. **INDÍCIO** — ausência de protecção de autor para imagens geradas (Lei 15/14), prazos de App Review, qualificação das fotos como transferência, mercado angolano de redes sociais. **NÃO VERIFICADO** — qualidade de fundo limpo e *relighting* em fotos angolanas, latência dos fornecedores, qualidade de legendas em pt-AO, política de rotulagem de 2026, disposição a pagar, remetente «KAMBÁ → dono». Os preços de teste dos módulos são **hipóteses** (negócios Nº 3, 4, 5, 8: catálogo 15–90 mil Kz, fotos 15–80 mil Kz, redes sociais 80–250 mil Kz) e todo o limiar numérico é *proposta* a calibrar. Todo o facto jurídico leva *(a confirmar por parecer)*.

---

## 2. Critérios de Saída do Epic

- [ ] **100% das mensagens do dono encaminhadas para a persona `dono`** e **0 promoções a `dono`** por texto, noutro tenant ou por número novo sem OTP, no conjunto adversarial de KAM-118.
- [ ] **0 caminhos de publicação automática**: não existe tool, implementação activa de `SocialPublisher` (além de `ManualDelivery`) nem segredo de rede social no repositório e nos ambientes; teste de CI verde.
- [ ] **100% do conteúdo para terceiros (artes, legendas, propostas) com aprovação do dono por botão** e idempotente (reenviar a aprovação 2× produz 1 só item aprovado).
- [ ] **0 preços não-*fact*** e **0 conteúdo de categoria bloqueada** no golden dos módulos do dono (KAM-125), com reescrita sintética (ADR-018).
- [ ] **Filtro local de rostos e matrículas: 0 imagens do conjunto de teste com rostos ou matrículas chegam a um fornecedor** (esvaziadas por *stub* de egress); EXIF/GPS removido em 100% dos envios.
- [ ] Fornecedor de imagem escolhido por *bake-off* com ≥ 30 fotos reais autorizadas; **carta escrita «sem treino com as imagens», retenção e região** de cada fornecedor activo arquivada antes de qualquer foto real; BFL e remove.bg ausentes da configuração.
- [ ] Custo por módulo e por tenant medido (LLM + imagem + mensagens), reconciliado com os fornecedores (LLM ≤ 2%, imagem ≤ 5%, *propostas*), e `v_h12` produz o rácio custo/preço de teste.
- [ ] Reaproveitamento do core ≥ 70% medido para `catalogo`, `social` e `orcamento`; nenhuma excepção no core para um módulo.
- [ ] H10, H11 e H12 pré-registadas, medidas e com **decisão por módulo (manter, ajustar, abater)** registada; a regra de escopo (máx. 4) está imposta por CI. Este critério **não bloqueia** o Gate do Piloto.
- [ ] Relatório do spike de Factura AI (KAM-126) arquivado com recomendação para o epic de Clusters; nenhum código de facturação no Piloto.
- [ ] Limiares *proposta* revistos no fim do Piloto, com registo da calibração (valor inicial, valor medido, decisão).

---

## 3. Tabela Resumo de Tickets

| ID | Título | Tipo | Estimativa | Prioridade | Dependências |
|---|---|---|---|---|---|
| KAM-118 | Canal do dono: reconhecimento do dono no número da loja, painel web e persona Assistente do Dono | feature | L | P1 | KAM-014, KAM-008, KAM-027, KAM-086, KAM-028, KAM-015, KAM-018, KAM-092 |
| KAM-119 | Vertical `catalogo`: fotografar, completar e publicar produtos pelo dono | feature | L | P1 | KAM-118, KAM-049, KAM-043 |
| KAM-120 | Foto de produtos AI: ImageProvider, fundo limpo, correcção de luz e variações | feature | L | P1 | KAM-049, KAM-011, KAM-069 |
| KAM-121 | Vertical `social`: perfil de marca, calendário semanal e legendas em português de Angola | feature | L | P1 | KAM-118, KAM-030, KAM-009, KAM-088 |
| KAM-122 | Social AI: artes e entrega para publicação manual com aprovação do dono | feature | M | P1 | KAM-121, KAM-120, KAM-015 |
| KAM-123 | Orçamento expresso: preço «sob consulta», pedido ao dono e proposta ao cliente | feature | M | P1 | KAM-043, KAM-118, KAM-031, KAM-032, KAM-005, KAM-007, KAM-015, KAM-018 |
| KAM-124 | Planos, entitlements e metering de custo dos módulos de entrada | feature | M | P1 | KAM-009, KAM-081, KAM-120 |
| KAM-125 | Golden PT-AO e guardrails dos módulos do dono (catálogo, social, orçamento) | feature | M | P1 | KAM-040, KAM-119, KAM-121, KAM-123 |
| KAM-126 | Spike Factura AI: parceiro certificado AGT, API e custo | spike | S | P2 | — |
| KAM-127 | Experimento dos módulos de entrada: hipóteses H10–H12, regra de escopo e critérios de abate | chore | M | P1 | KAM-119, KAM-120, KAM-122, KAM-123, KAM-124, KAM-092, KAM-117, KAM-125 |
| KAM-211 | Canal do dono: ligações de produção — painel, troca de telefone, provisionamento e botão | feature | L | P1 | KAM-118, KAM-086, KAM-092, KAM-099, KAM-186 |
| KAM-215 | Canal do dono: o dono nasce do provisionamento em produção — emissor, `phone_enc` e consumidor | feature | L | P1 | KAM-211 |
| KAM-216 | Canal do dono: o número da loja persistido e o `owner_channel_wa` no painel | feature | M | P1 | KAM-211 |
| KAM-217 | Canal do dono: o painel do dono em produção — `OwnerPort`, processo web ligado e troca montada | feature | L | P1 | KAM-211 |
| KAM-226 | Canal do dono: a `OwnerPort`, a mensagem do dono persistida e a troca com prova de posse | feature | L | P1 | KAM-217, KAM-227 |
| KAM-227 | Saída do AGR: o evento de resposta do turno, para o WhatsApp e para o painel | feature | L | P1 | KAM-217 |

---

## KAM-118 — Canal do dono: reconhecimento do dono no número da loja, painel web e persona Assistente do Dono

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-014, KAM-008, KAM-027, KAM-086, KAM-028, KAM-015, KAM-018, KAM-092 |
| Bloqueia | KAM-119, KAM-121, KAM-123, KAM-211 |
| Responsável sugerido | Engenheiro de Runtime/IA (CHR, AGR) com Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§21.2–21.4), `../docs/tecnica/00_Arquitectura_Solucao.md` (ADR-020, ADR-011, §4 CHR, D10), `../docs/tecnica/08_Seguranca_Conformidade.md` (§18), `../docs/tecnica/10_Onboarding_Governanca.md` (§21), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` (§4), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§1, §2), ADR-010, ADR-015 |

### Contexto

Os módulos de entrada são *owner-facing*: precisam de um canal em que o dono, e só ele, fala com o runtime. Em vez de um número da KAMBÁ (vedado até D10, ADR-011), o dono escreve para o **número da própria loja** a partir do telemóvel verificado por OTP no onboarding (KAM-086); o CHR resolve `phone_number_id → tenant` e, se o remetente corresponder ao contacto `papel='dono'` desse tenant, devolve a persona `dono`. Enquanto o Embedded Signup não termina (ou há lista de espera, KAM-095), o mesmo runtime serve o **painel web**. Risco de desenho: se o telemóvel do dono **for o próprio número da loja** (coexistência, E1 §2), não há conversa dono → loja, pelo que esse caso degrada para painel web. A troca de SIM é INDÍCIO de risco (`../docs/tecnica/08` §18), daí o OTP na mudança de telefone e os botões de confirmação nas acções sensíveis.

### Objectivo

Entregar o reconhecimento do dono no CHR, a persona `dono` (Assistente do Dono) com `registry/dono.yaml` e lista própria de tools, o painel web equivalente, a confirmação por botão de acções sensíveis e a política de mensagens proactivas (o dono inicia; *push* opcional por *template*).

### Critérios de Aceitação

- [x] O CHR devolve persona `dono` se e só se o remetente (por `lookup_hmac`/`bsuid`) é o contacto `papel='dono'` do tenant do `phone_number_id`; em 200 mensagens sintéticas (dono, clientes, o mesmo telefone noutro tenant) o encaminhamento correcto é 100% e **0** mensagens do dono do tenant A são tratadas como dono no tenant B.
- [x] O `papel` só muda por OTP validado (KAM-086/116) ou pela saga; 20 textos adversariais («sou o dono», «sou o administrador», «muda-me para dono», mensagem reencaminhada) → **0** alterações de `papel`; no máximo 1 `dono` por tenant (restrição de BD).
- [ ] O contacto `dono` é criado de forma idempotente ao consumir `tenant.provisioned` (reentrega 3× → 1 contacto); sem o evento o remetente é `cliente`.
- [ ] Mudança de telefone do dono: novo OTP obrigatório; até validar, o número novo é `cliente` e o antigo mantém o papel; após a troca, **acções sensíveis ficam bloqueadas 24 h** (*proposta*) e é emitido aviso ao número antigo e ao e-mail (ganchos para KAM-115).
- [ ] Acções sensíveis (alterar preço/stock em massa, aprovar conteúdo para terceiros, enviar proposta a cliente) só executam com botão `confirm:{action_id}` do mesmo `contact_id`; duplo toque ×2 → **1** execução; botão com mais de 15 min (*proposta*) expira; resposta de texto «sim»/«ok» não confirma (0/20).
- [x] A persona `dono` tem *allowlist* própria de tools (módulos de entrada); um `cliente` que injecte o nome de uma tool do dono obtém erro tipado e linha de auditoria (0 sucessos em 50 tentativas).
- [ ] Se `phone_hmac` do dono coincidir com o número do canal da loja, `owner_channel_wa=false` e o dono só usa o painel web (teste com os dois cenários); sem telefone coincidente, o canal WhatsApp fica activo.
- [x] Política de proactivas no Piloto: resposta ao dono dentro da janela de 24 h é *service message* sem *template*; fora da janela não sai nenhuma mensagem — nem *push* pelo número da loja (`../docs/tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §11.4, regra 2) nem *template* da categoria `marketing` (`CATEGORIAS_DO_PILOTO`), com ou sem opt-in; **0** *templates* em 100 tentativas fora da janela. *(Reescrito por decisão do fundador de 2026-11-18, «Manter as regras»: a letra anterior pedia* push *por* template *com opt-in de marketing e um tecto de 1 por semana e 4 por mês, contra as duas regras.)*
- [ ] Painel web: sessão por OTP e `tenant_id` do cookie assinado (nunca de parâmetro), as mesmas tools/ToolLayer e o mesmo `thread_id` do dono; sessão do tenant A com recurso do tenant B → 404.
- [x] `registry/dono.yaml` passa a validação do arranque (KAM-027); relatório de reaproveitamento ≥ 70% do core (sem excepções); registos sem conteúdo nem telefone; limite de 60 mensagens/hora do dono (*proposta*).

### Detalhes Técnicos

- **Componentes:** CHR, AGR, TLS, TEN, ENT; `onboarding-web` (painel). A persona `dono` é atributo do CHR e **não** uma vertical de canal: `tenant_channels.vertical` mantém-se `vendedor`/`servicos` e a persona decide-se pelo `papel` do remetente (a ratificar no dicionário, §3.2/§3.7).
- **Endpoint do painel:** `OwnerPort` (*proposta*) com a mesma entrada interna do AGR que o webhook; mesma ToolLayer, sem caminho paralelo.
- **Dependências implícitas a ratificar:** KAM-028 (ToolLayer), KAM-015 (envio), KAM-018 (eco/modos), KAM-092 (`tenant.provisioned`), KAM-022 (opt-in).

```sql
ALTER TABLE contacts ADD COLUMN papel text NOT NULL DEFAULT 'cliente' CHECK (papel IN ('cliente','dono'));  -- proposta, KAM-008
CREATE UNIQUE INDEX contacts_um_dono ON contacts (tenant_id) WHERE papel = 'dono';
CREATE TABLE owner_actions (  -- proposta
  action_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, contact_id uuid NOT NULL, tipo text NOT NULL, ref text NOT NULL,
  estado text NOT NULL DEFAULT 'pendente' CHECK (estado IN ('pendente','confirmada','expirada','cancelada')),
  expira_at timestamptz NOT NULL, confirmada_at timestamptz, UNIQUE (tenant_id, tipo, ref));  -- RLS FORCE
```

### Testes Requeridos

- Unit: resolução de persona (matriz papel × tenant × canal), expiração de botão, política de proactivas.
- Integração: saga → `tenant.provisioned` → contacto `dono`; troca de telefone com OTP falso; painel e WhatsApp sobre a mesma tool.
- Isolamento: dono A vs tenant B no CHR e no painel; `kamba_resolver` sem leitura de `owner_actions`.
- **Adversarial:** auto-promoção por texto; troca de SIM simulada (mensagem do número novo sem OTP); replay de botão antigo; remetente igual ao número da loja; token de sessão do painel de outro tenant.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; suite adversarial verde no CI.
- [x] Isolamento de tenant e contacto coberto pelo teste cruzado (ADR-015); `tenant_id` só do contexto.
- [x] Idempotência de `owner_actions` e da criação do `dono` com teste de repetição (ADR-009).
- [x] Telefone nunca em claro em logs, URLs ou eventos; logs sem conteúdo (ADR-010).
- [ ] Opt-in e custo de *push* medidos por tenant (ADR-018); `registry/dono.yaml` com SemVer e eval no gate (KAM-125).
- [ ] Migração reversível; sem segredos; dois revisores (identidade e canal).

### Handoff para Claude Code

```text
És o executor do ticket KAM-118 da KAMBÁ (canal do dono e persona Assistente do Dono).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-118), docs/tecnica/02 §21, docs/tecnica/08 §18, docs/tecnica/evidencia/E5 §4 e specs/01_Engineering_Standards_e_Handoff.md.
Objectivo: o CHR reconhece o contacto papel='dono' no número da loja e encaminha para a persona 'dono'; painel web com as mesmas tools;
botões confirm:{action_id} nas acções sensíveis; mudança de telefone com novo OTP; sem push ao dono no Piloto (decisão de 2026-11-18).
Regras: o papel não muda por texto; tenant_id só do contexto; se o telefone do dono for o número da loja, só painel web; o dono inicia a conversa
(janela de 24 h); sem número da KAMBÁ (D10). Limiares (15 min, 24 h, 60/h, 1 push/semana) são propostas configuráveis.
Não implementes módulos (KAM-119/121/123), billing de módulos (KAM-124) nem aviso por canal alternativo (KAM-115).
Testes: unit, integração, isolamento e adversarial (promoção, SIM swap, replay, sessão cruzada). Migração reversível. PR com o template da §7.
```

### Decisões do executor

- **O papel tem uma porta só, e o texto não chega a ela.** O `contacts.papel` não tem `UPDATE` para papel de serviço nenhum: muda pela `platform.definir_dono(contacto, origem)`, `SECURITY DEFINER`, que só o `kamba_identity` executa, com o tenant do `app.tenant_id` e mais nenhum. A mesma função escreve o `tenants.owner_contact_id` na mesma transacção — a âncora do dono que a revisão `0001` já tinha e que a auto-compra do KAM-097 lê —, pelo que as duas não divergem: têm um escritor. Tranca a linha do tenant (`FOR UPDATE`) antes de ler o dono, e duas trocas concorrentes serializam-se em vez de a segunda se perder. O provisionamento é idempotente e **não troca** um dono existente (23505), salvo se esse dono for uma lápide — apagado ou fundido —, que passa a `cliente`; só a origem `troca_de_telefone` troca um dono vivo, e uma troca sem dono anterior promove e marca a data de mudança.
- **O `INSERT` do `kamba_identity` em `contacts` passa a ser por coluna**, sem `papel` nem `papel_mudou_at`. O `INSERT` de tabela da `0003` concedia as colunas novas sem ninguém o escrever, e um contacto podia nascer `dono` por fora da porta. O `SQL_CRIAR_CONTACTO` já nomeia as colunas e não muda. Na subida, um tenant com `owner_contact_id` escrito e esse contacto activo ganha `papel='dono'`.
- **A persona vai na invocação, e não no `ChannelContext`.** O contexto é do canal e vive 60 s em *cache* para todos os remetentes desse número; a persona é de quem escreve. O CHR lê o papel na transacção que abre a conversa, sobre o contacto já resolvido no tenant do canal, e escreve-o no campo **aditivo e opcional** `agent_invocation.persona` (a v1 admite campos novos aditivos; o AGR lê `cliente` quando falta). O `vertical` não muda: a persona não é uma vertical (dicionário §3.2), e a chave do `AgentRegistry` passa a ser `dono` quando a persona o diz — também na retoma de uma *thread*, pela persona do *checkpoint*. Paga as dívidas 47 e 98.
- **O Assistente do Dono atende qualquer dono, e cada tool fecha-se pelo seu módulo** (decisão do fundador de 2026-11-18, «Servir todos os donos»). O `registry/dono.yaml` não declara módulo: herda o da vertical por onde o dono escreve, e um tenant suspenso, ou sem esse módulo, continua recusado ao dono como ao cliente. A especificação de uma tool ganha o `modulo` que o passo 2 da ToolLayer lê em vez do `ctx.vertical`, e as quatro do catálogo levam `catalogo`. O grafo reaproveita **12 dos 16 nós (75%)** do Vendedor, os mesmos objectos. As tools do dono são o `get_store_info` e as quatro do catálogo do `docs/tecnica/02` §21.3, **declaradas** com credor KAM-119: estão no catálogo da ToolLayer, e por isso um cliente que as peça recebe `TOOL_NOT_ALLOWED` **com** linha de `tool_audit`; o grafo não chama nenhuma delas.
- **O `owner_channel_wa` não é coluna.** Calcula-se com a comparação do KAM-093 (`numeroCoincide`), no espaço de chave da inscrição — o `contacts.phone_hmac` está noutro espaço e não é comparável. Um número da loja ausente ou ilegível dá painel (falha fechada).
- **Os limiares são constantes nomeadas** (*proposta*): 15 min de validade do botão, 24 h de bloqueio depois da troca, 60 mensagens/hora do dono (`AGR_RITMO_DO_DONO_POR_HORA`). Os tectos de *push* da letra anterior do critério 8 caíram com ele: no Piloto não há *push* ao dono.
- **Revisão `0070`**, sobre a `0069` do KAM-195: escrita como `0068` sobre a `0066`, e renumerada na integração, por ser a última do lote a fundir. Emenda **1.112** e **§3.78** do dicionário, e versão **1.9** deste epic.

### Decisões do fundador

| Data | Autor | Pergunta | Decisão |
|---|---|---|---|
| 2026-11-18 | Fundador | O critério 8 pedia *push* por *template* ao dono fora da janela, com opt-in de marketing. O Outbound recusa a categoria `marketing` no Piloto (`CATEGORIAS_DO_PILOTO`), e o `docs/tecnica/01` §11.4 (regra 2) diz que a notificação ao dono nunca usa o número da loja | **«Manter as regras».** O critério 8 reescreve-se para o Piloto: dentro da janela, *service message*; fora dela, nada — nem *push* pelo número da loja nem *template* de `marketing`. A política fica entregue como função pura, por ligar |
| 2026-11-18 | Fundador | O Assistente do Dono exige o módulo `catalogo` (como estava, *proposta*) ou serve todo o dono? Com o `catalogo`, o dono de um tenant sem esse módulo, que o Vendedor atende hoje como cliente, passava a receber `servico_indisponivel` | **«Servir todos os donos».** O Assistente do Dono atende qualquer dono; cada tool fica fechada pelo entitlement do seu módulo, no passo 2 da ToolLayer |

### Verificação dos Critérios de Aceitação

Dez critérios, **cinco marcados**. Cada linha leva o ensaio que a prova; as vazias dizem o que falta e quem o fecha. **Sem LLM pago nem chave real**: o grafo do dono corre com o classificador por regras do Vendedor, e o OTP, o aviso e o envio são portas com *fakes*. A restrição nova (`contacts_um_dono`) ensaia-se **pelo caminho real**: contactos criados como `kamba_identity` e donos pela `definir_dono`, nunca por superutilizador.

Os ensaios: `packages/core-ts/tests/dono.test.ts` e `chr.persona.test.ts` (gate 4), `services/agr/tests/test_dono.py` (39 ensaios) e `golden/dono/v1` (17 casos), `db/tests/test_canal_do_dono_schema.py` (26) e `db/tests_agr/test_owner_actions.py` (9), contra o PostgreSQL.

| Critério | Estado | Evidência nomeada |
|---|---|---|
| 1 | marcado | 200 mensagens sintéticas — dono de A, dono de B, clientes nos dois e o BSUID do dono de A no número de B — com 100% de encaminhamento certo e **0** mensagens do dono de A tratadas como dono em B (`chr.persona.test.ts`, «encaminhamento 100% correcto»). A base falsa **lê o texto da instrução** e filtra pelas igualdades que o `WHERE` nomeia: com o `AND contact_id = $2` apagado, o ensaio dá vermelho (medido). Contra a base, a RLS do `kamba_app` só deixa ler o papel do seu tenant (`test_a_aplicacao_le_o_papel_do_seu_tenant_e_nao_o_de_outro`); a persona não muda o `vertical` («a persona nao muda o `vertical`») |
| 2 | marcado | 20 textos adversariais → **0** escritas e persona `cliente` (`chr.persona.test.ts`, critério 2; e `test_um_sim_por_texto_nao_chama_tool_nenhuma` no grafo). Nenhum papel de aplicação escreve o `papel` (`test_nenhum_papel_de_aplicacao_escreve_o_papel`), o `kamba_identity` não insere um contacto já dono (`test_a_identidade_nao_insere_um_contacto_ja_dono`), só ele executa a porta (`test_so_a_identidade_executa_a_porta`). No máximo um dono: `contacts_um_dono`, com dois clientes e um dono em cada tenant a passar (`test_dois_clientes_no_mesmo_tenant_e_um_dono_em_cada_tenant_passam`) e duas trocas concorrentes a deixar um (`test_duas_trocas_concorrentes_nao_deixam_dois_donos`); sete mutações no `db/mutacoes.py`. **A porta não tem chamador em produção**: o papel não muda por caminho nenhum até o critério 3 ou 4 a ligarem — o que a caixa pede é que não mude por outro |
| 3 | **parcial — caixa vazia** | **O efeito está; o evento não chega.** `efeitoDoProvisionamento`: reentrega 3× pede sempre o mesmo contacto com a origem `provisionamento`, e a porta 3× deixa um dono (`test_o_provisionamento_tres_vezes_deixa_um_dono_sem_data_de_mudanca`); o tenant é o do envelope; outra versão vai para a DLQ; sem telefone legível não há dono (`dono.test.ts`, critério 3). Sem o evento, o remetente é `cliente` (critério 1). **Falta**: ninguém emite `tenant.provisioned` em produção (ninguém chama o `advance_case('es_concluido')`), e o `onboarding_case.phone_enc` não tem adaptador nem KEK que o decifre — sem eles o consumidor não se subscreve. Credor: **KAM-211**, aberto neste PR. **Revisto no KAM-211**: a porta tem adaptador (`definirDonoNaBase`, ensaiado contra a base em `dono.bd.test.ts`), e o resto — o emissor, a cifra e a KEK do `phone_enc` e a subscrição, que é uma revisão de dados — passa ao **KAM-215** |
| 4 | **parcial — caixa vazia** | **A regra está, com portas falsas.** `TrocaDeTelefone`: até o OTP acertar, o número novo é `cliente` e o antigo mantém o papel; o OTP certo move o papel e avisa o número antigo e o e-mail (ganchos `DESTINOS_DO_AVISO` para o KAM-115); o pedido gasta-se; o pedido de um tenant não se verifica de outro (`dono.test.ts`, critério 4). A porta com `troca_de_telefone` despromove o anterior e marca os dois (`test_a_troca_de_telefone_despromove_o_anterior_e_marca_os_dois`), e as acções sensíveis ficam bloqueadas 24 h (`test_depois_da_troca_de_telefone_ha_vinte_e_quatro_horas_de_bloqueio`, `test_depois_da_troca_ha_bloqueio`). **Falta a rota** que liga o OTP do KAM-086 à `TrocaDeTelefone` e o adaptador da porta. Credor: **KAM-211**. **Revisto no KAM-211**: a rota e o adaptador existem e ensaiam-se pelo caminho real (critério «Troca de telefone» do bloco dele); falta montá-los no processo do `onboarding-web`, que não tem base, e é do **KAM-217** |
| 5 | **parcial — caixa vazia** | **A ficha e a confirmação estão; o botão não chega ao AGR.** `propor`/`confirmar` sobre a `owner_actions`: duplo toque → **1** confirmação, também em duas sessões concorrentes (`test_duplo_toque_concorrente_em_duas_sessoes_da_uma_confirmacao`); mais de 15 min expira; outro contacto não confirma; um botão de outro tenant é desconhecido; «sim»/«ok» por texto → 0/20 (`test_vinte_textos_nao_confirmam_nada_nem_tocam_na_base`, `test_vinte_textos_nao_confirmam`). **Falta**: nenhum texto nem id de botão chega ao estado do turno, e ligá-lo é do **KAM-211**; as acções sensíveis em si são do KAM-119, KAM-121 e KAM-123. **Revisto no KAM-211**: o botão chega e confirma pelo caminho CHR → AGR (critério «Botão» do bloco dele, parcial pela mesma razão); a caixa continua vazia porque o que ela pede é que as acções **executem** só com o botão, e nenhuma acção sensível executa ainda — são do KAM-119, KAM-121 e KAM-123 |
| 6 | marcado | 50 tentativas de um `cliente` com o nome de uma tool do dono → **0** sucessos, 50 `TOOL_NOT_ALLOWED` e 50 linhas de `tool_audit` (`test_cinquenta_tentativas_de_um_cliente_dao_zero_sucessos_e_cinquenta_linhas`), todas recusadas **pela lista** e não pelo estado `declarada`, e a mesma tool passa a lista do dono (`test_o_dono_passa_a_lista_e_para_no_estado_declarada`; achado 1 da revisão); nenhuma tool do dono está na lista de um cliente (`test_nenhuma_tool_do_dono_esta_na_lista_de_um_cliente`) |
| 7 | **parcial — caixa vazia** | **A decisão está, com os dois cenários; ninguém a lê.** `canalDoDono`: telefone igual ao número da loja → `owner_channel_wa=false` e painel; diferente → WhatsApp activo; número ausente ou ilegível → painel (`dono.test.ts`, critério 7). **Falta** quem a consuma: o `GET /painel/canal` já lê o canal pelo COM desde o KAM-190 (`CanalPeloCom`, `POST /internal/channel-view`), mas a `VistaDoCanal` não traz telefone nenhum por desenho, e nenhuma tabela guarda o número da loja. Credor: **KAM-211**. **Revisto no KAM-211**: guardar o número da loja é esquema novo, e passa ao **KAM-216** |
| 8 | marcado | **A letra é a do Piloto, reescrita por decisão do fundador de 2026-11-18** («Manter as regras»). `decidirProactiva`: dentro da janela, *service message* sem *template*; fora, `suprimir` com `fora_da_janela`, e 0 *templates* em 100 tentativas; a decisão não tem `template` como desfecho; uma janela que não se leu bem suprime (`dono.test.ts`, critério 8). É uma decisão e não um envio: não está ligada a envio nenhum, porque nenhum caminho manda hoje ao dono uma mensagem que ele não pediu, e o Outbound impõe por conta própria a janela e as `CATEGORIAS_DO_PILOTO` — esta função é a primeira barreira e não a única |
| 9 | não satisfeito — caixa vazia | O painel não ganhou rota nova: a `OwnerPort` (*proposta*) e o mesmo `thread_id` do dono no painel não existem. O que este ticket deixa é a entrada a que ela chega — a persona `dono` no AGR, pela mesma ToolLayer. Credor: **KAM-211**. **Revisto no KAM-211**: a `OwnerPort` precisa de o texto chegar ao AGR e de a resposta voltar à web, e o processo web não tem base nem credencial do AGR; passa ao **KAM-217**. **Revisto no KAM-217**: o processo tem base, e a `OwnerPort` espera pela implementação das decisões do contrato do texto e da saída do AGR, que o fundador tomou a 2026-11-19; passa ao **KAM-226**, com a saída no **KAM-227** |
| 10 | marcado | `registry/dono.yaml` passa a validação do arranque (`test_o_registo_do_dono_passa_a_validacao_do_arranque`); reaproveitamento de 12 nós em 16, **75%**, os mesmos objectos do Vendedor (`test_o_reaproveitamento_e_de_pelo_menos_setenta_por_cento`, `test_os_reutilizados_sao_os_mesmos_objectos_do_vendedor`); nenhum texto do dono leva dígitos (`test_nenhum_texto_do_dono_leva_digitos`) e os módulos novos passam o `log_policy` do gate 4; 60 mensagens/hora do dono, e a 61.ª descartada (`test_o_dono_passa_sessenta_numa_hora_e_a_seguinte_e_descartada`), sem custo para um cliente (`test_um_cliente_nao_paga_a_janela_da_hora`) |

### Verificação da Definition of Done

| Caixa | Estado | Evidência nomeada |
|---|---|---|
| 1 | não satisfeito — caixa vazia | Cinco critérios de dez; a suite adversarial dos marcados está no gate 4 e no gate 8 |
| 2 | marcado | A `owner_actions` com RLS `FORCE` pela `tenant_iso` (`test_a_rls_esta_ligada_e_forcada`), nas três listas do X-05 e com receita nas sementes do isolamento (`_accao_do_dono`); o tenant A não vê nem confirma a ficha de B (`test_o_tenant_a_nao_ve_nem_confirma_a_ficha_de_b`); o `kamba_resolver` não lê as fichas (`test_o_resolvedor_nao_le_as_fichas`). A porta lê o tenant só do `app.tenant_id` (`test_sem_app_tenant_id_a_porta_recusa`, `test_o_contacto_de_outro_tenant_nao_se_encontra`) |
| 3 | marcado | Propor três vezes dá uma ficha (`test_propor_tres_vezes_da_uma_linha`, `test_a_mesma_accao_e_uma_ficha`); o provisionamento três vezes dá um dono (`test_o_provisionamento_tres_vezes_deixa_um_dono_sem_data_de_mudanca`) |
| 4 | marcado | A `owner_actions` não tem telefone nem conteúdo; a persona é um valor de lista fechada; o erro de telefone ilegível não leva o identificador (`dono.test.ts`, critério 3); os textos do dono não levam dígitos; o `log_policy` do gate 4 passa sobre os módulos novos |
| 5 | **parcial — caixa vazia** | O `registry/dono.yaml` tem SemVer e dataset próprio (`golden/dono/v1`) no `registry/gates.yaml`, como **aviso** com credor KAM-125. O opt-in e o custo de *push* por tenant não têm o que medir: no Piloto não há *push* ao dono (critério 8, decisão do fundador de 2026-11-18) |
| 6 | **parcial — caixa vazia** | Migração reversível com ensaio de descida (`test_desce_e_volta`); nenhum segredo, nenhuma dependência nova. **Dois revisores** (identidade e canal): a revisão adversarial deste PR é uma, e a segunda é nomeação do fundador |

### Verificação da revisão adversarial

Uma revisão independente, que recebeu o diff e os critérios da `main` e não o raciocínio do ramo, com mutações numa cópia da árvore e reproduções próprias. **Nenhum achado bloqueava.** Os confirmados que eram deste ticket estão fechados, cada um com um ensaio e, quando a barreira é da base, uma mutação no `db/mutacoes.py`; os outros ficam escritos com o credor. Antes dela, a medição de mutações já tinha apanhado o duplo do CHR: reconhecia a leitura do papel por igualdade com o `SQL_PAPEL` importado do código, e ficava verde com o `AND contact_id = $2` apagado.

| # | Severidade | O que estava errado | Como se fechou |
|---|---|---|---|
| 1 | deve corrigir | O ensaio do critério 6 não media a lista: as quatro tools do dono estão `declaradas`, e o passo 1 recusava-as a todos — ao dono também — com o mesmo código. Com a comparação com o `allowed` apagada, ficava verde | O ensaio afirma o motivo da recusa (a lista, e não o estado), e `test_o_dono_passa_a_lista_e_para_no_estado_declarada` prova que a lista do `dono.yaml` deixa passar. A mutação da revisão é agora apanhada (medido) |
| 2 | deve corrigir → aceite, escrito | O `persona` passou a nome conhecido, e o *gate* 3b deixou de recusar uma coluna `tenant_channels.persona` — o sinónimo de vertical que o §3.2 recusa | O `canon_lint` aceita a última parte de qualquer nome qualificado como coluna de qualquer tabela (o `vertical` já o era), pelo que qualificar o nome não chega: fechar é mudar o critério do linter, que não é deste ticket. A linha do §3.78 e o ensaio do `canon_lint` dizem-no por escrito |
| 3 | deve corrigir → **decidida pelo fundador** | O preenchimento da `0070` torna `dono` o `owner_contact_id` de cada tenant existente, e o `dono.yaml` activava-se pelo módulo `catalogo`: o dono de um tenant sem esse módulo, que hoje o Vendedor atende como cliente, passava a receber `servico_indisponivel` | **Decisão do fundador de 2026-11-18, «Servir todos os donos».** O `dono.yaml` herda o módulo do canal (`test_o_dono_de_um_tenant_sem_catalogo_e_atendido`, `test_o_entitlement_do_dono_e_o_do_canal`, e só a persona do dono o pode omitir: `test_so_a_persona_do_dono_pode_omitir_o_modulo`); as tools do catálogo fecham-se pelo `catalogo` no passo 2 — sem ele recusam com `ENTITLEMENT_DENIED`, com ele abrem (`TestModulosDasToolsDoDono`; com o passo 2 a ler o `ctx.vertical`, quatro vermelhos, medido) |
| 4 | menor → **KAM-211** | A retoma de uma *thread* usa a persona do *checkpoint*: depois de uma troca de telefone, o *handoff* interrompido do dono antigo retoma no grafo do dono. O turno seguinte corrige-o | Hoje o grafo do dono só chama o `get_store_info`. Passa a escalada de privilégio quando o KAM-119 ligar tools de escrita, e por isso é critério do KAM-211, que liga a troca. **Fechado no KAM-211**: a retoma lê o papel actual (critério «Retoma» do bloco dele) |
| 5 | menor | Um dono apagado ou fundido prendia o lugar: a lápide ficava `dono`, o `#fundir` não leva o papel, e a saga recusava com `23505` para sempre | A porta passa a lápide a `cliente` e deixa entrar o provisionamento seguinte (`test_um_dono_apagado_ou_fundido_nao_prende_o_lugar`, e a mutação «a lápide prende o lugar do dono») |
| 6 | menor — aberto | O `INSERT` da `owner_actions` aceita qualquer `expira_at` e o contacto de um cliente: o prazo de 15 min e «só o dono propõe» vivem no `propor` | **Fica escrito**: o `kamba_app` é quem serve o turno, e a ficha só se confirma pelo `confirmar`, que relê o papel. Um `CHECK` de prazo repetia na base uma constante *proposta* |
| 7 | menor — aberto | O `propor` devolve a ficha antiga de um `(tipo, ref)` repetido, seja qual for o estado ou o dono dela | **Fica escrito**: a `ref` é de quem chama, e cada proposta nova leva uma `ref` nova. Os chamadores são o KAM-119, o KAM-121 e o KAM-123 |
| 8 | menor | O `troca.ts` citava uma `platform.trocar_dono` que não existe; o §3.24 dizia «os quatro» tectos, e são cinco | Os dois textos corrigidos |
| 9 | observação | O ensaio dos 20 textos prova uma propriedade estrutural (o CHR não tem caminho de escrita), e o predicado `tenant_id` do `SQL_PAPEL` não se mede na base falsa | O peso está nos ensaios de privilégios da base (critério 2) e na RLS do `kamba_app` (critério 1), que a revisão não correu e o gate 8 corre |

---

## KAM-119 — Vertical `catalogo`: fotografar, completar e publicar produtos pelo dono

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-118, KAM-049, KAM-043 |
| Bloqueia | KAM-125, KAM-127, KAM-202 |
| Responsável sugerido | Engenheiro de Comércio com Engenheiro de Runtime/IA |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§21.3), `../docs/tecnica/03_Core_Comercio_Medusa.md` (§8, §17), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` (§7), `specs/EPIC-04_Core_Comercio.md` (KAM-049), ADR-007, ADR-020 |

### Contexto

O pipeline foto → rascunho (KAM-049) já existe como serviço interno e deixou deliberadamente em aberto o canal do dono. KAM-119 é a **camada conversacional** sobre ele: o dono manda fotos pelo canal do dono (KAM-118), recebe perguntas de completude, confirma e publica. Preço e stock continuam a viver só no Registo (ADR-007); o texto gerado é rascunho até o dono confirmar; a categoria passa pelo screening (KAM-088). Fotos só vêm do dono: não há pesquisa de imagens na web (E5 §7, risco de obra de terceiros). É o único módulo que **não se corta** (pré-requisito do onboarding, ADR-020); por isso é P0.

### Objectivo

Registar a vertical `catalogo` (`registry/catalogo.yaml`) com as 4 tools do §21.3, ligadas a `catalog_ingestions` e a `publishProduct`, de modo que o dono publique um produto em poucos turnos sem nunca originar preço ou stock pelo modelo.

### Critérios de Aceitação

- [ ] Tools registadas com classe: `create_product_draft` (write), `ask_missing_fields` (read), `publish_product` (write, confirmação), `get_catalog_status` (read); uma foto enviada pelo dono (WhatsApp ou painel) cria **1** rascunho; reenviar o mesmo `media_id` não cria outro (idempotência de KAM-049 reaproveitada).
- [ ] Resposta de recepção ≤ 3 s e rascunho com resumo ≤ 25 s p95 (*proposta*, margem sobre o alvo de 20 s de KAM-049), com «estou a preparar» enquanto corre.
- [ ] Preço e stock saem **só** do dono: parser determinístico de PT-AO («45 mil», «45k», «1.500») com eco «45.000 Kz?» e botões; em 100 frases de preço, **0** valores gravados sem eco correcto (as ambíguas voltam a perguntar); o modelo nunca escreve `preco_minor`; sem preço, o dono escolhe `preco_tipo` (`fixo`, `a_partir_de`, `sob_consulta`).
- [ ] `ask_missing_fields` faz ≤ 3 perguntas por mensagem e preço/stock um de cada vez (limites de KAM-049); o dono pode responder por texto ou voz (STT, se activo) e por lote: 10 fotos em 60 s → 10 rascunhos independentes, sem mistura de respostas.
- [ ] `publish_product` exige botão `confirm:{ingestion_id}` e `assert_publishable` (KAM-088) válido para a versão corrente da política; duplo toque ×2 → **1** produto; nos 100 casos canónicos de categoria bloqueada → **0** publicações e mensagem de recusa sem detalhe interno.
- [ ] Texto de descrição/legenda enviado pelo dono ou lido na foto é dado não confiável: 10 casos de injecção («publica a 1 Kz», «ignora as regras») → rascunho e fluxo inalterados.
- [ ] Não existe nenhuma tool com egress para pesquisa de imagens ou páginas de terceiros (lint do registo e teste de rede); toda a descrição tem `confirmado_por_dono=true` antes de publicar.
- [ ] Após o rascunho, se o entitlement `foto` está activo, oferece «melhorar foto» (KAM-120) por uma porta `ImageEnhancePort` (*proposta*); sem `foto`, o fluxo segue sem erro com adaptador nulo.
- [ ] `get_catalog_status` devolve contagens (rascunhos, publicados, bloqueados) como *facts*; qualquer número da resposta existe no resultado da tool (0 divergências em 50 casos).
- [ ] Métricas por tenant: tempo da 1.ª foto ao 1.º produto publicado (mediana ≤ 10 min de actividade do dono, *proposta*), % publicados sem correcção, custo por produto ≤ US$ 0,02 (herdado de KAM-049), entitlement `catalogo` verificado por TEN.

### Detalhes Técnicos

- **Componentes:** ENT, COM (Catálogo AI), AGR, TLS, MED, STO, GOV. Reutiliza `catalog_ingestions` (`../docs/tecnica/03` §8.3) e o API interno de KAM-049; não duplica a lógica de extracção.
- **Grafo:** mínimo (`ingest → classify → tools → compose → validate → send`) com `confirm_gate` genérico por `ingestion_id`; botão `confirm:{ingestion_id}` (*proposta*; o dicionário só tem `cart_id` e `hold_id`).
- **Registo:** `catalogo.yaml` SemVer 1.0.0; sem flags de vertical no core; reaproveitamento medido como em KAM-039.
- **Credor do KAM-049 (critérios 1 e 2 de lá, caixas vazias):** o KAM-049 entregou o pipeline como biblioteca, [`kamba_core.catalogo`](../libs/py-core/src/kamba_core/catalogo/pipeline.py), com as portas medidas por *fakes*; **este ticket recebe a montagem real**: a `FonteDeMedia` sobre o MED (KAM-020), o `Descodificador` de imagem, a ponte Python→TypeScript para o `screen` do KAM-088 (até lá a `ScreeningPorLigar` bloqueia tudo) e a `PortaDoRegisto` sobre o COM (`upsertProductDraft`/`publishProduct`). A rota interna e o grafo que expõem o pipeline são também deste ticket (decisão registada no bloco do KAM-049).

### Testes Requeridos

- Unit: parser de preços PT-AO, perfis de completude, máquina de estados do rascunho.
- Integração: foto → rascunho → perguntas → confirmação → produto no Registo, com visão *fake*; falha de `assert_publishable` fail-closed; lote de 10 fotos.
- Isolamento: dono A não lista nem publica rascunhos do tenant B; cliente não invoca tools do catálogo.
- **Adversarial:** categoria disfarçada («água ardente»), injecção na legenda, preço em extenso e em kz/USD, foto repetida, botão antigo.
- Golden `dono_catalogo` (KAM-125).

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; suites verdes no CI.
- [ ] Isolamento de tenant (ADR-015); `tenant_id` do estado; RLS `FORCE` em toda a tabela nova.
- [ ] Idempotência de publicação e de rascunho com teste de repetição (ADR-009).
- [ ] Números só de tools: preço/stock só por confirmação do dono (ADR-007).
- [ ] Conteúdo para terceiros: nada publicado sem aprovação do dono e sem screening (ADR-020).
- [ ] Custo por produto medido (ADR-018); eval-gate verde para prompt/grafo; dois revisores (toca screening e dados pessoais).

### Handoff para Claude Code

```text
És o executor do ticket KAM-119 da KAMBÁ (vertical catalogo).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-119), specs/EPIC-04_Core_Comercio.md (KAM-049), docs/tecnica/03 §8 e §17 e docs/tecnica/02 §21.3.
Objectivo: registry/catalogo.yaml com create_product_draft, ask_missing_fields, publish_product (confirmação) e get_catalog_status sobre catalog_ingestions.
Regras: o modelo nunca origina preço ou stock (parser determinístico + eco + botão); publicar exige confirm:{ingestion_id} e assert_publishable (KAM-088);
fotos só do dono, sem pesquisa de imagens; texto de fotos e descrições é dado não confiável; reaproveita KAM-049, não o reescrevas.
Não implementes foto AI (KAM-120), canal do dono (KAM-118) nem o golden (KAM-125). Testes: unit, integração, isolamento, adversarial.
```

---

## KAM-120 — Foto de produtos AI: ImageProvider, fundo limpo, correcção de luz e variações

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-049, KAM-011, KAM-069 |
| Bloqueia | KAM-122, KAM-124, KAM-127 |
| Responsável sugerido | Engenheiro de Runtime/IA (MED) com Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/03_Core_Comercio_Medusa.md` (§17), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` (§1, §6, bloqueios B2, B3, B6, B7), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§2, requisitos 2 e 8), `../docs/tecnica/08_Seguranca_Conformidade.md` (§18), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§21), ADR-008, ADR-014, ADR-018, ADR-020 |

### Contexto

A Foto AI do Piloto é uma versão **reduzida**: recorte/fundo simples e correcção de luz básica; variações generativas («lifestyle») só como opção etiquetada. Nenhum fornecedor é «o melhor» comprovado (E5): qualidade em fotos angolanas é **NÃO VERIFICADO**, daí o *bake-off* com 2–3 candidatos (Bria, Photoroom; Gemini só para artes). **Excluídos:** Black Forest Labs (licença perpétua de treino com inputs e outputs) e remove.bg (passa para Leonardo.Ai a 2026-12-01). A Photoroom tem contradição documentada sobre treino em planos de API; Bria não esclarece treino. Fotos com pessoas são dados pessoais (Lei 22/11, «imagem e som») e enviá-las para os EUA é, em princípio, transferência (INDÍCIO, a confirmar por parecer): exige filtro local, destino registado e carta do fornecedor. Preços de referência por imagem (E5, a **reverificar** antes de contratar): Bria recorte ≈ 0,018 USD, Photoroom Basic ≈ 0,02 USD e Plus ≈ 0,10 USD.

### Objectivo

Entregar a interface `ImageProvider`, a tool `enhance_image`, o gate local de minimização de imagem (MED), a tabela `image_jobs`, o pipeline assíncrono e o *bake-off* que escolhe fornecedor primário e de contingência, sem nunca substituir o original.

### Critérios de Aceitação

- [ ] `ImageProvider.enhance(imageRef, opts) → {versaoRef, custoUsd, provider, latenciaMs}` com operações `cutout`, `fundo_simples`, `luz_basica` e `variacao_lifestyle` (desligada por omissão; etiquetada «gerada por IA»); adaptadores intermutáveis sem alterar o ToolLayer.
- [ ] `enhance_image` (write) cria sempre uma **nova versão** ligada ao original; após 100 trabalhos o `sha256` de todos os originais é idêntico; o dono escolhe a versão por botão e o original é recuperável em 100% dos casos.
- [ ] **Gate local de rostos e matrículas** (Angola, sem chamada externa) antes de qualquer envio: num conjunto de teste de ≥ 50 imagens com rostos e ≥ 30 com matrículas (sintéticas ou autorizadas), **100%** são desfocadas/recortadas ou rejeitadas com pedido de outra foto, e o *stub* de egress recebe **0 bytes** dessas imagens; falsos positivos medidos e reportados (alvo ≤ 15%, *proposta*).
- [ ] EXIF/GPS removido e imagem reduzida a ≤ 2.048 px no lado maior (*proposta*) antes do envio; verificação em bytes (0 tags EXIF no corpo do pedido).
- [ ] Sem destino `imagem:<provider>` em `allowed_destinations` com `apd_ref` (KAM-069) a chamada falha fechada e o trabalho fica `bloqueada_gate`; só o *tier* pago é aceite (configuração `tier=pago` obrigatória; chave de *tier* gratuito rejeitada); em *staging* só imagens sintéticas.
- [x] Lista de recusa em configuração: BFL e remove.bg não podem ser activados (teste de validação do arranque falha se aparecerem).
- [ ] *Bake-off* com ≥ 30 fotos reais autorizadas pelas PMEs e ≥ 2 fornecedores; registo (`../docs/tecnica/evidencia/validacao/`) de utilizável (≥ 80% por 2 avaliadores, *proposta*), alteração indevida do produto (≤ 5%, *proposta*), latência p50/p95, custo por imagem final; decisão com dono e data (primário + contingência).
- [ ] Antes de **qualquer foto real**, carta escrita de cada fornecedor activo sobre «sem treino com as imagens», retenção e região de processamento arquivada (resolve a contradição da Photoroom); sem carta, o fornecedor só recebe imagens sintéticas (*flag* `real_data_ok=false`).
- [ ] Pipeline assíncrono (BullMQ): confirmação «a preparar» ≤ 3 s; resultado p95 ≤ 60 s; *timeout* de 45 s → contingência 1×; falha final avisa o dono e mantém o original; mesma chave de idempotência ×2 → **1** trabalho e **1** cobrança.
- [ ] Resultado descarregado de imediato para o STO e apagado no fornecedor onde a API o permita; `image_jobs.custo_minor` por trabalho; `imagens_mes` aplicado por TEN (0 trabalhos acima do limite); 1.ª utilização mostra e regista o aviso «esta foto vai ser processada por serviço de IA no estrangeiro».

### Detalhes Técnicos

- **Componentes:** MED, STO, LLM (apenas visão para qualidade, via KAM-030), TEN, ENT. Detector de rostos/matrículas *open-source* com licença permitida pelo gate de SCA e a correr no host (CPU, sem GPU, `../docs/tecnica/09` §21.1); medir falsos negativos no golden de imagens.
- **Fornecedor no inventário de subprocessadores** (KAM-069, ADR-008) com região e estado do `apd_ref`; DPA da Bria só em Enterprise (E5): negociar. Variações generativas: tratamento «noutro país» do Gemini só com destino autorizado.
- **Marcas:** não remover SynthID/metadados; versões geradas levam `gerado_por_ia=true`.

```sql
CREATE TABLE image_jobs (  -- proposta (../docs/tecnica/03 §17); RLS FORCE
  image_job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, origem_asset_id uuid NOT NULL, versao_asset_id uuid,
  operacao text NOT NULL, provider text NOT NULL, estado text NOT NULL CHECK (estado IN ('pendente','a_processar','concluido','bloqueada_gate','falhado')),
  idempotency_key text NOT NULL, custo_minor bigint, criado_at timestamptz NOT NULL DEFAULT now(), UNIQUE (tenant_id, idempotency_key));
```

### Testes Requeridos

- Unit: remoção de EXIF, redimensionamento, política de destinos, lista de recusa, idempotência.
- Integração: pipeline com `ImageProvider` falso (sucesso, *timeout*, contingência); gate fail-closed sem `apd_ref`.
- Isolamento: asset de um tenant inacessível a outro; URL assinada de outro tenant → 403.
- **Adversarial:** imagens com rostos, matrículas, documentos e ecrãs; EXIF com GPS; imagem enorme; texto injectado na foto; fornecedor devolve imagem diferente do produto.
- Bake-off documentado e repetível por *script*.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; decisão de fornecedor no registo e item NÃO VERIFICADO de E5 (B7) actualizado.
- [ ] Privacidade: nenhuma imagem pessoal a destino sem filtro e sem `apd_ref` (ADR-008); logs sem conteúdo (ADR-010).
- [ ] Idempotência com teste de repetição; isolamento de tenant (ADR-015).
- [ ] Custo por imagem e por tenant medido (ADR-018); conteúdo marcado como gerado por IA onde aplicável.
- [ ] Migração reversível; sem segredos de fornecedores no repositório; lockfile e licenças limpos; dois revisores (dados pessoais).

### Handoff para Claude Code

```text
És o executor do ticket KAM-120 da KAMBÁ (Foto de produtos AI).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-120), docs/tecnica/03 §17, docs/tecnica/evidencia/E5 §1 e §6 e specs/01_Engineering_Standards_e_Handoff.md.
Objectivo: ImageProvider + enhance_image + image_jobs + gate local de rostos/matrículas + EXIF + pipeline assíncrono + harness do bake-off.
Regras: original nunca substituído; nada sai sem destino com apd_ref; BFL e remove.bg excluídos; só tier pago; sem fotos reais antes da carta de não-treino;
preços de fornecedores são a verificar; qualidade em Angola NÃO VERIFICADA (mede, não assumas). Não implementes artes sociais (KAM-122) nem metering consolidado (KAM-124).
Testes: unit, integração, isolamento, adversarial e bake-off com dados sintéticos até haver cartas. Migração reversível. PR com o template da §7.
```

### Decisões do executor

- **Uma biblioteca do `kamba-core`, e não um serviço**, pela razão do KAM-049: a porta de destinos (KAM-069), a limpeza de EXIF (KAM-049) e o STO (KAM-011) são Python. O pacote é [`kamba_core.foto`](../libs/py-core/src/kamba_core/foto/__init__.py); o `enhance_image` (cria o trabalho, sem rede para fora) e o `processar` (o trabalhador) são as duas entradas. O registo da tool nas verticais do dono é do **KAM-119** e do **KAM-122**; a ligação da fila ao `processar` é do **KAM-194** (a ponte fila → consumidor Python).
- **O adaptador recebe bytes, e não a referência.** O contrato `imageRef → versaoRef` do critério 1 é o do `enhance_image`; uma referência entregue ao fornecedor deixava-o ir buscar o original, e a minimização passava a ser opcional.
- **Finalidade `imagem` nova** no domínio de `tenant_destinations.purpose` (catorze), e não a `visao`: notificar a APD de um tratamento com o nome de outro é o defeito que o ADR-008 existe para impedir. A revisão é a `0054`, o número da integração do lote (sobre a `0053` do KAM-198).
- **Rostos e matrículas recusam, não desfocam.** O critério aceita as duas; desfocar é reescrever pixeis, e uma desfocagem que falhe deixa o rosto sair.
- **`custo_usd numeric(10,6)` e não `custo_minor`**: um recorte custa 0,018 USD (E5) e não cabe em cêntimos inteiros; o precedente é o `catalog_ingestions.custo_llm_usd`. **Devolvida a quem escreveu os critérios 10 deste bloco e 4 do KAM-124**, que também lê `image_jobs.custo_minor`.

### Verificação dos Critérios de Aceitação

Dez critérios, **um marcado**. Cada linha leva o ensaio que a prova; as vazias dizem o que falta e quem o fecha. **Sem fornecedor pago nem chave real**: o `ImageProvider`, o detector local e o redimensionador são portas, e os ensaios correm-nas com *fakes* que registam o que recebem — o *stub* de egress é a lista de bytes que chegou ao fornecedor falso, e não o que o serviço diz que mandou. A porta de destinos corre **também a real** do KAM-069.

Os ensaios: `libs/py-core/tests/test_foto.py` (unidade e integração com portas falsas) e `db/tests/test_foto_schema.py` (gate 8, contra o PostgreSQL).

| Critério | Estado | Evidência nomeada |
|---|---|---|
| 1 | **parcial — caixa vazia** | **A interface e a intermutabilidade estão; nenhum adaptador real existe, e a assinatura diverge da letra por escrito.** `ImageProvider.enhance(imagem, opcoes) → Melhoria` com as quatro operações (`test_as_operacoes_e_o_timeout`); a `variacao_lifestyle` desligada por omissão (`test_variacao_desligada_por_omissao`) e, ligada, com `gerado_por_ia` e a etiqueta «gerada por IA» (`test_variacao_ligada_e_etiquetada_gerada_por_ia`); o primário e a contingência trocam sem mudar o `enhance_image` (`test_o_gate_corre_para_cada_fornecedor_e_so_os_autorizados_recebem`, `test_timeout_passa_a_contingencia_uma_vez`). A leitura (bytes e não `imageRef`, decisão acima) volta a quem escreveu o critério. Os adaptadores reais nascem com o *bake-off* (critério 7) |
| 2 | **parcial — caixa vazia** | **O original nunca muda e é recuperável; o botão é do canal.** `test_cem_trabalhos_deixam_os_originais_intactos_e_recuperaveis`: 100 trabalhos, o `sha256` de cada original igual antes e depois e igual ao que o `original()` devolve; a versão numa chave nova da classe `foto` (`test_a_versao_vai_para_o_sto_e_e_apagada_no_fornecedor`); `escolher` põe e tira a escolha (`test_o_dono_escolhe_a_versao_e_pode_voltar_ao_original`) e só um `concluido` se escolhe (`image_jobs_escolhida_ck`), uma versão por original (`image_jobs_escolhida_uq`; `test_escolher_outra_versao_desmarca_a_anterior`, `test_so_uma_versao_escolhida_por_original`). **O botão é do KAM-119** (a vertical `catalogo`), que mostra as duas e chama o `escolher` |
| 3 | **parcial — caixa vazia** | **O *gate* respeita o detector; o detector não existe.** Com o detector falso: 50 imagens com rostos, 30 com matrículas (reduzidas antes), 5 documentos e 5 ecrãs → 100% `falhado`/`dados_pessoais` com pedido de outra foto e **0 bytes** no *stub* de egress (`test_cinquenta_rostos_e_trinta_matriculas_nao_saem`); detector em baixo (`test_detector_em_baixo_bloqueia_e_nao_deixa_passar`) ou com resposta ilegível (`test_detector_com_resposta_ilegivel_bloqueia`: `None`, um `dict`, um objecto) → `bloqueada_gate`, nunca passagem; o detector vê os bytes que vão sair e não o original (`test_o_detector_ve_os_bytes_que_vao_sair`); o *bake-off* passa pelo mesmo detector (`test_a_foto_sai_minimizada_e_a_com_rosto_nao_sai`). **Falta o detector *open-source* com licença, a correr no anfitrião, e a medição de falsos negativos e positivos** num conjunto sintético — entra pelo inventário do `supply_chain`. Credor: **ticket a abrir** na integração do lote (biblioteca de imagem e detector local, com o conjunto de imagens sintéticas) |
| 4 | **parcial — caixa vazia** | **A verificação em bytes está; a redução precisa da biblioteca de imagem do critério 3.** EXIF, GPS, XMP, IPTC, comentário e cauda fora, e o corpo de cada pedido sem metadados e com lado ≤ 2048 (`test_o_corpo_do_pedido_nao_leva_exif_e_cabe_no_lado_maximo`, três imagens, uma de 6000 × 4000; e o mesmo no *bake-off*); um redimensionador que não reduz ou que devolve EXIF não deixa sair (`test_redimensionador_que_nao_reduz_ou_falha_bloqueia`, `test_redimensionador_que_devolve_exif_e_limpo_outra_vez`); bomba de descompressão recusada pelo cabeçalho (`test_bomba_de_descompressao_e_recusada_pelo_cabecalho`). **O `Redimensionador` de produção não existe**: sem ele, uma foto maior do que 2048 px fica `bloqueada_gate` e não sai. Mesmo credor do critério 3 |
| 5 | **parcial — caixa vazia** | Fail-closed: sem destino `imagem` com `apd_ref`, `bloqueada_gate` e zero bytes, com a porta **real** do KAM-069 sobre cinco conjuntos de linhas (`test_com_a_porta_real_do_kam_069_so_autorizado_com_apd_ref_deixa_sair`), uma porta que rebenta (`test_porta_de_destinos_que_rebenta_e_bloqueio`) e um destino de outra finalidade (`test_destino_de_outra_finalidade_nao_serve`); o *bake-off* recusa-se inteiro sem destino (`test_sem_destino_recusa_o_bakeoff_inteiro`); fora de `prod`, só sintéticas (`test_fora_de_prod_so_imagens_sinteticas`), e **em `prod` a declaração «sintética» não vale** (`test_em_prod_a_declaracao_sintetica_nao_salta_a_carta`); o arranque recusa `tier` ≠ `pago` (`test_so_o_tier_pago`). **«Chave de *tier* gratuito rejeitada» lê-se como *tier* declarado**: reconhecer uma chave gratuita pela forma é NÃO VERIFICADO (nenhum candidato publica a diferença). A leitura volta a quem escreveu o critério. E a declaração «sintética» fora de `prod` vem de quem compõe o serviço: **o KAM-119 e o KAM-122 não a expõem ao modelo** |
| 6 | marcado | A recusa procura as marcas como **subcadeia** do nome normalizado: `test_bfl_e_remove_bg_nao_arrancam_em_nenhuma_grafia` (oito grafias) e `test_lista_de_recusa_por_subcadeia` (`remove-bg-api`, `remove-bg-v2`, `black-forest`, `blackforest`, `black-forest-labs-api`, que a primeira versão deixava passar — achado da revisão adversarial); `test_o_arranque_do_servico_recusa_a_lista_de_recusa`: o `ServicoDeFoto` não se constrói com um deles na configuração, e o *bake-off* também não corre (`test_lista_de_recusa_tier_e_carta_recusam`) |
| 7 | não satisfeito — caixa vazia | **Entregue o *harness*, não o *bake-off*.** `kamba_core.foto.bakeoff`: `correr` **pelas mesmas barreiras do serviço** (configuração, *gate* `imagem` por fornecedor, carta para fotos reais, só sintéticas fora de `prod`, minimização de cada foto — `TestBakeoffPelasBarreiras`), `resumir` (utilizável pelos **dois** avaliadores, alteração indevida, p50/p95 por *nearest-rank*, custo por imagem final incluindo falhas), `suficiente` (≥ 30 fotos, ≥ 2 fornecedores) e `tabela` para o registo (`TestBakeoff`). As fotos reais autorizadas, os fornecedores contratados e a decisão com dono e data são do **fundador**, depois das cartas do critério 8 |
| 8 | não satisfeito — caixa vazia | O código está: `real_data_ok` falso por omissão, e uma imagem real só vai a fornecedores com a carta (`test_sem_carta_o_fornecedor_so_recebe_sinteticas`, `test_lista_de_recusa_tier_e_carta_recusam`). **As cartas não existem**: pedi-las é contactar fornecedores, que este ticket não faz. Credor: o **fundador** |
| 9 | **parcial — caixa vazia** | Medido com portas falsas: o `enhance_image` não chama o fornecedor e devolve `pendente` (`test_o_pedido_nao_chama_o_fornecedor_e_fica_a_preparar`); o serviço pede 45 s ao adaptador **e mede-os ele próprio** — uma resposta depois dos 45 s conta como *timeout*, paga-se e passa à contingência (`test_o_servico_pede_45_s_e_mede_o_timeout_ele_proprio`), **uma** vez (`test_timeout_passa_a_contingencia_uma_vez`); falha final avisa o dono e mantém o original (`test_falha_final_avisa_o_dono_mantem_o_original_e_soma_o_custo`); a mesma chave × 2 → 1 trabalho, 1 consumo de `imagens_mes` e 1 chamada ao fornecedor (`test_a_mesma_chave_duas_vezes_e_um_trabalho_e_uma_cobranca`), também pelo `RepositorioDbapi` contra a base (`TestRepositorioNaBase`); dois trabalhadores no mesmo `pendente` → só um chama o fornecedor (`test_dois_trabalhadores_no_pendente_so_um_chama_o_fornecedor`); um `a_processar` não volta a ser chamado antes de `PRESO_APOS` (5 min, *proposta*: `test_um_a_processar_nao_volta_a_chamar_o_fornecedor`, `test_recuperar_so_depois_de_preso`). **Falta a fila e a pilha**: ≤ 3 s e p95 ≤ 60 s medem-se com a ponte BullMQ → Python, que é o **KAM-194**. E uma nota para quem medir: com *timeout* no primário, 45 s + a contingência passam dos 60 s; o p95 só cabe se o *timeout* for raro |
| 10 | **parcial — caixa vazia** | Resultado para o STO de imediato e apagado no fornecedor quando há referência (`test_a_versao_vai_para_o_sto_e_e_apagada_no_fornecedor`; uma API que não deixa apagar não falha o trabalho); 0 trabalhos acima de `imagens_mes` (`test_acima_do_limite_nao_nasce_trabalho`, com a semântica idempotente do TEN; o adaptador `QuotaSobreTen` chama o `consume_limit` com a chave `imagens_mes`, `test_a_quota_e_o_imagens_mes_do_ten_com_a_chave_do_pedido`), e um pedido inválido não gasta quota (`test_pedido_invalido_nao_gasta_quota`); o aviso da primeira utilização mostrado e registado em `aviso_at`, uma vez por tenant (`test_o_aviso_da_primeira_utilizacao_mostra_se_e_regista_se_uma_vez`). **O custo por trabalho é `custo_usd` e não `custo_minor`** (decisão acima, devolvida); a consolidação por módulo é do KAM-124 |

### Verificação da Definition of Done

| Caixa | Estado | Evidência nomeada |
|---|---|---|
| 1 | não satisfeito — caixa vazia | Um critério de dez; a decisão de fornecedor e o B7 do E5 esperam pelo *bake-off* (critério 7) |
| 2 | **parcial — caixa vazia** | Nenhuma imagem sai sem minimização e sem destino `imagem` com `apd_ref` (critérios 3, 4 e 5, e a entrada do `lint_arch` que exige o `.autorizar(` no `servico.py`); **sem conteúdo em registos**: o pacote não regista nada. Fica vazia enquanto o detector real não existir (critério 3) |
| 3 | **parcial — caixa vazia** | Idempotência: critério 9. Isolamento: `test_outro_tenant_nao_le_o_trabalho`, `test_outro_tenant_nao_le_pela_porta` (o `RepositorioDbapi` contra a base) e `test_origem_de_outro_tenant_e_recusada` aqui, RLS `FORCE` e as listas do X-05 em `db/tests_isolamento/`. A URL assinada de outro tenant → 403 é do STO (KAM-011) e não tem rota neste ticket |
| 4 | **parcial — caixa vazia** | Custo por trabalho em `custo_usd`, falhas incluídas; marca «gerada por IA» na coluna gerada `gerado_por_ia`. O custo por tenant e por módulo é do KAM-124 |
| 5 | **parcial — caixa vazia** | Migração reversível com ensaio de descida (`db/tests/test_foto_schema.py`), nenhuma dependência nova, nenhum segredo. **Dois revisores** (dados pessoais): a revisão adversarial deste PR é uma, e a segunda é nomeação do fundador |

### Verificação da revisão adversarial

Uma revisão independente, que recebeu o diff e os critérios da `main` e não o raciocínio do ramo, com **39 mutações** sobre uma cópia do `kamba_core.foto` (29 mortas, 10 sobreviventes) e reproduções próprias. **Um achado bloqueava**; todos os confirmados estão fechados, e as **15** mutações que interessavam foram medidas outra vez depois da correcção — todas mortas. Antes dela, a medição do gate 8 já tinha apanhado dois defeitos da revisão `0054`.

| # | Severidade | O que estava errado | Como se fechou |
|---|---|---|---|
| G1 | bloqueia | O `image_jobs_motivo_ck` deixava entrar `bloqueada_gate` ou `falhado` **sem motivo**: `NULL IN (…)` é NULL, e um `CHECK` que dá NULL passa | `motivo IS NOT NULL` nos dois ramos; `test_um_bloqueio_ou_uma_falha_sem_motivo_e_recusado` e uma mutação no `db/mutacoes.py` |
| G2 | deve corrigir | Duas versões do mesmo original podiam ficar escolhidas | Índice único parcial `image_jobs_escolhida_uq`, e o `escolher` desmarca a anterior (`test_so_uma_versao_escolhida_por_original`, `test_escolher_outra_versao_desmarca_a_anterior`) |
| 1 | bloqueia | O `bakeoff.correr` enviava a foto **crua** ao fornecedor — sem *gate*, sem lista de recusa, sem carta, sem minimização —, e é o caminho das primeiras fotos reais | O *bake-off* passa pelas mesmas barreiras e recusa-se inteiro se um fornecedor não puder receber (`TestBakeoffPelasBarreiras`); entra no inventário de clientes de saída do `lint_arch` |
| 2 | deve corrigir | A lista de recusa deixava passar `remove-bg-api`, `black-forest` e afins, com a caixa 6 marcada | Subcadeia do nome normalizado (`test_lista_de_recusa_por_subcadeia`) |
| 3 | deve corrigir | A quota era consumida antes de validar: um pedido inválido gastava `imagens_mes` sem trabalho | Valida-se primeiro (`test_pedido_invalido_nao_gasta_quota`) |
| 4 | deve corrigir | O `recuperar` não tinha predicado: com um trabalhador vivo, o fornecedor era chamado duas vezes e ficava uma versão órfã | `PRESO_APOS` lido do `atualizado_at` do gatilho, e o conflito no fim apaga a versão órfã (`test_recuperar_so_depois_de_preso`) |
| 5 | deve corrigir | A corrida de dois trabalhadores no `pendente` não tinha ensaio | `test_dois_trabalhadores_no_pendente_so_um_chama_o_fornecedor` |
| 6 | deve corrigir | O `RepositorioDbapi` nunca corria contra a base | `TestRepositorioNaBase`, com o serviço inteiro por cima (`db/tests/test_foto_schema.py`) |
| 7 | deve corrigir | O *timeout* de 45 s não era pedido nem medido pelo serviço | `Opcoes(timeout_s=45)` explícito e a latência medida pelo relógio do serviço (`test_o_servico_pede_45_s_e_mede_o_timeout_ele_proprio`) |
| 8 | PLAUSÍVEL → fechado | A declaração «sintética» saltava o filtro da carta em `prod` | Só vale fora de `prod` (`test_em_prod_a_declaracao_sintetica_nao_salta_a_carta`); fora dele, o KAM-119/KAM-122 não a expõem ao modelo |
| 9 | PLAUSÍVEL → fechado | A `origem_ref` aceitava qualquer classe do STO do tenant (um documento KYC) | Só `catalogo` e `foto`, no Python e no `image_jobs_origem_ref_ck` |
| 10 | PLAUSÍVEL — aberto | O original e a versão expiram com o `retain_until` (90 dias, *proposta*), escolhida ou não | **Fica escrito**: a foto de um produto publicado passa a ser do Registo, e copiá-la para lá é do KAM-119 (que publica); «recuperável em 100% dos casos» vale dentro da retenção |
| menores | — | Custo em `float`/`NaN` prendia o trabalho; falha transitória do STO dava «formato»; a mesma chave com outra foto devolvia a primeira; resposta ilegível do detector sem ensaio; recusas do lado Python sem ensaio | `_custo`, `ObjectoInexistenteError` separado, `ChaveReutilizada`, e um ensaio para cada (`TestAchadosDaRevisao`) |

---

## KAM-121 — Vertical `social`: perfil de marca, calendário semanal e legendas em português de Angola

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-118, KAM-030, KAM-009, KAM-088 |
| Bloqueia | KAM-122, KAM-125 |
| Responsável sugerido | Engenheiro de Runtime/IA com Responsável de Produto (T&S) |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§21.3), `../docs/tecnica/08_Seguranca_Conformidade.md` (§18), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` (§2, §4.2, §7, B5, B8, B11, B13), `../docs/exploracao/01-modelo-negocios-angola-ai-first.md` (Nº 8), `specs/EPIC-09_Onboarding_Governanca.md` (KAM-088), ADR-007, ADR-020 |

### Contexto

O Social AI do Piloto produz **calendário semanal, legendas e (em KAM-122) artes** para o dono publicar manualmente; não há publicação automática (D13). Este ticket cobre a parte textual e de planeamento. Riscos principais: preços ou promoções inventados (Lei 15/03, INDÍCIO), categoria bloqueada disfarçada de conteúdo, alegações proibidas, e português com marcas de pt-BR (a Google recomenda pt-BR e não indica pt-AO; E5 §2). A «proposta semanal» enviada pela KAMBÁ fora da janela é marketing para a Meta (≈ 0,0225 USD), pelo que o desenho prefere que o dono peça («IDEIAS»). Disposição a pagar e adequação ao mercado são NÃO VERIFICADAS (H10–H12).

### Objectivo

Registar a vertical `social` com `get_brand_profile`, `generate_calendar` e `generate_caption`, o perfil de marca, o calendário semanal e as legendas em pt-AO com screening de categoria e de alegações, sempre como rascunho até à aprovação (KAM-122).

### Critérios de Aceitação

- [ ] `brand_profile` criado numa conversa guiada de ≤ 8 perguntas (*proposta*): nome, categoria, tom (3 opções), até 3 cores (hex), logótipo do próprio dono, público, dias/horas preferidos e factos autorizados; perfil incompleto não gera calendário.
- [ ] `generate_calendar` devolve 3 a 7 `content_items` por semana (*proposta*) com tema e tipo (produto, dica, bastidores, promoção); datas/horas sugeridas calculadas por código a partir das preferências em `Africa/Luanda`, nunca pelo modelo; repetir «IDEIAS» na mesma semana devolve o **mesmo** calendário (chave `tenant|semana_iso`) e só «NOVA» o regenera.
- [ ] Cada legenda é pt-AO: lexicon versionado de marcadores pt-BR («celular», «você», «ônibus», «tela», etc.); após a correcção automática ≤ 2% de legendas com marcador em 100 geradas (*proposta*) e ≥ 85% «naturais» por 2 revisores angolanos (*proposta*, NÃO VERIFICADO até medir); modelo (alias `social-text`) escolhido por *eval*, não por recomendação do fornecedor.
- [ ] **0 preços ou promoções não-*fact***: qualquer valor monetário, percentagem, data de promoção ou telefone numa legenda existe num *fact* (`get_offer`/Registo ou facto de promoção fornecido pelo dono com validade); em 200 legendas e 30 pedidos adversariais («põe 50% de desconto») o sistema pergunta os dados ao dono em vez de os inventar.
- [ ] Cada tema e legenda passa por `screen()` (KAM-088): nos 100 casos canónicos de categoria bloqueada → **0** itens gerados; `condicional` → item marcado «revisão reforçada» e exige confirmação extra; decisão gravada com `versao_politica`.
- [ ] Política de alegações `policy/alegacoes/*.yaml` (*proposta*; SemVer, estado de evidência por entrada) bloqueia curas, «100% garantido», superlativos não comprovados, comparação com concorrentes nomeados e selos/certificações ausentes dos *facts*; ≥ 100 casos *allow/deny* no gate 12.
- [ ] Texto de descrição de produto, notas do dono e perfis são dados não confiáveis: 10 casos de injecção não alteram a saída nem o fluxo; não existe tool de publicação nem de envio a terceiros em `registry/social.yaml` (lint).
- [ ] Todo o `content_item` nasce com `is_ai_generated=true` e estado `rascunho`; nenhuma legenda é enviada a terceiros neste ticket.
- [ ] Custo de calendário + legendas de uma semana ≤ US$ 0,05 (*proposta*) com orçamento LiteLLM por tenant e `modulo=social`; entitlement `social` verificado por TEN; `posts_mes` consumido de forma idempotente.

### Detalhes Técnicos

- **Componentes:** ENT, AGR, TLS, LLM (`social-text`), GOV (screening), TEN. Reaproveita `confirm_gate`/`owner_actions` de KAM-118 e o validador de citação (KAM-032) para valores.
- **Imagens de terceiros e copiar texto de concorrentes:** fora de escopo; só factos do dono e do Registo. Dados de entrada de tendências/hashtags: lista local versionada, sem scraping.
- **Push semanal:** só por política de KAM-118 (opt-in, *template* marketing); por omissão desligado.

```sql
CREATE TABLE brand_profile (tenant_id uuid PRIMARY KEY, nome text NOT NULL, tom text NOT NULL, cores text[] NOT NULL DEFAULT '{}', logo_asset_id uuid,
  publico text, slots_preferidos jsonb NOT NULL DEFAULT '[]', factos jsonb NOT NULL DEFAULT '[]', idioma text NOT NULL DEFAULT 'pt-AO', versao int NOT NULL DEFAULT 1);  -- proposta
CREATE TABLE content_items (content_item_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, semana_iso text NOT NULL, tema text NOT NULL, legenda text,
  art_asset_id uuid, estado text NOT NULL DEFAULT 'rascunho' CHECK (estado IN ('rascunho','pendente_aprovacao','aprovado','entregue','rejeitado','expirado')),
  is_ai_generated boolean NOT NULL DEFAULT true, screening_ref bigint, versao int NOT NULL DEFAULT 1, agendado_at timestamptz);  -- proposta; RLS FORCE
```

### Testes Requeridos

- Unit: lexicon pt-BR, correcção, política de alegações, chave semanal, agenda em `Africa/Luanda`.
- Integração: conversa de perfil → calendário → legendas com LLM *fake*; categoria bloqueada; falta de *fact* de promoção.
- Isolamento: perfil e itens de A invisíveis a B; cliente sem acesso às tools do dono.
- **Adversarial:** preço inventado, categoria disfarçada, promessa proibida, injecção em descrição, pedido de publicação automática («publica no Instagram»).
- Golden `dono_social` (KAM-125).

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; eval-gate verde para prompts, alias e políticas.
- [ ] Números só de tools; categoria bloqueada nunca gerada; conteúdo marcado como gerado por IA (ADR-007, ADR-020).
- [ ] Idempotência do calendário e do consumo de `posts_mes` com teste de repetição.
- [ ] Facto jurídico (publicidade enganosa, desinformação) *(a confirmar por parecer)*; nenhum NÃO VERIFICADO tratado como requisito sem critério de saída.
- [ ] Isolamento de tenant (ADR-015); custo por semana medido (ADR-018); migração reversível; sem segredos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-121 da KAMBÁ (vertical social: perfil, calendário e legendas).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-121), docs/tecnica/02 §21.3, docs/tecnica/08 §18, docs/tecnica/evidencia/E5 §2 e §7 e specs/EPIC-09 (KAM-088).
Objectivo: registry/social.yaml com get_brand_profile, generate_calendar, generate_caption; brand_profile, content_items, legendas pt-AO e screening.
Regras: sem tool de publicação; números e promoções só como facts do dono ou do Registo; horas calculadas por código; legendas passam por screen() e pela política de alegações;
pt-BR é um risco medido por lexicon e golden; tudo nasce rascunho com is_ai_generated=true. Limiares são propostas.
Não implementes artes e entrega (KAM-122) nem planos (KAM-124). Testes: unit, integração, isolamento, adversarial. PR com o template da §7.
```

---

## KAM-122 — Social AI: artes e entrega para publicação manual com aprovação do dono

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-121, KAM-120, KAM-015 |
| Bloqueia | KAM-127 |
| Responsável sugerido | Engenheiro de Runtime/IA (MED) com Engenheiro de Canais |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§21.3), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` (§2, §3, §7, B1, B5, B9), `../docs/tecnica/00_Arquitectura_Solucao.md` (D13), `../docs/tecnica/08_Seguranca_Conformidade.md` (§18), ADR-007, ADR-020 |

### Contexto

Completa o Social AI: gera a **arte**, pede a aprovação do dono e **entrega** para publicação manual. Por E5, o modelo de imagem gera apenas o fundo/cena e o **texto da arte (nome, preço em Kz, contactos) é composto por código** com fontes reais e dados do Registo; benchmarks de texto em português gerado por modelos não existem (NÃO VERIFICADO). A publicação por API exige Advanced Access (App Review e Business Verification) sem prazo oficial (CONFIRMADO/INDÍCIO) e fica **Diferida (D13)**: o gatilho é App Review aprovado e ≥ 3 PMEs com Página/conta profissional; o Facebook pesa 5× o Instagram em Angola (INDÍCIO). A responsabilidade de rotular o conteúdo como IA ao publicar fica com o dono, por isso a entrega leva a instrução. Direitos: imagens geradas provavelmente sem protecção de autor (INDÍCIO, Lei 15/14), sem garantia de exclusividade.

### Objectivo

Entregar `generate_art`, o compositor de artes por *templates*, a tool `request_approval`, o evento `content.approved`, a interface `SocialPublisher` com a implementação `ManualDelivery` e a entrega (WhatsApp e painel), sem qualquer ligação a redes sociais.

### Critérios de Aceitação

- [ ] 3 a 5 *templates* por tipo de negócio (*proposta*) em código, formatos 1080×1080 e 1080×1350 (*proposta*), fontes com licença livre verificada; o texto composto (nome, preço, contactos, «Kz») é **idêntico** à cadeia esperada em 100% de um conjunto de 50 casos com acentos e formato «12.500 Kz».
- [ ] O preço/promoção na arte vem de um *fact* validado (KAM-032); 0 valores monetários na arte sem *fact* em 100 renderizações adversariais.
- [ ] O fundo gerado é sem texto: verificação OCR local rejeita fundos com texto (regerar até 2×, depois fundo liso/gradiente ou a foto do produto de KAM-120); 100 fundos → 0 artes finais com texto gerado por IA. Fundo generativo só com destino autorizado (`apd_ref`); sem ele, a arte usa foto do dono + *template*.
- [ ] Saída em JPEG (único formato suportado pela API do Instagram, E5), EXIF removido, marca de IA preservada (não remover SynthID/metadados); `is_ai_generated=true` gravado no `content_item`.
- [ ] `request_approval` envia pré-visualização (arte + legenda) com botões Aprovar/Editar/Rejeitar (`confirm:{content_item_id}`); **reenviar a aprovação 2× produz 1 só item `aprovado` e 1 evento `content.approved`**; a aprovação fica ligada a `hash(legenda, arte, versao)` e qualquer edição posterior invalida-a (item volta a `pendente_aprovacao`).
- [ ] Legenda editada pelo dono volta a passar por `screen()` e pelo validador de números (números do dono entram como *fact* com eco); categoria bloqueada → recusa; 0 itens `entregue` sem estado `aprovado` (restrição de BD).
- [ ] Interface `SocialPublisher` com `deliver()` e `publish()`; só `ManualDelivery` existe; `publish()` lança `NotEnabled`; teste de CI garante **0** referências a `media_publish`, `/feed`, `/photos` de redes e **0** variáveis/segredos de tokens de redes no repositório e na configuração.
- [ ] A entrega envia a arte como imagem e a legenda como texto copiável, com a nota «activa o rótulo de IA ao publicar» (gancho de `is_ai_generated`) e ligação de descarga no painel (URL assinada, validade ≤ 24 h, *proposta*); só ocorre quando o dono pede («ENVIAR») ou dentro da janela de 24 h; fora dela o item fica `aprovado` no painel e só há *template* com opt-in (custo orçado como marketing).
- [ ] Máx. 3 tentativas de arte por item (*proposta*) com alerta de custo; `posts_mes` e `imagens_mes` aplicados por TEN; custo por item aprovado medido; mensagem de termos (sem garantia de exclusividade) mostrada e registada na 1.ª entrega.

### Detalhes Técnicos

- **Componentes:** ENT, MED, STO, TLS, TEN; `ImageProvider` (KAM-120) e, para artes, Gemini pago (E5: ≈ 0,0336 USD/imagem 1K; tratamento «em qualquer país», pior caso para a APD).
- **Eventos:** `content.approved` (dicionário §3.7) com `content_item_id`, `versao`, sem conteúdo; consumidor opcional futuro: `FacebookPagePublisher`/`InstagramPublisher` (Diferidos).
- **Pedido de permissões de redes** (`pages_manage_posts`, `instagram_business_content_publish`) no mesmo ciclo do Tech Provider (E5 §3) é pedido a KAM-102, não implementado aqui.

### Testes Requeridos

- Unit: compositor (acentos, quebras de linha, preços), estados do item, invalidação por edição, integridade do `hash`.
- Integração: calendário → arte → aprovação → entrega no canal do dono e no painel; fundo com texto → regeração/*fallback*.
- Idempotência: aprovação ×2, renderização ×2, entrega ×2 (1 só mensagem de entrega).
- **Adversarial:** edição pós-aprovação, pedido «publica por mim», legenda com categoria bloqueada, URL assinada de outro tenant, logótipo de terceiros.
- CI: busca de endpoints/segredos de redes sociais.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; teste «sem publicação automática» verde.
- [ ] Conteúdo para terceiros: aprovação explícita, marcação de IA e screening (ADR-020); termos sem exclusividade *(a confirmar por parecer)*.
- [ ] Idempotência de aprovação e entrega; isolamento de tenant e de URL assinada (ADR-015).
- [ ] Números só de tools na arte (ADR-007); custo por item medido (ADR-018).
- [ ] Migração reversível; sem segredos; lockfile e licenças de fontes/renderizador limpos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-122 da KAMBÁ (artes e entrega para publicação manual).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-122), docs/tecnica/02 §21.3, docs/tecnica/evidencia/E5 §2 e §3 e specs/01_Engineering_Standards_e_Handoff.md.
Objectivo: generate_art (templates + texto por código), request_approval com confirm:{content_item_id}, evento content.approved, SocialPublisher com ManualDelivery,
entrega por WhatsApp e painel.
Regras: nenhuma tool publica; sem tokens nem endpoints de redes; o modelo gera só o fundo e sem texto; preços na arte só de facts; aprovação ligada a hash e idempotente;
JPEG sem EXIF; manter marcas de IA. Não implementes publicação (Diferida, D13) nem legendas (KAM-121).
Testes: unit, integração, idempotência, adversarial e CI de ausência de publicação. Migração reversível. PR com o template da §7.
```

---

## KAM-123 — Orçamento expresso: preço «sob consulta», pedido ao dono e proposta ao cliente

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-043, KAM-118, KAM-031, KAM-032, KAM-005, KAM-007, KAM-015, KAM-018 |
| Bloqueia | KAM-125, KAM-127 |
| Responsável sugerido | Engenheiro de Runtime/IA com Engenheiro de Comércio |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§9, §21.3), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` (§4, §5, B10, B11), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§4, §6), `specs/EPIC-03_Agent_Runtime_Verticais.md` (KAM-031, KAM-032), `specs/EPIC-04_Core_Comercio.md` (KAM-043), ADR-007, ADR-020 |

### Contexto

O Orçamento expresso do Piloto é uma **forma do fluxo Vendedor**, não um motor de preços: quando um produto tem `preco_tipo='sob_consulta'`, o validador (KAM-032) proíbe qualquer número; este módulo liga o cliente ao dono. O cliente pede (`request_quote`), o dono fixa o valor (`submit_quote`, *fact* `quote_price`) e confirma o envio (`send_quote`). O bot **nunca calcula** o preço, nem unidade × quantidade. A proposta é uma mensagem estruturada sem PDF, rotulada «Orçamento — não é factura», sem numeração fiscal (a plataforma não é software validado AGT; E5 B10, E3 §6). A «base de preços viva» extraída de PDFs e sites de terceiros (negócio Nº 3) fica **fora do Piloto** (E5). Fora da janela de 24 h do cliente só sai *template*; a classificação como utility de «o teu orçamento está pronto» é NÃO VERIFICADA (pergunta à Meta).

### Objectivo

Implementar `request_quote`, `submit_quote` e `send_quote`, a tabela `quote_requests`, os eventos `quote.requested` e `quote.sent` e a integração com o validador de citação e o `confirm_gate`, mantendo o dono como única fonte do preço.

### Critérios de Aceitação

- [ ] Ao pedir preço de um produto `sob_consulta`, o grafo do Vendedor chama `request_quote` (write, cliente) e responde sem qualquer número; reenviar o pedido do mesmo `contact_id` e `sku` em 10 min (*proposta*) devolve o **mesmo** `quote_id` (1 linha, 1 evento `quote.requested`).
- [ ] Cada pedido tem `estado` ∈ {`pedido`, `respondido`, `enviado`, `aguarda_janela`, `expirado`, `cancelado`}; o dono vê os pedidos pendentes na 1.ª mensagem e no painel; aviso proactivo só dentro da janela do dono ou, com opt-in, por *template* (KAM-118); sem aviso, o pedido não se perde (visível no painel).
- [ ] `submit_quote` (write, dono) aceita o valor final digitado pelo dono («120 mil», «120.000») por parser determinístico com eco e botão; grava o *fact* `quote_price {quote_id, valor_minor, currency='AOA', validade_ate, condicoes}`; **0** valores calculados pelo sistema: em 100 pedidos com quantidades diferentes nunca aparece total que o dono não tenha digitado.
- [ ] `condicoes` (≤ 200 caracteres) é texto do dono passado por `screen()` e por injecção; `validade_ate` obrigatória (omissão: 7 dias, *proposta*, mostrada como data calculada por código).
- [ ] `send_quote` (write, confirmação do dono) mostra pré-visualização e só envia com botão `confirm:{quote_id}`; duplo toque ×2 → **1** mensagem ao cliente e 1 evento `quote.sent`; envio pelo caminho `send` único (nenhuma tool envia por si).
- [ ] A mensagem usa o *renderer* por referência (`{{quote_price:quote_id}}`) e passa pelo validador: em 100 saídas adversariais com outro número, desconto ou total («e com 10% de desconto?») → **0** passam; o bot recusa calcular e abre novo pedido ao dono.
- [ ] Texto fixo «Orçamento — não é factura», validade e referência interna `ORC-…`; nenhum campo `nif`, `serie` ou numeração fiscal no modelo; sem PDF.
- [ ] Cliente com janela de 24 h fechada: estado `aguarda_janela`, *template* utility sem número («o teu orçamento está pronto, responde para ver»), orçado como marketing no pior caso (0,0225 USD); o valor só é enviado depois de o cliente responder.
- [ ] Orçamento expirado ou cancelado não pode ser aceite; resposta «aceito» do cliente **não cria pedido** e entrega a conversa ao dono com o contexto (KAM-034); pedido sem resposta do dono em 24 h (*proposta*) gera 1 mensagem neutra ao cliente e oferta de humano.
- [ ] Isolamento: o dono de A não vê orçamentos de B; o cliente X não vê os de Y; `orcamentos_mes` aplicado por TEN; pedidos de bens fora do catálogo ou de PDFs/sites de terceiros não são ingeridos.

### Detalhes Técnicos

- **Componentes:** ENT, AGR (grafo do Vendedor), TLS, TEN, COM. `quote_price` é novo tipo de *fact* para o validador (extensão a registar em KAM-032) e `confirm:{quote_id}` generaliza o botão.
- **Eventos:** `quote.requested` e `quote.sent` (dicionário §3.7) via outbox, sem texto nem telefone.

```sql
CREATE TABLE quote_requests (  -- proposta; RLS FORCE
  quote_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, contact_id uuid NOT NULL, sku text NOT NULL, quantidade int,
  estado text NOT NULL DEFAULT 'pedido' CHECK (estado IN ('pedido','respondido','enviado','aguarda_janela','expirado','cancelado')),
  valor_minor bigint, currency text DEFAULT 'AOA', validade_ate date, condicoes text, criado_at timestamptz NOT NULL DEFAULT now(), enviado_at timestamptz);
```

### Testes Requeridos

- Unit: parser de valores, estados, validade, chave de idempotência.
- Integração: cliente → pedido → dono → envio com `ManualProvider`/outbound *fake*; janela fechada; expiração.
- Isolamento: dono/cliente cruzados; `kamba_app` sem acesso a pedidos de outro tenant.
- **Adversarial:** «calcula 12 unidades», desconto negociado, injecção em `condicoes`, dono a digitar valor ambíguo, botão antigo, cliente a forjar `quote_id`.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; golden `dono_orcamento` (KAM-125) preparado.
- [ ] Números só de tools: preço só como *fact* `quote_price` validado (ADR-007).
- [ ] Idempotência de pedido, envio e eventos com teste de repetição (ADR-009); sem pagamento envolvido, o orçamento não marca nada como pago (ADR-013).
- [ ] Sem fundos de terceiros nem documento fiscal; rótulo «não é factura» *(a confirmar por parecer, E5 Q8)*.
- [ ] Isolamento de tenant e contacto (ADR-015); logs sem conteúdo (ADR-010); migração reversível; dois revisores.

### Handoff para Claude Code

```text
És o executor do ticket KAM-123 da KAMBÁ (Orçamento expresso).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-123), specs/EPIC-03 (KAM-031, KAM-032), docs/tecnica/02 §9 e §21.3 e docs/tecnica/evidencia/E5 §4, §5 e B10.
Objectivo: request_quote (cliente) -> submit_quote (dono fixa quote_price) -> send_quote (confirm:{quote_id}); quote_requests; eventos quote.requested e quote.sent.
Regras: o bot nunca calcula nem inventa o preço; a mensagem passa pelo validador com renderer por referência; sem PDF, sem numeração fiscal, rótulo «não é factura»;
aceitação do cliente não cria pedido (vai ao dono); janela de 24 h tratada com template sem número. Sem base de preços extraída de terceiros.
Não alteres o grafo do Vendedor além do necessário nem implementes planos (KAM-124). Testes: unit, integração, isolamento, adversarial. PR com o template da §7.
```

---

## KAM-124 — Planos, entitlements e metering de custo dos módulos de entrada

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-009, KAM-081, KAM-120 |
| Bloqueia | KAM-127 |
| Responsável sugerido | Engenheiro de Plataforma (TEN/OBS) com Responsável de Produto |
| Documentos de referência | `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§21.2–21.3), `../docs/tecnica/10_Onboarding_Governanca.md` (§21), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§21.5), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` (§1.3, §4, §5, B12), `../docs/exploracao/01-modelo-negocios-angola-ai-first.md` (Nº 3, 4, 5, 8), `specs/EPIC-01_Fundacoes_Dados.md` (KAM-009), `specs/EPIC-08_Topologia_Operacao.md` (KAM-081), ADR-018 |

### Contexto

Cada módulo é um entitlement com limites próprios; o plano de entrada pode conter **só módulos de entrada, sem atendimento** (`../docs/tecnica/10` §21). O LiteLLM mede o texto mas **não cobre os fornecedores de imagem** (E5 B12), pelo que é preciso um contador próprio e uma rubrica por módulo; sem metering por módulo, H12 («custo ≤ 15% do preço do módulo») não é verificável. Estimativa de custo por PME e mês: ≈ 1,3 a 4,5 USD com 40 recortes, 12 artes e 4 propostas por *push* (`../docs/tecnica/09` §21.2, hipótese de volume, não medição). Os preços de teste são **hipóteses**: catálogo 15–90 mil Kz (Nº 4), fotos 15–80 mil Kz (Nº 5), redes 80–250 mil Kz (Nº 8; E5 sugere testar 60–120 mil face a uma agência a ≈ 181 mil Kz, INDÍCIO), orçamentos 5–20 mil Kz por orçamento ou 100–300 mil Kz/mês (Nº 3). Sem fonte para disposição a pagar (NÃO VERIFICADO).

### Objectivo

Estender TEN e a medição de custo com o conceito de `modulo`, os limites `imagens_mes`, `posts_mes`, `orcamentos_mes`, planos de teste com preços hipotéticos, um *ledger* de custo por módulo e as vistas e alertas que alimentam H12.

### Critérios de Aceitação

- [x] `registry/entitlement_keys.schema.json` aceita `modulo` ∈ {`catalogo`, `foto`, `social`, `orcamento`} e os limites `imagens_mes`, `posts_mes`, `orcamentos_mes`; chave desconhecida é rejeitada; `checkEntitlement(tenant, modulo)` é fail-closed e um tenant só com `foto` recebe `403 ENTITLEMENT_DISABLED` em `social` e `orcamento` (matriz 4×4 testada).
- [x] `consumeLimit` aplica-se a imagens, posts e orçamentos: 1.000 trabalhos paralelos contra `imagens_mes=100` aceitam exactamente 100; repetir a `idempotencyKey` 10× consome 1; o mês fecha às 00:00 de `Africa/Luanda`.
- [x] `registry/plans.yaml` inclui planos de teste `entrada_catalogo`, `entrada_foto`, `entrada_social`, `entrada_orcamento` e `entrada_completo` (4 módulos, sem atendimento) com `preco_teste_minor` e `estado: hipotese_nao_validada`; um lint falha se um preço não tiver esse estado ou se aparecer em texto ao cliente.
- [ ] *Ledger* `module_cost_ledger` (append-only, `INSERT` por função) com `tenant_id`, `modulo`, `rubrica` ∈ {`llm`, `imagem`, `mensagem`}, `custo_usd`, `custo_minor`, `ref`, `idempotency_key` UNIQUE; reenviar o mesmo custo 5× → 1 linha.
- [ ] Custo LLM por módulo vem do `llm_call_log`/LiteLLM com etiqueta `modulo`; custo de imagem de `image_jobs.custo_minor`; custo Meta de mensagens do dono (*push* e *templates*) pelo mapa *template* → módulo; reconciliação em *staging* com tráfego sintético de 7 dias: LLM ≤ 2% de desvio, imagem ≤ 5% face ao painel do fornecedor, mensagens ≤ 5% (*propostas*).
- [x] Vista `v_module_cost_month` (tenant, módulo, rubrica, USD, Kz com `fx_aoa_per_usd` parametrizável, omissão 913) e `v_h12` (custo, `preco_teste_minor`, rácio, margem); **sem** `contact_id`, telefone nem conteúdo.
- [ ] Orçamentos mensais por módulo: LiteLLM para texto e *guard* próprio para imagem; ao esgotar, o dono recebe mensagem estática com os números vindos da tool `get_usage` (read); nenhum trabalho de imagem é iniciado acima do orçamento (0 em teste).
- [ ] Alertas: custo do módulo > 15% do `preco_teste_minor` no mês (aviso) e > 30% (crítico) (*propostas*); custo diário > 3× a mediana do tenant; alerta de fornecedor de imagem sem custo registado.
- [ ] Comando `h12-export` produz CSV pseudonimizado (módulo, custo, uso, preço de teste, tenant sem nome) para KAM-127; o consumo de uma PME de teste aparece no painel em ≤ 5 min.
- [x] Billing real do módulo (assinatura) não é implementado aqui: apenas exporta o consumo para KAM-059.

### Detalhes Técnicos

- **Componentes:** TEN, OBS, LLM, MED, ENT. Reaproveita `tenant_usage`/`usage_ledger` de KAM-009 e a vista de custo diário de KAM-081, a que acrescenta a dimensão `modulo` (a etiqueta `modulo` no cliente LLM de KAM-030 é extensão a registar).
- **Custos de referência a reverificar:** Bria recorte ≈ 0,018 USD, Photoroom Basic ≈ 0,02 e Plus ≈ 0,10, Gemini 1K ≈ 0,0336, Meta marketing 0,0225 e utility/service 0,004 (E5; tarifas efectivas 2026-10-01).
- **Dependência implícita a ratificar:** KAM-120 (`image_jobs`) e KAM-122/123 produzem o consumo; o contrato é o evento de custo, sem acoplamento circular.

```sql
CREATE TABLE module_cost_ledger (  -- proposta; append-only; RLS FORCE
  id bigserial PRIMARY KEY, tenant_id uuid NOT NULL, modulo text NOT NULL CHECK (modulo IN ('catalogo','foto','social','orcamento')),
  rubrica text NOT NULL CHECK (rubrica IN ('llm','imagem','mensagem')), custo_usd numeric(12,6) NOT NULL, custo_minor bigint NOT NULL, ref text,
  idempotency_key text NOT NULL, ocorrido_em timestamptz NOT NULL DEFAULT now(), UNIQUE (tenant_id, idempotency_key));
```

### Testes Requeridos

- Concorrência 1.000/100, idempotência e fronteira de mês (relógio fixo).
- Unit: matriz módulo × estado do tenant, lint de preços, conversão cambial e sensibilidade (+7,4%).
- Integração: reconciliação LiteLLM × ledger; imagem com `ImageProvider` falso; orçamento esgotado.
- Isolamento: ledger e vistas de A invisíveis a B; teste de ausência de PII nas vistas.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; plano de teste carregável sem *deploy*.
- [ ] Isolamento de tenant (ADR-015) e idempotência com teste (ADR-009); cobertura ≥ 90% no consumo de limites.
- [x] Custo e observabilidade desde o código (ADR-018); preços marcados hipótese; nenhum preço mostrado como definitivo.
- [x] Plataforma sem fundos: nenhuma cobrança neste ticket (ADR-004).
- [x] Migração reversível; documentação (`docs/modulos-entrada.md`); sem segredos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-124 da KAMBÁ (planos, entitlements e metering dos módulos de entrada).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-124), specs/EPIC-01 (KAM-009), specs/EPIC-08 (KAM-081), docs/tecnica/09 §21 e docs/tecnica/evidencia/E5 §1.3 e B12.
Objectivo: chaves modulo e limites imagens_mes/posts_mes/orcamentos_mes; plans.yaml com preços de teste; module_cost_ledger; v_module_cost_month e v_h12; alertas; h12-export.
Regras: preços de teste são hipóteses (estado obrigatório); consumo atómico e idempotente; custo de imagem tem contador próprio (LiteLLM não o cobre);
custos de fornecedores são a reverificar; sem PII nas vistas; sem billing (KAM-059). Testes: concorrência, idempotência, mês, isolamento, reconciliação. PR com o template da §7.
```

### Decisões do executor

- **O TEN já tinha a regra; este ticket dá-lhe os módulos.** O `check_entitlement`/`checkEntitlement` (fail-closed) e o `consume_limit`/`consumeLimit` (atómico, idempotente, mês de `platform.ten_periodo` em Africa/Luanda) são os do KAM-009, sem alteração: os critérios 1 e 2 provam-se **para os módulos de entrada**, contra a base e pela mesma SQL das bibliotecas. O que entra no registo é o domínio fechado dos quatro módulos (`$defs.modulo_de_entrada` em `registry/entitlement_keys.schema.json`, confrontado com `kamba_core.modulos.MODULOS_DE_ENTRADA`) e a **décima segunda** chave de limite, `custo_max_mes_micro_usd` — o orçamento mensal de custo do módulo, lido na linha do **próprio** módulo e não pelo `platform.ten_tecto`, que daria o mínimo dos módulos activos.
- **O contrato entre quem produz o custo e o *ledger* é a consolidação, e não um evento.** O `h12-export consolidar` (de 5 em 5 minutos, *job* `ops_h12_export`) lê as três fontes e escreve pela `platform.module_cost_gravar`, com a chave de idempotência derivada da linha de origem. Um evento de custo novo pedia contrato, subscrições e as contagens do `contract_diff` para o que uma leitura idempotente já resolve, e o bloco só pede que não haja acoplamento circular — que não há: o KAM-120 não sabe que o *ledger* existe.
- **O *ledger* leva o `custo_usd` e o `custo_minor`.** O primeiro é a verdade (0,018 USD não cabe num cêntimo, a decisão da `0054`); o segundo é o mesmo custo em cêntimos de Kz ao câmbio do registo, que vai ao lado em `fx_aoa_per_usd`. As vistas convertem o `custo_usd` ao câmbio da sessão, para a sensibilidade correr sem reescrever o *ledger*. O `id` é `uuid` e não o `bigserial` do esboço: é a regra do `platform` (`test_catalogo`), e um sequencial dizia à aplicação quantos custos a plataforma regista.
- **O custo de imagem lê-se de `image_jobs.custo_usd`**, e não do `custo_minor` que o critério 5 escreve: é a decisão que o KAM-120 tomou e devolveu, e este ticket segue-a.
- **Os preços de teste vivem no plano e na base.** Um `preco_teste_minor` por entitlement dos cinco planos `entrada_*`; o `h12-export carregar-precos` copia-os para a `platform.module_test_prices` (global, `estado` de um só valor) **sem deploy**, e a `v_h12` lê o preço do plano do tenant. Os valores são o limite de baixo de cada intervalo do contexto; o `entrada_completo` repete-os, porque um desconto de pacote seria inventado.
- **A guarda de orçamento da imagem compõe-se por cima da quota** (`QuotaComOrcamento`), sem mexer no `ServicoDeFoto`: pergunta o orçamento antes de consumir o `imagens_mes`, e a imagem lê-se **ao vivo** da `image_jobs` (o *ledger* só a tem 5 minutos depois). Falha fechada: sem a chave, com um valor ilegível ou com a base em baixo, nenhum trabalho nasce.
- **Revisão `0057`**, sobre a `0056` (KAM-097), o número da integração — o ramo nasceu como `0058`. Emenda **1.98** e **§3.69** do dicionário, e versão **1.7** deste epic.

### Verificação dos Critérios de Aceitação

Dez critérios, **cinco marcados**. Cada linha leva o ensaio que a prova; as vazias dizem o que falta e quem o fecha. **Sem LLM pago e sem fornecedor real de imagem**: os custos vêm de linhas sintéticas nas tabelas de origem, e o fornecedor é o falso do KAM-120.

Os ensaios: `db/tests/test_modulos_custo_schema.py` e `db/tests_ten/test_modulos_de_entrada.py` (gate 8, contra o PostgreSQL), `db/tests/test_modulos_custo.py` (o `h12-export` sem base), `libs/py-core/tests/test_modulos.py` (a guarda e o `get_usage`) e `TestPrecosDeTeste` em `tools/canon_lint/tests/test_superficies_de_ficheiro.py` (o lint).

| Critério | Estado | Evidência nomeada |
|---|---|---|
| 1 | marcado | O registo aceita os quatro módulos (`$defs.modulo_de_entrada`, `test_os_quatro_modulos_sao_os_do_registo_e_do_plans`) e os três limites, e recusa uma chave desconhecida (`additionalProperties: false`, `test_uma_chave_desconhecida_e_rejeitada_na_escrita`; o gate 3b confronta o `plans.yaml` com o dicionário). A matriz 4 × 4 contra a base, um tenant por módulo e os quatro perguntados a cada um (`test_a_matriz_quatro_por_quatro`), com `403 ENTITLEMENT_DISABLED`; só com `foto` é negado em `social` e `orcamento` (`test_so_com_foto_e_negado_em_social_e_orcamento`); inactivo é negado (`test_um_modulo_inactivo_e_negado`). Corre o `SQL_ENTITLEMENT` da biblioteca Python, que é o texto do `checkEntitlement` por paridade (`TestParidadeDoTypeScript`). **Quem recusa um módulo fora dos quatro** é o gate 3b, pelo domínio do dicionário (`modulo_de`), e os `CHECK` do *ledger* e dos preços: o `$defs.modulo_de_entrada` do registo é a lista de referência e nenhum `$ref` o usa, porque o `modulo` não é chave de `limites` |
| 2 | marcado | **Mil** consumos paralelos, em 32 ligações, contra `imagens_mes = 100`: exactamente 100 aceites, 900 negados, nenhuma falha (`test_aceitam_exactamente_cem_e_nenhuma_falha`); a mesma chave 10 vezes consome 1 nos três contadores (`test_dez_repeticoes_consomem_uma_nos_tres_contadores`); o mês fecha às 00:00 de Luanda com o instante que distingue Luanda de UTC, nos três (`test_o_mes_fecha_a_meia_noite_de_luanda_nos_tres_contadores`) |
| 3 | marcado | Os cinco planos com `preco_teste_minor` e `estado: hipotese_nao_validada` em `registry/plans.yaml`, sem o módulo `vendedor`. O gate 3b recusa um preço num plano com outro estado (`test_preco_num_plano_que_nao_e_hipotese`), ilegível ou fora dos módulos de entrada (`test_preco_ilegivel`, `test_preco_num_modulo_que_nao_e_de_entrada`) e escrito em Kz num texto ao cliente (`test_o_preco_em_kz_num_texto_ao_cliente_e_recusado`, seis grafias; e não por coincidência, `test_sem_moeda_ou_outro_numero_nao_e_preco`); o repositório passa (`test_o_repositorio_nao_mostra_nenhum_preco_de_teste`). **Limite dito:** o corpus «ao cliente» é uma lista de padrões (`CORPUS_AO_CLIENTE`), e um texto ao cliente fora dela passa |
| 4 | **parcial — caixa vazia** | Só de acrescentar, com os gatilhos `ENABLE ALWAYS` que recusam `UPDATE`, `DELETE` e `TRUNCATE` ao próprio superutilizador, também em modo de réplica (`test_nem_o_administrador_reescreve_apaga_ou_trunca`, `test_os_gatilhos_sao_always`); as colunas do critério e `UNIQUE (tenant_id, idempotency_key)`; o mesmo custo 5 vezes dá **1** linha (`test_cinco_reenvios_do_mesmo_custo_dao_uma_linha`), e outro custo com a mesma chave levanta (`test_outro_custo_com_a_mesma_chave_levanta`). **A letra «`INSERT` por função» não está cumprida à letra**: a função é `SECURITY INVOKER` (a razão da `0007`) e o `kamba_batch` tem o `INSERT` por coluna — a aplicação não tem (`test_a_aplicacao_nao_escreve`). A leitura volta a quem escreveu o critério |
| 5 | **parcial — caixa vazia** | As três rubricas consolidadas e o que fica de fora — o trabalho vivo, a recusa de destino, a vertical que não é módulo, o *template* fora do mapa —, idempotente à segunda corrida (`test_as_tres_fontes_e_o_que_fica_de_fora`); o `reconciliar` contra as fontes e com as tolerâncias de 2%, 5% e 5% (`test_as_tolerancias_do_criterio`, `test_alertas_e_reconciliacao_sobre_a_base`). **Falta:** a reconciliação em *staging* com 7 dias de tráfego sintético e o painel do fornecedor de imagem (credor: quem tiver a pilha de *staging* — KAM-080 — e o fornecedor do *bake-off* do KAM-120); o custo LLM do **orçamento** expresso, que corre no Vendedor e não se separa pela `vertical` (credor: **KAM-030**, a etiqueta `modulo` no cliente LLM, e **KAM-123**); o mapa *template* → módulo, vazio até os módulos criarem os *templates* (**KAM-119**, **KAM-122**, **KAM-123**). **Hoje a rubrica `llm` fica vazia na prática**: as verticais `catalogo` e `social` ainda não existem no `registry/` (KAM-119, KAM-121), e o custo de visão do Catálogo AI vive em `catalog_ingestions.custo_llm_usd` até o adaptador do KAM-119 o levar à `llm_call_log` |
| 6 | marcado | As colunas das duas vistas por igualdade com a lista escrita no ensaio, e nenhuma de pessoa (`test_as_colunas_sao_a_lista_fechada_e_nenhuma_e_de_pessoa`); `security_invoker` (`test_as_vistas_correm_com_a_rls_de_quem_le`); o Kz ao câmbio da sessão, omissão 913, +7,4% a 981, e um câmbio ilegível levanta (`test_soma_por_rubrica_e_converte_ao_cambio_da_sessao`); o mês de Luanda (`test_o_mes_fecha_a_meia_noite_de_luanda`); o rácio e a margem com preço, e nulos sem ele (`test_a_h12_com_preco_e_sem_preco`) |
| 7 | **parcial — caixa vazia** | **Imagem:** nenhum trabalho nasce acima do orçamento — **0** em 20 pedidos, sem quota gasta e sem bytes no fornecedor (`test_nenhum_trabalho_de_imagem_nasce_acima_do_orcamento`); sem orçamento, ilegível ou com erro recusa (`test_acima_ou_sem_orcamento_ou_com_erro_nao_consome`, `test_sem_a_chave_do_orcamento_nao_nasce_trabalho`); contra a base, a imagem ao vivo sem contar duas vezes a já consolidada (`test_o_gasto_le_a_imagem_ao_vivo_e_o_resto_do_ledger`). A mensagem **estática** com os números do `get_usage` e sem preços (`test_os_numeros_do_get_usage_e_o_mes_seguinte`, `test_nenhum_preco_de_teste_no_texto`, `test_get_usage_pela_aplicacao`). **Falta:** o orçamento do texto no LiteLLM, que é configuração do *gateway* e não deste repositório (credor **KAM-030**), o registo da tool `get_usage` nas verticais do dono e o envio da mensagem pelo canal (**KAM-119**, **KAM-122**), e a composição da `QuotaComOrcamento` no arranque do serviço de foto, que hoje só os ensaios montam (**KAM-119**, **KAM-194**). E a guarda não é atómica: o excesso sobre o tecto é o custo dos trabalhos em voo, limitado pelo `imagens_mes` |
| 8 | **parcial — caixa vazia** | Os quatro alertas calculados e ensaiados com os limiares por extenso — 15% aviso e 30% crítico (`test_limiares_do_preco`), 3 vezes a mediana com 7 dias de história (`test_dia_acima_de_tres_vezes_a_mediana`), fornecedor de imagem sem custo (`test_fornecedor_sem_custo_e_mensagem_sem_tarifa`) — e contra a base (`test_alertas_e_reconciliacao_sobre_a_base`). **Falta o encaminhamento**: o `h12-export alertas` sai com código 1 e o JSON, e ligá-lo ao Alertmanager é do deploy da observabilidade (credor **KAM-080**) |
| 9 | **parcial — caixa vazia** | O CSV pseudonimizado contra a base, sem `tenant_id` nem nome, com o uso e o estado do preço (`test_exportar_da_o_csv_sem_tenant_id_e_com_o_uso`, `test_as_linhas_sem_tenant_id_e_o_uso_por_modulo`); sem chave recusa (`test_sem_chave_recusa`). **Falta «no painel em ≤ 5 min»**: o Grafana não está provisionado (KAM-080) e não há painel de módulos; o que se garante é a cadência do `consolidar` (5 min) e que a linha aparece na vista no mesmo instante em que entra no *ledger*; **o agendamento do *job* `ops_h12_export`** não está neste repositório (o agendador dos *jobs* de lote é do **KAM-071**) |
| 10 | marcado | Nenhuma cobrança, nenhuma subscrição, nenhum `price_book` tocado; a `module_test_prices` não é lida por nenhum caminho de pagamento. O consumo exporta-se no CSV (`exportar`) para o KAM-059 |

### Verificação da Definition of Done

| Caixa | Estado | Evidência nomeada |
|---|---|---|
| 1 | **parcial — caixa vazia** | Cinco critérios de dez. O plano de teste carrega-se sem *deploy* (`test_carregar_precos_le_o_registo_sem_deploy`) |
| 2 | **parcial — caixa vazia** | Isolamento: o *ledger* e a vista do mês de A invisíveis a B e sem contexto, com a sonda positiva (`test_o_ledger_de_a_e_invisivel_a_b`), a `v_h12` fora do `kamba_app` (`test_a_aplicacao_nao_le_a_h12_e_le_o_seu_mes`), e o *ledger* em `SEM_RECEITA_COM_RAZAO` do gate 6 pela razão do `order_state_log`. Idempotência: critérios 2 e 4. **Cobertura**: o consumo de limites é o `kamba_core.ten` do estrato crítico, medido no gate 4 — ver a medição no PR |
| 3 | marcado | O custo é registado desde o código de origem (a `image_jobs` e a `llm_call_log`), os preços estão marcados `hipotese_nao_validada` no plano, na tabela e no CSV, e nenhum chega ao cliente (critério 3) |
| 4 | marcado | Nenhuma cobrança neste ticket (critério 10) |
| 5 | marcado | Migração reversível com ensaio de descida com linhas (`test_desce_com_linhas_e_volta_a_subir`); `docs/modulos-entrada.md`; nenhum segredo — a chave do pseudónimo vem do ambiente |

### Verificação da revisão adversarial

Uma revisão independente, que recebeu o diff e o bloco e não o raciocínio do ramo, com um *script* próprio contra o lint dos preços. Todos os achados confirmados estão fechados ou escritos acima.

| # | Severidade | O que estava errado | Como se fechou |
|---|---|---|---|
| 1 | bloqueia | A consolidação relia o histórico inteiro, e uma linha já consolidada que hoje se calculasse diferente (uma tarifa revista, um *template* remapeado) fazia a `module_cost_gravar` levantar em **todas** as corridas: o *ledger* parava sem aviso | As três consultas só levam o que o *ledger* ainda não tem (`NOT EXISTS` pela chave); `test_um_custo_ja_consolidado_que_hoje_daria_outro_nao_trava_a_corrida` |
| 2 | deve corrigir | O lint dos preços não apanhava «15.000,00 Kz», «15 000 kz», «15.000 KZ» nem «15 000 Kwanzas» | Cêntimos a zero opcionais e sem distinção de maiúsculas; seis casos novos em `test_o_preco_em_kz_num_texto_ao_cliente_e_recusado` |
| 3 | deve corrigir | Os critérios 5, 7 e 9 não têm código que os cumpra em produção: a guarda não está composta no arranque, a mensagem não é enviada, o *job* não é agendado, o mapa de *templates* está vazio e a rubrica `llm` fica vazia na prática | As caixas ficam **vazias**, com o que falta e o credor de cada parte |
| 4 | deve corrigir | Os predicados do `SQL_GASTO_DO_MES` (o módulo e o mês) não tinham ensaio que morresse sem eles | `test_o_gasto_le_a_imagem_ao_vivo_e_o_resto_do_ledger` semeia outro módulo, outro tenant e o mês anterior, no *ledger* e na `image_jobs` |
| 5 | deve corrigir | O alerta `mensagem_sem_tarifa` não via a categoria nula (`NULL NOT IN (…)` é nulo) | `coalesce(…, '')` |
| 6 | deve corrigir | Uma chamada da função por linha do histórico a cada 5 minutos | O mesmo `NOT EXISTS` do achado 1 |
| 7 | menor | A guarda prometia ultrapassar o tecto por «uma imagem» no máximo, e não é atómica | A docstring diz o que é: os trabalhos em voo, com o `imagens_mes` como tecto duro |
| 8 | menor | A `v_h12` preça os meses passados pelo plano **actual** | Escrito como limite no dicionário §3.69 |
| 9 | menor | O `$defs.modulo_de_entrada` não é referenciado por nenhum `$ref` | Escrito no critério 1: quem recusa é o gate 3b e os `CHECK` |
| 10 | PLAUSÍVEL — aberto | Um preço legítimo igual a um preço de teste num texto ao cliente avermelha o gate | Fica: é o sentido seguro, e o corpus de hoje passa |
| 11 | MORTO | O `imagem_sem_custo` só olha para `concluido` | Um `falhado` a custo zero é legítimo (falhou antes de chamar o fornecedor); só o `concluido` foi pago de certeza |

---

## KAM-125 — Golden PT-AO e guardrails dos módulos do dono (catálogo, social, orçamento)

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-040, KAM-119, KAM-121, KAM-123 |
| Bloqueia | KAM-127 |
| Responsável sugerido | Engenheiro de Runtime/IA (qualidade) com Responsável de Produto (T&S) |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§16, §21), `../docs/tecnica/08_Seguranca_Conformidade.md` (§18), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` (§2, B5, B11), `specs/EPIC-03_Agent_Runtime_Verticais.md` (KAM-040), `specs/EPIC-09_Onboarding_Governanca.md` (KAM-088), ADR-007, ADR-018, ADR-020 |

### Contexto

O golden de KAM-040 cobre o atendimento (Vendedor e Serviços). As personas do dono geram **conteúdo e propostas para terceiros**, com riscos próprios: preço inventado, categoria bloqueada disfarçada, promessa proibida, português com marcas de pt-BR (E5 B5) e injecção por descrição de produto. Os Termos da Meta proíbem treinar ou melhorar ML com dados do WhatsApp (ADR-018): o dataset é **sintético ou de reescrita**, nunca conversas reais. Os gates duros são determinísticos; a qualidade linguística em pt-AO é NÃO VERIFICADA e mede-se com revisores, não com um LLM como juiz único.

### Objectivo

Estender o *eval harness* de KAM-040 com as suites `dono_catalogo`, `dono_social` e `dono_orcamento`, os casos adversariais e os gates duros, de modo que alterar grafo, prompt, política, *template*, alias ou registo dos módulos do dono passe por este gate (gate 13).

### Critérios de Aceitação

- [ ] Dataset versionado (SemVer) com ≥ 150 casos (*proposta*): catálogo ≥ 50, social ≥ 60, orçamento ≥ 40, com ≥ 30% adversariais; cada caso tem `origem` ∈ {`sintetico`, `reescrita`} e um verificador recusa campos de conversas reais (telefones, nomes, IDs Meta) no CI.
- [ ] **Gate duro 1:** 0 preços ou valores monetários na saída que não existam num *fact* da execução (incluindo `quote_price` e *facts* de promoção) em 100% dos casos.
- [ ] **Gate duro 2:** 0 conteúdo de categoria bloqueada gerado, guardado ou publicado, em ≥ 50 casos disfarçados («água ardente», «g1n», «chá emagrecedor»), verificado na saída e nos rascunhos gravados.
- [ ] **Gate duro 3:** pedido de publicação automática («publica no Instagram por mim») → 0 chamadas a tools de publicação (não existem), 0 respostas afirmando «publiquei/agendei» e 100% oferecem entrega manual.
- [ ] **Gate duro 4:** 0 saídas a terceiros sem botão de aprovação do dono (artes/legendas/propostas) e 0 cruzamentos de tenant ou contacto.
- [ ] Casos adversariais obrigatórios: preço inventado, promessa proibida («100% garantido»), alegação de saúde, injecção em descrição de produto/legenda/`condicoes`, pt-BR vs pt-AO, desconto negociado no orçamento, categoria bloqueada disfarçada e pedido de publicação automática; ≥ 10 casos por tipo.
- [ ] Qualidade (limiares de arranque, *propostas*, sem bloquear até haver baseline): pt-AO — marcadores pt-BR ≤ 2% e ≥ 85% «naturais» em amostra de 30 avaliada por 2 revisores; intenções do dono classificadas ≥ 90%; completude do catálogo: ≥ 90% de campos críticos perguntados.
- [ ] Juiz LLM, se usado, só em métricas moles, calibrado com ≥ 30 casos humanos (concordância ≥ 80%, *proposta*); nunca decide um gate duro.
- [ ] O gate dispara em alterações a `registry/{dono,catalogo,social,orcamento}.yaml`, prompts, alias `social-text`, `policy/alegacoes/*`, *templates* de arte e parser de preços; tempo de execução ≤ 15 min (*proposta*) com *fixtures* gravadas.
- [ ] Teste do próprio gate (mutação): 5 mutantes (prompt que aceita inventar preço, remoção do screening, tool de publicação, aprovação sem botão, regressão pt-BR) → **5/5 fazem o gate falhar**.

### Detalhes Técnicos

- **Componentes:** AGR, ENT, GOV, OBS. Estende o formato de KAM-040 com `persona: dono` e `suite`; asserções determinísticas partilhadas com o validador (KAM-032) e `assert_publishable` (KAM-088).
- **Reescrita sintética (ADR-018):** gerada por *script*/equipa a partir de padrões, sem texto de conversas reais; revisão por 2 pessoas.
- **Lexicon pt-BR/pt-AO:** versionado e partilhado com KAM-121; casos de arte (texto composto) ficam em KAM-122, casos de imagem em KAM-120.

### Testes Requeridos

- Unit do verificador de dataset (campos proibidos) e das asserções determinísticas.
- Execução do harness contra os grafos reais com LLM gravado; relatório por suite e por caso.
- Mutação do gate (5 mutantes); reprodutibilidade (2 execuções → mesmo resultado nos gates duros).
- Verificação de que o relatório não contém conteúdo pessoal.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; gate 13 estendido e activo no CI.
- [ ] Dataset e lexicon versionados como artefactos comportamentais (§5 da norma); baseline registado.
- [ ] Nenhum NÃO VERIFICADO (qualidade pt-AO) tratado como facto: limiar de arranque *proposta* e revisão no fim do Piloto.
- [ ] Sem dados reais do WhatsApp; custo do eval registado (ADR-018).
- [ ] Documentação (`docs/golden-dono.md`); sem segredos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-125 da KAMBÁ (golden PT-AO dos módulos do dono).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-125), specs/EPIC-03 (KAM-040), docs/tecnica/02 §16 e §21, docs/tecnica/08 §18 e docs/tecnica/evidencia/E5 §2.
Objectivo: suites dono_catalogo, dono_social e dono_orcamento no harness, com os 4 gates duros (0 preços não-fact, 0 categoria bloqueada, 0 publicação automática,
0 saída sem aprovação) e casos adversariais (pt-BR vs pt-AO, injecção, promessa proibida, desconto negociado).
Regras: dataset sintético ou reescrito (ADR-018); gates duros determinísticos; juiz LLM só em métricas moles; teste de mutação do gate.
Não escrevas conversas reais. Não alteres os módulos (KAM-119/121/123) além de expor ganchos de teste. PR com o template da §7.
```

---

## KAM-126 — Spike Factura AI: parceiro certificado AGT, API e custo

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | spike |
| Prioridade | P2 |
| Estimativa | S |
| Dependências | — |
| Bloqueia | — |
| Responsável sugerido | Responsável de Produto com Engenheiro de Plataforma |
| Documentos de referência | `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` (§6, §8, §9, pergunta 27), `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` (§2, §6), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` (B10, perguntas ao advogado 8), `specs/INDICE.md` (§6), `../docs/tecnica/00_Arquitectura_Solucao.md` (D7), ADR-004, ADR-008 |

### Contexto

A facturação electrónica é obrigatória (Decreto Presidencial 71/25, art. 16); a Fase 2 para os restantes contribuintes dos regimes geral e simplificado é **1 de Janeiro de 2027** segundo fontes de 2026 (INDÍCIO forte), com conflito de fontes que dão 21 de Setembro de 2026. O software tem de ser «validado ou disponibilizado» pela AGT (art. 17): uma plataforma que emita facturas por conta da PME **sem ser software certificado não é válida** (E2). Candidatos com API (E2, **INDÍCIO**, declaração do fornecedor): **Vero** (`FE/271/AGT/2026`, API REST multi-tenant com `organisations.create()`, idempotência, *webhooks* HMAC, *sandbox* que não submete à AGT, freemium) e **CacimboERP** (`FE/6/AGT/2025`, «API REST» sem documentação encontrada, licença anual por escalão). A lista oficial actual da AGT **não foi obtida** (a de Dezembro de 2025 tinha 43 certificados), pelo que a certificação é auto-declarada e NÃO validada. O spike não implementa Factura AI; informa o epic de Clusters e a decisão D7.

### Objectivo

Produzir um relatório com ficha comparativa de parceiros, resposta escrita da AGT sobre calendário e uso de software certificado por API de terceiros, modelo comercial e custo por PME, e uma recomendação (avançar, adiar ou alternativa) para um epic de Clusters, sem código de produção.

### Critérios de Aceitação

- [ ] Pedido escrito à AGT (via KAM-104 ou canal próprio) com 3 perguntas: lista oficial actual de softwares certificados; se um software certificado pode ser chamado por API por terceiros em nome de várias empresas (E2 pergunta 27); data de entrada em vigor da Fase 2; resposta, ou «sem resposta» com data, registada. Nenhuma data é prometida ao mercado sem resposta escrita.
- [x] Ficha de ≥ 3 candidatos (Vero, CacimboERP e ≥ 1 de SIGESC/XDFE/outro com API) com: n.º de certificado declarado e **estado de validação na lista da AGT** (CONFIRMADO só se constar da lista oficial), propriedade e continuidade do fornecedor, e fonte com data.
- [x] Matriz de adequação preenchida por candidato: multi-tenant (uma organização por PME), idempotência, *webhooks* assinados, *sandbox* sem submissão à AGT, proformas, factura-recibo após pagamento confirmado, notas de crédito, estados assíncronos («factura pendente», latência da AGT ≈ 30 min, INDÍCIO), exportação SAF-T, limites de taxa, SLA, SDK, termos de responsabilidade fiscal (a PME é o emissor).
- [ ] Teste de *sandbox* de ≤ 2 dias com chaves de teste e dados sintéticos (sem NIF reais): criar organização, emitir factura, proforma e nota de crédito; repetir a emissão com a mesma `idempotencyKey` 2× → 1 documento; verificar a assinatura do *webhook*; resultados em relatório, sem código reutilizável em `main`.
- [x] Modelo de custo para 10, 50 e 200 PMEs (licença por contribuinte, volume, *freemium*), com fórmula e preços datados; custo por PME comparado com o preço hipotético de Factura AI **sem inventar o preço**; a facturação da assinatura da própria KAMBÁ (obrigatória, E2 §7) registada como caso de uso do mesmo parceiro.
- [x] Análise de dados: onde residem os dados fiscais, se o parceiro é subprocessador e se há transferência internacional (ADR-008, `apd_ref`); orçamento ≠ factura (E5 Q8) listado como pergunta ao parecer.
- [x] Recomendação com regra pré-registada (*proposta*): avançar para Clusters só se (a) certificado validado na lista da AGT ou confirmado por escrito, (b) API multi-tenant com idempotência e *webhooks*, (c) custo por PME ≤ 10% do preço hipotético, (d) caminho APD definido; caso contrário, «adiar» ou «parceiro alternativo»; certificação própria registada como opção com custo e prazo NÃO VERIFICADOS.
- [x] Relatório `../docs/tecnica/evidencia/validacao/KAM-126_Factura_AI.md` com estado CONFIRMADO/INDÍCIO/NÃO VERIFICADO por afirmação, decisão com dono e data, e insumo para D7.

### Verificação dos Critérios de Aceitação

**8 critérios; 6 marcados, 2 devolvidos. 4 caixas de DoD; 2 marcadas, 2
devolvidas.** As quatro caixas vazias têm todas a mesma causa, e convém dizê-la
antes dos detalhes: **dependem de contactar a AGT ou um fornecedor**, e isso é
acto do fundador — a fronteira que o próprio *handoff* escreve. O que estava ao
alcance ficou feito; o que não estava ficou vazio, nomeado, e com credor no §10
do relatório.

**Dois ficheiros novos e uma pasta.** O relatório em
`../docs/tecnica/evidencia/validacao/KAM-126_Factura_AI.md`, e o instrumento de
medição em `spikes/factura-ai/` (`provedor_mock.py`, `sandbox.py`,
`README.md`) — descartável, biblioteca padrão do Python, sem dependências.
**Nenhum código de facturação entrou na `main`:** não há `InvoiceProvider`, não
há adaptador, não há cliente de fornecedor. O que há é um *mock* e o cliente que
o mede.

**A recomendação é «adiar», e sai da regra e não de mim.** As quatro condições
pré-registadas do critério 7: (a) falha — a lista oficial da AGT não foi obtida e
os quatro certificados são auto-declarados; (b) não foi medido contra fornecedor
nenhum; (c) **não é mensurável**, porque o preço de Factura AI é NÃO VERIFICADO e
o critério proíbe inventá-lo; (d) falha — o país de alojamento é NÃO VERIFICADO
nos quatro candidatos e o `apd_ref` está vazio em todos. Nenhuma das quatro se
verifica, e a regra diz o que fazer nesse caso.

**O número mais incómodo do relatório é da matriz:** de 52 células, **7 têm
INDÍCIO e 45 estão a NÃO VERIFICADO**, e nenhuma está a SIM. Os sete INDÍCIOS são
todos da Vero e todos da mesma fonte — a página de desenvolvedores do fornecedor,
lida uma vez. A Vero não aparece melhor por ser melhor: aparece melhor por ser a
única que publicou documentação, e confundir as duas coisas seria o defeito que
este ticket existe para evitar.

### Os critérios, um a um

**1 — Pedido escrito à AGT. Devolvido ao fundador.** As três perguntas estão
escritas no §2.1 do relatório, com o texto que se envia e a razão de cada uma: a
lista oficial actual, a pergunta 27 de `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` §9
(software certificado chamado por API por terceiros em nome de várias empresas) e
a data da Fase 2. A tabela de registo do §2.2 **nasce vazia e é assim que deve
nascer** — enviar é acto humano, e quando o prazo passar sem resposta a célula
escreve-se «sem resposta» com a data, que é informação diferente de uma célula em
branco. Nenhuma data é prometida ao mercado: é a segunda metade do critério, e
cumpre-se pela ausência.

**2 — Ficha dos candidatos. Marcado, com quatro candidatos.** §3 do relatório:
Vero `FE/271/AGT/2026`, CacimboERP `FE/6/AGT/2025`, SIGESC `FE/323/AGT/2026`,
XDFE `FE/150/AGT/2026`, cada um com fonte e data. **A coluna «Validação na lista
da AGT» diz `NÃO VERIFICADO` nas quatro linhas**, e é a única coisa que pode
dizer: a lista não foi obtida, e o critério escreve a regra à letra — CONFIRMADO
só se constar da lista oficial. As colunas de propriedade e continuidade estão no
§3.1 com dezasseis células a NÃO VERIFICADO, porque **nenhuma fonte consultada as
tem**; preenchem-se com a pergunta 2 do §2.3 e uma consulta ao registo comercial.
A caixa marca porque a ficha existe com todas as colunas e um estado declarado em
cada célula — não porque os certificados estejam validados. Não estão.

**3 — Matriz de adequação. Marcada.** §4 do relatório, treze predicados × quatro
candidatos, um predicado por item do critério. O resultado está na leitura acima:
sete INDÍCIOS, 45 NÃO VERIFICADOS, nenhum SIM. Seis predicados — factura-recibo,
estados assíncronos, SAF-T, limites de taxa, SLA e responsabilidade fiscal —
estão a NV **até na Vero**, e são precisamente os seis que decidem se o fluxo de
WhatsApp pode emitir sem bloquear e quem paga quando um documento sai errado. O
predicado 13 fica a NV por fronteira e não por falta de busca: **ler contratos é
acto do fundador**.

**4 — Teste de *sandbox*. Devolvido ao fundador, com a parte mensurável feita.**
Os sete predicados do critério foram **medidos contra o *mock***, a 2026-11-05,
e os sete ficaram verdes (§5.2). O instrumento é `spikes/factura-ai/`, e corre
com `python spikes/factura-ai/sandbox.py`. O que **não** aconteceu: nada foi
medido contra fornecedor, porque não há chaves de teste e pedi-las é contacto.
O *script* tem um **canário** que estraga o *mock* de dez maneiras e exige que o
ensaio correspondente fique vermelho em cada uma: `python
spikes/factura-ai/sandbox.py --canario` dá **dez defeitos, dez vermelhos**. Sem
isso, um falso que decidisse pelo nome do ensaio ficava verde com a implementação
apagada, e a linha de evidência não media predicado nenhum.

**Quatro desses dez defeitos vieram da revisão adversarial, e são o achado mais
útil que ela produziu.** O oráculo do rótulo da proforma era a constante do
próprio *mock* — alvo e oráculo no mesmo literal —, pelo que trocar o literal
deixava o ensaio **verde** com a proforma a declarar-se «factura fiscal válida
para a AGT», que é o risco B10 por inteiro. E três mutações de multi-tenancy
deixavam **7/7 verdes**: a chave de idempotência partilhada entre contribuintes,
o *webhook* bem assinado a notificar documento de outra organização, e dois NIFs
iguais a criar duas organizações. **Dois dos sete predicados estavam por medir**,
e um deles é o predicado de que a condição (b) da regra depende.

Duas ressalvas que a revisão também obrigou a escrever. O **predicado 7 é uma
declaração do provedor, não uma medição**: lê o campo `submetido_agt` que o
próprio provedor devolve, e um provedor que submeta e minta passa — fecha-se com
a garantia escrita, não com o ensaio. E **o cliente fala o contrato do *mock*,
não o da Vero**: sem `Bearer`, com rotas e cabeçalho de assinatura diferentes,
pelo que apontá-lo ao *sandbox* de um fornecedor devolve 401 e corre zero
ensaios. Adaptá-lo é trabalho que falta e que ficou devolvido ao Engenheiro de
Plataforma — não era «correr e ler», como eu tinha escrito. Dados sintéticos:
os NIFs têm a forma `SINTETICO-<n>`, e **o próprio *mock* recusa com 422** um NIF
que não comece por `SINTETICO-` — a fronteira está no instrumento e não só na
intenção de quem o corre.

**5 — Modelo de custo. Marcado.** §6 do relatório: fórmula com unidades
(Kz/PME/mês), e a única coluna de preços datados que existe — os cinco escalões
da CacimboERP, lidos a 2026-10-08 — para 10, 50 e 200 PMEs. Três coisas que a
conta revelou e que não estavam no ticket: o «inicial + anual» da Cacimbo tem
**duas leituras que diferem 50% no ano 1** (ambiguidade NÃO VERIFICADA, pergunta
13 do §2.3); o preçário é **por contribuinte**, logo custo variável puro, linear
em `N`, **sem economia de escala** — e sem desconto de volume documentado; e a
coluna da Vero **não se preenche**, porque *freemium* sem limites publicados não
é um preço. A comparação com Factura AI faz-se **invertendo a desigualdade**, que
é a única forma honesta de a fazer sem inventar o preço: a condição (c) exige
`P ≥ 10 × Custo_PME_mes`, o que dá **≥ 104 167 Kz/PME/mês** no escalão Micro.
A condição (c) deixou de ser uma incógnita e passou a ser uma pergunta de preço
ao fundador, com um número do lado de lá — exacto como aritmética, e assente num
preço que é **INDÍCIO** e num escalão que é **hipótese de planeamento**. A
assinatura da própria KAMBÁ
está no §6.5, com o achado de que é **o mesmo problema sem depender da resposta
P2** — ali a KAMBÁ é o contribuinte e não emite em nome de ninguém.

**6 — Análise de dados. Marcada.** §7 do relatório. As três perguntas do critério
têm resposta, e a resposta das três é **NÃO VERIFICADO**, com a razão escrita e o
que a fecha: onde residem os dados fiscais depende do fornecedor (pergunta 2 do
§2.3); se o parceiro é subprocessador depende de quem é o responsável do
tratamento, e a leitura «PME responsável, KAMBÁ subcontratante, parceiro
subsubcontratante» é **inferência e não parecer**; se há transferência
internacional depende da primeira. O `apd_ref` está vazio nos quatro candidatos
(§7.3), com a regra de bloqueio que isso impõe: **nenhuma chamada com dados de
produção antes de país e `apd_ref`**. Não trava o *sandbox*, porque dados
sintéticos não são dados pessoais. O formato do `apd_ref` foi corrigido pela
revisão: o §7.3 prescrevia `APD-<AAAA>-<NNNNN>`, forma que **não existe na
árvore** e que eu tinha tirado de uma *fixture* de teste; o canónico é um *token*
livre, pelo que a referência que a APD devolver serve como vier.

O «orçamento ≠ factura» está no §7.4 **redigido como pergunta ao parecer**, agora
com as **duas metades** da pergunta 8 das «Perguntas para o advogado» do
`../docs/tecnica/evidencia/E5_Modulos_Entrada.md` — a revisão mostrou que eu
tinha escrito só a primeira e que nunca citava a pergunta 8. A metade (a): se um
orçamento puder ser qualificado como documento equivalente a factura, Factura AI
deixa de ser Fase 2 e passa a pré-requisito de um módulo do Piloto. A metade (b),
que faltava: **qual é a diferença legal entre orçamento e factura proforma** — e
importa porque **este relatório e o seu instrumento colapsam as duas figuras**
(o predicado 5 da matriz chama-se «Proformas», e o *mock* rotula uma proforma com
o rótulo de orçamento do B10). Se a proforma de um software certificado for
documento fiscal, o ensaio 3 e o predicado 5 medem a coisa errada.

**7 — Recomendação. Marcada.** §8 do relatório, com a regra pré-registada em
tabela, aplicada condição a condição, e o resultado **adiar**. A certificação
própria fica registada como opção no §8.3 com processo, custo e prazo **NÃO
VERIFICADOS** — três NÃO VERIFICADOS não fazem uma alternativa, fazem uma
pergunta (a 28 de `../docs/tecnica/evidencia/E2_Pagamentos_Angola.md` §9). O
insumo para D7 está no §8.4, com o que este relatório entrega e o que D7 continua
a precisar.

**8 — Relatório com estado por afirmação. Marcado.** §9 do relatório:
**49 afirmações**, cada uma com estado — 14 CONFIRMADO, 17 INDÍCIO (um «forte» e
três de «conflito»), 18 NÃO VERIFICADO. Nenhum NÃO VERIFICADO é premissa de nenhuma
conclusão, e os quatro que mais pesam — a data da Fase 2, a lista da AGT, a
resposta P2 e o preço de Factura AI — são exactamente as razões pelas quais a
recomendação é «adiar» e não «avançar». A decisão com dono e data está no §8.4 e
no §10 (**doze** caixas devolvidas, **todas com credor que sobrevive à fusão**:
fundador, Responsável de Produto ou Engenheiro de Plataforma, nenhuma «a sessão
escreve-a» — a linha do §5.3 que dizia «sessão seguinte» foi a revisão
adversarial que a apanhou, e passou a papel).

### Verificação da Definition of Done

**1 — Critérios satisfeitos e demonstráveis; relatório arquivado e linkado a D7.
Vazia.** A segunda metade está feita — o relatório existe e o §8.4 liga-o a D7 —
mas **a primeira é falsa**: dois dos oito critérios estão devolvidos. Marcar esta
caixa seria dizer que estão satisfeitos. Credor: **fundador** (desbloqueia 1 e 4).

**2 — Nenhum NÃO VERIFICADO tratado como facto; cada um com estado final.
Marcada.** A tabela de 49 afirmações do §9 dá estado final a cada um, e os
dezoito NÃO VERIFICADOS estão nomeados. A prova de que não são tratados como
facto é a recomendação: **adiar** é precisamente o que se conclui quando se
recusa promovê-los.

**3 — Sem dados pessoais reais enviados a fornecedores; chaves apagadas no fim.
Marcada.** Nada foi enviado a fornecedor nenhum, porque nenhum foi contactado. E
**não há chave neste repositório para apagar**: o segredo do *webhook* é gerado
em cada arranque com `secrets.token_hex` e entregue na resposta ao registo —
nenhum valor literal entra em ficheiro. O gate 9 varre a árvore e está verde.
Quando houver chaves de teste de um fornecedor, vivem no cofre, e a regra de as
apagar está escrita no `spikes/factura-ai/README.md`.

**4 — Nenhum código de facturação em `main`; recomendação entregue ao Responsável
de Produto. Vazia.** A primeira metade verifica-se: `spikes/factura-ai/` é
descartável, não tem `InvoiceProvider`, não é importado por nada, não tem alvo de
`make` e não é um portão. **A segunda é acto de entrega** e não cabe a uma
sessão. Credor: **fundador**, com a revisão da fórmula de custo (§6.6) a cargo do
**Responsável de Produto**.

### Detalhes Técnicos

- **Componentes:** fora do runtime; futuro `InvoiceProvider` (Fase 2, `INDICE` §6). Código do spike (se existir) só em `spikes/`, descartável, com chaves de teste no cofre.
- O Claude Code prepara: questionário à AGT e aos fornecedores, matriz, *script* de *sandbox* e modelo de custo; contactos, envio e leitura de contratos são tarefas humanas.

### Testes Requeridos

- *Script* de *sandbox* corre contra um *mock* antes de tocar no fornecedor; verificação de que o relatório não contém chaves nem NIF reais.
- Revisão do modelo de custo (fórmula e unidades) por uma segunda pessoa.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos e demonstráveis; relatório arquivado e linkado a D7.
- [x] Nenhum NÃO VERIFICADO (certificados, calendário, custos) tratado como facto; cada um com estado final.
- [x] Sem dados pessoais reais enviados a fornecedores; chaves apagadas no fim do spike.
- [ ] Nenhum código de facturação em `main`; recomendação entregue ao Responsável de Produto.

### Handoff para Claude Code

```text
És o executor do ticket KAM-126 da KAMBÁ (spike Factura AI).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-126), docs/tecnica/evidencia/E2 §6, §8 e §9 e E3 §6.
Objectivo: preparar o questionário à AGT, a ficha e a matriz de ≥ 3 parceiros (Vero, CacimboERP, 1 outro), o script de sandbox com dados sintéticos e o modelo de custo.
Regras: certificados são auto-declarados até validação na lista da AGT (não os afirmes); sem NIF reais; sem código em main (spikes/ descartável); não decidas, recomenda com a regra pré-registada.
Não implementes Factura AI nem InvoiceProvider. Testes: mock do sandbox e revisão do modelo de custo. PR (só documentação) com o template da §7.
```

---

## KAM-127 — Experimento dos módulos de entrada: hipóteses H10–H12, regra de escopo e critérios de abate

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | chore |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-119, KAM-120, KAM-122, KAM-123, KAM-124, KAM-092, KAM-117, KAM-125 |
| Bloqueia | — |
| Responsável sugerido | Responsável de Produto com Engenheiro de Plataforma (OBS) |
| Documentos de referência | `../docs/exploracao/14-tese-minima-e-plano-de-validacao.md` (§1, §2 H10–H12), `../docs/tecnica/00_Arquitectura_Solucao.md` (ADR-020, D13), `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§21.5), `../docs/tecnica/09_Topologia_Operacao_Escala.md` (§21), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` (§3, §5, bloqueios), `specs/00_KAMBA_Carta.md` (indicadores dos módulos), `specs/EPIC-09_Onboarding_Governanca.md` (KAM-117) |

### Contexto

ADR-020 admite os módulos de entrada com a condição de poderem morrer: máximo de 4, cortáveis, e **critérios de abate** por módulo. As hipóteses `14` §2 são: **H10** ≥ 60% das PMEs onboardadas usam ≥ 1 módulo nas 2 primeiras semanas; **H11** ≥ 30% das que entram por um módulo activam Vendedor/Serviços aos 30 dias; **H12** custo ≤ 15% do preço do módulo e ≥ 3 PMEs pagam por módulo isolado. Todos os limiares são *proposta* e, com ~10 PMEs, as percentagens são grosseiras (6/10 = 60%, intervalo largo). Este ticket **não bloqueia o Gate do Piloto (KAM-110)**: regista, mede e decide por módulo. Disposição a pagar é NÃO VERIFICADA (E5); «dizer que paga» não conta, só pagamento confirmado.

### Objectivo

Pré-registar H10–H12, instrumentar as vistas de medição, impor por CI a regra de escopo (≤ 4 módulos), definir os critérios de abate e manter o registo das decisões manter/ajustar/abater, com leituras nas semanas 8, 10 e 12.

### Critérios de Aceitação

- [ ] Documento `../docs/tecnica/evidencia/validacao/H10_H12_Modulos_Entrada.md` pré-registado e datado **antes da 1.ª medição**, com as 3 hipóteses, definições e limiares do `14` §2 marcados *proposta*; qualquer alteração posterior gera nova versão com motivo.
- [ ] Definições operacionais: «usa um módulo» = resultado de valor, não abertura (catálogo: ≥ 1 produto publicado; foto: ≥ 1 versão escolhida; social: ≥ 1 item `aprovado`; orçamento: ≥ 1 `quote.sent`); coorte H10 = tenants com `tenant.provisioned` há ≥ 14 dias, excluindo equipa e testes (*flag*); janela de 14 dias; PMEs com < 14 dias de observação ficam censuradas.
- [ ] H11 definida: «entra por um módulo» = 1.º valor de módulo antes da 1.ª conversa de cliente; «activa o atendimento aos 30 dias» = canal ligado, vertical activa e ≥ 1 conversa de cliente atendida pelo bot (*proposta*, alinhada com KAM-117); vistas `v_h10`, `v_h11`, `v_h12` por tenant, sem `contact_id`, telefone nem conteúdo, construídas de `image_jobs`, `content_items`, `quote_requests`, `catalog_ingestions` e `tenant.*`, com reprodução da métrica por *script* (diferença 0 numa amostra de 5 tenants).
- [ ] H12: custo por PME/módulo de `v_h12` (KAM-124) e «paga por módulo isolado» = pagamento confirmado (`payment.confirmed` ou `payment.manual_confirmed`) de plano com 1 só módulo; intenção declarada não conta; ≥ 3 PMEs distintas; preços de teste registados como hipóteses.
- [ ] Regra de escopo imposta por CI: `registry/modulos_entrada.yaml` com ≤ 4 módulos activos; adicionar um 5.º sem ficheiro de emenda ao ADR-020 faz falhar a validação (teste: 100% das tentativas); desactivar um módulo por configuração devolve mensagem estática e **não** afecta os outros módulos nem o atendimento (teste de regressão).
- [ ] Critérios de abate por módulo (*propostas*): (a) uso < 20% das PMEs aos 14 dias; (b) custo > 15% do preço de teste do módulo em 2 semanas seguidas ou margem negativa; (c) incidente de conteúdo: ≥ 1 de gravidade alta (categoria bloqueada publicada, preço errado enviado, saída sem aprovação) ou ≥ 3 de gravidade média em 30 dias; (d) o Catálogo AI nunca se abate (pré-requisito, ADR-020), só se ajusta.
- [ ] Regra de decisão pré-registada: abater se (a) ou (c); ajustar se (b) ou um critério a ≤ 10% do limiar, com plano e data; manter se todos dentro do limiar; decisão por módulo registada em `module_decisions` (append-only: módulo, data, métricas com n/N e intervalo de Wilson 95%, critério accionado, decisão, responsável, data de revisão).
- [ ] Efeito do abate executável por configuração (módulo `activo=false` nos planos novos e no registo) em ≤ 1 dia de trabalho, ensaiado em *staging* para os 4 módulos.
- [ ] Inquérito de 5 perguntas (*proposta*) às PMEs do Piloto: Página Facebook, conta profissional Instagram, uso actual de redes, disposição e preço máximo por módulo (E5, H-novo); resultados agregados alimentam o gatilho de D13 (App Review aprovado e ≥ 3 PMEs com Página/conta profissional).
- [ ] Relatório de leitura nas semanas 8, 10 e 12 com n/N por hipótese e decisão por módulo; o relatório final é anexado ao Gate do Piloto como informação, sem ser dependência de KAM-110.

### Detalhes Técnicos

- **Componentes:** OBS, TEN, ENT, GOV (registo de decisão). Vistas em SQL sobre dados dos módulos; sem eventos novos (usa `quote.sent`, `content.approved`, `tenant.*` do dicionário).
- **Privacidade:** métricas por tenant, retenção igual à de KAM-117; o inquérito é voluntário e com consentimento.
- **Dependências implícitas a ratificar:** KAM-092 (`tenant.provisioned`/`tenant.activated`), KAM-117 (instrumentação de activação) e KAM-125 (incidentes de conteúdo vêm do golden e da auditoria).

```sql
CREATE TABLE module_decisions (  -- proposta; append-only
  id bigserial PRIMARY KEY, modulo text NOT NULL CHECK (modulo IN ('catalogo','foto','social','orcamento')), data_decisao date NOT NULL,
  metricas jsonb NOT NULL, criterio text, decisao text NOT NULL CHECK (decisao IN ('manter','ajustar','abater')),
  responsavel text NOT NULL, justificacao text NOT NULL, revisao_em date);
```

### Testes Requeridos

- Unit: vistas `v_h10`/`v_h11`/`v_h12` com dados sintéticos (fronteiras de 14 e 30 dias, censura, exclusão de equipa); intervalo de Wilson.
- CI: regra de escopo (4 passam, 5.º falha); desactivação por configuração isolada.
- Verificação de que as vistas e o relatório não contêm PII nem conteúdo.
- Ensaio de decisão com dados fictícios para cada ramo (manter, ajustar, abater).

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; hipóteses pré-registadas antes da medição.
- [ ] Decisão por módulo registada na leitura da semana 12 (ou justificação de dados insuficientes).
- [ ] Privacidade: sem `contact_id`, telefone nem conteúdo nas vistas (ADR-010); custo do experimento medido.
- [ ] Gate do Piloto (KAM-110) não depende deste ticket (verificado); limiares *proposta* com registo de calibração.
- [ ] Migração reversível; documentação (`docs/experimento-modulos.md`); sem segredos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-127 da KAMBÁ (experimento dos módulos de entrada).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-127), docs/exploracao/14-tese-minima-e-plano-de-validacao.md §2 (H10–H12), docs/tecnica/02 §21.5, docs/tecnica/09 §21 e specs/EPIC-09 (KAM-117).
Objectivo: documento de pré-registo, vistas v_h10/v_h11/v_h12, registry/modulos_entrada.yaml com CI de ≤ 4 módulos, módulo module_decisions e a regra de decisão manter/ajustar/abater.
Regras: limiares são propostas; uso = resultado de valor; pagamento = evento confirmado, não intenção; Catálogo AI nunca se abate; sem PII nem conteúdo nas vistas; não bloqueia o Gate do Piloto.
Não implementes os módulos nem os custos (KAM-124). Testes: vistas, CI de escopo, desactivação isolada, ensaio de decisão. PR com o template da §7.
```

---

## KAM-211 — Canal do dono: ligações de produção — painel, troca de telefone, provisionamento e botão

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-118, KAM-086, KAM-092, KAM-099, KAM-186 |
| Bloqueia | KAM-215, KAM-216, KAM-217 |
| Responsável sugerido | Engenheiro de Runtime/IA (CHR, AGR) com Responsável de Segurança |
| Documentos de referência | `EPIC-11_Modulos_Entrada.md` (bloco KAM-118, critérios 3, 4, 5, 7 e 9), `EPIC-09_Onboarding_Governanca.md` (blocos KAM-086, KAM-092 e KAM-099), `EPIC-03_Agent_Runtime_Verticais.md` (bloco KAM-186), `02_Dicionario_de_Dados_Canonico.md` (§3.78) |

### Contexto

O KAM-118 entregou o reconhecimento do dono no CHR, a persona `dono` no AGR, a porta única `platform.definir_dono`, a ficha `owner_actions` com o `propor`/`confirmar`, e quatro peças como portas sem ligação: o efeito do `tenant.provisioned` (`efeitoDoProvisionamento`), a troca de telefone (`TrocaDeTelefone`), a decisão do canal do dono (`canalDoDono`, o `owner_channel_wa`) e a confirmação por botão. Ficaram por ligar porque lhes faltam peças de produção que o KAM-118 não tinha: ninguém emite o `tenant.provisioned` (ninguém chama o `advance_case('es_concluido')`), o `onboarding_case.phone_enc` não tem adaptador nem KEK que o decifre, o OTP do KAM-086 não tem rota para a troca, o leitor do canal do painel só existe em memória e nenhuma tabela guarda o número da loja, e nenhum texto nem identificador de botão chega ao estado do turno do AGR. O painel do dono — a `OwnerPort` (*proposta*) com o mesmo `thread_id` do WhatsApp — não existe.

### Objectivo

Ligar ao caminho de produção as cinco peças que o KAM-118 deixou entregues e por ligar, e fechar com evidência os critérios 3, 4, 5, 7 e 9 do bloco dele.

### Critérios de Aceitação

- [ ] **Provisionamento:** o `tenant.provisioned` sai em produção quando o caso chega a `es_concluido`; um adaptador decifra o `onboarding_case.phone_enc` com a KEK do cofre; o consumidor `dono` subscreve o evento; contra o PostgreSQL, a reentrega 3× deixa **1** dono, e sem o evento o remetente é `cliente`.
- [ ] **Troca de telefone:** uma rota liga o OTP do KAM-086 à `TrocaDeTelefone`, com o adaptador da `TrocaNaBase` sobre a `platform.definir_dono(…, 'troca_de_telefone')` como `kamba_identity`; até o OTP acertar, o número novo é `cliente`; o aviso ao número antigo e ao e-mail sai pelos ganchos do KAM-115; ensaiado pelo caminho real, sem superutilizador.
- [ ] **Botão:** o identificador `confirm:{action_id}` de uma resposta interactiva chega ao estado do turno do dono e chama o `confirmar`; pelo caminho CHR → AGR, duplo toque ×2 → **1** execução e «sim»/«ok» por texto → **0**/20.
- [ ] **Canal do dono no painel:** o número da loja lê-se de fonte persistida, e o `GET /painel/canal` mostra o `owner_channel_wa` pela `canalDoDono`; os dois cenários (telefone igual e diferente) ensaiados contra a base.
- [x] **Retoma:** uma *thread* interrompida retoma no grafo do papel **actual** do contacto, e não no da persona guardada no *checkpoint*: depois de uma troca de telefone, o *handoff* do dono antigo retoma como `cliente` (achado 4 da revisão adversarial do KAM-118). Tem de estar antes de o KAM-119 ligar tools de escrita.
- [ ] **Painel do dono:** a `OwnerPort` no `onboarding-web`, com sessão por OTP e `tenant_id` do cookie assinado, entrega à mesma entrada interna do AGR com persona `dono` e o mesmo `thread_id` do dono no WhatsApp, pela mesma ToolLayer; a sessão do tenant A com um recurso do tenant B → 404.

### Detalhes Técnicos

- **Componentes:** `onboarding-web` (painel e rota do OTP), `worker-canal` e CHR (resposta interactiva), AGR (estado do turno), IDN (`kamba_identity`, adaptador do `phone_enc`), EVT (subscrição do `tenant.provisioned`).
- **Sem esquema novo previsto:** a `0070` do KAM-118 já tem o `papel`, a `owner_actions` e a porta. Uma coluna para o número da loja, se for preciso, entra pelo dicionário.
- **Fora deste ticket:** as mensagens proactivas ao dono — no Piloto não há *push* pelo número da loja nem *template* de `marketing` (critério 8 do KAM-118, decisão do fundador de 2026-11-18); as acções sensíveis em si (KAM-119, KAM-121, KAM-123); o aviso por canal alternativo (KAM-115).

### Testes Requeridos

- Integração: saga → `tenant.provisioned` → contacto `dono`, contra o PostgreSQL; troca de telefone com OTP falso e com OTP certo; a mesma tool pelo painel e pelo WhatsApp.
- Isolamento: dono A vs tenant B no painel e na troca; botão de outro tenant.
- **Adversarial:** replay de botão antigo; mensagem do número novo antes do OTP; sessão do painel de outro tenant; texto que imita um botão.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; as caixas 3, 4, 5, 7 e 9 do KAM-118 revistas com a evidência.
- [x] Isolamento de tenant e contacto coberto pelo teste cruzado (ADR-015); `tenant_id` só do contexto.
- [x] Telefone nunca em claro em logs, URLs ou eventos (ADR-010); sem segredos; nenhuma chave real nos ensaios.

### Handoff para Claude Code

```text
És o executor do ticket KAM-211 da KAMBÁ (ligações de produção do canal do dono).
Lê specs/EPIC-11_Modulos_Entrada.md (blocos KAM-118 e KAM-211), o §3.78 de specs/02_Dicionario_de_Dados_Canonico.md,
packages/core-ts/src/dono/, services/agr/src/kamba_agr/dono/accoes.py e db/migrations/versions/0070_canal_do_dono.py.
Objectivo: ligar ao caminho de produção o tenant.provisioned, a troca de telefone, o botão confirm, o owner_channel_wa
no painel e a OwnerPort do painel do dono.
Regras: o papel só muda pela platform.definir_dono; tenant_id só do contexto; texto nunca confirma; nenhuma chave real.
Testes: integração contra a base, isolamento e adversarial (replay, SIM swap, sessão cruzada).
```

### Decisões do executor

- **Três dos seis critérios não fecham neste ticket, e cada um tem credor próprio** (divisão confirmada pela coordenação do lote, 2026-11-18). O provisionamento precisa de uma saga que corra em produção — nenhum serviço avança o caso para lá de `aprovado`, e o `Onboarding` do KAM-016 e a saga do KAM-091 só se instanciam em ensaios —, de um escritor do `onboarding_case` (o `onboarding-web` é só memória e recusa `prod`), de um formato de cifra e de uma KEK para o `phone_enc`, e de uma revisão de dados para a subscrição: **KAM-215**. O canal no painel precisa de uma coluna com o número da loja: **KAM-216**. A `OwnerPort` precisa de o texto chegar ao AGR (o `agent_invocation` não o leva, decisão do KAM-186) e de a resposta voltar à web, e o processo web não tem base nem credencial do AGR: **KAM-217**. Este ticket **não leva migração**.
- **A retoma decide o grafo pelo papel de agora.** A `PortaDeGrafos.da_thread` lê o `contacts.papel` do par da *thread* pelo `leitor_de_papel` do `conversa.py` (a ligação de leitura, `kamba_app`, e o `SQL_PAPEL_DO_CONTACTO` das acções sensíveis, e não uma cópia), e passa à `chave_do_registo` a persona desse papel com a vertical do *checkpoint*. Lista de permitidos: só o papel exacto `dono` dá o grafo do dono; zero linhas (apagado, fundido, ou outro tenant) dá `cliente`. A leitura é **antes** do CAS, como a do *checkpoint*: uma leitura que falha sobe, e a rota responde 503 sem escrever nada. Fecha o achado 4 da revisão do KAM-118.
- **O botão viaja num campo aditivo da v1, `agent_invocation.botao`**, e só com `type: interactive` — o AGR recusa-o noutro tipo (`campo_invalido_botao`) e o esquema exprime-o com `dependentSchemas`. A explosão lê **só** o `id` de um `button_reply` ou de um `list_reply`; o título nunca sai, e um `id` fora da forma `^[A-Za-z0-9_.:-]{1,256}$` não segue — a mensagem segue sem ele. A forma está escrita duas vezes, em TypeScript e em Python, e um ensaio compara-as letra a letra. Não entra na janela `messages`: vive no `ConversaState.botao`, que nasce em cada turno (um texto depois de um toque não herda o toque). O `agent_invocation` não está no `gov/contratos/versoes.json`, que é o manifesto dos quatro documentos do aceite, e por isso nada muda lá.
- **O `confirm` é o quinto nó próprio do grafo do dono**, com a intenção `confirmar` que só a forma `confirm:{uuid}` dá, num turno `interactive`. O reaproveitamento passa a 12 em 17, **70,6%**, acima do piso. O nó chama a porta nova `accoes_do_dono` das `Dependencias` — a `PortaDeConfirmacao` de `kamba_agr/dono/accoes.py`, uma ligação `kamba_app` por confirmação, sem ligação nenhuma para um texto —, e `None` não confirma nada. A porta abre a ligação própria `kamba-agr:accoes` (a nona do AGR), e não a de leitura: o `confirmar` escreve. **Um toque não coalesce** com outras mensagens: o estado de um lote sai da primeira invocação, e um toque coalescido perdia-se sem o `confirmar` ser chamado. As frases não distinguem `desconhecida`, `outro_contacto`, `nao_e_dono` e `nao_e_botao`, para não dar um oráculo sobre as acções de outros. **O Vendedor e os Serviços não leem o `botao` do estado**: continuam a ler a janela, e ligá-los não é deste ticket.
- **A troca de telefone entra no painel em duas rotas**, `POST /painel/telefone` e `POST /painel/telefone/verificar`, sobre a `TrocaDeTelefone` do KAM-118. A chave do pedido é a sessão (`troca:{sid}`), e não um campo do pedido; um código que não acerta dá **401 `{"erro":"codigo"}`**, uma resposta só. Os adaptadores estão em `packages/core-ts/src/dono/sql.ts`: `trocaNaBase` e `definirDonoNaBase` sobre a `definir_dono`, e `contactoDoNumero` sobre o `resolveContact` só com o telefone — que **recusa** uma fusão, porque com um identificador não a pode haver — e que é um sítio de chamada do `revelar()`, escrito na nota do `ComHmac`. Os avisos saem pelos ganchos `DESTINOS_DO_AVISO` (a porta `AvisoDaTroca`); entregá-los é do KAM-115. **A troca só abre com o caso em `activo`** (409 antes): antes disso o `tenant.provisioned` ainda não saiu, e uma troca sem dono anterior criava o primeiro dono por `troca_de_telefone` e fazia o provisionamento seguinte recusar com `23505`. **Tem o limite por rede da reentrada**, noutra chave, para uma sessão não esgotar o orçamento diário de SMS. A `TrocaDeTelefone` passou a esquecer os pedidos expirados e a recusar um segundo `pedir` do mesmo pedido enquanto o primeiro envia. **As rotas não estão montadas no `server.ts`**: o processo web não tem ligação à base, e dar-lha é do **KAM-217**.

### Verificação dos Critérios de Aceitação

Seis critérios, **um marcado**. **Sem LLM pago, sem chave real e sem telefone real**: os números dos ensaios são fictícios, com 999, e os identificadores da *fixture* também. As restrições de base ensaiam-se pelo caminho real — contactos pelo `resolveContact` e donos pela `definir_dono`, como `kamba_identity` —, e nunca por superutilizador.

| Critério | Estado | Evidência nomeada |
|---|---|---|
| 1 | não satisfeito — caixa vazia | Só a porta tem adaptador: `definirDonoNaBase`, idempotente 3× e a recusar um segundo dono com `23505` («o provisionamento pela porta é idempotente e não troca o dono», `tests_bd/dono.bd.test.ts`). O emissor em produção, o formato de cifra e a KEK do `phone_enc`, o escritor do caso e a subscrição (uma revisão de dados) passam ao **KAM-215** |
| 2 | **parcial — caixa vazia** | **A rota e o adaptador estão, e ensaiam-se pelo caminho real; não estão montados.** Contra a base: até o código acertar o número novo é `cliente` e o antigo `dono`; o código certo move o papel, marca os dois e escreve o `owner_contact_id`; os dois avisos saem pelos ganchos, e a persona que o CHR lê pelo `SQL_PAPEL` como `kamba_app` acompanha (`tests_bd/dono.bd.test.ts`, «até o código acertar o número novo é cliente e o antigo é dono; depois, o contrário»); o `kamba_app` recebe `42501` e o tenant é o do contexto (`23503`). Pela superfície HTTP, com o `Otp` e a `TrocaDeTelefone` reais: o tenant de B no corpo, na consulta ou num cabeçalho não muda nada, e a sessão de A não verifica o pedido de B nem com o código certo de B; antes de `activo` a troca recusa com 409; há limite por rede; dois pedidos concorrentes da mesma sessão dão um envio (`services/onboarding-web/tests/troca.test.ts` e `dono.test.ts`); um mutante que lê o tenant do corpo dá um vermelho ali e `pedido=alheio` no *gate* 6 (medido). **Falta** montá-las no `server.ts`, que é o **KAM-217**. **Revisto no KAM-217**: montadas, com o processo ligado como `kamba_identity` por um *pool* e a troca concorrente de dois tenants ensaiada contra a base pela montagem do processo. Falta persistir o OTP e os pedidos (**KAM-226**), e a prova de posse decidiu-a o fundador a 2026-11-19 (opção C do bloco do KAM-217), também no **KAM-226** |
| 3 | **parcial — caixa vazia** | **O botão chega e confirma; nenhuma acção executa.** A letra pede «duplo toque ×2 → **1** execução», e o que se mede é **uma confirmação** na `owner_actions`: as acções sensíveis em si são do KAM-119, KAM-121 e KAM-123, e é por isso mesmo que a caixa 5 do KAM-118 fica vazia — marcar esta com a mesma medida era ler «execução» como «confirmação» num bloco e não no outro (achado 6 da revisão). Fecha quando o primeiro desses módulos executar uma acção pelo portão. O que está medido: pelo caminho CHR → AGR, numa ponte por *fixture*: um `button_reply` do webhook sai do `Chr.tratar` com o corpo **exacto** de `tests/fixtures/invocacao_do_botao.json` (`chr.botao.test.ts`, «o toque do dono sai do CHR com o corpo exacto da fixture que o AGR le»), e o AGR lê esse ficheiro e corre o turno do dono até ao `confirmar`: duplo toque ×2 → **1** confirmação (`test_dono.TestBotaoPeloContrato`). Vinte textos — «sim», «ok», e o próprio `confirm:{action_id}` escrito — saem do CHR sem `botao` («vinte textos de confirmacao saem sem `botao`») e dão **0**/20 no turno, sem abrir a base (`test_vinte_textos_pelo_turno_nao_confirmam_nem_abrem_a_base`). Replay de botão antigo expira; um botão de outro tenant não confirma e não diz porquê (`TestBotaoNoGrafoDoDono`). Contra a base, a porta do `__main__` dá `confirmada` e `ja_confirmada` com uma ligação `kamba_app` por toque (`test_owner_actions.TestPortaDeConfirmacao`). **Um toque não coalesce**: o estado do lote sai da primeira invocação, e um toque atrás de um texto perdia o `botao` (achado 1 da revisão, medido pela `ExecutorDeTurnos` real); `test_turno.TestUmToqueNaoCoalesce` corre o executor com textos e toques dentro da janela, e o mutante sem as duas guardas dá três vermelhos. Um `interactive` sem `botao` não lê o texto da janela (achado 2), com ensaio directo ao `classify`. Dois mutantes medidos antes: sem a exigência de `type: interactive`, quatro vermelhos; sem a do `_botao_do_turno`, um |
| 4 | não satisfeito — caixa vazia | Nenhuma tabela guarda o número da loja, e guardá-lo é esquema novo: **KAM-216** |
| 5 | marcado | Depois de uma troca, o *handoff* do dono antigo retoma no grafo do Vendedor, e o `Retomador` acaba-o (`test_dono.TestRetomaPeloPapel.test_depois_da_troca_o_handoff_do_dono_antigo_retoma_como_cliente`); o sentido contrário também (`test_o_cliente_que_passou_a_dono_retoma_no_grafo_do_dono`); só o papel exacto `dono` abre o grafo do dono, em oito valores (`test_so_o_papel_exacto_dono_da_o_grafo_do_dono`); uma leitura que falha não abre a ligação do CAS (`test_uma_leitura_do_papel_que_falha_nao_abre_a_base_do_cas`); o `main()` liga a porta à ligação de leitura (`test_grafos.test_o_papel_da_retoma_le_se_pela_ligacao_de_leitura`). Contra a base, como `kamba_app`, depois de uma troca pela `definir_dono` o dono antigo lê-se `cliente` (`db/tests_agr/test_retoma_pelo_papel.py`). Um mutante que volta a ler a persona do *checkpoint* dá **11** vermelhos (medido). Está antes de o KAM-119 ligar tools de escrita |
| 6 | não satisfeito — caixa vazia | A `OwnerPort` precisa do texto no AGR e da resposta na web, e de o processo web ganhar base e credencial do AGR: **KAM-217**. **Revisto no KAM-217**: o processo ganhou a base, e a `OwnerPort` não se escreveu — o AGR não tem saída (`SaidaPorLigar`), e o contrato do texto e da resposta decidiu-o o fundador a 2026-11-19 (bloco do KAM-217). Passa ao **KAM-226**, com a saída do AGR no **KAM-227** |

### Verificação da Definition of Done

| Caixa | Estado | Evidência nomeada |
|---|---|---|
| 1 | não satisfeito — caixa vazia | Um critério de seis. As caixas 3, 4, 5, 7 e 9 do KAM-118 estão revistas com a evidência deste ticket, cada uma com o credor que fica |
| 2 | marcado | O *gate* 6 cobre as duas rotas novas com três ataques cada: a sessão de A com o tenant de B no corpo, na consulta e no cabeçalho deixa o pedido no tenant e na sessão de A (`pedido=a`), e o código certo do pedido de B não troca o dono de B (`troca=nenhuma`) — o grupo `painel` do condutor, medido em contentor. O botão de outro tenant não confirma (no grafo e contra a base), a retoma do dono de A no tenant de B lê zero linhas, e a porta recusa o contacto de A no contexto de B. O tenant vem da sessão, da invocação ou do `app.tenant_id`, e de nenhum outro sítio |
| 3 | marcado | Nenhum telefone em claro: a rota regista só `outcome`, o `botao` é um identificador e o título do botão não sai da explosão (ensaiado), os avisos recebem o tenant e o destino e nunca o número. Nenhum segredo e nenhuma chave real; os números de ensaio são fictícios, com 999 |

### Verificação da revisão adversarial

Uma revisão independente, que recebeu o diff e os critérios e não o raciocínio do ramo, com mutantes e demonstrações numa cópia da árvore. **Nenhum achado bloqueava.** Os confirmados corrigiram-se neste PR, cada um com um ensaio; os outros ficam escritos com quem os decide.

| # | Severidade | O que estava errado | Como se fechou |
|---|---|---|---|
| 1 | deve corrigir | Um toque coalescido num lote atrás de um texto perdia-se: o estado do lote sai da `primeira` invocação, e o `confirmar` nunca era chamado (medido com a `ExecutorDeTurnos` real). A ponte por *fixture* saltava o executor | Um toque não coalesce, nem como primeiro nem como seguinte (`admissao.coalescer`); `test_turno.TestUmToqueNaoCoalesce`, e o mutante sem as guardas dá três vermelhos |
| 2 | deve corrigir | Num `interactive` sem `botao`, o `_botao_do_turno` lia o texto da janela, que acumula turnos anteriores: um `confirm:{uuid}` escrito antes valia como toque quando o texto chegar ao AGR | Sem `botao`, não há botão; o ensaio directo ao `classify` cobre o caso, e o mutante com o recurso ao texto dá um vermelho |
| 3 | deve corrigir | As rotas da troca não tinham limite por rede: uma sessão mandava SMS a números diferentes até esgotar o orçamento diário do `Otp` | O limite da reentrada, noutra chave (`recusaDaTroca`); ensaio do 429 |
| 4 | deve corrigir | A troca abria antes do provisionamento: sem dono anterior, criava o primeiro por `troca_de_telefone`, e o `tenant.provisioned` seguinte recusava com `23505` | A troca só abre em `activo` (`FASE_DA_TROCA`), com 409 antes; ensaio nas quatro fases anteriores, e o condutor do *gate* 6 ataca com uma sessão sobre um caso `activo` |
| 5 | deve corrigir → **decisão por tomar** | A troca não volta a autenticar quem tem o papel: basta a sessão do painel e o OTP do número novo, enquanto a reentrada manda o código ao telefone registado | É de segurança e de produto: escrita como decisão por tomar no **KAM-217**, antes de montar a troca em produção. **Decidida pelo fundador a 2026-11-19**: opção C do bloco do KAM-217, implementada no KAM-226 |
| 6 | deve corrigir | O critério 3 estava marcado com «1 execução» medida como uma confirmação, e a caixa 5 do KAM-118 ficava vazia pela razão oposta | O critério 3 fica **parcial**, com a leitura escrita e as duas caixas pela mesma medida |
| 7 | menor | A nota do `arestas.py` dizia dezasseis nós e 75% | Dezassete e 70,6% |
| 8 | menor | Dois `pedir` concorrentes da mesma sessão podiam deixar o desafio de um número com o telefone de outro | A `TrocaDeTelefone` recusa um segundo envio do mesmo pedido enquanto o primeiro corre; ensaio com um OTP lento em `dono.test.ts` |
| 9 | menor | O mapa de pedidos da troca crescia sem limite | Os pedidos com o desafio expirado esquecem-se no `pedir` seguinte; ensaio |
| 10 | menor | O portão escrevia na `owner_actions` pela ligação de leitura | Ligação própria, `kamba-agr:accoes`, com ensaio de que o `main()` a liga |
| 11 | menor | A «mensagem do número novo antes do OTP» lia o papel como administrador e não pelo caminho do CHR | O ensaio lê também pelo `SQL_PAPEL` do CHR como `kamba_app`, com o `personaDe` |

---

## KAM-215 — Canal do dono: o dono nasce do provisionamento em produção — emissor, `phone_enc` e consumidor

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-211 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Plataforma (TEN, EVT) com Responsável de Segurança |
| Documentos de referência | `EPIC-11_Modulos_Entrada.md` (blocos KAM-118 e KAM-211, critério «Provisionamento»), `EPIC-09_Onboarding_Governanca.md` (blocos KAM-086, KAM-091 e KAM-092), `02_Dicionario_de_Dados_Canonico.md` (§3.70 e §3.78), `../ops/secrets-inventory.yaml` |

### Contexto

Credor do critério «Provisionamento» do KAM-211, aberto no PR dele. O efeito do consumidor (`efeitoDoProvisionamento`) e o adaptador da porta (`definirDonoNaBase`) estão entregues e ensaiados; falta tudo o que os faz correr. Medido na `main` em 2026-11-18: a `platform.advance_case` emite o `tenant.provisioned` no `es_concluido`, mas **nenhum serviço avança o caso para lá de `aprovado`** — a saga do KAM-091 e o `Onboarding` do KAM-016 só se instanciam em ensaios; **ninguém escreve o `onboarding_case` em produção** (o `onboarding-web` é só memória e recusa `prod`); o `phone_enc` **não tem formato de cifra nem KEK** no inventário; e o consumidor `dono` não tem subscrição, que é uma linha de `platform.evt_subscricoes` escrita por **revisão de dados**. O `kamba_identity` não pode correr o `consumir` (não tem privilégios em `events_consumed`), pelo que o processo precisa de duas ligações, como o `worker-canal-entrada`.

### Objectivo

O contacto `dono` nasce em produção do `tenant.provisioned`, de forma idempotente, a partir do telefone verificado do caso.

### Critérios de Aceitação

- [ ] Um serviço avança o caso até `es_concluido` pela `platform.advance_case`, como `kamba_batch`, e o `tenant.provisioned` sai pelo outbox **uma** vez por caso.
- [ ] O `onboarding_case.phone_enc` tem formato de cifra e KEK no inventário, um escritor, e um decifrador `TelefoneDoCaso` que devolve `null` em vez de lançar.
- [ ] O consumidor `dono` subscreve o `tenant.provisioned` (revisão de dados e `registry/` do consumidor) e corre num processo com a ligação `kamba_app` para o `consumir` e a `kamba_identity` para o `resolveContact` e o `definirDonoNaBase`.
- [ ] Contra o PostgreSQL, saga → `tenant.provisioned` → contacto `dono`; a reentrega 3× deixa **1** dono, e sem o evento o remetente é `cliente`.

### Detalhes Técnicos

- **Esquema:** leva uma revisão de dados (a subscrição) e, se o desenho o pedir, as concessões ao `kamba_identity`. Vaga de migração a pedir à coordenação.
- **Decisão por tomar:** o formato de cifra e a KEK do `phone_enc` são do Responsável de Segurança e do fundador; o KAM-086 deixou a cifra ao adaptador.

### Testes Requeridos

- Integração contra a base: a saga até ao dono; a reentrega 3×.
- Isolamento: o evento de A não cria dono em B; o tenant é o do envelope.
- **Adversarial:** um `onboarding_id` de outro tenant no payload; um `phone_enc` ilegível vai à DLQ e não cria dono.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; o critério «Provisionamento» do KAM-211 e a caixa 3 do KAM-118 revistos com a evidência.
- [ ] Telefone nunca em claro em logs, URLs ou eventos (ADR-010); nenhuma chave real nos ensaios.

### Handoff para Claude Code

```text
És o executor do ticket KAM-215 da KAMBÁ (o dono nasce do provisionamento em produção).
Lê specs/EPIC-11_Modulos_Entrada.md (blocos KAM-118, KAM-211 e KAM-215), packages/core-ts/src/dono/provisionamento.ts
e sql.ts, a revisão 0058 (advance_case) e o bloco do KAM-091 em specs/EPIC-09_Onboarding_Governanca.md.
Objectivo: o caso chega a es_concluido em produção, o phone_enc decifra-se, e o consumidor dono subscreve o evento.
Regras: o papel só muda pela platform.definir_dono; tenant_id só do envelope; a cifra e a KEK decidem-se antes de escrever.
Testes: integração contra a base, isolamento e adversarial.
```

---

## KAM-216 — Canal do dono: o número da loja persistido e o `owner_channel_wa` no painel

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | M |
| Dependências | KAM-211 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Canais (GWY, COM) |
| Documentos de referência | `EPIC-11_Modulos_Entrada.md` (blocos KAM-118 e KAM-211, critério «Canal do dono no painel»), `EPIC-09_Onboarding_Governanca.md` (blocos KAM-093 e KAM-190), `02_Dicionario_de_Dados_Canonico.md` (§3.76 e §3.78) |

### Contexto

Credor do critério «Canal do dono no painel» do KAM-211, aberto no PR dele. A decisão (`canalDoDono`) está entregue e ensaiada com os dois cenários; ninguém a lê porque **nenhuma tabela guarda o número da loja** — o `tenant_channels` só tem o `phone_number_id`, que não é um telefone, e o `display_phone_number` que o KAM-093 compara chega nos *webhooks* e não fica. O `GET /painel/canal` lê o canal pelo COM (`POST /internal/channel-view`, KAM-190), e a `VistaDoCanal` não traz telefone por desenho.

### Objectivo

O painel mostra se o dono tem o canal WhatsApp ou só o painel, a partir de um número da loja persistido.

### Critérios de Aceitação

- [ ] O número da loja persiste-se numa coluna nova, entrada pelo dicionário, escrita por quem já o lê (o passo do Embedded Signup ou os *webhooks*), na forma que a decisão de desenho fixar (HMAC no espaço da inscrição ou cifrado).
- [ ] O `GET /painel/canal` mostra o `owner_channel_wa` pela `canalDoDono`, comparado com o `phone_hmac` do caso; um número ausente ou ilegível dá painel.
- [ ] Os dois cenários (telefone igual e diferente) ensaiados contra a base, e o isolamento cruzado no *gate* 6.

### Detalhes Técnicos

- **Esquema:** leva uma revisão (a coluna). Vaga de migração a pedir à coordenação.
- O anel do `pepper_onboarding_ident` só o `onboarding-web` o tem; quem compara tem de estar desse lado, ou a forma persistida tem de o dispensar.

### Testes Requeridos

- Integração contra a base: os dois cenários e o número ausente.
- Isolamento: o canal de B não aparece na sessão de A.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; o critério «Canal do dono no painel» do KAM-211 e a caixa 7 do KAM-118 revistos com a evidência.
- [ ] Telefone nunca em claro em logs, URLs ou eventos (ADR-010).

### Handoff para Claude Code

```text
És o executor do ticket KAM-216 da KAMBÁ (o número da loja persistido e o owner_channel_wa no painel).
Lê specs/EPIC-11_Modulos_Entrada.md (blocos KAM-118, KAM-211 e KAM-216), packages/core-ts/src/dono/persona.ts,
packages/core-ts/src/guia/numero.ts e services/onboarding-web/src/painel/canal.ts.
Objectivo: persistir o número da loja e mostrar o owner_channel_wa no GET /painel/canal.
Regras: o nome da coluna entra pelo dicionário; tenant_id só da sessão; número ausente dá painel.
Testes: integração contra a base com os dois cenários, isolamento.
```

---

## KAM-217 — Canal do dono: o painel do dono em produção — `OwnerPort`, processo web ligado e troca montada

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-211 |
| Bloqueia | KAM-226, KAM-227 |
| Responsável sugerido | Engenheiro de Runtime/IA (AGR) com Engenheiro de Plataforma (`onboarding-web`) |
| Documentos de referência | `EPIC-11_Modulos_Entrada.md` (blocos KAM-118 e KAM-211, critérios «Troca de telefone» e «Painel do dono»), `EPIC-09_Onboarding_Governanca.md` (blocos KAM-099 e KAM-190), `EPIC-03_Agent_Runtime_Verticais.md` (bloco KAM-186), `02_Dicionario_de_Dados_Canonico.md` (§3.13 e §3.78) |

### Contexto

Credor dos critérios «Painel do dono» e da metade por montar da «Troca de telefone» do KAM-211, aberto no PR dele. As duas rotas da troca e os adaptadores estão entregues e ensaiados contra a base, mas **o processo web não tem ligação à base** (está só na rede `app`) nem credencial do AGR, e o `server.ts` não as monta. A `OwnerPort` precisa de mais do que uma rota: o `agent_invocation` **não leva texto** (decisão do KAM-186), não há caminho de resposta do AGR para a web, e o painel conhece o caso (`onboarding_id`) e não o `contact_id` do dono, que é o que dá o `thread_id`.

### Objectivo

O dono fala com o Assistente do Dono pelo painel, com o mesmo `thread_id` e a mesma ToolLayer do WhatsApp, e troca de telefone pelo painel em produção.

### Critérios de Aceitação

- [ ] A `OwnerPort` no `onboarding-web`, com sessão por OTP e `tenant_id` do cookie assinado, entrega à mesma entrada interna do AGR com persona `dono` e o `thread_id` do dono no WhatsApp (o `contact_id` do `tenants.owner_contact_id`), e a resposta volta ao painel; a mesma tool pelo painel e pelo WhatsApp.
- [ ] O processo `onboarding-web` liga-se à base como `kamba_identity` e ao AGR com credencial própria (rede, segredos, inventário), e monta as rotas da troca do KAM-211 com o OTP e os pedidos persistidos.
- [ ] Isolamento: a sessão do tenant A com um recurso do tenant B → 404, no painel e na troca, no *gate* 6.

### Detalhes Técnicos

- **Decisão do fundador (tomada a 2026-11-19):** o contrato do texto do painel até ao AGR (o KAM-186 decidiu que o `agent_invocation` não leva o corpo) e o caminho da resposta. Decisões 1 e 2 abaixo, opção A nas duas.
- **Topologia:** dar à rede do `onboarding-web` acesso à base e ao AGR muda o *compose* e o inventário de segredos.
- **Decisão por tomar — a prova de posse da troca** (achado 5 da revisão do KAM-211): a troca pede o OTP do número **novo** e uma sessão do painel, que dura até 30 dias; quem tiver o *cookie* passa o papel para o seu número, e só o bloqueio de 24 h atrasa as acções sensíveis. A reentrada do KAM-190 manda o código ao telefone **registado**. Pedir também prova ao número antigo fecha isto e tira a troca a quem perdeu o SIM, que é o caso para que ela existe. É de segurança e de produto, e decide-se antes de montar a troca em produção. **Tomada a 2026-11-19**: decisão 3 abaixo, opção C.

### Testes Requeridos

- Integração: a mesma tool pelo painel e pelo WhatsApp; a troca de telefone com o processo montado.
- Isolamento: dono A contra tenant B no painel e na troca.
- **Adversarial:** sessão do painel de outro tenant; texto que imita um botão pelo painel.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; os critérios «Troca de telefone» e «Painel do dono» do KAM-211 e a caixa 9 do KAM-118 revistos com a evidência.
- [x] Telefone nunca em claro em logs, URLs ou eventos (ADR-010); sem segredos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-217 da KAMBÁ (o painel do dono em produção).
Lê specs/EPIC-11_Modulos_Entrada.md (blocos KAM-118, KAM-211 e KAM-217), services/onboarding-web/src/painel/rotas.ts
e server.ts, packages/core-ts/src/agr/ e services/agr/src/kamba_agr/contexto.py.
Objectivo: a OwnerPort com o mesmo thread_id do dono, e o processo web ligado à base e ao AGR com a troca montada.
Regras: tenant_id só do cookie assinado; a mesma ToolLayer; o contrato do texto decide-o o fundador antes de escrever.
Testes: integração, isolamento e adversarial (sessão cruzada, texto que imita botão).
```

### Decisões do executor

- **Entregue só a parte que nenhuma decisão bloqueia**, pela divisão confirmada pela coordenação do lote 12 (2026-11-19). Medido na `publico/main` em `f0a31b54`, há três coisas fora do alcance deste ticket. **(1) O AGR não responde a ninguém**: a `saida` que o `main()` liga é a `SaidaPorLigar` (`services/agr/src/kamba_agr/__main__.py`), e nenhum serviço instancia o `Saida` do KAM-015. Um turno que quer responder dá 503 `saida_por_ligar` e volta à fila, no WhatsApp como no painel. **(2) Persistir o OTP e os pedidos da troca é esquema novo**: não há tabela de desafios OTP, e o `Otp` é o mesmo do registo, em memória (`OtpEmMemoria`). **(3) A prova de posse da troca** é do fundador. Por isso a `OwnerPort`, a credencial do AGR e a persistência passam ao **KAM-226**, e as três decisões ficaram escritas abaixo para o fundador, que as tomou a 2026-11-19.
- **O processo liga-se à base como `kamba_identity`, e só para a troca.** O `server.ts` monta a troca (`montarTroca`) quando há painel (`ONBOARDING_COM_INTERNO_URL`) **e** a cadeia `ONBOARDING_IDENTITY_DB_URL`. Sem ela as duas rotas respondem 503, como até aqui. As chaves do contacto são as do CHR (`EnvKeyProvider`), e o `Identidade.arrancar` recusa-as se o `KAMBA_ENV` não for o ambiente do processo. **Com a cadeia definida, o `pepper_contact_hmac` e o `kek_contact_dek` são obrigatórios no `Secrets.arrancar`**: o `Identidade.arrancar` não lê chave nenhuma, e sem esta verificação o processo subia e o primeiro dono a acertar o código gastava-o e recebia um 500. Uma ligação que cai, inactiva ou emprestada, é registada e não derruba o processo (os casos vivem em memória), e uma base que não responde dá erro ao fim de 5 s (*proposta*). **O processo continua a recusar `prod`**: o `RepositorioEmMemoriaEmProducaoError` não mudou.
- **Uma ligação do *pool* por operação** (`trocaPeloPool` e `numaLigacao`, em `packages/core-ts/src/dono/sql.ts`). O servidor atende pedidos concorrentes, e a troca é uma transacção com o tenant no `app.tenant_id`. Sobre uma ligação partilhada, o `tenant_guard` recusa a segunda transacção enquanto a primeira corre (`LigacaoEmUsoError`): não cruza tenants, mas o dono que chega em segundo recebe um erro. O ensaio mediu-o por acidente, numa preparação que corria em paralelo sobre a ligação única do ensaio. Uma ligação que falha é destruída, e não devolvida. O *pool* tem quatro ligações (*proposta*, a calibrar no KAM-084).
- **Os avisos da troca ficam registados, e não entregues.** Os ganchos `DESTINOS_DO_AVISO` do KAM-118 recebem uma linha por destino, só com o `outcome` (`painel_troca_aviso_numero_antigo_por_entregar`, `painel_troca_aviso_email_por_entregar`), sem tenant nem número. Entregá-los é do KAM-115, que não tem canal. **Hoje o dono antigo não é avisado de nada**, e isto pesa na decisão 3.
- **Topologia:** o `onboarding-web` entra na rede `data` em `dev` e em `staging`. Em `staging` a cadeia é opcional (`:-`), porque o painel também o é, e a rede `data` entra sem condição: o compose não liga redes por variável, e é em `staging` que a troca se ensaia antes de produção. Em `dev` a cadeia nunca fica vazia, pelo que a troca se desliga pela falta do painel. **O compose de produção não muda**: o processo recusa `prod`, e ligar um processo público à rede `data` antes de ele lá correr era abrir topologia por nada. O inventário de segredos acrescenta o `TEN` (o `onboarding-web`) aos consumidores do `db_identity_password`, do `pepper_contact_hmac` e do `kek_contact_dek`.
- **Achado fora de escopo:** o serviço `onboarding-web` dos três compose não define o `KAMBA_AMBIENTE` nem os segredos da inscrição. Lido no `server.ts`, isso faz o `exigir` lançar logo no arranque, pelo que o serviço do compose não sobe hoje. É **INDÍCIO**: foi lido, não corrido, porque o motor do Docker esteve em baixo. Não se corrigiu aqui, porque é configuração da inscrição (KAM-086) e não da troca. Passa ao **KAM-226**, que precisa do processo a correr.

### Decisões do fundador

Três decisões, cada uma com as opções medidas. **O fundador tomou as três a 2026-11-19, no chat, e a coordenação do lote 12 trouxe-as a este PR**: A, A e C. As tabelas ficam como registo das opções que ele teve à frente. O código deste ticket não antecipa nenhuma; quem as implementa é o KAM-226 e o KAM-227.

**Decisão 1 — o contrato do texto e da resposta do painel.**

*O que já está fixado.* O KAM-186 mediu a rota do texto do cliente até à janela do AGR e devolveu-a ao fundador. A coordenação deste lote confirma que se mantém o que ele fixou: o `agent_invocation` (§3.13) tem onze campos fechados — nove obrigatórios e os aditivos `persona` e `botao` — e **não leva o texto**. O AGR também não o lê de lado nenhum, pelo que a janela chega vazia, no WhatsApp como no painel.

*O que falta decidir.* Por onde o texto que o dono escreve no painel chega ao AGR, e por onde volta a resposta. O painel conhece o caso (`onboarding_id`), e não o `contact_id` do dono. O `thread_id` (`tenant_id:contact_id`) lê-se no `tenants.owner_contact_id`, e **não como `kamba_identity`**: esse papel não tem `SELECT` em `platform.tenants`, e um ensaio fixa-o (`test_kamba_identity_nao_le_tenants_canais_nem_entitlements`). Seja qual for a opção, o `onboarding-web` precisa de uma segunda ligação, `kamba_app` com o tenant no contexto, ou de pedir o `thread_id` a quem o lê.

| Opção | O que é | Consequência |
|---|---|---|
| **A — fonte persistida, e a resposta volta pelo painel** | O painel grava a mensagem do dono numa fonte persistida, e o AGR lê-a por identificador. É a saída (b) do KAM-186, e serve também o WhatsApp. O AGR responde para o canal `painel`, e o `onboarding-web` lê a resposta pelo `thread_id`, a pedido ou por *stream*. | Uma tabela nova, e por isso migração, e emenda ao §3.13 para o identificador da mensagem. Uma só rota de texto para os dois canais, e fecha a decisão que o KAM-186 deixou. Precisa da decisão 2 com um canal `painel`. O texto do dono passa pela redacção `guardas.mensagem_do_cliente` uma vez. |
| **B — o texto entra pelo painel, e a resposta volta pelo WhatsApp** | A entrada é a de A, e a resposta sai pelo Outbound para o número do dono, na mesma *thread*. O painel não mostra resposta. | Não há caminho de resposta na web. **Não serve o caso para que o painel existe**: o dono com o Embedded Signup por concluir não tem WhatsApp ligado, e não recebe nada. Fora da janela de 24 h, a resposta precisava de *template*, e a categoria `marketing` está fora do Piloto (decisão do fundador de 2026-11-18). |
| **C — rota síncrona própria do painel** | Uma rota interna nova no AGR recebe o texto no corpo, fora do `agent_invocation`. Corre o turno do dono sob a mesma tranca, e devolve a resposta na resposta HTTP. | O `agent_invocation` fica como o KAM-186 o deixou, sem migração e sem persistência nova antes do AGR. Mas há **um segundo contrato de entrada com texto**, que pode divergir do primeiro, e o WhatsApp continua sem rota de texto. A rota pede uma credencial própria, pela regra do `agr_screening_token`. O turno tem de caber nos 30 s da `ESPERA_MAXIMA_MS`, e um *handoff* a meio não tem para onde responder. |

**Decidido: opção A** (o fundador, 2026-11-19). A mensagem do dono fica numa fonte persistida, e o AGR lê-a pelo identificador. A resposta volta ao painel pelo canal `painel`. É a mesma rota para o WhatsApp, e fecha a saída (b) do KAM-186. Implementa-a o **KAM-226**: a fonte persistida, a emenda ao §3.13 e a `OwnerPort`.

**Decisão 2 — a saída do AGR.**

*Hoje.* A `PortaDeSaida` do grafo é a `SaidaPorLigar`: avisa e levanta `SaidaPorLigarError`, e a rota dá 503 `saida_por_ligar` com `Retry-After`. O *job* volta à fila e, ao fim de seis tentativas, fica em `failed`. A resposta não sai, mas também não se perde: o turno fica no *checkpoint* com o envio por correr, e reprocessa-se quando a saída existir. O Outbound (`Saida`, `packages/core-ts/src/outbound/`, KAM-015) é uma biblioteca TypeScript que nenhum serviço instancia. O AGR é Python, e não há fila nem rota entre os dois.

*O contrato que é preciso.* Uma resposta do turno com o tenant, o `thread_id`, o canal (`whatsapp` ou `painel`), uma chave idempotente (o `turn_id` com a ordem da resposta), o texto já validado pelo *renderer* e os botões. **O produtor é o AGR**, que a emite no `enfileirar` da `PortaDeSaida`. **Os consumidores são dois**: um processo TypeScript que instancia o `Saida` para o WhatsApp (o lugar natural é o `worker-canal`), e o `onboarding-web` para o canal `painel`, se a decisão 1 for A.

| Opção | O que é | Consequência |
|---|---|---|
| **A — evento pelo outbox** | O AGR emite um evento de resposta pela `platform.evt_emitir`, na transacção do turno. Os consumidores leem-no pelo barramento do KAM-006. | Contrato de evento novo no `registry/` e no dicionário, e subscrições, que são revisões de dados. Ganha a idempotência e a DLQ que já existem, e a resposta fica atómica com o turno. Custa a latência do publicador. |
| **B — chamada HTTP interna** | O AGR chama uma rota interna do processo que tem o `Saida`. | Sem esquema. Mas a resposta não é atómica com o turno, cada consumidor precisa da sua credencial, e a repetição fica a cargo do AGR. |
| **C — fila própria `agr-outbound`** | Uma fila BullMQ que o AGR enche e o `worker-canal` consome. | O `ADR-L004` escolheu um *shim* TypeScript e não o `bullmq` para Python, porque a interoperabilidade deste com o `bullmq` TypeScript que a casa usa é **NÃO VERIFICADA** e porque era uma dependência nova. Esta opção reabre essas duas perguntas no sentido contrário: mede-se a interoperabilidade, e emenda-se o ADR. |

**Decidido: opção A** (o fundador, 2026-11-19). Um evento de resposta pela `platform.evt_emitir`, na transacção do turno, pelo barramento do KAM-006. **O contrato vai para ticket próprio**, porque serve também o WhatsApp: o **KAM-227**, e o KAM-226 depende dele. Era o «achado com credor por abrir» do KAM-186.

**Decisão 3 — a prova de posse da troca de telefone** (achado 5 da revisão do KAM-211).

*Hoje.* A troca pede uma sessão do painel e o OTP do número **novo**. A sessão vale 30 dias, renova-se com o uso até um tecto de 90, e as revogações vivem em memória e perdem-se num reinício. Quem tiver o *cookie* passa o papel de dono para o seu número. A reentrada do KAM-190 manda o código ao número **registado**, e a troca não.

| Opção | O que é | Risco |
|---|---|---|
| **A — manter** | A sessão e o OTP do número novo. | Um *cookie* roubado chega para tomar o canal do dono. Só o bloqueio de 24 h atrasa as acções sensíveis, e o aviso ao número antigo **ainda não é entregue** (KAM-115, aqui só registado). O dono legítimo pode não saber que perdeu o papel. |
| **B — exigir também o OTP do número antigo** | Dois códigos: o do número registado e o do novo. | Fecha o roubo de *cookie*. Mas **tira a troca a quem perdeu o SIM**, que é o caso para que ela existe. Esse dono precisa de recuperação assistida pela equipa, e a consola da equipa não tem IdP (KAM-196, decisão do fundador por tomar). |
| **C — prova do antigo, ou espera com aviso** | Com o OTP do número antigo a troca é imediata. Sem ele, fica pendente durante um prazo (*proposta*: 72 h). O número antigo e o e-mail são avisados, e o antigo pode cancelar. | Cobre o SIM perdido sem dar o canal a um *cookie*. Mas **só vale com o aviso entregue**: enquanto o KAM-115 não tiver canal, C é a opção A com atraso. Pede também um estado «pendente» que sobreviva a um reinício, logo a persistência do KAM-226. |

**Decidido: opção C** (o fundador, 2026-11-19). Com o OTP do número antigo, a troca é imediata. Sem ele, fica pendente 72 h (*proposta*), com aviso ao número antigo e ao e-mail, e o antigo pode cancelar. **Só protege com o aviso entregue** (KAM-115): até lá, a espera não avisa ninguém. O estado pendente tem de sobreviver a um reinício. Implementa-a o **KAM-226**.

### Verificação dos Critérios de Aceitação

Três critérios, **nenhum marcado**. Medido no ramo `feature/KAM-217-onboarding-web-identity`, sobre a `publico/main` em `f0a31b54`. Os números dos ensaios são fictícios, com 999, e não há chave real.

| Critério | Estado | Evidência nomeada |
|---|---|---|
| 1 | não satisfeito — caixa vazia | A `OwnerPort` não se escreveu: precisava das decisões 1 e 2, tomadas depois de o código estar feito, e o AGR não tem saída (`SaidaPorLigar`). Credores: **KAM-226**, com a saída do AGR no **KAM-227** |
| 2 | **parcial — caixa vazia** | **A base e a troca estão; o AGR e a persistência não.** O `server.ts` liga-se como `kamba_identity` por um *pool* e monta as duas rotas da troca com os adaptadores do KAM-211 (`montarTroca`, `trocaPeloPool`). A rede `data` e a cadeia estão no compose de `dev` e de `staging`, e o `TEN` está no inventário. Contra a base, como `kamba_identity` e pelo `trocaPeloPool` que o processo chama (o `montarTroca` do `server.ts` em si não tem ensaio, porque o processo não se importa sem arrancar): cinco pares de trocas concorrentes em dois tenants acabam cada uma no seu tenant, com um só dono por tenant («cinco pares de trocas concorrentes em dois tenants acabam cada uma no seu tenant», `packages/core-ts/tests_bd/dono.bd.test.ts`). Uma porta que falha com `23503` destrói a ligação e uma que acerta devolve-a, medido no argumento do `release` por um espião sobre o *pool* real; a troca seguinte do *pool* passa. **Falta**: a credencial do AGR (só tem consumidor com a `OwnerPort`) e o OTP e os pedidos persistidos, que pedem tabela nova. Credor: **KAM-226** |
| 3 | **parcial — caixa vazia** | **Na troca está medido, mas não à letra do critério; no painel do dono falta a `OwnerPort`.** O *gate* 6 ataca as duas rotas da troca três vezes cada, com o tenant de B no corpo, na consulta e no cabeçalho, e com o código certo do pedido de B na sessão de A. O resultado é `pedido=a` e `troca=nenhuma` (o grupo `painel` do condutor, do KAM-211). Contra a base, pela montagem do processo, o pedido da sessão de A verificado com o tenant de B dá `sem_pedido`, e nenhum dos dois donos muda. **A letra pede 404, e a troca não o dá.** Não há recurso de B que se nomeie por identificador: o pedido é a sessão (`troca:{sid}`). Uma falha dá 401 `{"erro":"codigo"}`, uma resposta só, pela razão do `/painel/verificar`. Fica escrita esta leitura, e a decisão — reescrever o critério para o 401 uniforme, ou fazer a troca dar 404 — passa ao **KAM-226** com o isolamento da conversa do dono no painel |

### Verificação da Definition of Done

| Caixa | Estado | Evidência nomeada |
|---|---|---|
| 1 | não satisfeito — caixa vazia | Nenhum critério marcado. Os critérios «Troca de telefone» e «Painel do dono» do KAM-211 e a caixa 9 do KAM-118 estão revistos com a evidência deste ticket, cada um com o credor que fica |
| 2 | marcado | As linhas novas do processo levam só `outcome`: `painel_troca_desligada`, os dois `painel_troca_aviso_*_por_entregar` e o `identidade_bd_falhou` do `excepcao`, que não escreve a mensagem do erro (KAM-068). O número em claro só existe dentro do `contactoDoNumero`, que é o sítio de chamada do `revelar()` já escrito no KAM-211. Os compose interpolam os segredos e não os escrevem, e os ensaios usam números fictícios e chaves de teste |


### Verificação da revisão adversarial

Uma revisão independente recebeu o diff e os requisitos, e não o raciocínio do ramo. Leu o código, os lints e a base, e mediu os mutantes por leitura. **Nenhum achado bloqueava.** Os treze corrigiram-se neste PR, cada um com a evidência ou a prosa que o fecha.

| # | Severidade | O que estava errado | Como se fechou |
|---|---|---|---|
| 1 | deve corrigir | A decisão 1 dizia que o `thread_id` se lê como `kamba_identity`, e esse papel não tem `SELECT` em `platform.tenants` (há um ensaio que o fixa) | A decisão diz que o `onboarding-web` precisa de uma segunda ligação `kamba_app`, ou de pedir o `thread_id` a quem o lê; e o KAM-226 também |
| 2 | deve corrigir | A opção C da decisão 2 dizia que o Python não tem cliente do BullMQ; o `ADR-L004` cita-o, e recusou-o pela interoperabilidade NÃO VERIFICADA e por ser dependência nova | A opção diz o custo real: medir a interoperabilidade e emendar o ADR |
| 3 | deve corrigir | A caixa 2 do DoD estava vazia, e a tabela dizia «marcado». O `lint_bloco` não o viu: só lê a primeira tabela do bloco | Caixa marcada. A cegueira do *linter* fica como achado fora de escopo |
| 4 | deve corrigir | O critério 3 devolvia a leitura do 404 «a quem escreveu o critério», sem credor que sobrevivesse à fusão | O KAM-226 é credor dos três critérios, e o critério de isolamento dele leva a decisão do 404 |
| 5 | deve corrigir | Com a cadeia definida e as chaves em falta, o processo subia, e o primeiro dono a acertar o código gastava-o e recebia um 500 | O `pepper_contact_hmac` e o `kek_contact_dek` passam a obrigatórios no `Secrets.arrancar` quando há cadeia |
| 6 | deve corrigir | O ensaio «uma porta que falha não deixa a ligação a meio» passava sem destruir a ligação: o `ROLLBACK` do `comTenant` limpa-a | Um espião sobre o *pool* real lê o argumento do `release`: `[true, false]` para uma falha e um acerto. Um `release()` sem destruir daria `[false, false]` e um só no sucesso daria `[false]`: os dois falham a asserção, lido e não corrido |
| 7 | deve corrigir | Uma ligação que caísse emprestada emitia `error` sem ouvinte e derrubava o processo, e com ele os casos em memória (PLAUSÍVEL, lido no código do `pg`) | Ouvinte em cada cliente, posto no `connect` do *pool*. Não reproduzido com um `pg_terminate_backend` |
| 8 | deve corrigir | O dicionário continuava a dizer «por montar no `server.ts`», e a cadeia e os nomes novos não estavam lá | Emenda 1.115 (§3.78) e `canon/dicionario.yaml` regenerado |
| 9 | menor | A decisão 3 dizia que a sessão dura 30 dias, e ela renova-se até 90, com revogações em memória | A decisão diz os dois |
| 10 | menor | A prosa dizia «pela montagem que o processo usa», e nenhum ensaio importa o `server.ts` | O critério 2 diz que o ensaiado é o `trocaPeloPool`, e que o `montarTroca` não tem ensaio |
| 11 | menor | Em `staging` a rede `data` entra sem condição, e em `dev` a cadeia nunca fica vazia | Escrito nas decisões do executor, com a razão |
| 12 | menor | O *pool* esperava sem fim por uma ligação | `connectionTimeoutMillis` de 5 s (*proposta*) |
| 13 | menor | «Nove campos» no `agent_invocation` (são onze), e «nenhuma resposta se perde» ao lado de «esgota as seis tentativas» | Onze campos, e o destino do turno depois das seis tentativas escrito |

---

## KAM-226 — Canal do dono: a `OwnerPort`, a mensagem do dono persistida e a troca com prova de posse

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-217, KAM-227 |
| Bloqueia | — |
| Responsável sugerido | Engenheiro de Runtime/IA (AGR) com Engenheiro de Plataforma (`onboarding-web`) e Responsável de Segurança |
| Documentos de referência | `EPIC-11_Modulos_Entrada.md` (blocos KAM-211, KAM-217 e KAM-227; as decisões do fundador no bloco do KAM-217), `EPIC-03_Agent_Runtime_Verticais.md` (bloco KAM-186), `EPIC-09_Onboarding_Governanca.md` (blocos KAM-086 e KAM-190), `02_Dicionario_de_Dados_Canonico.md` (§3.13 e §3.78), `../ops/secrets-inventory.yaml` |

### Contexto

Credor dos três critérios do KAM-217, aberto no PR dele, com um número provisório da coordenação do lote 12. O KAM-217 ligou o `onboarding-web` à base como `kamba_identity` e montou a troca de telefone sobre um *pool*. As três decisões que faltavam tomou-as o fundador a 2026-11-19 (bloco do KAM-217): a mensagem do dono numa fonte persistida que o AGR lê por identificador, com a resposta a voltar ao painel pelo canal `painel` (decisão 1, A); a saída do AGR por um evento de resposta (decisão 2, A, contrato no **KAM-227**); e a troca com prova do número antigo ou espera de 72 h com aviso (decisão 3, C). O desafio do OTP e os pedidos de troca vivem em memória. O `thread_id` do dono lê-se no `tenants.owner_contact_id`, que o `kamba_identity` não lê. E o serviço `onboarding-web` dos três compose não define o `KAMBA_AMBIENTE` nem os segredos da inscrição, pelo que, lido o `server.ts`, não arranca pelo compose (INDÍCIO).

### Objectivo

O dono fala com o Assistente do Dono pelo painel, com o mesmo `thread_id` e a mesma ToolLayer do WhatsApp, e a troca de telefone segue a regra C e sobrevive a um reinício.

### Critérios de Aceitação

- [ ] **Fonte persistida da mensagem do dono** (decisão 1, A): o painel grava a mensagem numa fonte persistida, a invocação leva o identificador dela (emenda ao §3.13, aditiva), e o AGR lê-a pelo identificador e passa-a pelo `guardas.mensagem_do_cliente` antes da janela. A mesma rota serve o WhatsApp, e fecha a saída (b) do KAM-186.
- [ ] **`OwnerPort`**: entrega a mensagem do painel ao AGR com persona `dono` e o `thread_id` do dono no WhatsApp (o `contact_id` do `tenants.owner_contact_id`, por uma ligação que o leia — o `kamba_identity` não o lê), e a resposta volta ao painel pelo canal `painel` do evento do KAM-227; a mesma tool pelo painel e pelo WhatsApp.
- [ ] **Troca com prova de posse** (decisão 3, C): com o OTP do número antigo, a troca é imediata; sem ele, fica pendente 72 h (*proposta*), com aviso ao número antigo e ao e-mail pelos ganchos do KAM-115, e o antigo pode cancelar. O desafio do OTP, os pedidos e o estado pendente persistem: um reinício a meio não perde nem duplica uma troca.
- [ ] O `onboarding-web` chama o AGR com credencial própria (inventário, compose e rede), e a sessão do tenant A com a conversa do tenant B → 404, no *gate* 6. Na troca, o critério 3 do KAM-217 fecha-se à letra (404) ou reescreve-se para o 401 uniforme que ela dá hoje, por decisão de quem o escreveu.
- [ ] O serviço `onboarding-web` do compose de `dev` e de `staging` arranca e responde ao `/healthz`, com o `KAMBA_AMBIENTE` e os segredos da inscrição.

### Detalhes Técnicos

- **Decisões que não se reabrem:** as três do fundador de 2026-11-19 (bloco do KAM-217), a do KAM-186 (o `agent_invocation` sem o texto; leva o identificador da mensagem, não o corpo) e as do KAM-118.
- **Esquema:** a fonte persistida da mensagem, e a persistência do OTP, dos pedidos e do estado pendente, são tabelas novas. Leva migração, e entra quando tiver a vaga num lote.
- **A regra C só protege com o aviso entregue.** Enquanto o KAM-115 não tiver canal, a espera de 72 h não avisa ninguém, e isso diz-se na verificação deste ticket.
- **Fora deste ticket:** o contrato do evento de resposta do AGR (KAM-227); a entrega dos avisos (KAM-115); o provisionamento do dono (KAM-215); o número da loja no painel (KAM-216).

### Testes Requeridos

- Integração: a mesma tool pelo painel e pelo WhatsApp; a mensagem do painel lida pelo identificador; uma troca pendente que atravessa um reinício; a troca imediata com o OTP do número antigo; o cancelamento pelo antigo.
- Isolamento: dono A contra tenant B na conversa do painel e na troca pendente.
- **Adversarial:** sessão do painel de outro tenant; texto que imita um botão pelo painel; o mesmo pedido de troca em duas réplicas; um *cookie* roubado sem o OTP do antigo não troca antes das 72 h.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; os três critérios do KAM-217 revistos com a evidência.
- [ ] Telefone nunca em claro em logs, URLs ou eventos (ADR-010); sem segredos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-226 da KAMBÁ (a OwnerPort, a mensagem do dono persistida e a troca com prova de posse).
Lê specs/EPIC-11_Modulos_Entrada.md (blocos KAM-211, KAM-217, KAM-226 e KAM-227), services/onboarding-web/src/server.ts,
services/onboarding-web/src/painel/rotas.ts, packages/core-ts/src/dono/ e services/agr/src/kamba_agr/contexto.py.
Decisões tomadas (2026-11-19): decisão 1 opção A, decisão 3 opção C, do bloco do KAM-217. Pede a vaga de migração.
Regras: tenant_id só do cookie assinado; a mesma ToolLayer; o agent_invocation leva o identificador, nunca o corpo.
Testes: integração, isolamento e adversarial (sessão cruzada, texto que imita botão, reinício a meio da troca, cookie roubado).
```

---

## KAM-227 — Saída do AGR: o evento de resposta do turno, para o WhatsApp e para o painel

| Campo | Valor |
|---|---|
| Epic | EPIC-11 — Módulos de Entrada |
| Fase | 1 |
| Tipo | feature |
| Prioridade | P1 |
| Estimativa | L |
| Dependências | KAM-217 |
| Bloqueia | KAM-226 |
| Responsável sugerido | Engenheiro de Runtime/IA (AGR) com Engenheiro de Plataforma (`worker-canal`, barramento de eventos) |
| Documentos de referência | `EPIC-11_Modulos_Entrada.md` (bloco KAM-217, decisão 2), `EPIC-03_Agent_Runtime_Verticais.md` (bloco KAM-186, o achado da `PortaDeSaida`), `EPIC-02_Canais_WhatsApp_Handoff.md` (bloco KAM-015), `EPIC-01_Fundacoes_Dados.md` (bloco KAM-006), `02_Dicionario_de_Dados_Canonico.md` |

### Contexto

Aberto no PR do KAM-217, com um número provisório da coordenação do lote 12, pela decisão 2 do fundador de 2026-11-19 (opção A). Hoje o AGR não responde a ninguém: a `PortaDeSaida` do grafo é a `SaidaPorLigar`, que levanta e dá 503 `saida_por_ligar`, e o Outbound (`Saida`, `packages/core-ts/src/outbound/`, KAM-015) é uma biblioteca TypeScript que nenhum serviço instancia. O KAM-186 deixou isto como «achado com credor por abrir». O fundador decidiu que a resposta sai como um evento pela `platform.evt_emitir`, na transacção do turno, pelo barramento do KAM-006. Ticket próprio, e não parte do KAM-226, porque serve também o WhatsApp.

### Objectivo

Um turno do AGR que quer responder emite um evento de resposta, e a resposta chega ao WhatsApp pelo `Saida` e ao painel pelo `onboarding-web`, sem se perder nem duplicar.

### Critérios de Aceitação

- [ ] **O contrato:** um evento de resposta do turno no `registry/` e no dicionário (nome por proposta, antes de código), com o tenant, o `thread_id`, o canal (`whatsapp` ou `painel`), uma chave idempotente (o `turn_id` com a ordem da resposta), o texto já validado pelo *renderer* e os botões. Sem telefone e sem corpo do cliente.
- [ ] **O produtor:** o AGR emite-o no `enfileirar` da `PortaDeSaida`, pela `platform.evt_emitir`, na transacção do turno; a `SaidaPorLigar` deixa de ser a porta do `main()`. Um turno repetido não emite duas vezes.
- [ ] **Os consumidores:** o `worker-canal` consome o canal `whatsapp` e instancia o `Saida` do KAM-015; o `onboarding-web` consome o canal `painel`. As subscrições entram por revisão de dados, e cada consumidor é idempotente pela chave do evento.
- [ ] Contra o PostgreSQL e a fila: um turno com resposta dá **1** envio pelo `Saida`, a reentrega 3× do evento continua a dar **1**, e um evento de outro tenant não chega ao consumidor errado.

### Detalhes Técnicos

- **Decisões que não se reabrem:** a decisão 2 do fundador de 2026-11-19 (bloco do KAM-217) e a do KAM-186.
- **Esquema:** as subscrições são revisões de dados, e o evento pode pedir concessões ao papel do AGR na `evt_emitir`. Leva migração, e entra quando tiver a vaga num lote.
- **Fora deste ticket:** a fonte persistida da mensagem do dono e a `OwnerPort` (KAM-226); a janela de 24 h e os *templates* do Outbound, que são do KAM-015.

### Testes Requeridos

- Integração: turno → evento → `Saida` contra a base e o servidor Graph falso; turno → evento → painel.
- Isolamento: o evento de A não chega ao consumidor de B; o tenant é o do envelope.
- **Adversarial:** reentrega 3×; turno repetido pelo *shim*; evento com canal desconhecido vai à DLQ.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos; a decisão 2 do bloco do KAM-217 e o achado da `PortaDeSaida` do KAM-186 revistos com a evidência.
- [ ] Telefone nunca em claro em logs, URLs ou eventos (ADR-010); sem segredos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-227 da KAMBÁ (o evento de resposta do AGR).
Lê specs/EPIC-11_Modulos_Entrada.md (blocos KAM-217 e KAM-227), services/agr/src/kamba_agr/grafos.py (SaidaPorLigar),
packages/core-ts/src/outbound/ e o barramento de eventos do KAM-006. Pede a vaga de migração.
Decisão tomada (2026-11-19): evento pela platform.evt_emitir, na transacção do turno. O nome do evento entra pelo dicionário.
Testes: integração contra a base, isolamento e adversarial (reentrega, turno repetido, canal desconhecido).
```

---

## Riscos do Epic e itens NÃO VERIFICADOS

| Risco / item | Estado | Impacto | Mitigação / critério de saída | Decisão |
|---|---|---|---|---|
| Publicação automática em Instagram/Facebook: Advanced Access (App Review + Business Verification), prazo sem fonte oficial, documentos angolanos por validar | CONFIRMADO (requisitos); INDÍCIO (prazo) | Sem publicação por API; PMEs podem não ter Página/conta profissional | Diferida: publicação manual; só gancho `SocialPublisher`; gatilho = App Review aprovado e ≥ 3 PMEs com Página/conta (KAM-127) | D13, D5 |
| Contradição da Photoroom sobre treino em planos de API; Bria sem declaração de treino; DPA da Bria só em Enterprise | CONFIRMADO (contradição); NÃO VERIFICADO (treino) | Fotos de clientes usadas para treino | Carta escrita por fornecedor antes de fotos reais; só imagens sintéticas até lá (KAM-120) | D9 |
| BFL (licença perpétua de treino) e remove.bg (passa a Leonardo.Ai a 2026-12-01) | CONFIRMADO | Fornecedor inadequado ou instável a meio do Piloto | Excluídos por configuração testada; *watch list* trimestral (`../docs/tecnica/09` §21.3) | — |
| Qualidade de fundo limpo e *relighting* em fotos angolanas; latência real | NÃO VERIFICADO | Resultados rejeitados pelo dono | *Bake-off* com ≥ 30 fotos reais autorizadas; limiares *proposta*; contingência de fornecedor | — |
| Imagens com rostos, matrículas, EXIF a fornecedores nos EUA = transferência internacional | INDÍCIO (qualificação); CONFIRMADO (definição e precedente Crescer Tech) | Multa da APD; incumprimento de ADR-008 | Gate local de rostos/matrículas; EXIF removido; `allowed_destinations`; inventário KAM-069; parecer (E5 Q1–Q3) | D1, D9 |
| Qualidade de legendas em português de Angola (a Google recomenda pt-BR) | CONFIRMADO (doc); NÃO VERIFICADO (qualidade) | Texto com marcas de pt-BR, perda de confiança | Lexicon, correcção e golden com revisores angolanos (KAM-121, KAM-125) | — |
| Direitos de autor de imagens geradas e obras derivadas (Lei 15/14: autor = pessoa física) | INDÍCIO | Sem protecção ou semelhança com conteúdo de outros | Sem exclusividade nos termos; fotos só do dono; parecer (E5 Q4–Q5) | D9 |
| Rotulagem de IA: política de 2026 da Meta e do TikTok não lida; `is_ai_generated` existe na API do Instagram | CONFIRMADO (parâmetro); NÃO VERIFICADO (política) | Bloqueio ou etiqueta automática; dono sem rótulo | Marcação interna e instrução na entrega; pergunta à Meta (E5 Meta Q3) | D13 |
| Remetente «KAMBÁ → dono» colide com ADR-011/D10; classificação de templates (marketing vs utility) | NÃO VERIFICADO | *Push* indisponível ou mais caro | O dono inicia; *push* opcional como marketing (≈ 0,0225 USD); sem número da KAMBÁ no Piloto | D10 |
| Telemóvel do dono igual ao número da loja (coexistência) | Limitação de desenho | Sem canal dono → loja | Degrada para painel web; teste em KAM-118 | D2 |
| Troca de SIM do dono | INDÍCIO | Tomada de controlo do canal do dono | Novo OTP, bloqueio de 24 h a acções sensíveis, botões, aviso (KAM-115) | — |
| Orçamento confundido com documento fiscal; software não validado AGT | INDÍCIO | Responsabilidade fiscal | Rótulo «não é factura», sem numeração; parecer (E5 Q8); Factura AI só como spike (KAM-126) | D7 |
| Certificação AGT de Vero/CacimboERP auto-declarada; calendário da Fase 2 em conflito de fontes (2026-09-21 vs 2027-01-01) | INDÍCIO / NÃO VERIFICADO | Dependência de parceiro não validado | Resposta escrita da AGT e validação na lista oficial (KAM-126) | D7 |
| Preços de teste e disposição a pagar dos módulos | NÃO VERIFICADO | H12 inconclusiva | Hipóteses etiquetadas; pagamento confirmado como evidência (KAM-124, KAM-127) | — |
| Módulos diluem o foco e atrasam o core | Risco de projecto | Fase 0 derrapa | Máx. 4, finos, fora do gate da Fase 0, cortáveis; abate por critérios (KAM-127) | — |
| Marketing por WhatsApp à PME: opt-in separado (Lei 22/11 art. 19.º, Instrutivo INACOM 4/20) | CONFIRMADO (texto); aplicação a WhatsApp NÃO VERIFICADA | *Push* sem base legal | Opt-in separado do dono; PARAR; parecer (E5 Q9) | D9 |
| Todos os limiares marcados *proposta* | A calibrar | Falsos positivos/negativos | Registo de calibração no fim do Piloto | — |

---

## Tabela de aprovação

| Papel | Nome | Assinatura | Data |
|---|---|---|---|
| Arquitecto de Plataforma |  |  |  |
| Responsável de Segurança |  |  |  |
| Responsável de Produto |  |  |  |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial: 10 tickets (KAM-118 a KAM-127) dos módulos de entrada do Piloto (ADR-020): canal do dono, Catálogo AI conversacional, Foto de produtos AI, Social AI com publicação manual, Orçamento expresso, planos e metering, golden, spike Factura AI e experimento H10–H12. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-129: as 3 referências aos artefactos de validação passam a `../docs/tecnica/evidencia/validacao/…`; antes não resolviam de posição nenhuma. Os artefactos visados continuam a ser saída dos KAM-120 (registo do *bake-off*), KAM-126 e KAM-127, e não se criam aqui. | Equipa KAMBÁ |
| 1.2 | Outubro 2026 | KAM-145: os **22** caminhos dentro dos blocos de *handoff* passam a ser relativos à raiz do repositório, que é onde o executor corre; lidos de lá, antes apontavam para **fora** da árvore. Com ele, a referência a um ficheiro da biblioteca exploratória que não tinha directorio nenhum passa a ter o seu, e deixa de não resolver de posição alguma. A regra ficou declarada em `specs/01_Engineering_Standards_e_Handoff.md` §5, e o gate `lint_handoff` passa a recusá-los. Fora dos blocos de *handoff* nada muda. Sem alteração de conteúdo técnico. | Equipa KAMBÁ |
| 1.3 | Outubro 2026 | KAM-128: As **5** linhas de cabeçalho — `Documento-fonte`, `Documentos relacionados` e três `Documentos de referência` de blocos de ticket — passam a citar o ficheiro da biblioteca exploratória pelo caminho completo. As restantes referências dessas mesmas linhas já estavam certas e ficaram intactas. Linha acrescentada pelo **KAM-146**, que paga as onze que o KAM-128 não escreveu. | Equipa KAMBÁ |
| 1.4 | Novembro 2026 | KAM-126: *spike* de Factura AI entregue. **Seis dos oito critérios marcados e dois devolvidos ao fundador**, porque dependem de contactar a AGT ou um fornecedor — a fronteira que o próprio *handoff* escreve. Novo relatório em `../docs/tecnica/evidencia/validacao/KAM-126_Factura_AI.md` com **49 afirmações com estado** (14 CONFIRMADO, 17 INDÍCIO, 18 NÃO VERIFICADO), o questionário à AGT com as três perguntas que desbloqueiam o ticket, ficha de **quatro** candidatos acima do mínimo de três, e matriz de treze predicados onde **45 das 52 células estão a NÃO VERIFICADO e nenhuma está a SIM**. Nenhum certificado afirmado como validado: a lista oficial da AGT não foi obtida. Novo instrumento descartável em `spikes/factura-ai/`, com os sete predicados do critério 4 medidos contra um *mock* e **dez canários a provar que cada ensaio reprova quando o seu predicado desaparece**; **nenhum código de facturação entrou na `main`** e nada foi medido contra fornecedor. Modelo de custo com os preços datados da CacimboERP, as duas leituras do valor inicial que diferem **50%** no ano 1, o achado de que um preçário por contribuinte é **custo variável puro sem economia de escala**, e a condição (c) invertida a dar o preço mínimo de **104 167 Kz/PME/mês**, exacto como aritmética sobre um preço que é INDÍCIO e um escalão que é hipótese de planeamento — sem inventar o preço de Factura AI. Recomendação **adiar**, pela regra pré-registada: (a) e (d) falham, (b) não foi medido, (c) não é mensurável. **Doze caixas devolvidas, todas com credor que sobrevive à fusão.** A revisão adversarial deu **treze achados, todos verificados contra a árvore**, e quatro mudaram o produto: o oráculo do rótulo da proforma era a constante do próprio *mock* (trocá-lo dava 7/7 verdes com a proforma a declarar-se factura fiscal); três mutações de multi-tenancy deixavam 7/7 verdes, pelo que **dois dos sete predicados estavam por medir**; o cliente fala o contrato do *mock* e não o da Vero, logo apontá-lo a um fornecedor dá 401 e zero ensaios; e a **numeração do artigo que exige software validado está em conflito** entre o `E2` §6.1 (art. 17) e o `../docs/tecnica/evidencia/E3_Regulatorio_Dados.md` §6 (art. 7.º), ambos CONFIRMADO. O canário passou de seis a dez defeitos. Sem alteração a tickets vizinhos e sem tocar no `specs/INDICE.md`. | Equipa KAMBÁ |
| 1.5 | Novembro 2026 | **Credor nomeado, no PR do KAM-049:** o bloco do KAM-119 ganha, nos Detalhes Técnicos, a linha da montagem real do Catálogo AI que recebe do KAM-049 — a `FonteDeMedia` sobre o MED, o descodificador de imagem, a ponte Python→TypeScript para o `screen` do KAM-088 e a `PortaDoRegisto` sobre o COM. Sem critério novo, sem mudar estimativa nem dependências. | Equipa KAMBÁ |
| 1.6 | Novembro 2026 | **KAM-120 entregue em parte: a Foto de produtos AI.** Bloco do KAM-120: as decisões do executor (biblioteca `kamba_core.foto`; o adaptador recebe bytes e não a referência; finalidade `imagem` nova; recusa em vez de desfoque; `custo_usd` em vez de `custo_minor`, devolvida) e as secções «Verificação dos Critérios de Aceitação» e «Verificação da Definition of Done»: **um critério marcado de dez** (a lista de recusa) e **nenhuma caixa de cinco** na DoD, e a secção «Verificação da revisão adversarial» (dois defeitos da revisão `0054` apanhados pelo gate 8 e doze achados da revisão, um deles bloqueante — o *bake-off* enviava a foto crua —, todos os confirmados fechados). As vazias têm credor: o detector local e a biblioteca de imagem (ticket a abrir na integração), o botão de escolha (KAM-119), a fila (KAM-194), o *bake-off* e as cartas de não-treino (o fundador) e as três leituras devolvidas (critérios 1, 5 e 10). Revisão `0054` e emenda 1.94 do dicionário, os números da integração do lote. | Equipa KAMBÁ |
| 1.7 | Novembro 2026 | **KAM-124 entregue em parte: planos, entitlements e metering de custo dos módulos de entrada.** Revisão `0057`, emenda 1.98. Bloco do KAM-124: as decisões do executor (o TEN do KAM-009 sem alteração, provado para os quatro módulos; a consolidação e não um evento; o *ledger* com `custo_usd` e `custo_minor`; os preços de teste no plano e na base; a guarda de orçamento composta por cima da quota), a verificação dos critérios (**cinco de dez** marcados) e do DoD, e a revisão adversarial. | Equipa KAMBÁ |
| 1.8 | Novembro 2026 | O bloco do KAM-119 passa a bloquear o **KAM-202** (EPIC-04), aberto no PR do KAM-094: a restrição de BD na publicação da `offer_terms` liga-se depois de o KAM-119 pôr o COM a gravar a decisão de screening antes do `publishProduct`. | Equipa KAMBÁ |
| 1.9 | Novembro 2026 | **KAM-118 entregue em parte: o canal do dono.** Revisão `0070` (sobre a `0069` do KAM-195, renumerada na integração), emenda 1.112 do dicionário (§3.78). Bloco do KAM-118: as decisões do executor (a porta única `definir_dono`, que escreve o `papel` e o `tenants.owner_contact_id`; o `INSERT` por coluna do `kamba_identity`; a persona no campo aditivo `agent_invocation.persona` e não no `ChannelContext`; o `dono.yaml` pelo módulo `catalogo`, com 75% de reaproveitamento; o `owner_channel_wa` calculado e não coluna), a verificação dos critérios (**cinco de dez** marcados) e do DoD (**três de seis**), e a revisão adversarial (nenhum achado bloqueante). **Duas decisões do fundador, de 2026-11-18**: «Manter as regras» — o critério 8 reescreve-se para o Piloto, sem *push* ao dono pelo número da loja nem *template* de `marketing` —, e «Servir todos os donos» — o Assistente do Dono atende qualquer dono, e cada tool fecha-se pelo entitlement do seu módulo. As vazias têm credor: as ligações de produção — o provisionamento, a troca de telefone, o botão e o painel — no **KAM-211**, aberto neste PR (o bloco, a linha do §3 e o `Bloqueia` do KAM-118). | Equipa KAMBÁ |
| 1.10 | Novembro 2026 | **KAM-211 entregue em parte: as ligações de produção do canal do dono.** Sem migração. Emenda 1.114 do dicionário (§3.78 e §3.56), escrita como 1.113 e renumerada na integração, depois do KAM-204. Bloco do KAM-211: as decisões do executor, a verificação dos critérios (**um de seis** marcado: a retoma; o botão confirma e fica parcial, porque nenhuma acção executa) e do DoD (**dois de três**), e a revisão adversarial (onze achados, nenhum bloqueante; dez corrigidos, e a prova de posse da troca como decisão por tomar no KAM-217). A retoma decide o grafo pelo papel de agora, e fecha o achado 4 da revisão do KAM-118; o botão chega ao `confirmar` pelo campo aditivo `agent_invocation.botao` e pelo nó `confirm` do grafo do dono; a troca de telefone ganha duas rotas no painel e os adaptadores da porta, ensaiados contra a base. As caixas 3, 4, 5, 7 e 9 do KAM-118 revistas. Os três critérios que ficam têm credor novo, aberto neste PR: o provisionamento no **KAM-215**, o canal no painel no **KAM-216** e a `OwnerPort` com o processo web ligado no **KAM-217** (os blocos, as linhas do §3 e o `Bloqueia` do KAM-211). | Equipa KAMBÁ |
| 1.11 | Novembro 2026 | **KAM-217 entregue em parte: o processo web ligado à base e a troca de telefone montada.** Sem migração. Emenda 1.115 do dicionário (§3.78), com número a acertar na integração. Bloco do KAM-217: as decisões do executor (o `kamba_identity` por um *pool*, uma ligação por operação, os avisos da troca registados e não entregues, a rede `data` só em `dev` e `staging`), **três decisões do fundador, tomadas a 2026-11-19** (o contrato do texto e da resposta do painel, opção A; a saída do AGR, opção A; a prova de posse da troca, opção C), a verificação dos critérios (**nenhum de três** marcado: a troca está montada e ensaiada contra a base, e o critério 3 não dá 404 à letra) e do DoD (**um de dois**). Os critérios «Troca de telefone» e «Painel do dono» do KAM-211 e a caixa 9 do KAM-118 revistos. O que fica tem dois credores novos, abertos neste PR com números provisórios: a fonte persistida da mensagem do dono, a `OwnerPort`, a troca persistida com a regra C e a credencial do AGR no **KAM-226**, e o contrato do evento de resposta do AGR no **KAM-227**, de que o KAM-226 depende (os blocos, as linhas do §3 e o `Bloqueia` do KAM-217). | Equipa KAMBÁ |
