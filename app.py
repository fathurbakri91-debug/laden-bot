from flask import Flask, request, jsonify
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import re

app = Flask(__name__)

# --- KONFIGURASI ---
# Token Fonnte & Google Key diambil dari "Brankas" Render (Environment Variables)
FONNTE_TOKEN = os.environ.get("FONNTE_TOKEN") 
SHEET_ID = "1GMQ15xaMpJokmyNeckO6PRxtajiRV4yHB1U0wirRcGU"

# --- KONEKSI GOOGLE SHEET ---
def connect_google_sheet():
    # Mengambil kunci rahasia dari variabel Render
    json_creds = os.environ.get("GOOGLE_JSON_KEY")
    if not json_creds:
        print("Error: Kunci Google tidak ditemukan di Environment Variables")
        return None
        
    creds_dict = json.loads(json_creds)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1

def cari_stok(keyword):
    try:
        sheet = connect_google_sheet()
        if not sheet: return "⚠️ Gagal koneksi ke Database."
        
        data = sheet.get_all_records()
        if not data: return "⚠️ Database Kosong."
        
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip().str.lower()
        
        # Mapping Kolom Otomatis (Cari kolom yang mirip)
        col_desc = next((c for c in df.columns if "desc" in c), None)
        col_mat = next((c for c in df.columns if "material" in c and "desc" not in c), None)
        col_qty = next((c for c in df.columns if "total" in c or "stock" in c or "unrestricted" in c), None)
        col_plant = next((c for c in df.columns if "plant" in c), None)
        col_bin = next((c for c in df.columns if "bin" in c), None)

        if not (col_desc and col_qty): return "❌ Format Data Salah (Kolom tidak dikenali)."
        
        # Bersihkan Data Angka
        df[col_qty] = pd.to_numeric(df[col_qty].astype(str).str.replace(r'[^\d.]', '', regex=True), errors='coerce').fillna(0)
        
        # Cari (Case Insensitive)
        k = keyword.lower().strip()
        mask = df[col_desc].astype(str).str.contains(k, case=False, na=False) | \
               df[col_mat].astype(str).str.contains(k, case=False, na=False)
        
        hasil = df[mask]
        if hasil.empty: return f"🙏 Stok *'{keyword}'* tidak ditemukan."
        
        # Format Balasan
        pesan = f"🤖 *LADEN 24 Jam*\nHasil: *{keyword}*\n━━━━━━━━━━━━━\n"
        for _, row in hasil.head(5).iterrows():
            nama = row[col_desc]
            mat = row[col_mat] if col_mat else "-"
            qty = row[col_qty]
            plant = row[col_plant] if col_plant else "-"
            lokasi = row[col_bin] if col_bin else "-"
            
            pesan += f"📦 *{nama}*\n   Mat: {mat}\n   Stok: {qty} | Plant: {plant}\n   Lok: {lokasi}\n\n"
            
        if len(hasil) > 5:
            pesan += f"⚠️ Ada {len(hasil)-5} item lain yg mirip. Spesifikkan lagi ya."
            
        return pesan
        
    except Exception as e: return f"⚠️ Error System: {str(e)}"

@app.route('/', methods=['GET'])
def home():
    return "LADEN BOT IS LIVE AND RUNNING!"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    # Debug: Print data yang masuk (bisa dilihat di log Render nanti)
    print(f"Pesan Masuk: {data}")
    
    sender = data.get('sender')
    message = data.get('message')
    
    # Logika Trigger: "Tanya laden"
    if message and "tanya laden" in message.lower():
        kunci = message.lower().replace("tanya laden", "").strip()
        
        if kunci:
            jawaban = cari_stok(kunci)
            
            # Kirim Balasan ke Fonnte
            requests.post(
                "https://api.fonnte.com/send", 
                headers={"Authorization": FONNTE_TOKEN},
                data={
                    "target": sender, 
                    "message": jawaban
                }
            )
            
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)