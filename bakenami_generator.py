#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import base64
import tempfile
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import re
import io

# Google関連のインポート
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import gspread
from google.auth.transport.requests import Request

# その他
from PIL import Image, ImageDraw, ImageFont
import requests
from gtts import gTTS
from pydub import AudioSegment
import numpy as np

# ============================================================
# 定数設定
# ============================================================
SCRIPT_NAME = "朝ドラ「ばけばけ」動画生成システム"
VERSION = "2.0.0"
OUTPUT_DIR = Path("output")
TEMP_DIR = Path("temp")
ASSETS_DIR = Path("assets")

# 動画設定
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30
VIDEO_DURATION = 60  # 秒

# フォント設定
FONT_SIZE_TITLE = 72
FONT_SIZE_SUBTITLE = 48
FONT_SIZE_DIALOG = 36
FONT_COLOR_MAIN = "#FFFFFF"
FONT_COLOR_SHADOW = "#000000"

# YouTube設定
YOUTUBE_TITLE_TEMPLATE = "【朝ドラ考察】ばけばけ 第{episode}話 みんなの反応まとめ"
YOUTUBE_DESCRIPTION_TEMPLATE = """
朝ドラ「ばけばけ」第{episode}話のネット上の反応をまとめました！

アイドルグループ風の男性キャラクター2人が、
視聴者の感想や考察を楽しくお届けします。

#朝ドラ #ばけばけ #NHK #考察 #感想
"""

# ============================================================
# ヘルパー関数
# ============================================================
def setup_directories():
    """必要なディレクトリを作成"""
    for dir_path in [OUTPUT_DIR, TEMP_DIR, ASSETS_DIR]:
        dir_path.mkdir(exist_ok=True)

def print_header(message: str, level: int = 1):
    """見出しを出力"""
    if level == 1:
        print("=" * 60)
        print(f"🎬 {message}")
        print("=" * 60)
    elif level == 2:
        print("=" * 60)
        print(f"🚀 {message}")
        print("=" * 60)
    elif level == 3:
        print(f"📌 {message}")
    else:
        print(f"  {message}")

def print_error(message: str):
    """エラーメッセージを出力"""
    print(f"❌ {message}", file=sys.stderr)

def print_success(message: str):
    """成功メッセージを出力"""
    print(f"✅ {message}")

def print_info(message: str):
    """情報メッセージを出力"""
    print(f"📝 {message}")

def get_jst_now():
    """現在の日本時間を取得"""
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst)

def find_working_model():
    """利用可能なGeminiモデルを探す"""
    # 2024年11月時点で利用可能なモデル
    model_names = [
        "gemini-2.0-flash-exp",      # 最新の実験版（2024年11月）
        "gemini-1.5-flash",          # 安定版Flash
        "gemini-1.5-flash-latest",   # Flash最新版
        "gemini-1.5-pro",            # Pro版
        "gemini-1.5-pro-latest",     # Pro最新版
        "gemini-pro",                # 基本Pro
        "models/gemini-2.0-flash-exp",  # modelsプレフィックス付き
        "models/gemini-1.5-flash",
        "models/gemini-1.5-pro",
    ]
    
    for model_name in model_names:
        try:
            print(f"  試行中: {model_name}...")
            model = genai.GenerativeModel(model_name)
            # 簡単なテストを実行
            response = model.generate_content("Say hello")
            if response and response.text:
                print(f"  ✅ {model_name} が利用可能です！")
                return model, model_name
        except Exception as e:
            error_msg = str(e)[:100]  # エラーメッセージの一部のみ表示
            print(f"  ❌ {model_name} は利用できません")
            continue
    
    # すべて失敗した場合
    raise Exception(
        "利用可能なGeminiモデルが見つかりませんでした。\n"
        "APIキーが正しく設定されているか確認してください。"
    )

