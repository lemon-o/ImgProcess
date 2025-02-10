import os
import sys
import time
import re
import urllib.parse
import pygetwindow as gw
from PyQt5.QtWidgets import QLabel, QMenu, QMessageBox, QPushButton,  QVBoxLayout, QFileDialog, QListWidget, QListWidgetItem, QLineEdit
from PyQt5.QtWidgets import QComboBox, QFrame, QStackedWidget, QProgressBar, QApplication, QWidget, QDesktopWidget,QHBoxLayout, QShortcut
from PyQt5.QtGui import QBrush, QFont, QIcon,QColor,QDesktopServices, QPainter, QKeySequence, QRegExpValidator
from PyQt5.QtCore import QCoreApplication, QPropertyAnimation, QRect, QSettings,Qt, QUrl, QTimer, QThread, pyqtSignal, QRegExp
from PIL import Image
from psd_tools import PSDImage

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
                            # 发送子进度更新信号
                            jpg_files += 1
                            if total_psd_files != 0:
                                total_progress = (jpg_files / total_psd_files) * 100
                                self.progress_update.emit(int(total_progress))
                            else:
                                self.progress_update.emit(100)
                            # 处理事件队列，确保及时更新UI
                            QCoreApplication.processEvents()
                        except Exception as e:
                            full_path = os.path.join(self.file_path_right, file_name)
                            print(f"无法处理文件: {file_name} ({full_path})")
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

        # 当线程耗时任务完成时，直接发送总进度为100%
        self.progress_update.emit(100)
        time.sleep(0.5)
        self.start1 = False                 
        self.finished_signal.emit()

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
        #设置默认文件类型
        last_input_left = self.settings.value("last_input_left", "", str)
        self.filter_combo.setEditText(last_input_left) 
        self.filter_combo.lineEdit().textChanged.connect(lambda text: self.settings.setValue("last_input_left", text))
        #设置默认排序方式
        last_selected_right = self.settings.value("last_selected_right", 0, int)
        self.sort_combo.setCurrentIndex(last_selected_right) 
        self.sort_combo.currentIndexChanged.connect(lambda index: self.settings.setValue("last_selected_right", index) )
        #设置默认窗口大小
        # self.load_window_size()       
        #初始化变量
        self.parent_dir = None
        self.dir_path = None
        self.file_type = ""
        self.new_position = None
        self.animation = None  # 初始化动画属性
        self.psd_found = False
        self.thread_running = False
        self.is_dragging = False
        self.expanded = None
        self.double_clicked = False
        self.monitor_top_border = 0
        self.animation_finished = False
        self.selected_page1 = None
        self.selected_page2 = None
        self.selected_page3 = None
        # 初始化列表
        self.clicked_folder_path = []  
        self.target_folder_titles = []
        self.clicked_folder_names = []
        self.renamed_folders = []

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
        hbox_main.addSpacing(self.margin) # 添加（）像素的空白占位 
        vbox_dock_widget = QWidget() # 创建一个新容器
        new_width1 = int((5 / 90) * self.fixed_width) # 设置 容器 的宽度
        vbox_dock_widget.setFixedWidth(new_width1)
        vbox_dock = QVBoxLayout(vbox_dock_widget)
        left_margin = int(((5 / 90) * self.fixed_width - self.button_width_dock) // 2)
        vbox_dock.setContentsMargins(left_margin , 0, 0, 0)  # 调整边距
        vbox_dock.setSpacing(0)  # 设置控件之间的间距为0
        vbox_dock.addWidget(self.dock_button_1)  
        vbox_dock.addSpacing(5)
        vbox_dock.addWidget(self.dock_button_2) 
        vbox_dock.addSpacing(5)
        vbox_dock.addWidget(self.dock_button_3) 
        vbox_dock.addSpacing(5)
        vbox_dock.addStretch(1)  
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
    def setup_button(self, button, index, style):
        button.setFixedSize(self.button_width_dock, self.button_height_dock)
        button.setStyleSheet(style)
        button.setCheckable(True)
        button.clicked.connect(lambda: self.set_button_selected(index))
        button.clicked.connect(lambda: self.stackedWidget.setCurrentIndex(index)) # 连接切换页面槽函数
    def set_button_selected(self, index):
        for btn in self.findChildren(QPushButton):
            btn.setChecked(False)
        sender_button = self.sender()
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
            QMessageBox.information(self,'提示','请输入要筛选的文件类型\n例如：“.txt”')
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
                    sub_dir_path = os.path.join(root, dir_name)
                    # 如果该子文件夹是目录A的一级子文件夹，则添加到控件中
                    if os.path.dirname(sub_dir_path) == self.dir_path:
                        # 检查子文件夹及其所有子文件夹中是否存在.file_type文件
                        file_type_exist = False
                        for sub_root, sub_dirs, sub_files in os.walk(sub_dir_path):
                            if any(f.endswith(file_type) for f in sub_files):
                                file_type_exist = True
                                break

                        if not file_type_exist:
                            sub_dir_files = os.listdir(os.path.join(self.parent_dir, sub_dir_path))
                            if any(file.lower().endswith(('.jpg', '.jpeg', '.png', '.raw', '.bmp', '.gif')) for file in sub_dir_files):
                                try:
                                    os.makedirs(os.path.join(self.parent_dir, sub_dir_path, "已修", "psd"))
                                    os.makedirs(os.path.join(self.parent_dir, sub_dir_path, "已修", "其他尺寸"))
                                except:
                                    pass
                            if os.path.exists(os.path.join(self.parent_dir, sub_dir_path, "待修")):
                                try:
                                    os.makedirs(os.path.join(self.parent_dir, sub_dir_path, "已修", "psd"))
                                    os.makedirs(os.path.join(self.parent_dir, sub_dir_path, "已修", "其他尺寸"))
                                except:
                                    pass
                                wait_repaire_files = os.listdir(os.path.join(self.parent_dir, sub_dir_path, "待修"))
                                if not any(file.lower().endswith(('.jpg', '.jpeg', '.png', '.raw', '.bmp', '.gif')) for file in wait_repaire_files):
                                    dir_name = "未选图 " + dir_name
                            elif os.path.exists(os.path.join(self.parent_dir, sub_dir_path)):
                                wait_repaire_files = os.listdir(os.path.join(self.parent_dir, sub_dir_path))
                                for file in wait_repaire_files:
                                    if file.lower().endswith(('.jpg', '.jpeg', '.png', '.raw', '.bmp', '.gif')):
                                        file_path = os.path.join(self.parent_dir, sub_dir_path, file)
                                        with Image.open(file_path) as img:
                                            if img.size[0] > 1800:
                                                dir_name = "未选图 " + dir_name
                                                break
                            item = QListWidgetItem()
                            # 给item设置数据，包括名称和HTML链接
                            item.setData(Qt.DisplayRole, dir_name)
                            item.setData(Qt.TextColorRole, QColor("#2F857E")) # 设置链接的颜色
                            item.setData(Qt.TextAlignmentRole, Qt.AlignLeft)   # 设置链接的对齐方式
                            item.setData(Qt.UserRole, os.path.join(self.parent_dir, sub_dir_path))  
                            self.file_left_list.addItem(item)
                            left_count += 1

                        if file_type_exist:
                            item = QListWidgetItem()
                            # 给item设置数据，包括名称和HTML链接
                            item.setData(Qt.DisplayRole, dir_name)
                            item.setData(Qt.TextColorRole, QColor("#39569E")) # 设置链接的颜色
                            item.setData(Qt.TextAlignmentRole, Qt.AlignLeft)   # 设置链接的对齐方式
                            item.setData(Qt.UserRole, os.path.join(self.parent_dir, sub_dir_path))
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
        if self.thread_running:
            QMessageBox.information(self,'提示','后台正在运行自动归档，请稍后再操作')
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