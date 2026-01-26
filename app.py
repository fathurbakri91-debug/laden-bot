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

app = Flask(__name__)

# --- CONFIG ---
FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN") 
SHEET_ID = "1GMQ15xaMpJokmyNeckO6PRxtajiRV4yHB1U0wirRcGU"
MY_BOT_NAME_KEYWORDS = ["laden", "bot", "den", "min"] 

# --- GLOBAL MEMORY ---
CACHE_DATA = []      
CACHE_TIMESTAMP = None
CACHE_DURATION = 900 
USER_SESSIONS = {} 

# --- KAMUS PINTAR ---
KAMUS_SINONIM = {
    "wipol": "wipers", "wypal": "wipers", "waipol": "wipers", 
    "wypall": "wipers", "wipal": "wipers", "jumbo": "wipers",
    "hendel": "handle", "handel": "handle",
    "sok": "shock", "sox": "shock",
    "breket": "bracket", "briket": "bracket",
    "fiter": "filter", "filtir": "filter",
    "hos": "hose", "hosing": "hose",
    "sealtep": "seal tape", "siltep": "seal tape",
    "ban": "tire", "tyre": "tire", 
    "oli": "oil", "lube": "oil",
    "aki": "battery", "accu": "battery",
    "baut": "bolt", "mur": "nut", 
    "laher": "bearing", "klem": "clamp", 
    "oring": "o-ring", "o ring": "o-ring",
    "pipa": "pipe", "paralon": "pipe",
    "siku": "elbow", "knie": "elbow", "elbo": "elbow",
    "keran": "valve", "kran": "valve", "balp": "valve",
    "sambungan": "fitting", "konektor": "connector",
    "kabel": "cable",
    "lampu": "lamp", "bohlam": "bulb",
    "las": "welding", "kawat": "wire",
    "inci": "inch", "inchi": "inch",
    "cyl": "cylinder", "silinder": "cylinder",
    "fuse": "fuse", "sikring": "fuse", "sekring": "fuse"
}

# --- KONFIGURASI FILTER KATA (V.32 ANTI SPAM UPGRADE) ---
TRIGGERS_LAMA = ["tanya laden", "tanya den", "cek laden", "cek den", "tanya stok", "cek stok"]
UNIVERSAL_KEYWORDS = ["stok", "stock", "cek"]

# 1. HARD BLACKLIST (PASTI DIAM)
# Tambahan: "maksudnya" (untuk kasus 'ini maksudnya pak de umam')
HARD_BLACKLIST = [
    "senggol", "colek", "biar", "dulu", "dijawab", 
    "jawab", "cuy", "woi", "halo", "test", "tes", "wkwk", "haha",
    "rajin", "pinter", "bodoh", "goblok", "lemot", "rusak", "error", 
    "lur", "gan", "mz", "lek", "maksudnya", "dibantu", "bantu"
]

# 2. SOFT BLACKLIST (Boleh lewat KALO ada kata 'Stok' di AWAL kalimat)
SOFT_BLACKLIST = [
    "pak", "bu", "om", "kah", "kok", "sih", "dong", "tuh", "nih", 
    "ready", "aman", "ada", "bang", "mas", "mba", "kak", "gantine"
]

# 3. OPERATIONAL
OPERATIONAL_WORDS = [
    "lambung", "cn", "sn", "hm", "km", "engine", 
    "unit", "dt", "hd", "lv", "gd", "dozer", "grader", 
    "mekanik", "driver", "operator", "breakdown", "rfu", "schedule", 
    "service", "perbaikan", "laporan", "kondisi", "wo", "pr", "po",
    "siap", "standby", "monitor", "copy", "rogger", "86",
    "update", "urung", "belum", "lagi", "merapat", "info", "progress", "nanya",
    "absen", "lokasi", "posisi", "cuaca", "shift",
    "edit", "besok", "kemarin", "lusa", "ntar", "dicek", "di cek"
]

# --- STOP WORDS (KATA SAMPAH YANG DIHAPUS) ---
# V.32: Ditambah banyak kata agar pencarian bersih dari "sampah" chat
STOP_WORDS = [
    "stok", "stock", "ready", "cek", "cari", "tanya", "ada", "gak", "nggak", 
    "brp", "berapa", "harga", "minta", "tolong", "liat", "lihat", 
    "kah", "ya", "bisa", "pak", "mas", "bang", "bu", "om", "lek", 
    "bantu", "mohon", "coba", "tolongin", "mba", "kak", "sist", "gan",
    "laden", "bot", "den", "min", "admin", "beta", "tes",
    "sent", "via", "fonnte", "com",
    # V.32 ADDITIONS (Pembersih Chat):
    "ukuran", "saja", "nya", "yang", "mana", "tipe", "type", "jenis", "model",
    "merk", "brand", "butuh", "perlu", "punya", "pake", "pakai",
    "pakde", "pakdhe", "lurr", "lur", "gantine", "ut", "mtw", "komplit", "udh", "sudah",
    "ini", "itu", "disini", "disitu", "wae", "bawa", "balik"
]

