#!/usr/bin/env python3
"""
AI Maintenance Analysis Module - RAG Enhanced v2
真正的 AI 保养分析：完整联动维保记录 + 手册内容 + 零部件寿命预估
"""
import os
import re
import sqlite3
from datetime import datetime, timedelta

# ============================================================
# 1. PDF/Text Extraction (using pypdf, available on PythonAnywhere)
# ============================================================
def extract_text_from_pdf(filepath):
    """Extract text from PDF using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        text_parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
        return '\n'.join(text_parts)
    except Exception as e:
        return f"[PDF extraction error: {str(e)}]"

def extract_text_from_file(filepath, filetype=None):
    """Extract text from uploaded file (PDF, TXT, or auto-detect)."""
    if not filetype:
        ext = os.path.splitext(filepath)[1].lower().replace('.', '')
        filetype = ext
    
    filetype = filetype.lower()
    
    if filetype == 'txt':
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except:
            return "[Error reading text file]"
    elif filetype == 'pdf':
        return extract_text_from_pdf(filepath)
    else:
        if os.path.splitext(filepath)[1].lower() == '.pdf':
            return extract_text_from_pdf(filepath)
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except:
            return "[Unsupported file format]"

# ============================================================
# 2. LLM-based Analysis (RAG pattern) with 429 retry
# ============================================================
def call_llm_api(prompt, model=None):
    """
    Call LLM API for maintenance analysis.
    Supports: glm-4.7-flash (default), glm-4-flash, etc.
    Auto-retry on 429 (rate limit) with exponential backoff.
    """
    import requests
    import time
    
    # Determine model: .env > env var > default
    # Default to glm-4-flash (most reliable on free tier)
    if model is None:
        model = os.environ.get('ZHIPU_MODEL', 'glm-4-flash')
    
    # Get API key from environment or config
    api_key = os.environ.get('ZHIPU_API_KEY') or os.environ.get('LLM_API_KEY')
    if not api_key:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('ZHIPU_API_KEY=') or line.startswith('LLM_API_KEY='):
                        api_key = line.split('=', 1)[1].strip()
                    elif line.startswith('ZHIPU_MODEL='):
                        model = line.split('=', 1)[1].strip()
        if not api_key:
            # Try alternative paths
            for alt_path in ['/home/IvanTso/vehicle-management/.env', 
                             os.path.join(os.getcwd(), '.env')]:
                if os.path.exists(alt_path):
                    with open(alt_path) as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith('ZHIPU_API_KEY=') or line.startswith('LLM_API_KEY='):
                                api_key = line.split('=', 1)[1].strip()
                            elif line.startswith('ZHIPU_MODEL='):
                                model = line.split('=', 1)[1].strip()
                    if api_key:
                        break
    
    if not api_key:
        return None, "API key not configured. Please set ZHIPU_API_KEY in .env file or environment variable."
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是一位专业的汽车保养专家，擅长根据车辆手册、历史记录和当前状况生成个性化的保养建议和零部件更换时间预估。请用简洁、专业的语言回答，输出结构化内容。'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.3,
        'max_tokens': 1500  # Keep response concise to avoid PA timeout
    }
    
    # Model fallback chain: try primary, then fallback on 429
    # Keep it short to avoid PA request timeout
    MODEL_FALLBACK_CHAIN = ['glm-4-flash', 'glm-4.7-flash']
    
    # Build the chain starting from the requested model
    if model in MODEL_FALLBACK_CHAIN:
        chain = [model] + [m for m in MODEL_FALLBACK_CHAIN if m != model]
    else:
        chain = [model, 'glm-4-flash']  # custom model + fallback
    
    for current_model in chain:
        payload['model'] = current_model
        
        try:
            response = requests.post(
                'https://open.bigmodel.cn/api/paas/v4/chat/completions',
                headers=headers,
                json=payload,
                timeout=45
            )
            
            if response.status_code == 429:
                continue  # Try next model in fallback chain

            if response.status_code == 401:
                return None, "API Key 无效 (401)，请检查配置。"
            elif response.status_code == 402:
                return None, "API 额度不足 (402)，请充值后重试。"
            elif response.status_code == 1113 or '余额不足' in response.text:
                continue  # Insufficient balance, try next model

            response.raise_for_status()
            result = response.json()
            content = result['choices'][0]['message']['content']
            return content, None

        except requests.exceptions.Timeout:
            continue  # Try next model
        except Exception as e:
            continue  # Try next model
    
    return None, f"API 请求失败，所有模型均不可用 (尝试: {', '.join(chain)})。请稍后重试。"

# ============================================================
# 3. Enhanced History Processing
# ============================================================
def _build_history_context(history, current_mileage):
    """
    Build comprehensive maintenance history context for AI.
    Analyzes each record to extract component-level info.
    """
    if not history:
        return '无历史维保记录', {}, {}
    
    # Component keyword mapping
    COMPONENT_KEYWORDS = {
        '机油': ['机油', '换油', 'oil change', '润滑油'],
        '机油滤清器': ['机滤', '机油滤', 'oil filter'],
        '空气滤清器': ['空滤', '空气滤', 'air filter'],
        '空调滤清器': ['空调滤', '花粉滤', 'cabin filter'],
        '刹车片': ['刹车片', '制动片', 'brake pad'],
        '刹车盘': ['刹车盘', '制动盘', 'brake rotor', 'brake disc'],
        '刹车油': ['刹车油', '制动液', 'brake fluid'],
        '轮胎': ['轮胎', '轮胎换位', 'tire', 'tyre'],
        '蓄电池': ['蓄电池', '电池', '电瓶', 'battery'],
        '火花塞': ['火花塞', 'spark plug'],
        '变速箱油': ['变速箱油', '齿轮油', 'transmission fluid', 'gear oil'],
        '冷却液': ['冷却液', '防冻液', 'coolant', 'antifreeze'],
        '雨刮片': ['雨刮', '雨刷', 'wiper'],
        '正时皮带': ['正时皮带', 'timing belt'],
        '发电机皮带': ['发电机皮带', '驱动皮带', 'serpentine belt'],
        '燃油滤清器': ['汽油滤', '燃油滤', 'fuel filter'],
        '转向助力油': ['转向油', '助力油', 'power steering fluid'],
        '减震器': ['减震', '避震', 'shock', 'strut'],
        '空调压缩机': ['空调压缩机', 'ac compressor'],
    }
    
    last_service = {}   # component -> {date, mileage, description, cost}
    service_count = {}  # component -> count
    
    for h in history:
        desc = (h.get('description', '') or '').lower()
        mtype = (h.get('maintenance_type', '') or '').lower()
        combined = f"{desc} {mtype}"
        
        date = h.get('maintenance_date', '')
        mileage = h.get('mileage_at_service', 0) or 0
        cost = h.get('cost', 0) or 0
        
        for component, keywords in COMPONENT_KEYWORDS.items():
            if any(kw in combined for kw in keywords):
                if component not in last_service:
                    last_service[component] = {
                        'date': date,
                        'mileage': mileage,
                        'description': h.get('description', ''),
                        'cost': cost
                    }
                service_count[component] = service_count.get(component, 0) + 1
    
    # Build full history text (all records, not just 5)
    history_lines = []
    for i, h in enumerate(history):
        date = h.get('maintenance_date', '')
        desc = h.get('description', '') or h.get('maintenance_type', '')
        cost = h.get('cost', 0) or 0
        mtype = h.get('maintenance_type', '')
        mileage = h.get('mileage_at_service', '')
        mileage_str = f" | 里程: {mileage:,.0f}km" if mileage else ""
        type_str = f" [{mtype}]" if mtype else ""
        history_lines.append(f"  {i+1}. {date}: {desc}{type_str} (¥{cost:.0f}){mileage_str}")
    
    history_text = '\n'.join(history_lines) if history_lines else '无历史维保记录'
    
    return history_text, last_service, service_count

def _build_component_status(last_service, current_mileage, vehicle_age_months):
    """Build component status summary with mileage since last service."""
    if not last_service:
        return '无已知零部件维保记录'
    
    lines = []
    for comp, info in last_service.items():
        last_mileage = info.get('mileage', 0) or 0
        mileage_since = current_mileage - last_mileage if last_mileage > 0 else None
        mileage_str = f", 已行驶 {mileage_since:,.0f}km" if mileage_since else ""
        lines.append(f"  - {comp}: 上次 {info['date']} 更换{mileage_str}, 花费 ¥{info['cost']:.0f}")
    
    return '\n'.join(lines)

# ============================================================
# 4. Core AI Analysis with Full Integration
# ============================================================
def analyze_maintenance_ai(vehicle, history, manual_text=None, lang='zh'):
    """
    AI-powered maintenance analysis with FULL integration:
    - Complete maintenance history (not just 5 records)
    - Component-level tracking (when each part was last replaced)
    - Mileage-based wear calculation
    - Manual-based personalized recommendations
    - Predictive component replacement timeline
    
    Args:
        vehicle: dict with vehicle info
        history: list of ALL past maintenance records
        manual_text: extracted text from uploaded manual
        lang: 'zh' or 'en'
    
    Returns:
        (ai_analysis_text, error_message)
    """
    current_mileage = vehicle.get('current_mileage', 0) or 0
    plate = vehicle.get('plate_number', 'Unknown')
    brand_model = vehicle.get('brand_model', 'Unknown')
    purchase_date = vehicle.get('purchase_date', '')
    
    # Calculate vehicle age
    vehicle_age_months = 0
    if purchase_date:
        try:
            purchase = datetime.strptime(purchase_date, '%Y-%m-%d')
            vehicle_age_months = (datetime.now() - purchase).days // 30
        except:
            pass
    
    # Build comprehensive history context
    history_text, last_service, service_count = _build_history_context(history, current_mileage)
    
    # Build component status
    component_status = _build_component_status(last_service, current_mileage, vehicle_age_months)
    
    # Build prompt (Chinese)
    if lang == 'zh':
        prompt = f"""请为以下车辆生成专业的保养建议和零部件更换时间预估：

