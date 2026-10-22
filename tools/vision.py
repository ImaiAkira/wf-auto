"""用视觉模型看截图：描述界面 / 自由提问 / 定位元素（输出像素坐标，可裁剪为模板）。

配置（二选一）:
  1) 项目 config/vision.json: {"base_url": "...", "api_key": "...", "model": "..."}
  2) 环境变量: VISION_BASE_URL / VISION_API_KEY / VISION_MODEL

用法:
  .venv\\Scripts\\python.exe tools\\vision.py describe <截图>
  .venv\\Scripts\\python.exe tools\\vision.py ask <截图> "问题"
  .venv\\Scripts\\python.exe tools\\vision.py locate <截图> "目标元素" [--crop 输出.png]

说明:
  locate 会把模型返回的 0-1000 归一化坐标换算为截图像素坐标（左上原点），
  并可按第一个结果裁剪出图片（可用于自动生成 MAA 模板）。

各服务 base_url 参考:
  智谱:   https://open.bigmodel.cn/api/paas/v4          (glm-4.6v-flash 免费)
  阿里:   https://dashscope.aliyuncs.com/compatible-mode/v1  (qwen3-vl-flash)
  本地:   http://127.0.0.1:11434/v1                     (Ollama, api_key 随便填)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from pathlib import Path

import httpx
from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT / "config" / "vision.json"


def load_config() -> dict:
    cfg: dict = {}
    if CONFIG_PATH.is_file():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for key, env in (
        ("base_url", "VISION_BASE_URL"),
        ("api_key", "VISION_API_KEY"),
        ("model", "VISION_MODEL"),
    ):
        if not cfg.get(key):
            cfg[key] = os.environ.get(env, "")
    if not cfg.get("base_url") or not cfg.get("model"):
        raise SystemExit(
            "缺少视觉模型配置：请填写 config/vision.json 或设置环境变量 "
            "VISION_BASE_URL / VISION_MODEL"
        )
    if not cfg.get("api_key"):
        cfg["api_key"] = "EMPTY"  # 部分本地服务要求非空
    return cfg


def to_data_url(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "webp": "webp", "png": "png"}.get(suffix, "png")
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/{mime};base64,{b64}"


def ask_vlm(cfg: dict, image: Path, prompt: str, max_tokens: int = 1500) -> str:
    payload = {
        "model": cfg["model"],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": to_data_url(image)}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    last_error: Exception | None = None
    for attempt, delay in enumerate((0, 5, 15, 30), start=1):
        if delay:
            time.sleep(delay)
        try:
            with httpx.Client(timeout=180) as client:
                resp = client.post(url, json=payload, headers=headers)
            if resp.status_code == 429:
                last_error = RuntimeError("429 限流")
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code != 429:
                raise
    raise SystemExit(f"视觉 API 多次限流失败: {last_error}")


def extract_json_array(text: str):
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


LOCATE_PROMPT = (
    "你是游戏 UI 分析助手。请在这张手机游戏截图中找到「{target}」。"
    "只输出 JSON 数组，不要输出其他内容。数组元素格式: "
    '{{"name": "元素名称", "bbox": [x1, y1, x2, y2], "score": 0.0}}。'
    "bbox 使用 0-1000 的归一化坐标（左上角为原点，x 向右，y 向下）。"
    "如果找不到，输出 []。"
)


def locate(image: Path, target: str) -> list[tuple[str, int, int, int, int, float]]:
    """定位元素，返回 [(名称, x1, y1, x2, y2, score)]（截图像素坐标）。"""
    cfg = load_config()
    text = ask_vlm(cfg, image, LOCATE_PROMPT.format(target=target))
    items = extract_json_array(text) or []
    with Image.open(image) as img:
        width, height = img.size
    results: list[tuple[str, int, int, int, int, float]] = []
    for item in items:
        bbox = item.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x1 = round(bbox[0] / 1000 * width)
        y1 = round(bbox[1] / 1000 * height)
        x2 = round(bbox[2] / 1000 * width)
        y2 = round(bbox[3] / 1000 * height)
        results.append(
            (str(item.get("name", "")), x1, y1, x2, y2, float(item.get("score", 0) or 0))
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="让视觉模型看截图")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_desc = sub.add_parser("describe", help="描述界面")
    p_desc.add_argument("image", type=Path)

    p_ask = sub.add_parser("ask", help="自由提问")
    p_ask.add_argument("image", type=Path)
    p_ask.add_argument("question")

    p_loc = sub.add_parser("locate", help="定位元素并输出像素坐标")
    p_loc.add_argument("image", type=Path)
    p_loc.add_argument("target")
    p_loc.add_argument("--crop", type=Path, default=None, help="裁剪第一个结果到该文件")

    args = parser.parse_args()

    if not args.image.is_file():
        raise SystemExit(f"图片不存在: {args.image}")

    cfg = load_config()

    if args.cmd == "describe":
        prompt = (
            "用中文简要描述这张手机游戏截图：当前是什么界面、主要区域布局、"
            "可见的可点击按钮及大致位置（如左上/右下）。"
        )
        print(ask_vlm(cfg, args.image, prompt))
        return

    if args.cmd == "ask":
        print(ask_vlm(cfg, args.image, args.question))
        return

    text = ask_vlm(cfg, args.image, LOCATE_PROMPT.format(target=args.target))
    print("模型原始输出:", text)
    items = extract_json_array(text)
    if not items:
        print("未解析到结果")
        return

    with Image.open(args.image) as img:
        width, height = img.size

    parsed = []
    for item in items:
        bbox = item.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x1 = round(bbox[0] / 1000 * width)
        y1 = round(bbox[1] / 1000 * height)
        x2 = round(bbox[2] / 1000 * width)
        y2 = round(bbox[3] / 1000 * height)
        parsed.append((item.get("name", ""), x1, y1, x2, y2, item.get("score", 0)))

    for name, x1, y1, x2, y2, score in parsed:
        print(
            f"{name}\t像素框=({x1},{y1},{x2},{y2})\t"
            f"中心=({(x1 + x2) // 2},{(y1 + y2) // 2})\tscore={score}"
        )

    if args.crop and parsed:
        _, x1, y1, x2, y2, _ = parsed[0]
        with Image.open(args.image) as img:
            box = (max(0, x1), max(0, y1), min(img.width, x2), min(img.height, y2))
            crop = img.crop(box)
            args.crop.parent.mkdir(parents=True, exist_ok=True)
            crop.save(args.crop)
        print("已裁剪:", args.crop, crop.size)


if __name__ == "__main__":
    main()
