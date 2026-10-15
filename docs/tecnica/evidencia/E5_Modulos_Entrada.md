# E5 - Módulos de entrada (Catálogo AI, Foto AI, Social AI, Orçamento expresso): verificação para a decisão «Piloto ou Diferido»

Data da pesquisa: 9 de Outubro de 2026. Todas as páginas foram lidas nesse dia (coluna Data = data «Updated» da própria página quando existe; «acedido 2026-10-09» quando a página não tem data).
Método: leitura directa do HTML de documentação, páginas de preços e termos dos fornecedores (a pesquisa web serviu apenas para descobrir URLs e como INDÍCIO). As tarifas WhatsApp foram lidas **no ficheiro oficial de tarifas** (folha «List rates», cabeçalho «effective October 1, 2026») descarregado de novo da página de preços da Meta.

Legenda:
- **CONFIRMADO** = lido em documentação, preços ou termos oficiais do próprio fornecedor/diploma.
- **INDÍCIO** = fonte secundária (imprensa, blogs, agregadores), inferência minha a partir de factos confirmados, ou resumo automático sem leitura do texto integral.
- **NÃO VERIFICADO** = sem fonte; não presumir.

Contexto lido: `../00_Arquitectura_Solucao.md` (§1, ADR-005/007/008/011/018/019, §13.3 D1-D12), `E1_Meta_WhatsApp.md`, `E3_Regulatorio_Dados.md`, `../../exploracao/01-modelo-negocios-angola-ai-first.md` (negócios Nº 3, 4, 5, 8). Câmbio de referência do projecto: ~913 AOA/USD (arquitectura §11). Esta pesquisa **não é parecer jurídico**.

---

## 0. Conclusões que mais mudam o desenho

| # | Conclusão | Estado | Impacto |
|---|---|---|---|
| 1 | **Publicação automática em Instagram/Facebook não cabe no arranque do Piloto; fica Diferida (entrega para publicação manual).** Exige Advanced Access (App Review) **e** Business Verification; a Meta não publica prazo de aprovação (INDÍCIO: dias a cerca de 1 mês); o Facebook (6,18 M utilizadores) pesa 5x o Instagram (1,17 M) em Angola. Mas o desenho deve deixar o gancho pronto (campo `is_ai_generated`, tokens de 60 dias, publicador atrás de interface) e pedir as permissões **no mesmo ciclo de Business Verification/App Review já necessário para o Tech Provider (D5)**. | CONFIRMADO (requisitos); INDÍCIO (prazo) | Social AI do Piloto = calendário + legenda + arte aprovados pelo dono no WhatsApp, entregues como ficheiro/texto para ele publicar. |
| 2 | **Fornecedor de imagem: nenhum é «o melhor» comprovado.** Qualidade para fundo limpo/relighting em fotos angolanas **não tem fonte independente** (NÃO VERIFICADO): fazer bake-off. Em preço/termos, a short-list é **Bria** (cutout 0,018 USD, lifestyle 0,03 USD; inputs «não retidos além do necessário»; dados de treino licenciados; indemnização) e **Photoroom** (Basic 0,02 USD/Plus 0,10 USD; a política diz que a API não treina, mas a página de segurança diz o contrário para planos self-serve: **contradição por resolver por escrito**). **Gemini (Nano Banana 2.1) pago** é o mais barato para artes (0,0336 USD/imagem 1K), não treina em serviços pagos, mas fica em infra com tratamento «em qualquer país». **BFL (FLUX) excluído**: os termos de API não-UE dão-lhe licença perpétua para treinar com inputs e outputs. **remove.bg excluído**: muda para Leonardo.Ai (Canva) a 1-12-2026. | CONFIRMADO (preços/termos); NÃO VERIFICADO (qualidade, latência, aceitação de clientes em Angola para Photoroom/Bria) | Custo-alvo por imagem de produto: 0,02-0,10 USD; ver §1. |
| 3 | **Mensagens proactivas ao dono são baratas; o problema é o remetente, não o preço.** Rest of Africa (inclui Angola): marketing **0,0225 USD**, utility **0,004 USD**, service **0,004 USD** (1.000/mês/número grátis). **Confirmo os valores da E1 sem correcção.** 4 propostas semanais classificadas como marketing = 0,09 USD/PME/mês (~82 Kz). Uma proposta de conteúdo é «recomendação» → Meta classifica-a como marketing (CONFIRMADO nas directrizes); só avisos específicos do serviço contratado têm hipótese de utility. | CONFIRMADO | Mas o remetente «KAMBÁ → dono» exige um número da plataforma, que o ADR-011/D10 deixa vedado até resposta da Meta. Alternativa sem custo e sem número agregador: o **dono inicia** (ex. escreve «IDEIAS»), janela de 24 h, service messages. |
| 4 | **Fotos de produto são dados pessoais quando mostram pessoas.** A Lei 22/11 define dados pessoais «incluindo imagem e som» (CONFIRMADO no texto). Enviar a fornecedor no estrangeiro é, por defeito, transferência (Art. 33-34, E3); o precedente Crescer Tech (USD 505 mil) aplica-se. Mitigação de desenho: filtro local de rostos/matrículas **antes** de sair de Angola, remoção de EXIF/GPS, `allowed_destinations` por fornecedor. | CONFIRMADO (definição); INDÍCIO (qualificação como transferência) | Novo componente no MED: «gate de minimização de imagem». |
| 5 | **Direitos sobre artes geradas: risco de não haver protecção.** A Lei 15/14 define «autor» como pessoa física; uma imagem sem intervenção criativa humana provavelmente não é protegida (INDÍCIO, inferência). Não prometer exclusividade à PME. Gemini declara que não reclama propriedade, mas pode gerar conteúdo igual ou semelhante para terceiros. | INDÍCIO / CONFIRMADO (texto Google) | Termos de serviço: sem garantia de exclusividade nem de ausência de semelhança. |

**Recomendação por módulo (para a decisão do fundador):**

| Módulo | Piloto? | Forma mínima no Piloto | Condição |
|---|---|---|---|
| Catálogo AI (foto → ficha) | **Sim** (já em Roadmap Fase 1) | Visão (LLM) para ficha + cutout/fundo limpo; dono confirma antes de publicar | Gate de minimização de imagem + DPA/subprocessador listado |
| Foto AI | **Sim, em versão reduzida** | Cutout, fundo de cor/estúdio simples e sombra (Basic/Cutout). Variações «lifestyle» generativas como opção etiquetada e com validação do dono | Bake-off de 30 fotos reais; resposta escrita do fornecedor sobre treino/retenção |
| Social AI | **Sim, sem publicação automática** | Calendário semanal, legenda PT, arte com **texto composto por código** (não pelo modelo), aprovação no WhatsApp, entrega para publicação manual | Publicação API = Diferida (ver §3) |
| Orçamento expresso | **Sim, como formato do fluxo Vendedor** | Orçamento sobre o catálogo e preços do próprio dono (Registo) com validador de citação; rotulado «não é documento fiscal» | Não incluir a «base de preços viva» extraída de PDFs/sites de terceiros no Piloto (§5, §7) |

---

## 1. APIs de edição/melhoria de imagem de produto

Cotações em USD, lidas nas páginas dos fornecedores a 2026-10-09.

