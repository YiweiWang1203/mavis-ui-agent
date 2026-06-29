#!/usr/bin/env python3
import re
import json
import os
import sys

def parse_diarization(txt):
    # 匹配形如 [0:00:07] Speaker 0:
    header_re = re.compile(r'^\[(\d+):(\d{2}):(\d{2})\]\s*(Speaker\s*\d+)\s*:?', re.IGNORECASE)
    blocks = []
    cur = None

    for line in txt.splitlines():
        line = line.rstrip()
        if not line:
            # 保持段落分隔但不结束当前段落
            if cur is not None:
                cur['text_lines'].append('')
            continue

        m = header_re.match(line)
        if m:
            # 新段开始
            h, mm, s, speaker = m.groups()
            start_sec = int(h) * 3600 + int(mm) * 60 + int(s)
            if cur is not None:
                blocks.append(cur)
            cur = {'start_time': float(start_sec), 'speaker': speaker.strip(), 'text_lines': []}
        else:
            if cur is None:
                # 忽略文件开头的任意前导文本
                continue
            cur['text_lines'].append(line)

    if cur is not None:
        blocks.append(cur)

    # 计算 end_time：使用下一个段的 start_time，最后一段估算为 start+5s
    for i in range(len(blocks)):
        if i < len(blocks) - 1:
            blocks[i]['end_time'] = float(blocks[i+1]['start_time'])
        else:
            blocks[i]['end_time'] = round(blocks[i]['start_time'] + 5.0, 2)

    # 合并文本行
    for b in blocks:
        text = '\n'.join([ln for ln in b['text_lines'] if ln is not None])
        # 清理多余空行
        text = re.sub('\n{2,}', '\n\n', text).strip()
        b['text'] = text
        # 保留仅需要的字段
        b.pop('text_lines', None)

    return blocks


def normalize_file(input_path):
    if not os.path.isfile(input_path):
        print(f"文件不存在: {input_path}")
        return 2

    base_dir = os.path.dirname(input_path)
    base_name = os.path.basename(input_path).replace('_diarization.txt', '')

    with open(input_path, 'r', encoding='utf-8') as f:
        txt = f.read()

    blocks = parse_diarization(txt)

    # 规范输出路径
    json_output = os.path.join(base_dir, f"{base_name}.json")
    txt_output = os.path.join(base_dir, f"{base_name}.normalized.txt")

    # 准备 JSON 数据结构
    json_list = []
    txt_lines = []
    for b in blocks:
        start = round(float(b['start_time']), 2)
        end = round(float(b['end_time']), 2)
        speaker = b.get('speaker', 'Unknown')
        text = b.get('text', '')

        json_list.append({
            'start_time': start,
            'end_time': end,
            'speaker': speaker,
            'text': text
        })

        txt_lines.append(f"[{start:.2f}s - {end:.2f}s] {speaker}:\n{text}\n")

    with open(json_output, 'w', encoding='utf-8') as f:
        json.dump(json_list, f, ensure_ascii=False, indent=2)

    with open(txt_output, 'w', encoding='utf-8') as f:
        f.write('\n'.join(txt_lines))

    print("写入完成:")
    print(json_output)
    print(txt_output)
    return 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: normalize_transcript.py /path/to/..._diarization.txt")
        sys.exit(1)
    sys.exit(normalize_file(sys.argv[1]))
