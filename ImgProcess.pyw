import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import subprocess
import sys
import time
import re
import urllib.parse
import zipfile
import tempfile   
import subprocess
import shutil
import urllib.request
import psutil
import requests
import pygetwindow as gw
from PyQt5.QtWidgets import QLabel, QMenu, QMessageBox, QPushButton,  QVBoxLayout, QFileDialog, QListWidget, QListWidgetItem, QLineEdit, QDialog  
from PyQt5.QtWidgets import QComboBox, QFrame, QStackedWidget, QProgressBar, QApplication, QWidget, QDesktopWidget,QHBoxLayout, QShortcut, QProgressDialog
from PyQt5.QtGui import QBrush, QFont, QIcon,QColor,QDesktopServices, QPainter, QKeySequence, QRegExpValidator,QCursor, QTextCursor
from PyQt5.QtCore import QCoreApplication, QPropertyAnimation, QRect, QSettings,Qt, QUrl, QTimer, QThread, pyqtSignal, QRegExp, QProcess, QPoint,QEvent       
from PIL import Image
from psd_tools import PSDImage


CURRENT_VERSION = "v1.1.1"  #版本号

# —— 配置 FFmpeg 的绝对路径 —— #
FFMPEG_ABSOLUTE_PATH = r"C:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe"
FFPROBE_PATH = r"C:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffprobe.exe"

def run_as_admin():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return  # 已经是管理员，直接运行

    # 重新以管理员身份启动
    exe = sys.executable
    params = " ".join(sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    sys.exit()  # 退出当前进程，等待新进程执行

run_as_admin()

#下载更新包线程
class DownloadThread(QThread):
    download_progress = pyqtSignal(int, int, str)  # 进度, 已下载大小, 网速字符串
    download_finished = pyqtSignal(str)
    download_failed = pyqtSignal(str)
    message = pyqtSignal(str)
    
    def __init__(self, download_url):
        super().__init__()
        self.download_url = download_url
        self.total_size = 0
        self._is_running = True
        self._start_time = None
        self._last_update_time = None
        self._last_size = 0
        self._speed_history = []

    def run(self):
        try:
            tmp_dir = tempfile.mkdtemp()
            local_path = os.path.join(tmp_dir, os.path.basename(self.download_url))
            
            self.message.emit(f"开始下载: {os.path.basename(self.download_url)}")
            self._start_time = time.time()
            self._last_update_time = self._start_time
            self._last_size = 0
            
            with requests.get(self.download_url, stream=True, timeout=30) as r:
                r.raise_for_status()
                self.total_size = int(r.headers.get('content-length', 0))
                downloaded_size = 0
                
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if not self._is_running:
                            os.remove(local_path)
                            self.message.emit("下载已取消")
                            return
                            
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # 计算实时网速（每100ms更新一次）
                        current_time = time.time()
                        if current_time - self._last_update_time >= 0.1:  # 100ms更新频率
                            elapsed = current_time - self._last_update_time
                            speed = (downloaded_size - self._last_size) / elapsed  # B/s
                            
                            # 平滑处理（最近3次平均值）
                            self._speed_history.append(speed)
                            if len(self._speed_history) > 3:
                                self._speed_history.pop(0)
                            avg_speed = sum(self._speed_history) / len(self._speed_history)
                            
                            # 格式化网速显示
                            speed_str = self.format_speed(avg_speed)
                            
                            progress = int(downloaded_size * 100 / self.total_size) if self.total_size > 0 else 0
                            self.download_progress.emit(progress, downloaded_size, speed_str)
                            
                            self._last_update_time = current_time
                            self._last_size = downloaded_size
                
            self.download_finished.emit(local_path)
            
        except Exception as e:
            self.download_failed.emit(str(e))
    
    def format_speed(self, speed_bps):
        """格式化网速显示"""
        if speed_bps < 1024:  # <1KB/s
            return f"{speed_bps:.0f} B/s"
        elif speed_bps < 1024 * 1024:  # <1MB/s
            return f"{speed_bps/1024:.1f} KB/s"
        else:
            return f"{speed_bps/(1024 * 1024):.1f} MB/s"

class CheckUpdateThread(QThread):
    update_checked = pyqtSignal(dict, str)  # 传递检查结果和错误信息

    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version
        self.api_url = "https://api.github.com/repos/lemon-o/ImgProcess/releases/latest"

    def run(self):
        try:
            response = requests.get(self.api_url, timeout=10)
            response.raise_for_status()
            self.update_checked.emit(response.json(), "")
        except Exception as e:
            self.update_checked.emit({}, str(e))

# 检测更新窗口
class UpdateDialog(QDialog):
    def __init__(self, parent=None, current_version=""):
        super().__init__(parent)
        self.current_version = current_version
        self.latest_version = ""
        self.download_url = ""
        self.setup_ui()
        self.show()  # 立即显示窗口
        self.start_check_update()  # 使用专用线程检查更新
        
    def setup_ui(self):
        self.setWindowTitle("检查更新")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(400, 150)
        
        layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("软件更新")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        
        # 状态信息
        self.status_label = QLabel("正在检查更新...")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 5px;
                background-color: #f8f9fa;
                min-height: 40px;
            }
        """)
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()  # 初始隐藏
        layout.addWidget(self.progress_bar)
        
        # 按钮布局 - 只在检查更新窗口显示
        button_height1 = self.height() // 5
        button_style = """
        QPushButton {
            background-color: #ffffff;
            color: #3b3b3b;
            border-radius: 6%; /* 圆角半径使用相对单位，可以根据需要调整 */
            border: 1px solid #f5f5f5;
        }

        QPushButton:hover {
            background-color: #0773fc;
            color: #ffffff;
            border: 0.1em solid #0773fc; /* em为相对单位 */
        }

        QPushButton:disabled {
            background-color: #f0f0f0;  /* 禁用时的背景色（浅灰色） */
            color: #a0a0a0;           /* 禁用时的文字颜色（灰色） */
            border: 1px solid #d0d0d0; /* 禁用时的边框颜色 */
        }
        """
        self.button_layout = QHBoxLayout()
        self.update_button = QPushButton("更新")
        self.update_button.setFixedHeight(button_height1)
        self.update_button.setStyleSheet(button_style)
        self.update_button.clicked.connect(self.start_update)
        self.update_button.setEnabled(False)  # 初始不可用
        self.button_layout.addWidget(self.update_button)
        
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setFixedHeight(button_height1)
        self.cancel_button.setStyleSheet(button_style)
        self.cancel_button.clicked.connect(self.close)
        self.button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(self.button_layout)
        self.setLayout(layout)
        
    def start_check_update(self):
        """启动异步检查更新"""
        self.status_label.setText("正在检查更新...")
        self.check_thread = CheckUpdateThread(self.current_version)
        self.check_thread.update_checked.connect(self.handle_update_result)
        self.check_thread.start()

    def handle_update_result(self, release_info, error):
        """处理检查结果"""
        if error:
            self.status_label.setText(f"检查失败: {error}")
            self.cancel_button.setText("关闭")
            return

        # 解析版本信息
        self.latest_version = release_info.get("tag_name", "")
        if not self.latest_version:
            self.status_label.setText("无法获取版本号")
            self.cancel_button.setText("关闭")
            return

        self.status_label.setText(f"当前版本: {self.current_version}\n最新版本: {self.latest_version}")

        if self.latest_version == self.current_version:
            self.status_label.setText("已经是最新版本")
            self.cancel_button.setText("关闭")
            return

        # 获取下载链接
        assets = release_info.get("assets", [])
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith((".exe", ".zip")):
                self.download_url = asset.get("browser_download_url")
                break

        if not self.download_url:
            self.status_label.setText("未找到可下载的安装文件")
            self.cancel_button.setText("关闭")
            return

        # 发现新版本，启用更新按钮
        self.status_label.setText(f"发现新版本 {self.latest_version}，当前版本{CURRENT_VERSION}")
        self.update_button.setEnabled(True)

    def start_update(self):
        """开始下载更新"""
        if hasattr(self, 'download_url') and self.download_url:
            # 重置UI状态
            self.update_button.hide()
            self.cancel_button.hide()
            self.progress_bar.show()
            self.progress_bar.setValue(0)
            self.status_label.setText("准备下载更新...")
            
            # 强制立即更新UI
            QApplication.processEvents()
            
            # 创建下载线程
            self.download_thread = DownloadThread(self.download_url)
            
            # 正确连接所有信号
            self.download_thread.download_progress.connect(self.handle_download_progress)
            self.download_thread.download_finished.connect(self.on_download_finished)
            self.download_thread.download_failed.connect(self.on_download_failed)
            self.download_thread.message.connect(self.status_label.setText)
            
            self.download_thread.start()

    def handle_download_progress(self, progress, downloaded_size, speed_str):
        """处理下载进度和网速"""
        # 格式化大小显示
        def format_size(size):
            if size < 1024:
                return f"{size}B"
            elif size < 1024 * 1024:
                return f"{size/1024:.1f}KB"
            else:
                return f"{size/(1024 * 1024):.1f}MB"
        
        # 更新UI
        total_size = self.download_thread.total_size
        total_str = format_size(total_size) if total_size > 0 else "未知大小"
        
        self.progress_bar.setValue(progress)
        self.status_label.setText(
            f"正在下载更新({format_size(downloaded_size)}/{total_str}) | 速度: {speed_str}"
        )
        QApplication.processEvents()

    def on_download_failed(self, error_msg):
        """下载失败处理"""
        self.progress_bar.hide()
        self.status_label.setText(f"下载失败: {error_msg}")
        # 只显示关闭按钮
        self.cancel_button.setText("关闭")
        self.cancel_button.show()

    def on_download_finished(self, local_path):
        """下载完成处理"""
        self.status_label.setText("下载完成，准备安装...")
        self.progress_bar.setValue(100)
        
        try:
            if local_path.endswith(".exe"):
                # 最小化所有窗口并启动安装程序
                self.minimize_all_windows()
                subprocess.Popen(
                    [local_path], 
                    shell=True,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )         
                
            elif local_path.endswith(".zip"):
                self.status_label.setText(f"更新包已下载到: {local_path}")
                # 只显示关闭按钮
                self.cancel_button.setText("关闭")
                self.cancel_button.show()
                
        except Exception as e:
            self.status_label.setText(f"安装失败: {e}")
            # 只显示关闭按钮
            self.cancel_button.setText("关闭")
            self.cancel_button.show()

    def minimize_all_windows(self):
        """最小化主窗口和所有子窗口"""
        # 最小化主窗口
        if self.parent():
            self.parent().showMinimized()
        
        # 最小化所有对话框
        for window in QApplication.topLevelWidgets():
            if window.isWindow() and window.isVisible():
                window.showMinimized()

        # 退出当前实例
        QApplication.quit()

#图片处理线程
class Worker(QThread):
    finished_signal = pyqtSignal()
    archiving_thread_start_signal = pyqtSignal()
    progress_update = pyqtSignal(int)

    def __init__(self, parent):
        super().__init__(parent)
        self.file_right_list = parent.file_right_list
        self.start1 = False
    
    def run(self):
        if self.start1:
            self.archiving_thread()

    def archiving_thread(self):
        total_psd_files = 0  # 初始化总文件数量
        jpg_files = 0  # 初始化已处理的 JPG 文件数量
        for i in range(self.file_right_list.count()):
            item = self.file_right_list.item(i)
            # 检查item是否为空
            if item is None:
                continue
            folder_path = os.path.join(item.data(Qt.UserRole), "已修")
            total_psd_files += sum(1 for file_name in os.listdir(folder_path) if file_name.endswith(".psd") and os.path.isfile(os.path.join(folder_path, file_name)))
        for i in range(self.file_right_list.count()):
            item = self.file_right_list.item(i)
            # 检查item是否为空
            if item is None:
                continue
            folder_path = os.path.join(item.data(Qt.UserRole), "已修")
            self.right_list_path = item.data(Qt.UserRole)
            self.file_path_right = os.path.join(self.right_list_path, "已修")

            if os.path.exists(self.file_path_right):
                self.psd_folder_right = os.path.join(self.file_path_right, "psd")
                # 遍历目标文件夹中的文件
            for file_name in os.listdir(self.file_path_right):
                # 检查文件类型是否为 PSD
                if os.path.isfile(os.path.join(self.file_path_right, file_name)) and file_name.endswith(".psd"):
                    try:
                        # 导出为 JPG
                        jpg_file_name = os.path.splitext(file_name)[0] + ".jpg"
                        jpg_path = os.path.join(self.right_list_path, "已修", jpg_file_name)
                        psd = PSDImage.open(os.path.join(self.file_path_right, file_name))
                        image = psd.compose()
                        # 将 RGBA 转换为 RGB
                        if image.mode == "RGBA":
                            image = image.convert("RGB")
                        image.save(jpg_path, "JPEG")

                        # 复制到“其他尺寸”文件夹
                        other_sizes_path = os.path.join(self.file_path_right, "其他尺寸")
                        if not os.path.exists(other_sizes_path):
                            os.makedirs(other_sizes_path)
                        shutil.copy(jpg_path, os.path.join(other_sizes_path, jpg_file_name))

                        # 发送子进度更新信号
                        jpg_files += 1
                        if total_psd_files != 0:
                            total_progress = (jpg_files / total_psd_files) * 100
                            self.progress_update.emit(int(total_progress))
                        else:
                            self.progress_update.emit(100)

                        # 处理事件队列，确保及时更新UI
                        QCoreApplication.processEvents()

                        # 裁剪图片为方图（不包括“其他尺寸”里的图片）
                        img = Image.open(jpg_path)
                        width, height = img.size
                        # 以宽度为基准裁剪成方图
                        if width > height:
                            left = (width - height) // 2
                            top = 0
                            right = left + height
                            bottom = height
                        else:
                            left = 0
                            top = (height - width) // 2
                            right = width
                            bottom = top + width

                        cropped_img = img.crop((left, top, right, bottom))
                        cropped_img.save(jpg_path)

                    except Exception as e:
                        full_path = os.path.join(self.file_path_right, file_name)
                        print(f"无法处理文件: {file_name} ({full_path})")
                        print(f"错误信息: {e}")
                        logging.info(f"无法处理文件: {file_name} ({full_path})")
                        logging.info(f"错误信息: {e}")

                    destination_path = os.path.join(self.file_path_right, file_name)
                    source_path = os.path.join(self.psd_folder_right, file_name)
                    try:
                        # 移动 PSD 文件到 "psd" 文件夹
                        os.rename(destination_path, source_path)
                    except FileExistsError:
                        # 在文件名中添加后缀
                        base, extension = os.path.splitext(file_name)
                        counter = 1
                        new_psd_dest_path = os.path.join(self.psd_folder_right, f"{base}_backup_{counter}{extension}")   
                        # 生成唯一的文件名
                        while os.path.exists(new_psd_dest_path):
                            counter += 1
                            new_psd_dest_path = os.path.join(self.psd_folder_right, f"{base}_backup_{counter}{extension}")
                        # 移动文件到新路径
                        os.rename(destination_path, new_psd_dest_path)

            # 复制"图片复制"文件夹内的所有jpg和png图片到 self.file_path_right
            copy_dir = os.path.join(os.path.dirname(self.right_list_path), "图片复制")
            # 检查"图片复制"文件夹是否存在
            if os.path.isdir(copy_dir):
                # 遍历文件夹中的所有文件
                for filename in os.listdir(copy_dir):
                    # 检查文件扩展名是否为jpg或png（不区分大小写）
                    if filename.lower().endswith(('.jpg', '.png')):
                        source_file = os.path.join(copy_dir, filename)
                        try:
                            # 复制文件到目标路径
                            shutil.copy2(source_file, self.file_path_right)
                            print(f"成功复制图片: {filename}")
                            logging.info(f"成功复制图片: {filename}")
                        except Exception as e:
                            print(f"复制图片失败: {filename}, 错误: {e}")
                            logging.info(f"复制图片失败: {filename}, 错误: {e}")
            else:
                print(f"未找到'图片复制'文件夹: {copy_dir}")
                logging.info(f"未找到'图片复制'文件夹: {copy_dir}")
         
        # 当线程耗时任务完成时，直接发送总进度为100%
        self.progress_update.emit(100)
        time.sleep(0.5)
        self.start1 = False            
        self.finished_signal.emit()

#视频处理线程
class VideoWorker(QThread):
    finished_signal = pyqtSignal()

    def __init__(self, folders_list, parent=None):
        super().__init__(parent)
        self.folders_list = folders_list  # 接收文件夹列表 [(dir_path, file_path), ...]

    def run(self):
        for dir_path, file_path in self.folders_list:
            # 处理单个文件夹的逻辑
            self.process_folder(dir_path, file_path)
        self.finished_signal.emit()

    def process_folder(self, dir_path, file_path):
        # 1. 收集原始视频文件
        video_files = []
        for fn in os.listdir(dir_path):  # 使用传入的 dir_path 参数
            fullp = os.path.join(dir_path, fn)
            if os.path.isfile(fullp) and fn.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".flv")):
                video_files.append((fn, fullp))

        # 2. 处理视频文件
        if video_files:
            for src_filename, src_fullpath in video_files:
                print(f"正在处理视频: {src_filename}")
                logging.info(f"正在处理视频: {src_filename}")

                # 构造输出文件名（在原名后面加后缀 "_cropped"）
                name_no_ext, ext = os.path.splitext(src_filename)
                new_filename = f"{name_no_ext}_cropped{ext}"
                temp_output = os.path.join(dir_path, new_filename)  # 使用传入的 dir_path
                final_output = os.path.join(file_path, new_filename)  # 使用传入的 file_path

                # 如果输出文件名已存在，则添加数字后缀
                if os.path.exists(temp_output):
                    counter = 1
                    while True:
                        new_filename = f"{name_no_ext}_cropped_{counter}{ext}"
                        temp_output = os.path.join(dir_path, new_filename)
                        final_output = os.path.join(file_path, new_filename)
                        if not os.path.exists(temp_output):  # 确保找到不存在的文件名
                            break
                        counter += 1
                
                # 用 ffprobe 获取视频宽高
                cmd_probe = [
                    FFPROBE_PATH, "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    src_fullpath
                ]
                result = subprocess.run(
                    cmd_probe,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if result.returncode != 0:
                    print(f"[错误] 无法获取视频分辨率（{src_filename}）：{result.stderr.strip()}")
                    logging.info(f"[错误] 无法获取视频分辨率（{src_filename}）：{result.stderr.strip()}")
                    continue

                try:
                    w_str, h_str = result.stdout.splitlines()
                    w = int(w_str.strip())
                    h = int(h_str.strip())
                except Exception as e:
                    print(f"[错误] 解析分辨率失败（{src_filename}）：{e}")
                    logging.info(f"[错误] 解析分辨率失败（{src_filename}）：{e}")
                    continue

                # 直接让 FFmpeg 计算居中裁剪，不再用 Python 手动算 x/y
                cmd_crop = [
                    FFMPEG_ABSOLUTE_PATH, "-y", "-i", src_fullpath,
                    # crop=min(iw\,ih):min(iw\,ih):(iw-min(iw\,ih))/2:(ih-min(iw\,ih))/2
                    "-vf", r"crop=min(iw\,ih):min(iw\,ih):(iw-min(iw\,ih))/2:(ih-min(iw\,ih))/2",
                    "-an",
                    "-c:v", "libx264",
                    "-preset", "medium",
                    temp_output
                ]
                proc = subprocess.run(
                    cmd_crop,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if proc.returncode != 0:
                    print(f"[错误] ffmpeg 裁剪失败（{src_filename}）：{proc.stderr.strip()}")
                    logging.info(f"[错误] ffmpeg 裁剪失败（{src_filename}）：{proc.stderr.strip()}")
                    # 删除残留的临时文件
                    if os.path.exists(temp_output):
                        try:
                            os.remove(temp_output)
                        except:
                            pass
                    continue

                # 处理完毕后强制结束 FFmpeg 进程
                kill_ffmpeg_processes()
                # 将生成的临时文件移动到目标目录
                try:
                    shutil.move(temp_output, final_output)
                    print(f"[完成] 视频已处理并移动：{final_output}")
                    logging.info(f"[完成] 视频已处理并移动：{final_output}")
                except Exception as e:
                    print(f"[错误] 移动文件时异常（{temp_output} → {final_output}）：{e}")
                    logging.info(f"[错误] 移动文件时异常（{temp_output} → {final_output}）：{e}")
                    # 如果移动失败，可考虑删除残留的 temp_output
                    if os.path.exists(temp_output):
                        try:
                            os.remove(temp_output)
                        except:
                            pass
                    continue

def kill_ffmpeg_processes():
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if 'ffmpeg' in proc.info['name'].lower():
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

#ffmpeg安装窗口
class FFmpegInstallDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent  # 保存父窗口引用
        self.setWindowTitle("安装 FFmpeg")
        self.resize(400, 200)
        # self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        
        # 创建布局
        layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("FFmpeg 安装中...")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 提示信息
        info_label = QLabel("请等待安装完成，不要关闭此窗口。")
        info_label.setStyleSheet("margin-bottom: 10px;")
        info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(info_label)
        
        # 状态标签
        self.status_label = QLabel("正在初始化安装程序...")
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 5px;
                background-color: #f8f9fa;
                min-height: 40px;
            }
        """)
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # 设置布局
        self.setLayout(layout)
        
        # 安装线程
        self.install_thread = None
        
    def start_installation(self):
        """开始安装FFmpeg"""
        self.status_label.setText("正在检查系统环境...")
        self.show()  # 确保弹窗显示
        
        # 创建并启动安装线程
        self.install_thread = FFmpegInstallThread()
        self.install_thread.status_updated.connect(self.update_status)
        self.install_thread.progress_updated.connect(self.update_progress)
        self.install_thread.finished_signal.connect(self.handle_install_result)
        self.install_thread.start()
        
    def update_status(self, text):
        """更新状态信息"""
        self.status_label.setText(text)
        
    def update_progress(self, value):
        """更新进度条"""
        self.progress_bar.setValue(value)
        
    def handle_install_result(self, success, message):
        """处理安装结果"""
        if success:
            self.status_label.setText("安装完成！")
            self.progress_bar.setValue(100)
            QMessageBox.information(self, "安装成功", message)
            # 通知主线程安装完成
            if self.parent:
                self.parent.ffmpeg_installed(True, message)
        else:
            self.status_label.setText(f"安装失败: {message}")
            QMessageBox.critical(self, "安装失败", message)
            # 通知主线程安装失败
            if self.parent:
                self.parent.ffmpeg_installed(False, message)
        # 安装完成后关闭弹窗
        self.close()
        