### 1.1 Comparação (4 opções + 2 excluídas)

| Critério | Photoroom API | Bria (API) | Google Gemini «Nano Banana 2.1» (API paga) | OpenAI gpt-image-2.5 (API) |
|---|---|---|---|---|
| Preço por imagem | Basic (Remove Background) **0,02**; Plus (Image Editing: AI Backgrounds, Shadows, Staging) **0,10**. 1 chamada Image Editing = 5 chamadas Remove Background. Sandbox grátis com marca de água (1.000/mês) | Cutout **0,018**; Product Shadow 0,018; Lifestyle por texto ou por imagem **0,03**; Background Generation 0,03; Eraser 0,02; Fibo Edit 0,03. 100 gerações grátis | **0,0336** (1K), 0,0504 (2K), 0,113 (4K); batch metade. Entrada: 1,50 USD/M tokens | Por tokens: saída de imagem **30 USD/M tokens**, entrada de imagem 8 USD/M. Exemplo oficial de qualidade baixa: 196 tokens = 0,00588 USD. Médio/alto: não encontrei tabela por imagem no modelo actual (NÃO VERIFICADO); estimativa minha com os tokens do modelo anterior (1.056 médio, 4.160 alto, 1024x1024): ~0,03 e ~0,12 USD |
| Qualidade fundo limpo / relighting | NÃO VERIFICADO (sem benchmark independente); produto especializado em e-commerce (Wolt, Depop, Decathlon como casos do próprio site: INDÍCIO) | NÃO VERIFICADO; modelos treinados «exclusivamente com dados licenciados» (afirmação do fornecedor) | NÃO VERIFICADO para fundo limpo; é modelo generativo (risco de alterar o produto) | NÃO VERIFICADO; idem. Doc admite que a colocação precisa de texto/elementos pode falhar |
| Latência típica | NÃO VERIFICADO | «FIBO Lite afinado para baixa latência»; plano gratuito com latência em fila; 10 pedidos/min grátis, 60/min pay-as-you-go | NÃO VERIFICADO | Prompts complexos **até 2 minutos** (doc oficial) |
| Limites | 25 megapíxeis recomendados; largura máx. 5.000 px (Plus) / 6.000 px (Basic) | 10 req/min (grátis); 60 req/min (pay-as-you-go) | NÃO VERIFICADO (quotas por projecto) | NÃO VERIFICADO (por tier) |
| Uso comercial / direitos | NÃO VERIFICADO nos termos lidos (termos de utilização não obtidos: 404) | Pay-as-you-go: indemnização padrão limitada; **indemnização ilimitada, relatório de «copyrightability», DPA próprio e SSO só em Enterprise**. «Direitos de uso comercial dos modelos open-source» só em Enterprise | Termos Gemini: Google «não reclama propriedade» do conteúdo gerado e pode gerar conteúdo igual ou semelhante para outros | NÃO VERIFICADO (página de termos devolveu 403) |
| **Retenção** | «Imagens da API descartadas após cada chamada» (página de segurança); logs operacionais 15 dias; logs de acesso 1 ano | **Inputs «não retidos além do necessário para processar»**; outputs alojados 3 dias (imagens), Product Shot Editing 1 hora | Serviços pagos: Google guarda prompts e respostas «por tempo limitado», para detecção de violações; pode ser armazenado «transitoriamente ou em cache em qualquer país» | Por omissão, **logs de abuso até 30 dias**; Zero Data Retention ou Modified Abuse Monitoring só com aprovação prévia. Geração de imagem é ZDR-compatível (gpt-image-2.5, 2, 1.5...). Excepção CSAM para inputs de imagem |
| **Treino com as imagens** | Política de privacidade (actualizada Março 2026): «a melhoria dos modelos não se aplica às imagens processadas pela API». **Mas** a página de segurança diz: contratos Enterprise não treinam por omissão; «planos API self-serve treinam, com opt-out nas definições» (e noutra linha: «nunca usadas para treino sem o teu consentimento»). **Contradição interna** | Doc de retenção **não aborda** treino com inputs (NÃO VERIFICADO) | **Serviços pagos: não usa prompts, ficheiros e respostas para melhorar produtos** (tabela de preços: «Used to improve our products: No» no pago, «Yes» no gratuito) | Desde 1-3-2023, dados da API **não** são usados para treino salvo opt-in (doc oficial) |
| Região de processamento | **EUA**; residência só UE «não disponível hoje» (página de segurança) | NÃO VERIFICADO («cloud-only»; implantação on-prem/BYOC só Enterprise) | Qualquer país onde a Google tenha instalações (termos) | `us.api.openai.com` por omissão; residência (UE, AU, CA, JP, IN) sujeita a elegibilidade e a +10% (doc) |
| DPA | **Sim**, «disponível para revisão de aquisição e jurídica»; SOC 2 Tipo 2 (âmbito API); sub-processadores GCP, AWS, Cloudflare, Datadog, Vercel | DPA próprio **só Enterprise** | DPA «Products where Google is a Data Processor» aplica-se a serviços pagos | NÃO VERIFICADO nesta leitura |
| Aceita utilizadores em Angola | NÃO VERIFICADO (sem lista de países; sem restrição vista) | NÃO VERIFICADO | **Sim**: Angola consta da lista de regiões disponíveis | **Sim**: Angola consta da lista de países suportados |

### 1.2 Fornecedores excluídos

| Fornecedor | Motivo | Estado |
|---|---|---|
| Black Forest Labs (FLUX) | Termos de API (revistos 4-8-2026, aplicáveis fora da UE): o Programador concede à empresa licença perpétua e irrevogável sobre Input e Output «para melhorar produtos» e a empresa «pode usar Inputs e Outputs para treinar e melhorar os seus modelos». Incompatível com fotos de clientes das PMEs sem contrato Enterprise. Preços: FLUX 3 Image 0,041 USD (768x768); FLUX.2 [pro] «a partir de 0,03» | CONFIRMADO |
| remove.bg | A página da API anuncia que «a partir de 1 de Dezembro de 2026, a remoção de fundo passa para Leonardo.Ai (Canva)». Mudança de fornecedor no meio do Piloto | CONFIRMADO |
| Claid.ai, Cloudinary | Páginas obtidas mas **não analisadas em profundidade** (tempo): NÃO VERIFICADO quanto a preços/retenção/treino | NÃO VERIFICADO |

### 1.3 Tabela de afirmações (fontes)

