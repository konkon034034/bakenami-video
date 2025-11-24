#!/usr/bin/env python3
"""
利用可能なGeminiモデルを確認するスクリプト
"""
import os
import google.generativeai as genai

# APIキーを設定
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if not GEMINI_API_KEY:
    print("❌ GEMINI_API_KEY が設定されていません")
    exit(1)

print("🔍 Gemini APIに接続中...")
genai.configure(api_key=GEMINI_API_KEY)

print("\n📋 利用可能なモデル一覧:\n")
print("-" * 80)

try:
    models = genai.list_models()
    
    for model in models:
        # generateContentをサポートしているモデルのみ表示
        if 'generateContent' in model.supported_generation_methods:
            print(f"✅ モデル名: {model.name}")
            print(f"   表示名: {model.display_name}")
            print(f"   説明: {model.description}")
            print(f"   サポート機能: {', '.join(model.supported_generation_methods)}")
            print("-" * 80)
            
except Exception as e:
    print(f"❌ エラー: {e}")
    import traceback
    traceback.print_exc()
