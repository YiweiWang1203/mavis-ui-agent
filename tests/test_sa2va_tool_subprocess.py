from src.tools.sa2va_tool import sa2va_tool
answer = sa2va_tool.invoke({
    "video_folder": "D:\\Github\\SegAnyGAussians\\data\\360_v2\\garden\\input",
    "question": "<image>where is the vase?"
})
print(answer)