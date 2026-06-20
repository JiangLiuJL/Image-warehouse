# Image Warehouse

A Windows desktop tool for Pinduoduo decorative art sellers to manage shop-specific image folders, generate standardized image codes, create multiple print sizes with custom DPI, and keep local JSON/CSV records without using a database.

## Project Goals

- Manage image folders for multiple shops
- Upload images and bind them to standardized codes
- Generate image codes automatically
- Create multiple print-size versions from one source image
- Read image pixels and DPI
- Store local settings with JSON
- Store the image index with CSV files that can be opened in Excel
- Avoid using a database in the first version

## Tech Stack

- Python 3.12+
- PySide6 for the Windows desktop interface
- Pillow for image metadata, resizing, and DPI output
- JSON / CSV for local records
- PyInstaller for future Windows `.exe` packaging

## Structure

```text
src/pdd_art_manager
├─ app.py                 # App entry point
├─ config.py              # Paths and default config
├─ models.py              # Shop, image, and size data models
├─ services
│  ├─ code_generator.py   # Image code generation
│  ├─ image_processor.py  # Image metadata and size generation
│  ├─ index_store.py      # CSV image index
│  └─ shop_store.py       # JSON shop config
└─ ui
   └─ main_window.py      # Main window
```

## Run Locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pdd_art_manager.app
```

## Local Data

The app does not use a database. It stores local records in:

```text
data/
├─ shops.json
├─ settings.json
└─ image_index.csv
```

Image files are stored in the folders selected for each shop.

