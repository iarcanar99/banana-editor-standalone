#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🍌 Banana Editor - Standalone Version
เครื่องมือ Image-to-Image editing อิสระ ด้วย Gemini 2.5 Flash API

วัตถุประสงค์: เครื่องมือแก้ไขภาพแบบ Image-to-Image editing ที่ใช้งานได้อิสระ
โดยไม่ต้องพึ่งพา Promptist หรือ IPC communication
"""

import sys
import os
import traceback
from pathlib import Path
from typing import Optional, List
import json
from datetime import datetime
# IPC features removed for standalone version
# import socket
# import threading
import tempfile
import time
import re
from contextlib import contextmanager
import weakref

# Qt Imports
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QFileDialog, QTextEdit, QScrollArea,
    QFrame, QSizePolicy, QMessageBox, QProgressBar, QComboBox, QDialog, QListWidget, QListWidgetItem, QGridLayout
)
from PySide6.QtCore import Qt, QThread, Signal as pyqtSignal, QTimer, QMimeData, QSettings, QRect, QPoint
from PySide6.QtGui import QPixmap, QFont, QPalette, QDragEnterEvent, QDropEvent, QPainter, QPainterPath, QCursor, QGuiApplication, QShortcut, QKeySequence, QColor, QPolygon, QWheelEvent

# Image Processing
from PIL import Image
from io import BytesIO

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()  # Load .env file
except ImportError:
    # If python-dotenv is not installed, just continue
    pass


# ===== BANANA HISTORY SYSTEM =====

class BananaHistoryItem:
    """Simplified history item for Banana Editor - Manual add only"""
    def __init__(self, prompt_text: str, timestamp: datetime = None):
        self.text = prompt_text.strip()
        self.timestamp = timestamp or datetime.now()
        # ไม่มี is_favorite เพราะทุกรายการเป็น "favorite" (manual add เท่านั้น)
        
    def to_dict(self) -> dict:
        """Convert to dict for JSON storage"""
        return {
            'text': self.text,
            'timestamp': self.timestamp.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'BananaHistoryItem':
        """Create from dict"""
        return cls(
            prompt_text=data['text'],
            timestamp=datetime.fromisoformat(data['timestamp'])
        )

class BananaHistoryManager:
    """Simple history manager for Banana Editor only - Manual add only"""
    def __init__(self):
        self.history_file = Path("banana_history.json")  # แยกไฟล์จาก Promptist
        self.max_items = 30  # ลดลงเพราะเป็น manual add เท่านั้น
        self.items = []
        self.load()  # โหลดประวัติที่มีอยู่
        
    def add_prompt(self, text: str) -> bool:
        """Add new prompt to history (MANUAL ONLY - จากการกดปุ่ม ➕)"""
        if not text.strip():
            return False
            
        # Check for duplicates กับรายการล่าสุด (ท้ายสุด)
        if self.items and self.items[-1].text.strip() == text.strip():
            return False  # ไม่เพิ่มซ้ำ
            
        item = BananaHistoryItem(text)
        self.items.append(item)  # เพิ่มที่ท้ายสุด (ใหม่สุด)
        
        # Limit items - ลบรายการเก่าสุด
        if len(self.items) > self.max_items:
            self.items = self.items[1:]  # ลบตัวแรกออก (เก่าสุด)
            
        self.save()
        return True
    
    def remove_item(self, item: BananaHistoryItem) -> bool:
        """Remove specific item from history"""
        for i, hist_item in enumerate(self.items):
            if (hist_item.text == item.text and 
                hist_item.timestamp == item.timestamp):
                del self.items[i]
                self.save()
                return True
        return False
    
    def load(self):
        """โหลดประวัติจากไฟล์"""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.items = [
                        BananaHistoryItem.from_dict(item_data) 
                        for item_data in data.get('items', [])
                    ]
            except Exception as e:
                print(f"⚠️ Error loading banana history: {e}")
                self.items = []
    
    def save(self):
        """บันทึกประวัติลงไฟล์"""
        try:
            data = {
                'items': [item.to_dict() for item in self.items],
                'created': datetime.now().isoformat()
            }
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving banana history: {e}")

class HistoryLabel(QLabel):
    """แถบข้อความแคบแสดงตัวเลข - คลิกเพื่อเลือก + focus highlight"""
    
    history_clicked = pyqtSignal(str, object)  # ส่งข้อความและ label object เมื่อคลิก
    selection_changed = pyqtSignal(object)     # ส่งเมื่อ selection เปลี่ยน
    
    def __init__(self, item: BananaHistoryItem, sequence_number: int, parent=None):
        super().__init__(parent)
        self.item = item
        self.sequence_number = sequence_number  # เก็บ sequence ที่ส่งมา
        self.is_focused = False  # สถานะ focus highlight
        self.is_selected = False  # สถานะ selection (ใหม่)
        
        self.setup_ui()
        
    def setup_ui(self):
        """Setup label appearance ตามภาพที่แสดง + focus system"""
        # ใช้ sequence number ที่ส่งมา
        display_text = f"{self.sequence_number:02d}"  # แสดงแค่ตัวเลข 01, 02, 03...
        
        self.setText(display_text)
        self.setFixedSize(26, 40)  # แคบมาก ตามภาพ
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Tooltip แสดง preview (ไม่มี hover delete แล้ว)
        self.setToolTip(f"Click to select prompt #{self.sequence_number:02d}\n\n{self.item.text[:60]}...")
        
        # เปิดใช้ mouse events
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.update_style()
    
    def update_style(self):
        """อัปเดต styling ตาม selection state"""
        if self.is_selected:
            # Selected state - สีที่เด่นชัดสำหรับรายการที่เลือก
            self.setStyleSheet("""
                QLabel {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #4a7a4a, stop:0.5 #5a8a5a, stop:1 #4a7a4a);
                    color: #ffffff;
                    border: 2px solid #6a9a6a;
                    border-radius: 3px;
                    font-size: 8px;
                    font-weight: 600;
                    padding: 2px 1px;
                    margin: 1px 0px;
                }
            """)
        elif self.is_focused:
            # Focused state - highlight เหมือน Promptist selected item
            self.setStyleSheet("""
                QLabel {
                    background-color: #3a5a3a;
                    color: #ffffff;
                    border: 1px solid #5a7b5a;
                    border-radius: 3px;
                    font-size: 8px;
                    font-weight: 600;
                    padding: 2px 1px;
                    margin: 1px 0px;
                }
            """)
        else:
            # Normal state
            self.setStyleSheet("""
                QLabel {
                    background-color: #2a4a2a;
                    color: #c8e6c9;
                    border: 1px solid #4a6b4a;
                    border-radius: 3px;
                    font-size: 8px;
                    font-weight: 500;
                    padding: 2px 1px;
                    margin: 1px 0px;
                }
                QLabel:hover {
                    background-color: #3a5a3a;
                    border-color: #5a7b5a;
                }
            """)
    
    def set_focused(self, focused: bool):
        """ตั้งค่า focus state (เหมือน Promptist highlight system)"""
        self.is_focused = focused
        self.update_style()
    
    def set_selected(self, selected: bool):
        """ตั้งค่า selection state (สำหรับระบบใหม่)"""
        self.is_selected = selected
        self.update_style()
        if selected:
            self.selection_changed.emit(self)
    
    
    def mousePressEvent(self, event):
        """เมื่อคลิก - toggle selection state และส่ง history_clicked เพื่อ compatibility"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Toggle selection และส่ง signal
            self.set_selected(not self.is_selected)
            # ส่ง history_clicked เพื่อ compatibility กับ old code
            self.history_clicked.emit(self.item.text, self)
        super().mousePressEvent(event)

# ===== END BANANA HISTORY SYSTEM =====

# IPCServer class removed for standalone version


class TextToImageWorker(QThread):
    """Worker thread for Text-to-Image generation (both Gemini and Imagen)"""
    
    images_generated = pyqtSignal(list)  # Generated image data list
    error_occurred = pyqtSignal(str)     # Error message
    status_update = pyqtSignal(str)      # Status updates
    
    def __init__(self, prompt: str, use_gemini: bool = True, aspect_ratio: str = "1:1"):
        super().__init__()
        self.prompt = prompt
        self.use_gemini = use_gemini
        self.aspect_ratio = aspect_ratio
        self.api_key = os.getenv("GEMINI_API_KEY")
        
    def run(self):
        """Run text-to-image generation"""
        try:
            self.status_update.emit("🔧 เตรียมระบบสำหรับสร้างภาพ...")
            
            if not self.api_key:
                raise Exception("GEMINI_API_KEY not found in environment variables")
            
            if self.use_gemini:
                results = self._generate_with_gemini()
            else:
                results = self._generate_with_imagen4()
                
            if not results:
                raise Exception("No images received from API")
                
            self.images_generated.emit(results)
            
        except Exception as e:
            if "GEMINI_API_KEY not found" in str(e):
                self.error_occurred.emit("❌ ไม่พบ API Key - กรุณาตั้งค่า GEMINI_API_KEY")
            elif "No images received" in str(e):
                self.error_occurred.emit("❌ API ไม่ส่งผลลัพธ์ - โปรดลองเปลี่ยนพร้อมท์ใหม่")
            else:
                self.error_occurred.emit("❌ การสร้างภาพไม่สำเร็จ - โปรดลองเปลี่ยนพร้อมท์หรือลดความซับซ้อน")
    
    def _generate_with_gemini(self) -> List[bytes]:
        """Generate with Gemini 2.5 Flash"""
        try:
            self.status_update.emit("🚀 เรียก Gemini 2.5 Flash API...")
            
            # Import New SDK
            from google import genai
            from google.genai.types import GenerateContentConfig, Modality
            
            # Create client
            client = genai.Client(api_key=self.api_key)
            
            # Enhanced prompt for text-to-image
            enhanced_prompt = f"""
            Create a high-quality image based on this description: {self.prompt}
            
            Style: photorealistic, detailed, well-composed
            Output: single image with aspect ratio {self.aspect_ratio}
            """
            
            # Configure generation
            config = GenerateContentConfig(
                response_modalities=[Modality.IMAGE, Modality.TEXT],
                candidate_count=1
            )
            
            self.status_update.emit("⏳ กำลังสร้างภาพ...")
            
            # Generate content
            response = client.models.generate_content(
                model="gemini-2.5-flash-image-preview",
                contents=enhanced_prompt,
                config=config
            )
            
            self.status_update.emit("📥 ประมวลผลผลลัพธ์...")
            
            # Extract images from response
            results = []
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and candidate.content:
                    if hasattr(candidate.content, 'parts') and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                                self.status_update.emit("✅ พบข้อมูลภาพในการตอบกลับ")
                                results.append(part.inline_data.data)
            
            if not results:
                raise Exception("No image data found in Gemini API response")
                
            return results
            
        except Exception as e:
            raise Exception(f"Gemini generation error: {str(e)}")
    
    def _generate_with_imagen4(self) -> List[bytes]:
        """Generate with Imagen 4.0"""
        try:
            self.status_update.emit("🚀 เรียก Imagen 4.0 API...")
            
            # Import New SDK
            from google import genai
            from google.genai import types
            
            # Create client
            client = genai.Client(api_key=self.api_key)
            
            self.status_update.emit("⏳ กำลังสร้างภาพคุณภาพสูง...")
            
            # Generate with Imagen
            response = client.models.generate_images(
                model="imagen-4.0-generate-preview-06-06",
                prompt=self.prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio=self.aspect_ratio,
                ),
            )
            
            self.status_update.emit("📥 ประมวลผลผลลัพธ์...")
            
            # Check if response and generated_images exist
            if not response or not hasattr(response, 'generated_images') or not response.generated_images:
                raise Exception("ไม่ได้รับผลลัพธ์จาก Imagen 4.0 API")
            
            # Convert PIL Images to bytes
            image_data_list = []
            for img in response.generated_images:
                if not img or not hasattr(img, 'image'):
                    continue
                    
                from io import BytesIO
                
                # Handle different image object types
                pil_image = img.image
                if not pil_image:
                    continue
                    
                if hasattr(pil_image, "_pil_image"):
                    pil_image = pil_image._pil_image
                elif not isinstance(pil_image, Image.Image):
                    if hasattr(pil_image, "tobytes"):
                        import numpy as np
                        if isinstance(pil_image, np.ndarray):
                            pil_image = Image.fromarray(pil_image)
                
                if pil_image:  # ตรวจสอบอีกครั้งก่อน save
                    buffer = BytesIO()
                    pil_image.save(buffer, "PNG")
                    image_data_list.append(buffer.getvalue())
            
            if not image_data_list:
                raise Exception("ไม่สามารถประมวลผลภาพใด ๆ จาก Imagen 4.0 ได้")
                
            return image_data_list
            
        except Exception as e:
            raise Exception(f"Imagen 4.0 generation error: {str(e)}")


class ImageEditWorker(QThread):
    """Worker thread สำหรับ Multiple Images Editing (รองรับ contents parameter)"""
    
    # Signals
    finished = pyqtSignal(list)  # ส่ง list ของ image data
    error = pyqtSignal(str)      # ส่ง error message
    status_update = pyqtSignal(str)  # ส่ง status updates
    
    def __init__(self, contents: list, use_new_sdk: bool = True):
        super().__init__()
        self.contents = contents  # รายการที่มี prompt และ PIL.Image objects
        self.use_new_sdk = use_new_sdk
        self.api_key = os.getenv('GEMINI_API_KEY')
        
    def run(self):
        """Run the multiple images editing process"""
        try:
            self.status_update.emit("🔄 เริ่มต้นการทำงาน...")
            
            if not self.api_key:
                self.error.emit("❌ ไม่พบ API Key - กรุณาตั้งค่า GEMINI_API_KEY")
                return
            
            self.status_update.emit("🔑 พบ API Key แล้ว")
            
            # Count images in contents (skip first item which is prompt)
            image_count = len(self.contents) - 1
            self.status_update.emit(f"📷 ประมวลผล {image_count} ภาพ...")
            
            # Process with selected SDK
            if self.use_new_sdk:
                results = self._use_new_sdk()
            else:
                results = self._use_legacy_sdk()
                
            if not results:
                self.error.emit("❌ API ไม่ส่งผลลัพธ์ - โปรดลองเปลี่ยนพร้อมท์ใหม่")
                return
                
            self.status_update.emit("✅ สำเร็จ! ได้รับผลลัพธ์แล้ว")
            self.finished.emit(results)
            
        except Exception as e:
            try:
                # Safe error logging without encoding issues
                error_msg = str(e).encode('utf-8', errors='ignore').decode('utf-8')
                print(f"[ImageEditWorker] Error: {error_msg[:100]}")
            except:
                print("[ImageEditWorker] Error (encoding issue)")
            self.error.emit("การสร้างภาพไม่สำเร็จ - โปรดลองเปลี่ยนพร้อมท์ใหม่หรือเลือกภาพอื่น")
    
    def _use_new_sdk(self) -> List[bytes]:
        """ใช้ New SDK (google-genai) สำหรับ Multiple Images editing"""
        try:
            # Import New SDK
            self.status_update.emit("📦 กำลังโหลด google-genai...")
            from google import genai
            from google.genai import types
            
            self.status_update.emit("🔧 สร้าง Client...")
            client = genai.Client(api_key=self.api_key)
            
            # เตรียม content สำหรับ multimodal input (contents ถูกเตรียมไว้แล้ว)
            # เพิ่ม aspect ratio ใน prompt
            enhanced_contents = self.contents.copy()
            if enhanced_contents and isinstance(enhanced_contents[0], str):
                enhanced_contents[0] = f"{enhanced_contents[0]}. Output the image in 1:1 aspect ratio."
            
            # กำหนดค่า config พร้อม safety settings แบบง่าย
            config = types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
                candidate_count=1,
                temperature=0.7,
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_NONE"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT",
                        threshold="BLOCK_NONE"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        threshold="BLOCK_NONE"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT",
                        threshold="BLOCK_NONE"
                    ),
                ]
            )
            
            self.status_update.emit("🚀 เรียก API สำหรับ Multiple Images editing...")
            
            # เรียก API ด้วย contents ที่เตรียมไว้
            response = client.models.generate_content(
                model="gemini-2.5-flash-image-preview",
                contents=enhanced_contents,
                config=config
            )
            
            self.status_update.emit("📥 ประมวลผลการตอบกลับจาก API...")
            
            # Process response (ใช้โค้ดเดียวกับ BananaWorker)
            print(f"[DEBUG] Response received: {response}")
            print(f"[DEBUG] Candidates count: {len(response.candidates) if response.candidates else 0}")
            
            if not response.candidates:
                print("[DEBUG] No candidates in response - this indicates API rejection or billing issue")
                raise Exception("No candidates received from API - check API key billing status")
            
            candidate = response.candidates[0]
            
            if not candidate.content:
                raise Exception("No content received from API")
            
            if not candidate.content.parts:
                raise Exception("No parts received from content")
            
            results = []
            for part in candidate.content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    if hasattr(part.inline_data, 'data'):
                        image_data = part.inline_data.data
                        results.append(image_data)
                        self.status_update.emit(f"✅ ได้รับภาพแล้ว ({len(results)} ภาพ)")
            
            if not results:
                raise Exception("No image data found in response")
            
            return results
            
        except Exception as e:
            try:
                # Safe error logging without encoding issues
                error_msg = str(e).encode('utf-8', errors='ignore').decode('utf-8')
                print(f"[ImageEditWorker] New SDK Error: {error_msg[:200]}")
            except:
                print("[ImageEditWorker] New SDK Error (cannot display details)")
            raise Exception("New SDK Error occurred")
    
    def _use_legacy_sdk(self) -> List[bytes]:
        """ใช้ Legacy SDK - placeholder (ยังไม่รองรับ multiple images)"""
        raise Exception("Legacy SDK does not support Multiple Images - please use New SDK")




