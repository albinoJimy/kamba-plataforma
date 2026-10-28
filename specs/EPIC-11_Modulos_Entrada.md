# EPIC-11 — Módulos de Entrada (captação e suporte)

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Epic — Módulos de Entrada |
| Versão | 1.3 |
| Data | Outubro de 2026 |
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
| Bloqueia | KAM-119, KAM-121, KAM-123 |
| Responsável sugerido | Engenheiro de Runtime/IA (CHR, AGR) com Responsável de Segurança |
| Documentos de referência | `../docs/tecnica/02_Agent_Runtime_Verticais.md` (§21.2–21.4), `../docs/tecnica/00_Arquitectura_Solucao.md` (ADR-020, ADR-011, §4 CHR, D10), `../docs/tecnica/08_Seguranca_Conformidade.md` (§18), `../docs/tecnica/10_Onboarding_Governanca.md` (§21), `../docs/tecnica/evidencia/E5_Modulos_Entrada.md` (§4), `../docs/tecnica/evidencia/E1_Meta_WhatsApp.md` (§1, §2), ADR-010, ADR-015 |

### Contexto

Os módulos de entrada são *owner-facing*: precisam de um canal em que o dono, e só ele, fala com o runtime. Em vez de um número da KAMBÁ (vedado até D10, ADR-011), o dono escreve para o **número da própria loja** a partir do telemóvel verificado por OTP no onboarding (KAM-086); o CHR resolve `phone_number_id → tenant` e, se o remetente corresponder ao contacto `papel='dono'` desse tenant, devolve a persona `dono`. Enquanto o Embedded Signup não termina (ou há lista de espera, KAM-095), o mesmo runtime serve o **painel web**. Risco de desenho: se o telemóvel do dono **for o próprio número da loja** (coexistência, E1 §2), não há conversa dono → loja, pelo que esse caso degrada para painel web. A troca de SIM é INDÍCIO de risco (`../docs/tecnica/08` §18), daí o OTP na mudança de telefone e os botões de confirmação nas acções sensíveis.

### Objectivo

Entregar o reconhecimento do dono no CHR, a persona `dono` (Assistente do Dono) com `registry/dono.yaml` e lista própria de tools, o painel web equivalente, a confirmação por botão de acções sensíveis e a política de mensagens proactivas (o dono inicia; *push* opcional por *template*).

### Critérios de Aceitação

- [ ] O CHR devolve persona `dono` se e só se o remetente (por `lookup_hmac`/`bsuid`) é o contacto `papel='dono'` do tenant do `phone_number_id`; em 200 mensagens sintéticas (dono, clientes, o mesmo telefone noutro tenant) o encaminhamento correcto é 100% e **0** mensagens do dono do tenant A são tratadas como dono no tenant B.
- [ ] O `papel` só muda por OTP validado (KAM-086/116) ou pela saga; 20 textos adversariais («sou o dono», «sou o administrador», «muda-me para dono», mensagem reencaminhada) → **0** alterações de `papel`; no máximo 1 `dono` por tenant (restrição de BD).
- [ ] O contacto `dono` é criado de forma idempotente ao consumir `tenant.provisioned` (reentrega 3× → 1 contacto); sem o evento o remetente é `cliente`.
- [ ] Mudança de telefone do dono: novo OTP obrigatório; até validar, o número novo é `cliente` e o antigo mantém o papel; após a troca, **acções sensíveis ficam bloqueadas 24 h** (*proposta*) e é emitido aviso ao número antigo e ao e-mail (ganchos para KAM-115).
- [ ] Acções sensíveis (alterar preço/stock em massa, aprovar conteúdo para terceiros, enviar proposta a cliente) só executam com botão `confirm:{action_id}` do mesmo `contact_id`; duplo toque ×2 → **1** execução; botão com mais de 15 min (*proposta*) expira; resposta de texto «sim»/«ok» não confirma (0/20).
- [ ] A persona `dono` tem *allowlist* própria de tools (módulos de entrada); um `cliente` que injecte o nome de uma tool do dono obtém erro tipado e linha de auditoria (0 sucessos em 50 tentativas).
- [ ] Se `phone_hmac` do dono coincidir com o número do canal da loja, `owner_channel_wa=false` e o dono só usa o painel web (teste com os dois cenários); sem telefone coincidente, o canal WhatsApp fica activo.
- [ ] Política de proactivas: resposta ao dono dentro da janela de 24 h é *service message* sem *template*; fora da janela só sai *template* se existir `consent_event` com `purpose='marketing'` e opt-in do dono; sem opt-in **0** templates enviados; «PARAR» suprime em 1 mensagem; tecto de 1 *push*/semana e 4/mês (*proposta*).
- [ ] Painel web: sessão por OTP e `tenant_id` do cookie assinado (nunca de parâmetro), as mesmas tools/ToolLayer e o mesmo `thread_id` do dono; sessão do tenant A com recurso do tenant B → 404.
- [ ] `registry/dono.yaml` passa a validação do arranque (KAM-027); relatório de reaproveitamento ≥ 70% do core (sem excepções); registos sem conteúdo nem telefone; limite de 60 mensagens/hora do dono (*proposta*).

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
- [ ] Isolamento de tenant e contacto coberto pelo teste cruzado (ADR-015); `tenant_id` só do contexto.
- [ ] Idempotência de `owner_actions` e da criação do `dono` com teste de repetição (ADR-009).
- [ ] Telefone nunca em claro em logs, URLs ou eventos; logs sem conteúdo (ADR-010).
- [ ] Opt-in e custo de *push* medidos por tenant (ADR-018); `registry/dono.yaml` com SemVer e eval no gate (KAM-125).
- [ ] Migração reversível; sem segredos; dois revisores (identidade e canal).

