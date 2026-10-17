import json
import os
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser
import deepl
from deep_translator import GoogleTranslator
import keyboard
import mss
import pyperclip
import pytesseract
from PIL import Image, ImageEnhance, ImageOps, ImageTk

# 設定ファイル名
SETTINGS_FILE = "translation_settings.json"


# --- 領域セレクタークラス ---
class RegionSelector:

    def __init__(self, parent_root, on_selected_callback):
        self.callback = on_selected_callback
        self.parent_root = parent_root
        self.parent_root.attributes("-topmost", False)

        self.top = tk.Toplevel()
        self.top.attributes("-fullscreen", True)
        self.top.attributes("-topmost", True)
        self.top.config(cursor="cross")

        with mss.MSS() as sct:
            monitor = sct.monitors[1]
            self.screenshot = sct.grab(monitor)
            self.bg_image = Image.frombytes(
                "RGB", self.screenshot.size, self.screenshot.rgb
            )

        self.tk_img = ImageTk.PhotoImage(self.bg_image)
        self.canvas = tk.Canvas(
            self.top, cursor="cross", highlightthickness=0, bg="grey"
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")

        self.start_x = None
        self.start_y = None
        self.rect_id = None

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.top.bind("<Escape>", lambda e: self.close_selector())

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect_id = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            self.start_x,
            self.start_y,
            outline="#ff0000",
            width=2,
            dash=(4, 4),
        )

    def on_drag(self, event):
        cur_x, cur_y = event.x, event.y
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, cur_x, cur_y)

    def on_release(self, event):
        end_x, end_y = event.x, event.y
        left = min(self.start_x, end_x)
        top = min(self.start_y, end_y)
        width = abs(end_x - self.start_x)
        height = abs(end_y - self.start_y)

        if width > 10 and height > 10:
            region = {"left": left, "top": top, "width": width, "height": height}
            self.callback(region)

        self.close_selector()

    def close_selector(self):
        self.top.destroy()
        self.parent_root.attributes("-topmost", True)