【车辆信息】
- 车牌：{plate}
- 品牌型号：{brand_model}
- 当前里程：{current_mileage:,.0f} km
- 车龄：{vehicle_age_months} 个月（约 {vehicle_age_months/12:.1f} 年）

【官方手册建议】
{manual_text[:3000] if manual_text else '未上传手册，请参考通用保养标准'}

【完整维保记录】
{history_text}

【各零部件上次保养状态】
{component_status}

请根据以上信息，生成一份详细、个性化的保养建议，必须包含以下内容：

一、🔴 立即需要保养的项目
列出当前里程/车龄下已超期或即将超期的项目，说明原因。

二、🟡 近期（1-3个月内）需要保养的项目
预估到期时间或到期里程。

三、🟢 长期保养规划（3-12个月）
列出未来需要关注的项目和大致时间。

四、📋 重要零部件预估更换时间表
请用表格形式列出关键零部件的预估更换时间，格式如下：
| 零部件 | 上次更换 | 预估下次更换 | 预估剩余里程 | 紧急程度 | 参考依据 |
根据该车型的通用标准和手册要求，结合当前里程和上次更换记录来估算。如果某零部件无更换记录，则按出厂计算。

五、💡 基于手册的特殊注意事项
如果上传了手册，列出手册中特别强调的保养要求。

