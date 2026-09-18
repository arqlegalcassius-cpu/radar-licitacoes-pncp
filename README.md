# Radar de Licitações — PNCP (Demolição · Construção · Reforma)

Robô interno que monitora o **Portal Nacional de Contratações Públicas (PNCP)**
— fonte oficial e obrigatória desde a Lei nº 14.133/2021, cobrindo órgãos
federais, estaduais e municipais em todo o Brasil — filtra editais de
**demolição, construção e reforma**, avisa a empresa por **WhatsApp** e mantém
um **painel (dashboard)** com o histórico. Roda de graça no GitHub Actions,
sem precisar de servidor próprio.

⚠️ **Isto não é aconselhamento jurídico.** O robô existe para você não perder
prazos e oportunidades — a decisão de participar, a análise de habilitação,
exigências de atestado de capacidade técnica, garantias, etc. deve sempre ser
feita lendo o edital completo.

---

## Como funciona

1. A cada execução, consulta `https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao`
   para as modalidades de obras (Concorrência, Dispensa) nos últimos dias.
2. Filtra o texto do objeto do edital por palavras-chave de demolição/construção/reforma.
3. Ignora editais que já foram vistos antes (guarda estado em `data/seen.json`).
4. Se você configurar a chave da API da Anthropic, cada oportunidade nova
   ganha um resumo curto do escopo/pontos de atenção, gerado por IA.
5. Envia um resumo consolidado no seu WhatsApp.
6. Salva tudo em `docs/data.json`, que alimenta o painel em `docs/index.html`.

## Passo a passo de configuração (uns 15 minutos)

### 1. Criar o repositório
Crie um repositório **privado** no GitHub (ex: `radar-licitacoes`) e suba
todos os arquivos desta pasta para ele.

### 2. Ativar o WhatsApp (CallMeBot — gratuito)
1. Salve o número **+34 644 59 71 67** nos seus contatos (é o bot do CallMeBot).
2. Envie no WhatsApp, para esse número, a mensagem:
   `I allow callmebot to send me messages`
3. Você vai receber uma resposta com a sua **API Key** (um número).
4. Guarde: seu número de telefone completo com código do país (ex: `5521999999999`) e essa API Key.

> Para volumes maiores no futuro, o caminho "oficial" é a Meta WhatsApp
> Cloud API (tem faixa gratuita, mas exige conta Business verificada e
> aprovação de templates) — o CallMeBot é o caminho mais simples para
> começar sem burocracia.

### 3. Configurar os *Secrets* do repositório
No GitHub: **Settings → Secrets and variables → Actions → New repository secret**

| Nome | Valor |
|---|---|
| `WHATSAPP_PHONE` | seu número com DDI, ex: `5521999999999` |
| `CALLMEBOT_APIKEY` | a API key que o CallMeBot te enviou |
| `ANTHROPIC_API_KEY` | *(opcional)* sua chave da API da Anthropic, para os resumos de escopo por IA |

### 4. (Opcional) Configurar as *Variables* do repositório
Mesma tela, aba **Variables**, se quiser mudar os padrões:

| Nome | Padrão | Exemplo |
|---|---|---|
| `UFS` | vazio = Brasil inteiro | `SP,RJ,MG` |
| `MODALIDADES` | `4,5,8` (Concorrência Eletrônica/Presencial, Dispensa) | `4,5,6,8` |
| `DIAS_RETROATIVOS` | `2` | `3` |

### 5. Ativar o GitHub Pages (o painel/dashboard)
**Settings → Pages → Source: "Deploy from a branch" → Branch: `main` / pasta `/docs` → Save.**
Em alguns minutos seu painel estará em `https://SEU-USUARIO.github.io/SEU-REPO/`.

### 6. Testar
**Actions → Monitor de licitações PNCP → Run workflow** (botão manual).
Depois de rodar, confira:
- Se chegou mensagem no WhatsApp (só chega se houver oportunidade nova no período).
- Se `docs/data.json` foi atualizado (aba "Actions" mostra o commit automático).
- O painel em GitHub Pages.

Depois disso, ele roda sozinho 2x por dia (08h e 17h, horário de Brasília) —
ajustável no `cron` de `.github/workflows/monitor.yml`.

## Ajustando as palavras-chave

Edite as listas `KEYWORDS` e `BLACKLIST` no topo de `monitor_pncp.py`.
Hoje a prioridade é demolição > construção > reforma (primeira que bater
no texto do objeto do edital define a categoria mostrada).

## Limitações conhecidas (e próximos passos sugeridos)

- **Não há busca por palavra-chave nativa na API do PNCP** — o filtro é feito
  aqui no script, em cima do texto do campo `objetoCompra`. Ajuste as
  palavras-chave conforme for vendo falsos positivos/negativos.
- **O resumo por IA usa os metadados estruturados do edital** (objeto, valor,
  prazos, amparo legal), não o PDF completo do edital. Ler o PDF do edital
  inteiro (para extrair exigências de habilitação, planilha orçamentária
  etc.) é um próximo passo possível, usando os endpoints de documentos da
  contratação (ver Manual de Integração PNCP) + extração de texto de PDF.
- **CallMeBot é um serviço não-oficial e gratuito**, ótimo para começar, mas
  tem limite informal de volume. Se o número de alertas crescer muito,
  migrar para a WhatsApp Cloud API oficial da Meta é o caminho natural.
- Vale também acompanhar, além do PNCP, os **portais estaduais próprios**
  (ex.: BEC-SP) — a maioria dos órgãos já publica no PNCP por obrigação
  legal, mas checagens pontuais no portal do seu estado são uma boa prática
  enquanto o histórico do robô ainda é curto.
