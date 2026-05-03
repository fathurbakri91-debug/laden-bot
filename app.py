from flask import Flask, request, jsonify
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import difflib
import sys
from datetime import datetime, timedelta
import re
import time

app = Flask(__name__)

# ==========================================
# 1. KONFIGURASI & MEMORY
# ==========================================
FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN") or "ISI_TOKEN_DISINI"
STARSENDER_API_KEY = "0486d8c7-1bb2-479d-b97d-7c0a4dd09be0"
SHEET_ID = "1GMQ15xaMpJokmyNeckO6PRxtajiRV4yHB1U0wirRcGU"
MY_BOT_NAME_KEYWORDS = ["laden", "bot", "den", "min"] 

CACHE_DATA = []      
CACHE_TIMESTAMP = None
CACHE_DURATION = 900 
USER_SESSIONS = {}
PROCESSED_WEBHOOKS = {}

# --- VENDOR DATA (EDJS, MD, RAJAWALI) ---
CACHE_VENDOR = {'EDJS': {}, 'MD': {}, 'RAJAWALI': {}}
CACHE_VENDOR_TIMESTAMP = {'EDJS': None, 'MD': None, 'RAJAWALI': None}
VENDOR_SHEETS = ['EDJS', 'MD', 'RAJAWALI']

# ==========================================
# 2. DATABASE KATA (KAMUS & FILTER PINTAR)
# ==========================================
KAMUS_SINONIM = {
    "wipol": "jumbo", 
    "wypal": "jumbo", 
    "waipol": "jumbo", 
    "wypall": "jumbo", 
    "wipal": "jumbo", 
    "jumbo": "jumbo",
    "hendel": "handle", 
    "handel": "handle", 
    "sok": "shock", 
    "sox": "shock", 
    "breket": "bracket",
    "fiter": "filter", 
    "filtir": "filter", 
    "hos": "hose", 
    "hosing": "hose", 
    "sealtep": "seal tape",
    "ban": "tire", 
    "tyre": "tire", 
    "oli": "oil", 
    "lube": "oil", 
    "aki": "battery", 
    "accu": "battery",
    "baut": "bolt", 
    "mur": "nut", 
    "laher": "bearing", 
    "klem": "clamp", 
    "oring": "o-ring",
    "pipa": "pipe", 
    "paralon": "pipe", 
    "siku": "elbow", 
    "knie": "elbow", 
    "elbo": "elbow",
    "keran": "valve", 
    "kran": "valve", 
    "balp": "valve", 
    "sambungan": "fitting", 
    "konektor": "connector",
    "kabel": "cable", 
    "lampu": "lamp", 
    "bohlam": "bulb", 
    "las": "welding", 
    "kawat": "wire",
    "inci": "inch", 
    "inchi": "inch", 
    "cyl": "cylinder", 
    "silinder": "cylinder", 
    "fuse": "fuse",
    "fatigue": "fatique",  # Jika user ketik pakai G, cari di database pakai Q
    "fatique": "fatique",  # Jika user ketik pakai Q, tetap cari pakai Q
    # --- PENAMBAHAN SINONIM BARU (V.4.16) ---
    "rotari": "rotary",
    "cat": "paint",
    "jotun": "paint",
    "epodur": "paint",
    "putih": "white",
    "hitam": "black",
    "merah": "red",
    "kuning": "yellow",
    "hijau": "green",
    "biru": "blue",
    "abu": "gray",
    "abu-abu": "gray"
}

# --- MODE KETAT (STRICT MODE V.4.16) ---
CHATTY_WORDS = [
    "otomatis", "iso", "kah", "apakah", "gimana", "bagaimana", 
    "cara", "kenapa", "kok", "e", "nya", "sih", "dong", "tuh", "nih",
    # --- PENAMBAHAN FILTER BASA-BASI LAPANGAN (V.4.16) ---
    "dah", "udah", "dulu", "habiskan", "appv", "approve", "kt", "kita", 
    "nanti", "lagi"
]

