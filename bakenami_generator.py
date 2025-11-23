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
