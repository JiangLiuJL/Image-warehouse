# 装饰画图片管理软件

这是一个面向拼多多装饰画商家的 Windows 本地桌面软件项目。

第一版目标：

- 管理多个店铺的图片文件夹
- 上传图片并绑定编码
- 自动生成规范图片编码
- 一张原图生成多个尺寸版本
- 读取图片像素和 DPI
- 使用本地 JSON / CSV 保存设置和图片索引
- 不使用数据库

## 技术栈

- Python 3.12+
- PySide6：桌面软件界面
- Pillow：图片读取、缩放、DPI 设置
- CSV / JSON：本地记录文件
- PyInstaller：后续打包为 Windows 可执行文件

## 项目结构

```text
src/pdd_art_manager
├─ app.py                 # 软件启动入口
├─ config.py              # 路径和默认配置
├─ models.py              # 店铺、图片、尺寸等数据结构
├─ services
│  ├─ code_generator.py   # 图片编码生成
│  ├─ image_processor.py  # 图片读取和多尺寸生成
│  ├─ index_store.py      # CSV 图片索引
│  └─ shop_store.py       # JSON 店铺配置
└─ ui
   └─ main_window.py      # 主窗口
```

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pdd_art_manager.app
```

## 数据保存方式

软件不使用数据库，默认本地记录文件如下：

```text
data/
├─ shops.json
├─ settings.json
└─ image_index.csv
```

图片文件保存在用户为每个店铺指定的文件夹中。

