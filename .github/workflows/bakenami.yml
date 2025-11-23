#!/usr/bin/env python3
"""
朝ドラ「ばけばけ」ネット反応動画自動生成システム
毎朝9時に実行して、ネット反応をまとめた3分動画を生成
"""
import os
import json
import time
from datetime import datetime
from pathlib import Path
import google.generativeai as genai
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.service_account import Credentials
import gspread
from moviepy.editor import (
    ImageClip, AudioFileClip, CompositeVideoClip, 
    concatenate_videoclips
)
from PIL import Image, ImageDraw, ImageFont
import io

# ================== 環境変数・認証情報 ==================
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS_JSON')  # JSON文字列
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
YOUTUBE_CHANNEL_ID = os.getenv('YOUTUBE_CHANNEL_ID')
DRIVE_FOLDER_ID = os.getenv('DRIVE_FOLDER_ID')  # 素材保管用フォルダ
BGM_FILE_ID = os.getenv('BGM_FILE_ID')  # BGMファイルのID
BACKGROUND_IMAGE_ID = os.getenv('BACKGROUND_IMAGE_ID')  # 背景画像ID
CHARACTER1_IMAGE_ID = os.getenv('CHARACTER1_IMAGE_ID')  # キャラ1画像ID
CHARACTER2_IMAGE_ID = os.getenv('CHARACTER2_IMAGE_ID')  # キャラ2画像ID

# ワークディレクトリ
WORK_DIR = Path('/tmp/bakenami_work')
WORK_DIR.mkdir(exist_ok=True)


def create_text_clip(text, fontsize=40, color='white', bg_color='black', 
                     duration=1.0, size=(1920, 1080), position='bottom'):
    """PILでテキスト画像を作成してImageClipに変換（TextClipの代替）"""
    
    # 画像作成
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # フォント設定
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", fontsize)
    except Exception as e:
        print(f"⚠ フォント読み込み失敗、デフォルトフォント使用: {e}")
        font = ImageFont.load_default()
    
    # テキストのサイズを取得
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # テキストの配置計算
    padding = 20
    box_width = min(text_width + padding * 2, size[0] - 100)
    box_height = text_height + padding * 2
    
    # 位置によって配置を変える
    if position == 'bottom':
        x = (size[0] - box_width) // 2
        y = size[1] - box_height - 50
    else:  # center
        x = (size[0] - box_width) // 2
        y = (size[1] - box_height) // 2
    
    # 背景矩形（半透明の黒）
    draw.rectangle(
        [x, y, x + box_width, y + box_height],
        fill=(0, 0, 0, 200)
    )
    
    # テキスト描画（複数行対応）
    text_x = x + padding
    text_y = y + padding
    
    # 長いテキストは折り返し
    max_width = box_width - padding * 2
    lines = []
    words = text.split()
    current_line = ""
    
    for word in words:
        test_line = current_line + word + " "
        test_bbox = draw.textbbox((0, 0), test_line, font=font)
        test_width = test_bbox[2] - test_bbox[0]
        
        if test_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word + " "
    
    if current_line:
        lines.append(current_line)
    
    # 各行を描画
    for i, line in enumerate(lines):
        draw.text((text_x, text_y + i * (text_height + 5)), line.strip(), font=font, fill=color)
    
    # 一時ファイルとして保存
    temp_path = WORK_DIR / f"text_temp_{abs(hash(text))}.png"
    img.save(temp_path)
    
    # ImageClipとして返す
    return ImageClip(str(temp_path)).set_duration(duration).set_position(('center', 'bottom'))