# --- メインアプリケーションクラス ---
class TranslationApp:

    def __init__(self, root):
        self.root = root
        self.root.title("W_Translate")
        self.root.geometry("300x900")
        self.root.attributes("-topmost", True)

        self.capture_region = {"left": 100, "top": 100, "width": 400, "height": 150}
        self.is_running = False
        self.last_translated_text = ""
        self.last_translated_time = 0

        self.setup_ui()
        self.load_settings()

        try:
            keyboard.add_hotkey("ctrl+alt+t", self.manual_translate_trigger)
        except Exception as e:
            print(f"ショートカットキー登録エラー: {e}")

    def setup_ui(self):
        # 0-A. Tesseract-OCR 設定
        frame_ocr = tk.LabelFrame(
            self.root, text=" 0-A. Tesseract-OCR 設定 ", padx=10, pady=10
        )
        frame_ocr.pack(fill="x", padx=10, pady=5)

        lbl_link_tess = tk.Label(
            frame_ocr,
            text="🌐 未設定の方: Tesseract-OCR ダウンロードページを開く",
            font=("Meiryo", 8, "underline"),
            fg="blue",
            cursor="hand2",
        )
        lbl_link_tess.pack(anchor="w")
        lbl_link_tess.bind(
            "<Button-1>",
            lambda e: webbrowser.open("https://github.com/UB-Mannheim/tesseract/wiki"),
        )

        f_tess_input = tk.Frame(frame_ocr)
        f_tess_input.pack(fill="x", pady=3)

        tk.Label(f_tess_input, text="Exeパス:").pack(side="left")
        self.entry_tess_path = tk.Entry(f_tess_input, font=("Meiryo", 8))
        self.entry_tess_path.pack(side="left", fill="x", expand=True, padx=5)
        self.entry_tess_path.insert(0, r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        self.entry_tess_path.bind(
            "<KeyRelease>", lambda e: self.check_and_save_tesseract()
        )

        self.lbl_tess_status = tk.Label(frame_ocr, text="", font=("Meiryo", 8, "bold"))
        self.lbl_tess_status.pack(anchor="w")

        # 0-B. 翻訳API設定
        frame_api = tk.LabelFrame(
            self.root, text=" 0-B. 翻訳エンジン設定 ", padx=10, pady=10
        )
        frame_api.pack(fill="x", padx=10, pady=5)

        tk.Label(frame_api, text="使用API:").grid(row=0, column=0, sticky="w")
        self.combo_api = ttk.Combobox(
            frame_api,
            values=["DeepL API (推奨)", "Google Translate (無料)"],
            state="readonly",
        )
        self.combo_api.current(0)
        self.combo_api.grid(row=0, column=1, sticky="ew", padx=5)
        self.combo_api.bind("<<ComboboxSelected>>", self.on_api_changed)

        lbl_link_deepl = tk.Label(
            frame_api,
            text="🌐 DeepL API 無料キー取得ページを開く",
            font=("Meiryo", 8, "underline"),
            fg="blue",
            cursor="hand2",
        )
        lbl_link_deepl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))
        lbl_link_deepl.bind(
            "<Button-1>",
            lambda e: webbrowser.open(
                "https://www.deepl.com/ja/pro-api?cta=header-pro-api"
            ),
        )

        tk.Label(frame_api, text="DeepL Key:").grid(row=2, column=0, sticky="w", pady=5)
        self.entry_apikey = tk.Entry(frame_api, show="*")
        self.entry_apikey.grid(row=2, column=1, sticky="ew", padx=5, pady=5)
        self.entry_apikey.bind("<KeyRelease>", lambda e: self.save_settings())
        frame_api.columnconfigure(1, weight=1)

        # 1. 領域設定
        frame_region = tk.LabelFrame(
            self.root, text=" 1. チャット領域の設定 ", padx=10, pady=10
        )
        frame_region.pack(fill="x", padx=10, pady=5)

        self.lbl_region = tk.Label(
            frame_region,
            text=f"現在の領域: X={self.capture_region['left']}, Y={self.capture_region['top']}, "
            f"W={self.capture_region['width']}, H={self.capture_region['height']}",
            font=("Meiryo", 9),
        )
        self.lbl_region.pack(anchor="w")

        self.btn_select = tk.Button(
            frame_region,
            text="画面上の領域をドラッグして指定",
            command=self.open_selector,
            bg="#e0e0e0",
        )
        self.btn_select.pack(fill="x", pady=5)

        # 2. コントロール ＆ ステータス ＆ 手動ボタン
        frame_ctrl = tk.LabelFrame(
            self.root, text=" 2. チャット受信（英→日）コントロール ", padx=10, pady=10
        )
        frame_ctrl.pack(fill="x", padx=10, pady=5)

        self.btn_toggle = tk.Button(
            frame_ctrl,
            text="オートモード開始 (常時監視)",
            command=self.toggle_monitoring,
            bg="#4CAF50",
            fg="white",
            font=("Meiryo", 9, "bold"),
        )
        self.btn_toggle.pack(fill="x", pady=2)

        self.btn_manual = tk.Button(
            frame_ctrl,
            text="手動で今すぐ認識・翻訳 (Shortcut: Ctrl+Alt+T)",
            command=self.manual_translate_trigger,
            bg="#2196F3",
            fg="white",
            font=("Meiryo", 9, "bold"),
        )
        self.btn_manual.pack(fill="x", pady=2)

        self.lbl_status = tk.Label(
            frame_ctrl,
            text="ステータス: 待機中",
            fg="gray",
            font=("Meiryo", 9, "bold"),
        )
        self.lbl_status.pack(anchor="w", pady=2)

        # 3. 返信（日→英）機能
        frame_send = tk.LabelFrame(
            self.root, text=" 3. 返信（日→英）作成 ＆ 自動コピー ", padx=10, pady=10
        )
        frame_send.pack(fill="x", padx=10, pady=5)

        tk.Label(
            frame_send, text="英語にしてゲーム内に送る日本語を入力:", font=("Meiryo", 9)
        ).pack(anchor="w")

        self.txt_input_jp = tk.Entry(frame_send, font=("Meiryo", 10))
        self.txt_input_jp.pack(fill="x", pady=3)
        self.txt_input_jp.bind("<Return>", lambda e: self.translate_jp_to_en())

        self.btn_send_trans = tk.Button(
            frame_send,
            text="日本語を英語に翻訳してクリップボードにコピー (Enterキー可)",
            command=self.translate_jp_to_en,
            bg="#FF9800",
            fg="white",
            font=("Meiryo", 9, "bold"),
        )
        self.btn_send_trans.pack(fill="x", pady=3)

        # 4. 翻訳ログ
        frame_res = tk.LabelFrame(self.root, text=" 4. 翻訳ログ ", padx=10, pady=10)
        frame_res.pack(fill="both", expand=True, padx=10, pady=5)

        self.txt_result = tk.Text(frame_res, height=7, wrap="word", font=("Meiryo", 9))
        self.txt_result.pack(fill="both", expand=True)

        self.txt_result.tag_config(
            "receive_log", background="#E3F2FD", foreground="#0D47A1"
        )
        self.txt_result.tag_config(
            "send_log", background="#FFF3E0", foreground="#E65100"
        )

    def check_and_save_tesseract(self):
        path = self.entry_tess_path.get().strip()
        if os.path.exists(path) and path.endswith("tesseract.exe"):
            pytesseract.pytesseract.tesseract_cmd = path
            self.lbl_tess_status.config(text="✅ OCRエンジン検出OK", fg="green")
        else:
            self.lbl_tess_status.config(
                text="❌ 指定パスに tesseract.exe が見つかりません", fg="red"
            )
        self.save_settings()

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    api_choice = data.get("api_choice", "DeepL API (推奨)")
                    self.combo_api.set(api_choice)

                    api_key = data.get("deepl_key", "")
                    if api_key:
                        self.entry_apikey.config(state="normal")
                        self.entry_apikey.delete(0, tk.END)
                        self.entry_apikey.insert(0, api_key)

                    tess_path = data.get(
                        "tess_path", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                    )
                    self.entry_tess_path.delete(0, tk.END)
                    self.entry_tess_path.insert(0, tess_path)

                    self.on_api_changed(None)
                    self.check_and_save_tesseract()
            except Exception as e:
                print(f"設定読み込みエラー: {e}")
        else:
            self.check_and_save_tesseract()

    def save_settings(self):
        data = {
            "api_choice": self.combo_api.get(),
            "deepl_key": self.entry_apikey.get().strip(),
            "tess_path": self.entry_tess_path.get().strip(),
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"設定保存エラー: {e}")

    def on_api_changed(self, event):
        if "DeepL" in self.combo_api.get():
            self.entry_apikey.config(state="normal")
        else:
            self.entry_apikey.config(state="disabled")
        self.save_settings()

    def open_selector(self):
        RegionSelector(self.root, self.on_region_selected)

    def on_region_selected(self, region):
        self.capture_region = region
        self.lbl_region.config(
            text=f"現在の領域: X={region['left']}, Y={region['top']}, "
            f"W={region['width']}, H={region['height']}"
        )

    def translate_text(self, text, source_lang="EN", target_lang="JA"):
        selected = self.combo_api.get()
        try:
            if "DeepL" in selected:
                api_key = self.entry_apikey.get().strip()
                if not api_key:
                    return "[翻訳エラー: DeepL APIキーが設定されていません]"
                translator = deepl.Translator(api_key)
                result = translator.translate_text(text, target_lang=target_lang)
                return result.text
            else:
                translator = GoogleTranslator(
                    source=source_lang.lower(), target=target_lang.lower()
                )
                return translator.translate(text)
        except Exception as e:
            return f"[翻訳エラー: {e}]"

    def translate_jp_to_en(self):
        jp_text = self.txt_input_jp.get().strip()
        if not jp_text:
            messagebox.showwarning("警告", "翻訳する日本語を入力してください。")
            return

        try:
            translated_en = self.translate_text(
                jp_text, source_lang="JA", target_lang="EN-US"
            )

            if "[翻訳エラー:" in translated_en:
                self.lbl_status.config(
                    text="ステータス: ❌ 返信翻訳に失敗しました", fg="red"
                )
                return

            pyperclip.copy(translated_en)

            log_entry = f"[返信用原文(JP)]: {jp_text}\n[英語訳(EN) ※コピー済み]: {translated_en}\n---\n"
            self.txt_result.insert(tk.END, log_entry, "send_log")
            self.txt_result.see(tk.END)

            self.txt_input_jp.delete(0, tk.END)
            self.lbl_status.config(
                text="ステータス: 📋 英語に翻訳してコピーしました！ (Ctrl+Vで送信可能)",
                fg="green",
            )

        except Exception as e:
            print(f"[返信翻訳エラー]: {e}")
            self.lbl_status.config(
                text="ステータス: ❌ 返信翻訳エラーが発生しました", fg="red"
            )

    def manual_translate_trigger(self):
        threading.Thread(
            target=self.execute_ocr_and_translate, args=(True,), daemon=True
        ).start()

    def execute_ocr_and_translate(self, force=False):
        try:
            tess_path = self.entry_tess_path.get().strip()
            if not os.path.exists(tess_path):
                self.lbl_status.config(
                    text="ステータス: ❌ Tesseract-OCR のパスが無効です", fg="red"
                )
                return

            self.lbl_status.config(text="ステータス: 🔍 スキャン・翻訳中...", fg="blue")

            with mss.MSS() as sct:
                screenshot = sct.grab(self.capture_region)
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

                img_gray = img.convert("L")
                img_inverted = ImageOps.invert(img_gray)
                enhancer = ImageEnhance.Contrast(img_inverted)
                img_enhanced = enhancer.enhance(2.0)

                raw_text = pytesseract.image_to_string(img_enhanced, lang="eng")

                valid_lines = []
                for line in raw_text.split("\n"):
                    line = line.strip()
                    if (
                        re.search(r"\[\d{2}:\d{2}\]", line)
                        or (len(line) > 5 and ":" in line)
                        or ("hi" in line.lower() or "test" in line.lower())
                    ):
                        valid_lines.append(line)

                text = " ".join(valid_lines)
                if not text:
                    text = pytesseract.image_to_string(img_enhanced, lang="eng").strip()

                text = re.sub(r"[^\w\s:\[\]\?\!\.\,]", "", text).strip()

                current_time = time.time()
                if text and len(text) > 2:
                    is_different = text != self.last_translated_text
                    is_timeout = current_time - self.last_translated_time > 15

                    if force or is_different or is_timeout:
                        self.last_translated_text = text
                        self.last_translated_time = current_time

                        translated = self.translate_text(
                            text, source_lang="EN", target_lang="JA"
                        )

                        log_entry = (
                            f"[受信原文]: {text}\n[日本語訳]: {translated}\n---\n"
                        )
                        self.txt_result.insert(tk.END, log_entry, "receive_log")
                        self.txt_result.see(tk.END)
                        self.lbl_status.config(
                            text="ステータス: ✅ 翻訳完了", fg="green"
                        )
                    else:
                        self.lbl_status.config(
                            text="ステータス: ℹ️ 変更なし（スキップ）", fg="gray"
                        )
                else:
                    self.lbl_status.config(
                        text="ステータス: ⚠️ 有効な本文が検知されませんでした",
                        fg="orange",
                    )

        except Exception as e:
            print(f"[翻訳処理エラー]: {e}")
            self.lbl_status.config(text="ステータス: ❌ エラー発生", fg="red")

    def toggle_monitoring(self):
        if not self.is_running:
            if "DeepL" in self.combo_api.get() and not self.entry_apikey.get().strip():
                messagebox.showwarning(
                    "警告", "DeepLを使用するにはAPIキーを入力してください。"
                )
                return

            self.is_running = True
            self.btn_toggle.config(text="オートモード停止", bg="#F44336")
            self.lbl_status.config(
                text="ステータス: 🟢 オートモード稼働中...", fg="green"
            )

            self.thread = threading.Thread(target=self.monitoring_loop, daemon=True)
            self.thread.start()
        else:
            self.is_running = False
            self.btn_toggle.config(text="オートモード開始 (常時監視)", bg="#4CAF50")
            self.lbl_status.config(text="ステータス: 停止中", fg="gray")

    def monitoring_loop(self):
        while self.is_running:
            self.execute_ocr_and_translate(force=False)
            time.sleep(6)


if __name__ == "__main__":
    root = tk.Tk()
    app = TranslationApp(root)
    root.mainloop()