GENERIC_ITEMS = ["baut", "bolt", "mur", "nut", "screw", "washer", "ring"]

def log(message):
    print(f"[LOG] {message}", file=sys.stdout, flush=True)

def connect_google_sheet():
    json_creds = os.environ.get("GOOGLE_JSON_KEY")
    if not json_creds: return None
    try:
        creds_dict = json.loads(json_creds)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID).sheet1
    except Exception as e:
        log(f"Error GSheet: {e}")
        return None

def clean_text(text):
    if not text: return ""
    t = str(text).strip()
    if t.lower() in ["nan", "none", "null", "-", "0"]: return ""
    return t

def normalize_pn(text):
    t = str(text).lower()
    t = re.sub(r'[^a-z0-9]', '', t) 
    t = t.replace('o', '0')         
    return t

def is_sap_document(word):
    clean_w = re.sub(r'[^0-9]', '', word)
    if len(clean_w) != 10: return False
    if clean_w.startswith("10") or clean_w.startswith("22") or clean_w.startswith("24") or clean_w.startswith("26"):
        return True
    return False

def smart_clean_keyword(text):
    if text.strip().startswith(">"): return "" 
    text_clean = text.replace("?", "").replace("!", "").replace(",", " ").replace(".", " ").replace(":", "") 
    text_clean = re.sub(r'@[a-zA-Z0-9]+', '', text_clean)
    has_digit = any(char.isdigit() for char in text_clean)
    
    words = text_clean.split()
    final_words = []
    
    for w in words:
        w_lower = w.lower()
        if w_lower in STOP_WORDS: continue
        if has_digit and w_lower in GENERIC_ITEMS: continue
        if is_sap_document(w): continue 
        
        final_words.append(w)
        
    if not final_words: return ""
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
        if not raw_rows: return []
        headers = [h.strip().lower() for h in raw_rows[0]]
        
        idx_desc = next((i for i, h in enumerate(headers) if "desc" in h), -1)
        idx_mat  = next((i for i, h in enumerate(headers) if "material" in h and "desc" not in h), -1)
        idx_qty  = next((i for i, h in enumerate(headers) if "total" in h or "stock" in h or "unrestricted" in h), -1)
        idx_plant = next((i for i, h in enumerate(headers) if "plant" in h), -1)
        idx_bin = next((i for i, h in enumerate(headers) if "bin" in h), -1)
        idx_spec = next((i for i, h in enumerate(headers) if "procurement" in h), -1)
        idx_upd = next((i for i, h in enumerate(headers) if "update" in h), -1)
        idx_batch = next((i for i, h in enumerate(headers) if "batch" in h), -1)

        if idx_desc == -1 or idx_qty == -1: return []

        clean_data = []
        for row in raw_rows[1:]:
            if len(row) <= idx_qty: continue
            raw_qty = row[idx_qty]
            try: qty_val = float(re.sub(r'[^\d.]', '', str(raw_qty)))
            except: qty_val = 0.0

            item = {
                'desc': str(row[idx_desc]).strip(),
                'mat': str(row[idx_mat]).strip() if idx_mat != -1 else "-",
                'qty': qty_val,
                'plant': str(row[idx_plant]).strip() if idx_plant != -1 else "-",
                'bin': str(row[idx_bin]).strip() if idx_bin != -1 else "-",
                'spec': clean_text(row[idx_spec]) if idx_spec != -1 else "",
                'last_update': clean_text(row[idx_upd]) if idx_upd != -1 else "",
                'batch': clean_text(row[idx_batch]) if idx_batch != -1 else ""
            }
            clean_data.append(item)
        CACHE_DATA = clean_data
        CACHE_TIMESTAMP = now
        log(f"✅ Berhasil Cache {len(clean_data)} item.")
        return CACHE_DATA
    except Exception as e:
        log(f"⚠️ Gagal Download: {e}")
        return CACHE_DATA

def get_general_update_time():
    data = get_data_lightweight()
    if not data: return "Unknown"
    for item in data:
        if item['last_update'] and len(item['last_update']) > 5:
            return item['last_update']
    return "Live via Google Sheet"

