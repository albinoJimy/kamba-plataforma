# Entrevistas a PMEs: texto de consentimento e regras de dados

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — consentimento das entrevistas do KAM-106 e tratamento das notas |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-106 (EPIC-10) |
| Estado | NÃO VERIFICADO — o texto segue a Lei 22/11 tal como `../E3_Regulatorio_Dados.md` §1 a descreve, e não passou por parecer jurídico |
| Fonte | `../E3_Regulatorio_Dados.md` §1 e §1.1; `../E5_Modulos_Entrada.md` §6; `../../../../specs/EPIC-10_Spikes_Validacao_Gates.md` (bloco KAM-106, «Detalhes Técnicos») |
| Dono | Responsável de Produto, com o Responsável de Segurança para o arquivo controlado |
| Documento-fonte | `../E3_Regulatorio_Dados.md`; `../E5_Modulos_Entrada.md` §6 |
| Relacionados | [`Entrevistas_Guiao.md`](Entrevistas_Guiao.md), [`Pacote_Parecer_Juridico.md`](Pacote_Parecer_Juridico.md) |

> **Nada aqui é aconselhamento jurídico** (EPIC-10 §1). Os artigos citados
> vêm de `../E3_Regulatorio_Dados.md`, que os leu em repositórios não oficiais
> e manda verificá-los no Diário da República antes de os citar em contrato ou
> parecer. Herdam esse estado. O que não está verificado fica **NÃO
> VERIFICADO (a confirmar por parecer)**, e há três pontos (§3) que têm de ser
> respondidos **antes da primeira entrevista**.

---

## 1. O texto (ler à pessoa entrevistada, ou entregar por escrito)

Os campos entre parênteses rectos preenchem-se antes de imprimir; os dois
primeiros dependem do §3.

> **Entrevista sobre o atendimento e as vendas de pequenas e médias empresas**
>
> Chamo-me [nome do entrevistador] e trabalho para [entidade responsável]. Estamos
> a conversar com cerca de 30 empresas em Luanda para perceber como atendem e
> vendem aos clientes por mensagem. Não estou a vender nada.
>
> **O que registamos.** As suas respostas, a categoria do que vende, o número de
> pessoas da empresa e a sua opinião sobre preços. O nome da empresa e o seu
> contacto ficam guardados à parte, num arquivo com acesso restrito, e **não**
> aparecem nas notas, que usam um código.
>
> **O que não registamos.** Dados dos seus clientes. Se for preciso dar um
> exemplo, não diga nomes nem números de clientes.
>
> **Para quê.** Para estudar o mercado e desenhar um serviço. Os resultados
> publicam-se apenas em números agregados, sem nada que identifique a sua
> empresa. As notas não são vendidas nem cedidas a ninguém.
>
> **Convite para um teste (só se autorizar).** No fim, posso perguntar-lhe se
> quer participar num teste gratuito. Se autorizar abaixo, guardamos o seu
> contacto para esse convite e para mais nada; se não autorizar, o contacto
> não se usa para isso.
>
> **Durante quanto tempo.** [prazo de conservação — ver §3], e depois são
> apagadas.
>
> **Os seus direitos.** A participação é voluntária: pode recusar, não responder
> a uma pergunta, ou parar a qualquer momento, sem consequência nenhuma. Pode
> pedir para ver o que registámos, para o corrigir ou para o apagar, através de
> [contacto de privacidade].
>
> **Gravação.** [Só se for gravar:] Peço-lhe também autorização para gravar o
> áudio desta conversa, apenas para não perder as respostas. A gravação fica no
> mesmo arquivo restrito e apaga-se no mesmo prazo. Pode aceitar a entrevista e
> recusar a gravação.
>
> Concorda em participar e que tomemos notas nestas condições?
> ☐ Sim ☐ Não    [Se gravar:] Concorda com a gravação do áudio? ☐ Sim ☐ Não
> Autoriza que usemos o seu contacto para o convite para o teste? ☐ Sim ☐ Não
>
> Data: ____-__-__   Assinatura (ou consentimento gravado no início do áudio): ______

**Consentimento gravado.** Quando não há papel, o entrevistador lê o texto e
grava a pergunta e a resposta no início do áudio; a ficha regista `gravado`. A
gravação de voz é dado pessoal (a definição da Lei 22/11 inclui «imagem e som»,
citada em `../E5_Modulos_Entrada.md` §6), e guarda-se como as notas.

## 2. Em que se apoia cada frase