### Handoff para Claude Code

```text
És o executor do ticket KAM-118 da KAMBÁ (canal do dono e persona Assistente do Dono).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-118), docs/tecnica/02 §21, docs/tecnica/08 §18, docs/tecnica/evidencia/E5 §4 e specs/01_Engineering_Standards_e_Handoff.md.
Objectivo: o CHR reconhece o contacto papel='dono' no número da loja e encaminha para a persona 'dono'; painel web com as mesmas tools;
botões confirm:{action_id} nas acções sensíveis; mudança de telefone com novo OTP; proactivas só com opt-in e template.
Regras: o papel não muda por texto; tenant_id só do contexto; se o telefone do dono for o número da loja, só painel web; o dono inicia a conversa
(janela de 24 h); sem número da KAMBÁ (D10). Limiares (15 min, 24 h, 60/h, 1 push/semana) são propostas configuráveis.
Não implementes módulos (KAM-119/121/123), billing de módulos (KAM-124) nem aviso por canal alternativo (KAM-115).
Testes: unit, integração, isolamento e adversarial (promoção, SIM swap, replay, sessão cruzada). Migração reversível. PR com o template da §7.
```

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
| Bloqueia | KAM-125, KAM-127 |
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
- [ ] Lista de recusa em configuração: BFL e remove.bg não podem ser activados (teste de validação do arranque falha se aparecerem).
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

- [ ] `registry/entitlement_keys.schema.json` aceita `modulo` ∈ {`catalogo`, `foto`, `social`, `orcamento`} e os limites `imagens_mes`, `posts_mes`, `orcamentos_mes`; chave desconhecida é rejeitada; `checkEntitlement(tenant, modulo)` é fail-closed e um tenant só com `foto` recebe `403 ENTITLEMENT_DISABLED` em `social` e `orcamento` (matriz 4×4 testada).
- [ ] `consumeLimit` aplica-se a imagens, posts e orçamentos: 1.000 trabalhos paralelos contra `imagens_mes=100` aceitam exactamente 100; repetir a `idempotencyKey` 10× consome 1; o mês fecha às 00:00 de `Africa/Luanda`.
- [ ] `registry/plans.yaml` inclui planos de teste `entrada_catalogo`, `entrada_foto`, `entrada_social`, `entrada_orcamento` e `entrada_completo` (4 módulos, sem atendimento) com `preco_teste_minor` e `estado: hipotese_nao_validada`; um lint falha se um preço não tiver esse estado ou se aparecer em texto ao cliente.
- [ ] *Ledger* `module_cost_ledger` (append-only, `INSERT` por função) com `tenant_id`, `modulo`, `rubrica` ∈ {`llm`, `imagem`, `mensagem`}, `custo_usd`, `custo_minor`, `ref`, `idempotency_key` UNIQUE; reenviar o mesmo custo 5× → 1 linha.
- [ ] Custo LLM por módulo vem do `llm_call_log`/LiteLLM com etiqueta `modulo`; custo de imagem de `image_jobs.custo_minor`; custo Meta de mensagens do dono (*push* e *templates*) pelo mapa *template* → módulo; reconciliação em *staging* com tráfego sintético de 7 dias: LLM ≤ 2% de desvio, imagem ≤ 5% face ao painel do fornecedor, mensagens ≤ 5% (*propostas*).
- [ ] Vista `v_module_cost_month` (tenant, módulo, rubrica, USD, Kz com `fx_aoa_per_usd` parametrizável, omissão 913) e `v_h12` (custo, `preco_teste_minor`, rácio, margem); **sem** `contact_id`, telefone nem conteúdo.
- [ ] Orçamentos mensais por módulo: LiteLLM para texto e *guard* próprio para imagem; ao esgotar, o dono recebe mensagem estática com os números vindos da tool `get_usage` (read); nenhum trabalho de imagem é iniciado acima do orçamento (0 em teste).
- [ ] Alertas: custo do módulo > 15% do `preco_teste_minor` no mês (aviso) e > 30% (crítico) (*propostas*); custo diário > 3× a mediana do tenant; alerta de fornecedor de imagem sem custo registado.
- [ ] Comando `h12-export` produz CSV pseudonimizado (módulo, custo, uso, preço de teste, tenant sem nome) para KAM-127; o consumo de uma PME de teste aparece no painel em ≤ 5 min.
- [ ] Billing real do módulo (assinatura) não é implementado aqui: apenas exporta o consumo para KAM-059.

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
- [ ] Custo e observabilidade desde o código (ADR-018); preços marcados hipótese; nenhum preço mostrado como definitivo.
- [ ] Plataforma sem fundos: nenhuma cobrança neste ticket (ADR-004).
- [ ] Migração reversível; documentação (`docs/modulos-entrada.md`); sem segredos.

