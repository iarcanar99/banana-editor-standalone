# 🍌 Banana Editor - Standalone Version

เครื่องมือ Image-to-Image editing อิสระ ด้วย Gemini 2.5 Flash API

![Banana Editor](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-GUI-green?logo=qt&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-orange?logo=google&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow?logo=license&logoColor=white)

## 📸 ภาพรวมโปรแกรม

![Banana Editor Screenshot](screenshot_ui_image.jpg)
*หน้าตาโปรแกรม Banana Editor Standalone พร้อมธีม Navy Green และฟีเจอร์การแก้ไขภาพด้วย AI*

## ⚠️ **ข้อควรทราบก่อนใช้งาน**
- **ต้องใช้ Paid API Key เท่านั้น** - Free API Key ไม่รองรับการสร้างภาพ
- **ค่าใช้จ่าย**: $0.039 ต่อภาพที่สร้าง (ประมาณ 1.2 บาท)

## คุณสมบัติหลัก

### ✅ คงไว้จากเวอร์ชันต้นฉบับ
- 🎨 **Core Banana Editor functionality**: การแก้ไขภาพแบบ Image-to-Image
- 🤖 **Gemini API integration**: ใช้ Gemini 2.5 Flash สำหรับการประมวลผลภาพ
- 🎨 **Navy Green theme UI** (#304530): ธีมสีเขียวกรมท่าเหมือนเดิม
- 📚 **History system**: ระบบประวัติแยกไฟล์ (banana_history.json)
- 🖼️ **Multiple image support**: รองรับหลายภาพพร้อมกัน (สูงสุด 3 ภาพ)
- 🔍 **Floating viewer**: ตัวดูภาพแบบลอยตัว พร้อม zoom
- 📁 **Direct image loading**: โหลดภาพโดยตรงด้วย --preload-image

### ❌ ลบออกสำหรับเวอร์ชัน Standalone
- 🔗 **IPC features**: ไม่มีการเชื่อมต่อผ่าน IPC
- 🔄 **Single instance mode**: ไม่จำกัดจำนวน instance ที่เปิดได้
- 📤 **Auto-refresh notifications**: ไม่ส่งการแจ้งเตือนไป Promptist
- 🤝 **Promptist integration**: ไม่เชื่อมต่อกับ Promptist

## การใช้งาน

### รันโปรแกรม
```bash
python banana_editor_standalone.py
```

### โหลดภาพตั้งแต่เริ่มต้น
```bash
python banana_editor_standalone.py --preload-image path/to/image.jpg
# หรือ
python banana_editor_standalone.py --image path/to/image.jpg
```

### ทดสอบการทำงาน
```bash
python test_standalone.py
```

## ข้อกำหนดระบบ

### Python Dependencies
- Python 3.8+
- PySide6 (PyQt6)
- PIL (Pillow)
- python-dotenv (optional)

### Environment Variables
- `GEMINI_API_KEY`: Google Gemini API Key (จำเป็น) - **ต้องเป็น Paid API Key เท่านั้น**

### ติดตั้ง Dependencies
```bash
pip install PySide6 Pillow python-dotenv
```

## การตั้งค่า

### 1. Clone repository
```bash
git clone https://github.com/iarcanar99/banana-editor-standalone.git
cd banana-editor-standalone
```

### 2. ติดตั้ง dependencies
```bash
pip install -r requirements.txt
```

### 3. ตั้งค่า API Key
สร้างไฟล์ `.env` จากตัวอย่าง:
```bash
cp .env.example .env
```

แก้ไขไฟล์ `.env`:
```env
GEMINI_API_KEY=your_paid_gemini_api_key_here
```

### ⚠️ **ข้อกำหนด API Key ที่สำคัญ**
- **Gemini 2.5 Flash Image Preview ไม่รองรับ Free Tier**
- **ต้องใช้ Paid API Key เท่านั้น** (เปิดใช้งาน billing account)
- **ค่าใช้จ่าย**: $0.039 ต่อภาพที่สร้าง
- **Free API Key จะได้รับ Error 429** หลังจากใช้งานเพียง 1-2 ครั้ง

### Settings
- ตั้งค่าจะถูกเก็บใน QSettings โดยใช้ organization "BananaEditor"
- History จะถูกเก็บในไฟล์ `banana_history.json`

## โครงสร้างไฟล์

```
banana_editor_build/
├── banana_editor_standalone.py    # โปรแกรมหลัก
├── test_standalone.py             # สคริปต์ทดสอบ
├── README.md                      # คู่มือนี้
└── banana_history.json           # ไฟล์ประวัติ (สร้างอัตโนมัติ)
```

## ข้อแตกต่างจากเวอร์ชัน Promptist

| คุณสมบัติ | Promptist Version | Standalone Version |
|---------|------------------|-------------------|
| IPC Communication | ✅ | ❌ |
| Single Instance | ✅ | ❌ |
| Auto-refresh Promptist | ✅ | ❌ |
| Organization Name | "Promptist" | "BananaEditor" |
| Window Title | "🍌 Banana Editor - New SDK Testing Tool" | "🍌 Banana Editor" |
| History File | รวมกับ Promptist | `banana_history.json` แยกไฟล์ |

## การแก้ไขปัญหา

### ปัญหาที่พบบ่อย
1. **Import Error**: ตรวจสอบ dependencies และ Python version
2. **API Key Error**: ตั้งค่า GEMINI_API_KEY ใน environment variables
3. **Error 429 (Quota Exceeded)**: API Key เป็น Free Tier - **ต้องเปลี่ยนเป็น Paid API Key**
4. **UI แสดงผิด**: ตรวจสอบ PySide6 version
5. **การสร้างภาพล้มเหลว**: ตรวจสอบว่า API Key มี billing account เปิดใช้งาน

### ล็อกการแก้ไขปัญหา
- ดูข้อความใน console สำหรับข้อมูล debug
- ตรวจสอบไฟล์ log ถ้ามี

## เวอร์ชัน

- **Version**: 1.0.0
- **Build Date**: September 2, 2025
- **Based on**: banana_editor.py (Promptist 3.5)

## 👤 About Developer

**iarcanar** - Indie developer & AI enthusiast 🤖

- 🌟 **Previous Project**: [Magicite Babel](https://iarcanar99.github.io/magicite_babel/) - Real-time translation tool
- 🎯 **Specialization**: AI integration, GUI development, automation tools
- 💡 **Philosophy**: Making AI tools accessible for everyone

### Other Projects
- 🔮 **Magicite Babel**: Real-time language translation with advanced AI
- 🍌 **Banana Editor**: AI-powered image editing (this project)

## 📄 License

MIT License - สร้างจาก Promptist Banana Editor โดยลบ IPC features เพื่อให้ใช้งานได้อิสระ

### Credits
- Original concept from Promptist project
- Developed by **iarcanar**
- Powered by Google Gemini 2.5 Flash API
- UI framework: PySide6

---
*Made with ❤️ by [iarcanar](https://github.com/iarcanar99) | Check out [Magicite Babel](https://iarcanar99.github.io/magicite_babel/)*