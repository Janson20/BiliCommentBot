"""
B站评论机器人 - 一键启动器
为不会使用电脑的人设计，自动完成环境配置和启动
"""
import os
import sys
import subprocess
import urllib.request
import zipfile
import shutil
import time
import json
from pathlib import Path

# 项目配置
PROJECT_REPO = "https://github.com/Janson20/BiliCommentBot.git"
PROJECT_NAME = "BiliCommentBot"
# 获取exe所在目录作为安装目录
if getattr(sys, 'frozen', False):
    # 如果是打包后的exe
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTALL_DIR = os.path.join(BASE_DIR, PROJECT_NAME)
PYTHON_VERSION = "3.11.9"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"


def print_step(step_num, total_steps, message):
    """打印步骤信息"""
    print(f"\n{'='*50}")
    print(f"步骤 {step_num}/{total_steps}: {message}")
    print('='*50)


def run_command(cmd, cwd=None, check=True, shell=True):
    """运行命令并返回结果"""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, shell=shell,
            capture_output=True, text=True, check=check
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.CalledProcessError as e:
        return False, e.stdout or "", e.stderr or ""
    except Exception as e:
        return False, "", str(e)


def check_python_installed():
    """检查Python是否已安装"""
    print("检查Python安装状态...")
    try:
        result = subprocess.run(
            ["python", "--version"],
            capture_output=True, text=True
        )
        version = result.stdout.strip()
        print(f"✓ 已安装: {version}")
        
        # 检查pip
        result = subprocess.run(
            ["pip", "--version"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"✓ pip已安装")
            return True
        else:
            print("⚠ pip未安装")
            return False
    except FileNotFoundError:
        print("✗ Python未安装")
        return False


def download_python():
    """下载并安装Python"""
    print_step(1, 4, "下载并安装Python")
    
    python_dir = os.path.join(os.path.expanduser("~"), "Python311")
    
    if os.path.exists(python_dir):
        print(f"Python目录已存在: {python_dir}")
        python_exe = os.path.join(python_dir, "python.exe")
        if os.path.exists(python_exe):
            print("✓ Python已安装")
            return python_dir
    
    print(f"正在下载Python {PYTHON_VERSION}...")
    print("（这可能需要几分钟，请耐心等待...）")
    
    # 创建临时下载目录
    temp_dir = os.path.join(os.path.expanduser("~"), "python_download")
    os.makedirs(temp_dir, exist_ok=True)
    
    zip_path = os.path.join(temp_dir, "python.zip")
    
    try:
        # 下载Python
        urllib.request.urlretrieve(PYTHON_URL, zip_path)
        print("✓ 下载完成，正在解压...")
        
        # 解压到目标目录
        os.makedirs(python_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(python_dir)
        
        print("✓ Python解压完成")
        
        # 添加Python到PATH（当前会话）
        os.environ["PATH"] = python_dir + os.pathsep + os.environ.get("PATH", "")
        
        # 下载get-pip用于安装pip
        print("正在安装pip...")
        get_pip_url = "https://bootstrap.pypa.io/get-pip.py"
        get_pip_path = os.path.join(temp_dir, "get-pip.py")
        urllib.request.urlretrieve(get_pip_url, get_pip_path)
        
        python_exe = os.path.join(python_dir, "python.exe")
        subprocess.run([python_exe, get_pip_path], check=True)
        
        print("✓ pip安装完成")
        
        # 清理临时文件
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        return python_dir
        
    except Exception as e:
        print(f"✗ 安装Python失败: {e}")
        print("请手动下载Python: https://www.python.org/downloads/")
        return None


def get_python_path():
    """获取Python路径"""
    # 优先使用系统Python
    try:
        subprocess.run(["python", "--version"], capture_output=True, check=True)
        return "python"
    except:
        pass
    
    # 检查自定义安装目录
    python_dir = os.path.join(os.path.expanduser("~"), "Python311")
    python_exe = os.path.join(python_dir, "python.exe")
    if os.path.exists(python_exe):
        return python_exe
    
    return "python"


def clone_or_update_project():
    """克隆或更新项目"""
    print_step(2, 4, "获取项目文件")
    
    python = get_python_path()
    
    if os.path.exists(INSTALL_DIR):
        print(f"项目目录已存在: {INSTALL_DIR}")
        
        # 检查是否是git仓库
        git_dir = os.path.join(INSTALL_DIR, ".git")
        if os.path.exists(git_dir):
            print("正在检查项目更新...")
            
            # 获取远程更新
            success, stdout, stderr = run_command(
                f'"{python}" -c "import subprocess; subprocess.run([\'git\', \'fetch\'], cwd=r\'{INSTALL_DIR}\'])"',
                check=False
            )
            
            # 检查是否有更新
            success, stdout, stderr = run_command(
                f'"{python}" -c "import subprocess; result = subprocess.run([\'git\', \'rev-list\', \'HEAD..origin/main\', \'--count\'], cwd=r\'{INSTALL_DIR}\', capture_output=True, text=True); print(result.stdout.strip())"',
                check=False
            )
            
            update_count = stdout.strip() if stdout else "0"
            
            if update_count.isdigit() and int(update_count) > 0:
                print(f"发现 {update_count} 个更新，正在更新...")
                success, _, _ = run_command(
                    f'"{python}" -c "import subprocess; subprocess.run([\'git\', \'pull\', \'origin\', \'main\'], cwd=r\'{INSTALL_DIR}\'])"',
                    check=False
                )
                if success:
                    print("✓ 项目更新完成")
                else:
                    print("⚠ 更新失败，将使用现有版本")
            else:
                print("✓ 项目已是最新版本")
        else:
            print("⚠ 目录不是git仓库，将重新克隆...")
            shutil.rmtree(INSTALL_DIR, ignore_errors=True)
            return clone_or_update_project()
    else:
        print(f"正在克隆项目...")
        print(f"项目地址: {PROJECT_REPO}")
        print("（这可能需要几分钟，请耐心等待...）")
        
        # 检查git是否安装
        try:
            subprocess.run(["git", "--version"], capture_output=True, check=True)
        except:
            print("✗ Git未安装")
            print("请先安装Git: https://git-scm.com/download/win")
            # 尝试下载便携版Git
            print("尝试使用Python下载项目...")
            success, _, _ = run_command(
                f'"{python}" -c "import subprocess; subprocess.run([\'pip\', \'install\', \'gitpython\'])"',
                check=False
            )
            
            if success:
                try:
                    from git import Repo
                    Repo.clone_from(PROJECT_REPO, INSTALL_DIR)
                    print("✓ 项目克隆完成")
                    return True
                except Exception as e:
                    print(f"✗ 使用Python克隆失败: {e}")
                    return False
            return False
        
        try:
            subprocess.run(
                ["git", "clone", PROJECT_REPO, INSTALL_DIR],
                capture_output=True, text=True, check=True
            )
            print("✓ 项目克隆完成")
        except Exception as e:
            print(f"✗ 克隆失败: {e}")
            return False
    
    return True


def install_dependencies():
    """安装项目依赖"""
    print_step(3, 4, "安装项目依赖")
    
    python = get_python_path()
    
    requirements_file = os.path.join(INSTALL_DIR, "requirements.txt")
    
    if not os.path.exists(requirements_file):
        print("✗ requirements.txt 不存在")
        return False
    
    print("正在安装依赖包...")
    print("（这可能需要几分钟，请耐心等待...）")
    
    success, stdout, stderr = run_command(
        f'"{python}" -m pip install -r "{requirements_file}"',
        check=False
    )
    
    if success:
        print("✓ 依赖安装完成")
        return True
    else:
        print(f"⚠ 安装依赖时出现问题: {stderr}")
        # 尝试分别安装
        print("尝试逐个安装依赖...")
        packages = ["requests", "tomli_w", "pyyaml"]
        for package in packages:
            run_command(f'"{python}" -m pip install {package}', check=False)
        return True


def start_bot():
    """启动机器人"""
    print_step(4, 4, "启动B站评论机器人")
    
    python = get_python_path()
    main_file = os.path.join(INSTALL_DIR, "main.py")
    
    if not os.path.exists(main_file):
        print("✗ main.py 不存在")
        return False
    
    print("\n" + "="*50)
    print("正在启动机器人...")
    print("="*50 + "\n")
    
    # 切换到项目目录并启动
    try:
        os.chdir(INSTALL_DIR)
        subprocess.run([python, "main.py"])
        return True
    except KeyboardInterrupt:
        print("\n\n程序已停止")
        return True
    except Exception as e:
        print(f"\n✗ 启动失败: {e}")
        return False


def check_and_configure():
    """检查并配置配置文件"""
    config_file = os.path.join(INSTALL_DIR, "config.toml")
    example_config = os.path.join(INSTALL_DIR, "config.example.toml")
    gui_file = os.path.join(INSTALL_DIR, "config_gui.py")
    
    if not os.path.exists(config_file):
        if os.path.exists(example_config):
            shutil.copy(example_config, config_file)
            print("✓ 已创建配置文件 config.toml")
    
    # 检查配置是否已填写
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # 简单检查是否还是示例配置
                if '你的B站Cookie' in content or 'your-bili-cookie' in content.lower():
                    print("\n" + "="*50)
                    print("请先配置您的账号信息！")
                    print("="*50)
                    print("\n请选择配置方式:")
                    print("  1. 运行图形界面配置工具 (推荐)")
                    print("  2. 手动编辑配置文件")
                    print("  3. 退出")
                    print(f"\n配置文件路径: {config_file}")
                    
                    while True:
                        choice = input("\n请输入选项 (1/2/3): ").strip()
                        
                        if choice == '1':
                            # 检查GUI文件是否存在
                            if os.path.exists(gui_file):
                                print("\n正在启动图形界面配置工具...")
                                python = get_python_path()
                                try:
                                    os.chdir(INSTALL_DIR)
                                    subprocess.run([python, "config_gui.py"])
                                    # 重新检查配置
                                    with open(config_file, 'r', encoding='utf-8') as f:
                                        content = f.read()
                                        if '你的B站Cookie' not in content and 'your-bili-cookie' not in content.lower():
                                            print("✓ 配置完成！")
                                            return True
                                        else:
                                            print("\n配置文件尚未填写完整，是否继续？")
                                except Exception as e:
                                    print(f"启动GUI失败: {e}")
                                    print("请手动编辑配置文件")
                                    input("\n按回车键打开配置文件目录...")
                                    subprocess.run(f'explorer /select,"{config_file}"', shell=True)
                            else:
                                print("⚠ 图形界面文件不存在，将使用手动配置")
                                choice = '2'
                        
                        if choice == '2':
                            print("\n请编辑配置文件填写以下信息:")
                            print("  1. B站Cookie (必填)")
                            print("  2. DeepSeek API密钥 (必填)")
                            print("  3. B站用户ID (必填)")
                            input("\n按回车键打开配置文件目录...")
                            subprocess.run(f'explorer /select,"{config_file}"', shell=True)
                            print("\n编辑完成后，请重新运行本程序")
                            return False
                        
                        if choice == '3':
                            return False
                        
                        print("请输入正确的选项 (1/2/3)")
        except Exception as e:
            print(f"⚠ 读取配置文件失败: {e}")
    
    return True


def main():
    """主函数"""
    print("\n" + "="*50)
    print("  B站评论机器人 - 一键启动器")
    print("="*50)
    print(f"\n项目目录: {INSTALL_DIR}")
    
    # 步骤1: 检查/安装Python
    if not check_python_installed():
        python_dir = download_python()
        if not python_dir:
            print("\n无法自动安装Python，请手动安装后重试")
            input("\n按回车键退出...")
            sys.exit(1)
    
    # 步骤2: 克隆/更新项目
    if not clone_or_update_project():
        print("\n获取项目失败")
        input("\n按回车键退出...")
        sys.exit(1)
    
    # 步骤3: 安装依赖
    if not install_dependencies():
        print("\n安装依赖失败")
        input("\n按回车键退出...")
        sys.exit(1)
    
    # 检查并配置配置文件
    if not check_and_configure():
        input("\n按回车键退出...")
        sys.exit(0)
    
    # 步骤4: 启动机器人
    start_bot()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n操作已取消")
        input("\n按回车键退出...")
    except Exception as e:
        print(f"\n\n发生错误: {e}")
        input("\n按回车键退出...")