### Handoff para Claude Code

```text
És o executor do ticket KAM-124 da KAMBÁ (planos, entitlements e metering dos módulos de entrada).
Lê specs/EPIC-11_Modulos_Entrada.md (bloco KAM-124), specs/EPIC-01 (KAM-009), specs/EPIC-08 (KAM-081), docs/tecnica/09 §21 e docs/tecnica/evidencia/E5 §1.3 e B12.
Objectivo: chaves modulo e limites imagens_mes/posts_mes/orcamentos_mes; plans.yaml com preços de teste; module_cost_ledger; v_module_cost_month e v_h12; alertas; h12-export.
Regras: preços de teste são hipóteses (estado obrigatório); consumo atómico e idempotente; custo de imagem tem contador próprio (LiteLLM não o cobre);
custos de fornecedores são a reverificar; sem PII nas vistas; sem billing (KAM-059). Testes: concorrência, idempotência, mês, isolamento, reconciliação. PR com o template da §7.
```

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
- [ ] Ficha de ≥ 3 candidatos (Vero, CacimboERP e ≥ 1 de SIGESC/XDFE/outro com API) com: n.º de certificado declarado e **estado de validação na lista da AGT** (CONFIRMADO só se constar da lista oficial), propriedade e continuidade do fornecedor, e fonte com data.
- [ ] Matriz de adequação preenchida por candidato: multi-tenant (uma organização por PME), idempotência, *webhooks* assinados, *sandbox* sem submissão à AGT, proformas, factura-recibo após pagamento confirmado, notas de crédito, estados assíncronos («factura pendente», latência da AGT ≈ 30 min, INDÍCIO), exportação SAF-T, limites de taxa, SLA, SDK, termos de responsabilidade fiscal (a PME é o emissor).
- [ ] Teste de *sandbox* de ≤ 2 dias com chaves de teste e dados sintéticos (sem NIF reais): criar organização, emitir factura, proforma e nota de crédito; repetir a emissão com a mesma `idempotencyKey` 2× → 1 documento; verificar a assinatura do *webhook*; resultados em relatório, sem código reutilizável em `main`.
- [ ] Modelo de custo para 10, 50 e 200 PMEs (licença por contribuinte, volume, *freemium*), com fórmula e preços datados; custo por PME comparado com o preço hipotético de Factura AI **sem inventar o preço**; a facturação da assinatura da própria KAMBÁ (obrigatória, E2 §7) registada como caso de uso do mesmo parceiro.
- [ ] Análise de dados: onde residem os dados fiscais, se o parceiro é subprocessador e se há transferência internacional (ADR-008, `apd_ref`); orçamento ≠ factura (E5 Q8) listado como pergunta ao parecer.
- [ ] Recomendação com regra pré-registada (*proposta*): avançar para Clusters só se (a) certificado validado na lista da AGT ou confirmado por escrito, (b) API multi-tenant com idempotência e *webhooks*, (c) custo por PME ≤ 10% do preço hipotético, (d) caminho APD definido; caso contrário, «adiar» ou «parceiro alternativo»; certificação própria registada como opção com custo e prazo NÃO VERIFICADOS.
- [ ] Relatório `../docs/tecnica/evidencia/validacao/KAM-126_Factura_AI.md` com estado CONFIRMADO/INDÍCIO/NÃO VERIFICADO por afirmação, decisão com dono e data, e insumo para D7.

### Detalhes Técnicos

- **Componentes:** fora do runtime; futuro `InvoiceProvider` (Fase 2, `INDICE` §6). Código do spike (se existir) só em `spikes/`, descartável, com chaves de teste no cofre.
- O Claude Code prepara: questionário à AGT e aos fornecedores, matriz, *script* de *sandbox* e modelo de custo; contactos, envio e leitura de contratos são tarefas humanas.

### Testes Requeridos

- *Script* de *sandbox* corre contra um *mock* antes de tocar no fornecedor; verificação de que o relatório não contém chaves nem NIF reais.
- Revisão do modelo de custo (fórmula e unidades) por uma segunda pessoa.

### Definition of Done

- [ ] Critérios de Aceitação satisfeitos e demonstráveis; relatório arquivado e linkado a D7.
- [ ] Nenhum NÃO VERIFICADO (certificados, calendário, custos) tratado como facto; cada um com estado final.
- [ ] Sem dados pessoais reais enviados a fornecedores; chaves apagadas no fim do spike.
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
