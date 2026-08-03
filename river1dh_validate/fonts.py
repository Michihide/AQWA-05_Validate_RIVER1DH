"""matplotlibで日本語 (観測所名・河川名など) を文字化けさせずに表示するための共通設定。

`plotting.py` と `scoring.py` の両方が日本語を含む図・表を描画するため、
フォント設定をここに集約する。
"""

from __future__ import annotations

import matplotlib

_JAPANESE_FONT_CANDIDATES = (
    "Hiragino Sans",
    "Yu Gothic",
    "Noto Sans CJK JP",
    "IPAexGothic",
    "MS Gothic",
)

_configured = False


def setup_japanese_font() -> None:
    """OS上で見つかった日本語対応フォントを matplotlib の既定フォントにする。

    見つからない場合は既定 (DejaVu Sans) のままにする (文字化けはするが描画自体は続行)。
    複数回呼んでもコストがかからないよう、一度設定したら以降は何もしない。
    """
    global _configured
    if _configured:
        return
    _configured = True

    available = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
    for candidate in _JAPANESE_FONT_CANDIDATES:
        if candidate in available:
            matplotlib.rcParams["font.family"] = candidate
            break
    matplotlib.rcParams["axes.unicode_minus"] = False