# PENAMBAHAN FILTER ANTI-REPORT (V.4.14)
HARD_BLACKLIST = [
    "senggol", "colek", "biar", "dijawab", "jawab", "halo", "test", "tes", 
    "wkwk", "haha", "rajin", "pinter", "bodoh", "goblok", "lemot", "rusak", 
    "error", "lur", "gan", "mz", "lek", "maksudnya", "maksud", "bawa", 
    "balik", "wae", "fisik", "harga", "report", "daily", "taking", "siklus", 
    "http", "https", "bit.ly", "update terbaru"
]

COMMAND_WORDS = [
    "cek", "stok", "stock", "laden", "bot", "tanya", "carikan", "min", "den"
]

STOP_WORDS = [
    "stok", "stock", "ready", "cek", "cari", "tanya", "ada", "ga", "gak", 
    "nggak", "ya", "punya", "punyane", "brp", "berapa", "minta", "tolong", 
    "liat", "lihat", "bisa", "pak", "mas", "bang", "bu", "om", "lek", "bantu", 
    "mohon", "coba", "tolongin", "mba", "kak", "sist", "gan", "dibantu", "dulu",
    "laden", "bot", "den", "min", "admin", "nya", "yang", "mana", "tipe", 
    "type", "jenis", "model", "stoknya", "ut", "mtw", "komplit", "udh", "sudah", 
    "ini", "itu", "disini", "disitu"
]

GENERIC_ITEMS = ["baut", "bolt", "mur", "nut", "screw", "washer", "ring"]

# ==========================================
# 3. FUNGSI LOGIKA (CORE ENGINE)
# ==========================================

def log(message):
    print(f"[LOG] {message}", file=sys.stdout, flush=True)

def connect_google_sheet():
    json_creds = os.environ.get("GOOGLE_JSON_KEY")
    try:
        if json_creds:
            creds_dict = json.loads(json_creds)
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        elif os.path.exists("kunci_rahasia.json"):
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name("kunci_rahasia.json", scope)
        else: 
            return None
        return gspread.authorize(creds).open_by_key(SHEET_ID).sheet1
    except Exception as e:
        log(f"Error GSheet: {e}")
        return None

def get_vendor_data(sheet_name):
    global CACHE_VENDOR, CACHE_VENDOR_TIMESTAMP
    now = datetime.now()
    
    cached = CACHE_VENDOR.get(sheet_name, {})
    cached_ts = CACHE_VENDOR_TIMESTAMP.get(sheet_name)
    
    if cached and cached_ts and (now - cached_ts).total_seconds() < CACHE_DURATION:
        return cached
        
    log(f"🔄 Download Data {sheet_name} dari Cloud...")
    try:
        json_creds = os.environ.get("GOOGLE_JSON_KEY")
        if json_creds:
            creds_dict = json.loads(json_creds)
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        elif os.path.exists("kunci_rahasia.json"):
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name("kunci_rahasia.json", scope)
        else: 
            log("⚠️ Kunci rahasia JSON tidak ditemukan!")
            return cached

        client = gspread.authorize(creds)
        
        try:
            sheet = client.open_by_key(SHEET_ID).worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            log(f"⚠️ Tab bernama '{sheet_name}' TIDAK DITEMUKAN di Spreadsheet!")
            return cached
            
        raw_rows = sheet.get_all_values()
        
        if len(raw_rows) < 2:
            return cached
            
        headers = [str(h).strip().lower() for h in raw_rows[0]]
        
        idx_pn = next((i for i, h in enumerate(headers) if "material" in h and "desc" not in h), -1)
        idx_desc = next((i for i, h in enumerate(headers) if "desc" in h), -1)
        idx_qty = next((i for i, h in enumerate(headers) if "stock" in h or "qty" in h), -1)
        idx_loc = next((i for i, h in enumerate(headers) if "loc" in h or "plant" in h), -1)
        
        if idx_pn == -1 or idx_qty == -1:
            log(f"⚠️ Gagal menemukan kolom 'Material' atau 'Total Stock' di tab {sheet_name}.")
            return cached
            
        result = {}
        for row in raw_rows[1:]:
            if len(row) <= max(idx_pn, idx_qty): continue
            
            pn_raw = str(row[idx_pn]).strip()
            pn_norm = normalize_pn(pn_raw)
            loc = str(row[idx_loc]).strip() if idx_loc != -1 and len(row) > idx_loc else sheet_name
            
            try: 
                qty = float(re.sub(r'[^\d.]', '', str(row[idx_qty])))
            except ValueError: 
                qty = 0.0
                
            desc = str(row[idx_desc]).strip() if idx_desc != -1 and len(row) > idx_desc else pn_raw
            
            if pn_norm and pn_raw.lower() not in ["nan", "", "none"]:
                if pn_norm not in result:
                    result[pn_norm] = {'pn': pn_raw, 'desc': desc, 'details': {}}
                
                if loc not in result[pn_norm]['details']:
                    result[pn_norm]['details'][loc] = 0
                result[pn_norm]['details'][loc] += qty
                    
        CACHE_VENDOR[sheet_name] = result
        CACHE_VENDOR_TIMESTAMP[sheet_name] = now
        log(f"✅ {sheet_name} (Cloud) dimuat: {len(result)} item unik.")
        return result
        
    except Exception as e:
        log(f"💥 ERROR FATAL {sheet_name}: {e}")
        return cached