| Afirmação | Estado | Fonte | Data | Implicação para o desenho |
|---|---|---|---|---|
| Photoroom: Basic 0,02 USD/imagem, Plus 0,10 USD/imagem; Enterprise com mínimo de 200 mil imagens/ano | CONFIRMADO | https://www.photoroom.com/api/pricing | acedido 2026-10-09 | O preço do slider por volume não ficou legível: cotar por escrito. Para cutout simples, o plano Basic chega |
| Photoroom: imagens da API descartadas após cada trabalho; sub-processadores GCP/AWS; infra nos EUA; sem residência UE | CONFIRMADO | https://www.photoroom.com/platform/security | acedido 2026-10-09 | Transferência para os EUA: entra no inventário de subprocessadores (ADR-008) |
| Photoroom: contradição sobre treino em planos API self-serve (política vs página de segurança) | CONFIRMADO (a contradição existe) | https://www.photoroom.com/legal/privacy-policy (Updated March 2026) e https://www.photoroom.com/platform/security | 2026-03 / acedido 2026-10-09 | Exigir cláusula contratual «no training» por escrito antes de usar fotos reais; sem isso, usar apenas dados sintéticos/de teste |
| Bria: preços da lista (cutout 0,018; lifestyle 0,03; etc.) e planos (grátis 100 gerações; pay-as-you-go 60 req/min; Enterprise com DPA) | CONFIRMADO | https://bria.ai/pricing | acedido 2026-10-09 | Opção mais barata para fundo limpo + lifestyle; DPA só no Enterprise: negociar |
| Bria: inputs não retidos além do necessário; outputs 3 dias (Product Shot Editing 1 hora); treino com inputs não abordado | CONFIRMADO (retenção); NÃO VERIFICADO (treino) | https://docs.bria.ai/getting-started/asset-retention | acedido 2026-10-09 | Descarregar o resultado de imediato para o nosso storage; pedir declaração de não-treino |
| Bria: modelos treinados exclusivamente com dados licenciados; indemnização limitada no pay-as-you-go | CONFIRMADO (como afirmação do fornecedor); eficácia NÃO VERIFICADO | https://bria.ai/pricing; https://docs.bria.ai/ | acedido 2026-10-09 | Reduz risco de direitos de terceiros nas variações generativas |
| Bria: termos de utilização dão ao fornecedor licença sobre os dados do cliente «para prestar os Serviços», sem aquisição de direitos | CONFIRMADO (termos do sítio; os Termos específicos da API podem diferir) | https://bria.ai/terms-of-use | acedido 2026-10-09 | Pedir os termos de API |
| Gemini (Nano Banana 2.1): 0,0336 USD (1K), 0,0504 (2K), 0,113 (4K); batch metade; serviço pago não usado para melhorar produtos; gratuito sim | CONFIRMADO | https://ai.google.dev/gemini-api/docs/pricing | Last updated 2026-10-09 UTC | Só usar **tier pago** (o gratuito treina e tem revisão humana). Para artes de redes sociais é o mais barato |
| Gemini: serviços não pagos: revisores humanos podem ler; não enviar dados pessoais/sensíveis | CONFIRMADO | https://ai.google.dev/gemini-api/terms | Last updated 2026-04-28 | Proibir o tier gratuito em produção |
| Gemini: serviços pagos: DPA de processador; logs por tempo limitado; dados podem ser guardados «em qualquer país» | CONFIRMADO | https://ai.google.dev/gemini-api/terms | 2026-04-28 | Mapa de transferências sem destino fixo: pior caso para a notificação à APD |
| Gemini: Angola na lista de regiões disponíveis | CONFIRMADO | https://ai.google.dev/gemini-api/docs/available-regions | acedido 2026-10-09 | Sem bloqueio geográfico |
| OpenAI: Angola na lista de países suportados | CONFIRMADO | https://platform.openai.com/docs/supported-countries | acedido 2026-10-09 | idem |
| OpenAI: sem treino com dados da API; logs de abuso até 30 dias; ZDR/MAM sujeitos a aprovação; imagens ZDR-compatíveis; residência regional com +10% | CONFIRMADO | https://platform.openai.com/docs/guides/your-data | acedido 2026-10-09 | Pedir ZDR/MAM para o projecto de imagens |
| OpenAI: preço de saída de imagem 30 USD/M tokens; latência até 2 min; texto «ainda pode falhar na colocação e clareza» | CONFIRMADO | https://platform.openai.com/docs/guides/image-generation e https://platform.openai.com/docs/pricing | acedido 2026-10-09 | Latência incompatível com resposta síncrona no WhatsApp: fila assíncrona e «estou a preparar» |
| BFL: licença perpétua e treino com Inputs e Outputs | CONFIRMADO | https://bfl.ai/legal/flux-api-service-terms | Last Revised 2026-08-04 | Excluir |
| remove.bg → Leonardo.Ai em 1-12-2026 | CONFIRMADO | https://www.remove.bg/api | acedido 2026-10-09 | Excluir |

**Custo por imagem para o modelo de negócio (estimativa minha, com 913 AOA/USD):**
- Catálogo AI, pacote 10 produtos a 15.000 Kz (~16,4 USD, negócio Nº 4): 10 cutouts a 0,02 + 20 variações a 0,03 + chamadas de visão ≈ 1 USD de imagem, ordem de 6% da receita.
- Foto AI Premium 25 fotos a até 80.000 Kz (~87,6 USD, negócio Nº 5): 25 finais × 4 tentativas × 0,10 = 10 USD no pior caso (Photoroom Plus), ~11%; com Bria a 0,03, ~3 USD.
- Os valores acima não incluem o custo do LLM de visão (ADR-005).

---

## 2. Geração de artes/posts

| Afirmação | Estado | Fonte | Data | Implicação para o desenho |
|---|---|---|---|---|
| Gemini recomenda, para melhor desempenho, os idiomas EN, ar-EG, de-DE, es-MX, fr-FR, hi-IN, id-ID, it-IT, ja-JP, ko-KR, pt-BR, ru-RU, ua-UA, vi-VN, zh-CN: **pt-BR consta; pt-PT/pt-AO não** | CONFIRMADO | https://ai.google.dev/gemini-api/docs/image-generation | acedido 2026-10-09 | Acentuação e vocabulário angolano (kwanza, «Kz») sem garantia |
| Google afirma «texto legível e estilizado» no modelo | CONFIRMADO (como afirmação do fornecedor); eficácia em PT NÃO VERIFICADO | idem | idem | Não confiar |
| OpenAI admite que a colocação precisa de texto e elementos pode falhar | CONFIRMADO | https://platform.openai.com/docs/guides/image-generation | acedido 2026-10-09 | Idem |
| Benchmarks independentes de texto em português nas imagens geradas: não encontrei (os benchmarks achados cobrem EN/FR/ZH/IT) | NÃO VERIFICADO | pesquisa web (STRICT, EasyText, Glyph-ByT5, arXiv) | 2026-10-09 | Decisão de desenho abaixo |
| Custos por imagem de arte: Gemini 0,0336 USD (1K); OpenAI baixa qualidade ~0,006 USD (exemplo oficial); BFL FLUX.2 [pro] «a partir de 0,03» | CONFIRMADO | ver §1.3 | idem | Custo de arte ≈ 1-5 cêntimos; 20 posts × 3 tentativas ≈ 2 USD/mês/PME (~1.900 Kz), cerca de 2% de um pacote de 80.000 Kz (negócio Nº 8) |
| Direitos de uso comercial: Gemini «não reclama propriedade» mas pode gerar o mesmo ou semelhante para outros | CONFIRMADO | https://ai.google.dev/gemini-api/terms | 2026-04-28 | Cláusula nos termos da KAMBÁ: sem exclusividade |
| Direitos de uso comercial OpenAI e BFL sobre outputs | OpenAI NÃO VERIFICADO (termos devolveram 403); BFL: licença do Programador à empresa (ver §1) | — | — | Exigir leitura dos termos antes da escolha |
| Meta (oficial): rótulo «AI info» aplicado quando detecta indicadores padrão da indústria **ou** quando a pessoa declara que carregou conteúdo gerado por IA; conteúdo só editado por IA tem o rótulo no menu da publicação | CONFIRMADO | https://about.fb.com/news/2024/04/metas-approach-to-labeling-ai-generated-content-and-manipulated-media/ | Abril 2024, actualizado 1-7-2024 | A página é de 2024; a política de 2026 não foi relida aqui. Tratar como mínimo, não como estado actual |
| **API de publicação do Instagram tem o parâmetro `is_ai_generated=true`** (auto-declaração; só no contentor de carrossel, não nos filhos; disponível com Facebook Login e Instagram Login) | CONFIRMADO | https://developers.facebook.com/documentation/instagram-platform/content-publishing | Updated 2026-06-30 | Quando houver publicação automática, enviar sempre `is_ai_generated=true` para conteúdo gerado por IA. No Piloto (publicação manual), instruir o dono a activar o rótulo e incluir a nota na entrega |
| Gemini marca todas as imagens geradas com **SynthID** | CONFIRMADO | https://ai.google.dev/gemini-api/docs/image-generation | acedido 2026-10-09 | A Meta pode rotular automaticamente; não remover marcas nem metadados |
| Se a Meta obriga a rotular imagens de produto «editadas» (cutout, fundo) em 2026: texto de política de 2026 não lido | NÃO VERIFICADO | — | — | Pergunta à Meta (§9) |
| TikTok: exige rotular AIGC realista e usa C2PA para rotular automaticamente conteúdo carregado | INDÍCIO (imprensa 2024; página oficial de suporte não legível) | https://www.nbcnews.com/tech/tech-news/tiktok-will-automatically-label-ai-generated-content-rcna151446 | 2024 | TikTok fora do Piloto (nem para publicação manual há automatização) |

