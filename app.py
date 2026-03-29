import os
import re
import uuid
from flask import Flask, render_template, request, jsonify, send_from_directory
from gtts import gTTS
from pydub import AudioSegment

# --- 初始化 Flask 應用 ---
app = Flask(__name__)

# --- 設定暫存資料夾 ---
# 在 Render 這種環境，'/tmp' 是一個可以安全讀寫的臨時目錄
TEMP_FOLDER = '/tmp'

# --- 核心語音生成函式 ---
def create_segment(text, lang):
    """使用 gTTS 將文字轉換為音訊片段"""
    if not text:
        return None
    try:
        tts = gTTS(text=text, lang=lang)
        # 在 /tmp 中產生一個暫時的檔名
        temp_filename = os.path.join(TEMP_FOLDER, f"seg_{uuid.uuid4()}.mp3")
        tts.save(temp_filename)
        segment = AudioSegment.from_mp3(temp_filename)
        os.remove(temp_filename) # 讀取後立即刪除，保持 /tmp 乾淨
        return segment
    except Exception as e:
        print(f"gTTS 錯誤: {e}")
        return None

# --- Flask 路由設定 ---

# 1. 首頁路由
@app.route('/')
def index():
    """顯示主頁面 (index.html)"""
    return render_template('index.html')

# 2. 語音生成的主要邏輯路由
@app.route('/generate_audio', methods=['POST'])
def generate_audio_route():
    """接收前端請求，生成 MP3 和 LRC 資料，並回傳結果"""
    try:
        data = request.get_json()
        txt_content = data.get('content', '')
        word_repeats = int(data.get('word_repeats', 3))
        sentence_repeats = int(data.get('sentence_repeats', 1))

        if not txt_content:
            return jsonify({"error": "內容不能為空"}), 400

        blocks = [b.strip() for b in txt_content.split('\n\n') if b.strip()]
        if not blocks:
            return jsonify({"error": "找不到有效的內容區塊"}), 400

        combined_audio = AudioSegment.empty()
        lrc_lyrics = []
        current_duration_ms = 0

        # 內部函式，用來組合音訊並記錄時間
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
        
        # 遍歷文字內容並生成音訊
        for block in blocks:
            lines = [line.strip() for line in block.split('\n') if line.strip()]
            if len(lines) < 2: continue
            
            chinese_word = lines[0]
            japanese_word = lines[1]
            jp_sentence, ch_sentence = "", ""
            if len(lines) > 2:
                match = re.match(r'^(.*?)[\(\（](.*?)[\)\）]$', lines[2])
                if match:
                    jp_sentence, ch_sentence = match.groups()
                else:
                    jp_sentence = lines[2]

            add_segment_and_log(chinese_word, 'zh-TW', 1, 800)
            add_segment_and_log(japanese_word, 'ja', word_repeats, 400)
            add_segment_and_log(jp_sentence, 'ja', sentence_repeats, 600)
            add_segment_and_log(ch_sentence, 'zh-TW', 1, 800)
            
            combined_audio += AudioSegment.silent(duration=1500)
            current_duration_ms += 1500

        if len(combined_audio) == 0:
            return jsonify({"error": "無法生成音訊，請檢查文字內容或 gTTS 服務是否正常"}), 400

        # 將最終的 MP3 檔案儲存到 /tmp
        output_filename = f"{uuid.uuid4()}.mp3"
        output_path = os.path.join(TEMP_FOLDER, output_filename)
        combined_audio.export(output_path, format="mp3")

        # 回傳成功訊息，包含 LRC 資料和一個指向新下載路由的 URL
        return jsonify({
            "status": "success",
            "mp3_url": f"/audio/{output_filename}",
            "lrc_data": "\n".join(lrc_lyrics)
        })

    except Exception as e:
        print(f"伺服器內部錯誤: {e}")
        return jsonify({"error": f"伺服器內部錯誤，請檢查日誌"}), 500

# 3. 新增的音訊檔案提供路由
@app.route('/audio/<filename>')
def serve_audio(filename):
    """
    這個路由專門用來讓瀏覽器可以下載/播放儲存在 /tmp 裡的音訊檔案。
    """
    try:
        return send_from_directory(
            TEMP_FOLDER, 
            filename, 
            as_attachment=False # False 表示在瀏覽器中直接播放，而不是下載
        )
    except FileNotFoundError:
        return jsonify({"error": "找不到音訊檔案"}), 404

# --- 用於本機測試的啟動方式 ---
if __name__ == '__main__':
    # 在本機執行時，監聽所有 IP 的 8080 埠
    app.run(host='0.0.0.0', port=8080, debug=True)
