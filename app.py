import os
import re
from flask import Flask, render_template, request, jsonify
from gtts import gTTS
from pydub import AudioSegment
import uuid  # 用來生成獨一無二的檔案名稱

# --- 初始化 Flask 應用 ---
app = Flask(__name__)

# --- 建立暫存資料夾 ---
# 確保 static/temp 資料夾存在，用來存放暫時生成的 MP3
TEMP_FOLDER = 'static/temp'
if not os.path.exists(TEMP_FOLDER):
    os.makedirs(TEMP_FOLDER)

# --- 核心語音生成函式 ---
def create_segment(text, lang):
    """使用 gTTS 將文字轉換為音訊片段 (在記憶體中處理)"""
    if not text:
        return None
    try:
        tts = gTTS(text=text, lang=lang)
        # 產生一個暫時的檔名
        temp_filename = os.path.join(TEMP_FOLDER, f"seg_{uuid.uuid4()}.mp3")
        tts.save(temp_filename)
        segment = AudioSegment.from_mp3(temp_filename)
        os.remove(temp_filename) # 讀取後立即刪除
        return segment
    except Exception as e:
        print(f"語音生成錯誤: {e}")
        return None

# --- Flask 路由設定 ---

# 1. 首頁路由：解決 "Not Found" 錯誤
@app.route('/')
def index():
    """
    當使用者訪問網站根目錄 (例如：https://wordmp3-19.onrender.com/) 時，
    這個函式會被觸發，並回傳 templates/index.html 頁面。
    """
    return render_template('index.html')

# 2. 語音生成路由
@app.route('/generate_audio', methods=['POST'])
def generate_audio_route():
    """
    這個路由只接受 POST 請求，負責接收前端傳來的資料並生成音訊。
    """
    try:
        # 從前端請求中獲取 JSON 資料
        data = request.get_json()
        txt_content = data.get('content', '')
        word_repeats = int(data.get('word_repeats', 3))
        sentence_repeats = int(data.get('sentence_repeats', 1))

        if not txt_content:
            return jsonify({"error": "內容不能為空"}), 400

        # --- 開始處理音訊 ---
        blocks = [b.strip() for b in txt_content.split('\n\n') if b.strip()]
        if not blocks:
            return jsonify({"error": "找不到有效的內容區塊"}), 400

        combined_audio = AudioSegment.empty()
        lrc_lyrics = []
        current_duration_ms = 0

        # 內部函式，用來增加音訊片段並記錄LRC時間
        def add_segment_and_log(text, lang, repeats=1, silence_after=400):
            nonlocal current_duration_ms, combined_audio
            if not text: return

            segment = create_segment(text, lang)
            if not segment: return

            for _ in range(repeats):
                minutes, seconds = divmod(current_duration_ms / 1000, 60)
                lrc_line = f"[{int(minutes):02d}:{seconds:05.2f}] {text}"
                lrc_lyrics.append(lrc_line)
                
                combined_audio += segment + AudioSegment.silent(duration=silence_after)
                current_duration_ms += len(segment) + silence_after
        
        # 遍歷每一個單字區塊
        for block in blocks:
            lines = [line.strip() for line in block.split('\n') if line.strip()]
            if len(lines) < 2: continue

            # 假設格式：中文 -> 日文 -> 日文例句(中文翻譯)
            chinese_word = lines[0]
            japanese_word = lines[1]
            jp_sentence, ch_sentence = "", ""
            if len(lines) > 2:
                match = re.match(r'^(.*?)[\(\（](.*?)[\)\）]$', lines[2])
                if match:
                    jp_sentence, ch_sentence = match.groups()
                else:
                    jp_sentence = lines[2]

            # 按照順序生成
            add_segment_and_log(chinese_word, 'zh-TW', 1, 800)
            add_segment_and_log(japanese_word, 'ja', word_repeats, 400)
            add_segment_and_log(jp_sentence, 'ja', sentence_repeats, 600)
            add_segment_and_log(ch_sentence, 'zh-TW', 1, 800)
            
            # 區塊間的大停頓
            combined_audio += AudioSegment.silent(duration=1500)
            current_duration_ms += 1500

        # --- 產生最終的 MP3 檔案 ---
        if len(combined_audio) == 0:
            return jsonify({"error": "無法生成音訊，請檢查內容格式"}), 400

        # 產生一個獨一無二的檔名，並存放在 static 資料夾中
        output_filename = f"{uuid.uuid4()}.mp3"
        output_path = os.path.join(TEMP_FOLDER, output_filename)
        combined_audio.export(output_path, format="mp3")

        # 產生可以給前端使用的 URL
        mp3_url = f"/{TEMP_FOLDER}/{output_filename}"

        # --- 回傳成功結果 ---
        return jsonify({
            "status": "success",
            "mp3_url": mp3_url,
            "lrc_data": "\n".join(lrc_lyrics)
        })

    except Exception as e:
        # 如果過程中發生任何錯誤，回傳錯誤訊息
        print(f"伺服器錯誤: {e}")
        return jsonify({"error": f"伺服器內部錯誤: {e}"}), 500


# --- 用於本機測試的啟動方式 ---
# 當您在自己電腦上執行 `py app.py` 時，這段會被觸發
# 在 Render 上，gunicorn 會直接呼叫 `app` 變數，所以不會執行這段
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

