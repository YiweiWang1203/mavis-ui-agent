import os
# 🌟 关键修复：强制使用 Hugging Face 国内镜像站
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from datasets import load_dataset

# 1. 明确你的绝对目标路径
TARGET_DIR = "/wyw/meeting_agent_workspace/my_agent/data/input/images/sketch2code"
os.makedirs(TARGET_DIR, exist_ok=True)

print("🚀 开始从 Hugging Face 加载 Sketch2Code 数据集...")
# 2. 加载 HF 格式的数据集
dataset = load_dataset("SALT-NLP/Sketch2Code-hf", split="train")

print(f"✅ 成功加载！总共包含 {len(dataset)} 张手绘草图。")
print("📦 正在抽取前 20 张核心草图落地到本地，用于首批压力测试...")

# 3. 遍历并保存图片
for index, row in enumerate(dataset):
    if index >= 20: 
        break
        
    sketch_id = row["id"]
    sketch_image = row["sketch"]  
    
    file_name = f"sketch_{sketch_id}.png"
    save_path = os.path.join(TARGET_DIR, file_name)
    
    sketch_image.save(save_path)
    print(f"   [已落盘] -> {save_path}")

print("\n🎉 任务完成！标准学术草图已成功喂进你的输入目录中！")