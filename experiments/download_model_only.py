from modelscope.hub.snapshot_download import snapshot_download

print("📥 开始独立下载 FunASR (Paraformer) 模型权重...")
print("⚠️ 注意：这包含了几个 G 的大文件，请观察下方是否出现进度条！")

# 显式下载 paraformer-zh 对应的真实底层模型库
model_dir = snapshot_download('iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch')

print(f"\n✅ 模型已经全部下载并缓存至本地物理路径: {model_dir}")
print("💡 接下来即使拔掉网线，也能瞬间启动推理！")