def sync_kamus():
    """Tarik data kamus dari worksheet KAMUS_BOT dan perbarui variabel global."""
    global KAMUS_SINONIM, STOP_WORDS, HARD_BLACKLIST, CHATTY_WORDS
    log("🔄 Sinkronisasi kamus dari Google Sheets...")
    try:
        json_creds = os.environ.get("GOOGLE_JSON_KEY")
        if json_creds:
            creds_dict = json.loads(json_creds)
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        elif os.path.exists("kunci_rahasia.json"):
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name("kunci_rahasia.json", scope)
        else:
            log("⚠️ Kunci rahasia JSON tidak ditemukan untuk sync kamus.")
            return

        client = gspread.authorize(creds)
        ws = client.open_by_key(SHEET_ID).worksheet("KAMUS_BOT")
        raw = ws.get_all_values()

        if len(raw) < 2:
            log("⚠️ Tab KAMUS_BOT kosong atau hanya header.")
            return

        new_sinonim = {}
        new_chatty = []
        new_blacklist = []
        new_stopword = []

        for row in raw[1:]:
            if len(row) < 2: continue
            kategori = str(row[0]).strip().upper()
            kata = str(row[1]).strip().lower()
            baku = str(row[2]).strip().lower() if len(row) > 2 else ""

            if kategori == "SINONIM" and kata and baku:
                new_sinonim[kata] = baku
            elif kategori == "CHATTY" and kata:
                new_chatty.append(kata)
            elif kategori == "BLACKLIST" and kata:
                new_blacklist.append(kata)
            elif kategori == "STOPWORD" and kata:
                new_stopword.append(kata)

        KAMUS_SINONIM = new_sinonim
        CHATTY_WORDS = new_chatty
        HARD_BLACKLIST = new_blacklist
        STOP_WORDS = new_stopword

        log(f"✅ Kamus disinkronisasi: {len(new_sinonim)} sinonim, {len(new_chatty)} chatty, {len(new_blacklist)} blacklist, {len(new_stopword)} stopword.")
    except Exception as e:
        log(f"💥 Gagal sync kamus: {e}")

def clean_text(text):
    if text is None: return ""
    t = str(text).strip()
    return "" if t.lower() in ["nan", "none", "null", "-", "0", ""] else t

def normalize_pn(text):
    """Menghapus semua spasi dan simbol, menyisakan huruf dan angka"""
    if text is None: return ""
    t = str(text).lower()
    t = re.sub(r'[^a-z0-9]', '', t) 
    return t.replace('o', '0')

def is_sap_document(word):
    clean_w = re.sub(r'[^0-9]', '', word)
    return len(clean_w) == 10 and clean_w.startswith(("10", "22", "24", "26"))

def smart_clean_keyword(text):
    if not text or text.strip().startswith(">"): return "" 
    text_clean = text.replace("?", "").replace("!", "").replace(",", " ").replace(".", " ").replace(":", "") 
    text_clean = re.sub(r'@[a-zA-Z0-9]+', '', text_clean)
    words = text_clean.split()
    final_words = []
    
    for w in words:
        if w.lower() not in STOP_WORDS and not is_sap_document(w):
            final_words.append(w)
            
    return " ".join(final_words)

