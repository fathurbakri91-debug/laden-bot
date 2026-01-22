from flask import Flask, request, jsonify
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import re
import difflib # Library untuk membetulkan typo

app = Flask(__name__)

# --- KONFIGURASI ---
FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN") 
SHEET_ID = "1GMQ15xaMpJokmyNeckO6PRxtajiRV4yHB1U0wirRcGU"

# --- KAMUS PINTAR (DARI KODE LAMA BAPAK) ---
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

KEYWORDS_INTRO = [
    "siapa", "kepanjangan", "apa itu", "kenalan", 
    "kamu itu", "robot apa", "bot apa", "fungsi"
]

TRIGGERS_LADEN = [
    "tanya laden", "#tanyaladen", 
    "tanya den", "#tanyaden", 
    "cek laden", "cek den"
]

# --- KONEKSI GOOGLE SHEET ---
def connect_google_sheet():
    json_creds = os.environ.get("GOOGLE_JSON_KEY")
    if not json_creds: return None
    creds_dict = json.loads(json_creds)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1

def cari_stok(raw_keyword):
    try:
        sheet = connect_google_sheet()
        if not sheet: return "⚠️ Gagal koneksi Database."
        
        data = sheet.get_all_records()
        if not data: return "⚠️ Database Kosong."
        
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip().str.lower()
        
        # Mapping Kolom Otomatis
        col_desc = next((c for c in df.columns if "desc" in c or "description" in c), None)
        col_mat  = next((c for c in df.columns if "material" in c and "desc" not in c), None)
        col_qty  = next((c for c in df.columns if "unrestricted" in c or "total" in c or "stock" in c), None)
        col_plant = next((c for c in df.columns if "plant" in c), None)
        col_bin = next((c for c in df.columns if "bin" in c), None)
        col_spec = next((c for c in df.columns if "procurement" in c or "spec" in c), None)

        if not (col_desc and col_qty): return "❌ Format Data Salah."
        
        # Bersihkan Data Angka
        df[col_qty] = pd.to_numeric(df[col_qty].astype(str).str.replace(r'[^\d.]', '', regex=True), errors='coerce').fillna(0)
        
        # 1. LOGIKA SINONIM (Ganti kata dulu sebelum cari)
        clean_keyword = raw_keyword.lower().strip()
        kata_kata = clean_keyword.split()
        kata_baru = []
        for k in kata_kata:
            kata_baru.append(KAMUS_SINONIM.get(k, k)) # Ganti jika ada di kamus
        keyword_search = " ".join(kata_baru)

        # 2. CARI TAHAP 1 (Pencarian Tepat)
        mask = pd.Series([True] * len(df))
        for k in keyword_search.split():
            cond_desc = df[col_desc].astype(str).str.contains(k, case=False, na=False)
            cond_mat = df[col_mat].astype(str).str.contains(k, case=False, na=False)
            mask = mask & (cond_desc | cond_mat)
        
        hasil_full = df[mask]
        pesan_koreksi = ""

        # 3. CARI TAHAP 2 (AUTO-CORRECT / TYPO)
        if hasil_full.empty:
            semua_barang = df[col_desc].astype(str).dropna().unique().tolist()
            mirip = difflib.get_close_matches(keyword_search.upper(), semua_barang, n=1, cutoff=0.5)
            
            if mirip:
                tebakan = mirip[0]
                pesan_koreksi = f"⚠️ _Ngapunten, '{raw_keyword}' boten wonten._\n💡 _Mungkin maksud Bapak:_ *{tebakan}*?\n\n"
                hasil_full = df[df[col_desc].astype(str).str.contains(tebakan, case=False, na=False)]
                keyword_search = tebakan

        if hasil_full.empty: return f"🙏 _Ngapunten_, stok *'{raw_keyword.upper()}'* boten wonten (tidak ditemukan)."
        
        # --- FORMATTING (MINING VS HAULING) ---
        pesan = f"🤖 *LADEN 24 Jam (Cloud)*\n"
        if pesan_koreksi: pesan += pesan_koreksi
        else: pesan += f"Hasil: *{keyword_search.upper()}*\n"
        pesan += "━━━━━━━━━━━━━━━━━━\n"
        
        unik_materials = hasil_full[col_mat].unique()
        
        # Batasi 7 barang teratas
        for mat_num in unik_materials[:7]:
            data_item = hasil_full[hasil_full[col_mat] == mat_num]
            nama = data_item[col_desc].iloc[0]
            
            # Ambil Spek (Jika ada)
            val_spec = ""
            if col_spec:
                raw_s = str(data_item[col_spec].iloc[0])
                if raw_s.lower() not in ['nan', '']: val_spec = f"({raw_s})"

            # Hitung Mining vs Hauling
            df_m = data_item[data_item[col_plant].astype(str).str.contains('40AI', case=False, na=False)]
            total_m = df_m[col_qty].sum()
            
            df_h = data_item[data_item[col_plant].astype(str).str.contains('40AJ', case=False, na=False)]
            total_h = df_h[col_qty].sum()

            # Ambil Lokasi
            str_bin_m, str_bin_h = "-", "-"
            if col_bin:
                bm = df_m[col_bin].unique()
                str_bin_m = ", ".join(str(b) for b in bm if str(b).lower() not in ['nan', ''])
                bh = df_h[col_bin].unique()
                str_bin_h = ", ".join(str(b) for b in bh if str(b).lower() not in ['nan', ''])

            # Format Angka Bulat
            sm = f"{int(total_m)}" if total_m % 1 == 0 else f"{total_m}"
            sh = f"{int(total_h)}" if total_h % 1 == 0 else f"{total_h}"

            pesan += f"📦 *{nama}*\n   Mat: {mat_num} {val_spec}\n"
            pesan += f"   Mining : {sm} | Hauling : {sh}\n"
            if str_bin_m != "-" or str_bin_h != "-":
                pesan += f"   Lok: ({str_bin_m} | {str_bin_h})\n"
            pesan += "\n"
            
        return pesan
        
    except Exception as e: return f"⚠️ Error System: {str(e)}"

