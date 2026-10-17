import tkinter as tk
import mss
from PIL import Image, ImageTk


class RegionSelector:

    def __init__(self, parent, on_selected_callback):
        self.callback = on_selected_callback

        # フルスクリーンの透明／オーバーレイウィンドウを作成
        self.top = tk.Toplevel(parent)
        self.top.attributes("-fullscreen", True)
        self.top.attributes("-topmost", True)
        self.top.overrideredirect(True)  # タイトルバーを非表示

        # 現在の画面をキャプチャして背景にする（ゲーム画面を静止画として表示するため）
        with mss.mss() as sct:
            # プライマリモニターのキャプチャ
            monitor = sct.monitors[1]
            self.screenshot = sct.grab(monitor)
            self.bg_image = Image.frombytes(
                "RGB", self.screenshot.size, self.screenshot.rgb
            )

        self.tk_img = ImageTk.PhotoImage(self.bg_image)

        # キャンバスの作成
        self.canvas = tk.Canvas(
            self.top, cursor="cross", highlightthickness=0, bg="grey"
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")

        # 暗めの半透明オーバーレイ表現（オプション：全体の雰囲気を暗くする）
        # ※シンプルにするため今回は省略し、選択枠のみを鮮やかに表示します

        self.start_x = None
        self.start_y = None
        self.rect_id = None

        # マウスイベントのバインド
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        # ESCキーでキャンセル可能に
        self.top.bind("<Escape>", lambda e: self.top.destroy())

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        # 選択枠（赤色の点線）の初期作成
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
        # ドラッグに合わせて矩形を更新
        cur_x, cur_y = event.x, event.y
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, cur_x, cur_y)

    def on_release(self, event):
        end_x, end_y = event.x, event.y

        # どの方向（右下へ、左上へなど）にドラッグしても正しく座標計算できるようにする
        left = min(self.start_x, end_x)
        top = min(self.start_y, end_y)
        width = abs(end_x - self.start_x)
        height = abs(end_y - self.start_y)

        # 一定以上のサイズで囲まれた場合のみ確定
        if width > 10 and height > 10:
            region = {"left": left, "top": top, "width": width, "height": height}
            self.callback(region)

        self.top.destroy()
