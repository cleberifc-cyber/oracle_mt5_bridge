import json
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Oracle MT5 Bridge", version="3.7")

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
    try:
        return float(v)
    except Exception:
        return default


def to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def split_text_lines(text: str, max_len: int, max_lines: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return [""] * max_lines

    words = text.split()
    lines: List[str] = []
    current = ""

    for w in words:
        candidate = w if current == "" else current + " " + w
        if len(candidate) <= max_len:
            current = candidate
        else:
            lines.append(current)
            current = w
            if len(lines) >= max_lines - 1:
                break

    if current and len(lines) < max_lines:
        lines.append(current)

    while len(lines) < max_lines:
        lines.append("")

    return lines[:max_lines]


# ===================================================================
# NOVO MÓDULO: Q&A INTELIGENTE (SIMULAÇÃO DE NLP INSTITUCIONAL)
# ===================================================================
def interpretar_pergunta(
    pergunta: str,
    sinal: str,
    entrada: float,
    stop: float,
    alvo: float,
    digits: int,
    vies: str,
    modo_operacional: str,
    fatores: List[str],
    confianca: str,
    qualidade_volume: str
) -> str:
    p = (pergunta or "").strip().lower()

    if not p:
        return ""

    # Intenção: Motivo / Por que?
    if any(w in p for w in ["por que", "porque", "motivo", "explicacao", "pq", "razao"]):
        if sinal == "SEM SINAL CLARO":
            return "Nao entramos porque a estrutura atual apresenta ruidos e falta de confluencia institucional."
        fator_txt = ", ".join(fatores[:2]) if fatores else "leitura de fluxo dinamico"
        return f"A decisao baseia-se em: {fator_txt}. Isso gera nossa confianca de {confianca}."

    # Intenção: Risco / Stop / Proteção
    if any(w in p for w in ["risco", "stop", "protecao", "perigo", "seguro"]):
        if sinal == "SEM SINAL CLARO":
            return "O maior risco agora e operar num mercado sem direcao. Fique de fora."
        distancia = abs(entrada - stop)
        return f"Risco controlado. Stop tecnico posicionado em {format_price(stop, digits)}, protegido pela estrutura."

    # Intenção: Alvo / Ganho / Target
    if any(w in p for w in ["alvo", "target", "lucro", "ganho", "objetivo"]):
        if sinal == "SEM SINAL CLARO":
            return "Sem alvo definido pois nao ha operacao ativa recomendada."
        return f"Projetamos a saida principal na regiao de liquidez em {format_price(alvo, digits)} (Risco/Retorno 2:1)."

    # Intenção: Volume / Força
    if any(w in p for w in ["volume", "forca", "institucional", "players"]):
        return f"O volume atual e classificado como {qualidade_volume.lower()}. Os institucionais atuam em zonas de interesse."

    # Intenção: Tendência / Viés
    if any(w in p for w in ["tendencia", "vies", "direcao"]):
        return f"O fluxo macro favorece o vies {vies.lower()}. Nosso foco atual e: {modo_operacional}."

    # Intenção: Validade da operação (ainda vale?)
    if any(w in p for w in ["vale", "ainda", "entrar agora", "atrasado"]):
        if sinal == "SEM SINAL CLARO":
            return "Aguarde. O momento atual exige paciencia para buscar assimetria."
        return f"Operacao valida enquanto o preco se mantiver do lado correto do nosso limite em {format_price(stop, digits)}."

    # Fallback genérico educado
    return f"A IA considerou o seu contexto. Sinal vigente: {sinal} ({confianca} de confianca). Gestao de risco sempre em primeiro lugar."


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
    bullish = 0
    bearish = 0

    for c in candles:
        o = to_float(c.get("open", 0.0))
        cl = to_float(c.get("close", 0.0))
        if cl > o:
            bullish += 1
        elif cl < o:
            bearish += 1

    return {"bullish": bullish, "bearish": bearish}


def classificar_volume(zscore_volume: float, candles_recentes: List[Dict[str, Any]]) -> Dict[str, str]:
    volumes = [to_float(c.get("tick_volume", 0.0)) for c in candles_recentes if to_float(c.get("tick_volume", 0.0)) > 0]

    if len(volumes) < 3:
        return {
            "mercado_status": "Sem leitura",
            "qualidade_volume": "Baixa",
            "confirmacao_volume": "Sem dados"
        }

    media_vol = sum(volumes) / len(volumes)
    ultimo_vol = volumes[-1]

    if media_vol <= 0:
        return {
            "mercado_status": "Sem leitura",
            "qualidade_volume": "Baixa",
            "confirmacao_volume": "Sem dados"
        }

    rel = ultimo_vol / media_vol

    if zscore_volume <= -0.35 or rel < 0.75:
        return {
            "mercado_status": "Mercado Vazio",
            "qualidade_volume": "Fraca",
            "confirmacao_volume": "Sem Interesse"
        }

    if -0.35 < zscore_volume < 0.20:
        return {
            "mercado_status": "Liquidez Normal",
            "qualidade_volume": "Media",
            "confirmacao_volume": "Parcial"
        }

    return {
        "mercado_status": "Alta Atividade",
        "qualidade_volume": "Forte",
        "confirmacao_volume": "Volume Apoia"
    }


def verificar_exaustao(candles_recentes: List[Dict[str, Any]], preco: float, indicadores: Dict[str, float]) -> str:
    atr = indicadores.get("atr", 0.0)
    vwap_d = indicadores.get("vwap_diaria", 0.0)
    ema200 = indicadores.get("ema200", 0.0)

    margem_distorcao = (atr * 2.5) if atr > 0 else (preco * 0.002)

    if vwap_d == 0 and ema200 == 0:
        return ""

    ancora = vwap_d if vwap_d > 0 else ema200

    distancia_up = preco - ancora
    distancia_down = ancora - preco

    esticado_topo = distancia_up > margem_distorcao
    esticado_fundo = distancia_down > margem_distorcao

    if not (esticado_topo or esticado_fundo):
        return ""

    ultimos = candles_recentes[-4:]
    rejeicao_topo = 0
    rejeicao_fundo = 0

    for c in ultimos:
        o = to_float(c.get("open", 0))
        h = to_float(c.get("high", 0))
        l = to_float(c.get("low", 0))
        cl = to_float(c.get("close", 0))
        
        tamanho = h - l
        if tamanho == 0: continue

        corpo = abs(o - cl)
        pavio_sup = h - max(o, cl)
        pavio_inf = min(o, cl) - l

        if pavio_sup > corpo * 1.5 or (cl < o and corpo > tamanho * 0.6):
            rejeicao_topo += 1

        if pavio_inf > corpo * 1.5 or (cl > o and corpo > tamanho * 0.6):
            rejeicao_fundo += 1

    if esticado_topo and rejeicao_topo >= 2:
        return "VENDA_EXAUSTAO"
    
    if esticado_fundo and rejeicao_fundo >= 2:
        return "COMPRA_EXAUSTAO"

    return ""


def classificar_fluxo(
    preco: float,
    indicadores: Dict[str, float],
    candles_recentes: List[Dict[str, Any]]
) -> Dict[str, Any]:
    ema20 = indicadores["ema20"]
    ema200 = indicadores["ema200"]
    vwap_d = indicadores["vwap_diaria"]
    vwap_w = indicadores["vwap_semanal"]
    vwap_m = indicadores["vwap_mensal"]
    zscore = indicadores["zscore_volume"]

    pressao = contar_pressao(candles_recentes)
    bullish = pressao["bullish"]
    bearish = pressao["bearish"]

    volume_info = classificar_volume(zscore, candles_recentes)

    # 1. MÓDULO DE EXAUSTÃO
    sinal_exaustao = verificar_exaustao(candles_recentes, preco, indicadores)
    
    if sinal_exaustao == "VENDA_EXAUSTAO":
        return {
            "sinal": "VENDA",
            "tipo_cenario": "EXAUSTAO DE TOPO",
            "confianca": "85%",
            "vies": "Reversao Baixista",
            "modo_operacional": "Retorno a Media",
            "comentario_base": "O ativo subiu de forma agressiva e atingiu exaustao. Os big players estao defendendo o topo (rejeicao). Excelente oportunidade para buscar um scalp vendedor voltando para a VWAP.",
            "fatores": ["Preco muito esticado", "Absorcao institucional no topo"],
            "mercado_status": volume_info["mercado_status"],
            "qualidade_volume": volume_info["qualidade_volume"],
            "confirmacao_volume": volume_info["confirmacao_volume"],
        }
    
    if sinal_exaustao == "COMPRA_EXAUSTAO":
        return {
            "sinal": "COMPRA",
            "tipo_cenario": "EXAUSTAO DE FUNDO",
            "confianca": "85%",
            "vies": "Reversao Altista",
            "modo_operacional": "Retorno a Media",
            "comentario_base": "Queda severa gerando desvio padrao extremo. Identificamos forte defesa compradora (absorcao) no fundo. A simetria favorece uma compra de retorno a VWAP.",
            "fatores": ["Preco subprecificado", "Defesa compradora no fundo"],
            "mercado_status": volume_info["mercado_status"],
            "qualidade_volume": volume_info["qualidade_volume"],
            "confirmacao_volume": volume_info["confirmacao_volume"],
        }

    # 2. FLUXO NORMAL DE TENDÊNCIA E PULLBACK
    score_compra = 0
    score_venda = 0
    fatores_compra: List[str] = []
    fatores_venda: List[str] = []

    if ema20 > 0 and preco > ema20:
        score_compra += 1
        fatores_compra.append("Preco acima da EMA20")
    elif ema20 > 0 and preco < ema20:
        score_venda += 1
        fatores_venda.append("Preco abaixo da EMA20")

    if ema20 > 0 and ema200 > 0 and ema20 > ema200:
        score_compra += 1
        fatores_compra.append("Estrutura macro de Alta")
    elif ema20 > 0 and ema200 > 0 and ema20 < ema200:
        score_venda += 1
        fatores_venda.append("Estrutura macro de Baixa")

    if vwap_d > 0 and preco > vwap_d:
        score_compra += 1
        fatores_compra.append("Sustentacao acima da VWAP")
    elif vwap_d > 0 and preco < vwap_d:
        score_venda += 1
        fatores_venda.append("Pressao abaixo da VWAP")

    if bullish > bearish:
        score_compra += 1
        fatores_compra.append("Fluxo agressivo de compra")
    elif bearish > bullish:
        score_venda += 1
        fatores_venda.append("Fluxo agressivo de venda")

    if volume_info["qualidade_volume"] in ["Media", "Forte"]:
        if score_compra > score_venda:
            score_compra += 1
            fatores_compra.append("Apoio do volume financeiro")
        elif score_venda > score_compra:
            score_venda += 1
            fatores_venda.append("Apoio do volume financeiro")

    if volume_info["mercado_status"] == "Mercado Vazio":
        score_compra -= 1
        score_venda -= 1

    # Classificação Final Institucional
    if score_compra >= 4 and score_compra > score_venda:
        confianca_num = min(92, 65 + score_compra * 4)
        if volume_info["mercado_status"] == "Mercado Vazio":
            confianca_num = max(55, confianca_num - 15)

        return {
            "sinal": "COMPRA",
            "tipo_cenario": "ALINHAMENTO COMPRADOR",
            "confianca": f"{confianca_num}%",
            "vies": "Forte Alta",
            "modo_operacional": "Seguimento de Fluxo",
            "comentario_base": "O preco recuou em zona de liquidez e mostrou defesa. Com a estrutura alinhada a nosso favor, o risco/retorno justifica o posicionamento na compra.",
            "fatores": fatores_compra[:3],
            "mercado_status": volume_info["mercado_status"],
            "qualidade_volume": volume_info["qualidade_volume"],
            "confirmacao_volume": volume_info["confirmacao_volume"],
        }

    if score_venda >= 4 and score_venda > score_compra:
        confianca_num = min(92, 65 + score_venda * 4)
        if volume_info["mercado_status"] == "Mercado Vazio":
            confianca_num = max(55, confianca_num - 15)

        return {
            "sinal": "VENDA",
            "tipo_cenario": "ALINHAMENTO VENDEDOR",
            "confianca": f"{confianca_num}%",
            "vies": "Forte Baixa",
            "modo_operacional": "Seguimento de Fluxo",
            "comentario_base": "O preco corrigiu na resistencia e atraiu agressao vendedora. Estrutura macro alinhada para baixo. Otima janela para posicionamento na venda.",
            "fatores": fatores_venda[:3],
            "mercado_status": volume_info["mercado_status"],
            "qualidade_volume": volume_info["qualidade_volume"],
            "confirmacao_volume": volume_info["confirmacao_volume"],
        }

    return {
        "sinal": "SEM SINAL CLARO",
        "tipo_cenario": "AGUARDAR ALINHAMENTO",
        "confianca": "50%",
        "vies": "Indefinido",
        "modo_operacional": "Preservacao de Capital",
        "comentario_base": "O mercado apresenta ruidos, falta de direcao clara ou volume insuficiente. Profissionais nao operam no meio do caos. Aguarde a definicao das pontas.",
        "fatores": ["Cenario conflitante ou consolidado"],
        "mercado_status": volume_info["mercado_status"],
        "qualidade_volume": volume_info["qualidade_volume"],
        "confirmacao_volume": volume_info["confirmacao_volume"],
    }


def calcular_stop_alvo(
    preco_entrada: float,
    point: float,
    digits: int,
    candles_fechados: List[Dict[str, Any]],
    sinal: str
) -> Dict[str, float]:
    swing = candles_fechados[-6:] if len(candles_fechados) >= 6 else candles_fechados

    if not swing:
        risco_padrao = max(point * 120, abs(preco_entrada) * 0.001)
        if sinal == "COMPRA":
            stop = preco_entrada - risco_padrao
            alvo = preco_entrada + risco_padrao * 2.0
        else:
            stop = preco_entrada + risco_padrao
            alvo = preco_entrada - risco_padrao * 2.0

        return {
            "entrada": round(preco_entrada, digits),
            "stop": round(stop, digits),
            "alvo": round(alvo, digits),
        }

    buffer_preco = max(point * 5, point)

    if sinal == "COMPRA":
        fundo = min(to_float(c["low"]) for c in swing)
        stop = fundo - buffer_preco
        risco = abs(preco_entrada - stop)
        if risco <= 0:
            risco = max(point * 120, abs(preco_entrada) * 0.001)
            stop = preco_entrada - risco
        alvo = preco_entrada + (risco * 2.0)
    else:
        topo = max(to_float(c["high"]) for c in swing)
        stop = topo + buffer_preco
        risco = abs(stop - preco_entrada)
        if risco <= 0:
            risco = max(point * 120, abs(preco_entrada) * 0.001)
            stop = preco_entrada + risco
        alvo = preco_entrada - (risco * 2.0)

    return {
        "entrada": round(preco_entrada, digits),
        "stop": round(stop, digits),
        "alvo": round(alvo, digits),
    }


def analisar_candles(metadata: Dict[str, Any]) -> Dict[str, Any]:
    symbol = metadata.get("symbol", "ATIVO")
    timeframe = metadata.get("timeframe", "M15")
    bid = to_float(metadata.get("bid", 0.0))
    ask = to_float(metadata.get("ask", 0.0))
    point = to_float(metadata.get("point", 0.01), 0.01)
    digits = to_int(metadata.get("digits", 2), 2)
    candles = metadata.get("candles", []) or []

    if len(candles) < 20:
        return {
            "status": "erro",
            "mensagem": "Poucas velas recebidas."
        }

    indicadores = obter_indicadores(metadata)

    candles_fechados = candles[:-1] if len(candles) >= 2 else candles
    recentes = candles_fechados[-8:] if len(candles_fechados) >= 8 else candles_fechados

    ultimo_close = to_float(candles_fechados[-1]["close"])
    preco_ref_buy = ask if ask > 0 else ultimo_close
    preco_ref_sell = bid if bid > 0 else ultimo_close
    preco_referencia = preco_ref_buy if preco_ref_buy > 0 else ultimo_close

    fluxo = classificar_fluxo(
        preco=preco_referencia,
        indicadores=indicadores,
        candles_recentes=recentes
    )

    sinal = fluxo["sinal"]
    comentario = fluxo["comentario_base"]

    comentario_linhas = split_text_lines(comentario, 45, 3)

    if sinal == "SEM SINAL CLARO":
        return {
            "status": "sucesso",
            "sinal": "SEM SINAL CLARO",
            "ativo": symbol,
            "timeframe": timeframe,
            "entrada": "",
            "stop": "",
            "alvo": "",
            "rr": "",
            "confianca": fluxo["confianca"],
            "comentario": comentario,
            "comentario_l1": comentario_linhas[0],
            "comentario_l2": comentario_linhas[1],
            "comentario_l3": comentario_linhas[2],
            "tipo_cenario": fluxo["tipo_cenario"],
            "vies": fluxo["vies"],
            "modo_operacional": fluxo["modo_operacional"],
            "fatores": fluxo["fatores"],
            "mercado_status": fluxo["mercado_status"],
            "qualidade_volume": fluxo["qualidade_volume"],
            "confirmacao_volume": fluxo["confirmacao_volume"],
            "resposta_contextual": ""
        }

    preco_entrada = preco_ref_buy if sinal == "COMPRA" else preco_ref_sell

    niveis = calcular_stop_alvo(
        preco_entrada=preco_entrada,
        point=point,
        digits=digits,
        candles_fechados=candles_fechados,
        sinal=sinal
    )

    return {
        "status": "sucesso",
        "sinal": sinal,
        "ativo": symbol,
        "timeframe": timeframe,
        "entrada": format_price(niveis["entrada"], digits),
        "stop": format_price(niveis["stop"], digits),
        "alvo": format_price(niveis["alvo"], digits),
        "rr": "2:1",
        "confianca": fluxo["confianca"],
        "comentario": comentario,
        "comentario_l1": comentario_linhas[0],
        "comentario_l2": comentario_linhas[1],
        "comentario_l3": comentario_linhas[2],
        "tipo_cenario": fluxo["tipo_cenario"],
        "vies": fluxo["vies"],
        "modo_operacional": fluxo["modo_operacional"],
        "fatores": fluxo["fatores"],
        "mercado_status": fluxo["mercado_status"],
        "qualidade_volume": fluxo["qualidade_volume"],
        "confirmacao_volume": fluxo["confirmacao_volume"],
    }


@app.get("/")
async def home():
    return {"status": "online", "servico": "oracle_mt5_bridge", "versao": "3.7"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/analisar-mt5-completo")
async def analisar_mt5_completo(
    file: UploadFile = File(...),
    metadata_json: str = Form(...),
    pergunta: Optional[str] = Form(default="")
):
    _ = await file.read()

    metadata = json.loads(metadata_json)
    resultado = analisar_candles(metadata)

    if resultado.get("status") != "sucesso":
        return resultado

    digits = to_int(metadata.get("digits", 2), 2)

    entrada = to_float(resultado.get("entrada", 0)) if resultado.get("entrada", "") != "" else 0.0
    stop = to_float(resultado.get("stop", 0)) if resultado.get("stop", "") != "" else 0.0
    alvo = to_float(resultado.get("alvo", 0)) if resultado.get("alvo", "") != "" else 0.0
    vies = resultado.get("vies", "Neutro")
    modo_operacional = resultado.get("modo_operacional", "Aguardar")
    fatores = resultado.get("fatores", [])
    confianca = resultado.get("confianca", "50%")
    qualidade_volume = resultado.get("qualidade_volume", "Media")

    resposta_contextual = interpretar_pergunta(
        pergunta=pergunta or "",
        sinal=resultado.get("sinal", ""),
        entrada=entrada,
        stop=stop,
        alvo=alvo,
        digits=digits,
        vies=vies,
        modo_operacional=modo_operacional,
        fatores=fatores,
        confianca=confianca,
        qualidade_volume=qualidade_volume
    )

    contexto_linhas = split_text_lines(resposta_contextual, 45, 2)

    resultado["pergunta_usuario"] = (pergunta or "").strip()
    resultado["resposta_contextual"] = resposta_contextual
    resultado["contexto_l1"] = contexto_linhas[0]
    resultado["contexto_l2"] = contexto_linhas[1]

    return resultado