# ffmpeg安装线程
class FFmpegInstallThread(QThread):
    status_updated = pyqtSignal(str)  # 发送状态更新信号
    progress_updated = pyqtSignal(int)  # 发送进度更新
    finished_signal = pyqtSignal(bool, str)  # 发送完成信号(成功/失败, 消息)

    def __init__(self):
        super().__init__()
        self._start_time = None
        self._last_update_time = None
        self._last_size = 0
        self._speed_history = []
        self._is_running = True

    def run(self):
        temp_dir = None
        try:
            # 检查是否已安装FFmpeg
            self.status_updated.emit("正在检查系统环境...")
            self.progress_updated.emit(10)
            if shutil.which("ffmpeg"):
                self.status_updated.emit("FFmpeg 已安装")
                self.progress_updated.emit(100)
                self.finished_signal.emit(True, "FFmpeg 已安装")
                return

            # 创建临时目录
            self.status_updated.emit("正在准备安装文件...")
            self.progress_updated.emit(15)
            temp_dir = tempfile.mkdtemp()
            ffmpeg_zip_path = os.path.join(temp_dir, "ffmpeg.zip")

            # 下载 FFmpeg
            self.status_updated.emit("开始下载FFmpeg...")
            self.progress_updated.emit(20)
            
            # 初始化下载计时
            self._start_time = time.time()
            self._last_update_time = self._start_time
            self._last_size = 0
            self._speed_history = []
            
            # 下载地址
            ffmpeg_urls = [
                "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                "http://oc.lemonlineo.top:54344/d/SA6400/%E8%B5%84%E6%BA%90/2-%E5%AE%89%E8%A3%85%E5%8C%85/exe/ffmpeg-master-latest-win64-gpl.zip?sign=-pW1oSnYvv5gy0cHUR7qsS8exxFzlaDap1oVwZXgGN8=:0",
            ]

            def update_progress(count, block_size, total_size):
                if not self._is_running:
                    raise Exception("下载已取消")
                
                if total_size > 0:
                    downloaded = count * block_size
                    current_time = time.time()
                    
                    # 计算实时网速（每100ms更新一次）
                    if current_time - self._last_update_time >= 0.1:
                        elapsed = current_time - self._last_update_time
                        speed = (downloaded - self._last_size) / elapsed  # B/s
                        
                        # 平滑处理（最近3次平均值）
                        self._speed_history.append(speed)
                        if len(self._speed_history) > 3:
                            self._speed_history.pop(0)
                        avg_speed = sum(self._speed_history) / len(self._speed_history)
                        
                        # 格式化显示
                        downloaded_mb = downloaded / (1024 * 1024)
                        total_mb = total_size / (1024 * 1024)
                        speed_str = self.format_speed(avg_speed)
                        
                        self.status_updated.emit(
                            f"正在下载FFmpeg({downloaded_mb:.1f}MB/{total_mb:.1f}MB) | 速度: {speed_str}"
                        )
                        
                        # 计算进度 (20-80% 用于下载)
                        progress = 20 + int(60 * downloaded / total_size)
                        self.progress_updated.emit(min(progress, 80))
                        
                        self._last_update_time = current_time
                        self._last_size = downloaded

            # 尝试多个下载地址
            download_success = False
            last_error = None

            for url in ffmpeg_urls:
                try:
                    self.status_updated.emit(f"尝试从 {'GitHub' if url == ffmpeg_urls[0] else '国内源'} 下载...")
                    urllib.request.urlretrieve(url, ffmpeg_zip_path, update_progress)
                    download_success = True
                    break
                except Exception as e:
                    last_error = e
                    continue

            if not download_success:
                logging.info(f"所有下载源尝试失败，最后错误: {str(last_error)}")
                raise RuntimeError(f"所有下载源尝试失败，最后错误: {str(last_error)}")

            # 解压文件
            self.status_updated.emit("正在安装文件...")
            self.progress_updated.emit(85)
            
            extracted_dir = r"C:\ffmpeg"
            os.makedirs(extracted_dir, exist_ok=True)
            
            with zipfile.ZipFile(ffmpeg_zip_path, 'r') as zip_ref:
                zip_ref.extractall(extracted_dir)

            # 创建bat文件
            self.status_updated.emit("正在配置环境变量...")
            self.progress_updated.emit(90)
            
            # 使用新的bat文件内容
            bat_content = """@echo off
:: 需要管理员权限
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo 请求管理员权限...
    goto UACPrompt
) else ( goto gotAdmin )

:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    echo UAC.ShellExecute "%~s0", "", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
    if exist "%temp%\getadmin.vbs" ( del "%temp%\getadmin.vbs" )

:: 直接指定要添加的路径（无需手动输入参数）
set "target_path=C:\\ffmpeg\\ffmpeg-master-latest-win64-gpl\\bin"

:: 校验路径是否存在
if not exist "%target_path%" (
    echo 错误：路径不存在 "%target_path%"
    timeout /t 5 /nobreak >nul
    exit /b
)

:: 获取当前系统Path
for /f "tokens=2,*" %%a in ('reg query "HKLM\\System\\CurrentControlSet\\Control\\Session Manager\\Environment" /v Path ^| findstr "Path"') do set "current_path=%%b"

:: 检查是否已存在（防止重复添加）
if "%current_path:C:\\ffmpeg\\ffmpeg-master-latest-win64-gpl\\bin=%" neq "%current_path%" (
    echo 已存在，跳过添加
    echo 窗口将在5秒后自动关闭...
    timeout /t 5 /nobreak >nul
    exit /b
)

:: 添加路径到系统Path
echo 正在将FFmpeg路径添加到系统环境变量...
setx /m Path "%current_path%;%target_path%"

:: 立即刷新环境变量
taskkill /f /im explorer.exe >nul 2>&1
start explorer.exe

:: 保持窗口显示5秒后自动关闭
echo.
echo 添加成功！窗口将在5秒后自动关闭...
timeout /t 5 /nobreak >nul
exit

:: 兼容旧系统的备用方案（当timeout不可用时启用）
:: ping 127.0.0.1 -n 6 >nul
"""
            
            bat_path = os.path.join(temp_dir, "add_to_path.bat")
            with open(bat_path, "w", encoding="gbk") as f:
                f.write(bat_content)

            # 以管理员权限运行bat文件
            self.status_updated.emit("正在请求管理员权限以添加环境变量...")
            self.progress_updated.emit(95)
            
            process = QProcess()
            command = f"""
            $batPath = '{bat_path.replace("'", "''")}'
            try {{
                $process = Start-Process -FilePath cmd.exe -ArgumentList '/c', $batPath -Verb RunAs -Wait -PassThru
                exit $process.ExitCode
            }} catch {{
                Write-Error $_
                exit 1
            }}
            """
            process.start("powershell.exe", ["-Command", command])
            process.waitForFinished(-1)

            exit_code = process.exitCode()
            output = process.readAllStandardOutput().data().decode("gbk", errors="ignore")
            error = process.readAllStandardError().data().decode("gbk", errors="ignore")

            if exit_code == 0:
                self.status_updated.emit("安装成功！")
                self.progress_updated.emit(100)
                self.finished_signal.emit(True, "FFmpeg安装和环境变量配置完成！")
            else:
                error_msg = f"添加环境变量失败 (退出代码: {exit_code})"
                if error.strip():
                    error_msg += f"\n错误信息:\n{error.strip()}"
                raise RuntimeError(error_msg)
            
        except Exception as e:
            self.status_updated.emit(f"安装失败: {str(e)}")
            self.progress_updated.emit(0)
            self.finished_signal.emit(False, str(e))
        finally:
            # 清理临时文件
            if temp_dir:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

    def format_speed(self, speed_bps):
        """格式化网速显示"""
        if speed_bps < 1024:  # <1KB/s
            return f"{speed_bps:.0f} B/s"
        elif speed_bps < 1024 * 1024:  # <1MB/s
            return f"{speed_bps/1024:.1f} KB/s"
        else:
            return f"{speed_bps/(1024 * 1024):.1f} MB/s"

