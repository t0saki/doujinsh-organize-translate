import os
import shutil
import re
import json
import requests
import subprocess
import sys
from tqdm import tqdm
from multiprocessing import Pool, Manager, cpu_count
import threading
import time
import logging
from datetime import datetime

# 设置源文件夹路径和目标文件夹路径
source_folder = '/mnt/synology/res/komga/240607-all-aio/'
target_folder = '/mnt/synology/res/komga/ehentai-organized/'

# 设置翻译缓存文件路径
cache_file_path = 'translation_cache.json'

# 设置是否使用本地API服务器进行翻译，否则使用其他翻译方式
use_local_api = True  # 如果不想使用本地API，设置为False

# 本地API服务器的地址
api_url = 'http://172.29.238.88:12345/v1/chat/completions'

# 最大进程数
# max_workers = cpu_count()
max_workers = 4

# 创建日志目录，如果不存在
if not os.path.exists('logs'):
    os.makedirs('logs')

# 设置日志文件名，使用当前时间命名
timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
log_filename = os.path.join('logs', f'{timestamp}.log')

# 配置日志
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

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
    response = requests.post(api_url, headers=headers, json=data, timeout=30)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content'].strip()

def sanitize_filename(name):
    illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in illegal_chars:
        name = name.replace(char, '_')
    return name.strip()

def process_file(args):
    filename, translation_cache, cache_lock = args
    try:
        source_path = os.path.join(source_folder, filename)
        if not os.path.isfile(source_path):
            return

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

        # 第二步，移除尾部的章节号
        name = re.sub(r'\s*(第?\d+(\.\d+)?(?:[巻话話章]|$))$', '', name)
        # 移除罗马数字章节号
        name = re.sub(r'\s*(第?[IVXLCDM]+(?:[巻话話章]|$))', '', name)

        # 提取作者信息和标题
        name_start_pos = name.find(']')
        if name_start_pos != -1:
            author_info = name[:name_start_pos + 1].strip()
            title_jp = name[name_start_pos + 1:].strip()
        else:
            # 无法匹配格式，作者信息为空，使用文件名作为标题
            author_info = ''
            title_jp = name
            logging.warning(f"文件 '{filename}' 的标题格式不符合预期。")

        # 翻译标题（如果缓存中已有，则直接使用）
        with cache_lock:
            if title_jp in translation_cache:
                title_cn = translation_cache[title_jp]
            else:
                title_cn = None

        if not title_cn:
            # 判断使用本地API还是其他翻译方式
            if use_local_api:
                # 使用本地API服务器进行翻译，尝试三次
                for attempt in range(3):
                    try:
                        title_cn = translate(title_jp)
                        break
                    except Exception as e:
                        if attempt < 2:
                            continue
                        else:
                            error_message = f"翻译失败：{e}"
                            logging.error(f"文件 '{filename}' 的标题 '{title_jp}' 翻译失败。错误信息：{e}")
                            title_cn = title_jp  # 保持原文
            else:
                # 使用其他翻译方式
                title_cn = title_jp  # 保持原文

            # 缓存翻译结果
            with cache_lock:
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

        # 将文件移动到目标文件夹，不修改文件名
        dest_path = os.path.join(dest_folder_path, filename)
        shutil.move(source_path, dest_path)

    except Exception as e:
        logging.error(f"处理文件 '{filename}' 时发生错误：{e}")

def periodic_save_cache(translation_cache, cache_lock, interval):
    while True:
        time.sleep(interval)
        with cache_lock:
            cache_dict = dict(translation_cache)
            with open(cache_file_path, 'w', encoding='utf-8') as cache_file:
                json.dump(cache_dict, cache_file, ensure_ascii=False, indent=4)
        print("翻译缓存已定期保存。")

if __name__ == '__main__':
    # 测试API服务器是否可用
    try:
        test_translation = translate('こんにちは')
        print(f"正在测试本地API服务器：'こんにちは' -> '{test_translation}'")
    except Exception as e:
        logging.error(f'本地API服务器测试失败：{e}')
        print('请检查API服务器地址是否正确。')
        sys.exit()

    # 创建 Manager 和锁
    manager = Manager()
    translation_cache = manager.dict()
    cache_lock = manager.Lock()  # 使用 Manager 创建锁

    # 加载或初始化翻译缓存字典
    if os.path.exists(cache_file_path):
        with open(cache_file_path, 'r', encoding='utf-8') as cache_file:
            cache_data = json.load(cache_file)
            translation_cache.update(cache_data)

    # 启动定期保存缓存的线程
    save_interval = 60  # 每1分钟保存一次（单位：秒）
    save_thread = threading.Thread(target=periodic_save_cache, args=(translation_cache, cache_lock, save_interval), daemon=True)
    save_thread.start()

    # 获取源文件夹中所有文件名
    file_list = os.listdir(source_folder)
    total_files = len(file_list)

    # 创建处理文件的参数列表
    args_list = [(filename, translation_cache, cache_lock) for filename in file_list]

    # 使用进程池进行并行处理
    with Pool(processes=max_workers) as pool:
        list(tqdm(pool.imap_unordered(process_file, args_list), total=total_files, ncols=80))

    # 程序结束前，保存一次缓存
    with cache_lock:
        cache_dict = dict(translation_cache)
        with open(cache_file_path, 'w', encoding='utf-8') as cache_file:
            json.dump(cache_dict, cache_file, ensure_ascii=False, indent=4)
    print('翻译缓存已保存。')

    print('全部处理完成。')