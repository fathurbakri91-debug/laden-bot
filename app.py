from flask import Flask, request, jsonify
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import difflib
import sys

app = Flask(__name__)

# --- PRINT LOG SUPAYA MUNCUL DI RENDER ---
def log(message):
    print(f"[LOG] {message}", file=sys.stdout, flush=True)

# --- KONFIGURASI ---
FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN") 
SHEET_ID = "1GMQ15xaMpJokmyNeckO6PRxtajiRV4yHB1U0wirRcGU"

# Cek apakah Token terbaca
if FONNTE_TOKEN:
    log(f"Token Fonnte Terdeteksi: {FONNTE_TOKEN[:5]}... (Aman)")
else:
    log("⚠️ BAHAYA: Token Fonnte TIDAK terbaca!")

# --- KONEKSI GOOGLE SHEET ---
def connect_google_sheet():
    json_creds = os.environ.get("GOOGLE_JSON_KEY")
    if not json_creds:
        log("⚠️ Error: Kunci Google (JSON) tidak ditemukan di Environment Variables")
        return None
    try:
        creds_dict = json.loads(json_creds)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID).sheet1
    except Exception as e:
        log(f"⚠️ Error Koneksi Google: {e}")
        return None

def cari_stok(raw_keyword):
    log(f"🔍 Sedang mencari: {raw_keyword}")
    try:
        sheet = connect_google_sheet()
        if not sheet: return "⚠️ Gagal koneksi Database (Cek Log)."
        
        data = sheet.get_all_records()
        if not data: return "⚠️ Database Kosong."
        
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip().str.lower()
        
        # Mapping Kolom
        col_desc = next((c for c in df.columns if "desc" in c), None)
        col_mat  = next((c for c in df.columns if "material" in c and "desc" not in c), None)
        col_qty  = next((c for c in df.columns if "total" in c or "stock" in c or "unrestricted" in c), None)
        col_plant = next((c for c in df.columns if "plant" in c), None)

        if not (col_desc and col_qty): return "❌ Format Data Salah."
        
        # Bersihkan Data
        df[col_qty] = pd.to_numeric(df[col_qty].astype(str).str.replace(r'[^\d.]', '', regex=True), errors='coerce').fillna(0)
        
        # Logic Pencarian
        clean_keyword = raw_keyword.lower().strip()
        mask = df[col_desc].astype(str).str.contains(clean_keyword, case=False, na=False) | \
               df[col_mat].astype(str).str.contains(clean_keyword, case=False, na=False)
        hasil = df[mask]
        
        if hasil.empty: 
            log("Barang tidak ditemukan.")
            return f"🙏 Stok *'{raw_keyword}'* tidak ditemukan."
        
        log(f"✅ Ditemukan {len(hasil)} barang.")
        
        # Format Balasan Simple
        pesan = f"🤖 *LADEN (Debug Mode)*\nHasil: *{raw_keyword}*\n━━━━━━━━━━━━━\n"
        for _, row in hasil.head(5).iterrows():
            pesan += f"📦 *{row[col_desc]}*\n   Stok: {row[col_qty]} | Plant: {row[col_plant]}\n\n"
        return pesan
        
    except Exception as e:
        log(f"⚠️ Error System: {str(e)}")
        return f"⚠️ Error System: {str(e)}"

@app.route('/', methods=['GET'])
def home():
    return "LADEN BOT IS LIVE AND READY!"

@app.route('/webhook', methods=['POST'])
def webhook():
    # 1. TANGKAP DATA
    data = request.json
    log(f"📩 Pesan Masuk dari Fonnte: {data}") # INI PENTING
    
    sender = data.get('sender')
    message = data.get('message')
    
    if message and "tanya laden" in message.lower():
        kunci = message.lower().replace("tanya laden", "").strip()
        if kunci:
            # 2. CARI DATA
            jawaban = cari_stok(kunci)
            
            # 3. KIRIM BALASAN
            log(f"📤 Mengirim balasan ke {sender}...")
            resp = requests.post(
                "https://api.fonnte.com/send", 
                headers={"Authorization": FONNTE_TOKEN},
                data={"target": sender, "message": jawaban}
            )
            log(f"Status Kirim Fonnte: {resp.status_code} | {resp.text}")
            
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
