# Consentimento para gravação de voz — spike de transcrição (KAM-107)

> **Rascunho do executor. A forma jurídica é NÃO VERIFICADO.** O texto cobre o
> que o critério 2 do bloco exige que o falante consinta — a gravação e o envio a
> um fornecedor nos EUA — e o que o `docs/tecnica/08_Seguranca_Conformidade.md`
> §8.1 diz de um consentimento (livre, específico, explícito, informado, separado
> por finalidade; Lei 22/11, Art. 5.º a)). **Se o envio aos EUA pode assentar no
> consentimento expresso escrito do Art. 34.º, e que forma esse consentimento
> deve ter, é exactamente a pergunta X1 do KAM-104, alíneas (ii) e (iii), que
> está aberta** — e o pacote pede ao advogado a minuta a usar. Se a minuta chegar,
> **substitui** este texto. Se a via for o risco aceite pelo fundador, este texto
> usa-se como está, com essa aceitação registada.
>
> Os campos entre `[ ]` preenche-os quem conduz o spike. Nenhum foi preenchido.

---

**KAMBÁ — Pedido de consentimento para gravar a sua voz**

**Quem pede.** [Nome da entidade], [contacto do responsável pelo estudo, pelo
papel].

**Para que é.** Estamos a testar dois serviços que transformam voz em texto
(«transcrição automática»), para saber se percebem bem o português falado em
Angola — números, preços, horas, moradas e palavras de Kimbundu ou Umbundu. O
resultado serve **só** para escolher qual dos dois serviços usar, ou para
decidir não usar nenhum. **Não** é usado para treinar nenhum programa nosso, nem
para publicidade, nem para o identificar.

**O que lhe pedimos.** Que leia em voz alta 22 frases que nós escrevemos —
sobre compras, preços, entregas e marcações — e que grave algumas delas num
sítio com barulho. As frases não falam de si. **Pedimos-lhe que não diga o seu
nome, o seu número de telefone nem nenhum dado seu durante a gravação.**

**Como guardamos.**
- A sua gravação fica identificada por um código (por exemplo `F03`), nunca pelo
  seu nome. Só este papel liga o seu nome ao código, e fica guardado em [arquivo,
  pelo papel de quem o guarda].
- Duas pessoas da nossa equipa ouvem a gravação para escrever o que disse.
- **Apagamos a sua gravação no máximo 24 horas depois de a enviarmos para
  transcrição, e em qualquer caso no fim do estudo**, previsto para [data].
- O texto do que disse (não a voz) fica guardado até [prazo — regra de
  retenção, a fixar pelo fundador antes de começar].
- O relatório final só tem números (percentagens de erro, tempos, custos). Não
  tem a sua voz, o seu nome, nem o seu código.

**Envio para fora de Angola.** Para testar os serviços, a gravação é enviada a
**duas empresas nos Estados Unidos da América**:
- Groq — serviço `whisper-large-v3-turbo` [entidade jurídica contratante, a confirmar];
- OpenAI — serviço `gpt-4o-mini-transcribe` [entidade jurídica contratante, a confirmar].

Antes de enviar, verificamos e registamos que cada uma **não guarda** a gravação
para além do tempo de responder e **não a usa para treinar** os seus programas:
[o que cada fornecedor garante, com a data em que se verificou]. Os Estados
Unidos podem ter regras de protecção de dados diferentes das de Angola.

**Os seus direitos.** A participação é voluntária, e dizer que não, ou desistir,
não tem nenhuma consequência para si. Pode, a qualquer momento: pedir para ouvir
ou saber o que temos (acesso), corrigir, ou pedir que apaguemos tudo (Lei 22/11,
Arts. 26.º a 28.º). Se desistir **antes** do envio, nada é enviado e apagamos a
gravação no próprio dia. Se desistir **depois** do envio, apagamos tudo o que
está connosco e pedimos às duas empresas que apaguem o que tiverem, se ainda
tiverem alguma coisa. Contacto para isto: [contacto, pelo papel].

**Autorizo** (assinale cada caso em separado):

- [ ] que gravem a minha voz a ler as frases do estudo;
- [ ] que a gravação seja enviada à **Groq**, nos Estados Unidos, para
      transcrição;
- [ ] que a gravação seja enviada à **OpenAI**, nos Estados Unidos, para
      transcrição;
- [ ] declaro que tenho 18 anos ou mais.

Nome: ____________________ Código atribuído: `F__`

Assinatura: ____________________ Data: ____ / ____ / ________

Recebi uma cópia deste documento: [ ] sim

---

*Nota para quem conduz o spike:* um falante que não assinale os dois envios não
entra no corpus — o spike mede os **dois** STT sobre o mesmo áudio, e um clip
enviado só a um quebra a comparação. A data deste papel é a que vai para o
ficheiro de autorização (`autorizacao.py`), pelo código e nunca pelo nome.