**Decisão de desenho derivada:** o modelo gera apenas o **fundo/cena**; o **texto da arte (nome, preço em Kz, contactos) é composto por código** com fontes reais e dados do Registo (ADR-007). Evita erros de acentuação e erros de preço, e liga-se ao validador de citação. Para o Piloto, 3 a 5 modelos de arte (templates) por vertical.

---

## 3. Publicação em redes sociais por API

| Afirmação | Estado | Fonte | Data | Implicação para o desenho |
|---|---|---|---|---|
| Publicação no Instagram: imagens, vídeos, reels e carrosséis em **contas profissionais** (Business ou Creator); contentor em `/<IG_ID>/media` e depois `/media_publish`; o media tem de estar em servidor público no momento da tentativa | CONFIRMADO | https://developers.facebook.com/documentation/instagram-platform/content-publishing | Updated 2026-06-30 | Servir a arte por URL assinada temporária e pública (o ADR «URL interna assinada» do MED tem de ter excepção pública, de curta duração) |
| **Só JPEG** é suportado; sem tags de compras; sem filtros | CONFIRMADO | idem | idem | Converter PNG/WebP para JPEG no pipeline |
| **Limite: 100 publicações via API em 24 h móveis por conta** (carrossel conta como 1); consulta em `/content_publishing_limit` | CONFIRMADO | idem | idem | Não é limitante para PMEs (8-20 posts/mês) |
| Duas vias de login: **Business Login for Instagram** (token de utilizador Instagram; não exige Página Facebook) e **Facebook Login for Business** (token de Página). Permissões: `instagram_business_basic` + `instagram_business_content_publish`, ou `instagram_basic` + `instagram_content_publish` + `pages_read_engagement` | CONFIRMADO | idem | idem | Preferir Instagram Login para reduzir atrito (muitas PMEs podem não ter Página); decisão a validar com PMEs reais |
| **Advanced Access exige App Review e Business Verification** quando a app serve contas que não possui nem gere (o caso de uma plataforma multi-cliente); Standard Access só serve contas com papel na app | CONFIRMADO | https://developers.facebook.com/documentation/instagram-platform/overview | Updated 2026-09-28 | Sim, a plataforma **pode** publicar em nome das PMEs, mas só depois de Advanced Access |
| Tokens de longa duração valem **60 dias** e podem ser renovados antes de expirar | CONFIRMADO | idem | idem | Job de renovação e alerta de falha por tenant; se o dono revogar ou mudar a palavra-passe, o token cai: fluxo de reconexão |
| Páginas Facebook: `pages_manage_posts` + `pages_read_engagement` (+ `publish_video`); publicar em `/{page_id}/feed` ou `/photos`; agendamento entre 10 min e 30 dias; o utilizador tem de poder executar tarefas na Página | CONFIRMADO | https://developers.facebook.com/documentation/pages-api/posts | Updated 2026-04-17 | Para Páginas, a publicação é directa e permite agendar; reduz a necessidade de jobs |
| Página com «Page Publishing Authorization» (PPA) pendente: não se publica até concluir | CONFIRMADO | content-publishing | 2026-06-30 | Estado de erro tratado com mensagem ao dono |
| **Prazo de aprovação**: a documentação lida **não publica prazo** de App Review/Business Verification para Instagram/Pages | NÃO VERIFICADO | — | — | Não prometer data |
| Prazos de terceiros: Business Verification «dias a semanas»; App Review do Instagram «dias a cerca de 1 mês»; sequenciais | INDÍCIO (resultado de pesquisa, sem fonte oficial; fórum Meta com caso de Business Verification «10 dias em revisão») | pesquisa web; https://communityforums.atmeta.com/discussions/Questions_Discussions/business-verification-in-review-10-days-%E2%80%94-blocking-app-review-submission/1372323 | 2026-10-09 | Planear 1-2 meses, em paralelo com D5 |
| Para o WhatsApp, a Meta indica App Review «cerca de 24 horas» e Business Verification **sem prazo** | CONFIRMADO (E1) | `E1_Meta_WhatsApp.md` | 2026-10-08 | A Business Verification da entidade da KAMBÁ é a mesma que serve Instagram/Pages (portfólio de negócio): é pré-requisito comum (inferência minha; confirmar) |
| Aceitação de documentos de empresa angolana na Business Verification | NÃO VERIFICADO | E1 | — | Risco já aberto (E1 §3) |
| Quota de Instagram em Angola: ~1,17 M utilizadores (2,8%); Facebook ~6,18 M (15%); Messenger ~5,74 M (13,9%) em Setembro de 2026. Dados da NapoleonCat (estimativas de audiência publicitária) | INDÍCIO | https://napoleoncat.com/stats/social-media-users-in-angola/2025 | Setembro 2026 | O canal dominante é o **Facebook**, não o Instagram. Priorizar Páginas Facebook na ordem de integração; verificar quantas PMEs têm Página |
| Percentagem de PMEs angolanas com Página Facebook / conta profissional Instagram | NÃO VERIFICADO | — | — | Perguntar no inquérito do Piloto (H-novo) |
| Publicar Status do WhatsApp por API | NÃO VERIFICADO (não encontrei endpoint na documentação lida) | E1 | — | Não planear |

