#!/usr/bin/env python3
"""
Monitor de licitações do PNCP (Portal Nacional de Contratações Públicas)
para empresa de engenharia interessada em: demolição > construção > reforma.

Fonte oficial: https://pncp.gov.br/api/consulta/v1
Base legal: Lei nº 14.133/2021 — publicação no PNCP é obrigatória para todos
os órgãos federais, estaduais e municipais.

Este script:
  1. Consulta contratações publicadas no PNCP, por modalidade, num período recente.
  2. Filtra pelo texto do objeto usando listas de palavras-chave (demolição/construção/reforma).
  3. Deduplica contra um "seen.json" (evita alertar 2x o mesmo edital).
  4. Opcionalmente gera um resumo/escopo com a API da Anthropic (Claude).
  5. Envia um resumo consolidado por WhatsApp via CallMeBot.
  6. Grava um log em docs/data.json para o dashboard (GitHub Pages).

Nenhuma parte disto é aconselhamento jurídico. Sempre leia o edital completo
antes de decidir participar — este script serve para NÃO PERDER a oportunidade,
não para substituir a análise de habilitação/exigências técnicas.
"""

import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# CONFIGURAÇÃO (ajuste aqui ou via variáveis de ambiente / secrets do GitHub)
# --------------------------------------------------------------------------

PNCP_BASE = "https://pncp.gov.br/api/consulta/v1"

# UFs a monitorar. Lista vazia = Brasil inteiro (todas as UFs de uma vez,
# a própria API já devolve nacionalmente quando "uf" não é informado).
UFS = [s.strip().upper() for s in os.environ.get("UFS", "").split(",") if s.strip()]

# Modalidades de contratação relevantes para obras/serviços de engenharia
# (tabela de domínio oficial do PNCP):
#   2 = Diálogo Competitivo | 4 = Concorrência Eletrônica | 5 = Concorrência Presencial
#   6 = Pregão Eletrônico    | 8 = Dispensa de Licitação
# Por padrão usamos as modalidades típicas de obras: Concorrência e Dispensa.
MODALIDADES = [int(m) for m in os.environ.get("MODALIDADES", "4,5,8").split(",") if m.strip()]

# Janela de datas: quantos dias para trás olhar a cada execução.
# 2 dias dá uma margem de segurança contra falhas/atrasos de execução.
DIAS_RETROATIVOS = int(os.environ.get("DIAS_RETROATIVOS", "2"))

TAMANHO_PAGINA = 500  # máximo permitido pela API

WHATSAPP_PHONE = os.environ.get("WHATSAPP_PHONE", "")       # ex: 5521999999999
CALLMEBOT_APIKEY = os.environ.get("CALLMEBOT_APIKEY", "")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")  # opcional
ANTHROPIC_MODEL = "claude-sonnet-4-6"

MAX_ITENS_NA_MENSAGEM = 12  # não deixar a mensagem de WhatsApp gigante

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
SEEN_PATH = os.path.join(DATA_DIR, "seen.json")
LOG_PATH = os.path.join(DOCS_DIR, "data.json")
MAX_LOG_ITEMS = 500

# --------------------------------------------------------------------------
# PALAVRAS-CHAVE — ajuste livremente conforme o apetite da empresa.
# A ordem de prioridade é demolição > construção > reforma (primeira que bater).
# --------------------------------------------------------------------------

KEYWORDS = {
    "demolicao": [
        "demolicao", "demolir", "demolicoes",
    ],
    "construcao": [
        "construcao de", "construcao civil", "construir", "edificacao nova",
        "obra nova", "execucao de obra", "implantacao de", "ampliacao de",
    ],
    "reforma": [
        "reforma", "retrofit", "requalificacao", "recuperacao estrutural",
        "recuperacao predial", "manutencao predial", "revitalizacao",
    ],
}

# Termos que costumam gerar falso-positivo (nada a ver com obra/engenharia).
BLACKLIST = [
    "reforma tributaria", "reforma administrativa", "reforma da previdencia",
    "reforma politica", "reforma agraria", "reforma trabalhista",
    "software", "sistema informatizado", "licenca de uso",
]