def cari_stok(raw_keyword, page=0, is_batch=False):
    data = get_data_lightweight()
    if not data: return "⚠️ Gagal mengambil data server."

    # V.32 Clean Keyword yang sangat kuat
    clean_keyword_step1 = smart_clean_keyword(raw_keyword.strip())
    
    # Jika setelah dibersihkan hasilnya kosong (misal cuma "cek om"), return kosong
    if not clean_keyword_step1 or len(clean_keyword_step1) < 2: return "" 

    clean_keyword = clean_keyword_step1.lower().strip()
    kata_kata = clean_keyword.split()
    kata_baru = [KAMUS_SINONIM.get(k, k) for k in kata_kata]
    keyword_search = " ".join(kata_baru)
    keywords_split = keyword_search.split()
    keyword_pn_clean = normalize_pn(keyword_search)

    hasil = []
    for item in data:
        match_desc = True
        teks_desc = item['desc'].lower()
        for k in keywords_split:
            if k not in teks_desc:
                match_desc = False
                break
        match_mat = False
        if keyword_pn_clean in normalize_pn(item['mat']):
            match_mat = True
        if match_desc or match_mat:
            hasil.append(item)

    unik_mat_list = []
    seen = set()
    for x in hasil:
        if x['mat'] not in seen:
            unik_mat_list.append(x['mat'])
            seen.add(x['mat'])
    total_items = len(unik_mat_list)
    
    ITEMS_PER_PAGE = 10 
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    
    if page >= total_pages and page > 0: return "⚠️ Sudah halaman terakhir, Pak."

    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    
    if is_batch:
        current_page_mats = unik_mat_list[:3]
    else:
        current_page_mats = unik_mat_list[start_idx:end_idx]

    pesan_koreksi = ""
    if not hasil and not is_batch:
        all_names = list(set([d['desc'] for d in data]))
        mirip = difflib.get_close_matches(keyword_search.upper(), all_names, n=1, cutoff=0.7) 
        if mirip:
            tebakan = mirip[0]
            pesan_koreksi = f"⚠️ _Mboten wonten. Maksud Bapak:_ *{tebakan}*?\n"
            hasil = [d for d in data if tebakan.lower() in d['desc'].lower()]

    if not hasil: 
        if is_batch: return f"❌ {keyword_search.upper()}: ⛔ Tidak Ditemukan\n"
        return f"🙏 Stok *'{clean_keyword}'* boten wonten."

    pesan = ""
    if not is_batch:
        pesan = f"🙏 *Laden jawab ya...*\n"
        if pesan_koreksi: pesan += pesan_koreksi
        pesan += f"Pencarian: {keyword_search.upper()} ({total_items} items)\n"
        pesan += f"📖 Halaman {page+1} dari {total_pages}\n"
        pesan += "------------------\n"
    
    for mat_id in current_page_mats:
        items_same_mat = [x for x in hasil if x['mat'] == mat_id]
        first_item = items_same_mat[0]
        nama_barang = first_item['desc']
        batch_info = f"({first_item['batch']})" if first_item['batch'] else ""
        spec_text = f"({first_item['spec']})" if first_item['spec'] else ""
        m_qty = sum(x['qty'] for x in items_same_mat if '40AI' in x['plant'].upper())
        h_qty = sum(x['qty'] for x in items_same_mat if '40AJ' in x['plant'].upper())
        
        locs_m = set(x['bin'] for x in items_same_mat if '40AI' in x['plant'].upper())
        locs_h = set(x['bin'] for x in items_same_mat if '40AJ' in x['plant'].upper())
        str_loc_m = ", ".join([l for l in locs_m if clean_text(l)]) or "-"
        str_loc_h = ", ".join([l for l in locs_h if clean_text(l)]) or "-"

        pesan += f"*{nama_barang} {batch_info}*\n"
        pesan += f"Mat: {mat_id} {spec_text}\n"
        pesan += f"Mining : {int(m_qty)} | Hauling : {int(h_qty)}\n"
        pesan += f"({str_loc_m} | {str_loc_h})\n"
        
        if is_batch:
            pesan += "------------------\n" 
        else:
            pesan += "\n"

    if not is_batch:
        if page < total_pages - 1:
             pesan += f"👇 _Ketik *Lagi* atau *Next* untuk halaman selanjutnya._\n"

        real_time = get_general_update_time()
        pesan += f"🕒 Updated: {real_time}"
        
    return pesan