class BananaEditor(QMainWindow):
    """Main UI สำหรับ Banana Editor"""
    
    def __init__(self):
        super().__init__()
        self.selected_image_path = None
        self.worker = None
        self.current_results = []
        
        # 🖼️ Multiple Start Images System
        self.image_slots = []  # List of 4 image slots
        self.image_paths = [None] * 4  # Store paths for slots 1-4
        
        # Session Management สำหรับ Multiple Images
        self.image_session = {
            'paths': [],                    # รายการ path ของภาพ (max 3)
            'thumbnails': [],              # QLabel objects สำหรับแสดง preview  
            'count': 0,                    # จำนวนภาพในปัจจุบัน
            'mode': 'single'               # 'single', 'dual', 'triple'
        }
        self.max_images_limit = 3          # จำกัดสูงสุด 3 ภาพ
        self.image_preview_layout = None   # Layout สำหรับแสดงภาพ responsive
        self.multi_image_container = None  # Container สำหรับ dual/triple layout
        
        # Save location setting (default: True = original folder)
        self.save_on_original = True
        
        # Font size settings
        self.current_font_size = 11  # Default font size
        self.min_font_size = 8
        self.max_font_size = 30
        
        # Settings for caching
        self.settings = QSettings("BananaEditor", "Settings")
        # Load saved font size
        self.current_font_size = self.settings.value("font_size", 11, type=int)
        
        # IPC Server removed for standalone version
        # self.ipc_server = None
        
        # Floating Image Viewer
        self.floating_viewer = None
        self.temp_result_files = []  # Track temporary files for cleanup
        
        self.init_ui()
        self.check_environment()
        self.setup_shortcuts()
        # self.setup_ipc_server()  # IPC removed for standalone version
        
        # 🧹 Ensure clean start - clear any residual slot data (before UI state update)
        self.clear_all_slots_on_startup()
        
        # Initialize UI state
        self.update_ui_state()
        
    def clear_all_slots_on_startup(self):
        """🧹 ล้าง slots ทั้งหมดเมื่อเริ่มต้นโปรแกรม (ไม่ใช่ preload)"""
        try:
            # Reset all image paths
            for i in range(4):
                self.image_paths[i] = None
            
            # Clear UI slots (if they exist)
            if hasattr(self, 'image_slots') and self.image_slots:
                for i, slot_widget in enumerate(self.image_slots):
                    if slot_widget:
                        image_label = slot_widget.findChild(QLabel)
                        if image_label:
                            image_label.clear()
                            image_label.setText(f"Slot {i + 1}")
                        
                        delete_btn = slot_widget.findChild(QPushButton)
                        if delete_btn:
                            delete_btn.setVisible(False)
            
            # Clear session data
            if hasattr(self, 'image_session'):
                self.image_session = {
                    'paths': [],
                    'thumbnails': [],
                    'count': 0,
                    'mode': 'single'
                }
            
            # Clear any temporary files
            if hasattr(self, 'temp_result_files'):
                self.temp_result_files.clear()
                
            print("[STARTUP-CLEANUP] All slots cleared for fresh start")
            
        except Exception as e:
            print(f"[STARTUP-CLEANUP] Error during cleanup: {e}")
        
    def init_ui(self):
        """สร้าง UI หลัก"""
        self.setWindowTitle("🍌 Banana Editor: Beta v-1")
        self.setGeometry(100, 100, 1000, 650)  # เล็กและกระชับกว่าเดิม
        
        # Remove window frame and make it movable
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        
        # Variables for window dragging and resizing
        self.drag_position = None
        self.resize_drag = False
        self.resize_start_pos = None
        self.resize_start_geometry = None
        
        # Enable drag and drop
        self.setAcceptDrops(True)
        
        # Focus state
        self.is_focused = True
        
        # History selection state
        self.selected_history_label = None  # เก็บ history label ที่เลือกไว้
        
        # Set dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1f2e1f;
                color: #c8e6c9;
                border: 2px solid #608060;
            }
            QMainWindow:!active {
                border: 1px solid #304530;
            }
            QWidget {
                background-color: #1f2e1f;
                color: #c8e6c9;
            }
        """)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Custom title bar with status
        title_bar = QWidget()
        title_bar.setFixedHeight(50)
        title_bar.setStyleSheet("""
            QWidget {
                background-color: #263a26;
                border-bottom: 1px solid #304530;
            }
        """)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(15, 0, 15, 0)
        
        # App title (left side)
        app_title = QLabel("Banana Editor v1.2")
        app_title.setStyleSheet("""
            QLabel {
                background-color: transparent;
                font-size: 14px;
                color: #c8e6c9;
                font-weight: 600;
                padding: 15px 0;
            }
        """)
        title_layout.addWidget(app_title)
        
        # Spacer to push status to the right
        title_layout.addStretch()
        
        # Status label (right side, draggable area)
        self.status_label = QLabel("🔄 เริ่มต้นระบบ...")
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: transparent;
                font-size: 12px;
                color: #c8e6c9;
                font-weight: 400;
                padding: 15px 0;
            }
        """)
        title_layout.addWidget(self.status_label)
        
        # Close button
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #c8e6c9;
                border: none;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff4444;
                color: white;
            }
        """)
        title_layout.addWidget(close_btn)
        
        main_layout.addWidget(title_bar)
        
        # Content layout
        content_layout = QHBoxLayout()
        content_layout.setSpacing(1)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        # Left Panel - File Selection & Thumbnail
        left_panel = self.create_left_panel()
        content_layout.addWidget(left_panel, 1)
        
        # Center Panel - Prompt Input
        center_panel = self.create_center_panel()
        content_layout.addWidget(center_panel, 1)
        
        # Right Panel - Results Display
        right_panel = self.create_right_panel()
        content_layout.addWidget(right_panel, 1)
        
        main_layout.addLayout(content_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(16)  # เพิ่มขนาดให้ใหญ่ขึ้น
        self.progress_bar.setMinimumWidth(200)  # ตั้งความกว้างขั้นต่ำ
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #304530;
                border: 2px solid #608060;
                border-radius: 4px;
                text-align: center;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                padding: 1px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #4CAF50, stop: 0.5 #66BB6A, stop: 1 #4CAF50);
                border-radius: 2px;
                margin: 0.5px;
            }
        """)
        main_layout.addWidget(self.progress_bar)
        
        # Error button (hidden by default)
        self.error_button = QPushButton("❌ Error Detail - คลิกเพื่อดูรายละเอียด")
        self.error_button.setVisible(False)
        self.error_button.clicked.connect(self.show_error_detail)
        self.error_button.setStyleSheet("""
            QPushButton {
                background-color: #4a1f1f;
                color: #ff6b6b;
                border: 1px solid #5a3030;
                padding: 8px 15px;
                font-size: 12px;
                font-weight: 600;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #5a2020;
                border: 1px solid #6a3535;
            }
            QPushButton:pressed {
                background-color: #3a1010;
            }
        """)
        main_layout.addWidget(self.error_button)
        
        # Variable to store error message for detail view
        self.last_error_message = ""
        
        # Initialize error translator
        self.setup_error_translator()
        
        # Add resize handle
        self.add_resize_handle()
        
        # ===== HISTORY INTEGRATION =====
        self.setup_history_integration()
        
        # Set initial status
        self.update_status("✅ ระบบพร้อมใช้งาน - เลือกภาพเพื่อเริ่มต้น (Drag & Drop รองรับ)")
    
    # IPC functions removed for standalone version
    # def setup_ipc_server(self): ...
    # def on_ipc_image_received(self, image_path): ...
    # def on_ipc_prompt_received(self, prompt_text): ...
    
    # ===== HISTORY SYSTEM INTEGRATION =====
    
    def setup_history_integration(self):
        """เชื่อมต่อ history system - เฉพาะ 3 ปุ่มหลัก"""
        # Button connections (เฉพาะที่จำเป็น)
        self.add_to_history_btn.clicked.connect(self.add_current_prompt_to_history)
        self.copy_prompt_btn.clicked.connect(self.copy_current_prompt)
        self.delete_history_btn.clicked.connect(self.delete_selected_history)
        self.clear_prompt_btn.clicked.connect(self.clear_prompt_text)
        
        # ปรับปุ่ม X ให้เป็นสีแดง
        self.delete_history_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a2a2a;
                color: #ff6666;
                border: 1px solid #6a4a4a;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
                padding: 2px;
            }
            QPushButton:hover {
                background-color: #6a3a3a;
                color: #ff8888;
                border-color: #8a5a5a;
            }
            QPushButton:pressed {
                background-color: #5a2a2a;
                color: #ffaaaa;
            }
        """)
        
        # Load existing history (ถ้ามี)
        self.refresh_history_display()
        
        # อัปเดตสถานะปุ่ม delete
        self.update_delete_button_state()
    
    def add_current_prompt_to_history(self):
        """เพิ่มพรอมต์ปัจจุบันลง history (MANUAL ONLY - การกดปุ่ม ➕)"""
        try:
            text = self.prompt_input.toPlainText().strip()
            
            if len(text) > 10:  # อย่างน้อย 10 ตัวอักษรเพื่อให้มีคุณภาพ
                success = self.history_manager.add_prompt(text)
                if success:
                    self.refresh_history_display()
                    self.update_status("✅ เพิ่มลงประวัติแล้ว")
                else:
                    self.update_status("⚠️ ข้อความซ้ำกับรายการล่าสุด")
            else:
                self.update_status("⚠️ ข้อความสั้นเกินไป (ต้อง 10+ ตัวอักษร)")
        except Exception as e:
            self.update_status(f"❌ ข้อผิดพลาด: {str(e)}")
            print(f"Error in add_current_prompt_to_history: {e}")
    
    def copy_current_prompt(self):
        """Copy prompt ปัจจุบัน (เหมือน Promptist)"""
        text = self.prompt_input.toPlainText().strip()
        if text:
            # QGuiApplication already imported
            QGuiApplication.clipboard().setText(text)
            self.update_status("✅ คัดลอกแล้ว")
        else:
            self.update_status("⚠️ ไม่มีข้อความให้คัดลอก")
    
    def clear_prompt_text(self):
        """Clear ข้อความ (เหมือน Promptist)"""
        self.prompt_input.clear()
        self.prompt_input.setFocus()
        self.update_status("📄 ล้างข้อความแล้ว")
    
    def refresh_history_display(self):
        """อัปเดตการแสดงผล history labels - แสดงเฉพาะเมื่อมี manual history"""
        # Clear existing labels
        for i in reversed(range(self.history_layout.count())):
            child = self.history_layout.itemAt(i).widget()
            if child:
                child.deleteLater()
        
        # Store current focused label reference
        self.focused_history_label = None
        
        # แสดง/ซ่อน history panel ตามจำนวนประวัติ (Manual add only)
        if len(self.history_manager.items) > 0:
            self.history_panel.setVisible(True)
            
            # Add new labels (แสดง 12 รายการแรก) - เก่าสุด = 01
            display_items = self.history_manager.items[:12]  # เอาเก่าสุดมาก่อน
            for i, item in enumerate(display_items):
                sequence_num = i + 1  # เก่าสุด = 01, ใหม่สุด = 02...
                label = HistoryLabel(item, sequence_num)
                label.history_clicked.connect(self.load_prompt_from_history)
                label.selection_changed.connect(self.on_history_selection_changed)
                self.history_layout.addWidget(label)
            
            # Add stretch to push labels to top
            self.history_layout.addStretch()
        else:
            self.history_panel.setVisible(False)  # ซ่อนเมื่อไม่มี manual history
    
    def load_prompt_from_history(self, text: str, label_obj):
        """โหลดพรอมต์จาก history + ตั้ง focus highlight"""
        # Clear previous focus
        if hasattr(self, 'focused_history_label') and self.focused_history_label:
            self.focused_history_label.set_focused(False)
        
        # Set new focus (เหมือน Promptist highlight system)
        label_obj.set_focused(True)
        self.focused_history_label = label_obj
        
        # Load prompt
        self.prompt_input.setPlainText(text)
        self.prompt_input.setFocus()
        self.update_status(f"📜 โหลดจากประวัติ: {text[:30]}...")
    
    def on_history_selection_changed(self, label_obj):
        """จัดการเมื่อ history ถูกเลือก - เคลียร์ selection อื่นๆ และเก็บ selection ใหม่"""
        # เคลียร์ selection อื่นๆ ทั้งหมด
        for i in range(self.history_layout.count() - 1):  # -1 เพราะ stretch
            item = self.history_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), HistoryLabel):
                widget = item.widget()
                if widget != label_obj:
                    widget.set_selected(False)
        
        # เก็บ selected label ใหม่
        if label_obj.is_selected:
            self.selected_history_label = label_obj
            self.update_status(f"เลือก history #{label_obj.sequence_number:02d}")
        else:
            self.selected_history_label = None
            self.update_status("ยกเลิกการเลือก")
        
        # อัปเดตสถานะปุ่ม delete
        self.update_delete_button_state()
    
    def delete_selected_history(self):
        """ลบ history ที่เลือกไว้ (ใช้กับปุ่ม X สีแดง)"""
        if not self.selected_history_label:
            return  # ไม่มีอะไรเลือก - ไม่มีการตอบสนอง
        
        # ลบออกจาก manager
        success = self.history_manager.remove_item(self.selected_history_label.item)
        if success:
            self.selected_history_label = None
            # Refresh display
            self.refresh_history_display()
            self.update_status("🗑️ ลบประวัติแล้ว")
            # อัปเดตสถานะปุ่ม delete
            self.update_delete_button_state()
        else:
            self.update_status("❌ ไม่สามารถลบประวัติได้")
    
    def update_delete_button_state(self):
        """อัปเดตสถานะปุ่ม X (เปิด/ปิด ตามการเลือก)"""
        has_selection = self.selected_history_label is not None
        
        if hasattr(self, 'delete_history_btn'):
            self.delete_history_btn.setEnabled(has_selection)
            
            if has_selection:
                # เปิดใช้งาน - สีแดงสด
                self.delete_history_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #5a2a2a;
                        color: #ff6666;
                        border: 1px solid #7a4a4a;
                        border-radius: 4px;
                        font-size: 12px;
                        font-weight: 600;
                        padding: 2px;
                    }
                    QPushButton:hover {
                        background-color: #7a3a3a;
                        color: #ff8888;
                        border-color: #9a5a5a;
                    }
                    QPushButton:pressed {
                        background-color: #6a2a2a;
                        color: #ffaaaa;
                    }
                """)
            else:
                # ปิดใช้งาน - สีเทาจาง
                self.delete_history_btn.setStyleSheet("""
                    QPushButton:disabled {
                        background-color: #3a3a3a;
                        color: #666666;
                        border: 1px solid #4a4a4a;
                        border-radius: 4px;
                        font-size: 12px;
                        font-weight: 600;
                        padding: 2px;
                    }
                """)
    
    def delete_history_item(self, label_obj):
        """ลบรายการ history (hover 2 วินาที) - เก่า method จะถูกลบออก"""
        # ลบออกจาก manager
        success = self.history_manager.remove_item(label_obj.item)
        if success:
            # Clear focus ถ้าลบรายการที่กำลัง focus อยู่
            if hasattr(self, 'focused_history_label') and self.focused_history_label == label_obj:
                self.focused_history_label = None
            
            # Refresh display
            self.refresh_history_display()
            self.update_status("🗑️ ลบประวัติแล้ว")
        else:
            self.update_status("❌ ไม่สามารถลบประวัติได้")
    
    # ===== END HISTORY INTEGRATION =====
    
    def closeEvent(self, event):
        """Handle window close - cleanup resources including memory leak prevention"""
        try:
            # Cleanup all active images
            for image in self._active_images[:]:  # Copy list to avoid modification during iteration
                try:
                    image.close()
                except:
                    pass
            self._active_images.clear()
            
            # Clear pixmap cache
            self._pixmap_cache.clear()
            
            # IPC Server removed for standalone version
            # if hasattr(self, 'ipc_server') and self.ipc_server:
            #     self.ipc_server.stop()
            #     self.ipc_server.wait(2000)
            
            # หยุด Worker thread
            if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait(2000)
            
            # ปิด floating viewer
            if hasattr(self, 'floating_viewer') and self.floating_viewer:
                self.floating_viewer.close()
                self.floating_viewer = None
            
            # ลบ temporary files
            if hasattr(self, 'temp_result_files'):
                for temp_file in self.temp_result_files:
                    try:
                        if os.path.exists(temp_file):
                            os.unlink(temp_file)
                            print(f"[FloatingViewer] Cleaned up temp file: {temp_file}")
                    except Exception as e:
                        print(f"[FloatingViewer] Error cleaning temp file {temp_file}: {e}")
                self.temp_result_files.clear()
            
            print("[BANANA] Cleanup completed with memory management")
            event.accept()
            
        except Exception as e:
            print(f"[BANANA] Error during close: {e}")
            event.accept()
    
    def create_left_panel(self) -> QFrame:
        """สร้าง Panel ซ้าย สำหรับเลือกไฟล์และแสดง thumbnail"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: #1f2e1f;
                border-right: 1px solid #304530;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # ลบหัวข้อออกเพื่อความกระชับ
        
        # Select image button with icon
        self.select_btn = QPushButton("OPEN FOLDER")
        self.select_btn.clicked.connect(self.select_image)
        self.select_btn.setStyleSheet("""
            QPushButton {
                padding: 15px;
                font-size: 14px;
                font-weight: 600;
                background-color: #304530;
                color: #c8e6c9;
                border: 1px solid #608060;
            }
            QPushButton:hover {
                background-color: #3a5a3a;
                border: 1px solid #708070;
            }
            QPushButton:pressed {
                background-color: #253525;
            }
        """)
        layout.addWidget(self.select_btn)
        
        # 🖼️ Multiple Start Images - 2x2 Slot Layout
        self.image_slots_widget = self.create_image_slots_widget()
        layout.addWidget(self.image_slots_widget, 1)  # stretch factor เพื่อขยายเต็มที่
        
        # Image info - ย่อขนาดให้เล็กลง
        self.image_info_label = QLabel("")
        self.image_info_label.setStyleSheet("""
            color: #9a9a9a;
            font-size: 10px;
            padding: 8px;
            background-color: #1a281a;
        """)
        self.image_info_label.setWordWrap(True)
        layout.addWidget(self.image_info_label, 0)  # ไม่ให้ขยาย
        
        layout.addStretch()
        return panel
    
    def create_image_slots_widget(self) -> QWidget:
        """สร้าง 2x2 Image Slots Layout สำหรับ Multiple Start Images"""
        
        # Main container
        container = QWidget()
        container.setStyleSheet("""
            QWidget {
                background-color: #1a281a;
                border: 2px dashed #405040;
                border-radius: 6px;
            }
        """)
        
        # 2x2 Grid Layout
        grid_layout = QGridLayout(container)
        grid_layout.setSpacing(8)  # ระยะห่างระหว่าง slots
        grid_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create 4 image slots
        self.image_slots = []
        slot_positions = [(0, 0), (0, 1), (1, 0), (1, 1)]  # top-left, top-right, bottom-left, bottom-right
        
        for i, (row, col) in enumerate(slot_positions):
            slot_widget = self.create_single_image_slot(i + 1)  # slot numbers 1-4
            self.image_slots.append(slot_widget)
            grid_layout.addWidget(slot_widget, row, col)
        
        # Set equal stretch for all rows and columns
        grid_layout.setRowStretch(0, 1)
        grid_layout.setRowStretch(1, 1)
        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnStretch(1, 1)
        
        return container
    
    def create_single_image_slot(self, slot_number: int) -> QWidget:
        """สร้าง slot เดียวสำหรับ image พร้อม X button"""
        
        # Slot container
        slot_widget = QWidget()
        slot_widget.setMinimumSize(120, 120)
        slot_widget.setStyleSheet("""
            QWidget {
                background-color: #2a3a2a;
                border: 1px solid #405040;
                border-radius: 4px;
            }
            QWidget:hover {
                border: 1px solid #608060;
            }
        """)
        
        # Stack layout for overlay positioning
        layout = QVBoxLayout(slot_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Image label
        image_label = QLabel(f"Slot {slot_number}")
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setScaledContents(False)  # ควบคุม aspect ratio
        image_label.setStyleSheet("""
            QLabel {
                background-color: transparent;
                color: #889888;
                font-size: 11px;
                border: none;
                padding: 10px;
            }
        """)
        
        # Delete button (hidden by default)
        delete_btn = QPushButton("✕")
        delete_btn.setFixedSize(20, 20)
        delete_btn.setVisible(False)  # Hidden when no image
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: rgba(200, 200, 200, 0.8);
                border: none;
                font-size: 16px;
                font-weight: 900;
            }
            QPushButton:hover {
                color: rgba(255, 255, 255, 1.0);
                background-color: rgba(255, 255, 255, 0.1);
            }
        """)
        
        # Position delete button at top-right corner
        delete_btn.setParent(slot_widget)
        delete_btn.move(95, 5)  # Fixed position for 120px slot
        delete_btn.raise_()  # Bring to front
        
        # Connect delete button
        delete_btn.clicked.connect(lambda: self.remove_image_from_slot(slot_number - 1))
        
        # Store references
        image_label.delete_button = delete_btn
        image_label.slot_number = slot_number - 1  # 0-based index
        
        layout.addWidget(image_label)
        
        return slot_widget
    
    def create_center_panel(self) -> QFrame:
        """สร้าง Panel กลาง สำหรับใส่ prompt"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: #1f2e1f;
                border-right: 1px solid #304530;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 15, 20, 20)  # ลด margin บนให้น้อยลงเพื่อชิดบน
        layout.setSpacing(10)  # ลด spacing ให้กระชับขึ้น
        
        # Header layout with title and floating editor button
        header_layout = QHBoxLayout()
        
        # Title
        title = QLabel("📝 Prompt")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #c8e6c9; padding: 10px 0;")
        header_layout.addWidget(title, 1)
        
        
        layout.addLayout(header_layout)
        
        # ===== COLORS SETUP =====
        self.colors = {
            'components': '#1a281a',
            'borders': '#405040'
        }
        
        # ===== HISTORY SYSTEM SETUP =====
        # Initialize history manager
        self.history_manager = BananaHistoryManager()
        self.focused_history_label = None  # Track focused history item
        
        # Prompt input container with history panel
        self.prompt_container = QFrame()
        self.prompt_container.setStyleSheet("""
            QFrame {
                background-color: transparent;
                border: none;
            }
        """)
        prompt_main_layout = QVBoxLayout(self.prompt_container)
        prompt_main_layout.setContentsMargins(0, 0, 0, 0)
        prompt_main_layout.setSpacing(2)
        
        # === Text Editor Area with History Panel ===
        text_editor_layout = QHBoxLayout()
        text_editor_layout.setContentsMargins(0, 0, 0, 0)
        text_editor_layout.setSpacing(2)
        
        # === History Panel (ด้านซ้าย - แถบแคบตามภาพ) ===
        self.history_panel = QWidget()
        self.history_panel.setFixedWidth(30)  # แคบมาก แค่แสดงวันที่
        self.history_panel.setVisible(False)  # ซ่อนจนกว่าจะมีประวัติ
        
        # History scroll area (สำหรับเลื่อนเมื่อประวัติเยอะ)
        history_layout = QVBoxLayout(self.history_panel)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(1)
        
        self.history_scroll = QScrollArea()
        self.history_scroll.setFixedWidth(28)
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background-color: rgba(40, 40, 40, 100);
                width: 4px;
                border-radius: 2px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: rgba(80, 80, 80, 150);
                border-radius: 2px;
                min-height: 20px;
            }
        """)
        
        # History content widget
        self.history_content = QWidget()
        self.history_layout = QVBoxLayout(self.history_content)
        self.history_layout.setSpacing(1)
        self.history_layout.setContentsMargins(2, 2, 2, 2)
        
        self.history_scroll.setWidget(self.history_content)
        history_layout.addWidget(self.history_scroll)
        
        # === Text Editor Area (ด้านขวา) ===
        text_editor_widget = QWidget()
        text_editor_layout_v = QVBoxLayout(text_editor_widget)
        text_editor_layout_v.setContentsMargins(0, 0, 0, 0)
        text_editor_layout_v.setSpacing(2)
        
        # === Button Bar (ด้านบนของ text editor) ===
        button_bar = QHBoxLayout()
        button_bar.setContentsMargins(4, 2, 4, 2)
        button_bar.setSpacing(4)
        
        # Prompt label
        prompt_label = QLabel("📝 Prompt")
        prompt_label.setStyleSheet("color: #c8e6c9; font-weight: 500; font-size: 11px;")
        button_bar.addWidget(prompt_label)
        
        button_bar.addStretch()  # Push buttons to right
        
        # Action buttons (emoji only, no text) - เฉพาะปุ่มที่จำเป็น
        self.copy_prompt_btn = QPushButton("📋")            # Copy
        self.add_to_history_btn = QPushButton("➕")          # Add to history (manual only)
        self.delete_history_btn = QPushButton("❌")         # Delete selected history (ใหม่)
        self.clear_prompt_btn = QPushButton("📄")           # Clear
        
        # Button styling
        button_style = f"""
            QPushButton {{
                background-color: {self.colors['components']};
                color: #c8e6c9;
                border: 1px solid {self.colors['borders']};
                border-radius: 4px;
                font-size: 12px;
                padding: 2px 4px;
            }}
            QPushButton:hover {{
                background-color: #3a5a3a;
                border-color: #5a7b5a;
            }}
            QPushButton:pressed {{
                background-color: #1a3a1a;
            }}
        """
        
        for btn in [self.copy_prompt_btn, self.add_to_history_btn, self.delete_history_btn, self.clear_prompt_btn]:
            btn.setFixedSize(28, 24)
            btn.setStyleSheet(button_style)
            button_bar.addWidget(btn)
        
        # Set tooltips
        self.copy_prompt_btn.setToolTip("Copy current prompt to clipboard")
        self.add_to_history_btn.setToolTip("Add current prompt to history (manual save)")
        self.delete_history_btn.setToolTip("Delete selected history item (เลือก history ก่อน)")
        self.clear_prompt_btn.setToolTip("Clear prompt text")
        
        # === Text Editor (ใช้เดิม) ===
        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText(
            "ใส่คำอธิบายภาพที่ต้องการแก้ไขหรือสร้างใหม่...\nเช่น: Add red pants, Remove hat, Create a cat on the beach..."
        )
        # ตั้งให้เล็กลง แต่ไม่จำกัด maximum เพื่อให้ขยายลงได้
        self.prompt_input.setMinimumHeight(80)
        # ลบ setMaximumHeight เพื่อให้สามารถ resize ลงได้ไม่จำกัด
        self.prompt_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)  # เปลี่ยนเป็น Expanding ทั้งคู่
        self.prompt_input.textChanged.connect(self.update_ui_state)  # Update UI when text changes
        # Apply saved font size
        self.apply_font_size()
        self.prompt_input.setStyleSheet("""
            QTextEdit {
                background-color: #1a281a;
                border: 1px solid #405040;
                color: #c8e6c9;
                padding: 12px;
                font-family: 'Segoe UI';
                line-height: 1.4;
            }
            QTextEdit:focus {
                border: 1px solid #608060;
            }
            /* Resize handle styling */
            QTextEdit::corner {
                background-color: #405040;
            }
        """)
        
        # Assemble text editor area
        text_editor_layout_v.addLayout(button_bar)
        text_editor_layout_v.addWidget(self.prompt_input, 1)
        
        # Combine layouts
        text_editor_layout.addWidget(self.history_panel)     # ซ้าย (ซ่อนจนกว่าจะมีประวัติ)
        text_editor_layout.addWidget(text_editor_widget, 1)  # ขวา (ขยายเต็มที่)
        
        # Add to main prompt layout
        prompt_main_layout.addLayout(text_editor_layout, 1)
        
        # Add custom resize handle for prompt box (using same icon as main resize)
        self.prompt_resize_handle = QLabel()
        self.prompt_resize_handle.setFixedSize(15, 15)  # Half size of main resize handle
        
        # Try to load resize.png icon
        resize_path = Path("resize.png")
        if resize_path.exists():
            pixmap = QPixmap(str(resize_path))
            if not pixmap.isNull():
                # Scale to half size (15x15 instead of 30x30)
                scaled_pixmap = pixmap.scaled(15, 15, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.prompt_resize_handle.setPixmap(scaled_pixmap)
            else:
                self.prompt_resize_handle.setText("◢")
        else:
            # Fallback to text if icon doesn't exist
            self.prompt_resize_handle.setText("◢")
        
        self.prompt_resize_handle.setStyleSheet("""
            QLabel {
                background-color: transparent;
                padding: 0px;
            }
            QLabel:hover {
                background-color: #405040;
                border-radius: 3px;
            }
        """)
        self.prompt_resize_handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt_resize_handle.setCursor(Qt.CursorShape.SizeFDiagCursor)
        
        # Position handle at bottom-right of prompt container
        self.prompt_resize_handle.setParent(self.prompt_container)
        
        # Set initial height for prompt container
        self.prompt_container.setMinimumHeight(100)
        self.prompt_container.setMaximumHeight(300)  # Initial max height
        self.prompt_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # Variables for prompt resize tracking
        self.prompt_resizing = False
        self.prompt_resize_start_pos = None
        self.prompt_resize_start_height = None
        
        # Image cache management for memory leak prevention
        self._active_images = []  # Keep track of PIL Images
        self._max_cache_size = 5  # Maximum cached images
        self._pixmap_cache = {}   # QPixmap cache with weak references
        
        # Install event filter for prompt resize handle
        self.prompt_resize_handle.installEventFilter(self)
        
        # Update handle position when container resizes
        self.prompt_container.resizeEvent = self.prompt_container_resize_event
        
        layout.addWidget(self.prompt_container, 0)  # ไม่ auto-stretch แต่ผู้ใช้ resize ได้
        
        # Initial position for prompt resize handle
        QTimer.singleShot(0, lambda: self.prompt_container_resize_event(None))
        
        # เพิ่ม stretch space เพื่อดันปุ่มลงไปด้านล่างเสมอ
        layout.addStretch(1)
        
        # Generation Mode Selection
        mode_layout = QVBoxLayout()
        
        # Mode title
        mode_title = QLabel("🎨 Generation Mode:")
        mode_title.setStyleSheet("""
            QLabel {
                color: #c8e6c9;
                font-size: 14px;
                font-weight: 600;
                margin-bottom: 10px;
                margin-top: 15px;
            }
        """)
        mode_layout.addWidget(mode_title)
        
        # First row: Image-to-Image (requires image)
        img_to_img_layout = QHBoxLayout()
        self.img_to_img_btn = QPushButton("🍌 แต่งภาพด้วย-BANANA")
        self.img_to_img_btn.setToolTip("แก้ไขภาพด้วย Banana Editor (Gemini 2.5 Flash)")
        self.img_to_img_btn.clicked.connect(lambda: self.start_generation("image_to_image"))
        self.img_to_img_btn.setStyleSheet(self.get_button_style("primary"))
        img_to_img_layout.addWidget(self.img_to_img_btn)
        mode_layout.addLayout(img_to_img_layout)
        
        # Second row: Text-to-Image buttons with aspect ratio on same line
        buttons_layout = QHBoxLayout()
        
        # Text-to-Image Button  
        self.txt_to_img_btn = QPushButton("📝 สร้างภาพ")
        self.txt_to_img_btn.setToolTip("สร้างภาพใหม่จากข้อความด้วย Gemini 2.5 Flash")
        self.txt_to_img_btn.clicked.connect(lambda: self.start_generation("text_to_image"))
        self.txt_to_img_btn.setStyleSheet(self.get_button_style("secondary"))
        
        # Imagen-4 Button (high quality)
        self.imagen4_btn = QPushButton("✨ สร้างภาพ-HD")
        self.imagen4_btn.setToolTip("สร้างภาพคุณภาพสูงด้วย Imagen 4.0 (ช้าแต่คุณภาพดีที่สุด)")
        self.imagen4_btn.clicked.connect(lambda: self.start_generation("imagen4"))
        self.imagen4_btn.setStyleSheet(self.get_button_style("premium"))
        
        # Aspect ratio dropdown (compact version)
        # QComboBox already imported
        self.aspect_combo = QComboBox()
        self.aspect_combo.addItems([
            "1:1",      # ลบเท็กซ์ตามที่ขอ
            "16:9", 
            "9:16",
            "4:3",
            "3:4"
        ])
        self.aspect_combo.setCurrentText("1:1")
        self.aspect_combo.setMaximumWidth(80)  # ทำให้กล่องแคบลง
        self.aspect_combo.setStyleSheet("""
            QComboBox {
                padding: 8px 6px;
                background-color: #304530;
                color: #c8e6c9;
                border: 1px solid #405040;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 500;
            }
            QComboBox:drop-down {
                border: none;
                background-color: #405040;
                width: 20px;
            }
            QComboBox:down-arrow {
                border: 1px solid #608060;
            }
        """)
        
        # Batch count dropdown (สำหรับเลือกจำนวนภาพ 1-4)
        self.batch_combo = QComboBox()
        self.batch_combo.addItems(["1-img", "2-img", "3-img", "4-img"])
        self.batch_combo.setCurrentText("1-img")
        self.batch_combo.setMaximumWidth(70)
        self.batch_combo.setStyleSheet("""
            QComboBox {
                padding: 8px 6px;
                background-color: #304530;
                color: #c8e6c9;
                border: 1px solid #405040;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 500;
            }
            QComboBox:drop-down {
                border: none;
            }
            QComboBox:down-arrow {
                border: 1px solid #608060;
            }
        """)
        
        # Create layout for dropdowns (aspect ratio บน, batch count ล่าง)
        dropdown_layout = QVBoxLayout()
        dropdown_layout.setSpacing(4)
        dropdown_layout.addWidget(self.aspect_combo)
        dropdown_layout.addWidget(self.batch_combo)
        
        # Add widgets to buttons layout
        buttons_layout.addWidget(self.txt_to_img_btn)
        buttons_layout.addWidget(self.imagen4_btn)
        buttons_layout.addLayout(dropdown_layout)  # เปลี่ยนจาก widget เป็น layout
        
        mode_layout.addLayout(buttons_layout)  # เพิ่มโดยตรง
        layout.addLayout(mode_layout)
        
        # [REMOVED] Duplicate progress_bar - using the one from main layout
        
        # [REMOVED] Save results button - ไม่จำเป็นเพราะมีการ save อัตโนมัติ
        
        return panel
    
    def create_right_panel(self) -> QFrame:
        """สร้าง Panel ขวา สำหรับแสดงผลลัพธ์ - คล้ายกับ left panel"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: #1f2e1f;
                border-left: 1px solid #304530;
            }
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # ลบหัวข้อออกเพื่อความกระชับ
        
        # ภาพผลลัพธ์ - เหมือน thumbnail ใน left panel
        self.result_image_label = QLabel("ยังไม่มีผลลัพธ์")
        self.result_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_image_label.setScaledContents(False)  # ควบคุม aspect ratio
        self.result_image_label.setStyleSheet("""
            QLabel {
                border: 2px dashed #405040;
                padding: 5px;
                background-color: #1a281a;
                min-height: 400px;
                color: #889888;
                font-size: 13px;
            }
        """)
        layout.addWidget(self.result_image_label, 1)  # stretch factor เพื่อขยายเต็มที่
        
        # Result image info - เหมือน left panel
        self.result_info_label = QLabel("")
        self.result_info_label.setStyleSheet("""
            color: #9a9a9a;
            font-size: 10px;
            padding: 8px;
            background-color: #1a281a;
        """)
        self.result_info_label.setWordWrap(True)
        layout.addWidget(self.result_info_label, 0)  # ไม่ให้ขยาย
        
        layout.addStretch()  # เผื่อพื้นที่ส่วนล่าง
        
        # Save location toggle button (เหมือนเดิม)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_location_button = QPushButton("SAVE ON ORIGINAL FOLDER")
        self.save_location_button.clicked.connect(self.on_save_location_toggle)
        self.save_location_button.setStyleSheet("""
            QPushButton {
                background-color: #b8860b;
                color: #2d2d2d;
                border: 2px solid #d4af37;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 10px;
                font-weight: bold;
                min-width: 160px;
            }
            QPushButton:hover {
                background-color: #d4af37;
                border-color: #ffd700;
            }
            QPushButton:pressed {
                background-color: #9a7c0a;
                border-color: #b8860b;
            }
        """)
        
        button_layout.addWidget(self.save_location_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        return panel
    
    def check_environment(self):
        """ตรวจสอบสภาพแวดล้อม"""
        api_key = os.getenv('GEMINI_API_KEY')
        
        # Check if .env file exists
        env_file = Path('.env')
        env_exists = env_file.exists()
        
        if not api_key:
            env_help = ""
            if env_exists:
                env_help = "\n\nหรือใส่ใน .env file:\nGEMINI_API_KEY=your_api_key_here"
            else:
                env_help = "\n\nหรือสร้างไฟล์ .env:\nGEMINI_API_KEY=your_api_key_here"
            
            self.update_status("⚠️ ไม่พบ GEMINI_API_KEY")
            QMessageBox.warning(
                self, 
                "ไม่พบ API Key",
                f"กรุณาตั้งค่า GEMINI_API_KEY\n\n"
                f"วิธีที่ 1 - Environment Variables:\n"
                f"Windows: set GEMINI_API_KEY=your_api_key_here\n"
                f"Linux/Mac: export GEMINI_API_KEY=your_api_key_here"
                f"{env_help}"
            )
        else:
            status_msg = "✅ ระบบพร้อมใช้งาน - พบ API Key แล้ว"
            if env_exists:
                status_msg += " (โหลดจาก .env)"
            self.update_status(status_msg)
    
    def update_status(self, message: str):
        """อัปเดตสถานะ"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_label.setText(f"[{timestamp}] {message}")
    
    def save_single_result(self, image, index):
        """บันทึกภาพผลลัพธ์เดี่ยว"""
        try:
            # ใช้ save location toggle setting
            if hasattr(self, 'save_on_original') and not self.save_on_original:
                save_dir = Path.cwd() / "banana_results"
                save_dir.mkdir(exist_ok=True)
            else:
                # Save to original folder
                if hasattr(self, 'current_image_path') and self.current_image_path:
                    save_dir = Path(self.current_image_path).parent
                else:
                    # Default: สร้างโฟลเดอร์ banana ในตำแหน่งปัจจุบัน
                    save_dir = Path.cwd() / "banana"
                    save_dir.mkdir(exist_ok=True)
            
            # Generate filename using new naming system
            now = datetime.now()
            date_str = f"{now.day}{now.strftime('%b').lower()}"  # 1sep, 2oct, etc.
            start_number = self.get_next_file_number(save_dir, date_str)
            filename = f"banana_{date_str}_{start_number + index:03d}.png"
            file_path = save_dir / filename
            
            # Safety check for file collision
            counter = 0
            while file_path.exists() and counter < 1000:
                counter += 1
                filename = f"banana_{date_str}_{start_number + index + counter:03d}.png"
                file_path = save_dir / filename
            
            # Save image
            image.save(str(file_path), "PNG")
            
            self.update_status(f"✅ บันทึกภาพที่ {index+1} สำเร็จ: {file_path.name}")
            
        except Exception as e:
            self.update_status(f"❌ ไม่สามารถบันทึกภาพที่ {index+1} ได้: {e}")
    
    def on_save_location_toggle(self):
        """สลับสถานะการบันทึก"""
        # สลับสถานะ
        self.save_on_original = not self.save_on_original
        
        # อัปเดตข้อความและสีบนปุ่มตามสถานะปัจจุบัน
        if self.save_on_original:
            # Original folder - สีเหลือง
            self.save_location_button.setText("SAVE ON ORIGINAL FOLDER")
            self.save_location_button.setStyleSheet("""
                QPushButton {
                    background-color: #b8860b;
                    color: #2d2d2d;
                    border: 2px solid #d4af37;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 10px;
                    font-weight: bold;
                    min-width: 160px;
                }
                QPushButton:hover {
                    background-color: #daa520;
                    border-color: #ffd700;
                    color: #1a1a1a;
                }
                QPushButton:pressed {
                    background-color: #9a7c0a;
                    border-color: #b8860b;
                }
            """)
        else:
            # Banana folder - สีเขียวสว่าง
            self.save_location_button.setText("SAVE ON BANANA FOLDER")
            self.save_location_button.setStyleSheet("""
                QPushButton {
                    background-color: #4a7c59;
                    color: #e8f5e8;
                    border: 2px solid #5a8c69;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 10px;
                    font-weight: bold;
                    min-width: 160px;
                }
                QPushButton:hover {
                    background-color: #5a8c69;
                    border-color: #6a9c79;
                    color: #ffffff;
                }
                QPushButton:pressed {
                    background-color: #3a6c49;
                    border-color: #4a7c59;
                }
            """)
    
    def mousePressEvent(self, event):
        """Handle mouse press for window dragging and resizing"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if self.is_in_resize_area(pos):
                # Start resizing
                self.resize_drag = True
                self.resize_start_pos = event.globalPosition().toPoint()
                self.resize_start_geometry = self.geometry()
                event.accept()
            else:
                # Start dragging
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for window dragging and resizing"""
        if self.resize_drag and event.buttons() == Qt.MouseButton.LeftButton:
            # Handle resizing
            if self.resize_start_pos and self.resize_start_geometry:
                diff = event.globalPosition().toPoint() - self.resize_start_pos
                new_width = max(800, self.resize_start_geometry.width() + diff.x())
                new_height = max(500, self.resize_start_geometry.height() + diff.y())
                self.resize(new_width, new_height)
            event.accept()
        elif event.buttons() == Qt.MouseButton.LeftButton and self.drag_position:
            # Handle dragging
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
        else:
            # Check if mouse is over resize area
            pos = event.position().toPoint()
            if self.is_in_resize_area(pos):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release for window dragging and resizing"""
        self.drag_position = None
        self.resize_drag = False
        self.resize_start_pos = None
        self.resize_start_geometry = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
    
    def setup_shortcuts(self):
        """ตั้งค่า keyboard shortcuts"""
        # QShortcut, QKeySequence already imported
        
        # Ctrl+V for paste from clipboard (4-slot system)
        paste_shortcut = QShortcut(QKeySequence("Ctrl+V"), self)
        paste_shortcut.activated.connect(self.paste_from_clipboard)
        
        # Ctrl+P for paste from clipboard (alternative shortcut)
        paste_shortcut_p = QShortcut(QKeySequence("Ctrl+P"), self)
        paste_shortcut_p.activated.connect(self.paste_from_clipboard)
        
        # Ctrl+Enter for triggering GEN-AI button
        generate_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        generate_shortcut.activated.connect(self.trigger_gen_ai)
        
        # Alternative Ctrl+Enter
        generate_shortcut2 = QShortcut(QKeySequence("Ctrl+Enter"), self)
        generate_shortcut2.activated.connect(self.trigger_gen_ai)
        
        # Note: Ctrl+Scroll for font size adjustment is handled in wheelEvent
        
    
    def get_button_style(self, button_type: str) -> str:
        """Get button stylesheet based on type"""
        base_style = """
            QPushButton {
                padding: 15px;
                font-size: 14px;
                font-weight: bold;
                border: 2px solid;
                border-radius: 8px;
                min-height: 20px;
            }
            QPushButton:hover {
                margin-top: 1px;
            }
            QPushButton:pressed {
                margin-top: 0px;
            }
            QPushButton:disabled {
                opacity: 0.4;
                background-color: #2a2a2a;
                color: #666;
                border-color: #444;
            }
        """
        
        if button_type == "primary":  # IMG-TO-IMG - สีเขียวเข้ม
            return base_style + """
                QPushButton:enabled {
                    background-color: #2d5a2d;
                    color: #c8e6c9;
                    border-color: #4a7c4a;
                }
                QPushButton:enabled:hover {
                    background-color: #3d6a3d;
                    border-color: #5a8c5a;
                }
            """
        elif button_type == "secondary":  # TXT-TO-IMG - สีฟ้าเขียว
            return base_style + """
                QPushButton:enabled {
                    background-color: #2d4a5a;
                    color: #c8d6e6;
                    border-color: #4a6c7c;
                }
                QPushButton:enabled:hover {
                    background-color: #3d5a6a;
                    border-color: #5a7c8c;
                }
            """
        elif button_type == "premium":  # IMAGEN-4 - สีทอง
            return base_style + """
                QPushButton:enabled {
                    background-color: #5a4a2d;
                    color: #f0e6c8;
                    border-color: #7c6c4a;
                }
                QPushButton:enabled:hover {
                    background-color: #6a5a3d;
                    border-color: #8c7c5a;
                }
            """
        else:
            return base_style
    
    def update_ui_state(self):
        """Update UI state based on current conditions"""
        has_image = bool(self.selected_image_path and os.path.exists(self.selected_image_path))
        has_prompt = bool(self.prompt_input.toPlainText().strip())
        
        # IMG-TO-IMG: ต้องมีทั้งภาพและ prompt
        if has_image and has_prompt:
            self.img_to_img_btn.setEnabled(True)
            self.img_to_img_btn.setToolTip("✅ แก้ไขภาพที่มีอยู่ด้วย Gemini 2.5 Flash")
        elif not has_image:
            self.img_to_img_btn.setEnabled(False)
            self.img_to_img_btn.setToolTip("❌ ต้องเลือกภาพก่อน (Drag & Drop หรือ Paste)")
        else:  # no prompt
            self.img_to_img_btn.setEnabled(False)
            self.img_to_img_btn.setToolTip("❌ ต้องใส่คำอธิบายการแก้ไข")
        
        # TXT-TO-IMG และ IMAGEN-4: ต้องมีแค่ prompt
        if has_prompt:
            self.txt_to_img_btn.setEnabled(True)
            self.txt_to_img_btn.setToolTip("✅ สร้างภาพใหม่จากข้อความด้วย Gemini 2.5 Flash")
            
            self.imagen4_btn.setEnabled(True)
            self.imagen4_btn.setToolTip("✅ สร้างภาพคุณภาพสูงด้วย Imagen 4.0 (ช้าแต่คุณภาพดีที่สุด)")
        else:
            self.txt_to_img_btn.setEnabled(False)
            self.txt_to_img_btn.setToolTip("❌ ต้องใส่คำอธิบายภาพที่ต้องการ")
            
            self.imagen4_btn.setEnabled(False) 
            self.imagen4_btn.setToolTip("❌ ต้องใส่คำอธิบายภาพที่ต้องการ")
        
        # Update status based on state
        if has_image and has_prompt:
            self.update_status("✅ พร้อมใช้งานทุกโหมด | เลือกโหมดการสร้าง")
        elif has_image:
            self.update_status("📝 ใส่คำอธิบายเพื่อเริ่มแก้ไข")
        elif has_prompt:
            self.update_status("🎨 พร้อมสร้างภาพใหม่ | เลือก TXT-TO-IMG หรือ IMAGEN-4")
        else:
            self.update_status("📂 Drag & Drop ภาพ หรือใส่คำอธิบายเพื่อเริ่มต้น")
    
    def start_generation(self, mode: str):
        """Start generation based on selected mode"""
        prompt = self.prompt_input.toPlainText().strip()
        
        if not prompt:
            self.update_status("❌ ต้องใส่คำอธิบายก่อน")
            return
        
        # ล้าง temp_result_files จากเซสชันก่อนหน้าเพื่อป้องกัน FloatingImageViewer แสดงผิด
        if hasattr(self, 'temp_result_files'):
            self.temp_result_files.clear()
            print("[GENERATION] Cleared temp_result_files from previous session")
        
        if mode == "image_to_image":
            if not self.selected_image_path or not os.path.exists(self.selected_image_path):
                self.update_status("❌ ต้องเลือกภาพก่อน")
                return
            
            # Get batch count for Banana editing
            batch_count = self.get_batch_count()
            
            if batch_count == 1:
                # Single image editing - แบบเดิม
                self.update_status("🍌 กำลังแก้ไขภาพด้วย Gemini 2.5 Flash...")
                self.start_editing(use_new_sdk=True)
            else:
                # Batch image editing - สร้างหลายภาพจากภาพเดียว
                self.update_status(f"🍌 กำลังสร้าง {batch_count} variations ด้วย Banana Editor...")
                self.start_batch_image_editing(batch_count)
            
        elif mode == "text_to_image":
            self.update_status("🎨 กำลังสร้างภาพใหม่ด้วย Gemini 2.5 Flash...")
            self.start_text_to_image_generation(use_gemini=True)
            
        elif mode == "imagen4":
            self.update_status("✨ กำลังสร้างภาพคุณภาพสูงด้วย Imagen 4.0...")
            # แสดง progress bar สำหรับ Imagen-4 เหมือนกับ text-to-image อื่นๆ
            if hasattr(self, 'progress_bar'):
                self.progress_bar.setVisible(True)
                self.progress_bar.setRange(0, 0)  # Indeterminate progress
                self.progress_bar.setValue(0)  # Reset value
            self.start_text_to_image_generation(use_gemini=False)
    
    def trigger_gen_ai(self):
        """เรียกใช้งานปุ่ม IMG-TO-IMG ผ่าน hotkey"""
        if self.img_to_img_btn.isEnabled():
            self.start_generation("image_to_image")
    
    
    
    def get_batch_count(self) -> int:
        """Get number of images to generate from batch combo"""
        batch_text = self.batch_combo.currentText()
        return int(batch_text.split('-')[0])  # Extract number from "1-img", "2-img", etc.
    
    def get_aspect_ratio(self) -> str:
        """Convert aspect ratio from combo box to API format"""
        combo_text = self.aspect_combo.currentText()
        if "1:1" in combo_text:
            return "1:1"
        elif "16:9" in combo_text:
            return "16:9" 
        elif "9:16" in combo_text:
            return "9:16"
        elif "4:3" in combo_text:
            return "4:3"
        elif "3:4" in combo_text:
            return "3:4"
        else:
            return "1:1"  # Default
    
    def start_text_to_image_generation(self, use_gemini: bool = True):
        """Start Text-to-Image generation with batch support"""
        prompt = self.prompt_input.toPlainText().strip()
        if not prompt:
            self.update_status("❌ ต้องใส่คำอธิบายภาพที่ต้องการ")
            return
            
        # Get parameters
        aspect_ratio = self.get_aspect_ratio()
        batch_count = self.get_batch_count()
            
        # Disable all buttons during generation
        self.set_buttons_enabled(False)
        
        # Initialize batch tracking
        self.batch_workers = []
        self.batch_results = []
        self.completed_workers = 0
        self.total_workers = batch_count
        
        # Setup progress bar for batch generation
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setVisible(True)
            if batch_count > 1:
                self.progress_bar.setRange(0, batch_count)  # Determinate progress for batch
                self.progress_bar.setValue(0)
            else:
                self.progress_bar.setRange(0, 0)  # Indeterminate for single image
        
        status_text = f"🚀 เริ่มสร้าง {batch_count} ภาพพร้อมกัน..."
        self.update_status(status_text)
        
        # Create multiple workers for concurrent generation
        for i in range(batch_count):
            worker = TextToImageWorker(prompt, use_gemini, aspect_ratio)
            worker.images_generated.connect(self.on_batch_worker_complete)
            worker.error_occurred.connect(self.on_batch_worker_error)
            worker.status_update.connect(lambda msg, idx=i: self.update_status(f"Worker {idx+1}: {msg}"))
            
            self.batch_workers.append(worker)
            worker.start()  # Start immediately for concurrent processing
    
    def start_batch_image_editing(self, batch_count: int):
        """Start batch Image-to-Image editing (multiple variations from single image)"""
        prompt = self.prompt_input.toPlainText().strip()
        
        # Disable all buttons during generation
        self.set_buttons_enabled(False)
        
        # Initialize batch tracking
        self.batch_workers = []
        self.batch_results = []
        self.completed_workers = 0
        self.total_workers = batch_count
        
        # Setup progress bar for batch generation
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, batch_count)  # Determinate progress for batch
            self.progress_bar.setValue(0)
        
        # Prepare image content for editing
        try:
            from PIL import Image
            with Image.open(self.selected_image_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Resize if needed
                max_size = 1024
                if max(img.size) > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
                # Create multiple workers for concurrent editing
                for i in range(batch_count):
                    # Each worker gets the same prompt and image but may produce different results
                    contents = [prompt, img.copy()]  # [prompt, PIL.Image]
                    
                    worker = ImageEditWorker(contents, use_new_sdk=True)
                    worker.finished.connect(self.on_batch_worker_complete)
                    worker.error.connect(self.on_batch_worker_error)
                    worker.status_update.connect(lambda msg, idx=i: self.update_status(f"Worker {idx+1}: {msg}"))
                    
                    self.batch_workers.append(worker)
                    worker.start()  # Start immediately for concurrent processing
                    
        except Exception as e:
            self.update_status(f"❌ Error preparing batch editing: {str(e)}")
            self.set_buttons_enabled(True)
    
    def on_batch_worker_complete(self, image_data_list: list):
        """Handle completion of one worker in batch generation"""
        print(f"[WORKER-COMPLETE] Worker finished with {len(image_data_list)} images")
        self.completed_workers += 1
        self.batch_results.extend(image_data_list)
        print(f"[WORKER-COMPLETE] Total results now: {len(self.batch_results)}")
        
        # Update progress bar
        if hasattr(self, 'progress_bar') and self.total_workers > 1:
            self.progress_bar.setValue(self.completed_workers)
        
        progress_text = f"✅ เสร็จแล้ว {self.completed_workers}/{self.total_workers} งาน"
        self.update_status(progress_text)
        
        # Check if all workers are done
        if self.completed_workers >= self.total_workers:
            self.on_all_batch_workers_complete()
    
    def on_batch_worker_error(self, error_message: str):
        """Handle error from one worker in batch generation"""
        try:
            print("[BATCH-ERROR] Worker error:", str(error_message)[:100])
        except:
            print("[BATCH-ERROR] Worker error (encoding issue)")
        self.completed_workers += 1
        
        # Update progress bar even on error
        if hasattr(self, 'progress_bar') and self.total_workers > 1:
            self.progress_bar.setValue(self.completed_workers)
        
        # Continue even if some workers fail
        progress_text = f"⚠️ {self.completed_workers}/{self.total_workers} งาน (มี error)"
        self.update_status(progress_text)
        
        if self.completed_workers >= self.total_workers:
            self.on_all_batch_workers_complete()
    
    def on_all_batch_workers_complete(self):
        """Handle completion of all batch workers"""
        try:
            # Hide progress bar safely
            if hasattr(self, 'progress_bar'):
                self.progress_bar.setVisible(False)
            
            self.results = self.batch_results
            
            # 🛠️ MIXED RESULTS FIX: ตรวจสอบทั้งผลลัพธ์ใน memory และไฟล์ที่บันทึกจริง
            saved_files = []
            has_api_results = bool(self.batch_results)
            print(f"[BATCH-COMPLETE] has_api_results={has_api_results}, batch_results_count={len(self.batch_results)}")
            
            # ตรวจหาไฟล์ที่บันทึกจริงๆ (กรณี API error แต่บันทึกได้)
            if hasattr(self, 'selected_image_path') and self.selected_image_path:
                saved_files = self._check_saved_files()
                print(f"[BATCH-COMPLETE] Found {len(saved_files)} saved files")
            
            if has_api_results:
                # แสดงผลลัพธ์จาก API memory
                print(f"[BATCH-COMPLETE] Calling display_results with {len(self.batch_results)} results")
                self.display_results(self.batch_results)
                
                # Auto-save for all generated images
                self.auto_save_results(self.batch_results)
                location = "โฟลเดอร์ต้นฉบับ" if (self.save_on_original and hasattr(self, 'selected_image_path') and self.selected_image_path) else "โฟลเดอร์ banana"
                self.update_status(f"✅ สำเร็จ! ได้รับภาพ {len(self.batch_results)} ภาพ และบันทึกอัตโนมัติใน{location}แล้ว")
                    
            elif saved_files:
                # 🎯 กรณีสำคัญ: API error แต่มีไฟล์บันทึกจริง - แสดงไฟล์ที่บันทึกแทน mock
                self._display_saved_files_as_results(saved_files)
                success_count = len(saved_files)
                failed_count = self.total_workers - success_count
                location = "โฟลเดอร์ต้นฉบับ" if self.save_on_original else "โฟลเดอร์ banana"
                self.update_status(f"⚠️ ผลลัพธ์แบบผสม: สำเร็จ {success_count}/{self.total_workers} ภาพ (บันทึกอัตโนมัติใน{location}แล้ว)")
                
            else:
                # ไม่มีทั้ง API results และไฟล์บันทึก - แสดง error และ mock thumbnails
                error_count = self.total_workers
                self.update_status(f"❌ Generation failed - {error_count}/{self.total_workers} workers failed (likely API blocked by safety filters)")
                
                # แสดง mock thumbnails เพื่อให้เห็นว่าระบบแสดงผลทำงานได้
                if self.total_workers > 1:
                    self.test_display_mock_results()
                
        except Exception as e:
            self.update_status(f"❌ Error displaying results: {str(e)}")
        
        # Cleanup batch workers
        self.batch_workers = []
        self.batch_results = []
        self.completed_workers = 0
        self.total_workers = 0
        
        self.set_buttons_enabled(True)

    def set_buttons_enabled(self, enabled: bool):
        """Enable/disable all generation buttons"""
        self.img_to_img_btn.setEnabled(enabled)
        self.txt_to_img_btn.setEnabled(enabled)
        self.imagen4_btn.setEnabled(enabled)
        
        # Show/hide progress bar
        self.progress_bar.setVisible(not enabled)
        
        if enabled:
            # Re-evaluate button states
            self.update_ui_state()
    
    def test_display_mock_results(self):
        """สำหรับทดสอบ: ใช้ error.png เป็น mock thumbnails แทนการสร้างภาพสี"""
        try:
            # ใช้ error.png ที่มีในระบบแทน
            error_png_path = Path("error.png")
            if not error_png_path.exists():
                print("[MOCK] error.png not found, skipping mock display")
                return
                
            # อ่าน error.png เป็น bytes
            with open(error_png_path, 'rb') as f:
                error_png_bytes = f.read()
            
            # สร้าง mock results ด้วย error.png จำนวน total_workers
            mock_results = [error_png_bytes] * self.total_workers
            
            # แสดงผล mock results
            if mock_results:
                self.display_results(mock_results)
                self.update_status(f"❌ API generation failed - แสดง {len(mock_results)} error thumbnails")
                
        except Exception as e:
            print(f"Error in test_display_mock_results: {str(e)}")

    def on_generation_complete(self, image_data_list: list):
        """Handle successful generation completion (both Text-to-Image and Image-to-Image)"""
        print(f"[GENERATION-COMPLETE] Called with {len(image_data_list) if image_data_list else 0} images")
        try:
            # Hide progress bar safely
            if hasattr(self, 'progress_bar'):
                self.progress_bar.setVisible(False)
            self.results = image_data_list
            
            if image_data_list:
                print(f"[GENERATION-COMPLETE] Calling display_results with {len(image_data_list)} images")
                self.display_results(image_data_list)
                
                # Auto-save for all generated images
                self.auto_save_results(image_data_list)
                location = "โฟลเดอร์ต้นฉบับ" if (self.save_on_original and hasattr(self, 'selected_image_path') and self.selected_image_path) else "โฟลเดอร์ banana"
                self.update_status(f"✅ สำเร็จ! ได้รับภาพ {len(image_data_list)} ภาพ และบันทึกอัตโนมัติใน{location}แล้ว")
                
                # [REMOVED] save_btn.setEnabled(True) - ไม่มีปุ่มแล้ว
            else:
                self.update_status("⚠️ ไม่ได้รับผลลัพธ์จาก API")
            
            self.set_buttons_enabled(True)
            
        except Exception as e:
            print(f"Error in on_generation_complete: {e}")  # Debug print
            self.on_generation_error(f"Error displaying results: {str(e)}")
    
    def on_generation_error(self, error_message: str):
        """Handle generation error (both Text-to-Image and Image-to-Image)"""
        try:
            print("[GENERATION-ERROR] Error occurred:", str(error_message)[:100])
        except:
            print("[GENERATION-ERROR] Error occurred (encoding issue)")
        
        # แสดงภาพ error แทนการแสดงผลผสม
        self.show_error_image()
        
        # ล้าง temp_result_files และ last_result_path เพื่อป้องกันการแสดงผลผิด
        if hasattr(self, 'temp_result_files'):
            self.temp_result_files.clear()
            
        if hasattr(self, 'last_result_path'):
            self.last_result_path = None
        
        # Hide progress bar safely
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setVisible(False)
        self.set_buttons_enabled(True)
        
        # แปล error เป็นภาษาคนได้
        translated_error = self.translate_error(error_message)
        
        self.update_status(f"❌ {translated_error['title']}")
        
        # แสดง error button เพื่อให้ดูรายละเอียด
        self.error_button.setText(f"{translated_error['title']} - คลิกเพื่อดูวิธีแก้ไข")
        self.error_button.setVisible(True)
        
        # Store error information
        self.last_error = error_message
        self.last_translated_error = translated_error

    def paste_from_clipboard(self):
        """Paste image from clipboard - 4-slot system compatible (Ctrl+V, Ctrl+P)"""
        try:
            # QGuiApplication already imported
            clipboard = QGuiApplication.clipboard()
            mime_data = clipboard.mimeData()
            
            if mime_data.hasImage():
                # Get image from clipboard
                pixmap = clipboard.pixmap()
                if not pixmap.isNull():
                    # Save to temporary file
                    import tempfile
                    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                    pixmap.save(temp_file.name, 'PNG')
                    
                    # 🆕 4-Slot System: Add to next available slot
                    success = self.add_image_to_next_available_slot(temp_file.name)
                    if success:
                        self.update_status("✅ วางภาพจาก Clipboard เข้า slot ถัดไป")
                    else:
                        # Fallback: Replace slot 1 if all slots full
                        self.image_paths[0] = temp_file.name
                        self.update_slot_display(0)
                        self.update_image_info()
                        self.update_status("✅ วางภาพจาก Clipboard แทนที่ slot 1 (slots เต็ม)")
                    
                    self.update_ui_state()  # Update button states
                    return
            
            if mime_data.hasUrls():
                urls = mime_data.urls()
                if urls:
                    file_path = urls[0].toLocalFile()
                    if self.is_image_file(file_path):
                        # 🆕 4-Slot System: Add to next available slot
                        success = self.add_image_to_next_available_slot(file_path)
                        if success:
                            self.update_status(f"✅ วางภาพจาก Clipboard: {Path(file_path).name} เข้า slot ถัดไป")
                        else:
                            # Fallback: Replace slot 1 if all slots full
                            self.image_paths[0] = file_path
                            self.update_slot_display(0)
                            self.update_image_info()
                            self.update_status(f"✅ วางภาพจาก Clipboard: {Path(file_path).name} แทนที่ slot 1 (slots เต็ม)")
                        
                        self.update_ui_state()  # Update button states
                        return
            
            self.update_status("⚠️ ไม่พบภาพใน Clipboard")
            
        except Exception as e:
            self.update_status(f"❌ เกิดข้อผิดพลาดในการวางภาพ: {str(e)}")
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter event for multiple images"""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            image_urls = [url for url in urls if self.is_image_file(url.toLocalFile())]
            
            if image_urls:
                count = len(image_urls)
                if count > self.max_images_limit:
                    self.update_status(f"⚠️ รองรับสูงสุด {self.max_images_limit} ภาพ (พบ {count} ภาพ)")
                else:
                    self.update_status(f"📁 ลากภาพเข้ามาที่นี่... ({count} ภาพ)")
                event.acceptProposedAction()
                return
        event.ignore()
    
    def dragLeaveEvent(self, event):
        """Handle drag leave event"""
        self.update_mode_indicator()  # Restore mode indicator
    
    def dropEvent(self, event: QDropEvent):
        """🖼️ Handle drop event for multiple images with slot-based management"""
        try:
            urls = event.mimeData().urls()
            if not urls:
                event.ignore()
                return
            
            # Filter only image files
            image_paths = []
            for url in urls:
                file_path = url.toLocalFile()
                if self.is_image_file(file_path) and self.validate_image_path(file_path):
                    image_paths.append(file_path)
                elif not self.validate_image_path(file_path):
                    print(f"[SECURITY] Dropped file rejected: {file_path}")
            
            if not image_paths:
                self.update_status("❌ ไม่พบไฟล์ภาพที่ถูกต้อง")
                event.ignore()
                return
            
            # 🎯 Slot-based Management: Add to next available slots
            added_count = 0
            skipped_files = []
            
            for image_path in image_paths:
                if self.add_image_to_next_available_slot(image_path):
                    added_count += 1
                else:
                    skipped_files.append(Path(image_path).name)
            
            # Save last directory to cache
            if image_paths:
                directory = str(Path(image_paths[0]).parent)
                self.settings.setValue("last_directory", directory)
            
            # Success/Warning messages
            if added_count == 0:
                self.update_status("⚠️ ไม่มี slot ว่าง - ลบภาพบางภาพก่อน")
            elif added_count == len(image_paths):
                if added_count == 1:
                    self.update_status(f"✅ เพิ่มภาพใน Slot: {Path(image_paths[0]).name}")
                else:
                    self.update_status(f"✅ เพิ่ม {added_count} ภาพใน Slots สำเร็จ")
            else:
                self.update_status(f"⚠️ เพิ่มได้ {added_count}/{len(image_paths)} ภาพ - Slots เต็ม")
            
            event.acceptProposedAction()
            return
            
        except Exception as e:
            self.update_status(f"❌ เกิดข้อผิดพลาดในการลากไฟล์: {str(e)}")
        
        event.ignore()
    
    def is_image_file(self, file_path: str) -> bool:
        """ตรวจสอบว่าไฟล์เป็นภาพหรือไม่"""
        if not file_path:
            return False
        
        image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp'}
        return Path(file_path).suffix.lower() in image_extensions
    
    def validate_image_path(self, image_path: str) -> bool:
        """ตรวจสอบความปลอดภัยของ path"""
        try:
            # ตรวจสอบ input พื้นฐาน
            if not image_path or not isinstance(image_path, str):
                return False
            
            # แปลงเป็น absolute path และตรวจสอบ
            path = Path(image_path).resolve()
            
            # ตรวจสอบว่าไฟล์มีอยู่จริง
            if not path.exists():
                return False
            
            # ตรวจสอบว่าเป็นไฟล์ (ไม่ใช่ directory)
            if not path.is_file():
                return False
            
            # ตรวจสอบ extension
            if not self.is_image_file(str(path)):
                return False
            
            # ตรวจสอบว่าไม่มี path traversal patterns ใน original path
            original_path = str(image_path)
            dangerous_patterns = ['../', '..\\', '~/', '$HOME', '%USERPROFILE%']
            for pattern in dangerous_patterns:
                if pattern in original_path:
                    print(f"[SECURITY] Blocked dangerous path pattern: {pattern}")
                    return False
            
            # ตรวจสอบขนาดไฟล์ (max 100MB)
            if path.stat().st_size > 100 * 1024 * 1024:
                print(f"[SECURITY] File too large: {path.stat().st_size} bytes")
                return False
            
            return True
            
        except Exception as e:
            print(f"[SECURITY] Path validation failed: {e}")
            return False
    
    @contextmanager
    def _managed_image(self, image_source):
        """Context manager for safe PIL Image handling"""
        image = None
        byte_io = None
        try:
            if isinstance(image_source, bytes):
                # From bytes data
                byte_io = BytesIO(image_source)
                image = Image.open(byte_io)
            elif isinstance(image_source, str):
                # From file path
                image = Image.open(image_source)
            else:
                raise ValueError("Invalid image source type")
            
            # Add to active images list
            self._active_images.append(image)
            yield image
            
        finally:
            # Cleanup
            if image:
                try:
                    image.close()
                except:
                    pass
            if byte_io:
                try:
                    byte_io.close()
                except:
                    pass
            
            # Remove from active images
            if image in self._active_images:
                self._active_images.remove(image)
                
            # Cleanup old images if cache is too large
            self._cleanup_image_cache()
    
    def _cleanup_image_cache(self):
        """Cleanup old cached images"""
        while len(self._active_images) > self._max_cache_size:
            try:
                old_image = self._active_images.pop(0)
                if hasattr(old_image, 'close'):
                    old_image.close()
            except Exception as e:
                print(f"[DEBUG] Error cleaning up image: {e}")
    
    
    def add_resize_handle(self):
        """เพิ่ม resize grip ที่มุมล่างขวา"""
        self.resize_handle = QLabel()
        self.resize_handle.setFixedSize(15, 15)  # ลดลง 50% จาก 30x30
        
        # Load resize.png icon
        resize_path = Path("resize.png")
        if resize_path.exists():
            pixmap = QPixmap(str(resize_path))
            if not pixmap.isNull():
                # Scale to fit handle size (50% smaller)
                scaled_pixmap = pixmap.scaled(12, 12, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.resize_handle.setPixmap(scaled_pixmap)
            else:
                # Fallback if image fails to load
                self.resize_handle.setText("◢")
        else:
            # Create resize.png if it doesn't exist
            self.create_resize_icon()
            # Load the created icon
            pixmap = QPixmap(str(resize_path))
            scaled_pixmap = pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.resize_handle.setPixmap(scaled_pixmap)
        
        self.resize_handle.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QLabel:hover {
                background: rgba(187, 187, 187, 0.2);
                border-radius: 3px;
            }
        """)
        
        self.resize_handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Position resize handle at bottom-right corner (adjusted for new size)
        self.resize_handle.setParent(self)
        self.resize_handle.move(self.width() - 16, self.height() - 16)
        self.resize_handle.raise_()  # Bring to front
        self.resize_handle.show()
        
        # Ensure it stays on top
        self.resize_handle.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
    
    def create_resize_icon(self):
        """สร้างไอคอน resize.png"""
        # QColor, QPolygon, QPoint already imported
        
        # Create 32x32 pixmap with transparent background
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Set color for resize grip
        painter.setPen(QColor(180, 180, 180))
        painter.setBrush(QColor(140, 140, 140))
        
        # Draw resize grip triangles (bottom-right corner style)
        # Create multiple small triangles to form resize grip pattern
        triangles = [
            # Triangle 1 (bottom-right)
            QPolygon([QPoint(24, 32), QPoint(32, 32), QPoint(32, 24)]),
            # Triangle 2 (middle)
            QPolygon([QPoint(16, 32), QPoint(24, 32), QPoint(24, 24)]),
            QPolygon([QPoint(20, 28), QPoint(28, 28), QPoint(28, 20)]),
            # Triangle 3 (smaller)
            QPolygon([QPoint(12, 32), QPoint(20, 32), QPoint(20, 24)]),
            QPolygon([QPoint(16, 28), QPoint(24, 28), QPoint(24, 20)]),
            QPolygon([QPoint(20, 24), QPoint(28, 24), QPoint(28, 16)])
        ]
        
        for triangle in triangles:
            painter.drawPolygon(triangle)
        
        painter.end()
        
        # Save as resize.png
        pixmap.save("resize.png", "PNG")
        print("Created resize.png icon")
    
    def setup_error_translator(self):
        """ตั้งค่าระบบแปลและจับคู่ error messages"""
        self.error_patterns = {
            # API Authentication Errors
            "PERMISSION_DENIED": {
                "title": "🔐 ปัญหาการยืนยันตัวตน",
                "description": "API Key ไม่ถูกต้องหรือไม่มีสิทธิ์เข้าถึง",
                "solutions": [
                    "ตรวจสอบ API Key ใน .env file หรือ environment variables",
                    "ลอง refresh API Key ใหม่จาก Google AI Studio",
                    "ตรวจสอบว่า API Key มีสิทธิ์เข้าถึง Gemini API"
                ]
            },
            
            # Rate Limiting Errors  
            "RESOURCE_EXHAUSTED": {
                "title": "⏱️ เกินขีดจำกัดการใช้งาน",
                "description": "เรียกใช้ API บ่อยเกินไป (เกิน 2,000 ครั้งต่อนาที)",
                "solutions": [
                    "รอสักครู่แล้วลองใหม่",
                    "ลดความถี่ในการสร้างภาพ",
                    "ใช้คิวสำหรับจัดการคำขอ"
                ]
            },
            
            # Content Policy Errors
            "INVALID_ARGUMENT": {
                "title": "⚠️ ปัญหาเนื้อหาหรือคำขอ",
                "description": "คำขอไม่ถูกต้องหรือเนื้อหาถูกบล็อกโดยนีตภาพ",
                "solutions": [
                    "ปรับเปลี่ยนคำสั่ง (prompt) ให้เหมาะสม",
                    "หลีกเลี่ยงเนื้อหาที่ไม่เหมาะสม",
                    "ตรวจสอบรูปแบบคำขอให้ถูกต้อง"
                ]
            },
            
            # Server Errors
            "INTERNAL": {
                "title": "🔧 ปัญหาเซิร์ฟเวอร์ Google",
                "description": "เกิดข้อผิดพลาดภายในเซิร์ฟเวอร์ของ Google",
                "solutions": [
                    "รอสักครู่แล้วลองใหม่",
                    "ตรวจสอบสถานะบริการ Google Cloud",
                    "ลองใช้โมเดลอื่นชั่วคราว"
                ]
            },
            
            "UNAVAILABLE": {
                "title": "🔧 บริการไม่พร้อมใช้งาน",
                "description": "เซิร์ฟเวอร์มีภาระงานมากหรือปิดปรับปรุง",
                "solutions": [
                    "รอสักครู่แล้วลองใหม่",
                    "ตรวจสอบประกาศจาก Google",
                    "ลองเปลี่ยนเวลาในการใช้งาน"
                ]
            },
            
            # Common SDK Errors
            "ไม่พบข้อมูลภาพในการตอบกลับจาก API": {
                "title": "🖼️ ไม่ได้รับภาพจาก API",
                "description": "API ตอบกลับแต่ไม่มีข้อมูลภาพ อาจเกิดจาก safety filter หรือปัญหา parsing",
                "solutions": [
                    "ปรับคำสั่ง (prompt) ให้ชัดเจนขึ้น",
                    "ระบุให้ชัดเจนว่าต้องการสร้างภาพ",
                    "หลีกเลี่ยงคำที่อาจถูกบล็อก",
                    "ลองเปลี่ยนไปใช้ Legacy SDK"
                ]
            },
            
            "ไม่พบ candidates ในการตอบกลับจาก API": {
                "title": "📭 การตอบกลับไม่สมบูรณ์",
                "description": "โครงสร้างการตอบกลับจาก API ไม่ถูกต้อง",
                "solutions": [
                    "ตรวจสอบการเชื่อมต่อเครือข่าย",
                    "ลองส่งคำขออีกครั้ง",
                    "ตรวจสอบ API key และ quota"
                ]
            },
            
            "ไม่พบ content ในการตอบกลับจาก API": {
                "title": "📝 เนื้อหาว่างเปล่า",
                "description": "API ตอบกลับแต่ไม่มีเนื้อหา",
                "solutions": [
                    "ลองส่งคำขออีกครั้ง",
                    "ตรวจสอบว่าคำสั่งไม่ถูกบล็อก",
                    "ปรับ safety settings"
                ]
            },
            
            "ไม่พบ parts ในการตอบกลับจาก API": {
                "title": "🧩 ข้อมูลไม่สมบูรณ์",
                "description": "API ตอบกลับแต่ข้อมูลภายในไม่ครบถ้วน",
                "solutions": [
                    "ลองส่งคำขออีกครั้ง",
                    "ตรวจสอบขนาดคำสั่งไม่เกินขีดจำกัด",
                    "เปลี่ยนเป็น Legacy SDK"
                ]
            },
            
            # Network and Connection Errors
            "Connection": {
                "title": "🌐 ปัญหาการเชื่อมต่อ",
                "description": "ไม่สามารถเชื่อมต่อกับเซิร์ฟเวอร์ได้",
                "solutions": [
                    "ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต",
                    "ลองใหม่ในอีกสักครู่",
                    "ตรวจสอบ firewall หรือ proxy"
                ]
            },
            
            # Import and Installation Errors
            "ImportError": {
                "title": "📦 ปัญหาการติดตั้ง SDK",
                "description": "ไม่สามารถโหลด SDK ได้",
                "solutions": [
                    "ติดตั้ง SDK: pip install google-genai",
                    "ตรวจสอบ Python version (ต้อง 3.9+)",
                    "ลองติดตั้งใหม่: pip install --upgrade google-genai"
                ]
            }
        }
    
    def translate_error(self, error_message: str) -> dict:
        """แปล error message เป็นภาษาคนได้"""
        error_text = str(error_message).lower()
        
        # ค้นหา pattern ที่ตรงกัน
        for pattern, info in self.error_patterns.items():
            if pattern.lower() in error_text:
                return {
                    "title": info["title"],
                    "description": info["description"],
                    "solutions": info["solutions"],
                    "original": error_message
                }
        
        # Default error สำหรับ error ที่ไม่รู้จัก
        return {
            "title": "❓ ข้อผิดพลาดที่ไม่ทราบสาเหตุ",
            "description": "เกิดข้อผิดพลาดที่ไม่สามารถระบุสาเหตุได้",
            "solutions": [
                "ลองส่งคำขออีกครั้ง",
                "ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต", 
                "ตรวจสอบ API Key",
                "ลองเปลี่ยนไปใช้ Legacy SDK"
            ],
            "original": error_message
        }
    
    def resizeEvent(self, event):
        """Handle window resize to reposition resize handle"""
        super().resizeEvent(event)
        if hasattr(self, 'resize_handle'):
            self.resize_handle.move(self.width() - 16, self.height() - 16)
            self.resize_handle.raise_()
            self.resize_handle.show()
    
    
    def wheelEvent(self, event):
        """Handle mouse wheel event for font size adjustment"""
        # QWheelEvent, Qt already imported
        
        # Check if Ctrl is pressed
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Get the delta (positive = up, negative = down)
            delta = event.angleDelta().y()
            
            if delta > 0:
                # Scroll up = increase font size
                self.current_font_size = min(self.current_font_size + 1, self.max_font_size)
            elif delta < 0:
                # Scroll down = decrease font size
                self.current_font_size = max(self.current_font_size - 1, self.min_font_size)
            
            # Apply new font size to prompt input
            self.apply_font_size()
            
            # Save font size to settings
            self.settings.setValue("font_size", self.current_font_size)
            
            # Update status
            self.update_status(f"Font size: {self.current_font_size}pt")
            
            # Accept the event to prevent default scrolling
            event.accept()
        else:
            # Pass event to parent if Ctrl is not pressed
            super().wheelEvent(event)
    
    def apply_font_size(self):
        """Apply the current font size to the prompt input"""
        if hasattr(self, 'prompt_input'):
            font = self.prompt_input.font()
            font.setPointSize(self.current_font_size)
            self.prompt_input.setFont(font)
    
    def prompt_container_resize_event(self, event):
        """Handle prompt container resize to reposition handle"""
        if hasattr(self, 'prompt_resize_handle'):
            # Position at bottom-right corner (very close to edge)
            self.prompt_resize_handle.move(
                self.prompt_container.width() - self.prompt_resize_handle.width() - 1,
                self.prompt_container.height() - self.prompt_resize_handle.height() - 1
            )
            self.prompt_resize_handle.raise_()
    
    def eventFilter(self, obj, event):
        """Event filter for prompt resize handle"""
        if obj == self.prompt_resize_handle:
            if event.type() == event.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.prompt_resizing = True
                    self.prompt_resize_start_pos = event.globalPosition().toPoint()
                    self.prompt_resize_start_height = self.prompt_container.height()
                    return True
            elif event.type() == event.Type.MouseMove:
                if self.prompt_resizing:
                    delta_y = event.globalPosition().toPoint().y() - self.prompt_resize_start_pos.y()
                    new_height = self.prompt_resize_start_height + delta_y
                    
                    # Limit height between min and max
                    new_height = max(100, min(500, new_height))
                    
                    # Update container heights
                    self.prompt_container.setFixedHeight(new_height)
                    self.prompt_container.setMaximumHeight(new_height)
                    
                    # Update status
                    self.update_status(f"Prompt box height: {new_height}px")
                    
                    return True
            elif event.type() == event.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.prompt_resizing = False
                    return True
        
        return super().eventFilter(obj, event)
    
    def is_in_resize_area(self, pos):
        """Check if mouse position is in resize area"""
        margin = 20  # ลดลง 50% จาก 35 ตาม handle ขนาดใหม่
        return (pos.x() >= self.width() - margin and pos.y() >= self.height() - margin)
    
    
    def select_image(self):
        """🖼️ เลือกไฟล์ภาพ (รองรับ multiple selection สำหรับ slot-based management)"""
        # Get last directory from cache
        last_dir = self.settings.value("last_directory", "")
        
        # Use QFileDialog.getOpenFileNames for multiple selection
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "เลือกภาพสำหรับ Edit (สูงสุด 4 ภาพ)",
            last_dir,
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp)"
        )
        
        if not file_paths:
            return
        
        # 🎯 Slot-based Management: Add to next available slots
        added_count = 0
        skipped_files = []
        
        for file_path in file_paths:
            if self.validate_image_path(file_path):
                if self.add_image_to_next_available_slot(file_path):
                    added_count += 1
                else:
                    skipped_files.append(Path(file_path).name)
            else:
                print(f"[SECURITY] Selected file rejected: {file_path}")
                skipped_files.append(Path(file_path).name)
        
        if added_count == 0:
            if skipped_files:
                self.update_status("❌ ไฟล์ไม่ปลอดภัยหรือไม่มี slot ว่าง")
            return
        
        # Save directory to cache
        directory = str(Path(file_paths[0]).parent)
        self.settings.setValue("last_directory", directory)
        
        # Success/Warning messages
        if added_count == len(file_paths):
            if added_count == 1:
                self.update_status(f"✅ เลือกภาพใน Slot: {Path(file_paths[0]).name}")
            else:
                self.update_status(f"✅ เลือก {added_count} ภาพใน Slots สำเร็จ")
        else:
            self.update_status(f"⚠️ เลือกได้ {added_count}/{len(file_paths)} ภาพ - Slots เต็มหรือไฟล์ไม่ปลอดภัย")
    
    def preload_image(self, image_path: str, clear_existing: bool = False):
        """🖼️ Preload single image from Promptist - smart slot management
        
        Args:
            image_path: Path to image file
            clear_existing: If True, clear all slots first (default: False)
        """
        try:
            # ตรวจสอบความปลอดภัยก่อน
            if not self.validate_image_path(image_path):
                print(f"[SECURITY] Preload blocked - unsafe path: {image_path}")
                self.update_status("❌ ไม่สามารถโหลดภาพได้ - ไฟล์ไม่ปลอดภัย")
                return
                
            if image_path and Path(image_path).exists() and self.is_image_file(image_path):
                # 🎯 Clear existing slots if requested (for first-time usage)
                if clear_existing:
                    for i in range(4):
                        self.image_paths[i] = None
                        self.clear_slot_display(i)
                    print(f"[DEBUG] Cleared all existing slots")
                
                # ตรวจสอบว่ามีภาพนี้อยู่แล้วหรือไม่
                if image_path in self.image_paths:
                    self.update_status(f"⚠️ ภาพนี้มีใน slots อยู่แล้ว: {Path(image_path).name}")
                    return
                
                # เพิ่มใน slot ว่างถัดไป
                if self.add_image_to_next_available_slot(image_path):
                    action_word = "โหลด" if clear_existing else "เพิ่ม"
                    self.update_status(f"🚀 {action_word}ภาพ: {Path(image_path).name}")
                    print(f"[DEBUG] Successfully added image to next available slot: {Path(image_path).name}")
                else:
                    self.update_status(f"⚠️ Slots เต็มแล้ว - ไม่สามารถเพิ่มภาพได้: {Path(image_path).name}")
                    print(f"[WARNING] All slots full, cannot add image: {Path(image_path).name}")
                    return
                
                # Save directory to cache
                directory = str(Path(image_path).parent)
                self.settings.setValue("last_directory", directory)
                
                self.update_status(f"🚀 โหลดภาพ: {Path(image_path).name}")
                print(f"[DEBUG] Successfully preloaded image: {Path(image_path).name}")
            else:
                print(f"[WARNING] Invalid image path: {image_path}")
                self.update_status("⚠️ ภาพที่โหลดไม่ถูกต้อง")
        except Exception as e:
            print(f"[ERROR] Failed to preload image: {e}")
            self.update_status(f"❌ เกิดข้อผิดพลาด: {str(e)}")
    
    def create_aspect_ratio_preserved_pixmap(self, image_path: str, max_width: int, max_height: int) -> QPixmap:
        """สร้าง QPixmap ที่รักษา aspect ratio อย่างสมบูรณ์แบบ"""
        try:
            # Load image using managed context to prevent memory leaks
            with self._managed_image(image_path) as img:
                # Convert to Qt format
                if img.mode == 'RGBA':
                    img = img.convert('RGB')
                
                # Convert to bytes using managed BytesIO
                with BytesIO() as byte_array:
                    img.save(byte_array, format='PNG')
                    byte_data = byte_array.getvalue()
                    
                    # Create QPixmap
                    pixmap = QPixmap()
                    pixmap.loadFromData(byte_data)
                    
                    # Scale with aspect ratio preservation
                    if not pixmap.isNull():
                        scaled_pixmap = pixmap.scaled(
                            max_width, max_height,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation
                        )
                        return scaled_pixmap
                    else:
                        # Return empty pixmap if failed to load
                        return QPixmap()
                    
        except Exception as e:
            print(f"[ERROR] Failed to create pixmap: {e}")
            return QPixmap()
    
    def display_thumbnail(self, image_path: str):
        """แสดง thumbnail ของภาพที่เลือก - รักษา aspect ratio อย่างสมบูรณ์แบบ"""
        try:
            # ตรวจสอบความปลอดภัยก่อน
            if not self.validate_image_path(image_path):
                self.thumbnail_label.setText("❌ ไฟล์ไม่ปลอดภัย")
                print(f"[SECURITY] Display blocked - unsafe path: {image_path}")
                return
                
            # Store the path
            self.selected_image_path = image_path
            
            # ใช้ helper function สำหรับสร้าง pixmap ที่รักษา aspect ratio
            scaled_pixmap = self.create_aspect_ratio_preserved_pixmap(image_path, 400, 300)
            
            if not scaled_pixmap.isNull():
                # ตั้งค่า Label ให้แสดงภาพตรงกลางและไม่ขยาย
                self.thumbnail_label.setScaledContents(False)
                self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.thumbnail_label.setPixmap(scaled_pixmap)
            else:
                self.thumbnail_label.setText("❌ ไม่สามารถโหลดภาพได้")
            
            # Show image info using managed context
            file_info = Path(image_path)
            with self._managed_image(image_path) as original_image:
                info_text = (
                    f"📁 {file_info.name}\n"
                    f"📐 {original_image.size[0]} × {original_image.size[1]}\n"
                    f"💾 {file_info.stat().st_size / 1024:.1f} KB"
                )
                self.image_info_label.setText(info_text)
            
            # เพิ่ม click handler สำหรับ thumbnail image
            self.make_image_clickable(self.thumbnail_label, image_path)
            
        except Exception as e:
            QMessageBox.warning(self, "เกิดข้อผิดพลาด", f"ไม่สามารถโหลดภาพได้:\n{str(e)}")
    
    def start_editing(self, use_new_sdk: bool = True):
        """เริ่มต้นการ edit ภาพ (รองรับ multiple images)"""
        # Check if we have images in session
        if self.get_image_count() == 0:
            QMessageBox.warning(self, "ไม่ได้เลือกภาพ", "กรุณาเลือกภาพก่อนการ edit (รองรับ 1-3 ภาพ)")
            return
        
        prompt = self.prompt_input.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "ไม่ได้ใส่ prompt", "กรุณาใส่คำสั่งสำหรับการ edit ภาพ")
            return
        
        # Disable buttons during processing
        self.img_to_img_btn.setEnabled(False)
        if hasattr(self, 'txt_to_img_btn'):
            self.txt_to_img_btn.setEnabled(False)
        if hasattr(self, 'imagen4_btn'):
            self.imagen4_btn.setEnabled(False)
        # [REMOVED] save_btn.setEnabled(False) - ไม่มีปุ่มแล้ว
        
        # Hide error button and show progress safely
        if hasattr(self, 'error_button'):
            self.error_button.setVisible(False)
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate progress
            self.progress_bar.setValue(0)  # Reset value
        
        # Show status based on session mode
        mode_text = {
            'single': "🍌 กำลังแก้ไขภาพเดียว...",
            'dual': "🍌 กำลังผสมผสาน 2 ภาพ...", 
            'triple': "🍌 กำลังสร้างผลงานจาก 3 ภาพ..."
        }
        sdk_name = "New SDK (google-genai)" if use_new_sdk else "Legacy SDK (google-generativeai)"
        self.update_status(f"🍌 กำลังประมวลผล... ด้วย {sdk_name}")
        
        # Clear previous results
        self.clear_results()
        
        # Start session-based generation
        self.start_session_generation(use_new_sdk)
    
    def clear_results(self):
        """เคลียร์ผลลัพธ์เก่า - รูปแบบใหม่"""
        # ล้าง result panel กลับไปสู่สถานะเริ่มต้น
        self.result_image_label.clear()
        self.result_image_label.setText("ยังไม่มีผลลัพธ์")
        self.result_info_label.setText("")
        self.current_results = []
    
    # [FLOATING VIEWER METHODS]
    def open_floating_viewer(self, image_path: str, thumbnail_index: int = None):
        """เปิด Floating Image Viewer สำหรับภาพที่กำหนด พร้อมนำทางในชุดปัจจุบัน"""
        try:
            if not image_path or not os.path.exists(image_path):
                print(f"[FloatingViewer] Image path not found: {image_path}")
                return
                
            # ปิด viewer เดิมถ้ามี
            if self.floating_viewer:
                self.floating_viewer.close()
                self.floating_viewer = None
            
            # หาภาพทั้งหมดในชุดปัจจุบันจาก temp result files
            current_session_images = []
            clicked_index = 0
            
            # ใช้ temp_result_files ถ้ามีและมีไฟล์ที่มีอยู่จริง
            if hasattr(self, 'temp_result_files') and self.temp_result_files:
                valid_temp_files = [path for path in self.temp_result_files if os.path.exists(path)]
                
                # ตรวจสอบว่าไม่อยู่ในสถานะ error (ไม่มี last_result_path หรือเป็น None)
                is_error_state = (hasattr(self, 'last_result_path') and self.last_result_path is None)
                
                if valid_temp_files and not is_error_state:
                    current_session_images = valid_temp_files
                    print(f"[FloatingViewer] Found {len(current_session_images)} valid session images")
                    
                    # 🔧 Fix: Use thumbnail index directly if provided, otherwise fall back to path search
                    if thumbnail_index is not None and 0 <= thumbnail_index < len(current_session_images):
                        clicked_index = thumbnail_index
                        print(f"[FloatingViewer] Using thumbnail index: {clicked_index}")
                    else:
                        # หา index ของภาพที่คลิก (fallback method)
                        try:
                            clicked_index = current_session_images.index(image_path)
                            print(f"[FloatingViewer] Clicked image found at index {clicked_index}")
                        except ValueError:
                            clicked_index = 0
                            print(f"[FloatingViewer] Clicked image not in session, using index 0")
                else:
                    print(f"[FloatingViewer] Error state detected or no valid files. Error state: {is_error_state}, Valid files: {len(valid_temp_files) if valid_temp_files else 0}")
            else:
                print("[FloatingViewer] No temp_result_files available")
                    
            # ถ้าไม่มี session images หรือภาพที่คลิกไม่อยู่ในชุด ให้ใช้ภาพเดียว
            if not current_session_images or image_path not in current_session_images:
                current_session_images = [image_path]
                clicked_index = 0
                print(f"[FloatingViewer] Using single image mode for: {os.path.basename(image_path)}")
            
            # สร้าง floating viewer ใหม่
            self.floating_viewer = FloatingImageViewer(current_session_images, self)
            
            # Set starting index to clicked image
            if clicked_index < len(current_session_images):
                self.floating_viewer.current_index = clicked_index
                self.floating_viewer.image_path = current_session_images[clicked_index]
                if hasattr(self.floating_viewer, 'update_nav_button_states'):
                    self.floating_viewer.update_nav_button_states()
            
            self.floating_viewer.show()
            
            if len(current_session_images) > 1:
                print(f"[FloatingViewer] Opened batch viewer: {clicked_index + 1}/{len(current_session_images)} images")
            else:
                print(f"[FloatingViewer] Opened: {os.path.basename(image_path)}")
            
        except Exception as e:
            print(f"[FloatingViewer] Error opening viewer: {e}")
            QMessageBox.warning(self, "Error", f"ไม่สามารถแสดงภาพได้: {str(e)}")
    
    def make_image_clickable(self, label: QLabel, image_path: str):
        """ทำให้ภาพคลิกได้เพื่อเปิด floating viewer"""
        if not label or not image_path:
            return
            
        # เก็บ reference ของ path
        label.image_path = image_path
        
        # Override mouse events
        def on_mouse_press(event):
            if hasattr(label, 'image_path') and label.image_path:
                # 🔧 Fix: Pass thumbnail index if available for correct navigation
                thumbnail_index = getattr(label, 'thumbnail_index', None)
                self.open_floating_viewer(label.image_path, thumbnail_index)
        
        def on_enter_event(event):
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            
        def on_leave_event(event):
            label.setCursor(Qt.CursorShape.ArrowCursor)
        
        # Enable mouse tracking and events
        label.setMouseTracking(True)
        label.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        
        # Set event handlers
        label.mousePressEvent = on_mouse_press
        label.enterEvent = on_enter_event
        label.leaveEvent = on_leave_event
        
        # Set initial cursor
        label.setCursor(Qt.CursorShape.ArrowCursor)
    
    def save_temp_result_image(self, image_data: bytes) -> Optional[str]:
        """บันทึกภาพผลลัพธ์เป็น temporary file สำหรับ floating viewer"""
        try:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                with Image.open(BytesIO(image_data)) as image:
                    if image.mode == 'RGBA':
                        image = image.convert('RGB')
                    image.save(temp_file.name, format='PNG')
                    
                # Track temporary file for cleanup
                self.temp_result_files.append(temp_file.name)
                    
                print(f"[FloatingViewer] Created temp result file: {temp_file.name}")
                return temp_file.name
                
        except Exception as e:
            print(f"[FloatingViewer] Error creating temp result file: {e}")
            return None
    
    # [REMOVED] on_editing_finished() - Merged into on_generation_complete()
    
    def get_next_file_number(self, save_dir: Path, date_str: str) -> int:
        """หาหมายเลขไฟล์ต่อไปในโฟลเดอร์สำหรับวันนี้"""
        try:
            # หา pattern: banana_1sep_*.png
            pattern = f"banana_{date_str}_*.png"
            existing_files = list(save_dir.glob(pattern))
            
            if not existing_files:
                return 1  # เริ่มจาก 001
            
            # Extract numbers from existing files
            numbers = []
            for file in existing_files:
                try:
                    # Extract number from banana_1sep_XXX.png
                    name_parts = file.stem.split('_')
                    if len(name_parts) >= 3:
                        number = int(name_parts[2])
                        numbers.append(number)
                except (ValueError, IndexError):
                    continue
            
            # Return next available number
            return max(numbers) + 1 if numbers else 1
            
        except Exception as e:
            print(f"Error getting next file number: {e}")
            return 1

    def _check_saved_files(self) -> List[str]:
        """🔍 ตรวจสอบไฟล์ที่บันทึกจริงๆ ในโฟลเดอร์ (สำหรับ mixed results)"""
        try:
            # สร้าง date string แบบใหม่: 1sep, 2sep, etc.
            now = datetime.now()
            date_str = f"{now.day}{now.strftime('%b').lower()}"
            
            # กำหนดโฟลเดอร์ตรวจสอบตาม toggle setting
            if self.save_on_original and self.selected_image_path:
                check_dir = Path(self.selected_image_path).parent
            else:
                check_dir = Path("banana")
            
            if not check_dir.exists():
                return []
            
            # ค้นหาไฟล์ที่มี pattern banana_<date>_<number>.png
            pattern = f"banana_{date_str}_*.png"
            saved_files = list(check_dir.glob(pattern))
            
            # เรียงตามเวลาสร้างไฟล์ (ล่าสุดก่อน) และคืนค่า path string
            saved_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            # เอาเฉพาะไฟล์ที่สร้างใน 5 นาทีล่าสุด (กรณีรันหลายครั้ง)
            current_time = time.time()
            recent_files = []
            for file_path in saved_files[:self.total_workers]:  # เอาตามจำนวน workers
                if current_time - file_path.stat().st_mtime < 300:  # 5 minutes
                    recent_files.append(str(file_path))
            
            return recent_files
            
        except Exception as e:
            print(f"Error checking saved files: {e}")
            return []

    def _display_saved_files_as_results(self, file_paths: List[str]):
        """📸 แสดงไฟล์ที่บันทึกแล้วเป็น results (สำหรับ mixed results)"""
        try:
            # อ่านไฟล์เป็น bytes และส่งไปแสดงผล
            results_bytes = []
            for file_path in file_paths:
                with open(file_path, 'rb') as f:
                    image_data = f.read()
                    results_bytes.append(image_data)
            
            if results_bytes:
                # ใช้ฟังก์ชัน display_results เดิม
                self.display_results(results_bytes)
                # เก็บ current results สำหรับการ click-to-zoom
                self.current_results = results_bytes
            
        except Exception as e:
            print(f"Error displaying saved files: {e}")
            # หากแสดงไฟล์บันทึกไม่ได้ ใช้ mock thumbnails แทน
            self.test_display_mock_results()

    def auto_save_results(self, results: List[bytes]):
        """บันทึกผลลัพธ์อัตโนมัติตาม toggle setting"""
        try:
            print(f"[AUTO-SAVE] Called with {len(results) if results else 0} results")
            # 🛡️ ป้องกันการบันทึกไฟล์เปล่า หรือ invalid results
            if not results:
                print("[AUTO-SAVE] No results to save - skipping auto-save")
                return
                
            # ตรวจสอบว่ามี valid image data
            valid_results = []
            for i, image_data in enumerate(results):
                if image_data and len(image_data) > 100:  # ต้องมีขนาดมากกว่า 100 bytes
                    valid_results.append(image_data)
                else:
                    print(f"[AUTO-SAVE] Skipping invalid image data at index {i}")
                    
            if not valid_results:
                print("[AUTO-SAVE] No valid image data found - skipping auto-save")
                return
                
            # สร้าง date string แบบใหม่: 1sep, 2sep, etc.
            now = datetime.now()
            date_str = f"{now.day}{now.strftime('%b').lower()}"  # 1sep, 2oct, etc.
            saved_files = []
            
            # กำหนดโฟลเดอร์บันทึกตาม toggle setting
            print(f"[AUTO-SAVE] save_on_original={getattr(self, 'save_on_original', 'NOT_SET')}")
            print(f"[AUTO-SAVE] selected_image_path={getattr(self, 'selected_image_path', 'NOT_SET')}")
            
            if self.save_on_original and self.selected_image_path:
                # บันทึกในโฟลเดอร์เดียวกับภาพต้นฉบับ
                save_dir = Path(self.selected_image_path).parent
                location_text = "โฟลเดอร์ต้นฉบับ"
                print(f"[AUTO-SAVE] Saving to original folder: {save_dir}")
            else:
                # บันทึกในโฟลเดอร์ banana (default)
                save_dir = Path("banana")
                save_dir.mkdir(exist_ok=True)
                location_text = "โฟลเดอร์ banana"
                print(f"[AUTO-SAVE] Saving to banana folder: {save_dir}")
                print(f"[AUTO-SAVE] Directory exists: {save_dir.exists()}")
            
            # หาหมายเลขเริ่มต้นสำหรับวันนี้
            start_number = self.get_next_file_number(save_dir, date_str)
            
            for i, image_data in enumerate(valid_results):
                # Convert to PIL Image using managed context
                with self._managed_image(image_data) as image:
                    # Generate filename: banana_1sep_001.png
                    filename = f"banana_{date_str}_{start_number + i:03d}.png"
                    filepath = save_dir / filename
                    
                    # ตรวจสอบอีกครั้งว่าไฟล์ไม่ซ้ำ (safety check)
                    counter = 0
                    original_filepath = filepath
                    while filepath.exists() and counter < 1000:
                        counter += 1
                        filename = f"banana_{date_str}_{start_number + i + counter:03d}.png"
                        filepath = save_dir / filename
                    
                    # Save image
                    image.save(str(filepath), 'PNG')
                    saved_files.append(str(filepath))
            
            self.update_status(f"💾 บันทึกอัตโนมัติ {len(saved_files)} ไฟล์ใน{location_text}")
            print(f"[AUTO-SAVE] Saved files: {[Path(f).name for f in saved_files]}")
            
            # Auto-refresh notifications removed for standalone version
            
        except Exception as e:
            self.update_status(f"⚠️ ไม่สามารถบันทึกอัตโนมัติได้: {str(e)}")
    
    # [REMOVED] on_editing_error() - Merged into on_generation_error()
    
    # notify_promptist_generation_complete removed for standalone version
    
    # ===== MULTIPLE START IMAGES MANAGEMENT =====
    
    def remove_image_from_slot(self, slot_index: int):
        """ลบภาพออกจาก slot ที่กำหนด (0-based index)"""
        if 0 <= slot_index < 4:
            self.image_paths[slot_index] = None
            self.update_slot_display(slot_index)
            self.update_image_info()
    
    def add_image_to_next_available_slot(self, image_path: str) -> bool:
        """เพิ่มภาพใน slot ที่ว่างถัดไป"""
        for i in range(4):
            if self.image_paths[i] is None:
                self.image_paths[i] = image_path
                self.update_slot_display(i)
                self.update_image_info()
                return True
        return False  # ไม่มี slot ว่าง
    
    def update_slot_display(self, slot_index: int):
        """อัปเดตการแสดงผลของ slot ที่กำหนด"""
        if not (0 <= slot_index < 4) or slot_index >= len(self.image_slots):
            return
        
        slot_widget = self.image_slots[slot_index]
        image_label = slot_widget.findChild(QLabel)
        
        if not image_label:
            return
        
        image_path = self.image_paths[slot_index]
        
        if image_path and os.path.exists(image_path):
            # แสดงภาพ
            try:
                with Image.open(image_path) as img:
                    # Resize เป็น thumbnail
                    img.thumbnail((120, 120), Image.Resampling.LANCZOS)
                    
                    # Convert เป็น QPixmap
                    img_bytes = BytesIO()
                    img.save(img_bytes, format='PNG')
                    img_bytes.seek(0)
                    
                    qimg = QPixmap()
                    qimg.loadFromData(img_bytes.getvalue())
                    
                    image_label.setPixmap(qimg)
                    image_label.setText("")  # ลบ text
                    
                    # แสดง delete button
                    if hasattr(image_label, 'delete_button'):
                        image_label.delete_button.setVisible(True)
                        # Update button position - use fixed position
                        image_label.delete_button.move(95, 5)  # Fixed position for 120px slot
                        image_label.delete_button.raise_()  # Bring to front
                    
                    # ทำให้ clickable
                    self.make_image_clickable(image_label, image_path)
            
            except Exception as e:
                print(f"Error loading image for slot {slot_index}: {e}")
                self.clear_slot_display(slot_index)
        else:
            # Clear slot
            self.clear_slot_display(slot_index)
    
    def clear_slot_display(self, slot_index: int):
        """ล้างการแสดงผลของ slot ที่กำหนด"""
        if not (0 <= slot_index < 4) or slot_index >= len(self.image_slots):
            return
        
        slot_widget = self.image_slots[slot_index]
        image_label = slot_widget.findChild(QLabel)
        
        if not image_label:
            return
        
        image_label.clear()
        image_label.setText(f"Slot {slot_index + 1}")
        
        # ซ่อน delete button
        if hasattr(image_label, 'delete_button'):
            image_label.delete_button.setVisible(False)
    
    def get_active_image_paths(self) -> List[str]:
        """ได้รายการ path ของภาพที่มีใน slots (ไม่รวม None)"""
        return [path for path in self.image_paths if path is not None]
    
    def get_image_count(self) -> int:
        """ได้จำนวนภาพที่มีใน slots"""
        return len(self.get_active_image_paths())
    
    def update_image_info(self):
        """อัปเดต image info label ด้วยข้อมูลภาพทั้งหมด"""
        active_images = self.get_active_image_paths()
        count = len(active_images)
        
        if count == 0:
            self.image_info_label.setText("ยังไม่มีภาพ")
            # อัปเดต legacy selected_image_path
            self.selected_image_path = None
        else:
            info_text = f"{count} ภาพถูกเลือก"
            if count == 1:
                # แสดงข้อมูลภาพเดียว
                try:
                    img_path = active_images[0]
                    with Image.open(img_path) as img:
                        size_mb = os.path.getsize(img_path) / (1024 * 1024)
                        info_text = f"1 ภาพ: {img.width}×{img.height}\n{size_mb:.1f} MB"
                except:
                    pass
            
            self.image_info_label.setText(info_text)
            # อัปเดต legacy selected_image_path เป็นภาพแรก
            self.selected_image_path = active_images[0]
    
    def show_error_detail(self):
        """แสดงรายละเอียด error แบบเต็ม"""
        if hasattr(self, 'last_translated_error') and self.last_translated_error:
            self.show_enhanced_error_dialog(self.last_translated_error)
        elif self.last_error_message:
            self.show_error_dialog("เกิดข้อผิดพลาดในการ edit ภาพ", self.last_error_message)
    
    def show_error_image(self):
        """แสดงภาพ error เมื่อการสร้างภาพไม่สำเร็จ"""
        try:
            # สร้างภาพ error อย่างง่าย
            error_pixmap = QPixmap(200, 200)
            error_pixmap.fill(QColor(48, 69, 48))  # พื้นหลังสีเขียวเข้ม
            
            # วาดข้อความ error
            from PySide6.QtGui import QPainter, QFont, QPen
            painter = QPainter(error_pixmap)
            painter.setPen(QPen(QColor(200, 230, 201), 2))  # สีเขียวอ่อน
            
            # ตั้งค่าฟอนต์
            font = QFont("Arial", 14, QFont.Weight.Bold)
            painter.setFont(font)
            
            # วาดไอคอน X
            painter.drawLine(50, 50, 150, 150)
            painter.drawLine(150, 50, 50, 150)
            
            # วาดข้อความ
            painter.drawText(error_pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "❌\nGeneration\nFailed")
            painter.end()
            
            # แสดงภาพ error ใน result label
            scaled_pixmap = error_pixmap.scaled(
                self.result_image_label.width(), 
                self.result_image_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.result_image_label.setPixmap(scaled_pixmap)
            
            print("[ERROR-IMAGE] Displayed error image in result panel")
            
        except Exception as e:
            print(f"[ERROR] Failed to create error image: {e}")
            # Fallback to text message
            self.result_image_label.setText("❌ การสร้างภาพไม่สำเร็จ - ลองเปลี่ยนพร้อมท์ใหม่")
    
    def show_error_dialog(self, title: str, error_message: str):
        """แสดง error dialog ที่มีขนาดใหญ่และปรับขนาดได้"""
        # QDialog, QTextEdit, QPushButton already imported
        
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        
        # Make dialog resizable and larger
        dialog.resize(800, 600)
        dialog.setMinimumSize(600, 400)
        
        # Set dark theme for dialog
        dialog.setStyleSheet("""
            QDialog {
                background-color: #1f2e1f;
                color: #c8e6c9;
                border: 1px solid #304530;
            }
            QTextEdit {
                background-color: #1a281a;
                border: 1px solid #405040;
                color: #c8e6c9;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                padding: 10px;
            }
            QPushButton {
                padding: 10px 20px;
                font-size: 13px;
                font-weight: 600;
                background-color: #304530;
                color: #c8e6c9;
                border: 1px solid #405040;
            }
            QPushButton:hover {
                background-color: #3a5a3a;
                border: 1px solid #608060;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title label
        title_label = QLabel(f"❌ {title}")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #ff6b6b;
                padding: 10px 0;
            }
        """)
        layout.addWidget(title_label)
        
        # Error text (scrollable and selectable)
        error_text = QTextEdit()
        error_text.setPlainText(error_message)
        error_text.setReadOnly(True)
        layout.addWidget(error_text)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        copy_btn = QPushButton("📋 คัดลอก Error")
        # QGuiApplication already imported
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(error_message))
        button_layout.addWidget(copy_btn)
        
        button_layout.addStretch()
        
        close_btn = QPushButton("ปิด")
        close_btn.clicked.connect(dialog.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # Show dialog
        dialog.exec()
    
    def show_enhanced_error_dialog(self, translated_error: dict):
        """แสดง enhanced error dialog พร้อมคำแปลและคำแนะนำ"""
        # QDialog, QTextEdit, QPushButton already imported, QListWidget, QListWidgetItem
        
        dialog = QDialog(self)
        dialog.setWindowTitle(translated_error["title"])
        dialog.setModal(True)
        
        # Make dialog larger for better UX
        dialog.resize(900, 700)
        dialog.setMinimumSize(700, 500)
        
        # Set dark theme for dialog
        dialog.setStyleSheet("""
            QDialog {
                background-color: #1f2e1f;
                color: #c8e6c9;
                border: 1px solid #304530;
            }
            QTextEdit {
                background-color: #1a281a;
                border: 1px solid #405040;
                color: #c8e6c9;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                padding: 10px;
            }
            QPushButton {
                padding: 10px 20px;
                font-size: 13px;
                font-weight: 600;
                background-color: #304530;
                color: #c8e6c9;
                border: 1px solid #405040;
            }
            QPushButton:hover {
                background-color: #3a5a3a;
                border: 1px solid #608060;
            }
            QListWidget {
                background-color: #1a281a;
                border: 1px solid #405040;
                color: #c8e6c9;
                font-size: 13px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #243324;
            }
            QListWidget::item:hover {
                background-color: #243324;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title and description
        title_label = QLabel(translated_error["title"])
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #ff6b6b;
                padding: 15px 0;
            }
        """)
        layout.addWidget(title_label)
        
        desc_label = QLabel(translated_error["description"])
        desc_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #c8e6c9;
                padding: 10px;
                background-color: #263a26;
                border-left: 4px solid #ff6b6b;
                margin-bottom: 15px;
            }
        """)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # Solutions section
        solutions_label = QLabel("💡 วิธีแก้ไขที่แนะนำ:")
        solutions_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #4CAF50;
                padding: 10px 0;
            }
        """)
        layout.addWidget(solutions_label)
        
        # Solutions list
        solutions_list = QListWidget()
        for i, solution in enumerate(translated_error["solutions"], 1):
            item = QListWidgetItem(f"{i}. {solution}")
            solutions_list.addItem(item)
        layout.addWidget(solutions_list)
        
        # Original error (collapsible)
        original_label = QLabel("🔍 ข้อมูลเทคนิค (สำหรับนักพัฒนา):")
        original_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #889888;
                padding: 10px 0 5px 0;
            }
        """)
        layout.addWidget(original_label)
        
        # Original error text (scrollable and selectable)
        error_text = QTextEdit()
        error_text.setPlainText(translated_error["original"])
        error_text.setReadOnly(True)
        error_text.setMaximumHeight(150)  # Limit height
        layout.addWidget(error_text)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        copy_btn = QPushButton("📋 คัดลอก Error เทคนิค")
        # QGuiApplication already imported
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(translated_error["original"]))
        button_layout.addWidget(copy_btn)
        
        copy_solutions_btn = QPushButton("📝 คัดลอกวิธีแก้ไข")
        solutions_text = f"{translated_error['title']}\n\n{translated_error['description']}\n\nวิธีแก้ไข:\n" + \
                        "\n".join([f"{i}. {sol}" for i, sol in enumerate(translated_error['solutions'], 1)])
        copy_solutions_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(solutions_text))
        button_layout.addWidget(copy_solutions_btn)
        
        button_layout.addStretch()
        
        close_btn = QPushButton("ปิด")
        close_btn.clicked.connect(dialog.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # Show dialog
        dialog.exec()
    
    def display_results(self, results: List[bytes]):
        """แสดงผลลัพธ์ - single image หรือ grid layout สำหรับ multiple images"""
        print(f"[DISPLAY-RESULTS] Called with {len(results) if results else 0} results")
        if not results:
            print("[DISPLAY-RESULTS] No results to display, returning early")
            return
            
        try:
            # ซ่อน error state เมื่อมีผลลัพธ์สำเร็จ
            if hasattr(self, 'result_image_label'):
                # Clear error image/text และกลับไปเป็น normal state
                self.result_image_label.setText("")
                print("[DISPLAY-RESULTS] Cleared error state")
            
            # Store results 
            self.current_results = results
            print(f"[DISPLAY-RESULTS] Stored {len(results)} results")
            
            if len(results) == 1:
                # Single image - แสดงแบบเดิม
                print("[DISPLAY-RESULTS] Displaying single result")
                self._display_single_result(results[0])
            else:
                # Multiple images - แสดงแบบ grid 2x2
                print(f"[DISPLAY-RESULTS] Displaying {len(results)} results in grid")
                self._display_grid_results(results)
                
        except Exception as e:
            print(f"[DISPLAY-RESULTS] Error in display_results: {str(e)}")
            import traceback
            traceback.print_exc()
            self.update_status(f"❌ Error displaying results: {str(e)}")
    
    def _display_grid_results(self, results: List[bytes]):
        """แสดงหลายภาพแบบแยก thumbnails 2x2 (เหมือนฝั่งซ้าย)"""
        try:
            # เคลียร์ result_image_label เก่า และสร้าง grid layout
            self.result_image_label.clear()
            self.result_image_label.setText("")
            
            # สร้าง container widget สำหรับ grid
            if not hasattr(self, 'result_grid_container'):
                self.result_grid_container = QWidget()
                self.result_grid_layout = QGridLayout(self.result_grid_container)
                self.result_grid_layout.setSpacing(10)  # ระยะห่าง 10px
                self.result_grid_layout.setContentsMargins(5, 5, 5, 5)
                
                # แทนที่ result_image_label ด้วย grid container
                parent_layout = self.result_image_label.parent().layout()
                label_index = -1
                for i in range(parent_layout.count()):
                    if parent_layout.itemAt(i).widget() == self.result_image_label:
                        label_index = i
                        break
                
                if label_index >= 0:
                    parent_layout.removeWidget(self.result_image_label)
                    self.result_image_label.hide()
                    parent_layout.insertWidget(label_index, self.result_grid_container)
            
            # เคลียร์ thumbnails เก่า
            for i in reversed(range(self.result_grid_layout.count())):
                child = self.result_grid_layout.itemAt(i).widget()
                if child:
                    child.deleteLater()
            
            # สร้าง thumbnail สำหรับแต่ละภาพ
            self.result_thumbnails = []
            for i, image_data in enumerate(results[:4]):  # สูงสุด 4 ภาพ
                # คำนวณตำแหน่งใน grid 2x2
                row = i // 2
                col = i % 2
                
                # สร้าง thumbnail label
                thumbnail = QLabel()
                thumbnail.setFixedSize(120, 120)  # ขนาดคงที่
                thumbnail.setStyleSheet("""
                    QLabel {
                        border: 2px solid #405040;
                        border-radius: 8px;
                        background-color: #1f2e1f;
                        padding: 3px;
                    }
                    QLabel:hover {
                        border-color: #608060;
                        background-color: #2a3d2a;
                    }
                """)
                thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
                thumbnail.setScaledContents(False)
                
                # โหลดและแสดงภาพ
                with self._managed_image(image_data) as img:
                    if img.mode == 'RGBA':
                        img = img.convert('RGB')
                    
                    # สร้าง QPixmap
                    with BytesIO() as byte_array:
                        img.save(byte_array, format='PNG')
                        byte_data = byte_array.getvalue()
                        
                        pixmap = QPixmap()
                        pixmap.loadFromData(byte_data)
                        
                        # Scale ให้พอดีกับ thumbnail
                        scaled_pixmap = pixmap.scaled(
                            114, 114,  # 120-6 padding
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation
                        )
                        
                        thumbnail.setPixmap(scaled_pixmap)
                
                # เพิ่ม click handler พร้อมเก็บ index
                temp_result_path = self.save_temp_result_image(image_data)
                if temp_result_path:
                    # 🔧 Fix: Store thumbnail index for correct floating viewer navigation
                    thumbnail.thumbnail_index = i
                    thumbnail.image_path = temp_result_path
                    self.make_image_clickable(thumbnail, temp_result_path)
                
                # เพิ่มใน grid
                self.result_grid_layout.addWidget(thumbnail, row, col)
                self.result_thumbnails.append(thumbnail)
            
            # อัพเดต info label สำหรับ multiple images
            total_size = sum(len(data) for data in results)
            if total_size < 1024 * 1024:
                size_str = f"{total_size / 1024:.1f} KB"
            else:
                size_str = f"{total_size / (1024 * 1024):.1f} MB"
            
            info_text = f"📁 {len(results)} images\n📐 Multiple thumbnails\n💾 {size_str}"
            self.result_info_label.setText(info_text)
                
        except Exception as e:
            print(f"Error in _display_grid_results: {str(e)}")
            self.update_status(f"❌ Error displaying grid: {str(e)}")
    
    def _display_single_result(self, image_data: bytes):
        """แสดงภาพเดี่ยวแบบเดิม"""
        print(f"[SINGLE-RESULT] Called with {len(image_data)} bytes")
        try:
            # ซ่อน grid container (ถ้ามี) และแสดง single image label
            if hasattr(self, 'result_grid_container'):
                print("[SINGLE-RESULT] Hiding grid container and showing single label")
                self.result_grid_container.hide()
                self.result_image_label.show()
                
                # ใส่ result_image_label กลับเข้าไปใน layout หากถูกลบออกไป
                parent_layout = self.result_grid_container.parent().layout()
                if parent_layout and not any(parent_layout.itemAt(i).widget() == self.result_image_label 
                                           for i in range(parent_layout.count())):
                    grid_index = -1
                    for i in range(parent_layout.count()):
                        if parent_layout.itemAt(i).widget() == self.result_grid_container:
                            grid_index = i
                            break
                    
                    if grid_index >= 0:
                        parent_layout.insertWidget(grid_index, self.result_image_label)
            
            with self._managed_image(image_data) as image:
                # Convert to Qt format
                if image.mode == 'RGBA':
                    image = image.convert('RGB')
                
                # Create BytesIO in context to ensure cleanup
                with BytesIO() as byte_array:
                    image.save(byte_array, format='PNG')
                    byte_data = byte_array.getvalue()
                    
                    pixmap = QPixmap()
                    pixmap.loadFromData(byte_data)
                    
                    # ฟิตให้เต็มพื้นที่ result_image_label เหมือน thumbnail (fixed size)
                    label_size = self.result_image_label.size()
                    available_width = label_size.width() - 14  # 5px padding x2 + 2px border x2
                    available_height = label_size.height() - 14
                    
                    scaled_pixmap = pixmap.scaled(
                        available_width, available_height,
                        Qt.AspectRatioMode.KeepAspectRatio, 
                        Qt.TransformationMode.SmoothTransformation
                    )
                    
                    print(f"[SINGLE-RESULT] Setting pixmap: {scaled_pixmap.size().width()}x{scaled_pixmap.size().height()}")
                    self.result_image_label.setPixmap(scaled_pixmap)
                    print("[SINGLE-RESULT] Pixmap set successfully")
            
            # แสดงข้อมูลภาพในตำแหน่ง info label
            filename = f"banana_result_001.png"  # ชื่อไฟล์ที่จะบันทึก
            size_text = f"{image.size[0]} × {image.size[1]}"
            
            # คำนวณขนาดไฟล์ (approximate)
            file_size_bytes = len(image_data)
            if file_size_bytes < 1024:
                size_str = f"{file_size_bytes} B"
            elif file_size_bytes < 1024 * 1024:
                size_str = f"{file_size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{file_size_bytes / (1024 * 1024):.1f} MB"
                
            info_text = f"📁 {filename}\n📐 {size_text}\n💾 {size_str}"
            self.result_info_label.setText(info_text)
            
            # สร้าง temporary file สำหรับ floating viewer
            temp_result_path = self.save_temp_result_image(image_data)
            if temp_result_path:
                self.make_image_clickable(self.result_image_label, temp_result_path)
                
        except Exception as e:
            print(f"Error in _display_single_result: {str(e)}")
    
    def save_results(self):
        """บันทึกผลลัพธ์แบบ manual (ให้ผู้ใช้เลือกโฟลเดอร์)"""
        if not self.current_results:
            QMessageBox.information(self, "ไม่มีผลลัพธ์", "ไม่มีผลลัพธ์ให้บันทึก")
            return
            
        # ตรวจสอบว่าไม่ใช่การแสดง error image
        if hasattr(self, 'last_result_path') and self.last_result_path is None:
            QMessageBox.warning(self, "ไม่สามารถบันทึกได้", "การสร้างภาพไม่สำเร็จ - โปรดลองสร้างภาพใหม่ก่อนบันทึก")
            return
        
        # เสนอโฟลเดอร์เริ่มต้นตาม toggle setting
        if self.save_on_original and self.selected_image_path:
            initial_dir = str(Path(self.selected_image_path).parent)
        else:
            initial_dir = str(Path("banana").resolve())
        
        # Choose save directory
        save_dir = QFileDialog.getExistingDirectory(
            self, 
            "เลือกโฟลเดอร์สำหรับบันทึก",
            initial_dir
        )
        if not save_dir:
            return
        
        try:
            # Use new naming system
            now = datetime.now()
            date_str = f"{now.day}{now.strftime('%b').lower()}"
            save_path = Path(save_dir)
            start_number = self.get_next_file_number(save_path, date_str)
            saved_files = []
            
            for i, image_data in enumerate(self.current_results):
                # Convert to PIL Image
                image = Image.open(BytesIO(image_data))
                
                # Generate filename using new system
                filename = f"banana_{date_str}_{start_number + i:03d}.png"
                filepath = save_path / filename
                
                # Safety check for file collision
                counter = 0
                while filepath.exists() and counter < 1000:
                    counter += 1
                    filename = f"banana_{date_str}_{start_number + i + counter:03d}.png"
                    filepath = save_path / filename
                
                # Save image
                image.save(str(filepath), 'PNG')
                saved_files.append(str(filepath))
            
            self.update_status(f"💾 บันทึกแล้ว {len(saved_files)} ไฟล์")
            
            QMessageBox.information(
                self, 
                "บันทึกเสร็จสิ้น",
                f"บันทึกผลลัพธ์ {len(saved_files)} ไฟล์แล้ว:\n\n" + 
                "\n".join([Path(f).name for f in saved_files])
            )
            
        except Exception as e:
            QMessageBox.critical(self, "เกิดข้อผิดพลาด", f"ไม่สามารถบันทึกไฟล์ได้:\n{str(e)}")
    
    # === Multiple Start Images Session Management ===
    
    def clear_image_session(self, keep_prompt=True):
        """ล้าง session ภาพ แต่เก็บ prompt และการตั้งค่าอื่น"""
        # Clear existing thumbnails
        for thumbnail in self.image_session['thumbnails']:
            if thumbnail and hasattr(thumbnail, 'deleteLater'):
                thumbnail.deleteLater()
        
        # Reset session data
        self.image_session = {
            'paths': [],
            'thumbnails': [], 
            'count': 0,
            'mode': 'single'
        }
        
        # Reset legacy selected_image_path for backward compatibility
        self.selected_image_path = None
        
        # Update UI
        self.update_responsive_ui()
        
        status_msg = "🔄 เริ่ม session ใหม่"
        if keep_prompt:
            status_msg += " (เก็บ prompt ไว้)"
        self.update_status(status_msg)
    
    def update_responsive_ui(self):
        """🖼️ อัปเดต UI สำหรับ slot-based system - simplified"""
        # ไม่จำเป็นต้องทำอะไร เพราะ slots จัดการเองแล้ว
        self.update_ui_state()  # Update button states only
    
    def hide_all_previews(self):
        """ซ่อนการแสดงภาพทั้งหมด"""
        # ลบ multi_image_container ถ้ามี
        if hasattr(self, 'multi_image_container') and self.multi_image_container:
            self.multi_image_container.deleteLater()
            self.multi_image_container = None
        
        # แสดง thumbnail_label กลับและรีเซ็ต
        if hasattr(self, 'thumbnail_label'):
            self.thumbnail_label.show()
            self.thumbnail_label.clear()
            self.thumbnail_label.setText("ลากไฟล์มาที่นี่\nหรือคลิกเพื่อเลือก\n(รองรับ 1-3 ภาพ)")
            self.thumbnail_label.setStyleSheet("""
                QLabel {
                    border: 2px dashed #608060;
                    border-radius: 10px;
                    background-color: #263a26;
                    color: #c8e6c9;
                    font-size: 14px;
                    text-align: center;
                    padding: 20px;
                }
                QLabel:hover {
                    background-color: #304530;
                    border-color: #80b080;
                }
            """)
    
    def show_single_image_layout(self):
        """แสดงภาพเดียวในรูปแบบเดิม"""
        # ลบ multi_image_container ถ้ามี
        if hasattr(self, 'multi_image_container') and self.multi_image_container:
            self.multi_image_container.deleteLater()
            self.multi_image_container = None
        
        # แสดง thumbnail_label กลับ
        self.thumbnail_label.show()
        
        if self.get_image_count() >= 1:
            active_paths = self.get_active_image_paths()
            image_path = active_paths[0] if active_paths else None
            self.display_thumbnail(image_path)
            # Update legacy path for compatibility
            self.selected_image_path = image_path
    
    def show_dual_images_layout(self):
        """แสดงสองภาพแนวนอน"""
        if self.get_image_count() >= 2:
            # ซ่อน thumbnail_label เดิม
            self.thumbnail_label.hide()
            
            # ลบ layout เก่าถ้ามี
            if hasattr(self, 'multi_image_container') and self.multi_image_container:
                self.multi_image_container.deleteLater()
            
            # สร้าง container สำหรับแสดงภาพหลายรูป
            self.multi_image_container = QFrame()
            self.multi_image_container.setStyleSheet("""
                QFrame {
                    border: 2px dashed #405040;
                    background-color: #1a281a;
                    border-radius: 10px;
                    min-height: 400px;
                }
            """)
            
            # Layout แนวนอนสำหรับ 2 ภาพ
            h_layout = QHBoxLayout(self.multi_image_container)
            h_layout.setSpacing(10)
            h_layout.setContentsMargins(10, 10, 10, 10)
            
            # สร้างภาพทั้ง 2
            for i in range(2):
                active_paths = self.get_active_image_paths()
                image_path = active_paths[i] if i < len(active_paths) else None
                
                # Container สำหรับภาพแต่ละรูป
                img_container = QFrame()
                img_container.setStyleSheet("""
                    QFrame {
                        border: 1px solid #608060;
                        border-radius: 5px;
                        background-color: #253525;
                    }
                """)
                
                img_layout = QVBoxLayout(img_container)
                img_layout.setSpacing(5)
                img_layout.setContentsMargins(5, 5, 5, 5)
                
                # Label หมายเลข
                number_label = QLabel(f"({i+1}/2)")
                number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                number_label.setStyleSheet("""
                    QLabel {
                        color: #c8e6c9;
                        font-size: 11px;
                        font-weight: bold;
                        background-color: transparent;
                        border: none;
                        padding: 2px;
                    }
                """)
                img_layout.addWidget(number_label)
                
                # Label สำหรับแสดงภาพ
                img_label = QLabel()
                img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                img_label.setScaledContents(False)
                img_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                img_label.setStyleSheet("""
                    QLabel {
                        border: 1px solid #405040;
                        background-color: #1a281a;
                        min-height: 180px;
                        min-width: 200px;
                    }
                """)
                
                # โหลดและแสดงภาพ
                try:
                    # ใช้ helper function สำหรับสร้าง pixmap ที่รักษา aspect ratio
                    scaled_pixmap = self.create_aspect_ratio_preserved_pixmap(image_path, 260, 200)
                    
                    if not scaled_pixmap.isNull():
                        # ตั้งค่า Label ให้แสดงภาพตรงกลาง
                        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        img_label.setScaledContents(False)
                        img_label.setPixmap(scaled_pixmap)
                        
                        # เพิ่ม click handler สำหรับภาพใน session
                        self.make_image_clickable(img_label, image_path)
                    else:
                        img_label.setText(f"ไม่สามารถโหลดภาพ {i+1}")
                        
                except Exception as e:
                    img_label.setText(f"Error loading image {i+1}")
                    print(f"[ERROR] Failed to load image {i+1}: {e}")
                
                img_layout.addWidget(img_label, 1)
                
                # ชื่อไฟล์
                file_label = QLabel(Path(image_path).name)
                file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                file_label.setStyleSheet("""
                    QLabel {
                        color: #9a9a9a;
                        font-size: 9px;
                        background-color: transparent;
                        border: none;
                        padding: 2px;
                    }
                """)
                file_label.setWordWrap(True)
                img_layout.addWidget(file_label)
                
                h_layout.addWidget(img_container)
            
            # เพิ่ม container เข้า layout ของ left panel
            left_panel_layout = self.thumbnail_label.parent().layout()
            if left_panel_layout:
                # หาตำแหน่งของ thumbnail_label เดิม
                index = -1
                for i in range(left_panel_layout.count()):
                    if left_panel_layout.itemAt(i) and left_panel_layout.itemAt(i).widget() == self.thumbnail_label:
                        index = i
                        break
                
                if index >= 0:
                    left_panel_layout.insertWidget(index, self.multi_image_container, 1)
            
            # อัปเดต selected_image_path ให้เป็นภาพแรก
            active_paths = self.get_active_image_paths()
            self.selected_image_path = active_paths[0] if active_paths else None
    
    def show_triple_images_layout(self):
        """แสดงสามภาพแนวนอน"""
        if self.get_image_count() >= 3:
            # ซ่อน thumbnail_label เดิม
            self.thumbnail_label.hide()
            
            # ลบ layout เก่าถ้ามี
            if hasattr(self, 'multi_image_container') and self.multi_image_container:
                self.multi_image_container.deleteLater()
            
            # สร้าง container สำหรับแสดงภาพหลายรูป
            self.multi_image_container = QFrame()
            self.multi_image_container.setStyleSheet("""
                QFrame {
                    border: 2px dashed #405040;
                    background-color: #1a281a;
                    border-radius: 10px;
                    min-height: 400px;
                }
            """)
            
            # Layout แนวนอนสำหรับ 3 ภาพ
            h_layout = QHBoxLayout(self.multi_image_container)
            h_layout.setSpacing(8)
            h_layout.setContentsMargins(8, 10, 8, 10)
            
            # สร้างภาพทั้ง 3
            for i in range(3):
                active_paths = self.get_active_image_paths()
                image_path = active_paths[i] if i < len(active_paths) else None
                
                # Container สำหรับภาพแต่ละรูป
                img_container = QFrame()
                img_container.setStyleSheet("""
                    QFrame {
                        border: 1px solid #608060;
                        border-radius: 5px;
                        background-color: #253525;
                    }
                """)
                
                img_layout = QVBoxLayout(img_container)
                img_layout.setSpacing(3)
                img_layout.setContentsMargins(3, 3, 3, 3)
                
                # Label หมายเลข
                number_label = QLabel(f"({i+1}/3)")
                number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                number_label.setStyleSheet("""
                    QLabel {
                        color: #c8e6c9;
                        font-size: 10px;
                        font-weight: bold;
                        background-color: transparent;
                        border: none;
                        padding: 2px;
                    }
                """)
                img_layout.addWidget(number_label)
                
                # Label สำหรับแสดงภาพ
                img_label = QLabel()
                img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                img_label.setScaledContents(False)
                img_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                img_label.setStyleSheet("""
                    QLabel {
                        border: 1px solid #405040;
                        background-color: #1a281a;
                        min-height: 140px;
                        min-width: 150px;
                    }
                """)
                
                # โหลดและแสดงภาพ
                try:
                    # ใช้ helper function สำหรับสร้าง pixmap ที่รักษา aspect ratio
                    scaled_pixmap = self.create_aspect_ratio_preserved_pixmap(image_path, 170, 140)
                    
                    if not scaled_pixmap.isNull():
                        # ตั้งค่า Label ให้แสดงภาพตรงกลาง
                        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        img_label.setScaledContents(False)
                        img_label.setPixmap(scaled_pixmap)
                        
                        # เพิ่ม click handler สำหรับภาพใน session
                        self.make_image_clickable(img_label, image_path)
                    else:
                        img_label.setText(f"ไม่สามารถโหลดภาพ {i+1}")
                        
                except Exception as e:
                    img_label.setText(f"Error loading image {i+1}")
                    print(f"[ERROR] Failed to load image {i+1}: {e}")
                
                img_layout.addWidget(img_label, 1)
                
                # ชื่อไฟล์
                file_label = QLabel(Path(image_path).name)
                file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                file_label.setStyleSheet("""
                    QLabel {
                        color: #9a9a9a;
                        font-size: 8px;
                        background-color: transparent;
                        border: none;
                        padding: 1px;
                    }
                """)
                file_label.setWordWrap(True)
                img_layout.addWidget(file_label)
                
                h_layout.addWidget(img_container)
            
            # เพิ่ม container เข้า layout ของ left panel
            left_panel_layout = self.thumbnail_label.parent().layout()
            if left_panel_layout:
                # หาตำแหน่งของ thumbnail_label เดิม
                index = -1
                for i in range(left_panel_layout.count()):
                    if left_panel_layout.itemAt(i) and left_panel_layout.itemAt(i).widget() == self.thumbnail_label:
                        index = i
                        break
                
                if index >= 0:
                    left_panel_layout.insertWidget(index, self.multi_image_container, 1)
            
            # อัปเดต selected_image_path ให้เป็นภาพแรก
            active_paths = self.get_active_image_paths()
            self.selected_image_path = active_paths[0] if active_paths else None
    
    def update_mode_indicator(self):
        """อัปเดตการแสดงโหมดปัจจุบัน"""
        count = self.get_image_count()
        
        if count == 0:
            status = "✅ ระบบพร้อมใช้งาน - เลือกภาพเพื่อเริ่มต้น (รองรับ 1-4 ภาพ)"
        elif count == 1:
            status = f"🍌 โหมดภาพเดียว (1/4 ภาพ)"
        elif count == 2:
            status = f"🍌 โหมดผสมผสาน (2/4 ภาพ)"
        elif count == 3:
            status = f"🍌 โหมดมัลติ (3/4 ภาพ)"
        elif count == 4:
            status = f"🍌 โหมดเต็ม (4/4 ภาพ - สูงสุด)"
        else:
            status = f"⚠️ เกินขีดจำกัด ({count} ภาพ)"
            
        self.update_status(status)
    
    def prepare_session_contents(self, prompt_text):
        """🖼️ เตรียมข้อมูล contents ตาม slot-based management สำหรับ API"""
        # 🎯 สร้าง prompt ที่อ้างอิงหมายเลขภาพที่ถูกต้อง
        active_image_paths = self.get_active_image_paths()
        image_count = len(active_image_paths)
        
        if image_count > 1:
            # เพิ่มคำอธิบายหมายเลขภาพใน prompt
            image_refs = []
            for i, path in enumerate(active_image_paths):
                slot_num = self.image_paths.index(path) + 1  # 1-based slot number
                image_refs.append(f"Image {slot_num}")
            
            enhanced_prompt = f"{prompt_text}\n\n[Images: {', '.join(image_refs)} (Total: {image_count} images)]"
            contents = [enhanced_prompt]
        else:
            contents = [prompt_text]  # Single image, no need for references
        
        # เพิ่มภาพตาม slot order (1-4) ที่มีภาพจริง
        for image_path in active_image_paths:
            try:
                with self._managed_image(image_path) as image:
                    if image.mode != 'RGB':
                        image = image.convert('RGB')
                        
                    # Resize ถ้าจำเป็น (เหมือนใน BananaWorker)
                    max_size = 1024
                    if max(image.size) > max_size:
                        # Create a copy for resizing to avoid modifying the original
                        resized_image = image.copy()
                        resized_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                        contents.append(resized_image)
                    else:
                        contents.append(image.copy())  # Use copy to avoid reference issues
            except Exception as e:
                print(f"[ERROR] Failed to load image {image_path}: {e}")
                continue
                
        return contents

    def start_session_generation(self, use_new_sdk: bool = True):
        """เริ่มการสร้างภาพตาม session ปัจจุบัน"""
        try:
            # เตรียม contents สำหรับ API
            prompt_text = self.prompt_input.toPlainText().strip()
            
            # สำหรับ multiple images ใช้ ImageEditWorker ใหม่ที่รองรับ contents
            contents = self.prepare_session_contents(prompt_text)
            
            # ใช้ ImageEditWorker ใหม่ที่รับ contents
            self.worker = ImageEditWorker(
                contents=contents,
                use_new_sdk=use_new_sdk
            )
            
            self.worker.finished.connect(self.on_generation_complete)
            self.worker.error.connect(self.on_generation_error)
            self.worker.status_update.connect(self.update_status)
            self.worker.start()
            
        except Exception as e:
            self.update_status(f"❌ เกิดข้อผิดพลาดในการเตรียมข้อมูล: {str(e)}")
            # Re-enable buttons on error
            self.set_buttons_enabled(True)


# IPC functions removed for standalone version
# def send_image_to_existing_instance(image_path): ...
# def send_prompt_to_existing_instance(prompt_text): ...
# def is_banana_editor_running(): ...


class FloatingImageViewer(QWidget):
    """Floating image viewer สำหรับแสดงภาพขนาดเต็ม พร้อม scroll wheel zoom"""
    
    def __init__(self, image_path_or_paths, parent=None):
        super().__init__(parent)
        # Support both single path (str) and multiple paths (list)
        if isinstance(image_path_or_paths, str):
            self.image_paths = [image_path_or_paths]
        else:
            self.image_paths = list(image_path_or_paths)
        
        # Current image index
        self.current_index = 0
        self.image_path = self.image_paths[0]
        self.parent_widget = parent
        
        # Setup frameless window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool  # ไม่แสดงใน taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        # Calculate appropriate target height based on screen size
        screen_geometry = QApplication.primaryScreen().geometry()
        screen_height = screen_geometry.height()
        screen_width = screen_geometry.width()
        
        # Use 80% of screen height as maximum, but not less than 400px
        max_height = int(screen_height * 0.8)
        self.target_height = min(960, max_height, screen_height - 100)  # Leave 100px for window decorations
        self.target_height = max(400, self.target_height)  # Minimum 400px
        
        # Store screen dimensions for width checking later
        self.max_width = int(screen_width * 0.9)  # Use 90% of screen width as maximum
        
        # Zoom properties
        self.zoom_factor = 1.0
        self.min_zoom = 0.10  # 10%
        self.max_zoom = 4.50  # 450%
        self.zoom_step = 0.1  # 10% increments
        self.original_pixmap = None
        
        self.image_widget = None
        self.overlay_widget = None
        
        # Navigation buttons
        self.prev_btn = None
        self.next_btn = None
        
        self.setup_ui()
        self.load_and_display_image()
        self.center_on_screen()
        
    def setup_ui(self):
        """สร้าง UI สำหรับ floating viewer"""
        # Set semi-transparent background
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(31, 46, 31, 0.85);
            }
        """)
        
        # Create main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(0)
        
        # Image label for displaying the image
        self.image_widget = QLabel(self)
        self.image_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_widget.setScaledContents(False)
        self.image_widget.setStyleSheet("""
            QLabel {
                background-color: transparent;
                border: 1px solid #808080;
                border-radius: 4px;
                padding: 0px;
            }
        """)
        layout.addWidget(self.image_widget)
        
        # Navigation buttons (only show if multiple images)
        if len(self.image_paths) > 1:
            print(f"[FloatingViewer] Setting up navigation for {len(self.image_paths)} images")
            self.setup_navigation_buttons()
        else:
            print(f"[FloatingViewer] No navigation needed - single image")
            
    def setup_navigation_buttons(self):
        """สร้างปุ่มนำทางสำหรับหลายภาพ"""
        print("[FloatingViewer] Creating navigation buttons...")
        
        # Create navigation buttons directly on main widget (no container)
        button_style = """
            QPushButton {
                background-color: transparent;
                border: none;
                color: white;
                font-size: 16px;
                font-weight: bold;
                font-family: 'Arial Black', Arial, sans-serif;
                border-radius: 16px;
                padding: 6px;
                min-width: 20px;
                min-height: 20px;
                max-width: 20px;
                max-height: 20px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
                border-radius: 16px;
                padding: 6px;
                min-width: 32px;
                min-height: 32px;
                max-width: 32px;
                max-height: 32px;
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.15);
                border-radius: 16px;
                padding: 6px;
                min-width: 32px;
                min-height: 32px;
                max-width: 32px;
                max-height: 32px;
            }
        """
        
        # Create buttons directly on the main widget
        self.prev_btn = QPushButton("‹", self)
        self.prev_btn.setStyleSheet(button_style)
        self.prev_btn.clicked.connect(self.prev_image)
        self.prev_btn.setToolTip("Previous image")
        self.prev_btn.setFixedSize(20, 20)
        print(f"[FloatingViewer] Prev button created: {self.prev_btn}")
        
        self.next_btn = QPushButton("›", self)
        self.next_btn.setStyleSheet(button_style)
        self.next_btn.clicked.connect(self.next_image)
        self.next_btn.setToolTip("Next image")
        self.next_btn.setFixedSize(20, 20)
        print(f"[FloatingViewer] Next button created: {self.next_btn}")
        
        # Position buttons immediately with manual coordinates
        self.position_nav_buttons_immediately()
        self.update_nav_button_states()
        
        # Bring to front and show
        self.prev_btn.raise_()
        self.next_btn.raise_()
        self.prev_btn.show()
        self.next_btn.show()
        
        print("[FloatingViewer] Navigation buttons setup completed")
        print(f"[FloatingViewer] Prev button visible: {self.prev_btn.isVisible()}")
        print(f"[FloatingViewer] Next button visible: {self.next_btn.isVisible()}")
        print(f"[FloatingViewer] Prev button size: {self.prev_btn.size()}")
        print(f"[FloatingViewer] Next button size: {self.next_btn.size()}")
        print(f"[FloatingViewer] FloatingViewer size: {self.size()}")
        
        print(f"[FloatingViewer] Navigation buttons created: prev at ({self.prev_btn.x()}, {self.prev_btn.y()}), next at ({self.next_btn.x()}, {self.next_btn.y()})")
        
    def position_nav_buttons_immediately(self):
        """จัดตำแหน่งปุ่มนำทางทันที"""
        if not self.prev_btn or not self.next_btn:
            print("[FloatingViewer] Buttons not found for positioning")
            return
            
        # Position based on current widget size
        widget_width = self.width()
        widget_height = self.height()
        
        # Center buttons vertically (using actual button size 20px)
        button_y = (widget_height - 20) // 2  
        
        # Left and right positions with margins  
        prev_x = 15  # Small margin from left edge
        next_x = widget_width - 35  # 20px button width + 15px margin
        
        self.prev_btn.move(prev_x, button_y)  
        self.next_btn.move(next_x, button_y)
        
        print(f"[FloatingViewer] Widget size: {widget_width}x{widget_height}")
        print(f"[FloatingViewer] Button Y position: {button_y}")
        print(f"[FloatingViewer] Prev button at: ({prev_x}, {button_y})")
        print(f"[FloatingViewer] Next button at: ({next_x}, {button_y})")
        print(f"[FloatingViewer] Prev button geometry: {self.prev_btn.geometry()}")
        print(f"[FloatingViewer] Next button geometry: {self.next_btn.geometry()}")
        
    def load_and_display_image(self):
        """โหลดและแสดงภาพตาม aspect ratio พร้อม zoom functionality"""
        try:
            if not os.path.exists(self.image_path):
                self.show_error("ไม่พบไฟล์ภาพ")
                return
                
            # Load original pixmap and store it
            self.original_pixmap = QPixmap(self.image_path)
            if self.original_pixmap.isNull():
                self.show_error("ไม่สามารถโหลดภาพได้")
                return
                
            # Get original dimensions
            original_width = self.original_pixmap.width()
            original_height = self.original_pixmap.height()
                
            # Calculate display size with screen bounds checking
            aspect_ratio = original_width / original_height
            display_width = int(self.target_height * aspect_ratio)
            
            # Check if width exceeds screen bounds and adjust accordingly
            if display_width > self.max_width:
                display_width = self.max_width
                self.target_height = int(display_width / aspect_ratio)
                print(f"[FloatingViewer] Adjusted size to fit screen: {display_width}x{self.target_height}")
            
            # Store base dimensions (100% zoom level)
            self.base_width = display_width
            self.base_height = self.target_height
            
            # Apply zoom and display
            self.update_zoom_display()
            
        except Exception as e:
            print(f"[FloatingViewer] Error loading image: {e}")
            self.show_error(f"เกิดข้อผิดพลาด: {str(e)}")
    
            
    def show_error(self, message: str):
        """แสดงข้อความข้อผิดพลาด"""
        self.image_widget.setText(f"❌ {message}")
        self.image_widget.setStyleSheet("""
            QLabel {
                color: #ff6b6b;
                background-color: rgba(0, 0, 0, 0.8);
                border: 1px solid #ff6b6b;
                border-radius: 4px;
                padding: 20px;
                font-size: 14px;
            }
        """)
        self.resize(400, 200)
        
    def center_on_screen(self):
        """จัดตำแหน่งด้วย smart positioning logic"""
        screen_geometry = QApplication.primaryScreen().geometry()
        screen_center_y = screen_geometry.height() // 2
        
        # แกนตั้ง (Y): กึ่งกลางหน้าจอเสมอ
        window_y = screen_center_y - self.height() // 2
        
        # แกนนอน (X): ยึดกับกึ่งกลาง UI หลัก หรือกึ่งกลางจอถ้าไม่มี parent
        if self.parent_widget:
            # ยึดกับกึ่งกลางของ UI หลัก (Banana Editor window)
            parent_geometry = self.parent_widget.geometry()
            parent_center_x = parent_geometry.x() + parent_geometry.width() // 2
            window_x = parent_center_x - self.width() // 2
            
            # ตรวจสอบไม่ให้ล้นออกจากขอบจอ
            screen_width = screen_geometry.width()
            if window_x < 0:
                window_x = 10  # padding จากขอบซ้าย
            elif window_x + self.width() > screen_width:
                window_x = screen_width - self.width() - 10  # padding จากขอบขวา
                
            # ย้ายหน้าต่างไปตำแหน่งที่คำนวณได้
            self.move(window_x, window_y)
        else:
            # ถ้าไม่มี parent ให้ใช้กึ่งกลางจอ
            screen_center_x = screen_geometry.width() // 2
            window_x = screen_center_x - self.width() // 2
            
            # ย้ายหน้าต่างไปกึ่งกลางจอ
            self.move(window_x, window_y)
    
    def update_zoom_display(self):
        """อัปเดตการแสดงภาพตาม zoom level"""
        if not self.original_pixmap:
            return
            
        # Calculate current display size
        current_width = int(self.base_width * self.zoom_factor)
        current_height = int(self.base_height * self.zoom_factor)
        
        # Scale pixmap to current zoom level
        scaled_pixmap = self.original_pixmap.scaled(
            current_width,
            current_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        # Set scaled image to label
        self.image_widget.setPixmap(scaled_pixmap)
        
        # Resize window to fit zoomed image + padding
        window_width = current_width + 40   # 20px padding on each side
        window_height = current_height + 40
        self.resize(window_width, window_height)
        
        # Center image in window
        self.image_widget.resize(current_width, current_height)
        self.image_widget.move(20, 20)  # 20px padding
        
        # Recenter window on screen after resize
        self.center_on_screen()
        
    def wheelEvent(self, event):
        """จัดการ scroll wheel สำหรับ zoom in/out"""
        # Get wheel delta (positive = zoom in, negative = zoom out)
        delta = event.angleDelta().y()
        
        if delta > 0:
            # Zoom in
            new_zoom = min(self.zoom_factor + self.zoom_step, self.max_zoom)
        else:
            # Zoom out
            new_zoom = max(self.zoom_factor - self.zoom_step, self.min_zoom)
        
        # Apply new zoom if changed
        if new_zoom != self.zoom_factor:
            self.zoom_factor = new_zoom
            self.update_zoom_display()
            
        # Accept event to prevent propagation
        event.accept()
        
    def reset_zoom(self):
        """รีเซ็ต zoom กลับไป 100%"""
        self.zoom_factor = 1.0
        self.update_zoom_display()
        
    def mousePressEvent(self, event):
        """ปิดหน้าต่างทันทีเมื่อคลิก (ไม่ว่าจะ zoom หรือไม่)"""
        # Close the viewer immediately regardless of zoom level
        self.close()
        super().mousePressEvent(event)
        
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts:
        - ESC: ปิดหน้าต่าง
        - Left Arrow: Previous image
        - Right Arrow: Next image
        - Ctrl+V/Ctrl+P: Paste image from clipboard to 4-slot system 
        - Ctrl+Enter: Execute generation with New SDK
        """
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_Left:
            self.prev_image()
        elif event.key() == Qt.Key.Key_Right:
            self.next_image()
        else:
            super().keyPressEvent(event)
        
    def prev_image(self):
        """แสดงภาพก่อนหน้า"""
        if len(self.image_paths) <= 1:
            return
            
        self.current_index = (self.current_index - 1) % len(self.image_paths)
        self.image_path = self.image_paths[self.current_index]
        
        # Keep current zoom level and reload image
        current_zoom = self.zoom_factor  # เก็บค่า zoom ปัจจุบัน
        self.load_and_display_image()
        self.zoom_factor = current_zoom  # คืนค่า zoom
        self.update_zoom_display()  # อัปเดตการแสดงผลตาม zoom
        self.update_nav_button_states()
        
    def next_image(self):
        """แสดงภาพถัดไป"""
        if len(self.image_paths) <= 1:
            return
            
        self.current_index = (self.current_index + 1) % len(self.image_paths)
        self.image_path = self.image_paths[self.current_index]
        
        # Keep current zoom level and reload image
        current_zoom = self.zoom_factor  # เก็บค่า zoom ปัจจุบัน
        self.load_and_display_image()
        self.zoom_factor = current_zoom  # คืนค่า zoom
        self.update_zoom_display()  # อัปเดตการแสดงผลตาม zoom
        self.update_nav_button_states()
        
    def update_nav_button_positions(self):
        """อัปเดตตำแหน่งปุ่มนำทาง"""
        if not self.prev_btn or not self.next_btn:
            return
        
        self.position_nav_buttons_immediately()
        
    def update_nav_button_states(self):
        """อัปเดตสถานะปุ่มนำทาง"""
        if not self.prev_btn or not self.next_btn:
            return
            
        # Always enable if multiple images (circular navigation)
        self.prev_btn.setEnabled(len(self.image_paths) > 1)
        self.next_btn.setEnabled(len(self.image_paths) > 1)
        
        # Update tooltips with current position
        if len(self.image_paths) > 1:
            self.prev_btn.setToolTip(f"Previous image ({self.current_index + 1}/{len(self.image_paths)})")
            self.next_btn.setToolTip(f"Next image ({self.current_index + 1}/{len(self.image_paths)})")
    
    def showEvent(self, event):
        """เมื่อแสดงหน้าต่าง ให้จัดตำแหน่งปุ่มใหม่"""
        super().showEvent(event)
        print("[FloatingViewer] showEvent triggered")
        if hasattr(self, 'prev_btn') and self.prev_btn:
            print("[FloatingViewer] Repositioning buttons in showEvent")
            # Use QTimer.singleShot to ensure widget is fully shown before positioning
            QTimer.singleShot(50, self.update_nav_button_positions)
    
    def resizeEvent(self, event):
        """อัปเดตตำแหน่งปุ่มเมื่อ resize"""
        super().resizeEvent(event)
        print(f"[FloatingViewer] resizeEvent: {event.size()}")
        if hasattr(self, 'prev_btn') and self.prev_btn:
            print("[FloatingViewer] Repositioning buttons in resizeEvent")
            self.update_nav_button_positions()
        
    def closeEvent(self, event):
        """Clean up เมื่อปิดหน้าต่าง"""
        # Release image resources
        if self.image_widget and self.image_widget.pixmap():
            self.image_widget.clear()
        super().closeEvent(event)


def main():
    """Main function with command line argument support"""
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Banana Editor - Image-to-Image Editing Tool')
    parser.add_argument('--preload-image', type=str, help='Path to image file to preload')
    parser.add_argument('--image', type=str, help='Alias for --preload-image')
    args = parser.parse_args()
    
    # Get preload path (direct loading - no IPC)
    preload_path = args.preload_image or args.image
    app = QApplication(sys.argv)
    
    # Set application info
    app.setApplicationName("Banana Editor")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("BananaEditor")
    
    # Enable high DPI support (PyQt6 handles this automatically)
    # app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)  # Not needed in PyQt6
    # app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)     # Not needed in PyQt6
    
    # Create and show main window
    window = BananaEditor()
    
    # Preload image if specified
    if preload_path:
        print(f"[DEBUG] Preloading image: {preload_path}")
        window.preload_image(preload_path, clear_existing=True)  # Direct loading
    
    window.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()