def get_data_lightweight():
    global CACHE_DATA, CACHE_TIMESTAMP
    now = datetime.now()
    if CACHE_DATA and CACHE_TIMESTAMP and (now - CACHE_TIMESTAMP).total_seconds() < CACHE_DURATION:
        return CACHE_DATA

    log("🔄 Download Data Baru...")
    try:
        sheet = connect_google_sheet()
        if not sheet: return []
        raw_rows = sheet.get_all_values()
        if len(raw_rows) < 2: return []
        
        headers = [h.strip().lower() for h in raw_rows[0]]
        
        idx = {
            'desc': next((i for i, h in enumerate(headers) if "desc" in h), -1),
            'mat': next((i for i, h in enumerate(headers) if "material" in h and "desc" not in h), -1),
            'qty': next((i for i, h in enumerate(headers) if any(x in h for x in ["total", "stock", "unrestricted"])), -1),
            'plant': next((i for i, h in enumerate(headers) if "plant" in h), -1),
            'bin': next((i for i, h in enumerate(headers) if "bin" in h), -1),
            'sloc': next((i for i, h in enumerate(headers) if any(x in h for x in ["location", "sloc", "lgort"])), -1),
            'spec': next((i for i, h in enumerate(headers) if "procurement" in h), -1),
            'upd': next((i for i, h in enumerate(headers) if "update" in h), -1),
            'batch': next((i for i, h in enumerate(headers) if "batch" in h), -1),
            'val_class': next((i for i, h in enumerate(headers) if "valuation" in h), -1)
        }

        clean_data = []
        for row in raw_rows[1:]:
            try: qty_val = float(re.sub(r'[^\d.]', '', str(row[idx['qty']])))
            except: qty_val = 0.0
                
            clean_data.append({
                'desc': str(row[idx['desc']]).strip() if idx['desc'] != -1 and len(row) > idx['desc'] else "-",
                'mat': str(row[idx['mat']]).strip() if idx['mat'] != -1 and len(row) > idx['mat'] else "-",
                'qty': qty_val,
                'plant': str(row[idx['plant']]).strip() if idx['plant'] != -1 and len(row) > idx['plant'] else "-",
                'bin': str(row[idx['bin']]).strip() if idx['bin'] != -1 and len(row) > idx['bin'] else "-",
                'sloc': str(row[idx['sloc']]).strip() if idx['sloc'] != -1 and len(row) > idx['sloc'] else "-",
                'spec': clean_text(row[idx['spec']]) if idx['spec'] != -1 and len(row) > idx['spec'] else "",
                'last_update': clean_text(row[idx['upd']]) if idx['upd'] != -1 and len(row) > idx['upd'] else "",
                'batch': clean_text(row[idx['batch']]) if idx['batch'] != -1 and len(row) > idx['batch'] else "",
                'val_class': clean_text(row[idx['val_class']]) if idx['val_class'] != -1 and len(row) > idx['val_class'] else ""
            })
            
        CACHE_DATA = clean_data
        CACHE_TIMESTAMP = now
        log(f"✅ Berhasil Cache {len(clean_data)} item.")
        return CACHE_DATA
    except Exception as e: 
        log(f"⚠️ Gagal: {e}")
        return CACHE_DATA