**Conclusão (pergunta 3): a publicação automática NÃO é viável no arranque do Piloto; fica Diferida (entrega para publicação manual).** Razões: (a) Advanced Access com App Review e Business Verification, sem prazo oficial e com documentos angolanos por validar; (b) a fila de excepções e o isolamento já ocupam a equipa (ADR-019); (c) o ganho marginal é baixo no Piloto porque o dono aprova cada peça de qualquer maneira. **Gancho obrigatório já no desenho:** interface `SocialPublisher` (implementações `ManualDelivery` P, `FacebookPagePublisher` e `InstagramPublisher` D), token vault por tenant com renovação aos 60 dias, `is_ai_generated` no modelo de dados da peça, e pedido de permissões `pages_manage_posts` e `instagram_business_content_publish` na mesma submissão do Tech Provider (D5). **Gatilho para passar a Clusters:** App Review aprovado e ≥ 3 PMEs piloto com Página/conta profissional ligada.

---

## 4. WhatsApp: mensagens iniciadas pela plataforma ao dono

### 4.1 Tarifas em vigor (confirmação da E1)

| Afirmação | Estado | Fonte | Data | Implicação para o desenho |
|---|---|---|---|---|
| **Rest of Africa (inclui Angola, +244), USD por mensagem entregue: Marketing 0,0225; Utility 0,004; Authentication 0,004; Service 0,004; Authentication-international n/a; Meta Business Agent 2,00 USD por milhão de tokens.** Valores iguais aos da E1: **confirmados, sem correcção** | CONFIRMADO | Ficheiro «USD list rates» (folha «List rates», cabeçalho «Cost per message in USD on the WhatsApp Business Platform, effective October 1, 2026») descarregado a partir de https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing | Updated 2026-09-30; efectivo 2026-10-01 | Mantém o modelo de custos da arquitectura §9 |
| Angola está na região «Rest of Africa – 40 markets» (inclui Algeria (DZ) – 213 e Angola (AO) – 244) | CONFIRMADO | idem (secção de códigos de país) | 2026-09-30 | Idem |
| 1.000 service messages grátis por **business phone number** por mês; cobra-se a partir da 1.001.ª | CONFIRMADO | idem | 2026-09-30 | Idem |
| Utility template fora da janela de 24 h é cobrado (e dentro da janela deixou de ser grátis em 1-10-2026) | CONFIRMADO | idem; E1 | 2026-09-30 | Fora da janela só há templates |
| A primeira leitura automática (WebFetch) da página devolveu texto desactualizado («service gratuito desde 1-11-2024») que **contradiz** o HTML integral. Prevalece o HTML integral e o ficheiro de tarifas | CONFIRMADO (verificado pelo HTML) | WebFetch vs HTML da página | 2026-10-09 | Nota de método: a E1 usou o HTML; não usar resumos automáticos para preços |
| Imprensa sul-africana e queniana dá valores diferentes para outros mercados (Nigéria utility ~0,0101 e marketing ~0,062; África do Sul utility 0,0076) face ao ficheiro oficial (Nigéria 0,0067 e 0,0516; África do Sul 0,0095). O Quénia a 0,0040 coincide com «Rest of Africa» | INDÍCIO (imprensa; diferença não explicada, possivelmente impostos ou data) | https://briefly.co.za/people/250520-meta-charge-whatsapp-business-api-users-message-1-october-2026/ ; https://nation.africa/kenya/business/kenyan-businesses-face-higher-online-costs-as-whatsapp-stops-free-messages-5573738 (403 no acesso directo) | 2026-10 | Não afecta Angola; confirmar impostos (IVA/ISP) na factura Meta |

### 4.2 Classificação e opt-in

| Afirmação | Estado | Fonte | Data | Implicação para o desenho |
|---|---|---|---|---|
| **Marketing** inclui promover, recomendar, construir relação e templates de conteúdo misto ou pouco claro. **Utility** exige ser não-promocional **e** específico do pedido/conta/serviço do destinatário (ou essencial/crítico). Mensagens utility «não devem promover, recomendar, vender mais ou renovar» | CONFIRMADO | https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/template-categorization | Updated 2026-09-15 | **Proposta semanal de ideias/conteúdo = marketing** (é «recomendação»). **Aviso «a tua arte está pronta/aprova até quinta»** relativo a um pedido do dono = candidato a utility (exemplos: «para concluir a configuração, carrega uma foto»), sem garantia: a Meta pode recategorizar |
| A Meta pode recategorizar templates automaticamente | CONFIRMADO | idem (secção de actualizações de categoria) | 2026-09-15 | Orçar tudo como marketing (0,0225); utility é desconto, não base |
| Opt-in obrigatório antes de contactar; pode ser geral e não específico do WhatsApp se cumprir a lei local; tem de indicar claramente o nome do negócio; métodos admitidos incluem website, SMS, IVR, presencial/papel; recomenda-se opt-in por categoria e opt-out claro | CONFIRMADO | https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in | Updated 2026-06-16 | Recolher no onboarding-web (ADR-019) um opt-in **separado** para «ideias de conteúdo da KAMBÁ» (marketing) e outro para avisos de serviço; guardar prova (E3 §requisito 3) |
| Limites de template de marketing por utilizador: a Meta pode limitar quantos templates de marketing um utilizador recebe, com base na taxa de leitura recente | CONFIRMADO (mecanismo); aplicação a Angola NÃO VERIFICADO | https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/marketing-templates/per-user-limits | Updated 2026-06-17 | 4 mensagens/mês a um destinatário que as lê: baixo risco; não enviar a quem nunca responde |
| Mensagem iniciada pelo dono: ao escrever, abre-se janela de 24 h; respostas não-template são service (grátis dentro das 1.000/mês por número); a janela renova-se com cada mensagem do dono | CONFIRMADO | `E1_Meta_WhatsApp.md` §1; pricing (acedido 2026-10-09) | 2026-09-30 | Fluxo «dono escreve IDEIAS / APROVAR / NOVA ARTE» tem custo zero no Piloto |
| **Custo das propostas proactivas**: 4/mês como marketing = 0,09 USD (~82 Kz) por PME; como utility, 0,016 USD (~15 Kz). Um template de marketing respondido pelo dono abre janela de 24 h onde o resto da conversa (ideias, artes, aprovações) é service | CONFIRMADO (tarifas) + cálculo meu | ficheiro de tarifas | 2026-10-01 | Irrelevante face a pacotes de 80.000-250.000 Kz/mês; o que importa é a entregabilidade |
| **Direct Send** (utility sem template pré-criado) exige portfólio com limite de mensagens 100.000 ou ilimitado | CONFIRMADO | https://developers.facebook.com/documentation/business-messaging/whatsapp/direct-send | Updated 2026-10-08 | Não disponível no Piloto (portfólio novo = 250). Ignorar |
| Portfólio novo: 250 contactos únicos/dia fora da janela (E1) | CONFIRMADO | `E1_Meta_WhatsApp.md` §5 | 2026-10-08 | Para dezenas de PMEs-dono por dia, chega |
| **Remetente de mensagens «KAMBÁ → dono»**: precisa de um número WhatsApp **da KAMBÁ** como negócio. O ADR-011/D10 deixa o tenant `platform` vedado até resposta da Meta (preocupação: número agregador a falar com consumidores de várias lojas). Mensagens da KAMBÁ aos seus próprios clientes (as PMEs) são um caso diferente, mas a Meta **não confirmou** | NÃO VERIFICADO | `../00_Arquitectura_Solucao.md` §5, §13.3 D10; E1 §4 | — | Duas opções: (1) número KAMBÁ de «relação com o cliente-PME», com pergunta explícita à Meta; (2) **dono inicia** a conversa com o número da própria PME (a partir do telemóvel pessoal), sem número agregador. O Piloto deve funcionar só com (2) e tratar (1) como melhoria |