@app.route('/', methods=['GET'])
def home(): return "LADEN V32 (ANTI SPAM & CONVERSATION FILTER) RUNNING"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print(f"[DEBUG] Masuk: {json.dumps(data)}", file=sys.stdout, flush=True)

    message = data.get('message') or data.get('pesan') 
    target_reply = data.get('pengirim') or data.get('id') or data.get('sender')
    sender_id = target_reply 

    if message:
        msg_lower = message.lower().strip()
        words = msg_lower.split()
        
        trigger_found = False
        
        # 1. CEK NEXT / LAGI
        next_triggers = ["lagi", "next", "lanjut", "berikutnya", "more"]
        if msg_lower in next_triggers:
            if sender_id in USER_SESSIONS:
                session = USER_SESSIONS[sender_id]
                keyword_sess = session['keyword']
                next_page = session['page'] + 1
                USER_SESSIONS[sender_id]['page'] = next_page
                jawaban = cari_stok(keyword_sess, page=next_page, is_batch=False)
                requests.post("https://api.fonnte.com/send", headers={"Authorization": FONNTE_TOKEN}, data={"target": target_reply, "message": jawaban})
                return jsonify({"status": "ok"}), 200
        
        # 2. TRIGGER DETECTION
        is_direct_call = False
        if msg_lower.startswith("@"):
            parts = msg_lower.split(" ", 1)
            first_word = parts[0]
            for my_name in MY_BOT_NAME_KEYWORDS:
                if my_name in first_word: is_direct_call = True
            if "628" in first_word and len(first_word) > 10: is_direct_call = True
            if is_direct_call: trigger_found = True

        elif any(msg_lower.startswith(name) for name in MY_BOT_NAME_KEYWORDS):
            trigger_found = True

        if not trigger_found:
            for trig in TRIGGERS_LAMA:
                if trig in msg_lower:
                    trigger_found = True
                    break

        # 3. JALUR UMUM (AUTO DETECT)
        if not trigger_found:
            has_trigger_word = any(w in words for w in UNIVERSAL_KEYWORDS)
            
            # Filter V.32: Jika ada "di stok" atau "di stock" -> Abaikan (Itu kalimat pasif/tempat)
            has_passive_stock = re.search(r'\bdi\s+stok', msg_lower) or re.search(r'\bdi\s+stock', msg_lower)
            
            is_hard_blacklist = any(w in msg_lower for w in HARD_BLACKLIST)
            is_operational = any(w in msg_lower for w in OPERATIONAL_WORDS)
            
            if has_trigger_word and not is_hard_blacklist and not is_operational and not has_passive_stock and len(words) <= 15:
                trigger_found = True

        # 4. SAFETY CHECK
        if trigger_found:
            has_part_number = re.search(r'\d+-[a-zA-Z0-9-]+', msg_lower)
            is_hard_blacklist = any(w in msg_lower for w in HARD_BLACKLIST)
            is_soft_blacklist = any(w in msg_lower for w in SOFT_BLACKLIST)
            has_strong_trigger = any(w in words for w in UNIVERSAL_KEYWORDS)
            
            # V.32: Cek apakah kalimat diawali "bisa dibantu" atau "maksudnya" (Indikasi percakapan)
            is_conversation = message.lower().startswith("bisa dibantu") or message.lower().startswith("maksudnya")

            if has_part_number:
                trigger_found = True
            elif is_hard_blacklist or is_conversation:
                trigger_found = False # Blokir percakapan
            elif is_soft_blacklist and not has_strong_trigger:
                trigger_found = False

        # 5. EKSEKUSI
        if trigger_found:
            clean_msg = message
            for trig in TRIGGERS_LAMA + UNIVERSAL_KEYWORDS + MY_BOT_NAME_KEYWORDS:
                clean_msg = re.sub(r'\b'+trig+r'\b', '', clean_msg, flags=re.IGNORECASE)
            clean_msg = re.sub(r'@[a-zA-Z0-9_]+', '', clean_msg)
            
            raw_lines = re.split(r'[\n,]', clean_msg)
            
            valid_searches = []
            for line in raw_lines:
                cleaned_line = smart_clean_keyword(line)
                if cleaned_line and len(cleaned_line) > 1: # Pastikan tidak kosong
                    valid_searches.append(cleaned_line)
            
            if not valid_searches:
                return jsonify({"status": "ignored"}), 200
                
            final_reply = ""
            is_batch = len(valid_searches) > 1
            
            if is_batch: final_reply += "📦 *Hasil Pencarian Multi-Item:*\n\n"
            
            if not is_batch:
                USER_SESSIONS[sender_id] = {'keyword': valid_searches[0], 'page': 0}

            for keyword in valid_searches:
                hasil_cari = cari_stok(keyword, page=0, is_batch=is_batch)
                if hasil_cari:
                    final_reply += hasil_cari
            
            if is_batch:
                real_time = get_general_update_time()
                final_reply += f"🕒 Updated: {real_time}"

            requests.post(
                "https://api.fonnte.com/send", 
                headers={"Authorization": FONNTE_TOKEN},
                data={"target": target_reply, "message": final_reply}
            )

    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