def cari_stok(raw_keyword, page=0, is_batch=False):
    data = get_data_lightweight()
    if not data: return "⚠️ Gagal mengambil data server."
    
    clean_k = smart_clean_keyword(raw_keyword)
    if not clean_k or len(clean_k) < 2: return ""

    is_short_num = clean_k.replace(" ", "").isdigit() and len(clean_k.replace(" ", "")) < 6
    
    original_words = clean_k.lower().split()
    translated_words = [KAMUS_SINONIM.get(k, k) for k in original_words]
    kw_search = clean_k.lower() 
    kw_search_norm = normalize_pn(kw_search) 
    translated_search = " ".join(translated_words)
    trans_norm = normalize_pn(translated_search).lstrip('0')

    # PENCARIAN DI SAP
    hasil = []
    for item in data:
        # Normalisasi dengan membuang nol di depan (lstrip)
        mat_norm = normalize_pn(item['mat']).lstrip('0')
        kw_norm = kw_search_norm.lstrip('0')
        
        if is_short_num:
            # Exact Match untuk angka pendek tanpa peduli nol di depan
            if kw_norm and (kw_norm == mat_norm or trans_norm == mat_norm):
                hasil.append(item)
        else:
            # DUAL-WORD MATCHING: Cek kata asli ATAU kata terjemahan
            match_desc = all( (original_words[i] in item['desc'].lower() or translated_words[i] in item['desc'].lower()) for i in range(len(original_words)) )
            match_mat = kw_search in item['mat'].lower() or translated_search in item['mat'].lower()
            match_mat_norm = (kw_norm in mat_norm if kw_norm else False) or (trans_norm in mat_norm if trans_norm else False)
            
            if match_desc or match_mat or match_mat_norm:
                hasil.append(item)

    # PENCARIAN DI VENDOR (EDJS, MD, RAJAWALI)
    vendor_matches = []
    all_vendor_data = {} # Gabungkan semua data vendor untuk referensi display nanti
    
    for v_sheet in VENDOR_SHEETS:
        v_data = get_vendor_data(v_sheet)
        all_vendor_data[v_sheet] = v_data
        
        for norm_pn, val in v_data.items():
            mat_norm = norm_pn.lstrip('0')
            kw_norm = kw_search_norm.lstrip('0')
            
            if is_short_num:
                if kw_norm and (kw_norm == mat_norm or trans_norm == mat_norm):
                    vendor_matches.append(val)
            else:
                match_desc = all( (original_words[i] in str(val.get('desc', '')).lower() or translated_words[i] in str(val.get('desc', '')).lower()) for i in range(len(original_words)) )
                match_pn = kw_search in val['pn'].lower() or translated_search in val['pn'].lower()
                match_pn_norm = (kw_norm in mat_norm if kw_norm else False) or (trans_norm in mat_norm if trans_norm else False)
                
                if match_desc or match_pn or match_pn_norm:
                    vendor_matches.append(val)

    unik_items = []
    seen = set()
    for x in hasil:
        key = (x['mat'], x['batch'])
        if key not in seen:
            unik_items.append(key)
            seen.add(key)

    for val in vendor_matches:
        norm_val_pn = normalize_pn(val['pn'])
        pn_in_sap = any(normalize_pn(x['mat']) == norm_val_pn for x in hasil)
        
        if not pn_in_sap:
            key = (val['pn'], "")
            if key not in seen:
                unik_items.append(key)
                seen.add(key)

    if not unik_items:
        if is_short_num:
            return "" # Diam jika angka pendek (misal "1000") tidak ada exact match
        if not any(char.isdigit() for char in clean_k) and len(clean_k.replace(" ", "")) < 4:
            return "" # Bot diam (Silent Mode huruf pendek)
        return f"🙏 Stok *'{clean_k}'* boten wonten."

    total_items = len(unik_items)
    ITEMS_PER_PAGE = 10
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    if page >= total_pages and page > 0: return "⚠️ Halaman terakhir."

    start = page * ITEMS_PER_PAGE
    current_items = unik_items[:10] if is_batch else unik_items[start:start + ITEMS_PER_PAGE]

    pesan = f"🙏 *Laden jawab ya...*\nPencarian: {kw_search.upper()} ({total_items} items)\n" if not is_batch else ""
    if not is_batch: pesan += f"📖 Halaman {page+1} dari {total_pages}\n------------------\n"

    for mat_id, b_val in current_items:
        grup = [x for x in hasil if x['mat'] == mat_id and x['batch'] == b_val]
        
        # Gabungkan stok dari semua vendor untuk mat_id ini
        vendor_details_combined = {}
        vendor_desc_fallback = "Item Vendor"
        for v_sheet in VENDOR_SHEETS:
            v_qty = all_vendor_data[v_sheet].get(normalize_pn(mat_id))
            if v_qty:
                vendor_desc_fallback = v_qty['desc']
                for loc, qty in v_qty['details'].items():
                    vendor_details_combined[loc] = vendor_details_combined.get(loc, 0) + qty

        if not grup and not vendor_details_combined: continue

        if grup:
            first = grup[0]
            desc_display = first['desc']
            batch_label = f" ({b_val})" if b_val else ""
            spec_label = f" ({first['spec']})" if first['spec'] else ""
            val_label = f" ({first['val_class']})" if first.get('val_class') else ""
        else:
            desc_display = vendor_desc_fallback
            batch_label = ""
            spec_label = ""
            val_label = ""

        pesan += f"*{desc_display}{batch_label}*\n"
        pesan += f"Mat : {mat_id}{spec_label}{val_label}\n"

        if grup:
            SLOC_KOSONG = {"-", "", "nan", "none", "null"}
            sloc_set = set()
            for x in grup:
                s = x['sloc'].strip().upper() if x['sloc'] else ""
                if s and s not in SLOC_KOSONG:
                    sloc_set.add(s)
            slocs = sorted(sloc_set)

            total_internal = int(sum(x['qty'] for x in grup
                                     if '40AI' in x['plant'].upper() or '40AJ' in x['plant'].upper()))

            if not slocs or total_internal == 0:
                pesan += "SAP - 0\n"
            else:
                for sloc in slocs:
                    sloc_grup = [x for x in grup if x['sloc'].strip().upper() == sloc]

                    m_items = [x for x in sloc_grup if '40AI' in x['plant'].upper()]
                    h_items = [x for x in sloc_grup if '40AJ' in x['plant'].upper()]

                    m_qty = int(sum(x['qty'] for x in m_items))
                    h_qty = int(sum(x['qty'] for x in h_items))

                    m_bins_list = sorted(set(clean_text(x['bin']) for x in m_items if clean_text(x['bin'])))
                    h_bins_list = sorted(set(clean_text(x['bin']) for x in h_items if clean_text(x['bin'])))

                    m_bin = ", ".join(m_bins_list) if m_bins_list else "-"
                    h_bin = ", ".join(h_bins_list) if h_bins_list else "-"

                    m_str = f"{m_qty} ({m_bin})" if m_bin != "-" else f"{m_qty} (-)"
                    h_str = f"{h_qty} ({h_bin})" if h_bin != "-" else f"{h_qty} (-)"

                    pesan += f"{sloc} - 40AI : {m_str} | 40AJ : {h_str}\n"
        else:
            pesan += "SAP - 0\n"

        if vendor_details_combined:
            for loc, qty in vendor_details_combined.items():
                pesan += f"{loc} - {int(qty)}\n"

        pesan += "------------------\n"

    if not is_batch:
        if page < total_pages - 1: pesan += "👇 _Ketik *Next* untuk lanjut._\n"
        pesan += f"🕒 {data[0]['last_update'] if data and 'last_update' in data[0] else 'Updated: -'}"

    return pesan

