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

# --- KAMUS PINTAR (Sama seperti V.24) ---
KAMUS_SINONIM = {
    "wipol": "wypall", "wypal": "wypall", "waipol": "wypall",
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

# --- KONFIGURASI FILTER KATA (UPDATED V.26) ---
TRIGGERS_LAMA = ["tanya laden", "tanya den", "cek laden", "cek den", "tanya stok", "cek stok"]
UNIVERSAL_KEYWORDS = ["stok", "stock", "cek"]

# DAFTAR KATA TERLARANG (ANTI SPAM & ANTI GOSIP)
BLACKLIST_WORDS = [
    # Kata Operasional (Biar gak nyaut laporan)
    "lambung", "cn", "sn", "hm", "km", "engine", 
    "unit", "dt", "hd", "lv", "gd", "dozer", "grader", 
    "mekanik", "driver", "operator", "breakdown", "rfu", "schedule", 
    "service", "perbaikan", "laporan", "kondisi", "wo", "pr", "po",
    "siap", "standby", "monitor", "copy", "rogger", "86",
    "update", "urung", "belum", "lagi", "merapat", "info", "progress", "nanya",
    "absen", "lokasi", "posisi", "cuaca", "shift",
    "edit", "besok", "kemarin", "lusa", "ntar", "dicek", "di cek",
    
    # Kata Percakapan / Basa-basi (ANTI GOSIP - BARU V.26)
    "senggol", "colek", "biar", "dulu", "dong", "tuh", "nih", "dijawab", 
    "jawab", "cuy", "woi", "halo", "test", "tes", "wkwk", "haha",
    "rajin", "pinter", "bodoh", "goblok", "lemot", "rusak", "error", 
    "lur", "gan", "bang", "mz", "mas", "pak", "bu", "om", "kah", "kok", "sih"
]

STOP_WORDS = [
    "stok", "stock", "ready", "cek", "cari", "tanya", "ada", "gak", "nggak", 
    "brp", "berapa", "harga", "minta", "tolong", "liat", "lihat", 
    "kah", "ya", "bisa", "pak", "mas", "bang", "bu", "om", "lek", 
    "bantu", "mohon", "coba", "tolongin", "mba", "kak", "sist", "gan",
    "laden", "bot", "den", "min", "admin", "beta", "tes" 
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

def smart_clean_keyword(text):
    text_clean = text.replace("?", "").replace("!", "") # Buang tanda tanya/seru
    text_clean = re.sub(r'@[a-zA-Z0-9]+', '', text_clean)
    has_digit = any(char.isdigit() for char in text_clean)
    
    words = text_clean.split()
    final_words = []
    
    for w in words:
        w_lower = w.lower()
        if w_lower in STOP_WORDS: continue
        if has_digit and w_lower in GENERIC_ITEMS: continue
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
        
        # Mapping Index (Flexible)
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

def cari_stok(raw_keyword):
    data = get_data_lightweight()
    if not data: return "⚠️ Gagal mengambil data server."

    clean_keyword = smart_clean_keyword(raw_keyword).lower().strip()
    if not clean_keyword: return "⚠️ _Maaf, kata kuncinya kurang jelas pak._"

    # Logika Hybrid (Sama seperti V.24)
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

    # Auto Correct
    pesan_koreksi = ""
    if not hasil:
        all_names = list(set([d['desc'] for d in data]))
        mirip = difflib.get_close_matches(keyword_search.upper(), all_names, n=1, cutoff=0.7) 
        if mirip:
            tebakan = mirip[0]
            pesan_koreksi = f"⚠️ _Mboten wonten. Maksud Bapak:_ *{tebakan}*?\n"
            hasil = [d for d in data if tebakan.lower() in d['desc'].lower()]

    if not hasil: return f"🙏 Stok *'{keyword_search}'* boten wonten."

    # Logic Tampilan Ringkas
    unik_mat_list = []
    seen = set()
    for x in hasil:
        if x['mat'] not in seen:
            unik_mat_list.append(x['mat'])
            seen.add(x['mat'])
    
    pesan = f"🙏 *Laden jawab ya...*\n"
    if pesan_koreksi: pesan += pesan_koreksi
    
    for mat_id in unik_mat_list[:10]:
        items_same_mat = [x for x in hasil if x['mat'] == mat_id]
        first_item = items_same_mat[0]
        nama_barang = first_item['desc']
        
        m_qty = sum(x['qty'] for x in items_same_mat if '40AI' in x['plant'].upper())
        h_qty = sum(x['qty'] for x in items_same_mat if '40AJ' in x['plant'].upper())
        
        # Lokasi Bin
        locs_m = set(x['bin'] for x in items_same_mat if '40AI' in x['plant'].upper())
        locs_h = set(x['bin'] for x in items_same_mat if '40AJ' in x['plant'].upper())
        
        str_loc_m = ", ".join([l for l in locs_m if clean_text(l)]) or "-"
        str_loc_h = ", ".join([l for l in locs_h if clean_text(l)]) or "-"

        pesan += f"*{nama_barang}*\nMat: {mat_id}\nMining : {int(m_qty)} | Hauling : {int(h_qty)}\n({str_loc_m} | {str_loc_h})\n\n"

    # Footer Waktu
    waktu_update_data = "Live via Google Sheet" 
    for h in hasil:
        if h['last_update']:
            waktu_update_data = h['last_update']
            break
            
    pesan += f"🕒 {waktu_update_data}"
    return pesan

@app.route('/', methods=['GET'])
def home(): return "LADEN V26 (ANTI GOSIP) RUNNING"

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
        
        # 1. CEK TAG LANGSUNG (Prioritas Tinggi)
        is_direct_call = False
        if msg_lower.startswith("@"):
            # Misal: @Laden stok baut (Dianggap perintah valid)
            parts = msg_lower.split(" ", 1)
            first_word = parts[0]
            for my_name in MY_BOT_NAME_KEYWORDS:
                if my_name in first_word: is_direct_call = True
            
            # Cek kalau di-tag pakai nomor WA (biasanya 628...)
            if "628" in first_word and len(first_word) > 10: is_direct_call = True
            
            if is_direct_call: trigger_found = True

        # 2. CEK NAMA DEPAN (Prioritas Tinggi)
        elif any(msg_lower.startswith(name) for name in MY_BOT_NAME_KEYWORDS):
            trigger_found = True

        # 3. CEK TRIGGER LAMA (Prioritas Sedang)
        if not trigger_found:
            for trig in TRIGGERS_LAMA:
                if trig in msg_lower:
                    trigger_found = True
                    break

        # 4. JALUR UMUM (Prioritas Rendah - RAWAN SPAM)
        if not trigger_found:
            has_trigger_word = any(w in words for w in UNIVERSAL_KEYWORDS)
            
            # --- FILTER BARU V.26 (ANTI GOSIP) ---
            # Cek apakah ada kata-kata blacklist di dalam kalimat
            is_operational = any(w in msg_lower for w in BLACKLIST_WORDS)
            is_short_message = len(words) <= 7 

            # HANYA JAWAB JIKA: Ada kata 'stok', BUKAN kalimat operasional/gosip, dan kalimat pendek.
            if has_trigger_word and not is_operational and is_short_message:
                trigger_found = True
                print("[DEBUG] Trigger Jalur Umum (Auto Detect)", file=sys.stdout)
            else:
                if has_trigger_word and is_operational:
                    print(f"[DEBUG] Dibatalkan Blacklist: {message}", file=sys.stdout)

        # --- EKSEKUSI ---
        if trigger_found:
            # Bersihkan trigger word dari pesan
            clean_msg = message
            for trig in TRIGGERS_LAMA + UNIVERSAL_KEYWORDS + MY_BOT_NAME_KEYWORDS:
                clean_msg = re.sub(r'\b'+trig+r'\b', '', clean_msg, flags=re.IGNORECASE)
            
            clean_msg = re.sub(r'@[a-zA-Z0-9_]+', '', clean_msg) # Hapus tag
            
            jawaban = cari_stok(clean_msg)
            requests.post(
                "https://api.fonnte.com/send", 
                headers={"Authorization": FONNTE_TOKEN},
                data={"target": target_reply, "message": jawaban}
            )

    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