---

## 5. Mercado e oferta (hipótese, INDÍCIO)

| Afirmação | Estado | Fonte | Data | Implicação para o desenho |
|---|---|---|---|---|
| Uma agência angolana (Brandix Angola) publica planos de gestão de redes sociais: **PMEs 180.989 Kz/mês** (2 posts/semana, tráfego pago 10 dias, relatório mensal, 3 reels), PLUS 220.798 Kz (3 posts/semana, 5 reels), EXCELENTE 315.700 Kz (4 posts/semana, 7 reels); design: flyer 15.999 Kz, logótipo 28.999 Kz, identidade visual 400.000 Kz; fotografia e catálogo **não listados**. (Um snippet de pesquisa mostrava preços inferiores, 98.900/140.000/248.999 Kz: diferença não explicada; vale o valor lido na página) | INDÍCIO (um preço de tabela de um concorrente; um só) | https://brandixao.com/precos/ | acedido 2026-10-09 | O pacote hipotético do negócio Nº 8 (80.000-250.000 Kz) fica **abaixo** do plano de PME desta agência, que inclui reels e tráfego pago que o Piloto não oferece. Faixa de teste plausível: 60.000-120.000 Kz para o pacote de peças + calendário, a validar |
| Preço de fotografia de produto em Angola (Kz) | NÃO VERIFICADO (não encontrei lista local; a Zaask Portugal indica 3-12 € por foto de e-commerce, o que não é Angola) | https://www.zaask.pt/quanto-custa/fotografia-de-produto | acedido 2026-10-09 | A faixa do negócio Nº 5 (15.000-80.000 Kz por pacote) fica sem âncora local: fazer 5 cotações a estúdios de Luanda |
| Disposição a pagar de PMEs angolanas por Catálogo/Foto/Social | NÃO VERIFICADO (nenhuma fonte) | — | — | Testar com preço real no Piloto (H1/H9) |
| E-commerce em Angola cresceu 72% no 1.º semestre de 2026, para 110 mil milhões de Kz; o artigo atribui parte do crescimento à adaptação das pequenas empresas às redes sociais | INDÍCIO (imprensa, um jornal) | https://expansao.co.ao/angola/detalhe/e-commerce-cresce-72-para-110-mil-milhoes-kz-a-boleia-da-expansao-digital-73724.html | 2026-08-05 (edição de 2026-07-31) | Contexto de procura, não prova de pagamento por estes módulos |
| Facebook mais usado que Instagram; TikTok com cerca de 3 M de perfis (DataReportal, Jan 2024; Facebook 5 M; Instagram 763 mil) | INDÍCIO | https://expansao.co.ao/empresas/detalhe/tik-tok-em-alta-com-3-milhoes-de-perfis-ameaca-facebook-em-angola-61678.html | 2024-04-06 | Dados antigos; ver NapoleonCat acima |
| Concorrentes locais conhecidos: marketplaces BayQi, Roque Online, Tupuca+ (referidos no documento `01`); ferramentas de IA locais de catálogo/fotos/social: não encontrei | NÃO VERIFICADO | `../../exploracao/01-modelo-negocios-angola-ai-first.md` Nº 4 | — | Rever na pesquisa de mercado do Piloto |

---

## 6. Protecção de dados das fotos (Lei 22/11)

| Afirmação | Estado | Fonte | Data | Implicação para o desenho |
|---|---|---|---|---|
| A Lei 22/11 define dados pessoais como «qualquer informação, seja qual for a sua natureza ou suporte, **incluindo imagem e som**, relativa a uma pessoa singular identificada ou identificável», sendo identificável quem o possa ser directa ou indirectamente, nomeadamente por número de identificação | CONFIRMADO (texto num repositório não oficial; verificar no Diário da República) | https://angolex.com/paginas/leis/lei-de-protecao-de-dados-pessoais.html | texto 2011 | Foto com rosto reconhecível é dado pessoal |
| Matrícula de veículo, rosto de cliente, ecrã de telemóvel ou documento visível na foto são dados pessoais ou potenciais identificadores | INDÍCIO (inferência a partir da definição; sem fonte angolana sobre matrículas) | idem | — | Tratar como pessoais por defeito |
| Enviar imagens a um fornecedor no estrangeiro com rostos/matrículas é **transferência internacional** (Art. 33-34: notificação para destino adequado, autorização da APD para os restantes); precedente de multa por cloud fora do país sem notificação/autorização (Crescer Tech, USD 505 mil, 24-6-2026) | CONFIRMADO (os artigos e a multa, ver E3); INDÍCIO (aplicação a imagens) | `E3_Regulatorio_Dados.md` §1.1 e §2 | 2026-10-08 | Os fornecedores de imagem entram no inventário de subprocessadores e no mapa de transferências para a APD (D9) |
| Foto de produto **sem pessoas** não é, em princípio, dado pessoal; mas o EXIF pode conter GPS do telemóvel e a identificação do dono | INDÍCIO (inferência) | — | — | Remover EXIF antes de qualquer envio; guardar o original só no nosso storage |
| Não há lista pública de países adequados nem cláusulas-tipo da APD | NÃO VERIFICADO | `E3_Regulatorio_Dados.md` §2 | 2026-10-08 | Os EUA (Photoroom, Google, OpenAI) provavelmente exigem autorização (INDÍCIO da E3) |
| Marca/registo de marca «KAMBÁ» e as marcas das PMEs nas artes | NÃO VERIFICADO (a confirmar por parecer) | — | — | Pergunta ao advogado §9 |

**Mitigações de desenho (requisitos):**
1. **Gate de minimização de imagem (MED):** detector de rostos e de matrículas a correr **em Angola** (open-source, sem chamada externa); se detectar, desfocar/recortar antes de enviar ao fornecedor, ou bloquear e pedir outra foto. Medir falsos negativos no golden set.
2. **Remoção de EXIF/GPS** e redução da resolução ao necessário (os fornecedores indicam 25 Mpx como máximo).
3. **Fornecedor por tenant com `allowed_destinations`** e cláusula de não-treino e retenção zero/mínima por escrito (ADR-008, requisito 8 da E3).
4. **Download imediato** do resultado e apagamento no fornecedor onde a API o permita (Bria: 3 dias por omissão, configurável).
5. **Sem uploads para o tier gratuito** dos fornecedores (Gemini gratuito tem revisão humana e treino).
6. **Declaração ao dono** na confirmação: «esta foto vai ser processada por serviço de IA no estrangeiro» (aviso de privacidade, E3 §requisito 2).
7. **Dados de teste e de avaliação**: usar apenas imagens sintéticas ou autorizadas pela PME (ADR-018).
8. Aceitar que o dono carrega imagens de terceiros (clientes) ou de fornecedores: cláusula nos termos (garantia de que tem direitos) e canal de remoção.

