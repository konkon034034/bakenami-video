#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ばけばけ動画自動生成システム
毎日、ネットの感想を検索して2人のキャラクターの会話動画を作成し、YouTubeにアップロード
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path

# Google APIs
import google.generativeai as genai
from google.cloud import texttospeech
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import gspread

# 画像・動画処理
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (
    ImageClip, AudioFileClip, CompositeVideoClip, 
    concatenate_videoclips, concatenate_audioclips, TextClip, CompositeAudioClip
)
from pydub import AudioSegment

# その他
import requests


# ========================================
# 設定
# ========================================

# 環境変数から取得
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
YOUTUBE_CHANNEL_ID = os.environ.get('YOUTUBE_CHANNEL_ID')
BACKGROUND_IMAGE_ID = os.environ.get('BACKGROUND_IMAGE_ID')
CHARACTER1_IMAGE_ID = os.environ.get('CHARACTER1_IMAGE_ID')
CHARACTER2_IMAGE_ID = os.environ.get('CHARACTER2_IMAGE_ID')
BGM_FILE_ID = os.environ.get('BGM_FILE_ID')
EPISODE_NUMBER = int(os.environ.get('EPISODE_NUMBER', '1'))

# キャラクター設定（デフォルト値）
CHARACTER1_NAME = "ソウタ"
CHARACTER2_NAME = "ハルト"
CHARACTER1_PERSONALITY = "明るくて元気、感情表現が豊か"
CHARACTER2_PERSONALITY = "落ち着いていてクール、的確な分析が得意"
PROGRAM_NAME = "ばけばけ"
SEARCH_KEYWORDS = "ばけばけ 朝ドラ 感想"

# 作業ディレクトリ
WORK_DIR = Path("./work")
WORK_DIR.mkdir(exist_ok=True)


# ========================================
# スプレッドシートから設定を読み込む
# ========================================

