import os
import json
import io
from PIL import Image
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai

# Configuração da API do Gemini via Variável de Ambiente
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

app = FastAPI(title="Oracle MT5 Bridge Hibrida", version="4.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def format_price(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"

def to_float(v: Any, default: float = 0.0) -> float:
    try: return float(v)
    except: return default

def to_int(v: Any, default: int = 0) -> int:
    try: return int(v)
    except: return default

# ===================================================================
# FUNÇÕES DE APOIO - MOTOR REGRAS PYTHON (QUANT)
# ===================================================================
def obter_indicadores(metadata: Dict[str, Any]) -> Dict[str, float]:
    ind = metadata.get("indicadores", {}) or {}
    return {
        "ema20": to_float(ind.get("ema20", 0.0)),
        "ema200": to_float(ind.get("ema200", 0.0)),
        "atr": to_float(ind.get("atr", 0.0)),
        "vwap_diaria": to_float(ind.get("vwap_diaria", 0.0)),
        "vwap_semanal": to_float(ind.get("vwap_semanal", 0.0)),
        "vwap_mensal": to_float(ind.get("vwap_mensal", 0.0)),
        "zscore_volume": to_float(ind.get("zscore_volume", 0.0)),
    }

def contar_pressao(candles: List[Dict[str, Any]]) -> Dict[str, int]:
    bullish, bearish = 0, 0
    for c in candles:
        o, cl = to_float(c.get("open", 0)), to_float(c.get("close", 0))
        if cl > o: bullish += 1
        elif cl < o: bearish += 1
    return {"bullish": bullish, "bearish": bearish}

def classificar_volume(zscore_volume: float, candles_recentes: List[Dict[str, Any]]) -> Dict[str, str]:
    volumes = [to_float(c.get("tick_volume", 0)) for c in candles_recentes if to_float(c.get("tick_volume", 0)) > 0]
    if len(volumes) < 3: return {"mercado_status": "Sem leitura", "qualidade_volume": "Baixa", "confirmacao_volume": "Sem dados"}
    media_vol = sum(volumes) / len(volumes)
    rel = volumes[-1] / media_vol if media_vol > 0 else 0

    if zscore_volume <= -0.35 or rel < 0.75:
        return {"mercado_status": "Mercado Vazio", "qualidade_volume": "Fraca", "confirmacao_volume": "Sem Interesse"}
    if -0.35 < zscore_volume < 0.20:
        return {"mercado_status": "Liquidez Normal", "qualidade_volume": "Media", "confirmacao_volume": "Parcial"}
    return {"mercado_status": "Alta Atividade", "qualidade_volume": "Forte", "confirmacao_volume": "Volume Apoia"}

def verificar_exaustao(candles_recentes: List[Dict[str, Any]], preco: float, indicadores: Dict[str, float]) -> str:
    atr = indicadores.get("atr", 0.0)
    vwap_d = indicadores.get("vwap_diaria", 0.0)
    ema200 = indicadores.get("ema200", 0.0)
    margem_distorcao = (atr * 2.5) if atr > 0 else (preco * 0.002)

    ancora = vwap_d if vwap_d > 0 else ema200
    if ancora == 0: return ""

    esticado_topo = (preco - ancora) > margem_distorcao
    esticado_fundo = (ancora - preco) > margem_distorcao
    if not (esticado_topo or esticado_fundo): return ""

    rejeicao_topo, rejeicao_fundo = 0, 0
    for c in candles_recentes[-4:]:
        o, h, l, cl = to_float(c.get("open")), to_float(c.get("high")), to_float(c.get("low")), to_float(c.get("close"))
        tamanho, corpo = h - l, abs(o - cl)
        if tamanho == 0: continue
        pavio_sup, pavio_inf = h - max(o, cl), min(o, cl) - l
        if pavio_sup > corpo * 1.5 or (cl < o and corpo > tamanho * 0.6): rejeicao_topo += 1
        if pavio_inf > corpo * 1.5 or (cl > o and corpo > tamanho * 0.6): rejeicao_fundo += 1

    if esticado_topo and rejeicao_topo >= 2: return "VENDA_EXAUSTAO"
    if esticado_fundo and rejeicao_fundo >= 2: return "COMPRA_EXAUSTAO"
    return ""

def classificar_fluxo(preco: float, indicadores: Dict[str, float], candles_recentes: List[Dict[str, Any]]) -> Dict[str, Any]:
    ema20, ema200, vwap_d = indicadores["ema20"], indicadores["ema200"], indicadores["vwap_diaria"]
    pressao = contar_pressao(candles_recentes)
    volume_info = classificar_volume(indicadores["zscore_volume"], candles_recentes)
    
    sinal_exaustao = verificar_exaustao(candles_recentes, preco, indicadores)
    if sinal_exaustao == "VENDA_EXAUSTAO":
        return {"sinal": "VENDA", "tipo_cenario": "EXAUSTAO DE TOPO", "confianca": "85%", "vies": "Reversao Baixista", "modo_operacional": "Scalp de Retorno", "motivo_curto": "Preco esticado + Rejeicao institucional", **volume_info}
    if sinal_exaustao == "COMPRA_EXAUSTAO":
        return {"sinal": "COMPRA", "tipo_cenario": "EXAUSTAO DE FUNDO", "confianca": "85%", "vies": "Reversao Altista", "modo_operacional": "Scalp de Retorno", "motivo_curto": "Preco descontado + Absorcao no fundo", **volume_info}

    score_c, score_v = 0, 0
    if ema20 > 0: score_c += (preco > ema20); score_v += (preco < ema20)
    if ema20 > 0 and ema200 > 0: score_c += (ema20 > ema200); score_v += (ema20 < ema200)
    if vwap_d > 0: score_c += (preco > vwap_d); score_v += (preco < vwap_d)
    if pressao["bullish"] > pressao["bearish"]: score_c += 1
    elif pressao["bearish"] > pressao["bullish"]: score_v += 1

    if score_c >= 3 and score_c > score_v: return {"sinal": "COMPRA", "tipo_cenario": "ALINHAMENTO COMPRADOR", "confianca": "80%", "vies": "Estrutura de Alta", "modo_operacional": "A Favor do Fluxo", "motivo_curto": "Suporte macro alinhado com pressao", **volume_info}
    if score_v >= 3 and score_v > score_c: return {"sinal": "VENDA", "tipo_cenario": "ALINHAMENTO VENDEDOR", "confianca": "80%", "vies": "Estrutura de Baixa", "modo_operacional": "A Favor do Fluxo", "motivo_curto": "Resistencia macro alinhada com pressao", **volume_info}

    return {"sinal": "SEM SINAL CLARO", "tipo_cenario": "AGUARDE", "confianca": "50%", "vies": "Indefinido", "modo_operacional": "Protecao", "motivo_curto": "Estrutura ruidosa ou falta de confluencia", **volume_info}

def calcular_stop_alvo_dinamico(preco: float, point: float, digits: int, swing: List[Dict[str, Any]], sinal: str, indicadores: Dict[str, float], tipo_cenario: str) -> Dict[str, Any]:
    buffer_preco = max(point * 5, point)
    stop_razao = "Protecao por volatilidade (ATR)"
    
    if sinal == "COMPRA":
        fundo = min(to_float(c["low"]) for c in swing) if swing else preco
        stop = fundo - buffer_preco
        if swing: stop_razao = "Abaixo do ultimo fundo do Swing"
    else:
        topo = max(to_float(c["high"]) for c in swing) if swing else preco
        stop = topo + buffer_preco
        if swing: stop_razao = "Acima do ultimo topo do Swing"

    risco = abs(preco - stop)
    if risco <= 0:
        risco = max(point * 120, preco * 0.001)
        stop = (preco - risco) if sinal == "COMPRA" else (preco + risco)

    niveis = []
    if indicadores["ema20"] > 0: niveis.append(indicadores["ema20"])
    if indicadores["ema200"] > 0: niveis.append(indicadores["ema200"])
    
    vwap_d = indicadores["vwap_diaria"]
    if vwap_d > 0:
        niveis.append(vwap_d)
        atr = indicadores.get("atr", risco)
        niveis.extend([vwap_d + (atr*1.5), vwap_d - (atr*1.5), vwap_d + (atr*3.0), vwap_d - (atr*3.0)])
    
    if swing:
        niveis.append(max(to_float(c["high"]) for c in swing))
        niveis.append(min(to_float(c["low"]) for c in swing))

    alvo, alvo_razao = 0.0, ""
    if "EXAUSTAO" in tipo_cenario and vwap_d > 0:
        if (sinal == "COMPRA" and vwap_d > preco) or (sinal == "VENDA" and vwap_d < preco):
            alvo, alvo_razao = vwap_d, "Ima magnetico na VWAP Diaria"
    
    if alvo == 0.0:
        if sinal == "COMPRA":
            validos = sorted([n for n in niveis if n > preco + (risco * 0.9)])
            if validos: alvo, alvo_razao = validos[0], "Proxima Resistencia"
            else: alvo, alvo_razao = preco + (risco * 2), "Projecao Matematica"
        elif sinal == "VENDA":
            validos = sorted([n for n in niveis if n < preco - (risco * 0.9)], reverse=True)
            if validos: alvo, alvo_razao = validos[0], "Proximo Suporte"
            else: alvo, alvo_razao = preco - (risco * 2), "Projecao Matematica"

    return {"entrada": round(preco, digits), "stop": round(stop, digits), "alvo": round(alvo, digits), "stop_razao": stop_razao, "alvo_razao": alvo_razao}

def gerar_resposta_pergunta(pergunta: str, fluxo: Dict[str, Any], niveis: Dict[str, Any], digits: int) -> str:
    p = (pergunta or "").strip().lower()
    if not p: return ""
    if any(w in p for w in ["por que", "pq", "motivo"]): return f"Decisao baseada em: {fluxo['motivo_curto']}."
    if any(w in p for w in ["risco", "stop", "perigo"]): return f"Risco travado em {format_price(niveis['stop'], digits)} ({niveis['stop_razao']})."
    if any(w in p for w in ["alvo", "lucro", "target"]): return f"Projetando alvo em {format_price(niveis['alvo'], digits)} ({niveis['alvo_razao']})."
    if any(w in p for w in ["volume"]): return f"Leitura de volume: {fluxo['qualidade_volume']} ({fluxo['mercado_status']})."
    return "A IA analisou os parametros da sua pergunta junto ao fluxo atual."

def analisar_motor_regras(metadata: Dict[str, Any], pergunta: str) -> Dict[str, Any]:
    symbol = metadata.get("symbol", "ATIVO")
    timeframe = metadata.get("timeframe", "M15")
    digits = to_int(metadata.get("digits", 2))
    point = to_float(metadata.get("point", 0.01))
    
    candles = metadata.get("candles", [])
    if len(candles) < 10: return {"status": "erro", "mensagem": "Poucas velas"}

    indicadores = obter_indicadores(metadata)
    candles_validos = candles[:-1] if len(candles) > 1 else candles
    preco_ref = to_float(metadata.get("ask")) if to_float(metadata.get("ask")) > 0 else to_float(candles_validos[-1]["close"])
    
    fluxo = classificar_fluxo(preco_ref, indicadores, candles_validos[-8:])
    
    niveis = {"entrada": 0, "stop": 0, "alvo": 0, "stop_razao": "", "alvo_razao": ""}
    if fluxo["sinal"] != "SEM SINAL CLARO":
        niveis = calcular_stop_alvo_dinamico(preco_ref, point, digits, candles_validos[-8:], fluxo["sinal"], indicadores, fluxo["tipo_cenario"])

    coment1 = f"[ GATILHO ] {fluxo['motivo_curto']}" if fluxo['sinal'] != "SEM SINAL CLARO" else "[ AVISO ] Mercado ruidoso. Fique de fora."
    coment2 = f"[ STOP ] {niveis['stop_razao']}" if fluxo['sinal'] != "SEM SINAL CLARO" else ""
    coment3 = f"[ ALVO ] {niveis['alvo_razao']}" if fluxo['sinal'] != "SEM SINAL CLARO" else ""
    
    resposta_ia = gerar_resposta_pergunta(pergunta, fluxo, niveis, digits)
    ctx1 = f"[ INFO ] {resposta_ia}" if resposta_ia else f"[ MERCADO ] {fluxo['mercado_status']}"

    return {
        "status": "sucesso", "sinal": fluxo["sinal"], "ativo": symbol, "timeframe": timeframe,
        "entrada": format_price(niveis["entrada"], digits) if niveis["entrada"] else "",
        "stop": format_price(niveis["stop"], digits) if niveis["stop"] else "",
        "alvo": format_price(niveis["alvo"], digits) if niveis["alvo"] else "",
        "confianca": fluxo["confianca"], "tipo_cenario": fluxo["tipo_cenario"],
        "vies": fluxo["vies"], "modo_operacional": fluxo["modo_operacional"],
        "mercado_status": fluxo["mercado_status"], "qualidade_volume": fluxo["qualidade_volume"],
        "confirmacao_volume": fluxo["confirmacao_volume"],
        "comentario_l1": coment1[:60], "comentario_l2": coment2[:60], "comentario_l3": coment3[:60],
        "contexto_l1": ctx1[:60]
    }

# ===================================================================
# FUNÇÃO DE APOIO - MOTOR GEMINI 1.5 FLASH (API Google)
# ===================================================================
def analisar_motor_gemini(metadata: Dict[str, Any], pergunta: str, chart_image: Image.Image) -> Dict[str, Any]:
    if not api_key:
        return {"status": "erro", "mensagem": "GEMINI_API_KEY nao configurada no servidor."}

    digits = int(metadata.get("digits", 2))
    symbol = metadata.get("symbol", "ATIVO")
    timeframe = metadata.get("timeframe", "M15")

    system_instruction = """
    Você é um Engenheiro Quantitativo Sênior e Trader Institucional operando MetaTrader 5.
    Sua missão é cruzar a imagem do gráfico (Price Action/Rejeições) com os dados técnicos fornecidos no JSON (VWAP, EMA20, EMA200, Z-Score de Volume).
    
    Regras de Ouro:
    1. Opere com alvos lógicos de liquidez (VWAP, EMA200 ou Topos/Fundos).
    2. Entenda EXAUSTÃO: Se o preço está muito esticado da VWAP e deixa pavio longo, favoreça o Retorno à Média.
    3. Mantenha os textos curtos e impactantes, use as tags solicitadas.
    4. NUNCA use acentos nas suas respostas de texto.
    
    Responda EXATAMENTE neste formato JSON, sem crases markdown:
    {
      "status": "sucesso",
      "sinal": "COMPRA", // VENDA ou SEM SINAL CLARO
      "tipo_cenario": "EXAUSTAO DE TOPO", 
      "confianca": "85%",
      "vies": "Reversao Baixista",
      "modo_operacional": "Scalp de Retorno",
      "mercado_status": "Alta Atividade",
      "qualidade_volume": "Forte",
      "confirmacao_volume": "Volume Apoia",
      "entrada": 4720.66, 
      "stop": 4725.31, 
      "alvo": 4699.40, 
      "comentario_l1": "[ GATILHO ] Preco esticado e rejeicao forte no topo",
      "comentario_l2": "[ STOP ] Protecao acima do pavio de rejeicao", 
      "comentario_l3": "[ ALVO ] Ima magnetico na VWAP Diaria", 
      "contexto_l1": "[ INFO ] O volume apoia a reversao por exaustao" 
    }
    """

    prompt_usuario = f"""
    Dados Técnicos do MT5:
    {json.dumps(metadata, indent=2)}

    Pergunta do Trader: '{pergunta}'
    
    Analise a imagem e os dados. Se for Sem Sinal, deixe entrada/stop/alvo zerados.
    Retorne APENAS o JSON válido.
    """

    try:
        # Mudamos para o FLASH: Rápido, liberado para todas as regiões e imune ao Erro 404
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content([system_instruction, chart_image, prompt_usuario])
        
        resposta_texto = response.text.strip()
        if resposta_texto.startswith("```"):
            linhas = resposta_texto.split("\n")
            if len(linhas) > 2: resposta_texto = "\n".join(linhas[1:-1])

        resultado_ia = json.loads(resposta_texto)
        
        if resultado_ia.get("entrada", 0) > 0:
            resultado_ia["entrada"] = format_price(float(resultado_ia["entrada"]), digits)
            resultado_ia["stop"] = format_price(float(resultado_ia["stop"]), digits)
            resultado_ia["alvo"] = format_price(float(resultado_ia["alvo"]), digits)
        else:
            resultado_ia["entrada"] = ""
            resultado_ia["stop"] = ""
            resultado_ia["alvo"] = ""

        resultado_ia["ativo"] = symbol
        resultado_ia["timeframe"] = timeframe

        return resultado_ia

    except Exception as e:
        # Blindagem contra a API caindo ou retornando erros não mapeados
        return {"status": "erro", "mensagem": f"A API do Google falhou: {str(e)}"}

# ===================================================================
# ENDPOINT PRINCIPAL (ROTEADOR DE MOTORES)
# ===================================================================
@app.get("/")
async def home():
    return {"status": "online", "servico": "oracle_mt5_bridge", "versao": "4.2"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/analisar-mt5-completo")
async def analisar_mt5_completo(
    file: UploadFile = File(...),
    metadata_json: str = Form(...),
    pergunta: Optional[str] = Form(default=""),
    motor: Optional[str] = Form(default="gemini") # "gemini" ou "regras"
):
    try:
        image_bytes = await file.read()
        chart_image = Image.open(io.BytesIO(image_bytes))
        metadata = json.loads(metadata_json)
        
        # Despachante Híbrido
        if motor == "gemini" and api_key:
            return analisar_motor_gemini(metadata, pergunta or "", chart_image)
        else:
            return analisar_motor_regras(metadata, pergunta or "")

    except Exception as e:
        return {"status": "erro", "mensagem": f"Erro interno na Bridge: {str(e)}"}