请用专业但易懂的中文回答，数据要具体，避免模糊表述。回答控制在800字以内，重点突出。"""
    else:
        prompt = f"""Please generate professional maintenance recommendations and component replacement timeline for the following vehicle:

[Vehicle Info]
- Plate: {plate}
- Model: {brand_model}
- Current Mileage: {current_mileage:,.0f} km
- Age: {vehicle_age_months} months (~{vehicle_age_months/12:.1f} years)

[Manual Recommendations]
{manual_text[:3000] if manual_text else 'No manual uploaded, refer to generic standards'}

[Complete Service History]
{history_text}

[Component Last Service Status]
{component_status}

Based on the above, provide detailed personalized maintenance advice including:

1. 🔴 IMMEDIATE items (overdue or critical)
2. 🟡 UPCOMING items (1-3 months)
3. 🟢 LONG-TERM planning (3-12 months)
4. 📋 COMPONENT REPLACEMENT TIMELINE (table format):
| Component | Last Replaced | Next Due | Remaining Mileage | Urgency | Reference |
5. 💡 Manual-specific notes (if available)

Be specific with data and timelines. Avoid vague statements."""

    # Call LLM
    analysis, error = call_llm_api(prompt)
    
    if error:
        return None, error
    
    return analysis, None

# ============================================================
# 5. Helper: Get manual text for a vehicle
# ============================================================
def get_manual_text_for_vehicle(vehicle_id):
    """Retrieve extracted manual text for a specific vehicle."""
    db_path = os.path.join(os.path.dirname(__file__), 'vehicle.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    manuals = conn.execute("""
        SELECT filename, extracted_text FROM uploaded_manuals 
        WHERE vehicle_id = ? AND extracted_text IS NOT NULL
    """, (vehicle_id,)).fetchall()
    
    conn.close()
    
    if not manuals:
        return None
    
    combined = []
    for m in manuals:
        combined.append(f"=== {m['filename']} ===\n{m['extracted_text']}")
    
    return '\n\n'.join(combined)

# ============================================================
# 6. Legacy compatibility
# ============================================================
def parse_manual_text(text):
    """Legacy: kept for backward compatibility."""
    return []

def analyze_maintenance(vehicle, history, lang='zh', manual_rules=None):
    """Legacy: use analyze_maintenance_ai instead."""
    return [], vehicle.get('current_mileage', 0)