def load_config_from_spreadsheet():
    """スプレッドシートから設定を読み込む"""
    global CHARACTER1_NAME, CHARACTER2_NAME, CHARACTER1_PERSONALITY, CHARACTER2_PERSONALITY
    global PROGRAM_NAME, SEARCH_KEYWORDS, EPISODE_NUMBER
    
    try:
        print("📋 スプレッドシートから設定を読み込み中...")
        
        credentials = service_account.Credentials.from_service_account_file(
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'],
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        gc = gspread.authorize(credentials)
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        
        # 「設定」シートを開く（なければ作成）
        try:
            config_sheet = spreadsheet.worksheet('設定')
        except:
            print("  ℹ️ 設定シートが見つかりません。デフォルト値を使用します。")
            return
        
        # 設定を読み込む
        config_data = config_sheet.get_all_values()
        config_dict = {}
        
        for row in config_data:
            if len(row) >= 2:
                config_dict[row[0]] = row[1]
        
        # 設定を更新
        if '番組名' in config_dict:
            PROGRAM_NAME = config_dict['番組名']
        if '検索キーワード' in config_dict:
            SEARCH_KEYWORDS = config_dict['検索キーワード']
        if 'キャラクター1名前' in config_dict:
            CHARACTER1_NAME = config_dict['キャラクター1名前']
        if 'キャラクター1性格' in config_dict:
            CHARACTER1_PERSONALITY = config_dict['キャラクター1性格']
        if 'キャラクター2名前' in config_dict:
            CHARACTER2_NAME = config_dict['キャラクター2名前']
        if 'キャラクター2性格' in config_dict:
            CHARACTER2_PERSONALITY = config_dict['キャラクター2性格']
        if 'エピソード番号' in config_dict and config_dict['エピソード番号']:
            EPISODE_NUMBER = int(config_dict['エピソード番号'])
        
        print(f"  ✅ 設定を読み込みました:")
        print(f"     番組名: {PROGRAM_NAME}")
        print(f"     {CHARACTER1_NAME} ({CHARACTER1_PERSONALITY})")
        print(f"     {CHARACTER2_NAME} ({CHARACTER2_PERSONALITY})")
        print(f"     エピソード: 第{EPISODE_NUMBER}話")
        
    except Exception as e:
        print(f"  ⚠️ 設定の読み込みに失敗: {e}")
        print(f"  ℹ️ デフォルト値を使用します")


# ========================================
# Google認証情報の準備
# ========================================

def setup_google_credentials():
    """Google認証情報をファイルに保存"""
    credentials_path = WORK_DIR / "credentials.json"
    with open(credentials_path, 'w') as f:
        f.write(GOOGLE_CREDENTIALS_JSON)
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(credentials_path)
    return credentials_path


# ========================================
# スプレッドシートから設定を読み込む
# ========================================

def load_settings_from_spreadsheet():
    """
    スプレッドシートから設定（プロンプト等）を読み込む
    """
    print("📋 スプレッドシートから設定を読み込み中...")
    
    try:
        credentials = service_account.Credentials.from_service_account_file(
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'],
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        gc = gspread.authorize(credentials)
        
        # スプレッドシートを開く
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        
        # 「設定」シートを取得（なければ作成）
        try:
            settings_sheet = spreadsheet.worksheet('設定')
        except:
            # シートが存在しない場合はデフォルト設定を返す
            print("⚠️ 「設定」シートが見つかりません。デフォルト設定を使用します。")
            return get_default_settings()
        
        # シートからデータを取得（A列: 項目名, B列: 値）
        all_values = settings_sheet.get_all_values()
        
        # 辞書に変換
        settings = {}
        for row in all_values:
            if len(row) >= 2 and row[0]:  # A列とB列が両方ある場合
                settings[row[0]] = row[1]
        
        print(f"✅ 設定を読み込みました: {len(settings)}個の項目")
        return settings
        
    except Exception as e:
        print(f"⚠️ 設定の読み込みに失敗: {e}")
        print("デフォルト設定を使用します。")
        return get_default_settings()


def get_default_settings():
    """デフォルト設定を返す"""
    return {
        '検索プロンプト': '朝ドラ「ばけばけ」の第{EPISODE}話についての、X（旧Twitter）での感想を5つ生成してください。リアルな感想風に、短めの文章で、様々な視点から書いてください。',
        '会話生成プロンプト': 'あなたは朝ドラ「ばけばけ」の感想を語る2人組のアイドルです。以下の感想をもとに、{CHARACTER1}と{CHARACTER2}の自然な会話を作成してください。',
        'キャラクター1名前': 'ソウタ',
        'キャラクター2名前': 'ハルト',
        'キャラクター1設定': '明るくて元気、感情表現が豊か',
        'キャラクター2設定': '落ち着いていてクール、的確な分析が得意',
    }


# ========================================
# 1. ネットから感想を検索
# ========================================

def search_reactions():
    """
    Gemini APIを使って番組の最新の感想を生成
    スプレッドシートの設定を使用
    """
    print("📱 感想を検索中...")
    
    # Gemini API設定
    genai.configure(api_key=GEMINI_API_KEY)
    
    # デバッグ: 利用可能なモデルを確認
    try:
        print("🔍 利用可能なモデルを確認中...")
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"  ✓ {m.name}")
    except Exception as e:
        print(f"⚠️ モデル一覧の取得に失敗: {e}")
    
    model = genai.GenerativeModel('models/gemini-2.5-flash')
    
    # プロンプト（スプレッドシートの設定を使用）
    prompt = f"""
朝ドラ「{PROGRAM_NAME}」の第{EPISODE_NUMBER}話についての、X（旧Twitter）での感想を5つ生成してください。
検索キーワード: {SEARCH_KEYWORDS}

リアルな感想風に、短めの文章で、様々な視点から書いてください。

出力形式：
1. （感想1）
2. （感想2）
3. （感想3）
4. （感想4）
5. （感想5）
"""
    
    response = model.generate_content(prompt)
    reactions = response.text
    
    print(f"✅ 感想を取得しました:\n{reactions}")
    return reactions


# ========================================
# 2. 会話スクリプト生成
# ========================================

def generate_script(reactions):
    """
    2人のキャラクターの会話スクリプトを生成
    スプレッドシートの設定を使用
    """
    print("💬 会話スクリプトを生成中...")
    
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('models/gemini-2.5-flash')
    
    prompt = f"""
あなたは朝ドラ「{PROGRAM_NAME}」の感想を語る2人組のアイドルです。

【キャラクター設定】
- {CHARACTER1_NAME}：{CHARACTER1_PERSONALITY}
- {CHARACTER2_NAME}：{CHARACTER2_PERSONALITY}

以下の感想をもとに、2人の自然な会話を作成してください。

【感想】
{reactions}

【出力形式】
{CHARACTER1_NAME}：（セリフ）
{CHARACTER2_NAME}：（セリフ）
...

【条件】
- 会話は10〜15往復程度
- 自然な口調で
- 感想に対するリアクションや考察を入れる
- 最後は次回への期待で締める
"""
    
    response = model.generate_content(prompt)
    script = response.text
    
    print(f"✅ スクリプト生成完了:\n{script}")
    
    # スクリプトをパースして保存
    save_script(script)
    
    return script


def save_script(script):
    """スクリプトをスプレッドシートに保存"""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'],
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        gc = gspread.authorize(credentials)
        sheet = gc.open_by_key(SPREADSHEET_ID).sheet1
        
        # 新しい行として追加
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([timestamp, EPISODE_NUMBER, script])
        print("✅ スクリプトをスプレッドシートに保存しました")
    except Exception as e:
        print(f"⚠️ スプレッドシート保存エラー: {e}")


# ========================================
# 3. 音声生成
# ========================================

def generate_audio(script):
    """
    Google Text-to-Speechで音声を生成
    """
    print("🎤 音声を生成中...")
    
    client = texttospeech.TextToSpeechClient()
    
    # スクリプトを行ごとに分割
    lines = script.strip().split('\n')
    audio_files = []
    
    # 音声設定
    voice_config = {
        CHARACTER1_NAME: texttospeech.VoiceSelectionParams(
            language_code="ja-JP",
            name="ja-JP-Neural2-C",  # 男性音声1
        ),
        CHARACTER2_NAME: texttospeech.VoiceSelectionParams(
            language_code="ja-JP",
            name="ja-JP-Neural2-D",  # 男性音声2
        )
    }
    
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )
    
    for i, line in enumerate(lines):
        if not line.strip() or '：' not in line:
            continue
        
        # キャラクター名とセリフを分離
        character, text = line.split('：', 1)
        character = character.strip()
        text = text.strip()
        
        if character not in voice_config:
            continue
        
        # 音声合成
        synthesis_input = texttospeech.SynthesisInput(text=text)
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice_config[character],
            audio_config=audio_config
        )
        
        # 音声ファイルを保存
        audio_path = WORK_DIR / f"audio_{i:03d}.mp3"
        with open(audio_path, 'wb') as f:
            f.write(response.audio_content)
        
        audio_files.append({
            'character': character,
            'text': text,
            'path': audio_path
        })
        
        print(f"  ✅ {character}: {text[:30]}...")
    
    print(f"✅ {len(audio_files)}個の音声ファイルを生成しました")
    return audio_files