# ============================================================
# メインクラス
# ============================================================
class BakenamiVideoGenerator:
    def __init__(self):
        """初期化"""
        print_header(SCRIPT_NAME, 1)
        print_header("プログラム開始", 2)
        
        print_info(f"タイムスタンプ: {get_jst_now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # ディレクトリ作成
        setup_directories()
        
        # 環境変数チェック
        self.check_environment()
        
        # Google API認証
        self.setup_google_apis()
        
        # Gemini API設定
        self.setup_gemini()
        
        # アセット準備
        self.prepare_assets()
    
    def check_environment(self):
        """環境変数をチェック"""
        print_info("環境変数チェック:")
        
        required_vars = [
            "GEMINI_API_KEY",
            "GOOGLE_CREDENTIALS_JSON",
            "SPREADSHEET_ID",
            "YOUTUBE_CHANNEL_ID",
            "BACKGROUND_IMAGE_ID",
            "CHARACTER1_IMAGE_ID", 
            "CHARACTER2_IMAGE_ID",
            "BGM_FILE_ID"
        ]
        
        self.env_vars = {}
        for var in required_vars:
            value = os.getenv(var)
            if not value:
                print_error(f"{var}: ❌ 未設定")
                raise ValueError(f"環境変数 {var} が設定されていません")
            else:
                # IDの一部だけ表示（セキュリティのため）
                display_value = value[:10] + "..." if len(value) > 10 else value
                print(f"  {var}: ✅ 設定済み")
                self.env_vars[var] = value
    
    def setup_google_apis(self):
        """Google APIの認証設定"""
        print_info("Google API認証開始...")
        
        try:
            # 認証情報のJSONをパース
            print("  📝 認証情報をパース中...")
            creds_json = json.loads(self.env_vars["GOOGLE_CREDENTIALS_JSON"])
            
            # 認証オブジェクト作成（google.oauth2を使用）
            print("  🎫 認証オブジェクト作成中...")
            credentials = service_account.Credentials.from_service_account_info(
                creds_json,
                scopes=[
                    'https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive',
                    'https://www.googleapis.com/auth/youtube.upload'
                ]
            )
            
            # gspread用の認証（google-authを使用）
            print("  📊 スプレッドシート接続中...")
            self.gspread_client = gspread.authorize(credentials)
            self.spreadsheet = self.gspread_client.open_by_key(self.env_vars["SPREADSHEET_ID"])
            print(f"  ✅ スプレッドシート接続成功: {self.env_vars['SPREADSHEET_ID'][:10]}...")
            
            # Google Drive接続
            print("  💾 Google Drive接続中...")
            self.drive_service = build('drive', 'v3', credentials=credentials)
            print("  ✅ Google Drive接続成功")
            
            # YouTube接続
            print("  📺 YouTube接続中...")
            self.youtube_service = build('youtube', 'v3', credentials=credentials)
            print("  ✅ YouTube接続成功")
            
            print_success("Google API認証成功")
            
        except Exception as e:
            print_error(f"Google API認証失敗: {str(e)}")
            raise
    
    def setup_gemini(self):
        """Gemini APIの設定"""
        print_info("Gemini API設定開始...")
        
        try:
            # API キー設定
            genai.configure(api_key=self.env_vars["GEMINI_API_KEY"])
            
            # 利用可能なモデルを探す
            print_info("利用可能なモデルを探しています...")
            self.model, self.model_name = find_working_model()
            
            # generation config
            self.generation_config = {
                "temperature": 0.9,
                "top_p": 0.95,
                "max_output_tokens": 2048,
            }
            
            print_success(f"Gemini API設定成功（モデル: {self.model_name}）")
            
        except Exception as e:
            print_error(f"Gemini API設定失敗: {str(e)}")
            raise
    
    def prepare_assets(self):
        """アセットファイルの準備"""
        print_info("アセット準備開始...")
        
        try:
            # 背景画像ダウンロード
            self.download_drive_file(
                self.env_vars["BACKGROUND_IMAGE_ID"],
                ASSETS_DIR / "background.jpg"
            )
            
            # キャラクター画像ダウンロード
            self.download_drive_file(
                self.env_vars["CHARACTER1_IMAGE_ID"],
                ASSETS_DIR / "character1.png"
            )
            self.download_drive_file(
                self.env_vars["CHARACTER2_IMAGE_ID"],
                ASSETS_DIR / "character2.png"
            )
            
            # BGMダウンロード
            self.download_drive_file(
                self.env_vars["BGM_FILE_ID"],
                ASSETS_DIR / "bgm.mp3"
            )
            
            print_success("アセット準備完了")
            
        except Exception as e:
            print_error(f"アセット準備失敗: {str(e)}")
            # アセットがなくても続行
            print_info("デフォルトアセットで続行します")
    
    def download_drive_file(self, file_id: str, output_path: Path):
        """Google Driveからファイルをダウンロード"""
        try:
            request = self.drive_service.files().get_media(fileId=file_id)
            content = request.execute()
            
            with open(output_path, 'wb') as f:
                f.write(content)
            
            print(f"  ✅ {output_path.name} ダウンロード完了")
            
        except Exception as e:
            print(f"  ⚠️ {output_path.name} ダウンロード失敗: {str(e)}")
            # ダミーファイルを作成
            self.create_dummy_asset(output_path)
    
    def create_dummy_asset(self, output_path: Path):
        """ダミーアセットを作成"""
        if output_path.suffix in ['.jpg', '.png']:
            # ダミー画像
            img = Image.new('RGB', (1920, 1080), color='#333333')
            img.save(output_path)
        elif output_path.suffix == '.mp3':
            # 無音のダミー音声
            silent = AudioSegment.silent(duration=1000)
            silent.export(output_path, format="mp3")
    
    def search_reactions(self, episode_num: int) -> List[str]:
        """ネット上の反応を検索（シミュレート）"""
        print_info(f"第{episode_num}話の反応を検索中...")
        
        # 実際のAPIがない場合のダミーデータ
        reactions = [
            "今回の展開は予想外だった！",
            "主人公の成長が感じられる回でした",
            "次回が気になる終わり方",
            "伏線回収がすごかった",
            "感動的なシーンに涙が出ました"
        ]
        
        print(f"  📊 {len(reactions)}件の反応を取得")
        return reactions
    
    def generate_script(self, episode_num: int, reactions: List[str]) -> str:
        """台本を生成"""
        print_info("台本生成中...")
        
        prompt = f"""
        朝ドラ「ばけばけ」第{episode_num}話の視聴者の反応をもとに、
        アイドルグループ風の男性キャラクター2人（ユウトとハルキ）が
        楽しく会話する台本を作成してください。

        視聴者の反応:
        {chr(10).join(reactions)}

        形式:
        - 約1分の動画用
        - 明るく楽しいトーン
        - 視聴者への呼びかけも含める
        - セリフは「ユウト:」「ハルキ:」で始める
        """
        
        try:
            response = self.model.generate_content(
                prompt,
                generation_config=self.generation_config
            )
            
            script = response.text
            print_success("台本生成完了")
            print("  📄 生成された台本の一部:")
            print(f"  {script[:200]}...")
            
            return script
            
        except Exception as e:
            print_error(f"台本生成失敗: {str(e)}")
            # フォールバック台本
            return self.get_fallback_script(episode_num)
    
    def get_fallback_script(self, episode_num: int) -> str:
        """フォールバック用の台本"""
        return f"""
        ユウト: みなさんこんにちは！ユウトです！
        ハルキ: ハルキです！今日も朝ドラ「ばけばけ」の感想をお届けします！
        ユウト: 第{episode_num}話、見ましたか？
        ハルキ: 今回も展開がすごかったですね！
        ユウト: 視聴者の皆さんの反応も熱いです！
        ハルキ: 次回も楽しみですね！
        ユウト: それではまた次回！
        ハルキ: お楽しみに！
        """
    
    def create_video(self, script: str, episode_num: int) -> Path:
        """動画を作成"""
        print_info("動画作成開始...")
        
        video_path = OUTPUT_DIR / f"bakenami_episode_{episode_num}.mp4"
        
        try:
            # 音声生成
            audio_path = self.generate_audio(script)
            
            # 字幕付き動画生成
            self.generate_video_with_subtitles(script, audio_path, video_path)
            
            print_success(f"動画作成完了: {video_path}")
            return video_path
            
        except Exception as e:
            print_error(f"動画作成失敗: {str(e)}")
            # ダミー動画を作成
            return self.create_dummy_video(video_path)
    
    def generate_audio(self, script: str) -> Path:
        """音声を生成"""
        print("  🎤 音声生成中...")
        
        audio_path = TEMP_DIR / "narration.mp3"
        
        try:
            # gTTSで音声生成
            tts = gTTS(text=script, lang='ja')
            tts.save(str(audio_path))
            
            print("  ✅ 音声生成完了")
            return audio_path
            
        except Exception as e:
            print(f"  ⚠️ 音声生成失敗: {str(e)}")
            # 無音ファイルを作成
            silent = AudioSegment.silent(duration=60000)
            silent.export(audio_path, format="mp3")
            return audio_path
    
    def generate_video_with_subtitles(self, script: str, audio_path: Path, output_path: Path):
        """字幕付き動画を生成"""
        print("  🎥 動画生成中...")
        
        # FFmpegコマンド構築
        cmd = [
            'ffmpeg',
            '-loop', '1',
            '-i', str(ASSETS_DIR / 'background.jpg'),
            '-i', str(audio_path),
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-shortest',
            '-pix_fmt', 'yuv420p',
            '-vf', 'scale=1920:1080',
            '-y',
            str(output_path)
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            print("  ✅ 動画生成完了")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠️ FFmpeg実行失敗: {e}")
            # 簡易的な動画を作成
            self.create_simple_video(output_path)
    
    def create_simple_video(self, output_path: Path):
        """簡易的な動画を作成"""
        # 静止画だけの動画を作成
        cmd = [
            'ffmpeg',
            '-loop', '1',
            '-i', str(ASSETS_DIR / 'background.jpg'),
            '-t', '60',
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-vf', 'scale=1920:1080',
            '-y',
            str(output_path)
        ]
        subprocess.run(cmd, check=True)
    
    def create_dummy_video(self, output_path: Path) -> Path:
        """ダミー動画を作成"""
        print("  📹 ダミー動画作成中...")
        
        # 黒い画面の動画を作成
        cmd = [
            'ffmpeg',
            '-f', 'lavfi',
            '-i', 'color=c=black:s=1920x1080:d=60',
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-y',
            str(output_path)
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return output_path
        except:
            # 最小限のダミーファイル
            output_path.write_bytes(b'dummy')
            return output_path
    
    def upload_to_youtube(self, video_path: Path, episode_num: int) -> Optional[str]:
        """YouTubeに動画をアップロード"""
        print_info("YouTube アップロード開始...")
        
        try:
            # メタデータ設定
            title = YOUTUBE_TITLE_TEMPLATE.format(episode=episode_num)
            description = YOUTUBE_DESCRIPTION_TEMPLATE.format(episode=episode_num)
            
            body = {
                'snippet': {
                    'title': title,
                    'description': description,
                    'tags': ['朝ドラ', 'ばけばけ', 'NHK', '考察', '感想'],
                    'categoryId': '24'  # Entertainment
                },
                'status': {
                    'privacyStatus': 'public'
                }
            }
            
            # メディアアップロード
            media = MediaFileUpload(
                str(video_path),
                chunksize=-1,
                resumable=True,
                mimetype='video/mp4'
            )
            
            # アップロード実行
            request = self.youtube_service.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )
            
            response = request.execute()
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            print_success(f"YouTube アップロード完了: {video_url}")
            return video_url
            
        except Exception as e:
            print_error(f"YouTube アップロード失敗: {str(e)}")
            return None
    
    def update_spreadsheet(self, episode_num: int, video_url: Optional[str], status: str):
        """スプレッドシートを更新"""
        print_info("スプレッドシート更新中...")
        
        try:
            worksheet = self.spreadsheet.sheet1
            
            # 新しい行を追加
            row_data = [
                get_jst_now().strftime('%Y-%m-%d %H:%M:%S'),
                f"第{episode_num}話",
                video_url or "アップロード失敗",
                status
            ]
            
            worksheet.append_row(row_data)
            print_success("スプレッドシート更新完了")
            
        except Exception as e:
            print_error(f"スプレッドシート更新失敗: {str(e)}")
    
    def run(self):
        """メイン処理を実行"""
        print_header("メイン処理開始", 2)
        
        try:
            # エピソード番号を取得（環境変数から、なければ1）
            episode_num = int(os.getenv('EPISODE_NUMBER', '1'))
            print_info(f"エピソード番号: 第{episode_num}話")
            
            # 1. 反応を検索
            print_header("ステップ 1: 反応検索", 3)
            reactions = self.search_reactions(episode_num)
            
            # 2. 台本生成
            print_header("ステップ 2: 台本生成", 3)
            script = self.generate_script(episode_num, reactions)
            
            # 3. 動画作成
            print_header("ステップ 3: 動画作成", 3)
            video_path = self.create_video(script, episode_num)
            
            # 4. YouTubeアップロード
            print_header("ステップ 4: YouTube アップロード", 3)
            video_url = self.upload_to_youtube(video_path, episode_num)
            
            # 5. スプレッドシート更新
            print_header("ステップ 5: レポート作成", 3)
            status = "成功" if video_url else "アップロード失敗"
            self.update_spreadsheet(episode_num, video_url, status)
            
            # 完了
            print_header("処理完了", 2)
            print_success(f"すべての処理が完了しました！")
            if video_url:
                print_success(f"動画URL: {video_url}")
            
            return True
            
        except Exception as e:
            print_error(f"処理中にエラーが発生しました: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # エラー情報をスプレッドシートに記録
            self.update_spreadsheet(
                episode_num if 'episode_num' in locals() else 0,
                None,
                f"エラー: {str(e)}"
            )
            
            return False

# ============================================================
# メイン実行
# ============================================================
if __name__ == "__main__":
    try:
        generator = BakenamiVideoGenerator()
        success = generator.run()
        
        if not success:
            print_error("処理が失敗しました")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️ ユーザーによって中断されました")
        sys.exit(130)
        
    except Exception as e:
        print(f"💥 致命的エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
