import os
import json
import io
from PIL import Image
from typing import Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai

# Configuração da API do Gemini via Variável de Ambiente (Render)
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

app = FastAPI(title="Oracle MT5 Bridge IA", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def format_price(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"

@app.get("/")
async def home():
    return {"status": "online", "servico": "oracle_mt5_bridge", "versao": "4.0", "ia_engine": "gemini-1.5-pro"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/analisar-mt5-completo")
async def analisar_mt5_completo(
    file: UploadFile = File(...),
    metadata_json: str = Form(...),
    pergunta: Optional[str] = Form(default="")
):
    try:
        # 1. Carrega a Imagem (Screenshot do MT5)
        image_bytes = await file.read()
        chart_image = Image.open(io.BytesFile(image_bytes))

        # 2. Carrega os metadados do MT5 (Medias, VWAP, Candles)
        metadata = json.loads(metadata_json)
        digits = int(metadata.get("digits", 2))
        
        # 3. Se não houver chave de API configurada, avisa.
        if not api_key:
            return {"status": "erro", "mensagem": "GEMINI_API_KEY nao configurada no servidor."}

        # 4. PREPARANDO O CÉREBRO INSTITUCIONAL (PROMPT)
        system_instruction = """
        Você é um Engenheiro Quantitativo Sênior e Trader Institucional operando MetaTrader 5.
        Sua missão é cruzar a imagem do gráfico (Price Action/Rejeições) com os dados técnicos fornecidos no JSON (VWAP, EMA20, EMA200, Z-Score de Volume).
        
        Regras de Ouro:
        1. Opere com alvos lógicos de liquidez (VWAP, EMA200 ou Topos/Fundos), não apenas matemáticos.
        2. Entenda EXAUSTÃO: Se o preço está muito esticado da VWAP e deixa pavio longo, favoreça o Retorno à Média (Scalp Contra-Tendência).
        3. Nunca use acentos nas suas respostas de texto.
        4. Mantenha os textos curtos e impactantes.
        
        Responda EXATAMENTE neste formato JSON, sem crases markdown (```json), apenas o objeto puro:
        {
          "status": "sucesso",
          "sinal": "COMPRA", // ou VENDA ou SEM SINAL CLARO
          "tipo_cenario": "EXAUSTAO DE TOPO", // Analise macro curta
          "confianca": "85%", // Probabilidade de sucesso
          "vies": "Reversao Baixista", // Direção do fluxo
          "modo_operacional": "Scalp de Retorno",
          "mercado_status": "Alta Atividade",
          "qualidade_volume": "Forte",
          "confirmacao_volume": "Volume Apoia",
          "entrada": 4720.66, // float da entrada sugerida (0.0 se sem sinal)
          "stop": 4725.31, // float do stop tecnico de protecao
          "alvo": 4699.40, // float do alvo logico (ex: VWAP)
          "comentario_l1": "[ GATILHO ] Preco esticado e rejeicao forte no topo", // max 60 chars
          "comentario_l2": "[ STOP ] Protecao acima do pavio de rejeicao", // max 60 chars ou vazio
          "comentario_l3": "[ ALVO ] Ima magnetico na VWAP Diaria", // max 60 chars ou vazio
          "contexto_l1": "[ INFO ] O volume apoia a reversao por exaustao" // Responda a pergunta do usuario aqui, max 60 chars
        }
        """

        prompt_usuario = f"""
        Dados Técnicos do MT5:
        {json.dumps(metadata, indent=2)}

        Pergunta do Trader (Opcional): '{pergunta}'
        
        Por favor, analise a imagem e os dados, responda à pergunta no campo 'contexto_l1' e retorne APENAS o JSON válido.
        """

        # 5. CHAMADA PARA A API DO GEMINI 1.5 PRO
        model = genai.GenerativeModel('gemini-1.5-pro')
        
        response = model.generate_content([
            system_instruction,
            chart_image,
            prompt_usuario
        ])

        # 6. TRATAMENTO DA RESPOSTA JSON
        resposta_texto = response.text.strip()
        
        # Limpa o markdown caso o Gemini retorne com as crases (```json ... ```)
        if resposta_texto.startswith("```"):
            linhas = resposta_texto.split("\n")
            if len(linhas) > 2:
                resposta_texto = "\n".join(linhas[1:-1])

        # Converte a string do Gemini para um Dicionário Python
        resultado_ia = json.loads(resposta_texto)
        
        # Formata as saídas financeiras garantindo os dígitos corretos da corretora
        if resultado_ia.get("entrada", 0) > 0:
            resultado_ia["entrada"] = format_price(float(resultado_ia["entrada"]), digits)
            resultado_ia["stop"] = format_price(float(resultado_ia["stop"]), digits)
            resultado_ia["alvo"] = format_price(float(resultado_ia["alvo"]), digits)
        else:
            resultado_ia["entrada"] = ""
            resultado_ia["stop"] = ""
            resultado_ia["alvo"] = ""

        # Garante o ativo e timeframe na resposta final
        resultado_ia["ativo"] = metadata.get("symbol", "ATIVO")
        resultado_ia["timeframe"] = metadata.get("timeframe", "M15")

        return resultado_ia

    except Exception as e:
        return {
            "status": "erro",
            "mensagem": f"Erro interno na Bridge: {str(e)}"
        }