# ========================================
# 4. 動画生成
# ========================================

def download_from_drive(file_id, output_path):
    """Google Driveからファイルをダウンロード（Google Drive API使用）"""
    from googleapiclient.http import MediaIoBaseDownload
    import io
    
    credentials = service_account.Credentials.from_service_account_file(
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'],
        scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    
    service = build('drive', 'v3', credentials=credentials)
    
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    
    done = False
    while not done:
        status, done = downloader.next_chunk()
    
    fh.seek(0)
    with open(output_path, 'wb') as f:
        f.write(fh.read())


def create_video(audio_files):
    """
    動画を生成
    """
    print("🎬 動画を生成中...")
    
    # 素材をダウンロード
    bg_path = WORK_DIR / "background.png"
    char1_path = WORK_DIR / "character1.png"
    char2_path = WORK_DIR / "character2.png"
    bgm_path = WORK_DIR / "bgm.mp3"
    
    download_from_drive(BACKGROUND_IMAGE_ID, bg_path)
    download_from_drive(CHARACTER1_IMAGE_ID, char1_path)
    download_from_drive(CHARACTER2_IMAGE_ID, char2_path)
    download_from_drive(BGM_FILE_ID, bgm_path)
    
    print("  ✅ 素材をダウンロードしました")
    
    # 動画クリップを作成
    clips = []
    current_time = 0
    
    bg_image = Image.open(bg_path)
    char1_image = Image.open(char1_path)
    char2_image = Image.open(char2_path)
    
    for audio_info in audio_files:
        # 音声の長さを取得
        audio = AudioSegment.from_mp3(audio_info['path'])
        duration = len(audio) / 1000.0  # 秒単位
        
        # 背景画像
        bg_clip = ImageClip(str(bg_path)).set_duration(duration).set_start(current_time)
        
        # キャラクター画像（話している方を強調）
        if audio_info['character'] == CHARACTER1_NAME:
            char_clip = ImageClip(str(char1_path)).set_duration(duration).set_start(current_time)
        else:
            char_clip = ImageClip(str(char2_path)).set_duration(duration).set_start(current_time)
        
        # 字幕（背景付きで見やすく）
        try:
            txt_clip = TextClip(
                audio_info['text'],
                fontsize=48,
                color='white',
                font='Noto-Sans-CJK-JP-Bold',  # 日本語フォント
                size=(1100, None),
                method='caption',
                align='center',
                stroke_color='black',
                stroke_width=3
            ).set_duration(duration).set_start(current_time).set_position(('center', 'bottom'))
        except:
            # フォントが見つからない場合は別のフォントを試す
            print(f"  ⚠️ Noto-Sans-CJK-JP-Boldが見つかりません。代替フォントを使用します。")
            txt_clip = TextClip(
                audio_info['text'],
                fontsize=48,
                color='white',
                size=(1100, None),
                method='caption',
                align='center',
                stroke_color='black',
                stroke_width=3
            ).set_duration(duration).set_start(current_time).set_position(('center', 'bottom'))
        
        # 音声
        audio_clip = AudioFileClip(str(audio_info['path'])).set_start(current_time)
        
        clips.append({
            'video': [bg_clip, char_clip, txt_clip],
            'audio': audio_clip
        })
        
        current_time += duration
    
    # 動画を合成
    video_clips = []
    audio_clips = []
    
    for clip_set in clips:
        video_clips.extend(clip_set['video'])
        audio_clips.append(clip_set['audio'])
    
    final_video = CompositeVideoClip(video_clips)
    final_audio = CompositeAudioClip(audio_clips)
    final_video = final_video.set_audio(final_audio)
    
    # BGMを追加（音量を下げる）
    bgm_audio = AudioFileClip(str(bgm_path)).volumex(0.2)
    
    # BGMの長さが動画より短い場合はループさせる
    if bgm_audio.duration < final_video.duration:
        # 必要な回数だけBGMをループ
        n_loops = int(final_video.duration / bgm_audio.duration) + 1
        bgm_audio = concatenate_audioclips([bgm_audio] * n_loops)
    
    # 動画の長さに合わせてBGMをカット
    bgm_clip = bgm_audio.set_duration(final_video.duration)
    
    final_audio_with_bgm = CompositeAudioClip([final_audio, bgm_clip])
    final_video = final_video.set_audio(final_audio_with_bgm)
    
    # 動画を保存
    output_path = WORK_DIR / f"bakenami_ep{EPISODE_NUMBER}.mp4"
    final_video.write_videofile(
        str(output_path),
        fps=24,
        codec='libx264',
        audio_codec='aac'
    )
    
    print(f"✅ 動画を生成しました: {output_path}")
    return output_path


# ========================================
# 5. YouTubeにアップロード
# ========================================

def upload_to_youtube(video_path):
    """
    YouTubeに動画をアップロード
    """
    print("📤 YouTubeにアップロード中...")
    
    credentials = service_account.Credentials.from_service_account_file(
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'],
        scopes=['https://www.googleapis.com/auth/youtube.upload']
    )
    
    youtube = build('youtube', 'v3', credentials=credentials)
    
    # 動画メタデータ
    body = {
        'snippet': {
            'title': f'【ばけばけ】第{EPISODE_NUMBER}話 感想トーク',
            'description': f'朝ドラ「ばけばけ」第{EPISODE_NUMBER}話の感想を{CHARACTER1_NAME}と{CHARACTER2_NAME}が語ります！',
            'tags': ['ばけばけ', '朝ドラ', '感想', 'NHK'],
            'categoryId': '24'  # エンターテイメント
        },
        'status': {
            'privacyStatus': 'public'  # 公開設定
        }
    }
    
    # アップロード
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )
    
    response = request.execute()
    video_id = response['id']
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    print(f"✅ アップロード完了: {video_url}")
    return video_url


# ========================================
# メイン処理
# ========================================

def main():
    """メイン処理"""
    print("=" * 50)
    print("🎬 ばけばけ動画自動生成システム 開始")
    print(f"📅 日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    try:
        # 1. Google認証情報の準備
        setup_google_credentials()
        
        # 2. スプレッドシートから設定を読み込む
        load_config_from_spreadsheet()
        
        print(f"📺 エピソード: 第{EPISODE_NUMBER}話")
        
        # 3. 感想を検索
        reactions = search_reactions()
        
        # 3. 会話スクリプト生成
        script = generate_script(reactions)
        
        # 4. 音声生成
        audio_files = generate_audio(script)
        
        # 5. 動画生成
        video_path = create_video(audio_files)
        
        # 6. YouTubeにアップロード（一旦スキップ）
        print("⏩ YouTubeアップロードはスキップします")
        # video_url = upload_to_youtube(video_path)
        
        print("=" * 50)
        print("🎉 動画生成が完了しました！")
        print(f"📹 動画ファイル: {video_path}")
        print("=" * 50)
        
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
