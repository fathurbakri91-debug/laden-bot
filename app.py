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

# --- GLOBAL CACHE ---
CACHE_DATA = []      
CACHE_TIMESTAMP = None
CACHE_TIME_STR = "-" # Untuk menyimpan teks waktu update terakhir
CACHE_DURATION = 900 # 15 Menit

# --- KAMUS PINTAR ---
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
    "oring": "o-ring", "o ring": "o-ring"
}

TRIGGERS_LADEN = ["tanya laden", "#tanyaladen", "tanya den", "#tanyaden", "cek laden", "cek den"]

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

def get_data_lightweight():
    global CACHE_DATA, CACHE_TIMESTAMP, CACHE_TIME_STR
    now = datetime.now()
    
    # Cek Cache
    if CACHE_DATA and CACHE_TIMESTAMP and (now - CACHE_TIMESTAMP).total_seconds() < CACHE_DURATION:
        return CACHE_DATA

    log("🔄 Download Data Baru...")
    try:
        sheet = connect_google_sheet()
        if not sheet: return []
        
        raw_rows = sheet.get_all_values()
        if not raw_rows: return []
        
        headers = [h.strip().lower() for h in raw_rows[0]]
        
        # Cari Index Kolom
        idx_desc = next((i for i, h in enumerate(headers) if "desc" in h), -1)
        idx_mat  = next((i for i, h in enumerate(headers) if "material" in h and "desc" not in h), -1)
        idx_qty  = next((i for i, h in enumerate(headers) if "total" in h or "stock" in h or "unrestricted" in h), -1)
        idx_plant = next((i for i, h in enumerate(headers) if "plant" in h), -1)
        idx_bin = next((i for i, h in enumerate(headers) if "bin" in h), -1)
        idx_spec = next((i for i, h in enumerate(headers) if "spec" in h or "procurement" in h), -1)

        if idx_desc == -1 or idx_qty == -1:
            log("❌ Format Header Salah")
            return []

        clean_data = []
        for row in raw_rows[1:]:
            if len(row) <= idx_qty: continue
            
            raw_qty = row[idx_qty]
            try:
                qty_val = float(re.sub(r'[^\d.]', '', str(raw_qty)))
            except:
                qty_val = 0.0

            item = {
                'desc': str(row[idx_desc]).strip(),
                'mat': str(row[idx_mat]).strip() if idx_mat != -1 else "-",
                'qty': qty_val,
                'plant': str(row[idx_plant]).strip() if idx_plant != -1 else "-",
                'bin': str(row[idx_bin]).strip() if idx_bin != -1 else "-",
                'spec': str(row[idx_spec]).strip() if idx_spec != -1 else ""
            }
            clean_data.append(item)
            
        CACHE_DATA = clean_data
        CACHE_TIMESTAMP = now
        # Update Jam Fetching (WIB = UTC+7)
        jam_wib = now + timedelta(hours=7)
        CACHE_TIME_STR = jam_wib.strftime("%d-%m-%Y %H:%M") + " WIB"
        
        log(f"✅ Berhasil Cache {len(clean_data)} item.")
        return CACHE_DATA

    except Exception as e:
        log(f"⚠️ Gagal Download: {e}")
        return CACHE_DATA