---

## 7. Direitos de autor (apenas INDÍCIO e risco)

| Afirmação | Estado | Fonte | Data | Implicação para o desenho |
|---|---|---|---|---|
| A Lei 15/14 (Direitos de Autor e Conexos) define **autor** como «a pessoa física que cria uma obra intelectual de natureza literária, artística e científica» | CONFIRMADO (texto no repositório angolex; verificar no DR) | https://angolex.com/paginas/leis/lei-dos-direitos-de-autor-e-conexos-15a-14a.html | Lei de 2014-07-31 | Obra sem autor humano: **provável ausência de protecção** (INDÍCIO, inferência; não encontrei texto angolano sobre IA) |
| Obras fotográficas protegidas quando organizadas para transmitir mensagem jornalística, artística ou estética e com originalidade; devem respeitar o direito à imagem; devem identificar o autor | CONFIRMADO (texto) | idem (Art. 10.º) | 2014 | A foto do dono, enquanto original, é protegida; a KAMBÁ precisa de **licença contratual do dono** para a processar. O resultado do cutout é obra derivada de foto do dono |
| Obras derivadas (transformação de obra originária) são protegidas como tais | CONFIRMADO (texto) | idem (Art. 5.º) | 2014 | Edição de foto alheia (por exemplo catálogo de fornecedor copiado) exige autorização do autor da original |
| Tratamento de obras geradas por IA no direito angolano (titularidade, registo): não encontrei fonte | NÃO VERIFICADO | pesquisa web | 2026-10-09 | Tratar como zona sem garantia |
| Projecto de Lei da IA (em consulta desde Set 2025) menciona marcação (watermark) de conteúdo gerado e direito de recusar uso de dados para treino | INDÍCIO (imprensa) | `E3_Regulatorio_Dados.md` §3 | 2025-11/12 | Reforça rotular conteúdo e `is_ai_generated` |
| Risco de **imagens de terceiros**: o negócio Nº 4 («catálogo a partir de foto do produto») e Nº 3 («base de preços extraída de mensagens, PDFs e sites») podem copiar fotos, descrições ou tabelas de preços de terceiros | INDÍCIO (risco) | `../../exploracao/01-modelo-negocios-angola-ai-first.md` | — | Catálogo AI: **só a partir de foto do dono**; sem busca de imagens na web; descrições geradas pelo modelo e validadas pelo dono (a Lei 15/03 sobre publicidade enganosa/informação, ver E3 §4) |

---

## Bloqueios e riscos

| # | Bloqueio/risco | Gravidade | Estado | Mitigação / acção |
|---|---|---|---|---|
| B1 | **Publicação automática depende de Advanced Access** (App Review + Business Verification) sem prazo oficial; documentos angolanos na Business Verification NÃO VERIFICADOS; as PMEs podem não ter Página/conta profissional | Alta | CONFIRMADO / NÃO VERIFICADO | Publicação manual no Piloto; pedir permissões no mesmo ciclo do Tech Provider; inquérito às PMEs |
| B2 | **Fornecedor de imagem: contradição de treino na Photoroom; Bria sem declaração de treino; BFL e remove.bg excluídos; OpenAI/Google sob termos de nuvem** | Alta | CONFIRMADO (contradição) | Carta de não-treino e retenção por fornecedor antes de qualquer foto real; bake-off com dados sintéticos |
| B3 | **Transferência internacional (EUA) de imagens com pessoas/matrículas/EXIF** | Alta | INDÍCIO (qualificação) / CONFIRMADO (precedente APD) | Gate de minimização local; inventário de subprocessadores; parecer D9; notificação/autorização APD |
| B4 | **Remetente de mensagens proactivas à PME** (número KAMBÁ vs número da PME) interage com ADR-011/D10 | Média | NÃO VERIFICADO | Piloto: dono inicia; pergunta à Meta |
| B5 | Texto em português nas imagens geradas sem garantia (pt-BR recomendado, pt-PT/AO não) | Média | CONFIRMADO (doc Google) | Texto compositado por código |
| B6 | Latência: OpenAI até 2 min; restantes NÃO VERIFICADO; WhatsApp exige 200 rápido | Média | CONFIRMADO / NÃO VERIFICADO | Pipeline assíncrono, mensagem «a preparar», timeouts e fallback de fornecedor |
| B7 | Qualidade para fundo limpo/relighting de fotos de telemóvel angolanas sem prova | Média | NÃO VERIFICADO | Bake-off com 30 fotos reais autorizadas antes de fixar fornecedor |
| B8 | Direitos de autor: artes sem protecção; fotos de terceiros; semelhança gerada para outros | Média | INDÍCIO | Cláusulas nos termos; sem garantia de exclusividade; catálogo só a partir de foto do dono |
| B9 | Rotulagem de IA: o parâmetro existe no Instagram, mas política de 2026 (Meta/TikTok) não foi lida; publicação manual deixa a responsabilidade no dono | Média | CONFIRMADO (parâmetro) / NÃO VERIFICADO (política 2026) | Nota de entrega: «activa o rótulo de IA»; confirmar com a Meta |
| B10 | Orçamento expresso: orçamento/proforma pode ser confundido com documento fiscal; a plataforma não é software validado AGT (E3 §6) | Média | INDÍCIO | Rótulo «Orçamento — não é factura»; sem numeração fiscal |
| B11 | Preços e descrições errados gerados por IA (responsabilidade perante o consumidor, Lei 15/03 Art. 9 e 21; E3 §4) | Média | INDÍCIO | Validador de citação (ADR-007); dono aprova antes de publicar |
| B12 | Custos em USD (imagem + Meta) e câmbio; entidade pagadora por definir (D9) | Baixa | CONFIRMADO | Metering por tenant (LiteLLM não cobre fornecedores de imagem: acrescentar contador próprio) |
| B13 | Lei contra desinformação (vigor 6-8-2026): publicar/difundir conteúdo gerado por IA em nome de PMEs pode tocar em «contas inautênticas» | Baixa-Média | INDÍCIO (E3) | Identificar conteúdo como gerado por IA; evitar publicação em massa automática no Piloto |

---

## Perguntas para o advogado e para a Meta

### Para o advogado (angolano)

