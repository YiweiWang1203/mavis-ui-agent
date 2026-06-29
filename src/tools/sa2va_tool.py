import subprocess
import sys  # ✅ 核心修复 1：导入 sys 模块，彻底解决 NameError

from langchain_core.tools import tool

@tool
def sa2va_tool(video_folder: str, question: str, venv_python: str = sys.executable) -> str:
    """
    在主环境下通过subprocess调用sa2va虚拟环境中的推理脚本。
    """
    # 🌟 新增这行打印，看看大模型到底有没有来调工具！
    print("\n" + "="*50)
    print("🚨 汇报：大模型确实调用了 sa2va_tool 视觉工具！")
    print(f"👉 接收到的路径是: {video_folder}")
    print("="*50 + "\n")
    # ✅ 核心解答 2：所谓的“优化脚本”，就是修改这个长字符串变量内部的 Python 逻辑
    script = f'''
import torch
from modelscope import AutoTokenizer, AutoModel
from PIL import Image
import os

path = "ByteDance/Sa2VA-1B"
if torch.cuda.is_available():
    model = AutoModel.from_pretrained(
        path, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True,
        use_flash_attn=False, trust_remote_code=True, device_map="auto"
    ).eval()
else:
    model = AutoModel.from_pretrained(
        path, torch_dtype=torch.float16, low_cpu_mem_usage=True,
        use_flash_attn=False, trust_remote_code=True
    ).eval()
tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=True, use_fast=False)

# 🌟 路径优化逻辑：自动兼容“单个图片文件”和“包含图片的文件夹”
video_folder_or_file = r"{video_folder}"
valid_exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')

images_paths = []
if os.path.isfile(video_folder_or_file):
    images_paths = [video_folder_or_file]
elif os.path.isdir(video_folder_or_file):
    images_paths = [os.path.join(video_folder_or_file, f) for f in os.listdir(video_folder_or_file) if f.lower().endswith(valid_exts)]
else:
    print("输入的路径不存在")

if len(images_paths) > 5:
    step = (len(images_paths) - 1) // (5 - 1)
    images_paths = [images_paths[0]] + images_paths[1:-1][::step][1:] + [images_paths[-1]]

video_frames = [Image.open(p).convert('RGB') for p in images_paths]
input_dict = {{
    'video': video_frames,
    'text': r"""{question}""",
    'past_text': '',
    'mask_prompts': None,
    'tokenizer': tokenizer,
}}
return_dict = model.predict_forward(**input_dict)
print(return_dict.get("prediction", ""))
'''
    result = subprocess.run(
        [venv_python, "-c", script],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    else:
        return f"[subprocess error] {result.stderr.strip()}"