def cari_stok(raw_keyword):
    data = get_data_lightweight()
    if not data: return "⚠️ Gagal mengambil data server."

    clean_keyword = raw_keyword.lower().strip()
    kata_kata = clean_keyword.split()
    kata_baru = [KAMUS_SINONIM.get(k, k) for k in kata_kata]
    keyword_search = " ".join(kata_baru)
    keywords_split = keyword_search.split()

    hasil = []
    for item in data:
        match_all = True
        teks_desc = item['desc'].lower()
        teks_mat = item['mat'].lower()
        
        for k in keywords_split:
            if (k not in teks_desc) and (k not in teks_mat):
                match_all = False
                break
        if match_all:
            hasil.append(item)

    # AUTO CORRECT
    pesan_koreksi = ""
    if not hasil:
        all_names = list(set([d['desc'] for d in data]))
        mirip = difflib.get_close_matches(keyword_search.upper(), all_names, n=1, cutoff=0.5)
        if mirip:
            tebakan = mirip[0]
            pesan_koreksi = f"⚠️ _Mboten wonten. Maksud Bapak:_ *{tebakan}*?\n\n"
            hasil = [d for d in data if tebakan.lower() in d['desc'].lower()]

    if not hasil: return f"🙏 Stok *'{raw_keyword}'* boten wonten."

    # --- PERBAIKAN LOGIKA HITUNG (COUNT UNIQUE) ---
    unik_mat_list = []
    seen = set()
    for x in hasil:
        if x['mat'] not in seen:
            unik_mat_list.append(x['mat'])
            seen.add(x['mat'])
            
    jumlah_item = len(unik_mat_list) # Hitung Barang Unik, bukan baris
    
    pesan = f"🙏 *Laden jawab ya...*\n"
    if pesan_koreksi: pesan += pesan_koreksi
    else: pesan += f"Pencarian: {keyword_search.upper()} ({jumlah_item} items)\n"
    pesan += "━━━━━━━━━━━━━━━━━━\n"
    
    ditampilkan = 0
    
    for mat_id in unik_mat_list:
        # Ambil semua baris milik material ini (untuk hitung total & lokasi)
        items_same_mat = [x for x in hasil if x['mat'] == mat_id]
        
        # Ambil data umum dari baris pertama
        first_item = items_same_mat[0]
        nama_barang = first_item['desc']
        
        # PERBAIKAN SPEC: Tampilkan jika ada
        spec_text = ""
        if first_item['spec'] and first_item['spec'] != "-":
            spec_text = f"({first_item['spec']})"
            
        # Hitung Stok
        m_qty = sum(x['qty'] for x in items_same_mat if '40AI' in x['plant'].upper())
        h_qty = sum(x['qty'] for x in items_same_mat if '40AJ' in x['plant'].upper())
        
        # Cek Lokasi (Bin)
        locs_m = set(x['bin'] for x in items_same_mat if '40AI' in x['plant'].upper() and x['bin'] not in ['-', ''])
        locs_h = set(x['bin'] for x in items_same_mat if '40AJ' in x['plant'].upper() and x['bin'] not in ['-', ''])
        
        str_loc_m = ", ".join(locs_m) if locs_m else "-"
        str_loc_h = ", ".join(locs_h) if locs_h else "-"

        # Format Tampilan Akhir
        pesan += f"*{nama_barang}*\n"
        pesan += f"Mat: {mat_id} {spec_text}\n"
        pesan += f"Mining : {int(m_qty)} | Hauling : {int(h_qty)}\n"
        pesan += f"({str_loc_m} | {str_loc_h})\n\n"
        
        ditampilkan += 1
        if ditampilkan >= 7: break
        
    # FOOTER WAKTU UPDATE (CACHE TIME)
    pesan += f"🕒 _Data Update: {CACHE_TIME_STR}_"
        
    return pesan

@app.route('/', methods=['GET'])
def home(): return "LADEN V3 READY"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    message = data.get('message') or data.get('pesan') 
    target_reply = data.get('pengirim') or data.get('id') or data.get('sender')
    
    if message:
        msg_lower = message.lower()
        trigger_found = False
        keyword = ""
        
        intro_keys = ["siapa", "intro", "kenalan"]
        if ("laden" in msg_lower) and any(k in msg_lower for k in intro_keys):
             intro_msg = "🤝 *Salam Kenal, Saya LADEN*\nSiap melayani cek stok 24 Jam.\nKetik *Tanya Den [Barang]*"
             requests.post("https://api.fonnte.com/send", headers={"Authorization": FONNTE_TOKEN}, data={"target": target_reply, "message": intro_msg})
             return jsonify({"status": "ok"}), 200

        for trig in TRIGGERS_LADEN:
            if trig in msg_lower:
                keyword = msg_lower.replace(trig, "").replace("stok", "").strip()
                trigger_found = True
                break
        
        if trigger_found and keyword:
            jawaban = cari_stok(keyword)
            requests.post(
                "https://api.fonnte.com/send", 
                headers={"Authorization": FONNTE_TOKEN},
                data={"target": target_reply, "message": jawaban}
            )

    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