1. Uma fotografia de produto que contém rostos, matrículas, documentos ou ecrãs é «dado pessoal» (Lei 22/11, Art. 5.º b) «imagem e som»)? Enviar essa imagem a um fornecedor nos EUA é transferência internacional sujeita a autorização (Art. 34.º)? Basta **desfocar rostos e matrículas localmente** antes de enviar para a imagem deixar de ser dado pessoal?
2. Fotos sem pessoas mas com EXIF (GPS, nome do dono): ficam fora do regime se o EXIF for removido antes de sair de Angola?
3. A notificação/autorização da APD cobre **cada fornecedor de imagem** (Photoroom, Bria, Google, OpenAI) como destinatário, ou basta o mapa de transferências com garantias contratuais? Quem notifica: a KAMBÁ ou cada PME (D9)?
4. Titularidade e protecção de **imagens geradas por IA** à luz da Lei 15/14 (autor = pessoa física): existe protecção quando o dono escolhe e aprova a peça? Que cláusula devo pôr nos termos para a PME (licença, sem exclusividade, sem garantia de ausência de semelhança)?
5. A edição de uma foto fornecida pelo dono (cutout, fundo) que contém obra de terceiros (embalagem de marca, logótipo, produto de fornecedor): é obra derivada que exige autorização? Quem responde: a PME ou a KAMBÁ?
6. Responsabilidade da KAMBÁ por publicidade enganosa ou informação errada (Lei 15/03 Art. 9.º e 21.º) quando a legenda ou arte é gerada por IA e **aprovada** pelo dono.
7. Marca «KAMBÁ»: pesquisa de anterioridade e registo no IAPI; uso da marca em artes geradas.
8. Orçamento/proforma gerado pela plataforma: precisa de algum requisito formal ou de validação AGT? Qual a diferença legal entre orçamento e factura proforma?
9. Marketing por WhatsApp à PME (propostas semanais): basta o opt-in electrónico recolhido no onboarding (Lei 22/11 Art. 19.º, Instrutivo INACOM 4/20)?
10. Lei contra a desinformação (vigor 6-8-2026): a publicação automatizada de conteúdo gerado por IA em páginas de PMEs é «disseminação artificial»? Obrigações de rotulagem?
11. Registo de imagens de clientes das PMEs (carregadas em conversas de clientes) como tratamento de dados de terceiros: as PMEs têm base legal para as enviar a um subcontratado no estrangeiro?

### Para a Meta (por escrito)

1. As permissões `instagram_business_content_publish`, `pages_manage_posts` e `pages_read_engagement` podem ser pedidas na mesma app e na mesma Business Verification que o Tech Provider do WhatsApp? Prazos reais de App Review e de Business Verification para uma empresa angolana; documentos aceites.
2. Uma plataforma multi-cliente pode publicar em nome de PMEs (conteúdo gerado por IA e aprovado pelo dono) sem violar a Platform Policy? Há restrições a ferramentas que geram e publicam conteúdo de IA?
3. Política de 2026 de rotulagem: o rótulo «AI info» é obrigatório para imagens de produto editadas por IA (cutout, fundo gerado) em Instagram e Facebook? O `is_ai_generated` na API é suficiente ou exige também metadados IPTC/C2PA?
4. As Contas profissionais do Instagram e as Páginas estão plenamente disponíveis para negócios em Angola (+244)? Há PPA obrigatória?
5. Um número WhatsApp **da KAMBÁ** (negócio) pode enviar templates (propostas semanais de conteúdo, avisos de arte pronta) aos donos das PMEs clientes? Isto é considerado «número agregador» (D2/D10) ou relação normal entre negócio e cliente?
6. Classificação de «proposta semanal de ideias de conteúdo» e de «arte pronta para aprovação, pedida pelo dono»: marketing ou utility? Pode ser pré-validada?
7. O limite por utilizador de templates de marketing (per-user limits) está activo em Angola? Valor?
8. Direct Send (utility sem template) estará disponível para portfólios abaixo de 100.000 mensagens?
9. (Repetidas da E1, relevantes aqui) Facturação em Kwanzas ou por Solution Partner; IVA/impostos aplicados nas tarifas para destinatários +244.

### Para os fornecedores de imagem (por escrito, antes de usar fotos reais)

1. **Photoroom:** as imagens enviadas pela API self-serve são usadas para treino? Resolver a contradição entre a política de privacidade (março 2026) e a página de segurança. Cotação para ~10-50 mil imagens/ano e DPA assinado. Aceitam clientes em Angola?
2. **Bria:** as imagens de entrada são usadas para treino ou melhoria? Região de processamento; DPA fora do Enterprise; termos de API específicos.
3. **Google (Gemini):** tempo exacto de retenção de logs de abuso nos serviços pagos e países de processamento; DPA para uso por subcontratado da KAMBÁ; possibilidade de região fixa.
4. **OpenAI:** aprovação de Zero Data Retention ou Modified Abuse Monitoring para um projecto de imagens; leitura dos termos de propriedade do output (a página devolveu 403).

---

## Limitações desta pesquisa

- Qualidade visual, latência real e comportamento em fotos angolanas não foram medidos (não executei os modelos): são NÃO VERIFICADO e exigem bake-off.
- Preços de Photoroom por volume (slider) e de OpenAI por imagem em qualidade média/alta não ficaram legíveis no HTML; usei o preço-base e uma estimativa assinalada.
- Termos de utilização da OpenAI e da Photoroom não foram lidos (403/404); Claid e Cloudinary não foram analisados em profundidade.
- A política de rotulagem de IA da Meta lida é de 2024 (blog oficial); a de 2026 e a do TikTok não foram obtidas de página oficial.
- O repositório angolano de legislação (angolex/lex.ao) não é o Diário da República; confirmar artigos antes de citar.
- Não encontrei dados de mercado angolano sobre disposição a pagar, concorrentes de IA locais nem percentagem de PMEs com Página/conta profissional.
- Resultados de WebSearch e resumos de WebFetch foram usados só para descobrir URLs ou como INDÍCIO; os dados CONFIRMADO vêm de leitura do HTML ou do ficheiro de tarifas.

## Fontes principais (leitura directa, 2026-10-09)

- Meta WhatsApp: https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing (+ ficheiro «USD list rates»); `/templates/template-categorization`; `/getting-opt-in`; `/templates/marketing-templates/per-user-limits`; `/direct-send`.
- Instagram/Facebook: https://developers.facebook.com/documentation/instagram-platform/content-publishing ; `/instagram-platform/overview` ; https://developers.facebook.com/documentation/pages-api/posts ; https://about.fb.com/news/2024/04/metas-approach-to-labeling-ai-generated-content-and-manipulated-media/
- Imagem: https://www.photoroom.com/api/pricing ; https://www.photoroom.com/platform/security ; https://www.photoroom.com/legal/privacy-policy ; https://bria.ai/pricing ; https://docs.bria.ai/getting-started/asset-retention ; https://bria.ai/terms-of-use ; https://ai.google.dev/gemini-api/docs/pricing ; https://ai.google.dev/gemini-api/terms ; https://ai.google.dev/gemini-api/docs/image-generation ; https://ai.google.dev/gemini-api/docs/available-regions ; https://platform.openai.com/docs/pricing ; https://platform.openai.com/docs/guides/image-generation ; https://platform.openai.com/docs/guides/your-data ; https://platform.openai.com/docs/supported-countries ; https://bfl.ai/legal/flux-api-service-terms ; https://docs.bfl.ai/quick_start/pricing ; https://www.remove.bg/api
- Angola: https://angolex.com/paginas/leis/lei-de-protecao-de-dados-pessoais.html ; https://angolex.com/paginas/leis/lei-dos-direitos-de-autor-e-conexos-15a-14a.html ; https://brandixao.com/precos/ ; https://napoleoncat.com/stats/social-media-users-in-angola/2025 ; https://expansao.co.ao/angola/detalhe/e-commerce-cresce-72-para-110-mil-milhoes-kz-a-boleia-da-expansao-digital-73724.html
- Evidência interna: `E1_Meta_WhatsApp.md`, `E3_Regulatorio_Dados.md`, `../00_Arquitectura_Solucao.md`, `../../exploracao/01-modelo-negocios-angola-ai-first.md`.
