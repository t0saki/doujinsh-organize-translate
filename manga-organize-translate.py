import os
import shutil
import re
import json
import requests
import subprocess
import sys
from tqdm import tqdm

# 设置源文件夹路径和目标文件夹路径
source_folder = '/mnt/synology/res/komga/240607-all-aio/'
target_folder = '/mnt/synology/res/komga/ehentai-organized/'

# 设置翻译缓存文件路径
cache_file_path = 'translation_cache.json'

# 设置是否使用本地API服务器进行翻译，否则使用Google翻译
use_local_api = True  # 如果不想使用本地API，设置为False

# 本地API服务器的地址
api_url = 'http://172.29.238.88:12345/v1/chat/completions'

def translate(text_jp):
    prompt = f"请将以下日文翻译成中文：'{text_jp}'"
    headers = {
        'Content-Type': 'application/json'
    }
    data = {
        "model": "qwen2.5-ja-zh",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0,
    }
    response = requests.post(api_url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content'].strip()

# 测试API服务器是否可用
try:
    print(f"正在测试本地API服务器：'こんにちは' -> '{translate('こんにちは')}'")
except Exception as e:
    print(f'本地API服务器测试失败：{e}')
    print('请检查API服务器地址是否正确。')
    sys.exit()

# 如果需要使用Google翻译，可以安装并使用googletrans库
# from googletrans import Translator
# translator = Translator()

# 加载或初始化翻译缓存字典
if os.path.exists(cache_file_path):
    with open(cache_file_path, 'r', encoding='utf-8') as cache_file:
        translation_cache = json.load(cache_file)
else:
    translation_cache = {}

def update_translation_cache(trans_cache):
    with open(cache_file_path, 'w', encoding='utf-8') as cache_file:
        json.dump(trans_cache, cache_file, ensure_ascii=False, indent=4)
        
# 定义清理文件名的函数
def sanitize_filename(name):
    illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in illegal_chars:
        name = name.replace(char, '_')
    return name.strip()

# 定义使用 CoW 复制的函数
def copy_with_cow(src, dst):
    try:
        # 使用 cp --reflink=always 命令进行复制
        subprocess.check_call(['cp', '--reflink=always', src, dst])
    except subprocess.CalledProcessError as e:
        print(f"复制文件错误：{e}")
        # 如果出错，可以选择使用普通复制方式
        shutil.copy2(src, dst)
    except Exception as e:
        print(f"发生异常：{e}")
        shutil.copy2(src, dst)

def mv_file(src, dst):
    try:
        shutil.move(src, dst)
    except Exception as e:
        print(f"移动文件错误：{e}")

# 获取源文件夹中所有文件名
file_list = os.listdir(source_folder)
total_files = len(file_list)

# 初始化计数器
counter = 0
save_interval = 10  # 每处理10个文件，保存一次缓存

# 遍历每个文件
for idx, filename in tqdm(enumerate(file_list, 1), ncols=80, total=total_files):
    # 检查是否是文件（而不是文件夹）
    source_path = os.path.join(source_folder, filename)
    if not os.path.isfile(source_path):
        continue

    # 移除文件名的扩展名
    name_without_ext, ext = os.path.splitext(filename)

    # 去除开头的 "数字-"或者"数字 -"形式（如果有）
    name_without_ext = re.sub(r'^\d+\s*-\s*', '', name_without_ext)

    # 第一步，移除尾部的 [XXXX] 这类带有[]的标识
    name = name_without_ext.strip()
    while name.endswith(']'):
        pos = name.rfind('[')
        if pos == -1:
            break
        name = name[:pos].strip()

    # 第二步，移除尾部的章节号，例如 " 2" 或者 " 第2章" 等
    name = re.sub(r'\s*(第?\d+(\.\d+)?(?:[巻话話章]|$))$', '', name)
    # 罗马数字
    name = re.sub(r'\s*(第?[IVXLCDM]+(?:[巻话話章]|$))', '', name)

    # 提取作者信息和标题
    # 假设格式为 "[作者信息] 标题"
    name_start_pos = name.find(']')
    if name_start_pos != -1:
        author_info = name[:name_start_pos + 1].strip()
        title_jp = name[name_start_pos + 1:].strip()
    else:
        # 无法匹配格式，作者信息为空，使用文件名作为标题
        author_info = ''
        title_jp = name

    # 翻译标题（如果缓存中已有，则直接使用）
    if title_jp in translation_cache:
        title_cn = translation_cache[title_jp]
    else:
        # 判断使用本地API还是Google翻译
        if use_local_api:
            # 使用本地API服务器进行翻译
            # 尝试三次
            for _ in range(3):
                try:
                    title_cn = translate(title_jp)
                    break
                except Exception as e:
                    print(f"第{_+1}次翻译失败：{e}")
                    title_cn = title_jp

            title_cn = re.sub(r'^[_"\'（( ]*|[_"\'）) ]*$', '', title_cn)

        else:
            # 使用Google翻译（这里暂时未实现）
            # title_cn = translator.translate(title_jp, src='ja', dest='zh-cn').text
            title_cn = title_jp  # 保持原文

        # 缓存翻译结果
        translation_cache[title_jp] = title_cn

    # 构建目标文件夹名
    if author_info:
        dest_folder_name = f'{author_info} {title_cn}'
    else:
        dest_folder_name = title_cn

    # 清理目标文件夹名
    dest_folder_name = sanitize_filename(dest_folder_name)

    # 构建目标文件夹路径
    dest_folder_path = os.path.join(target_folder, dest_folder_name)

    # 创建目标文件夹
    os.makedirs(dest_folder_path, exist_ok=True)

    # 将文件复制到目标文件夹，不修改文件名，使用 CoW 复制
    dest_path = os.path.join(dest_folder_path, filename)
    mv_file(source_path, dest_path)
    # print(f'[{idx}/{total_files}] 移动文件：{filename} -> {dest_path}')

    # 更新计数器
    counter += 1
    if counter % save_interval == 0:
        update_translation_cache(translation_cache)
        print(f'已处理{counter}个文件，翻译缓存已保存。')

    # print(f'[{idx}/{total_files}] 已处理文件：{filename}')

# 将更新后的翻译缓存写回文件
update_translation_cache(translation_cache)

print('全部处理完成。')