class BakenamiVideoGenerator:
    """朝ドラ「ばけばけ」動画生成クラス"""
    
    def __init__(self):
        """初期化"""
        self.timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.row_data = {}
        
        # Google API認証
        self.setup_google_services()
        
        # Gemini API設定
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
        print(f"[{self.timestamp}] システム初期化完了")
    
    def setup_google_services(self):
        """Google各種サービスの認証設定"""
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        self.credentials = Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive',
                'https://www.googleapis.com/auth/youtube.upload',
            ]
        )
        
        # スプレッドシート
        self.gc = gspread.authorize(self.credentials)
        self.sheet = self.gc.open_by_key(SPREADSHEET_ID).sheet1
        
        # Google Drive
        self.drive_service = build('drive', 'v3', credentials=self.credentials)
        
        # YouTube
        self.youtube_service = build('youtube', 'v3', credentials=self.credentials)
    
    def log_to_sheet(self, status, **kwargs):
        """スプレッドシートにログ記録"""
        self.row_data.update({
            'timestamp': self.timestamp,
            'status': status,
            **kwargs
        })
        
        # 新規行追加または既存行更新
        if not hasattr(self, 'sheet_row'):
            self.sheet_row = len(self.sheet.get_all_values()) + 1
            self.sheet.append_row([
                self.timestamp, status, '', '', '', '', '', ''
            ])
        else:
            # ステータス更新
            self.sheet.update_cell(self.sheet_row, 2, status)
    
    def download_from_drive(self, file_id, save_path):
        """Google Driveからファイルダウンロード"""
        if not file_id:
            print(f"⚠ ファイルID未設定: {save_path}")
            return False
            
        try:
            request = self.drive_service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            with open(save_path, 'wb') as f:
                f.write(fh.getvalue())
            
            print(f"✓ ダウンロード完了: {save_path}")
            return True
        except Exception as e:
            print(f"⚠ ダウンロード失敗: {save_path} - {e}")
            return False
    
    def search_bakenami_reactions(self):
        """ネットで朝ドラ「ばけばけ」の反応を検索"""
        print("\n=== STEP 1: ネット反応検索 ===")
        
        search_prompt = """
あなたは情報収集の専門家です。
現在放送中のNHK連続テレビ小説「ばけばけ」について、
SNSやニュースサイトでの視聴者の反応を検索してください。

以下の情報を含めてください：
- 今週のストーリー展開への反応
- 登場人物への感想
- 話題になっているシーン
- 感動的だった場面
- 面白かった・驚いたという意見

検索結果を整理して、JSONフォーマットで返してください：
{
  "reactions": [
    {
      "source": "情報源",
      "content": "反応内容",
      "sentiment": "positive/neutral/negative"
    }
  ],
  "trending_topics": ["トピック1", "トピック2", ...],
  "summary": "全体のまとめ"
}
"""
        
        response = self.model.generate_content(
            search_prompt,
            tools='google_search'
        )
        
        search_result = response.text
        self.log_to_sheet('検索完了', search_result=search_result[:500])
        
        # スプレッドシートに保存
        self.sheet.update_cell(self.sheet_row, 3, search_result[:1000])
        
        return search_result
    
    def generate_script(self, search_result):
        """台本生成（順列風男性2人の対談）"""
        print("\n=== STEP 2: 台本生成 ===")
        
        script_prompt = f"""
あなたは台本作家です。
以下の朝ドラ「ばけばけ」のネット反応をもとに、
高齢女性ファンに人気の「順列」風の男性2人による
トーク番組の台本を作成してください。

【キャラクター設定】
- タクヤ: 明るく情熱的、感情豊か。高音の声。
- ケンジ: 落ち着いた冷静なツッコミ役。低音の声。

【ネット反応データ】
{search_result}

【指示】
1. 3分程度（約900文字）の対談形式で
2. ネット反応を紹介しながら、2人が感想を言い合う
3. 順列風に爽やかで親しみやすいトーン
4. 「視聴者の皆さんこんにちは！」で始める
5. 最後は「また明日お会いしましょう！」で締める

以下のJSONフォーマットで返してください：
{{
  "script": [
    {{"speaker": "タクヤ", "text": "セリフ"}},
    {{"speaker": "ケンジ", "text": "セリフ"}},
    ...
  ],
  "total_chars": 文字数
}}
"""
        
        response = self.model.generate_content(script_prompt)
        script_data = response.text
        
        self.log_to_sheet('台本生成完了')
        self.sheet.update_cell(self.sheet_row, 4, script_data[:1000])
        
        return script_data
    
    def generate_audio(self, script_data):
        """音声生成（Gemini TTS）"""
        print("\n=== STEP 3: 音声生成 ===")
        
        # JSONパース
        try:
            # マークダウンコードブロックを除去
            clean_data = script_data.strip()
            if clean_data.startswith('```json'):
                clean_data = clean_data[7:]
            if clean_data.startswith('```'):
                clean_data = clean_data[3:]
            if clean_data.endswith('```'):
                clean_data = clean_data[:-3]
            
            script_json = json.loads(clean_data.strip())
            script_lines = script_json['script']
        except Exception as e:
            # パースエラー時は簡易処理
            print(f"⚠ JSON解析失敗、簡易モードで処理: {e}")
            script_lines = [
                {"speaker": "タクヤ", "text": "視聴者の皆さんこんにちは！"},
                {"speaker": "ケンジ", "text": "朝ドラばけばけ、話題ですね"}
            ]
        
        audio_files = []
        
        for i, line in enumerate(script_lines):
            speaker = line['speaker']
            text = line['text']
            
            # 音声生成プロンプト
            voice_config = "男性、低音、落ち着いた声" if speaker == "ケンジ" else "男性、高音、明るい声"
            
            audio_prompt = f"""
以下のテキストを{voice_config}で読み上げてください：
{text}
"""
            
            try:
                # Gemini音声生成
                response = self.model.generate_content(
                    audio_prompt,
                    generation_config=genai.types.GenerationConfig(
                        response_mime_type="audio/wav"
                    )
                )
                
                # 音声保存
                audio_path = WORK_DIR / f"audio_{i:03d}_{speaker}.wav"
                with open(audio_path, 'wb') as f:
                    f.write(response.parts[0].inline_data.data)
                
                audio_files.append(audio_path)
                print(f"  ✓ 音声生成: {speaker} ({len(text)}文字)")
                
                time.sleep(1)  # レート制限対策
                
            except Exception as e:
                print(f"  ⚠ 音声生成エラー: {speaker} - {e}")
        
        if not audio_files:
            raise Exception("音声ファイルが1つも生成されませんでした")
        
        # 音声結合
        combined_audio_path = WORK_DIR / "combined_audio.wav"
        self.combine_audio_files(audio_files, combined_audio_path)
        
        self.log_to_sheet('音声生成完了', audio_count=len(audio_files))
        
        return combined_audio_path, script_lines
    
    def combine_audio_files(self, audio_files, output_path):
        """複数音声ファイルを結合"""
        from pydub import AudioSegment
        
        combined = AudioSegment.empty()
        for audio_file in audio_files:
            audio = AudioSegment.from_wav(audio_file)
            combined += audio
            combined += AudioSegment.silent(duration=500)  # 0.5秒の間
        
        combined.export(output_path, format='wav')
        print(f"✓ 音声結合完了: {output_path}")
    
    def generate_subtitles(self, audio_path, script_lines):
        """字幕データ生成（音声と台本の同期）"""
        print("\n=== STEP 4: 字幕生成 ===")
        
        # 簡易タイミング計算（1文字0.2秒と仮定）
        subtitles = []
        current_time = 0.0
        
        for line in script_lines:
            text = line['text']
            speaker = line['speaker']
            duration = len(text) * 0.2 + 0.5
            
            subtitles.append({
                'start': current_time,
                'end': current_time + duration,
                'text': f"{speaker}: {text}",
                'speaker': speaker
            })
            
            current_time += duration + 0.5
        
        return subtitles
    
    def create_video(self, audio_path, subtitles):
        """動画生成"""
        print("\n=== STEP 5: 動画生成 ===")
        
        # 素材ダウンロード
        bg_image_path = WORK_DIR / "background.png"
        char1_image_path = WORK_DIR / "character1.png"
        char2_image_path = WORK_DIR / "character2.png"
        bgm_path = WORK_DIR / "bgm.mp3"
        
        bg_exists = self.download_from_drive(BACKGROUND_IMAGE_ID, bg_image_path)
        char1_exists = self.download_from_drive(CHARACTER1_IMAGE_ID, char1_image_path)
        char2_exists = self.download_from_drive(CHARACTER2_IMAGE_ID, char2_image_path)
        bgm_exists = self.download_from_drive(BGM_FILE_ID, bgm_path)
        
        # 音声読み込み
        audio_clip = AudioFileClip(str(audio_path))
        video_duration = audio_clip.duration
        
        # 背景画像（なければ黒背景）
        if bg_exists:
            bg_clip = ImageClip(str(bg_image_path)).set_duration(video_duration)
        else:
            # 黒背景を作成
            from PIL import Image as PILImage
            black_img = PILImage.new('RGB', (1920, 1080), color='black')
            black_img_path = WORK_DIR / "black_bg.png"
            black_img.save(black_img_path)
            bg_clip = ImageClip(str(black_img_path)).set_duration(video_duration)
        
        # BGM（音量調整）
        if bgm_exists:
            try:
                bgm_clip = AudioFileClip(str(bgm_path)).volumex(0.2)
                bgm_clip = bgm_clip.set_duration(video_duration)
                # 音声とBGMをミックス
                from moviepy.audio.AudioClip import CompositeAudioClip
                final_audio = CompositeAudioClip([audio_clip, bgm_clip])
            except Exception as e:
                print(f"⚠ BGM処理失敗、音声のみ使用: {e}")
                final_audio = audio_clip
        else:
            final_audio = audio_clip
        
        # 字幕クリップ作成（PILで生成）
        subtitle_clips = []
        for sub in subtitles:
            try:
                txt_clip = create_text_clip(
                    text=sub['text'],
                    fontsize=40,
                    color='white',
                    bg_color='black',
                    duration=sub['end'] - sub['start']
                ).set_start(sub['start'])
                
                subtitle_clips.append(txt_clip)
            except Exception as e:
                print(f"⚠ 字幕生成エラー: {e}")
        
        # キャラクター画像（話者によって表示切替）
        char_clips = []
        for sub in subtitles:
            try:
                if sub['speaker'] == 'タクヤ' and char1_exists:
                    char_img = char1_image_path
                elif sub['speaker'] == 'ケンジ' and char2_exists:
                    char_img = char2_image_path
                else:
                    continue
                
                if char_img.exists():
                    char_clip = (ImageClip(str(char_img))
                               .resize(height=400)
                               .set_position((50, 100))
                               .set_start(sub['start'])
                               .set_duration(sub['end'] - sub['start']))
                    char_clips.append(char_clip)
            except Exception as e:
                print(f"⚠ キャラクター画像エラー: {e}")
        
        # 合成
        all_clips = [bg_clip] + char_clips + subtitle_clips
        video = CompositeVideoClip(all_clips)
        video = video.set_audio(final_audio)
        
        # 動画出力
        output_video_path = WORK_DIR / "bakenami_video.mp4"
        video.write_videofile(
            str(output_video_path),
            fps=24,
            codec='libx264',
            audio_codec='aac',
            threads=4,
            preset='medium'
        )
        
        self.log_to_sheet('動画生成完了', duration=video_duration)
        
        return output_video_path
    
    def generate_metadata(self, search_result):
        """YouTube用メタデータ生成"""
        print("\n=== STEP 6: メタデータ生成 ===")
        
        metadata_prompt = f"""
以下の朝ドラ「ばけばけ」反応データから、
YouTube動画のタイトルと説明文を生成してください。

{search_result}

以下のJSONで返してください：
{{
  "title": "【ばけばけ】今日の反応まとめ | {datetime.now().strftime('%Y/%m/%d')}",
  "description": "説明文（300文字程度、出典情報含む）",
  "tags": ["タグ1", "タグ2", ...]
}}
"""
        
        response = self.model.generate_content(metadata_prompt)
        metadata = response.text
        
        self.log_to_sheet('メタデータ生成完了')
        self.sheet.update_cell(self.sheet_row, 5, metadata[:500])
        
        return metadata
    
    def generate_thumbnail(self):
        """サムネイル画像生成"""
        print("\n=== STEP 7: サムネイル生成 ===")
        
        # 背景画像を使用
        bg_image_path = WORK_DIR / "background.png"
        
        if bg_image_path.exists():
            img = Image.open(bg_image_path)
        else:
            # なければ青背景を作成
            img = Image.new('RGB', (1280, 720), color='#4169E1')
        
        # リサイズ（YouTube推奨サイズ）
        img = img.resize((1280, 720))
        
        # テキスト追加
        draw = ImageDraw.Draw(img)
        
        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()
        
        text1 = "朝ドラ「ばけばけ」"
        text2 = "今日の反応"
        
        # テキスト配置
        bbox1 = draw.textbbox((0, 0), text1, font=font_large)
        bbox2 = draw.textbbox((0, 0), text2, font=font_small)
        
        x1 = (img.width - (bbox1[2] - bbox1[0])) // 2
        y1 = 100
        x2 = (img.width - (bbox2[2] - bbox2[0])) // 2
        y2 = 200
        
        # 縁取り（黒）
        for offset_x in [-3, 0, 3]:
            for offset_y in [-3, 0, 3]:
                draw.text((x1 + offset_x, y1 + offset_y), text1, font=font_large, fill='black')
                draw.text((x2 + offset_x, y2 + offset_y), text2, font=font_small, fill='black')
        
        # メインテキスト（黄色）
        draw.text((x1, y1), text1, font=font_large, fill='yellow')
        draw.text((x2, y2), text2, font=font_small, fill='yellow')
        
        thumbnail_path = WORK_DIR / "thumbnail.png"
        img.save(thumbnail_path)
        
        print(f"✓ サムネイル生成完了: {thumbnail_path}")
        
        return thumbnail_path
    
    def upload_to_youtube(self, video_path, metadata, thumbnail_path):
        """YouTube自動アップロード"""
        print("\n=== STEP 8: YouTubeアップロード ===")
        
        try:
            # マークダウンコードブロックを除去
            clean_metadata = metadata.strip()
            if clean_metadata.startswith('```json'):
                clean_metadata = clean_metadata[7:]
            if clean_metadata.startswith('```'):
                clean_metadata = clean_metadata[3:]
            if clean_metadata.endswith('```'):
                clean_metadata = clean_metadata[:-3]
            
            metadata_json = json.loads(clean_metadata.strip())
        except Exception as e:
            print(f"⚠ メタデータ解析失敗、デフォルト値使用: {e}")
            metadata_json = {
                'title': f"朝ドラ「ばけばけ」反応まとめ {datetime.now().strftime('%Y/%m/%d')}",
                'description': "本日の朝ドラ「ばけばけ」のネット反応をまとめました。",
                'tags': ["ばけばけ", "朝ドラ", "NHK"]
            }
        
        body = {
            'snippet': {
                'title': metadata_json['title'],
                'description': metadata_json['description'],
                'tags': metadata_json.get('tags', ["ばけばけ", "朝ドラ"]),
                'categoryId': '24'  # エンターテイメント
            },
            'status': {
                'privacyStatus': 'public',
                'selfDeclaredMadeForKids': False
            }
        }
        
        # 動画アップロード
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        request = self.youtube_service.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )
        
        response = request.execute()
        video_id = response['id']
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        
        # サムネイルアップロード
        try:
            self.youtube_service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()
            print("✓ サムネイルアップロード完了")
        except Exception as e:
            print(f"⚠ サムネイルアップロード失敗: {e}")
        
        print(f"✓ アップロード完了: {video_url}")
        
        self.log_to_sheet('YouTube公開完了', video_url=video_url)
        self.sheet.update_cell(self.sheet_row, 6, video_url)
        
        return video_url
    
    def run(self):
        """メイン処理実行"""
        try:
            print("=" * 60)
            print("朝ドラ「ばけばけ」反応動画自動生成 開始")
            print("=" * 60)
            
            start_time = time.time()
            
            # STEP 1: ネット反応検索
            self.log_to_sheet('実行中')
            search_result = self.search_bakenami_reactions()
            
            # STEP 2: 台本生成
            script_data = self.generate_script(search_result)
            
            # STEP 3: 音声生成
            audio_path, script_lines = self.generate_audio(script_data)
            
            # STEP 4: 字幕生成
            subtitles = self.generate_subtitles(audio_path, script_lines)
            
            # STEP 5: 動画生成
            video_path = self.create_video(audio_path, subtitles)
            
            # STEP 6: メタデータ生成
            metadata = self.generate_metadata(search_result)
            
            # STEP 7: サムネイル生成
            thumbnail_path = self.generate_thumbnail()
            
            # STEP 8: YouTubeアップロード
            video_url = self.upload_to_youtube(video_path, metadata, thumbnail_path)
            
            # 完了
            elapsed_time = time.time() - start_time
            self.log_to_sheet('完了', elapsed_time=f"{elapsed_time:.1f}秒")
            self.sheet.update_cell(self.sheet_row, 7, f"{elapsed_time:.1f}秒")
            
            print("\n" + "=" * 60)
            print(f"✅ 処理完了！（所要時間: {elapsed_time:.1f}秒）")
            print(f"📺 動画URL: {video_url}")
            print("=" * 60)
            
        except Exception as e:
            print(f"\n❌ エラー発生: {e}")
            import traceback
            traceback.print_exc()
            self.log_to_sheet('エラー', error=str(e))
            raise


if __name__ == '__main__':
    generator = BakenamiVideoGenerator()
    generator.run()