# ==========================================
# 4. PUSAT PEMROSESAN (STRICT LOGIC ENGINE V.4.16)
# ==========================================

def proses_pesan(message, sender_id):
    if not message: return None
    
    # Jika ada mention/tag manusia (simbol @), asumsikan pesan bukan untuk bot
    if "@" in message and not any(bot_name in message.lower() for bot_name in ["@laden", "@bot"]):
        return None
        
    msg_l = message.lower().strip()
    words = msg_l.split()
    
    if msg_l in ["lagi", "next", "lanjut", "berikutnya"]:
        if sender_id in USER_SESSIONS:
            s = USER_SESSIONS[sender_id]
            s['page'] += 1
            return cari_stok(s['keyword'], page=s['page'])
    
    has_part_number = bool(re.search(r'\d+-[a-zA-Z0-9-]+', msg_l))
    is_blacklisted = any(w in msg_l for w in HARD_BLACKLIST)
    is_chatty = any(w in words for w in CHATTY_WORDS)
    has_command = any(cmd in words for cmd in COMMAND_WORDS)
    
    trigger_found = False
    
    if has_command:
        # Buat variabel pembantu untuk mengecek validitas Multi-Item (Enter)
        segments = msg_l.split('\n')
        is_valid_multi = len(segments) > 1 and all(len(seg.split()) <= 6 for seg in segments)

        if is_blacklisted:
            trigger_found = False
        elif has_part_number or is_valid_multi:
            # Lolos mutlak jika ada part number ATAU format enter yang valid
            trigger_found = True 
        elif is_chatty:
            # Blokir jika obrolan biasa (lebih dari 6 kata)
            trigger_found = False
        elif len(words) <= 6:
            # Lolos untuk pencarian item tunggal di bawah 6 kata
            trigger_found = True
            
    if trigger_found:
        clean_msg = re.sub(r'@[a-zA-Z0-9_]+', '', message)
        
        for t in ["tanya laden", "tanya den", "cek laden", "cek den", "tanya stok", "cek stok", "tolong cek stok", "cek", "stok", "stock", "laden", "bot", "min", "den", "tolong"]:
            clean_msg = re.sub(r'\b'+t+r'\b', '', clean_msg, flags=re.IGNORECASE)
        
        raw_lines = re.split(r'[\n,]', clean_msg)
        valid = [smart_clean_keyword(l) for l in raw_lines if len(smart_clean_keyword(l).strip()) > 1]
        
        if not valid: return None
        
        is_b = len(valid) > 1
        if not is_b: 
            USER_SESSIONS[sender_id] = {'keyword': valid[0], 'page': 0}
        
        reply = "📦 *Hasil Multi-Item:*\n\n" if is_b else ""
        for kw in valid: 
            reply += cari_stok(kw, page=0, is_batch=is_b)
            
        return reply
        
    return None

