from flask import Flask, request, jsonify
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import difflib
import sys
from datetime import datetime

app = Flask(__name__)

# --- CONFIG ---
FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN") 
SHEET_ID = "1GMQ15xaMpJokmyNeckO6PRxtajiRV4yHB1U0wirRcGU"

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

def cari_stok(raw_keyword):
    try:
        sheet = connect_google_sheet()
        if not sheet: return "⚠️ Gagal koneksi Database."
        
        data = sheet.get_all_records()
        if not data: return "⚠️ Database Kosong."
        
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip().str.lower()
        
        col_desc = next((c for c in df.columns if "desc" in c), None)
        col_mat  = next((c for c in df.columns if "material" in c and "desc" not in c), None)
        col_qty  = next((c for c in df.columns if "total" in c or "stock" in c or "unrestricted" in c), None)
        col_plant = next((c for c in df.columns if "plant" in c), None)
        col_bin = next((c for c in df.columns if "bin" in c), None)
        col_spec = next((c for c in df.columns if "spec" in c or "procurement" in c), None)

        if not (col_desc and col_qty): return "❌ Format Data Salah."
        
        df[col_qty] = pd.to_numeric(df[col_qty].astype(str).str.replace(r'[^\d.]', '', regex=True), errors='coerce').fillna(0)
        
        # LOGIK PINTAR
        clean_keyword = raw_keyword.lower().strip()
        kata_kata = clean_keyword.split()
        kata_baru = [KAMUS_SINONIM.get(k, k) for k in kata_kata]
        keyword_search = " ".join(kata_baru)

        mask = pd.Series([True] * len(df))
        for k in keyword_search.split():
            mask = mask & (df[col_desc].astype(str).str.contains(k, case=False, na=False) | 
                           df[col_mat].astype(str).str.contains(k, case=False, na=False))
        
        hasil = df[mask]
        
        # AUTO CORRECT
        pesan_koreksi = ""
        if hasil.empty:
            semua_barang = df[col_desc].astype(str).dropna().unique().tolist()
            mirip = difflib.get_close_matches(keyword_search.upper(), semua_barang, n=1, cutoff=0.5)
            if mirip:
                tebakan = mirip[0]
                pesan_koreksi = f"⚠️ _Mboten wonten. Maksud Bapak:_ *{tebakan}*?\n\n"
                hasil = df[df[col_desc].astype(str).str.contains(tebakan, case=False, na=False)]

        if hasil.empty: return f"🙏 Stok *'{raw_keyword}'* boten wonten."

        # --- FORMATTING TAMPILAN (BAJU BARU) ---
        jumlah_item = len(hasil)
        
        # Header Sopan
        pesan = f"🙏 *Laden jawab ya...*\n"
        if pesan_koreksi:
            pesan += pesan_koreksi
        else:
            pesan += f"Pencarian: {keyword_search.upper()} ({jumlah_item} items)\n"
        
        pesan += "━━━━━━━━━━━━━━━━━━\n"
        
        unik = hasil[col_mat].unique()[:7] # Max 7 barang
        for mat in unik:
            row = hasil[hasil[col_mat] == mat].iloc[0]
            nama = row[col_desc]
            
            sub = hasil[hasil[col_mat] == mat]
            m = sub[sub[col_plant].astype(str).str.contains('40AI', case=False, na=False)][col_qty].sum()
            h = sub[sub[col_plant].astype(str).str.contains('40AJ', case=False, na=False)][col_qty].sum()
            
            lok_m, lok_h = "-", "-"
            if col_bin:
                lm = sub[sub[col_plant].astype(str).str.contains('40AI')][col_bin].unique()
                lok_m = ",".join([str(x) for x in lm if str(x).lower() not in ['nan','']]) or "-"
                lh = sub[sub[col_plant].astype(str).str.contains('40AJ')][col_bin].unique()
                lok_h = ",".join([str(x) for x in lh if str(x).lower() not in ['nan','']]) or "-"
            
            spec_info = ""
            if col_spec:
                 s = str(row[col_spec])
                 if s.lower() not in ['nan', '']: spec_info = f"({s})"

            # Format Item ala Bot Lama
            pesan += f"*{nama}*\n"
            pesan += f"Mat: {mat} {spec_info}\n"
            pesan += f"Mining : {int(m)} | Hauling : {int(h)}\n"
            pesan += f"({lok_m} | {lok_h})\n\n"
            
        # Footer Waktu
        waktu_skrg = datetime.now().strftime("%d-%m-%Y %H:%M")
        pesan += f"🕒 _Data Update: Live via Google Sheet_"
            
        return pesan

    except Exception as e: return f"⚠️ Error: {e}"

@app.route('/', methods=['GET'])
def home(): return "LADEN IS READY"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    
    message = data.get('message') or data.get('pesan') 
    target_reply = data.get('pengirim') or data.get('id') or data.get('sender')
    
    if message:
        msg_lower = message.lower()
        trigger_found = False
        keyword = ""

        # Cek Intro
        intro_keys = ["siapa", "intro", "kenalan"]
        if ("laden" in msg_lower) and any(k in msg_lower for k in intro_keys):
             intro_msg = (
                "🤝 *Salam Kenal, Saya LADEN*\n\n"
                "*L.A.D.E.N* (Logistik Assistant Data Entry Network)\n"
                "Asisten digital logistik yang siap melayani 24 jam non-stop.\n\n"
                "Monggo, ketik *#tanyaladen* atau *Tanya Den* diikuti nama barang."
            )
             requests.post("https://api.fonnte.com/send", headers={"Authorization": FONNTE_TOKEN}, data={"target": target_reply, "message": intro_msg})
             return jsonify({"status": "ok"}), 200

        # Cek Stok
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
    app.run(host='0.0.0.0', port=5000)