| Frase do texto | Base | Estado |
|---|---|---|
| Pedir consentimento antes de tomar notas, específico por finalidade — o estudo, a gravação e o convite para o teste têm cada um a sua resposta | Consentimento é «manifestação de vontade livre, específica, explícita e informada» (Art. 5.º a)); tratamento com consentimento «inequívoco e expresso» ou outra base (Art. 12.º) | CONFIRMADO (portal, `../E3_Regulatorio_Dados.md` §1) |
| Dizer finalidade, o que se regista e quem recebe | Direito de informação (Art. 25.º); informar a origem dos dados e os destinatários | Art. 25.º CONFIRMADO (portal, resumo); o resto INDÍCIO (`../E3_Regulatorio_Dados.md` §1) |
| Ver, corrigir, apagar, opor-se | Arts. 26.º a 28.º | CONFIRMADO (portal, resumo); prazo de 60 dias úteis INDÍCIO |
| Conservar só o tempo necessário | Art. 11.º | CONFIRMADO (portal, resumo) — **o prazo é que falta** (§3) |
| Separar contacto e notas, acesso restrito | Medidas de segurança (Art. 30.º); acesso indevido é crime (Arts. 55.º–59.º) | CONFIRMADO (portal) |
| A gravação é dado pessoal | Definição inclui «imagem e som» | CONFIRMADO (repositório não oficial), `../E5_Modulos_Entrada.md` §6 |
| Uma entrevista anónima com categoria, n.º de empregados e canal pode identificar a PME indirectamente | Inferência a partir da definição de identificável | INDÍCIO — por isso a ficha preenchida fica fora do repositório, como manda o critério 8 |

## 3. O que tem de ser respondido antes da primeira entrevista

Três pontos que esta preparação **não decide**, porque não são do executor:

1. **Notificação ou autorização prévia à APD para este tratamento.** A Lei
   22/11 exige notificação ou autorização para «(quase) todo o tratamento»
   (Arts. 35.º–37.º, CONFIRMADO quanto à obrigação, `../E3_Regulatorio_Dados.md`
   §1), e a APD já multou por falta de autorização prévia (§1.1). Se 30
   entrevistas com notas pseudonimizadas estão abrangidas, e em nome de que
   entidade se notifica, é **NÃO VERIFICADO (a confirmar por parecer)**. Candidato natural a entrar no
   [`Pacote_Parecer_Juridico.md`](Pacote_Parecer_Juridico.md) (KAM-104); esta
   preparação não lhe acrescenta a pergunta.
2. **Prazo de conservação** das notas, gravações, consentimentos e da ficha
   preenchida. É uma decisão de retenção, e fica por tomar: o texto leva o
   campo em branco. O que a letra fixa é só que os dados brutos ficam fora do
   repositório.
3. **Onde fica o arquivo controlado.** Guardar ou enviar dados a uma *cloud*
   fora de Angola sem notificação nem autorização foi o que valeu à Crescer
   Tech a multa de USD 505 mil (`../E3_Regulatorio_Dados.md` §1.1, CONFIRMADO).
   Enquanto o parecer não responder, a leitura conservadora é: **arquivo em
   Angola, sem serviços no estrangeiro — o que inclui não passar as notas por
   nenhum modelo de linguagem**. É *proposta*, e a escolha do arquivo é do
   Responsável de Produto com o de Segurança.

Mais dois campos do texto que se preenchem antes de imprimir, sem decisão
jurídica: a **entidade responsável** (quem determina as finalidades, Art. 5.º)
e o **contacto de privacidade**.

## 4. Regras para quem entrevista

- Sem consentimento, não há notas; a linha da ficha, se existir, leva `nao` e
  fica vazia no resto — o *script* recusa a ficha se não estiver.
- Sem a autorização do convite, o contacto não entra na lista de PMEs-alvo que
  se entrega ao KAM-109.
- O nome da PME, o nome da pessoa e o contacto vivem só no arquivo controlado,
  ligados ao `id_anonimo`. Nunca na ficha, nunca no repositório, nunca numa
  mensagem de chat.
- Não se recolhem dados de clientes finais da PME. Se forem ditos, não se
  escrevem.
- Um pedido de acesso, correcção ou apagamento resolve-se no arquivo e na
  ficha; se a ficha já tiver sido medida, a medição repete-se.

## 5. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Produto | | | |
| Responsável de Segurança (arquivo controlado) | | | |
| Advogado (parecer, §3) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, preparação do KAM-106 (lote 24). Texto de consentimento em PT-AO, escrito ou gravado, com a gravação e o convite para o teste como finalidades opcionais e separadas; tabela que liga cada frase ao artigo da Lei 22/11 com o estado que `../E3_Regulatorio_Dados.md` lhe dá; três pontos por responder antes da primeira entrevista (notificação à APD, prazo de conservação, local do arquivo), nenhum decidido aqui. | Equipa KAMBÁ |