@app.route('/', methods=['GET'])
def home():
    return "LADEN BOT IS LIVE!"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    sender = data.get('sender')
    message = data.get('message')
    
    if message:
        msg_lower = message.lower()
        
        # 1. CEK INTRO (Siapa kamu?)
        if ("laden" in msg_lower or "den" in msg_lower) and any(k in msg_lower for k in KEYWORDS_INTRO):
            intro_msg = (
                "🤝 *Salam Kenal, Saya LADEN*\n\n"
                "*L.A.D.E.N* (Logistik Assistant Data Entry Network)\n"
                "Asisten digital logistik yang siap melayani 24 jam non-stop.\n\n"
                "Filosofi: _Melayani agar kerjaan lapangan makin ringan._ 🏗️\n"
                "Monggo, ketik *Tanya Den [nama barang]*."
            )
            requests.post("https://api.fonnte.com/send", headers={"Authorization": FONNTE_TOKEN}, data={"target": sender, "message": intro_msg})
            return jsonify({"status": "ok"}), 200

        # 2. CEK TANYA STOK (Flexible Trigger)
        trigger_found = False
        keyword = ""
        
        for trig in TRIGGERS_LADEN:
            if trig in msg_lower:
                temp_kw = msg_lower.replace(trig, "")
                temp_kw = temp_kw.replace("stok", "").replace("stock", "")
                keyword = temp_kw.strip()
                trigger_found = True
                break
        
        if trigger_found and keyword:
            jawaban = cari_stok(keyword)
            requests.post("https://api.fonnte.com/send", headers={"Authorization": FONNTE_TOKEN}, data={"target": sender, "message": jawaban})

    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