# ==========================================
# 5. SERVER ENDPOINTS
# ==========================================

@app.route('/', methods=['GET'])
def home(): 
    return "LADEN V.4.16 ACTIVE"

@app.route('/test', methods=['POST'])
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    log(f"Raw Webhook Data: {data}")
    if not data: 
        return jsonify({"reply": ""}), 400
        
    msg = data.get('message') or data.get('text') or data.get('pesan')
    sender = data.get('sender') or data.get('from') or data.get('pengirim')
    member = data.get('member') or data.get('participant') or ""

    if 'data' in data and isinstance(data['data'], dict):
        if not msg: msg = data['data'].get('message') or data['data'].get('text')
        if not sender: sender = data['data'].get('sender') or data['data'].get('from')
        if not member: member = data['data'].get('member') or data['data'].get('participant') or ""

    sender = sender or "Local"
    actual_user = member if member else sender
    
    # 1. DEBOUNCE LOGIC (Dipindah ke atas untuk mencegah Phantom Pagination)
    current_time = time.time()
    msg_signature = f"{sender}_{msg}"

    if msg_signature in PROCESSED_WEBHOOKS:
        if current_time - PROCESSED_WEBHOOKS[msg_signature] < 3: # Turunkan jadi 3 detik
            return jsonify({"reply": "Duplicate ignored"}), 200
            
    PROCESSED_WEBHOOKS[msg_signature] = current_time
    
    jawaban = None
    if msg and msg.strip().lower() == "/updatekamus":
        if "6281213223016" in actual_user or "081213223016" in actual_user:
            sync_kamus()
            jawaban = "✅ Kamus berhasil disinkronisasi dari Google Sheets!"
        else:
            jawaban = "⚠️ Akses Ditolak.\n\nFitur ini hanya bisa dilakukan oleh Creator.\nSilakan hubungi Creator jika ingin menambahkan sesuatu.\nWA: 081213223016"
    else:
        jawaban = proses_pesan(msg, sender)
    
    if jawaban:
        # if FONNTE_TOKEN and "ISI_TOKEN" not in FONNTE_TOKEN:
        #     try:
        #         requests.post(
        #             "https://api.fonnte.com/send", 
        #             headers={"Authorization": FONNTE_TOKEN}, 
        #             data={"target": sender, "message": jawaban},
        #             timeout=5
        #         )
        #     except Exception as e:
        #         log(f"Fonnte Send Error: {e}")
                
        if sender == "Local":
            log("Pesan tidak diteruskan ke Starsender karena nomor pengirim tidak ditemukan (Local).")
        elif STARSENDER_API_KEY and "PASTE_API_KEY_DISINI" not in STARSENDER_API_KEY:
            try:
                requests.post(
                    "https://api.starsender.online/api/send",
                    headers={
                        "Content-Type": "application/json", 
                        "Authorization": STARSENDER_API_KEY
                    },
                    json={
                        "messageType": "text",
                        "to": sender,
                        "body": jawaban
                    },
                    timeout=5
                )
            except Exception as e:
                log(f"Starsender Send Error: {e}")
                
        return jsonify({"reply": jawaban}), 200
        
    return jsonify({"reply": ""}), 200

# Jalankan sync_kamus otomatis saat di-load oleh Render/Gunicorn
sync_kamus()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