class ImgProcess(QWidget):

    def __init__(self):
        super().__init__()
        self.init_ui()
        ###########设置默认项
        self.settings = QSettings("lemon-o", "ImgProcess")
        # 从设置中获取上次输入的名称和数量
        self.last_folder_name = self.settings.value("last_folder_name", "")
        self.last_num_folders = int(self.settings.value("last_num_folders", "1"))
        self.folder_name_entry.setText(self.last_folder_name)
        self.num_folders_entry.setText(str(self.last_num_folders))
        # 读取 last_input_left，如果没有则默认 ".psd"
        last_input_left = self.settings.value("last_input_left", ".psd", str)
        self.filter_combo.setEditText(last_input_left)  # 设置组合框的初始文本
        self.filter_combo.lineEdit().textChanged.connect(
            lambda text: self.settings.setValue("last_input_left", text)  # 保存用户输入
        )
        #设置默认排序方式
        last_selected_right = self.settings.value("last_selected_right", 0, int)
        self.sort_combo.setCurrentIndex(last_selected_right) 
        self.sort_combo.currentIndexChanged.connect(lambda index: self.settings.setValue("last_selected_right", index) )
        #设置默认窗口大小
        # self.load_window_size()       
        #初始化变量
        self.parent_dir = None
        self.dir_path = None
        self.sub_dir_path = None
        self.file_type = ""
        self.new_position = None
        self.animation = None  # 初始化动画属性
        self.psd_found = False
        self.thread_running = False
        self.video_work_thread_running = False
        self.is_dragging = False
        self.expanded = None
        self.double_clicked = False
        self.monitor_top_border = 0
        self.animation_finished = False
        self.selected_page1 = None
        self.selected_page2 = None
        self.selected_page3 = None
        self.is_ffmpeg_install = None
        # 初始化列表
        self.clicked_folder_path = []  
        self.target_folder_titles = []
        self.clicked_folder_names = []
        self.renamed_folders = []
        self._video_threads = []
        self.init_logging()
        logging.info("程序启动")

        # 创建一个线程实例
        self.thread = Worker(self)
        self.thread.finished_signal.connect(self.thread_finished)
        # self.thread.archiving_thread_start_signal.connect(self.refresh)

    #创建UI界面
    def init_ui(self):
       # 设置界面
        # self.setMinimumSize(650, 450) # 设置最小大小
        # self.setMaximumSize(1080, 1080) # 设置最大大小
        # self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding) # 设置大小策略
        # 窗口始终在最顶层&去除默认标题栏
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        # 获取显示器宽高
        screen = QDesktopWidget().screenGeometry()
        self.screen_height = screen.height()
        self.screen_width = screen.width()
        #设置窗口大小
        if 1000 <= self.screen_height <= 1200:
            self.fixed_height = 430
            self.fixed_width = 600
        elif 1300 <= self.screen_height <= 1500:
            self.fixed_height = 500
            self.fixed_width = 680
        elif 2000 <= self.screen_height <= 2200:
            self.fixed_height = 700
            self.fixed_width = 1000
        else:
            if self.screen_height > self.screen_width:
                if 1000 <= self.screen_width <= 1200:
                    self.fixed_height = 430
                    self.fixed_width = 600
                elif 1300 <= self.screen_width <= 1500:
                    self.fixed_height = 500
                    self.fixed_width = 680
                elif 2000 <= self.screen_width <= 2200:
                    self.fixed_height = 700
                    self.fixed_width = 1000 
            else:
                self.fixed_height = int((45 / 108) * screen.height())
                self.fixed_width = int((65 / 192) * screen.width())  
        self.setGeometry(100, 100, self.fixed_width, self.fixed_height)
        # 窗口默认居中
        size = self.geometry()
        x = int((screen.width() - size.width()) / 2)
        y = int((screen.height() - size.height()) / 2)
        self.move(x, y)
        #设置缩进边距这样才能绘制窗口投影
        self.margin = round((5 / 430) * self.fixed_height)
        #设置窗口图标
        self.setWindowIcon(QIcon('./icon/ImgProcess.ico'))
        
         # 创建堆叠小部件
        self.stackedWidget = QStackedWidget(self)  
         # 连接currentChanged信号到槽函数
        self.stackedWidget.currentChanged.connect(self.update_window_size) 

        #创建自定义标题栏和dock栏 ############################################################
        self.title_label = QLabel('ImgProcess')
        self.title_label.setStyleSheet('color: #ffffff;')

        button_width = int((25 / 650) * self.fixed_width)
        button_height = int((25 / 450) * self.fixed_height)
        button_width_close = int((35 / 650) * self.fixed_width)
        button_height_close = int((25 / 450) * self.fixed_height)
        self.button_width_dock =  int((4 / 90) * self.fixed_width)
        self.button_height_dock = int((4 / 90) * self.fixed_width)
        button_style_close = """
        QPushButton {
            color: #ffffff;
            border: 0px;
        }

        QPushButton:hover {
            background-color: #f55b31;
            border: 0px;
        }
        """
        button_style_top = """
        QPushButton {
            color: #ffffff;
            border: 0px;
        }

        QPushButton:hover {
            background-color: #2c2c2c;
            border: 0px;
        }
        """
        button_style_dock = """
            QPushButton {
                color: #ffffff; /* 未点击按钮的普通样式 */
                border: 0px;
            }

            QPushButton:checked {
                background-color: #ffffff; /* 已点击按钮的普通样式 */
                border-radius: 3%; 
                border: 0px;
            }

            QPushButton:hover {
                background-color: #dedfe0; /* 未点击按钮的hover样式 */
                border-radius: 3%;
                border: 0px;
            }
            QPushButton:checked:hover { 
                background-color: #ffffff;  /* 已点击按钮的hover样式 */
                border-radius: 3%; 
                border: 0px;
            }
        """

        self.normal_style = """
        QPushButton {
            color: #ffffff;
            border: 0px;
        }
        """
        self.hover_style = """
        QPushButton:hover {
            background-color: #dedfe0;
            border-radius: 3%;
            border: 0px;
        }
        """


        self.main_icon = QPushButton()
        self.main_icon.setFixedSize(button_width, button_height)
        self.main_icon.setStyleSheet("border: 0px solid white;")
        self.main_icon.setIcon(QIcon('./icon/ImgProcess.ico')) 

        self.github_button = QPushButton()
        self.github_button.setFixedSize(button_width, button_height)
        self.github_button.setStyleSheet(button_style_top)
        self.github_button.setIcon(QIcon('./icon/github.ico'))  
        self.github_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/lemon-o/ImgProcess")))

        self.minimize_button = QPushButton()
        self.minimize_button.setFixedSize(button_width, button_height)
        self.minimize_button.setStyleSheet(button_style_top)
        self.minimize_button.setIcon(QIcon('./icon/minimize.ico'))  
        self.minimize_button.clicked.connect(self.showMinimized)  # 点击按钮最小化窗口

        self.close_button = QPushButton()
        self.close_button.setFixedSize(button_width_close, button_height_close)
        self.close_button.setStyleSheet(button_style_close)
        self.close_button.setIcon(QIcon('./icon/close.ico'))  
        self.close_button.clicked.connect(self.close)  # 点击关闭按钮关闭窗口

        #创建左侧dock
        self.dock_button_1 = QPushButton()
        self.setup_button(self.dock_button_1, 0, button_style_dock)
        self.dock_button_1.setIcon(QIcon('./icon/GSfolders.ico'))  

        self.dock_button_2 = QPushButton()
        self.setup_button(self.dock_button_2, 1, button_style_dock)
        self.dock_button_2.setIcon(QIcon('./icon/FoldersFilter.ico'))  
        self.dock_button_2.setChecked(True) #默认选择第二个按钮

        self.dock_button_3 = QPushButton()
        self.setup_button(self.dock_button_3, 2, button_style_dock)
        self.dock_button_3.setIcon(QIcon('./icon/Cmingoz.ico'))  

        # 设置菜单按钮（不绑定样式和页面切换）
        self.dock_button_menu = QPushButton()
        self.setup_button(self.dock_button_menu, -1, self.normal_style , is_menu_button=True)
        self.dock_button_menu.setIcon(QIcon('./icon/menu.png'))  
        # self.dock_button_menu.clicked.connect(self.show_menu) # 单独绑定菜单点击事件

        # 安装事件过滤器并开启鼠标跟踪
        self.dock_button_menu.setMouseTracking(True)
        self.dock_button_menu.installEventFilter(self)

        self.menu = QMenu(self)
        #让菜单超出主窗口也显示圆角
        self.menu.setWindowFlags(self.menu.windowFlags() | Qt.FramelessWindowHint)
        self.menu.setAttribute(Qt.WA_TranslucentBackground)
        # 基础样式
        self.menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 13px;
            }

            /* 普通状态 */
            QMenu::item {
                padding-left: 3px;   /* 靠左显示 */
                padding-right: 12px;   
                padding-top: 2px;
                padding-bottom: 2px;
                margin: 3px 5px;
                color: #3b3b3b;
            }

            /* 悬停状态：保持一致的 padding/margin，防止文字抖动 */
            QMenu::item:selected {
                background-color: #dedfe0;
                border-radius: 4px;
                padding-left: 3px;
                padding-right: 12px;
                padding-top: 2px;
                padding-bottom: 2px;
                margin: 3px 5px;
                color: #3b3b3b;
            }
        """)

        # 添加菜单项
        self.menu.addAction("查看日志").triggered.connect(self.show_log)
        self.menu.addAction("检查更新").triggered.connect(self.check_update)

        # 安装事件过滤器并开启鼠标跟踪
        self.menu.setMouseTracking(True)
        self.menu.installEventFilter(self)

        # 连接 QMenu 的 triggered 信号
        self.menu.triggered.connect(self._on_menu_triggered)

        # leave_timer：当鼠标完全移出（按钮和菜单区域都不在时），延迟隐藏菜单
        self.leave_timer = QTimer(self)
        self.leave_timer.setSingleShot(True)
        self.leave_timer.timeout.connect(self._try_hide)

        # click_block_timer：短暂屏蔽“菜单立即重现”的定时器（200ms 后重置 just_clicked）
        self.click_block_timer = QTimer(self)
        self.click_block_timer.setSingleShot(True)
        self.click_block_timer.timeout.connect(self._reset_just_clicked)

        # 点击菜单项后短暂禁止重新弹出的标志
        self.just_clicked = False

        # 在点击菜单项时，除了短时屏蔽 show_menu，还需要永久“去除”对菜单区域的识别，
        # 直到下一次按钮被移入才恢复。用下面这个标志来控制：
        self.ignore_menu_area = False

        # 上面是自定义标题栏和dock栏 ############################################################


        # 创建GSfolders界面 ############################################################
        # 创建标签1
        self.folder_name_label = QLabel('名称')
        self.folder_name_label.setStyleSheet('color: #3b3b3b; margin-top: 5px; margin-bottom: 0px;')
        # 创建标签2
        self.folder_num_label = QLabel('数量')
        self.folder_num_label.setStyleSheet('color: #3b3b3b; margin-top: 5px; margin-bottom: 0px;')
        #创建输入框
        linedit_style_1 = 'background-color: white; color: #272727; border-radius: 6px; border: 1px solid #C5C5C5;'
        linedit_height_1 = int((30 / 450) * self.fixed_height)
        self.num_folders_entry = QLineEdit()
        self.num_folders_entry.setFixedHeight(linedit_height_1)
        self.num_folders_entry.setPlaceholderText("输入文件夹数量")
        self.num_folders_entry.setStyleSheet(linedit_style_1)
        self.folder_name_entry = QLineEdit()
        self.folder_name_entry.setFixedHeight(linedit_height_1)
        self.folder_name_entry.setPlaceholderText("输入文件夹名称")
        self.folder_name_entry.setStyleSheet(linedit_style_1)
        #创建按钮
        button_height_build = int((30 / 450) * self.fixed_height)
        button_style_build = """
        QPushButton {
            background-color: #f5f5f5;
            color: #3b3b3b;
            border-radius: 6%; /* 圆角半径使用相对单位，可以根据需要调整 */
            border: 1px solid #f5f5f5;
        }

        QPushButton:hover {
            background-color: #0773fc;
            color: #ffffff;
            border: 0.1em solid #0773fc; /* em为相对单位 */
        }
        """
        self.select_path_button = QPushButton("创建文件夹")
        self.select_path_button.setFixedHeight(button_height_build)
        self.select_path_button.setStyleSheet(button_style_build)
        self.select_path_button.clicked.connect(self.select_path)

        # 创建子界面布局管理器
        self.GSfolders_page = QWidget()  

        #创建水平布局管理器
        hbox_name = QHBoxLayout()
        hbox_name.addWidget(self.folder_name_label)
        hbox_name.addWidget(self.folder_name_entry)
        hbox_num = QHBoxLayout()
        hbox_num.addWidget(self.folder_num_label)
        hbox_num.addWidget(self.num_folders_entry)

        # 创建主窗口的垂直布局管理器
        vbox_main1 = QVBoxLayout(self.GSfolders_page)
        vbox_main1.addLayout(hbox_name)
        vbox_main1.addLayout(hbox_num)  
        vbox_main1.addWidget(self.select_path_button)  
        vbox_main1.addSpacing(15)

        # 将界面添加到堆叠小部件中
        self.stackedWidget.addWidget(self.GSfolders_page)
        # 上面是GSfolders界面 ############################################################


        # 创建FoldersFilter界面 ############################################################
        #创建按钮
        button_height1 = int((30 / 450) * self.fixed_height)
        button_style = """
        QPushButton {
            background-color: #f5f5f5;
            color: #3b3b3b;
            border-radius: 6%; /* 圆角半径使用相对单位，可以根据需要调整 */
            border: 1px solid #f5f5f5;
        }

        QPushButton:hover {
            background-color: #0773fc;
            color: #ffffff;
            border: 0.1em solid #0773fc; /* em为相对单位 */
        }
        """

        self.folder_button = QPushButton('选择文件夹', self)
        self.folder_button.setFixedHeight(button_height1)
        self.folder_button.setStyleSheet(button_style)
        self.folder_button.clicked.connect(self.select_folder)

        self.reset_button = QPushButton('清空列表', self)
        self.reset_button.setFixedHeight(button_height1)
        self.reset_button.setStyleSheet(button_style)
        self.reset_button.clicked.connect(self.reset)

        self.refresh_button = QPushButton('刷新列表', self)
        self.refresh_button.setFixedHeight(button_height1)
        self.refresh_button.setStyleSheet(button_style)
        self.refresh_button.clicked.connect(self.refresh)

        # 创建标签1
        self.folder_label = QLabel('已选择的文件夹')
        self.folder_label.setStyleSheet('color: #3b3b3b; margin-top: 5px; margin-bottom: 0px;')

        #创建下拉框
        combo_width = int((85 / 650) * self.fixed_width)
        combo_height = int((30 / 450) * self.fixed_height)
        combo_style_1 = 'QComboBox { color: #3b3b3b; border: 1px solid #C5C5C5; border-radius: 4%; margin-top: 10px; padding-left:20px;} QComboBox::drop-down {  background-color: #C5C5C5; border: none; }'        
        combo_style_2 = 'QComboBox { color: #3b3b3b; border: 1px solid #C5C5C5; border-radius: 4%; margin-top: 10px; padding-left:20px;} QComboBox::drop-down {  background-color: #C5C5C5; border: none; }'                

        self.filter_combo = QComboBox() # 文件类型选择
        self.filter_combo.setFixedSize(combo_width, combo_height)
        self.filter_combo.setStyleSheet(combo_style_1)
        self.filter_combo.setEditable(True)
        self.file_type = []
        self.filter_combo.activated.connect(self.select_folder)
        
        self.sort_combo = QComboBox()#排序选择
        self.sort_combo.setFixedSize(combo_width, combo_height)
        self.sort_combo.setStyleSheet(combo_style_2)
        sort_options = ["升序", "降序"]
        for option in sort_options:
            self.sort_combo.addItem(option)
        self.sort_combo.activated.connect(self.folders_sort)

        #创建标签2
        label_style_3 = 'color: #3b3b3b; margin-top: 10px; margin-bottom: 0px; margin-left: 0px;'
        label_style_4 = 'color: #3b3b3b; margin-top: 10px; margin-bottom: 0px; margin-left: 0px;'

        self.folder_type_label = QLabel('文件筛选类型：')
        self.folder_type_label.setStyleSheet(label_style_3)     
        self.folder_sort_label = QLabel('列表排序方式：')
        self.folder_sort_label.setStyleSheet(label_style_4)

        #创建标签3
        label_style_1 = 'color: #3b3b3b; margin-top: 0px; margin-bottom: 0px;'
        label_style_2 = 'color: #3b3b3b; margin-top: 0px; margin-bottom: 0px; margin-left: 0px;color: #B6A338;'

        self.folder_left_label = QLabel('不含')
        self.folder_left_label.setStyleSheet(label_style_1)
        self.folder_left_num_label = QLabel()
        self.folder_left_num_label.setStyleSheet(label_style_2)       
        self.folder_right_label = QLabel('含有')
        self.folder_right_label.setStyleSheet(label_style_1)
        self.folder_right_num_label = QLabel()
        self.folder_right_num_label.setStyleSheet(label_style_2)

        # 创建列表
        list_style = 'background-color: white; color: #272727; border-radius: 6%; border: 1px solid #C5C5C5;'
        self.file_left_list = QListWidget()
        self.file_left_list.setStyleSheet(list_style)
        self.file_right_list = QListWidget()
        self.file_right_list.setStyleSheet(list_style)
        self.file_filter_folders_list = QListWidget()
        self.file_filter_folders_list.setStyleSheet(list_style)

        # 创建一个定时器对象
        self.timer = QTimer()
        self.countdown_label = QLabel(self)
        self.countdown_label.setText("90 秒后自动归档")
        self.countdown_label.setStyleSheet("color: #3b3b3b; margin-top: 10px; margin-bottom: 0px; margin-left: 0px; color: rgba(0, 0, 0, 0.1);")

        #创建进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)   
        self.progress_bar.setMaximum(100)
        self.progress_bar.setRange(0, 100)    
        self.progress_bar.setValue(self.progress_bar.minimum())
        self.progress_bar.setStyleSheet("QProgressBar {color: transparent;border: 1px solid #F0F0F0 ;border-radius: 4% ;text-align: center;} QProgressBar::chunk {background-color: #51B163;border-radius: 2% ;}")
        bar_height = int((10 / 450) * self.fixed_height)
        self.progress_bar.setFixedHeight(bar_height) # 设置进度条的高度

        # 创建水平布局管理器
        hbox1_left = QHBoxLayout()
        hbox1_left.addWidget(self.folder_button)
        hbox2_left = QHBoxLayout()
        hbox2_left.addWidget(self.reset_button)
        hbox2_left.addWidget(self.refresh_button)
        hbox3_left = QHBoxLayout()
        hbox3_left.addWidget(self.folder_label)
        hbox4_left = QHBoxLayout() # 筛选的文件夹显示框
        hbox4_left.addWidget(self.file_filter_folders_list)
        hbox5_left = QHBoxLayout()
        hbox5_left.addWidget(self.folder_type_label)
        hbox5_left.addWidget(self.filter_combo)
        hbox6_left = QHBoxLayout()
        hbox6_left.addWidget(self.folder_sort_label)
        hbox6_left.addWidget(self.sort_combo)
        hbox7_left = QHBoxLayout()
        hbox7_left.addWidget(self.countdown_label)
        hbox1_right = QHBoxLayout()
        hbox1_right.addWidget(self.folder_left_label)
        hbox1_right.addWidget(self.folder_left_num_label)
        hbox1_right.addWidget(self.folder_right_label)
        hbox1_right.addWidget(self.folder_right_num_label)
        hbox2_right = QHBoxLayout()
        hbox2_right.addWidget(self.file_left_list)
        hbox2_right.addWidget(self.file_right_list)
        hbox3_right = QHBoxLayout()
        hbox3_right.addWidget(self.progress_bar)

        # 创建垂直布局管理器
        vbox1_Pack = QWidget()  
        new_pack_width = int((190 / 650) * self.fixed_width) # 设置 容器 的宽度
        vbox1_Pack.setFixedWidth(new_pack_width)
        vbox1_Pack.setContentsMargins(0, 0, 0, 0)  # 调整边距
        vbox1 = QVBoxLayout(vbox1_Pack)
        vbox1.setContentsMargins(0, 0, 0, 0)  # 调整边距
        vbox1.addSpacing(20) # 添加（）像素的空白占位
        vbox1.addLayout(hbox1_left)
        vbox1.addSpacing(5) # 添加（）像素的空白占位
        vbox1.addLayout(hbox2_left)
        vbox1.addSpacing(15) # 添加（）像素的空白占位
        vbox1.addLayout(hbox3_left)
        vbox1.addLayout(hbox4_left)
        vbox1.addSpacing(15) # 添加（）像素的空白占位
        vbox1.addLayout(hbox5_left)
        vbox1.addLayout(hbox6_left)
        vbox1.addLayout(hbox7_left)
        vbox1.addSpacing(25) # 添加（）像素的空白占位
        vbox2 = QVBoxLayout()
        vbox2.addSpacing(0) # 添加（）像素的空白占位
        vbox2.addLayout(hbox1_right)
        vbox2.addLayout(hbox2_right)
        vbox2.addLayout(hbox3_right)
        vbox2.addSpacing(10) # 添加（）像素的空白占位
            
        # 创建子界面布局管理器
        self.FoldersFilter_page = QWidget()  
        # 创建水平布局管理器
        hbox_main_page2 = QHBoxLayout(self.FoldersFilter_page)
        hbox_main_page2.addWidget(vbox1_Pack)
        hbox_main_page2.addSpacing(26) # 添加（）像素的空白占位                                                                                                                                                                                                                                                                                                                                                   
        hbox_main_page2.addLayout(vbox2) 

        self.stackedWidget.addWidget(self.FoldersFilter_page) # 将布局放进小部件   
        # 上面是FoldersFilter界面 #############################################################


        # 创建Cmingoz界面 #############################################################
        linedit_style_3 = 'background-color: white; color: #272727; border-radius: 6px; border: 1px solid #C5C5C5;'
        linedit_height_3 = int((30 / 450) * self.fixed_height)

        self.cm_input = QLineEdit()
        self.cm_input.setStyleSheet(linedit_style_3)
        self.cm_input.setFixedHeight(linedit_height_3)
        validator1 = QRegExpValidator(QRegExp(r'^[0-9]+(\.[0-9]+)?$'))
        self.cm_input.setValidator(validator1)
        self.in_input = QLineEdit()
        self.in_input.setStyleSheet(linedit_style_3)
        self.in_input.setFixedHeight(linedit_height_3)
        validator2 = QRegExpValidator(QRegExp(r'^[0-9]+(\.[0-9]+)?$'))
        self.in_input.setValidator(validator2)        
        self.g_input = QLineEdit()
        self.g_input.setStyleSheet(linedit_style_3)
        self.g_input.setFixedHeight(linedit_height_3)
        validator3 = QRegExpValidator(QRegExp(r'^[0-9]+(\.[0-9]+)?$'))
        self.g_input.setValidator(validator3)
        self.oz_input = QLineEdit()
        self.oz_input.setStyleSheet(linedit_style_3)
        self.oz_input.setFixedHeight(linedit_height_3)
        validator4 = QRegExpValidator(QRegExp(r'^[0-9]+(\.[0-9]+)?$'))
        self.oz_input.setValidator(validator4)

        label_style_1 = 'color: #3B3E41; margin-top: 0px; margin-bottom: 0px;'
        self.cm_label = QLabel("厘米")
        self.cm_label.setStyleSheet(label_style_1)
        self.equal2 = QLabel("=")
        self.equal2.setStyleSheet(label_style_1)
        self.in_label = QLabel("英寸")
        self.in_label.setStyleSheet(label_style_1)
        self.goz_result = QLabel()
        self.goz_result.setStyleSheet(label_style_1)
        self.g_label = QLabel("克")
        self.g_label.setStyleSheet(label_style_1)
        self.equal = QLabel("=")
        self.equal.setStyleSheet(label_style_1)
        self.oz_label = QLabel("盎司")
        self.oz_label.setStyleSheet(label_style_1)
        self.cmin_result = QLabel()
        self.cmin_result.setStyleSheet(label_style_1)

        #创建按钮
        button_width_copy = int((90 / 650) * self.fixed_width)
        button_height_copy = int((30 / 450) * self.fixed_height)
        button_style_copy = """
        QPushButton {
            background-color: #f5f5f5;
            color: #3b3b3b;
            border-radius: 6%; /* 圆角半径使用相对单位，可以根据需要调整 */
            border: 1px solid #f5f5f5;
        }

        QPushButton:hover {
            background-color: #0773fc;
            color: #ffffff;
            border: 0.1em solid #0773fc; /* em为相对单位 */
        }
        """
        self.inch_copy_button = QPushButton("复制结果F1")
        self.inch_copy_button.setStyleSheet(button_style_copy)
        self.inch_copy_button.setFixedSize(button_width_copy, button_height_copy)
        self.ounce_copy_button = QPushButton("复制结果F2")
        self.ounce_copy_button.setStyleSheet(button_style_copy)
        self.ounce_copy_button.setFixedSize(button_width_copy, button_height_copy)

        self.convert_cm_to_inch()
        self.convert_inch_to_cm()
        self.convert_g_to_ounce()
        self.convert_ounce_to_g()

        self.cm_input.textChanged.connect(self.convert_cm_to_inch)
        self.in_input.textChanged.connect(self.convert_inch_to_cm)
        self.g_input.textChanged.connect(self.convert_g_to_ounce)
        self.oz_input.textChanged.connect(self.convert_ounce_to_g)

        self.inch_copy_button.clicked.connect(self.copy_cmin_result)
        self.ounce_copy_button.clicked.connect(self.copy_goz_result)

        # 创建布局管理器
        inch_layout = QHBoxLayout()
        inch_layout.addWidget(self.cmin_result)
        inch_layout.addSpacing(10)
        inch_layout.addWidget(self.inch_copy_button)

        inch2_layout = QHBoxLayout()
        inch2_layout.addWidget(self.cm_input)
        inch2_layout.addWidget(self.cm_label)
        inch2_layout.addWidget(self.equal)
        inch2_layout.addWidget(self.in_input)
        inch2_layout.addWidget(self.in_label)

        ounce_layout = QHBoxLayout()
        ounce_layout.addWidget(self.goz_result)
        ounce_layout.addSpacing(0)
        ounce_layout.addWidget(self.ounce_copy_button)

        ounce2_layout = QHBoxLayout()
        ounce2_layout.addWidget(self.g_input)
        ounce2_layout.addWidget(self.g_label)
        ounce2_layout.addWidget(self.equal2)
        ounce2_layout.addWidget(self.oz_input)
        ounce2_layout.addWidget(self.oz_label)
        
        # 创建子界面布局管理器
        self.Cmingoz_page = QWidget()   
        main_page3 = QVBoxLayout(self.Cmingoz_page)
        main_page3.addSpacing(12)
        main_page3.addLayout(inch2_layout)
        main_page3.addLayout(inch_layout)
        main_page3.addSpacing(36)
        main_page3.addLayout(ounce2_layout)
        main_page3.addLayout(ounce_layout)
        main_page3.addSpacing(12)

        # 将界面添加到堆叠小部件中
        self.stackedWidget.addWidget(self.Cmingoz_page)

        self.shortcut_return = QShortcut(QKeySequence(Qt.Key_F1), self)
        self.shortcut_return.activated.connect(self.copy_cmin_result)
        self.shortcut_return = QShortcut(QKeySequence(Qt.Key_F2), self)
        self.shortcut_return.activated.connect(self.copy_goz_result)
        # 上面是Cmingoz界面 ############################################################  


        # 创建自定义标题栏水平布局管理器
        hbox_top = QHBoxLayout()
        hbox_top.setContentsMargins(0, 0, 0, 0)  # 去除边距
        hbox_top.setSpacing(0)  # 设置控件之间的间距为0
        hbox_top.addSpacing(self.margin) # 添加（）像素的空白占位
        hbox_top.addWidget(self.main_icon)
        hbox_top.addWidget(self.title_label)
        hbox_top.addStretch(1)
        hbox_top.addWidget(self.github_button)
        hbox_top.addWidget(self.minimize_button)
        hbox_top.addWidget(self.close_button)
        hbox_top.addSpacing(self.margin)

        # 创建dock和主窗口水平布局管理器
        hbox_main = QHBoxLayout()
        hbox_main.addSpacing(self.margin)  # 添加左边距
        vbox_dock_widget = QWidget()  # 创建一个新容器
        new_width1 = int((5 / 90) * self.fixed_width)  # 设置容器的宽度
        vbox_dock_widget.setFixedWidth(new_width1)
        vbox_dock = QVBoxLayout(vbox_dock_widget)
        left_margin = int(((5 / 90) * self.fixed_width - self.button_width_dock) // 2)
        vbox_dock.setContentsMargins(left_margin, 0, 0, 0)  # 调整边距
        vbox_dock.setSpacing(0)  # 设置控件之间的间距为0
        # 先添加前三个按钮
        vbox_dock.addWidget(self.dock_button_1)  
        vbox_dock.addSpacing(5)
        vbox_dock.addWidget(self.dock_button_2) 
        vbox_dock.addSpacing(5)
        vbox_dock.addWidget(self.dock_button_3) 
        vbox_dock.addSpacing(5)
        # 添加弹性空间，把菜单按钮推到底部
        vbox_dock.addStretch(1)  
        # 最后添加菜单按钮，并在底部留 5px 间距
        vbox_dock.addWidget(self.dock_button_menu) 
        vbox_dock.addSpacing(10)  # 底部间距

        ##### 上面是dock部分 #######
        hbox_main.addWidget(vbox_dock_widget) 
        hbox_main.addWidget(self.stackedWidget) 
        hbox_main.addSpacing(10) 

        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)  # 去除边距
        main_layout.addSpacing(self.margin) # 添加（）像素的空白占位
        main_layout.addLayout(hbox_top)
        main_layout.addLayout(hbox_main)    
        self.setLayout(main_layout) # 将main_layout贴在父窗口上
        self.stackedWidget.setCurrentIndex(1) # 初始页面为page2
        # 设置窗口背景透明
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 创建垂直分隔线添加到page2
        self.vline = QFrame(self.FoldersFilter_page)
        self.vline.setFrameShape(QFrame.VLine)
        vline_x = int((217 / 650) * self.fixed_width) # 设置垂直分隔线的位置
        vline_y = 0 # 设置垂直分隔线的位置        
        self.vline.setGeometry(x, self.margin, 1, self.height())
        margin_top_value = self.margin
        margin_bottom_value = self.margin
        self.vline.setStyleSheet("border: 1px solid #C5C5C5; margin-top: {}px; margin-bottom: {}px;".format(margin_top_value, margin_bottom_value))
        self.vline.setGeometry(vline_x, vline_y, 1, self.fixed_height - 9*self.margin)
        
        # 创建垂直分隔线添加到page3
        self.hline = QFrame(self.Cmingoz_page)
        self.hline.setFrameShape(QFrame.HLine) 
        vline_y = int((150 / 650) * self.fixed_height)  # 设置水平分隔线的位置
        self.hline.setGeometry(0, vline_y, self.fixed_width - 9*self.margin, 1) 
        self.hline.setStyleSheet("border: 1px solid #C5C5C5;")

    # 切换不同的窗口大小和设置绘制标记
    def update_window_size(self, index):
        if index == 0:
            self.change_width = int((250 / 600) * self.fixed_width)
            self.change_height = int((200 / 430) * self.fixed_height)
            self.setFixedSize(self.change_width, self.change_height)
            self.selected_page1 = True
        elif index == 1:
            self.change_width = int((600 / 600) * self.fixed_width)
            self.change_height = int((430 / 430) * self.fixed_height)
            self.setFixedSize(self.change_width, self.change_height)
            self.selected_page2 = True
        if index == 2:
            self.change_width = int((350/ 600) * self.fixed_width)
            self.change_height = int((235 / 430) * self.fixed_height)
            self.setFixedSize(self.change_width, self.change_height)
            self.selected_page3 = True

    # 设置dock按钮
    def setup_button(self, button, index, style, is_menu_button=False):
        button.setFixedSize(self.button_width_dock, self.button_height_dock)
        button.setStyleSheet(style)
        button.setCheckable(True)
        
        # 如果是菜单按钮，不绑定 set_button_selected 和 stackedWidget 切换
        if not is_menu_button:
            button.clicked.connect(lambda: self.set_button_selected(index))
            button.clicked.connect(lambda: self.stackedWidget.setCurrentIndex(index))

    def set_button_selected(self, index):
        # 获取所有需要管理的按钮（排除菜单按钮）
        managed_buttons = [
            self.dock_button_1,
            self.dock_button_2,
            self.dock_button_3
            # 可以继续添加其他需要管理的按钮
        ]
        
        # 重置所有 managed_buttons 的选中状态
        for btn in managed_buttons:
            btn.setChecked(False)
        
        # 设置当前点击的按钮为选中状态
        sender_button = self.sender()
        if sender_button in managed_buttons:  # 确保是受管理的按钮
            sender_button.setChecked(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # 开启抗锯齿
        rect_color = QColor(7, 115, 252)
        corner_radius_percentage = 2
        # 计算相对单位的圆角大小
        rect = self.rect()
        corner_radius = min(rect.width(), rect.height()) * corner_radius_percentage / 100.0
        if self.animation_finished:
            #绘制一个圆角矩形用于触发下拉效果
            painter.setBrush(rect_color)
            painter.setPen(Qt.NoPen)
            width = self.width() // 5
            x = (self.width() - width) // 2
            painter.drawRoundedRect(x, 0, width, self.height(), corner_radius, corner_radius)
        else:  
            # 画多个矩形透明度渐变实现羽化边缘效果
            for i in range(self.margin):
                # 透明度从0开始递增
                alpha = i * self.margin
                shade_level = self.margin // 4
                brush_color = QColor(0, 0, 0, alpha)
                painter.setBrush(QBrush(brush_color))
                # 禁用描边
                painter.setPen(Qt.NoPen)
                rect = self.rect().adjusted(i * shade_level, i * shade_level, -i * shade_level, -i * shade_level)
                painter.drawRect(rect)
        # 绘制主窗口背景
        painter.fillRect(self.margin, self.margin, self.width() - 2 * self.margin, self.height() - 2 * self.margin, QColor(255, 255, 255))
        # 在窗口左侧添加纵向遮罩
        self.mask_width = int((5 / 90) * self.fixed_width)
        painter.fillRect(self.margin, self.margin, self.mask_width, self.height() - 2 * self.margin, QColor(239, 242, 246))
        # 在窗口顶部添加横向遮罩
        self.mask_height = int((5 / 90) * self.fixed_height)
        painter.fillRect(self.margin, self.margin, self.width() - 2 * self.margin, self.mask_height, QColor(0, 0, 0))      
      
    # 获取显示器边界信息
    def update_screen_info(self):
        # 保存 QDesktopWidget 的实例
        self.desktop_widget = QDesktopWidget()
        # 获取主窗口所在的屏幕索引
        screen_number = self.desktop_widget.screenNumber(self)
        # 获取主窗口所在屏幕的信息
        screen = self.desktop_widget.screen(screen_number)
        screen_geometry = screen.geometry()
        self.monitor_top_border = screen_geometry.y()
    #让自定义标题栏可以拖动主窗口
    def mousePressEvent(self, event):
        # 处理鼠标按下事件
        if event.button() == Qt.LeftButton and event.y() < self.mask_height + self.margin:
            self.is_dragging = True
            self.offset = event.pos()
    def mouseMoveEvent(self, event):
        # 处理鼠标移动事件
        if self.is_dragging:
            old_position = self.pos()  # 保存当前位置
            self.new_position = self.mapToParent(event.pos() - self.offset)
            if self.new_position == old_position:  # 检查新位置是否等于原位置
                return
            self.update_screen_info()
            # 确保y不超过显示器上边界
            if self.new_position.y() < self.monitor_top_border - self.margin:
                self.new_position.setY(self.monitor_top_border - self.margin)
            self.move(self.new_position)
    def mouseReleaseEvent(self, event):
        # 处理鼠标释放事件
        if self.is_dragging:
            if event.button() == Qt.LeftButton:
                # 添加对y是否等于显示器上边界的检测触发隐藏窗口效果
                if self.new_position is not None and self.new_position.y() == self.monitor_top_border - self.margin:
                    self.up_move_window()
                    self.expanded = False
                else:
                    self.expanded = None
                self.is_dragging = False
    #实现窗口隐藏显示的效果
    def enterEvent(self, event):
        #鼠标进入窗口区域
        if not self.expanded and self.y() == round(self.monitor_top_border - (994/1000) * self.change_height):
            self.down_move_window()
            self.expanded = True
    def leaveEvent(self, event):
        #鼠标离开窗口区域
        if self.expanded and self.y() == self.monitor_top_border - self.margin:
            if not self.double_clicked:       
                if not self.underMouse() and self.expanded:
                    self.up_move_window()
                    self.expanded = False
    #主窗口移动动画
    def up_move_window(self):
        if self.animation is None or self.animation.state() == QPropertyAnimation.Stopped:
            self.animation = QPropertyAnimation(self, b'geometry')
            self.animation.setDuration(300)
            self.animation.setStartValue(QRect(self.geometry()))
            # 使用round()处理舍入误差问题
            new_y = round(self.geometry().y() - (994/1000) * self.change_height + self.margin)
            self.animation.setEndValue(QRect(
                self.geometry().x(),
                new_y,
                self.geometry().width(),
                self.geometry().height()
            ))
            self.animation.finished.connect(self.animation_finished_work)
            self.animation.start()
    def down_move_window(self):
        if self.animation is None or self.animation.state() == QPropertyAnimation.Stopped:
            self.animation = QPropertyAnimation(self, b'geometry')
            self.animation.setDuration(300)
            self.animation.setStartValue(QRect(self.geometry()))
            # 使用round()处理舍入误差问题
            new_y = round(self.geometry().y() + (994/1000) * self.change_height - self.margin)
            self.animation.setEndValue(QRect(
                self.geometry().x(),
                new_y,
                self.geometry().width(),
                self.geometry().height()
            ))
            self.animation_finished = False
            self.update()
            self.animation.start()
    def animation_finished_work(self):
        self.animation_finished = True
        self.update()

    #倒计时自动执行
    def update_countdown(self):
        self.remaining_time -= 1
        if self.remaining_time <= 0:
            self.auto_archiving()
            # 重置倒计时时间
            self.remaining_time = 90
            self.countdown_label.setText(f"{self.remaining_time} 秒后自动归档")
        else:
            self.countdown_label.setText(f"{self.remaining_time} 秒后自动归档")
    
    ###########以下是dock区菜单按钮函数

    def _on_menu_triggered(self, action):
        """
        只要菜单有一项被点击，就会调用这个槽。
        1. 把 just_clicked 置为 True，短时（200ms）内不允许重新弹出。
        2. 同时把 ignore_menu_area 置为 True，直到下一次真正从按钮区触发 show_menu 才将其重置为 False。
        """
        # 屏蔽短时重新弹出
        self.just_clicked = True
        if self.click_block_timer.isActive():
            self.click_block_timer.stop()
        self.click_block_timer.start(200)

        # 去除对菜单区域的识别，直到下一次 show_menu（从按钮触发）时再恢复
        self.ignore_menu_area = True
        # 菜单和菜单项重置为初始状态
        self._hide_menu_and_reset()

    def _reset_just_clicked(self):
        """200ms 后自动把 just_clicked 置回 False"""
        self.just_clicked = False

    def show_menu(self):

        # 菜单已经可见时，只停止隐藏定时器，不重复弹出
        if self.menu.isVisible():
            self.leave_timer.stop()
            return

        # “从按钮重新打开菜单”，此时恢复识别菜单区域
        self.ignore_menu_area = False
        # 取消任何待执行的隐藏操作
        self.leave_timer.stop()
        # 把按钮样式改为 hover 样式
        self.dock_button_menu.setStyleSheet(self.hover_style)

        # 计算菜单位置
        button_rect = self.dock_button_menu.rect()
        button_pos = self.dock_button_menu.mapToGlobal(QPoint(0, 0))

        
        # 确保菜单已经布局完成，能获取正确高度
        self.menu.adjustSize()
        
        # 计算位置：
        menu_x = button_pos.x() + button_rect.width() + 10
        menu_y = button_pos.y() + button_rect.height()/2 - self.menu.sizeHint().height()/2
        
        # 显示菜单
        self.menu.exec_(QPoint(int(menu_x), int(menu_y)))

    def eventFilter(self, obj, event):
        """
        重写的事件过滤器：只关心鼠标相关的 Enter/Leave/MouseMove/HoverMove 事件
        根据 ignore_menu_area 标志，在两个模式之间切换：
        1) ignore_menu_area == True：只判断“鼠标是否在按钮区域”，忽略菜单区域
        2) ignore_menu_area == False：同时判断“按钮区域或菜单区域”，按之前逻辑处理
        """
        if event.type() in (QEvent.Enter, QEvent.Leave, QEvent.MouseMove, QEvent.HoverMove):
            cursor_pos = QCursor.pos()

            # 计算按钮在屏幕上的全局矩形
            btn_top_left = self.dock_button_menu.mapToGlobal(QPoint(0, 0))
            btn_rect_global = self.dock_button_menu.rect().translated(btn_top_left)

            # 菜单的 geometry() 默认就是全局坐标
            menu_rect_global = self.menu.geometry()

            # 如果当前只“识别按钮区域”，忽略菜单区域
            if self.ignore_menu_area:
                # 如果光标在按钮区域内，就调用 show_menu() 并同时把 ignore_menu_area 设回 False
                if btn_rect_global.contains(cursor_pos):
                    # 只有当 just_clicked == False 时才真的弹出
                    if not self.just_clicked:
                        self.show_menu()
                    # 无论如何，短时屏蔽都结束了（因为从按钮区触发打开）
                    self.just_clicked = False
                    return super().eventFilter(obj, event)
                else:
                    # 光标不在按钮区域内，菜单区也不再被识别
                    # 如果 menu 仍可见且尚未启动隐藏定时器，才启动延迟隐藏
                    if self.menu.isVisible() and not self.leave_timer.isActive():
                        self.leave_timer.start(700)
                    return super().eventFilter(obj, event)

            # 如果 ignore_menu_area == False，正常“按钮 + 菜单”双区域识别
            if btn_rect_global.contains(cursor_pos) or menu_rect_global.contains(cursor_pos):
                # 如果刚点击过菜单项，就先 stop 掉隐藏定时器，但不重复调用 show_menu()
                if self.just_clicked:
                    if self.leave_timer.isActive():
                        self.leave_timer.stop()
                    return super().eventFilter(obj, event)

                # 菜单可见时只 stop 掉隐藏定时器；不可见时就调用 show_menu() 弹出
                self.show_menu()
            else:
                # 光标移出按钮与菜单区域：如果菜单当前可见且定时器未启动，就启动延迟隐藏
                if self.menu.isVisible() and not self.leave_timer.isActive():
                    self.leave_timer.start(700)

        return super().eventFilter(obj, event)

    def _try_hide(self):
        """
        leave_timer 超时后再次检查光标位置：
        如果光标仍不在按钮/菜单区域，就真正隐藏菜单并恢复按钮样式；否则不做任何事。
        """
        cursor_pos = QCursor.pos()

        btn_top_left = self.dock_button_menu.mapToGlobal(QPoint(0, 0))
        btn_rect_global = self.dock_button_menu.rect().translated(btn_top_left)
        menu_rect_global = self.menu.geometry()

        # 如果光标仍在按钮或菜单区域，就不隐藏
        if btn_rect_global.contains(cursor_pos) or menu_rect_global.contains(cursor_pos):
            return

        # 否则，隐藏菜单并恢复按钮正常样式
        self._hide_menu_and_reset()

    def _hide_menu_and_reset(self):
        """隐藏菜单并把按钮恢复为 normal 样式（取消 hover）"""
        self.menu.hide()
        self.dock_button_menu.setStyleSheet(self.normal_style)

    ###########以上是dock区菜单按钮函数

    #查看日志
    def show_log(self):
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit
        import os

        log_path = os.path.join(os.getcwd(), "ImgProcess.log")

        log_window = QDialog(self)
        log_window.setWindowTitle("日志查看")
        log_window.setModal(True)
        log_window.resize(600, 400)

        layout = QVBoxLayout()

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setLineWrapMode(QTextEdit.NoWrap)  # 禁止自动换行

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(log_path, "r", encoding="gbk") as f:
                content = f.read()
        except FileNotFoundError:
            content = "日志文件未找到：ImgProcess.log"
        except Exception as e:
            content = f"读取日志出错：{str(e)}"

        text_edit.setText(content)

        # 自动滚动到文本末尾
        text_edit.moveCursor(QTextCursor.End)

        layout.addWidget(text_edit)
        log_window.setLayout(layout)

        # 居中显示
        parent_geom = self.geometry()
        log_window.move(
            parent_geom.center().x() - log_window.width() // 2,
            parent_geom.center().y() - log_window.height() // 2
        )

        log_window.exec_()

    def init_logging(self):  # 初始化日志
        handler = RotatingFileHandler(
            'ImgProcess.log',
            maxBytes=5*1024*1024,  # 最大5MB
            backupCount=1,         # 只保留 1 个备份
            encoding='utf-8'       # ✅ 强烈建议添加这一行
        )
        logging.basicConfig(
            handlers=[handler],
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

    #检查更新
    def check_update(self):
        """显示更新对话框"""
        dialog = UpdateDialog(self, CURRENT_VERSION)
        dialog.exec_()

#############主程序########################################主程序###################################主程序#######################################主程序###############################


###GSfolders##############################################################GSfolders#######################################GSfolders#########################################
    def select_path(self):
        if not self.folder_name_entry.text():
            QMessageBox.information(self, "提示", "请输入文件夹名称")
            return
        if not self.num_folders_entry.text():
            QMessageBox.information(self, "提示", "请输入文件夹数量")
            return
        #设置默认文件夹路径      
        last_folder_path = self.settings.value("last_folder_path", ".")
        if not last_folder_path:
            last_folder_path = "."
        folder_path = str(QFileDialog.getExistingDirectory(self, "创建文件夹", last_folder_path))
        if not folder_path:
            return  # 如果用户没有选择文件夹，则直接返回
        self.settings.setValue("last_folder_path", folder_path)  # 保存上次选择的文件夹路径
        self.create_folders(folder_path)

    def create_folders(self, folder_path):
        num_folders = self.num_folders_entry.text()
        folder_name = self.folder_name_entry.text()
        try:
            num_folders = int(num_folders)
            if num_folders <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.information(self, "出错了", "请输入正整数的文件夹数量")
            return
        success_count = 0
        skip_count = 0
        # 保存当前输入的名称和数量到设置中
        self.settings.setValue("last_folder_name", folder_name)
        self.settings.setValue("last_num_folders", num_folders)
        # Extract numeric suffix from the existing folder name
        existing_suffix_match = re.search(r'\d+$', folder_name)
        existing_suffix = int(existing_suffix_match.group()) if existing_suffix_match else None
        if existing_suffix is not None:
            for i in range(existing_suffix, existing_suffix + num_folders):
                current_folder_name = re.sub(r'\d+$', str(i), folder_name)
                folder_path_i = os.path.join(folder_path, current_folder_name)

                if os.path.exists(folder_path_i):
                    skip_count += 1
                    continue
                try:
                    os.makedirs(folder_path_i)
                    subfolder1_path = os.path.join(folder_path_i, "待修")
                    os.makedirs(subfolder1_path)
                    subfolder2_path = os.path.join(folder_path_i, "已修")
                    os.makedirs(subfolder2_path)
                    subfolder3_path = os.path.join(subfolder2_path, "psd")
                    os.makedirs(subfolder3_path)
                    subfolder4_path = os.path.join(subfolder2_path, "其他尺寸")
                    os.makedirs(subfolder4_path)
                    success_count += 1
                except:
                    pass
        else:
            # 如果文件夹名称末尾没有数字，则在最后一个文字后面从0开始依次递增
            for i in range(num_folders):
                current_folder_name = f"{folder_name}{i}"
                folder_path_i = os.path.join(folder_path, current_folder_name)
                if os.path.exists(folder_path_i):
                    skip_count += 1
                    continue
                try:
                    os.makedirs(folder_path_i)
                    subfolder1_path = os.path.join(folder_path_i, "待修")
                    os.makedirs(subfolder1_path)
                    subfolder2_path = os.path.join(folder_path_i, "已修")
                    os.makedirs(subfolder2_path)
                    subfolder3_path = os.path.join(subfolder2_path, "psd")
                    os.makedirs(subfolder3_path)
                    subfolder4_path = os.path.join(subfolder2_path, "其他尺寸")
                    os.makedirs(subfolder4_path)
                    success_count += 1
                except:
                    pass
        # 同时创建一个名为"需要复制的图片"的文件夹
        target_dir = os.path.join(folder_path, "图片复制")
        os.makedirs(target_dir, exist_ok=True)

        # 创建说明文件
        instruction_file = os.path.join(target_dir, "说明.txt")
        # 写入说明内容
        instruction_content = "修图完毕后，此文件夹内的所有图片将自动复制到每一个sku文件夹的子文件夹【已修】\n\n也可双击【手动复制.bat】进行复制图片"
        #如果不存在说明文件，则创建
        if not os.path.exists(instruction_file):
            with open(instruction_file, "w", encoding="utf-8") as f:
                f.write(instruction_content)

        # 再创建“手动复制”批处理文件路径
        bat_file = os.path.join(target_dir, "手动复制.bat")
        # 批处理内容
        bat_content = r"""@echo off
        chcp 65001
        setlocal enabledelayedexpansion

        :: 使用 PUSHD 进入当前 .bat 所在目录（兼容 UNC）
        PUSHD %~dp0

        set "current_dir=%cd%"
        for %%i in ("%cd%") do set "parent_dir=%%~dpi"

        :: 切换到上一级目录
        cd /d "%parent_dir%" || (
            echo 无法进入上级目录。
            pause
            POPD
            exit /b
        )

        :: 检查当前目录是否有JPG或PNG图片
        set "has_images=0"
        for %%I in ("%current_dir%\*.jpg" "%current_dir%\*.png") do (
            if exist "%%I" set "has_images=1"
        )

        :: 如果没有图片则提示并退出
        if "!has_images!"=="0" (
            echo 未发现图片文件（.jpg .png），请先将图片放至此文件夹内以便复制
            :: 返回原始路径
            POPD
            echo.
            echo 按任意键退出...
            pause >nul
            exit /b
        )

        :: 主循环：处理每个子文件夹
        for /d %%F in ("*") do (
            if /i not "%%~fF"=="%current_dir%" (
                set "target=%%~fF\已修"
                if exist "!target!" (
                    echo 正在复制到: "!target!"
                    for %%I in ("%current_dir%\*.jpg" "%current_dir%\*.png") do (
                        if exist "%%I" (
                            set "filename=%%~nxI"
                            if not exist "!target!\!filename!" (
                                copy "%%I" "!target!\" >nul
                                echo 复制: !filename!
                            ) else (
                                echo 已存在，跳过: !filename!
                            )
                        )
                    )
                ) else (
                    echo 跳过: "!target!" 文件夹不存在
                )
            )
        )

        :: 返回原始路径
        POPD
        echo 所有操作完成。

        echo 请按任意键关闭窗口...
        pause >nul
        """

        # 如果不存在“手动复制”批处理文件，则创建
        if not os.path.exists(bat_content):
            with open(bat_file, "w", encoding="utf-8") as f:
                f.write(bat_content)

        # 获取 folder_path 的父目录
        parent_dir = os.path.dirname(folder_path)
        # 【常用图片】文件夹路径
        common_img_dir = os.path.join(parent_dir, "常用图片")
        if os.path.exists(common_img_dir):
            # 查找【包装袋.jpg】
            source_file = os.path.join(common_img_dir, "包装袋.jpg")
     
            if os.path.exists(source_file):
                # 构造目标路径
                dest_file = os.path.join(target_dir, "包装袋.jpg")
                
                # 复制文件
                shutil.copy2(source_file, dest_file)
                print(f"已复制文件: {source_file} -> {dest_file}")
                logging.info(f"已复制文件: {source_file} -> {dest_file}")

        if success_count > 0:
            QMessageBox.information(self, "提示", f"成功创建 {success_count} 个文件夹。已存在的文件夹被跳过 {skip_count} 个。")
        elif skip_count == num_folders:
            QMessageBox.information(self, "提示", "所有文件夹均已存在，无需创建。")
        else:
            QMessageBox.information(self, "出错了", f"创建文件夹失败，共有 {num_folders - skip_count} 个文件夹创建失败。已存在的文件夹被跳过 {skip_count} 个。")
###GSfolders##############################################################GSfolders#######################################GSfolders#########################################
   
   
###FolderFilter#######################################################FolderFilter###################################FolderFilter#####################################################  
    #选择文件夹
    def select_folder(self):
        self.expanded = None
        self.clear_list_flag = True #不清空时选择的文件夹时候用的
        if self.thread_running:
            QMessageBox.information(self,'提示','后台正在运行自动归档，请稍后再操作')
            return
        # 获取用户输入的文件类型
        file_type = self.filter_combo.currentText()        
        if not file_type:
            QMessageBox.information(self,'提示','请输入要筛选的文件类型\n例如：“.psd”')
            return
        else:
            #设置进度条为初始状态
            self.progress_bar.setValue(0)
            #设置默认文件夹路径      
            last_dir_path = self.settings.value("last_dir_path", ".")
            if not last_dir_path:  # 如果还没有保存过选择的文件夹路径，则使用当前目录作为默认路径
                last_dir_path = "."
            dir_path = str(QFileDialog.getExistingDirectory(self, '选择文件夹', last_dir_path))
            if not dir_path:
                self.clear_list_flag = False
            else:
                if not os.access(dir_path, os.R_OK):
                    QMessageBox.warning(self, '警告', '无法读取选择的文件夹，请检查权限设置。')
                    self.clear_list_flag = False
            if dir_path in [self.file_filter_folders_list.item(index).data(Qt.UserRole) for index in range(self.file_filter_folders_list.count())]:
                QMessageBox.information(self, "提示", "此文件夹已在列表中。")
                self.clear_list_flag = False
            if self.clear_list_flag == False:
                self.expanded = True
                return
            if self.clear_list_flag == True:
                self.file_left_list.clear()
                self.file_right_list.clear()
                self.folder_left_num_label.clear()
                self.folder_right_num_label.clear()
                self.settings.setValue("last_dir_path", dir_path)
                # 设置已选择的文件夹路径
                item = QListWidgetItem()
                item.setData(Qt.DisplayRole, os.path.basename(dir_path))
                item.setData(Qt.TextColorRole, QColor("#761B73")) # 设置链接的颜色
                item.setData(Qt.TextAlignmentRole, Qt.AlignLeft)   # 设置链接的对齐方式
                item.setData(Qt.UserRole, dir_path)
                self.file_filter_folders_list.addItem(item)
            # 连接双击事件到槽函数
            self.file_filter_folders_list.itemDoubleClicked.connect(lambda: self.item_double_clicked(self.file_filter_folders_list))   
            # 连接右键菜单的槽函数
            self.file_filter_folders_list.setContextMenuPolicy(Qt.CustomContextMenu)
            self.file_filter_folders_list.customContextMenuRequested.connect(self.show_context_menu)
             #防止槽函数被多次调用而断开连接
            self.file_filter_folders_list.itemDoubleClicked.disconnect()
            self.file_filter_folders_list.customContextMenuRequested.disconnect()
            # 再次连接槽函数，确保只连接一次
            self.file_filter_folders_list.itemDoubleClicked.connect(lambda: self.item_double_clicked(self.file_filter_folders_list))   
            self.file_filter_folders_list.customContextMenuRequested.connect(self.show_context_menu)
            #启动筛选函数
            self.folders_filter()
            # 启动倒计时
            self.remaining_time = 90
            self.countdown_timer = QTimer()
            self.countdown_timer.timeout.connect(self.update_countdown)
            self.countdown_timer.start(1000)  # 每隔1秒更新倒计时
            self.settings = QSettings("lemon-o", "ImgProcess")
            self.expanded = True

    # 文件类型筛选      
    def folders_filter(self):
        if self.file_filter_folders_list.count() == 0:
            return
        #获取选择的文件类型
        file_type = self.filter_combo.currentText()
        left_count = 0  # 不含有此类文件的子文件夹数量
        right_count = 0  # 含有此类文件的子文件夹数量
        # 统计文件夹数量
        total_count = 0
        processed_count = 0
        for i in range(self.file_filter_folders_list.count()): 
            item = self.file_filter_folders_list.item(i)
            self.parent_dir = item.data(Qt.DisplayRole)
            self.dir_path = item.data(Qt.UserRole).replace("/", "\\") 
            for root, dirs, files in os.walk(self.dir_path):
                total_count += len(dirs)
                # 处理不可访问的目录
                if not os.access(root, os.R_OK):
                    continue
                # 继续处理其他的目录 
                for dir_name in dirs:              
                    # 子文件夹的路径
                    self.sub_dir_path = os.path.join(root, dir_name)
                    # 如果"需要复制的图片"文件夹不存在，则创建
                    target_dir = os.path.join(self.dir_path, "图片复制")
                    os.makedirs(target_dir, exist_ok=True)
                    # 如果该子文件夹是目录A的一级子文件夹，则添加到控件中
                    if os.path.dirname(self.sub_dir_path) == self.dir_path and self.sub_dir_path != target_dir:
                        # 检查子文件夹及其所有子文件夹中是否存在.file_type文件
                        file_type_exist = False
                        for sub_root, sub_dirs, sub_files in os.walk(self.sub_dir_path):
                            if any(f.endswith(file_type) for f in sub_files):
                                file_type_exist = True
                                break

                        if not file_type_exist:
                            sub_dir_files = os.listdir(os.path.join(self.parent_dir, self.sub_dir_path))
                            if any(file.lower().endswith(('.jpg', '.jpeg', '.png', '.raw', '.bmp', '.gif')) for file in sub_dir_files):
                                try:
                                    os.makedirs(os.path.join(self.parent_dir, self.sub_dir_path, "已修", "psd"))
                                    os.makedirs(os.path.join(self.parent_dir, self.sub_dir_path, "已修", "其他尺寸"))
                                except:
                                    pass
                            if os.path.exists(os.path.join(self.parent_dir, self.sub_dir_path, "待修")):
                                try:
                                    os.makedirs(os.path.join(self.parent_dir, self.sub_dir_path, "已修", "psd"))
                                    os.makedirs(os.path.join(self.parent_dir, self.sub_dir_path, "已修", "其他尺寸"))
                                except:
                                    pass
                                wait_repaire_files = os.listdir(os.path.join(self.parent_dir, self.sub_dir_path, "待修"))
                                if not any(file.lower().endswith(('.jpg', '.jpeg', '.png', '.raw', '.bmp', '.gif')) for file in wait_repaire_files):
                                    dir_name = "未选图 " + dir_name
                            elif os.path.exists(os.path.join(self.parent_dir, self.sub_dir_path)):
                                wait_repaire_files = os.listdir(os.path.join(self.parent_dir, self.sub_dir_path))
                                for file in wait_repaire_files:
                                    if file.lower().endswith(('.jpg', '.jpeg', '.png', '.raw', '.bmp', '.gif')):
                                        file_path = os.path.join(self.parent_dir, self.sub_dir_path, file)
                                        with Image.open(file_path) as img:
                                            if img.size[0] > 1800:
                                                dir_name = "未选图 " + dir_name
                                                break
                            item = QListWidgetItem()
                            # 给item设置数据，包括名称和HTML链接
                            item.setData(Qt.DisplayRole, dir_name)
                            item.setData(Qt.TextColorRole, QColor("#2F857E")) # 设置链接的颜色
                            item.setData(Qt.TextAlignmentRole, Qt.AlignLeft)   # 设置链接的对齐方式
                            item.setData(Qt.UserRole, os.path.join(self.parent_dir, self.sub_dir_path))  
                            self.file_left_list.addItem(item)
                            left_count += 1

                        if file_type_exist:
                            item = QListWidgetItem()
                            # 给item设置数据，包括名称和HTML链接
                            item.setData(Qt.DisplayRole, dir_name)
                            item.setData(Qt.TextColorRole, QColor("#39569E")) # 设置链接的颜色
                            item.setData(Qt.TextAlignmentRole, Qt.AlignLeft)   # 设置链接的对齐方式
                            item.setData(Qt.UserRole, os.path.join(self.parent_dir, self.sub_dir_path))
                            self.file_right_list.addItem(item)
                            right_count += 1
            
                        option = self.sort_combo.currentText()     
                        if option == "升序":
                            self.file_right_list.sortItems()
                            self.file_left_list.sortItems()       
                        elif option == "降序":
                            self.file_right_list.sortItems(Qt.DescendingOrder)
                            self.file_left_list.sortItems(Qt.DescendingOrder)   
                        self.file_right_list.update()
                        self.file_left_list.update()                     
                        self.folder_left_num_label.setText(f"总计：{self.file_left_list.count()}")
                        self.folder_right_num_label.setText(f"总计：{self.file_right_list.count()}")      
                    processed_count += 1
                    progress_percent = int(processed_count / total_count * 100)
                    self.progress_bar.setValue(progress_percent)    
        # 连接双击的槽函数
        self.file_left_list.itemDoubleClicked.connect(lambda: self.item_double_clicked(self.file_left_list))
        self.file_right_list.itemDoubleClicked.connect(lambda: self.item_double_clicked(self.file_right_list))
        # 连接右键菜单的槽函数
        self.file_left_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_left_list.customContextMenuRequested.connect(self.show_context_menu)
        self.file_right_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_right_list.customContextMenuRequested.connect(self.show_context_menu)
        #防止槽函数被多次调用而断开连接
        self.file_left_list.itemDoubleClicked.disconnect()
        self.file_right_list.itemDoubleClicked.disconnect()
        self.file_left_list.customContextMenuRequested.disconnect()
        self.file_right_list.customContextMenuRequested.disconnect()
        # 再次连接槽函数，确保只连接一次
        self.file_left_list.itemDoubleClicked.connect(lambda: self.item_double_clicked(self.file_left_list))
        self.file_right_list.itemDoubleClicked.connect(lambda: self.item_double_clicked(self.file_right_list))
        self.file_left_list.customContextMenuRequested.connect(self.show_context_menu)
        self.file_right_list.customContextMenuRequested.connect(self.show_context_menu)

        # 在"需要复制的图片"文件夹内创建说明文件
        instruction_file = os.path.join(target_dir, "说明.txt")
        # 写入说明内容
        instruction_content = "修图完毕后，此文件夹内的所有图片将自动复制到每一个sku文件夹的子文件夹【已修】\n\n也可双击【手动复制.bat】进行复制图片"
        #如果不存在说明文件，则创建
        if not os.path.exists(instruction_file):
            with open(instruction_file, "w", encoding="utf-8") as f:
                f.write(instruction_content)

        # 再创建“手动复制”批处理文件路径
        bat_file = os.path.join(target_dir, "手动复制.bat")
        # 批处理内容
        bat_content = r"""@echo off
        chcp 65001
        setlocal enabledelayedexpansion

        :: 使用 PUSHD 进入当前 .bat 所在目录（兼容 UNC）
        PUSHD %~dp0

        set "current_dir=%cd%"
        for %%i in ("%cd%") do set "parent_dir=%%~dpi"

        :: 切换到上一级目录
        cd /d "%parent_dir%" || (
            echo 无法进入上级目录。
            pause
            POPD
            exit /b
        )

        :: 检查当前目录是否有JPG或PNG图片
        set "has_images=0"
        for %%I in ("%current_dir%\*.jpg" "%current_dir%\*.png") do (
            if exist "%%I" set "has_images=1"
        )

        :: 如果没有图片则提示并退出
        if "!has_images!"=="0" (
            echo 未发现图片文件（.jpg .png），请先将图片放至此文件夹内以便复制
            :: 返回原始路径
            POPD
            echo.
            echo 按任意键退出...
            pause >nul
            exit /b
        )

        :: 主循环：处理每个子文件夹
        for /d %%F in ("*") do (
            if /i not "%%~fF"=="%current_dir%" (
                set "target=%%~fF\已修"
                if exist "!target!" (
                    echo 正在复制到: "!target!"
                    for %%I in ("%current_dir%\*.jpg" "%current_dir%\*.png") do (
                        if exist "%%I" (
                            set "filename=%%~nxI"
                            if not exist "!target!\!filename!" (
                                copy "%%I" "!target!\" >nul
                                echo 复制: !filename!
                            ) else (
                                echo 已存在，跳过: !filename!
                            )
                        )
                    )
                ) else (
                    echo 跳过: "!target!" 文件夹不存在
                )
            )
        )

        :: 返回原始路径
        POPD
        echo 所有操作完成。

        echo 请按任意键关闭窗口...
        pause >nul
        """

        # 如果不存在“手动复制”批处理文件，则创建
        if not os.path.exists(bat_content):
            with open(bat_file, "w", encoding="utf-8") as f:
                f.write(bat_content)

        # 获取 folder_path 的父目录
        parent_dir = os.path.dirname(self.dir_path)
        # 【常用图片】文件夹路径
        common_img_dir = os.path.join(parent_dir, "常用图片")
        if os.path.exists(common_img_dir):
            # 查找【包装袋.jpg】
            source_file = os.path.join(common_img_dir, "包装袋.jpg")
     
            if os.path.exists(source_file):
                # 构造目标路径
                dest_file = os.path.join(target_dir, "包装袋.jpg")
                
                # 复制文件
                shutil.copy2(source_file, dest_file)
                print(f"已复制文件: {source_file} -> {dest_file}")
                logging.info(f"已复制文件: {source_file} -> {dest_file}")
        
        self.start_vedio_processing()

    def start_vedio_processing(self):
        """开始视频处理"""
        # 检测是否安装 ffmpeg
        if not os.path.isfile(FFMPEG_ABSOLUTE_PATH):
            # 跳出提示：还没安装
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("提示")
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setText("检测到视频处理插件 'ffmpeg' 未安装，稍后将自动安装")
            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.button(QMessageBox.Ok).setText("确定")
            msg_box.setStyleSheet("""
                QMessageBox {
                    font-size: 14px;
                }
                QPushButton {
                    min-width: 80px;
                    padding: 5px;
                }
            """)
            msg_box.exec_()

            # 弹出安装对话框，开始下载安装
            self.install_dialog = FFmpegInstallDialog(self)
            self.install_dialog.start_installation()
            logging.info("检测到ffmpeg未安装，开始安装···")
        else:
            # 已经安装了
            self.is_ffmpeg_install = True
            self.video_thread_start()

    def ffmpeg_installed(self, success, message):
        """当 FFmpeg 安装完毕后被调用"""
        if success:
            logging.info("ffmpeg安装成功！")
            self.is_ffmpeg_install = True
            self.video_thread_start()

    def video_thread_start(self):
        if not self.is_ffmpeg_install:
            return
        # 收集所有需要处理的文件夹信息
        folders_to_process = []
        for entry in os.scandir(self.dir_path):
            if entry.is_dir() and entry.name != "图片复制":
                dir_path = entry.path
                
                # 首先检查主目录(dir_path)中是否有MP4文件
                if any(fn.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.flv')) for fn in os.listdir(dir_path)):
                    processed_folder = os.path.join(dir_path, "已修")
                    
                    # 然后检查"已修"目录中是否有MP4文件
                    if os.path.exists(processed_folder) and not any(fn.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.flv')) for fn in os.listdir(processed_folder)):
                        folders_to_process.append((dir_path, processed_folder))
        # 创建单个工作线程处理所有文件夹
        if folders_to_process:
            video_thread = VideoWorker(folders_list=folders_to_process)
            video_thread.finished_signal.connect(self.video_thread_finshed)
            video_thread.start()
            self._video_threads.append(video_thread)
            self.video_work_thread_running = True
        # 只保留 dir_path 的文件夹名
        only_folder_names = [os.path.basename(folder[0]) for folder in folders_to_process]
        print(f"视频待处理文件夹：{only_folder_names}")
        logging.info(f"视频待处理文件夹：{only_folder_names}")

    def video_thread_finshed(self):
        self.video_work_thread_running = False
        print("··················")
        print("所有视频都已处理完毕")
        logging.info("··················")
        logging.info("所有视频都已处理完毕")

    def item_double_clicked(self, list_widget):
        if self.expanded and self.y() == self.monitor_top_border - self.margin:
            self.double_clicked = True
            self.up_move_window()
            self.expanded = False
            self.double_clicked = False
        item = list_widget.currentItem()
        if not item:
            return
        # 获取文件夹路径
        folder_path = item.data(Qt.UserRole)
        # url编码
        encoded_path = urllib.parse.quote(folder_path)
        if list_widget == self.file_left_list:
            # 检查路径是否已经存在于列表中
            if folder_path not in self.clicked_folder_path:
                # 将文件夹路径添加到已经点击的列表中
                self.clicked_folder_path.append(folder_path)
        # 打开文件夹
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))
        folder_name = os.path.basename(folder_path)
        if folder_name not in self.clicked_folder_names:
            self.clicked_folder_names.extend({"待修", "已修", folder_name})
            # 去除重复元素
            self.clicked_folder_names = list(set(self.clicked_folder_names))
        # 复制路径到剪贴板
        additional_text = "\\已修\\psd"
        folder_path_with_additional_text = folder_path + additional_text
        clipboard = QApplication.clipboard()
        clipboard.setText(folder_path_with_additional_text)
        self.item_copy = item
        # self.rename_folder()

    # def rename_folder(self):
    #     item = self.item_copy
    #     if not item:
    #         return
    #     folder_path = item.data(Qt.UserRole)
    #     folder_name = os.path.basename(folder_path)
    #     original_folder_name = folder_name
    #     work_folder_name = "正在修图勿动" + folder_name
    #     if work_folder_name not in self.renamed_folders:
    #         self.renamed_folders.append(work_folder_name)
    #     working_folder_name = self.renamed_folders[-1]
    #     item.setData(Qt.DisplayRole, working_folder_name)
    #     if len(self.renamed_folders) > 1:
    #         for work_folder_name in self.renamed_folders[:-1]:
    #             item.setData(Qt.DisplayRole, original_folder_name)
    #             print(original_folder_name) 

    #右键删除选定项并设置“delete”为快捷键
    def show_context_menu(self, pos):
        current_list = self.sender()  # 获取发送信号的对象
        context_menu = QMenu(self)
        delete_action = context_menu.addAction("删除")
        # 获取鼠标位置相对于当前列表的本地坐标
        pos_local = current_list.mapToGlobal(pos)
        # 显示菜单
        action = context_menu.exec_(pos_local)
        if action == delete_action:
            self.deleteSelectedItem(current_list)
    def deleteSelectedItem(self, current_list):
        file_names = []
        for i in range(self.file_filter_folders_list.count()): 
            item = self.file_filter_folders_list.item(i)
            file_name = item.data(Qt.DisplayRole)
            if file_name not in file_names:
                file_names.append(file_name)
        # 在这里实现删除选定项的逻辑
        selected_items = current_list.selectedItems()
        for selected_item in selected_items:
            row = current_list.row(selected_item)
            current_list.takeItem(row)
            delete_file_name = selected_item.data(Qt.DisplayRole)
        if len(file_names) == 1 and delete_file_name == file_names[0]:
            self.file_left_list.clear()
            self.file_right_list.clear()
            self.folder_left_num_label.clear()
            self.folder_right_num_label.clear()
            self.clicked_folder_path = []
            self.clicked_folder_names = []
        elif delete_file_name in file_names:
            self.refresh()
        # 处理事件队列
        QCoreApplication.processEvents()
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            current_widget = self.focusWidget()
            if isinstance(current_widget, QListWidget):
                self.deleteSelectedItem(current_widget)
    
    # 进行排序      
    def folders_sort(self):  
        option = self.sort_combo.currentText()
                
        if option == "升序":
            self.file_right_list.sortItems()
            self.file_left_list.sortItems()
                
        elif option == "降序":
            self.file_right_list.sortItems(Qt.DescendingOrder) 
            self.file_left_list.sortItems(Qt.DescendingOrder)
                
        self.file_right_list.update()
        self.file_left_list.update()       
                
    #清空按钮配置
    def reset(self):
        self.expanded = None
        if self.file_filter_folders_list.count() == 0:
            QMessageBox.information(self,'提示','请先选择文件夹')
            self.expanded = True
            return
        if self.thread_running:
            QMessageBox.information(self,'提示','后台正在运行自动归档，请稍后再操作')
            self.expanded = True
            return
        if self.file_filter_folders_list.count() > 0:
            self.refresh()
            self.archive_auarantee()
            self.auto_archiving()
            if self.psd_found:
                self.dialog()
                self.psd_found = False
            self.close_folder_windows()
        self.parent_dir = None
        self.dir_path = None
        self.file_left_list.clear()
        self.file_right_list.clear()
        self.file_filter_folders_list.clear()
        self.folder_left_num_label.clear()
        self.folder_right_num_label.clear() 
        #防止槽函数被多次调用而断开连接
        self.file_left_list.itemDoubleClicked.disconnect()
        self.file_right_list.itemDoubleClicked.disconnect()
        self.file_filter_folders_list.itemDoubleClicked.disconnect()
        self.file_left_list.customContextMenuRequested.disconnect()
        self.file_right_list.customContextMenuRequested.disconnect()
        self.file_filter_folders_list.customContextMenuRequested.disconnect()
        #再次连接槽函数，这样可以确保只连接了一次
        self.file_filter_folders_list.itemDoubleClicked.connect(lambda: self.item_double_clicked(self.file_filter_folders_list))
        self.file_filter_folders_list.customContextMenuRequested.connect(self.show_context_menu)
        #进度条设置初始值
        self.progress_bar.setValue(0)
        # 重置倒计时时间并停止计时器
        self.remaining_time = 90
        self.countdown_timer.stop()
        # 更新倒计时标签
        self.countdown_label.setText(f"{self.remaining_time} 秒后自动归档")
        self.expanded = True

    #刷新按钮配置
    def refresh(self):
        self.expanded = None
        if self.file_filter_folders_list.count() == 0:
            QMessageBox.information(self, '提示', '请先选择文件夹')
            self.expanded = True
            return
        if len(self.clicked_folder_path) == 0:
            pass
        else:
            try:
                # 遍历已经存储的文件夹路径
                for folder_path in self.clicked_folder_path:
                        self.left_list_path = folder_path
                        self.file_path_left = os.path.join(self.left_list_path, "已修")
                        self.psd_folder_left = os.path.join(self.file_path_left, "psd")
                        if os.path.exists(self.file_path_left):
                            for file_name in os.listdir(self.psd_folder_left):
                                if os.path.isfile(os.path.join(self.psd_folder_left, file_name)) and file_name.endswith(".psd"):
                                    self.psd_path_left = os.path.join(self.file_path_left, file_name)
                                    # 移动 PSD 文件到 "已修" 文件夹
                                    os.rename(os.path.join(self.psd_folder_left, file_name), self.psd_path_left)
            except FileNotFoundError:
                folder_name = os.path.basename(self.left_list_path)
                QMessageBox.information(self, '提示', f"'{folder_name}' 不存在，可能已被重命名")

        self.file_left_list.clear()
        self.file_right_list.clear()
        self.folder_left_num_label.clear()
        self.folder_right_num_label.clear()
        #防止槽函数被多次调用而断开连接
        self.file_left_list.itemDoubleClicked.disconnect()
        self.file_right_list.itemDoubleClicked.disconnect()
        self.file_filter_folders_list.itemDoubleClicked.disconnect()
        self.file_left_list.customContextMenuRequested.disconnect()
        self.file_right_list.customContextMenuRequested.disconnect()
        self.file_filter_folders_list.customContextMenuRequested.disconnect()
        #再次连接槽函数，这样可以确保只连接了一次
        self.file_filter_folders_list.itemDoubleClicked.connect(lambda: self.item_double_clicked(self.file_filter_folders_list))
        self.file_filter_folders_list.customContextMenuRequested.connect(self.show_context_menu)
        ####
        self.folders_filter()
        self.close_folder_windows()
        self.clicked_folder_path = []
        self.clicked_folder_names = []
        self.expanded = True
        # 设置倒计时时间以快速启动归档
        self.remaining_time = 4

    #自动归档
    def auto_archiving(self):
        if self.thread_running:
            return
        if self.file_right_list.count() == 0:
            return
        for i in range(self.file_right_list.count()):
            item = self.file_right_list.item(i)
            self.right_list_path = item.data(Qt.UserRole)
            try:
                os.makedirs(os.path.join(self.right_list_path, "已修", "psd"))
            except:
                pass
            self.file_path_right = os.path.join(self.right_list_path, "已修")
            if os.path.exists(self.file_path_right):
                self.psd_folder_right = os.path.join(self.file_path_right, "psd")
                # 遍历目标文件夹中的文件
                for file_name in os.listdir(self.file_path_right):
                    # 检查文件类型是否为 PSD
                    if os.path.isfile(os.path.join(self.file_path_right, file_name)) and file_name.endswith(".psd"):
                        # 启动线程
                        self.thread.start1 = True
                        self.thread.start()
                        self.psd_found = True
                        self.thread_running = True
                        return 
    #归档线程完成信号        
    def thread_finished(self):
        self.thread_running = False

    #确保所有psd文件都将被导出
    def archive_auarantee(self):
        for i in range(self.file_right_list.count()):
            item = self.file_right_list.item(i)
            self.right_list_path = item.data(Qt.UserRole)
            self.file_path_right = os.path.join(self.right_list_path, "已修")
            try:
                for file_name in os.listdir(self.file_path_right):
                    if os.path.isfile(os.path.join(self.file_path_right, file_name)) and file_name.endswith(".jpg"):
                        break
                else:
                    self.psd_folder_right = os.path.join(self.file_path_right, "psd")
                    self.psd_open_ok = True
                    for psd_file_name in os.listdir(self.psd_folder_right):
                        if os.path.isfile(os.path.join(self.psd_folder_right, psd_file_name)) and psd_file_name.endswith(".psd"):
                            try:
                                # 尝试打开 PSD 文件
                                PSDImage.open(os.path.join(self.psd_folder_right, psd_file_name))
                                break
                            except Exception as e:
                                full_path = os.path.join(self.file_path_right, psd_file_name)
                                print(f"无法处理文件: {psd_file_name} ({full_path})")
                                logging.info(f"无法处理文件: {psd_file_name} ({full_path})")
                                self.psd_open_ok = False
                                break
                    if self.psd_open_ok:
                        for psd_file_name in os.listdir(self.psd_folder_right):
                            if os.path.isfile(os.path.join(self.psd_folder_right, psd_file_name)) and psd_file_name.endswith(".psd"):
                                source_path = os.path.join(self.psd_folder_right, psd_file_name)
                                destination_path = os.path.join(self.file_path_right, psd_file_name)
                                try:
                                    # 移动 PSD 文件到 "已修" 文件夹
                                    os.rename(source_path, destination_path)
                                except FileExistsError:
                                    # 在文件名中添加后缀
                                    base, extension = os.path.splitext(psd_file_name)
                                    counter = 1
                                    new_psd_dest_path = os.path.join(self.file_path_right, f"{base}_backup_{counter}{extension}")   
                                    # 生成唯一的文件名
                                    while os.path.exists(new_psd_dest_path):
                                        counter += 1
                                        new_psd_dest_path = os.path.join(self.file_path_right, f"{base}_backup_{counter}{extension}")
                                    # 移动文件到新路径
                                    os.rename(source_path, new_psd_dest_path)
            except FileNotFoundError:
                continue

    #加载上一次的窗口大小
    # def load_window_size(self):
    #     window_size = self.settings.value('window_size', QtCore.QSize(512, 512))
    #     self.resize(window_size)

    #归档提示框
    def dialog(self):
        self.expanded = None
        timer_timeout = False
        thread_finished = False
        last_update_time = time.time()  # 上次更新的时间戳初始值
        def on_timer_timeout():
            nonlocal timer_timeout
            timer_timeout = True
            try_close_dialog()
        def on_thread_finished():
            nonlocal thread_finished
            thread_finished = True
            try_close_dialog()
        def try_close_dialog():
            nonlocal timer_timeout, thread_finished
            if timer_timeout and thread_finished:
                dialog.accept()
        def updata_progress(value):
            nonlocal last_update_time
            current_time = time.time()
            # 判断是否在0.5秒内执行过更新
            if current_time - last_update_time >= 0.5:
                dialog.setText(f"正在归档 {value}%")
                last_update_time = current_time
            if value == 100:
                dialog.setText(f"正在归档 {value}%")         
        dialog = QMessageBox(self)
        dialog.setWindowTitle("提示")
        dialog.setText("正在归档 0%")
        dialog.setStandardButtons(QMessageBox.NoButton)
        dialog.setIcon(QMessageBox.Information)
        # 连接到进度更新信号，直接在这里处理进度更新
        self.thread.progress_update.connect(updata_progress)
        # 定时器超时时的处理
        close_timer = QTimer(dialog)
        close_timer.timeout.connect(on_timer_timeout)
        close_timer.start(1000)
        # 线程任务结束时的处理
        if not self.thread_running:
            on_thread_finished()
        self.thread.finished_signal.connect(on_thread_finished)  # 这里需要根据你的实际情况修改
        # 显示对话框
        dialog.exec_()
        self.expanded = True

    #关闭指定的其他程序的窗口
    def close_folder_windows(self):
        try:
            for title in self.clicked_folder_names:
                # 获取所有打开的窗口
                windows = gw.getWindowsWithTitle(title)
                # 关闭匹配的窗口
                for window in windows:
                    window.close()
        except Exception as e:
            print(f"An error occurred: {e}")
            logging.info(f"An error occurred: {e}")

###FolderFilter#######################################################FolderFilter###################################FolderFilter##################################################### 


###Cmingoz#######################################################Cmingoz###################################Cmingoz#####################################################  
    # def resizeEvent(self, event):
    #     # 获取新的窗口宽度和高度
    #     new_width = event.size().width()
    #     # 将水平分隔线位置和大小设置为新的窗口宽度和高度
    #     self.hline.setGeometry(0, self.y, new_width, 1)

    def convert_cm_to_inch(self):
        text = self.cm_input.text()
        try:
            cm = float(text)
            inch = cm * 0.393701
            self.in_input.textChanged.disconnect()
            self.in_input.setText(f"{inch:.4f}")
            self.cmin_result.setText(f"{cm:.2f} cm / {inch:.2f} inch")
            self.in_input.textChanged.connect(self.convert_inch_to_cm)
        except ValueError:
            self.cmin_result.setText("未输入换算数字")
            self.in_input.clear()

    def convert_inch_to_cm(self):
        text = self.in_input.text()
        try:
            inch = float(text)
            cm = inch / 0.393701
            self.cm_input.textChanged.disconnect()
            self.cm_input.setText(f"{cm:.4f}")
            self.cmin_result.setText(f"{inch:.2f} inch / {cm:.2f} cm")
            self.cm_input.textChanged.connect(self.convert_cm_to_inch)
        except ValueError:
            self.cmin_result.setText("未输入换算数字")
            self.cm_input.clear()

    def convert_g_to_ounce(self):
        text = self.g_input.text()
        try:
            g = float(text)
            ounce = g * 0.035274
            self.oz_input.textChanged.disconnect()
            self.oz_input.setText(f"{ounce:.4f}")
            self.goz_result.setText(f"{g:.2f} g / {ounce:.2f} oz")
            self.oz_input.textChanged.connect(self.convert_ounce_to_g)
        except ValueError:
            self.goz_result.setText("未输入换算数字")
            self.oz_input.clear()

    def convert_ounce_to_g(self):
        text = self.oz_input.text()
        try:
            ounce = float(text)
            g = ounce / 0.035274
            self.g_input.textChanged.disconnect()
            self.g_input.setText(f"{g:.4f}")
            self.goz_result.setText(f"{ounce:.2f} oz / {g:.2f} g")
            self.g_input.textChanged.connect(self.convert_g_to_ounce)
        except ValueError:
            self.goz_result.setText("未输入换算数字")
            self.g_input.clear()

    def copy_cmin_result(self):
        if self.cmin_result.text() == "未输入换算数字":
            QMessageBox.information(self,'提示','请输入要换算的数字')
            return
        else:
            clipboard = QApplication.clipboard()
            result = self.cmin_result.text()
            clipboard.setText(result)
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Information) 
            msg.setWindowTitle("提示")
            msg.setText("复制成功! 将重置此换算。")
            QTimer.singleShot(1500, msg.close) 
            msg.exec_()
            self.cm_input.clear()
            self.in_input.clear()
        
    def copy_goz_result(self):
        if self.goz_result.text() == "未输入换算数字":
            QMessageBox.information(self,'提示','请输入要换算的数字')
            return
        else:
            clipboard = QApplication.clipboard()
            result = self.goz_result.text()
            clipboard.setText(result)
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Information) 
            msg.setWindowTitle("提示")
            msg.setText("复制成功! 将重置此换算。")
            QTimer.singleShot(1500, msg.close) 
            msg.exec_()
            self.g_input.clear()
            self.oz_input.clear()
###Cmingoz#######################################################Cmingoz###################################Cmingoz#####################################################  
            
            
    #记录窗口关闭事件
    def closeEvent(self, event):
        self.expanded = None 
        if self.video_work_thread_running:
            QMessageBox.information(self,'提示','后台正在处理视频，请稍后再操作')
            event.ignore()
            self.expanded = True
            return
        else:
            if self.thread_running:
                QMessageBox.information(self,'提示','后台正在自动归档，请稍后再操作')
                event.ignore()
                self.expanded = True
                return       
            if self.file_filter_folders_list.count() > 0:
                self.refresh()
                self.archive_auarantee()
                self.auto_archiving()
                if self.psd_found:
                    self.dialog()
                    self.psd_found = False
                self.close_folder_windows()
            # # 保存窗口大小
            # self.settings.setValue('window_size', self.size())
            # 在关闭窗口之前等待线程完成
            self.thread.wait()
            event.accept()
            logging.info("程序关闭")
            logging.info("----------------------------------------------------------------")
            # 调用基类的 closeEvent 方法以关闭窗口
            super().closeEvent(event)

#设置全局字体大小
def set_global_font_size():
    app = QApplication.instance()
    if app is not None:
        font = QFont("Microsoft YaHei")
        font.setPointSize(9)
        app.setFont(font)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    set_global_font_size()
    folder_filter = ImgProcess()
    folder_filter.show()
    sys.exit(app.exec_())