def normalize(text: str) -> str:
    """Minusculas e sem acento, para comparação robusta de palavras-chave."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def match_categoria(objeto: str, info_complementar: str = ""):
    """Retorna a categoria (demolicao/construcao/reforma) ou None."""
    texto = normalize(f"{objeto} {info_complementar}")
    for termo_proibido in BLACKLIST:
        if termo_proibido in texto:
            return None
    for categoria in ("demolicao", "construcao", "reforma"):
        for termo in KEYWORDS[categoria]:
            if termo in texto:
                return categoria
    return None


# --------------------------------------------------------------------------
# HTTP helpers (sem dependências externas — só urllib)
# --------------------------------------------------------------------------

def http_get_json(url: str, tentativas: int = 3, espera: float = 2.0):
    ultimo_erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 204:
                    return {"data": [], "totalPaginas": 0}
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 204:
                return {"data": [], "totalPaginas": 0}
            ultimo_erro = e
        except Exception as e:  # noqa: BLE001
            ultimo_erro = e
        time.sleep(espera * (i + 1))
    print(f"[aviso] falha ao consultar {url}: {ultimo_erro}", file=sys.stderr)
    return {"data": [], "totalPaginas": 0}


def fetch_contratacoes(modalidade: int, data_inicial: str, data_final: str, uf: str = ""):
    """Pagina o endpoint /contratacoes/publicacao para uma modalidade e janela de datas."""
    resultados = []
    pagina = 1
    while True:
        params = {
            "dataInicial": data_inicial,
            "dataFinal": data_final,
            "codigoModalidadeContratacao": modalidade,
            "pagina": pagina,
            "tamanhoPagina": TAMANHO_PAGINA,
        }
        if uf:
            params["uf"] = uf
        url = f"{PNCP_BASE}/contratacoes/publicacao?{urllib.parse.urlencode(params)}"
        payload = http_get_json(url)
        dados = payload.get("data") or []
        resultados.extend(dados)
        total_paginas = payload.get("totalPaginas", 0) or 0
        if pagina >= total_paginas or not dados:
            break
        pagina += 1
        time.sleep(0.3)  # gentil com a API pública
    return resultados


def build_pncp_link(item: dict) -> str:
    """Monta o link do edital no portal público do PNCP."""
    cnpj = (item.get("orgaoEntidade") or {}).get("cnpj", "")
    ano = item.get("anoCompra", "")
    sequencial = item.get("sequencialCompra", "")
    if cnpj and ano and sequencial:
        return f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"
    return item.get("linkSistemaOrigem", "") or ""


def formatar_valor(valor) -> str:
    try:
        v = float(valor)
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "não informado"


def formatar_data(data_str) -> str:
    if not data_str:
        return "não informada"
    try:
        dt = datetime.fromisoformat(data_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        return data_str[:10]


# --------------------------------------------------------------------------
# Resumo/escopo com IA (opcional — só roda se ANTHROPIC_API_KEY existir)
# --------------------------------------------------------------------------

def resumir_escopo_com_claude(item: dict) -> str:
    if not ANTHROPIC_API_KEY:
        return ""
    orgao = (item.get("orgaoEntidade") or {}).get("razaosocial", "")
    unidade = (item.get("unidadeOrgao") or {}) or {}
    prompt = (
        "Você é um assistente de uma empresa de engenharia que disputa licitações "
        "públicas no Brasil (demolição, construção e reforma). Com base nos dados "
        "abaixo de um edital publicado no PNCP, escreva em português, em no máximo "
        "4 linhas curtas (bullets com '-'), o escopo provável do serviço, o que a "
        "empresa deve verificar antes de participar (ex.: exigência de atestado de "
        "capacidade técnica, visita técnica, garantia de proposta) e o nível de "
        "atenção ao prazo. Seja direto, sem introduções.\n\n"
        f"Órgão: {orgao}\n"
        f"Município/UF: {unidade.get('municipioNome', '')}/{unidade.get('ufSigla', '')}\n"
        f"Modalidade: {item.get('modalidadeNome', '')}\n"
        f"Objeto: {item.get('objetoCompra', '')}\n"
        f"Informação complementar: {item.get('informacaoComplementar', '')}\n"
        f"Valor total estimado: {item.get('valorTotalEstimado', '')}\n"
        f"Abertura de propostas: {item.get('dataAberturaProposta', '')}\n"
        f"Encerramento de propostas: {item.get('dataEncerramentoProposta', '')}\n"
        f"Amparo legal: {(item.get('amparoLegal') or {}).get('nome', '')}\n"
    )
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({
                "model": ANTHROPIC_MODEL,
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            partes = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
            return "\n".join(partes).strip()
    except Exception as e:  # noqa: BLE001
        print(f"[aviso] resumo com Claude falhou: {e}", file=sys.stderr)
        return ""


# --------------------------------------------------------------------------
# WhatsApp via CallMeBot (gratuito para uso pessoal/baixo volume)
# --------------------------------------------------------------------------

def enviar_whatsapp(mensagem: str):
    if not (WHATSAPP_PHONE and CALLMEBOT_APIKEY):
        print("[info] WHATSAPP_PHONE/CALLMEBOT_APIKEY não configurados — pulando envio.")
        return
    # CallMeBot tem limite de tamanho por mensagem; corta em blocos se preciso.
    blocos = [mensagem[i:i + 3000] for i in range(0, len(mensagem), 3000)] or [mensagem]
    for bloco in blocos:
        params = {"phone": WHATSAPP_PHONE, "text": bloco, "apikey": CALLMEBOT_APIKEY}
        url = f"https://api.callmebot.com/whatsapp.php?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=20) as resp:
                print(f"[info] WhatsApp enviado, status {resp.status}")
        except Exception as e:  # noqa: BLE001
            print(f"[erro] falha ao enviar WhatsApp: {e}", file=sys.stderr)
        time.sleep(15)  # respeita o rate-limit do CallMeBot entre mensagens


# --------------------------------------------------------------------------
# Persistência local (seen.json e log do dashboard)
# --------------------------------------------------------------------------

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


CATEGORIA_LABEL = {
    "demolicao": "DEMOLIÇÃO",
    "construcao": "CONSTRUÇÃO",
    "reforma": "REFORMA",
}
CATEGORIA_PRIORIDADE = {"demolicao": 0, "construcao": 1, "reforma": 2}


def main():
    hoje = datetime.now(timezone.utc)
    data_final = hoje.strftime("%Y%m%d")
    data_inicial = (hoje - timedelta(days=DIAS_RETROATIVOS)).strftime("%Y%m%d")

    seen = load_json(SEEN_PATH, {"ids": []})
    seen_ids = set(seen.get("ids", []))

    log = load_json(LOG_PATH, {"gerado_em": "", "itens": []})

    ufs_para_consultar = UFS or [""]  # "" = nacional, sem filtro de UF

    novos = []
    for modalidade in MODALIDADES:
        for uf in ufs_para_consultar:
            itens = fetch_contratacoes(modalidade, data_inicial, data_final, uf)
            for item in itens:
                categoria = match_categoria(
                    item.get("objetoCompra", ""), item.get("informacaoComplementar", "")
                )
                if not categoria:
                    continue
                pncp_id = item.get("numeroControlePNCP")
                if not pncp_id or pncp_id in seen_ids:
                    continue
                seen_ids.add(pncp_id)
                unidade = item.get("unidadeOrgao") or {}
                orgao = item.get("orgaoEntidade") or {}
                registro = {
                    "id": pncp_id,
                    "categoria": categoria,
                    "orgao": orgao.get("razaosocial", ""),
                    "municipio": unidade.get("municipioNome", ""),
                    "uf": unidade.get("ufSigla", ""),
                    "modalidade": item.get("modalidadeNome", ""),
                    "objeto": item.get("objetoCompra", ""),
                    "valor_estimado": item.get("valorTotalEstimado"),
                    "abertura_proposta": item.get("dataAberturaProposta", ""),
                    "encerramento_proposta": item.get("dataEncerramentoProposta", ""),
                    "link": build_pncp_link(item),
                    "capturado_em": hoje.isoformat(),
                    "resumo_ia": "",
                }
                novos.append(registro)

    # Resumo com IA (se configurado) — feito só para os itens novos.
    for registro in novos:
        item_completo = {
            "orgaoEntidade": {"razaosocial": registro["orgao"]},
            "unidadeOrgao": {"municipioNome": registro["municipio"], "ufSigla": registro["uf"]},
            "modalidadeNome": registro["modalidade"],
            "objetoCompra": registro["objeto"],
            "informacaoComplementar": "",
            "valorTotalEstimado": registro["valor_estimado"],
            "dataAberturaProposta": registro["abertura_proposta"],
            "dataEncerramentoProposta": registro["encerramento_proposta"],
            "amparoLegal": {},
        }
        registro["resumo_ia"] = resumir_escopo_com_claude(item_completo)

    # Ordena por prioridade (demolição > construção > reforma) e depois por prazo.
    novos.sort(key=lambda r: (CATEGORIA_PRIORIDADE.get(r["categoria"], 9), r["encerramento_proposta"] or ""))

    print(f"[info] {len(novos)} nova(s) oportunidade(s) encontrada(s).")

    if novos:
        linhas = [f"*Radar de licitações — {hoje.strftime('%d/%m/%Y %H:%M UTC')}*",
                  f"{len(novos)} nova(s) oportunidade(s):", ""]
        for registro in novos[:MAX_ITENS_NA_MENSAGEM]:
            objeto_curto = (registro["objeto"] or "")[:160]
            linhas.append(
                f"[{CATEGORIA_LABEL[registro['categoria']]}] {registro['municipio']}/{registro['uf']} "
                f"— {registro['orgao']}\n"
                f"{objeto_curto}\n"
                f"Valor est.: {formatar_valor(registro['valor_estimado'])} | "
                f"Propostas até: {formatar_data(registro['encerramento_proposta'])}\n"
                f"{registro['link']}"
            )
            if registro["resumo_ia"]:
                linhas.append(registro["resumo_ia"])
            linhas.append("")
        if len(novos) > MAX_ITENS_NA_MENSAGEM:
            linhas.append(f"+ {len(novos) - MAX_ITENS_NA_MENSAGEM} outra(s) no dashboard.")
        mensagem = "\n".join(linhas)
        enviar_whatsapp(mensagem)

    # Atualiza estado (seen.json) e log do dashboard.
    seen["ids"] = list(seen_ids)[-20000:]  # evita crescer para sempre
    save_json(SEEN_PATH, seen)

    log["gerado_em"] = hoje.isoformat()
    log["itens"] = (novos + log.get("itens", []))[:MAX_LOG_ITEMS]
    save_json(LOG_PATH, log)


if __name__ == "__main__":
    main()
